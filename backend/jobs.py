"""
Background jobs and per-document progress for async uploads.

POST /api/v1/documents?async=true -> 202 {job_id, status}
GET  /api/v1/jobs/{job_id}        -> parent job + independent file states

A batch has two levels of progress:
  * ``progress.files``: each uploaded document moves through its own queue,
    reading, extraction, secure-save, and terminal state.
  * ``progress.step``: batch-wide finalization after readable files are ready
    (organizing -> safety -> indexing -> ready / failed).

Storage is an in-memory dict with optional Supabase persistence. Updates are
protected by a lock because document extraction runs in a bounded thread pool.
"""

from __future__ import annotations

import copy
import logging
import os
import threading
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

logger = logging.getLogger("jobs")

USE_SUPABASE_JOBS = os.environ.get("USE_SUPABASE_JOBS", "").lower() in ("true", "1", "yes")
JOB_TTL_HOURS = int(os.environ.get("JOB_TTL_HOURS", "1"))

# In-memory store: job_id -> job dict. File workers update this concurrently.
_JOBS: Dict[str, Dict[str, Any]] = {}
_JOBS_LOCK = threading.RLock()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _copy_job(job: Dict[str, Any]) -> Dict[str, Any]:
    # Never expose the live nested progress dict to a polling request.
    return copy.deepcopy(job)


def _is_expired(job: Dict[str, Any]) -> bool:
    try:
        created = datetime.fromisoformat(job.get("created_at", ""))
        return datetime.now(timezone.utc) - created > timedelta(hours=JOB_TTL_HOURS)
    except Exception:
        return False


def _supabase_persist(job: Dict[str, Any]) -> None:
    if not USE_SUPABASE_JOBS:
        return
    try:
        from db import _get_client

        client = _get_client()
        # Machine-readable error metadata is nested in progress, so this stays
        # compatible with existing jobs tables (no migration/new columns).
        client.table("jobs").upsert(
            {
                "job_id": job["job_id"],
                "user_id": job["user_id"],
                "status": job["status"],
                "progress": job.get("progress"),
                "result": job.get("result"),
                "error": job.get("error"),
                "updated_at": _now_iso(),
            },
            on_conflict="job_id",
        ).execute()
    except Exception as exc:
        # Table may not exist yet (old deployment). Log but don't fail a job.
        if "PGRST205" not in str(exc) and "jobs" not in str(exc).lower():
            logger.warning("Supabase jobs persist failed: %s", exc)


def _supabase_load(job_id: str) -> Optional[Dict[str, Any]]:
    if not USE_SUPABASE_JOBS:
        return None
    try:
        from db import _get_client

        client = _get_client()
        result = client.table("jobs").select("*").eq("job_id", job_id).limit(1).execute()
        rows = result.data or []
        return rows[0] if rows else None
    except Exception:
        return None


def _normalise_stored_job(stored: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "job_id": stored["job_id"],
        "user_id": stored["user_id"],
        "status": stored["status"],
        "progress": stored.get("progress") or {},
        "result": stored.get("result"),
        "error": stored.get("error"),
        "created_at": stored.get("created_at"),
        "updated_at": stored.get("updated_at"),
    }


def create_job(user_id: str, file_names: List[str]) -> Dict[str, Any]:
    job_id = uuid.uuid4().hex
    now = _now_iso()
    file_progress = [
        {
            "id": f"file-{index}",
            "index": index,
            "name": name,
            "status": "queued",  # queued | processing | completed | failed
            "step": "upload",    # upload | reading | extracting | saving | ready | failed
            "message": "Uploaded and waiting for a processing slot",
            "error": None,
            "error_code": None,
            "retryable": None,
            "retry_after_seconds": None,
            "updated_at": now,
        }
        for index, name in enumerate(file_names, start=1)
    ]
    job: Dict[str, Any] = {
        "job_id": job_id,
        "user_id": user_id,
        "status": "pending",  # pending | processing | completed | failed
        "progress": {
            "step": "upload",
            "message": f"Received {len(file_names)} file(s)",
            "file_names": list(file_names),  # compatibility with older clients
            "total_files": len(file_names),
            "processed_files": 0,
            "successful_files": 0,
            "failed_files": 0,
            "files": file_progress,
        },
        "result": None,
        "error": None,
        "created_at": now,
        "updated_at": now,
    }
    with _JOBS_LOCK:
        _JOBS[job_id] = job
        snapshot = _copy_job(job)
    _supabase_persist(snapshot)
    _cleanup()
    logger.info("Job created %s for user %s files=%s", job_id, user_id, file_names)
    return snapshot


def get_job(job_id: str, user_id: str) -> Optional[Dict[str, Any]]:
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
        if job and job.get("user_id") == user_id and not _is_expired(job):
            return _copy_job(job)

    stored = _supabase_load(job_id)
    if stored and stored.get("user_id") == user_id:
        normalized = _normalise_stored_job(stored)
        with _JOBS_LOCK:
            _JOBS[job_id] = normalized
        return _copy_job(normalized)
    return None


