"""
Background Jobs for async uploads
=========================================================
Fixes free-tier 429 timeouts by returning 202 immediately and doing
the 4 LLM calls (extract × pages, cross-check) in the background.

POST /api/v1/documents?async=true or Prefer: respond-async or
USE_BACKGROUND_JOBS=true → 202 {job_id, status}
GET  /api/v1/jobs/{job_id} → {job_id, status, progress, result, error}
GET  /api/v1/jobs           → list user's jobs (recent 20)

Storage: in-memory dict (fast, no extra deps) with optional Supabase
`jobs` table persistence if USE_SUPABASE_JOBS=true and table exists.
Jobs are per-user (user_id check) and expire after 1 hour (in-memory).

Progress steps mirror ProcessingStatus: upload → reading → extracting
→ organizing → safety → indexing → ready / failed
"""

import os
import uuid
import time
import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

logger = logging.getLogger("jobs")

USE_SUPABASE_JOBS = os.environ.get("USE_SUPABASE_JOBS", "").lower() in ("true", "1", "yes")
JOB_TTL_HOURS = int(os.environ.get("JOB_TTL_HOURS", "1"))

# In-memory store: job_id -> job dict
_JOBS: Dict[str, Dict[str, Any]] = {}

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def _is_expired(job: Dict[str, Any]) -> bool:
    try:
        created = datetime.fromisoformat(job.get("created_at", ""))
        return datetime.now(timezone.utc) - created > timedelta(hours=JOB_TTL_HOURS)
    except Exception:
        return False

def _supabase_persist(job: Dict[str, Any]):
    if not USE_SUPABASE_JOBS:
        return
    try:
        from db import _get_client
        client = _get_client()
        # Upsert to jobs table (ignore if table missing)
        client.table("jobs").upsert({
            "job_id": job["job_id"],
            "user_id": job["user_id"],
            "status": job["status"],
            "progress": job.get("progress"),
            "result": job.get("result"),
            "error": job.get("error"),
            "updated_at": _now_iso(),
        }, on_conflict="job_id").execute()
    except Exception as e:
        # Table may not exist yet (old deployment). Log but don't fail job.
        if "PGRST205" not in str(e) and "jobs" not in str(e).lower():
            logger.warning("Supabase jobs persist failed: %s", e)

def _supabase_load(job_id: str) -> Optional[Dict[str, Any]]:
    if not USE_SUPABASE_JOBS:
        return None
    try:
        from db import _get_client
        client = _get_client()
        res = client.table("jobs").select("*").eq("job_id", job_id).limit(1).execute()
        rows = res.data or []
        return rows[0] if rows else None
    except Exception:
        return None

def create_job(user_id: str, file_names: List[str]) -> Dict[str, Any]:
    job_id = uuid.uuid4().hex
    job: Dict[str, Any] = {
        "job_id": job_id,
        "user_id": user_id,
        "status": "pending",  # pending | processing | completed | failed
        "progress": {"step": "upload", "message": f"Queued {len(file_names)} file(s)", "file_names": file_names},
        "result": None,
        "error": None,
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
    }
    _JOBS[job_id] = job
    _supabase_persist(job)
    # Cleanup expired
    _cleanup()
    logger.info("Job created %s for user %s files=%s", job_id, user_id, file_names)
    return job

def get_job(job_id: str, user_id: str) -> Optional[Dict[str, Any]]:
    # Check in-memory first
    job = _JOBS.get(job_id)
    if job and job.get("user_id") == user_id and not _is_expired(job):
        return job
    # Fallback to Supabase
    sj = _supabase_load(job_id)
    if sj and sj.get("user_id") == user_id:
        # Normalize shape
        return {
            "job_id": sj["job_id"],
            "user_id": sj["user_id"],
            "status": sj["status"],
            "progress": sj.get("progress") or {},
            "result": sj.get("result"),
            "error": sj.get("error"),
            "created_at": sj.get("created_at"),
            "updated_at": sj.get("updated_at"),
        }
    return None

def list_jobs(user_id: str, limit: int = 20) -> List[Dict[str, Any]]:
    # In-memory
    jobs = [j for j in _JOBS.values() if j.get("user_id") == user_id and not _is_expired(j)]
    jobs.sort(key=lambda j: j.get("created_at", ""), reverse=True)
    if len(jobs) >= limit:
        return jobs[:limit]
    # Supplement from Supabase if needed
    if USE_SUPABASE_JOBS:
        try:
            from db import _get_client
            client = _get_client()
            res = client.table("jobs").select("*").eq("user_id", user_id).order("created_at", desc=True).limit(limit).execute()
            for r in (res.data or []):
                if r["job_id"] not in _JOBS:
                    jobs.append({
                        "job_id": r["job_id"],
                        "user_id": r["user_id"],
                        "status": r["status"],
                        "progress": r.get("progress") or {},
                        "result": r.get("result"),
                        "error": r.get("error"),
                        "created_at": r.get("created_at"),
                        "updated_at": r.get("updated_at"),
                    })
        except Exception:
            pass
    jobs.sort(key=lambda j: j.get("created_at", ""), reverse=True)
    return jobs[:limit]

def update_job(job_id: str, status: Optional[str] = None, progress: Optional[Dict[str, Any]] = None, result: Optional[Dict[str, Any]] = None, error: Optional[str] = None):
    job = _JOBS.get(job_id)
    if not job:
        # Try Supabase load then create in-memory
        sj = _supabase_load(job_id)
        if sj:
            job = {
                "job_id": sj["job_id"],
                "user_id": sj["user_id"],
                "status": sj["status"],
                "progress": sj.get("progress") or {},
                "result": sj.get("result"),
                "error": sj.get("error"),
                "created_at": sj.get("created_at"),
                "updated_at": sj.get("updated_at"),
            }
            _JOBS[job_id] = job
        else:
            logger.warning("update_job missing %s", job_id)
            return
    if status:
        job["status"] = status
    if progress is not None:
        job["progress"] = progress
    if result is not None:
        job["result"] = result
    if error is not None:
        job["error"] = error
    job["updated_at"] = _now_iso()
    _supabase_persist(job)
    logger.info("Job %s -> %s progress=%s", job_id, job["status"], job.get("progress", {}).get("step"))

def _cleanup():
    # Remove expired in-memory jobs
    now = datetime.now(timezone.utc)
    expired = []
    for jid, j in _JOBS.items():
        try:
            created = datetime.fromisoformat(j.get("created_at", ""))
            if now - created > timedelta(hours=JOB_TTL_HOURS):
                expired.append(jid)
        except Exception:
            pass
    for jid in expired:
        _JOBS.pop(jid, None)
    if expired:
        logger.info("Cleaned %d expired jobs", len(expired))