def delete_user_jobs(user_id: str) -> int:
    """Forget every in-memory upload job owned by a deleted workspace."""
    with _JOBS_LOCK:
        ids = [job_id for job_id, job in _JOBS.items() if job.get("user_id") == user_id]
        for job_id in ids:
            _JOBS.pop(job_id, None)
    return len(ids)


def list_jobs(user_id: str, limit: int = 20) -> List[Dict[str, Any]]:
    with _JOBS_LOCK:
        values = [
            _copy_job(job)
            for job in _JOBS.values()
            if job.get("user_id") == user_id and not _is_expired(job)
        ]
    values.sort(key=lambda item: item.get("created_at", ""), reverse=True)
    if len(values) >= limit:
        return values[:limit]

    if USE_SUPABASE_JOBS:
        try:
            from db import _get_client

            client = _get_client()
            result = (
                client.table("jobs")
                .select("*")
                .eq("user_id", user_id)
                .order("created_at", desc=True)
                .limit(limit)
                .execute()
            )
            known_ids = {item["job_id"] for item in values}
            for row in result.data or []:
                if row["job_id"] not in known_ids:
                    values.append(_normalise_stored_job(row))
        except Exception:
            pass
    values.sort(key=lambda item: item.get("created_at", ""), reverse=True)
    return values[:limit]


def update_job(
    job_id: str,
    status: Optional[str] = None,
    progress: Optional[Dict[str, Any]] = None,
    result: Optional[Dict[str, Any]] = None,
    error: Optional[str] = None,
) -> None:
    """Update parent state while preserving nested per-file progress.

    ``progress`` is a patch, not a replacement. This is important when the
    parent enters ``safety`` while file rows from extraction must remain
    visible to polling clients.
    """
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
    if not job:
        stored = _supabase_load(job_id)
        if not stored:
            logger.warning("update_job missing %s", job_id)
            return
        job = _normalise_stored_job(stored)
        with _JOBS_LOCK:
            _JOBS[job_id] = job

    with _JOBS_LOCK:
        job = _JOBS[job_id]
        if status:
            job["status"] = status
        if progress is not None:
            current = job.get("progress") or {}
            current.update(copy.deepcopy(progress))
            job["progress"] = current
        if result is not None:
            job["result"] = result
        if error is not None:
            job["error"] = error
        job["updated_at"] = _now_iso()
        snapshot = _copy_job(job)

    _supabase_persist(snapshot)
    logger.info(
        "Job %s -> %s progress=%s (%s/%s files processed)",
        job_id,
        snapshot["status"],
        snapshot.get("progress", {}).get("step"),
        snapshot.get("progress", {}).get("processed_files", 0),
        snapshot.get("progress", {}).get("total_files", 0),
    )


def update_file_progress(
    job_id: str,
    file_index: int,
    *,
    status: Optional[str] = None,
    step: Optional[str] = None,
    message: Optional[str] = None,
    error: Optional[str] = None,
    error_code: Optional[str] = None,
    retryable: Optional[bool] = None,
    retry_after_seconds: Optional[float] = None,
) -> None:
    """Atomically update one child document and recompute batch counters."""
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
        if not job:
            logger.warning("update_file_progress missing job %s", job_id)
            return
        progress = job.get("progress") or {}
        files = progress.get("files") or []
        target = next((item for item in files if item.get("index") == file_index), None)
        if target is None:
            logger.warning("update_file_progress missing file %s in job %s", file_index, job_id)
            return
        if status is not None:
            target["status"] = status
        if step is not None:
            target["step"] = step
        if message is not None:
            target["message"] = message
        if error is not None:
            target["error"] = error
        if error_code is not None:
            target["error_code"] = error_code
        if retryable is not None:
            target["retryable"] = retryable
        if retry_after_seconds is not None:
            target["retry_after_seconds"] = retry_after_seconds
        target["updated_at"] = _now_iso()

        successful = sum(1 for item in files if item.get("status") == "completed")
        failed = sum(1 for item in files if item.get("status") == "failed")
        progress["total_files"] = len(files)
        progress["successful_files"] = successful
        progress["failed_files"] = failed
        progress["processed_files"] = successful + failed
        job["progress"] = progress
        job["updated_at"] = _now_iso()
        snapshot = _copy_job(job)

    _supabase_persist(snapshot)
    logger.info(
        "Job %s file %s -> %s/%s (%s)",
        job_id,
        file_index,
        target.get("status"),
        target.get("step"),
        target.get("name"),
    )


def _cleanup() -> None:
    now = datetime.now(timezone.utc)
    expired: List[str] = []
    with _JOBS_LOCK:
        for job_id, job in _JOBS.items():
            try:
                created = datetime.fromisoformat(job.get("created_at", ""))
                if now - created > timedelta(hours=JOB_TTL_HOURS):
                    expired.append(job_id)
            except Exception:
                pass
        for job_id in expired:
            _JOBS.pop(job_id, None)
    if expired:
        logger.info("Cleaned %d expired jobs", len(expired))
