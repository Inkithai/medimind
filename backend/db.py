"""
Supabase (Postgres) persistence (Phase 4)
=========================================
Replaces the local patient_docs_*.json / patient_report_*.json files used
by the CLI (see medical_extractor.py) with per-user, access-controlled
storage in Supabase Postgres, for the HTTP API only. Every read/write is
scoped by user_id — there is no query in this module that can return
another user's data.

All access is server-side through the Supabase REST API (supabase-py)
using the project's service-role key, which bypasses RLS. RLS is enabled
on both tables with NO policies, so the browser-facing anon key can read
or write nothing — only this backend (holding the service-role key) can
touch the data.

Two tables — create them once by running `supabase_schema.sql` in the
Supabase SQL editor (Dashboard -> SQL Editor):

    documents           one row per extracted page/file, includes the
                        Cloudinary document_url — no raw file bytes, no
                        LLM request/response payloads, no access tokens.
    patient_snapshots   one row per user: the last-built patient_timeline
                        + cross_check_report + lab_trends (mirrors what
                        the CLI writes to patient_report_<name>.json).

Env:
    SUPABASE_URL                e.g. https://abcdefgh.supabase.co
    SUPABASE_SERVICE_ROLE_KEY   Settings -> API -> service_role (secret)
"""

import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from supabase import Client, create_client

_client: Optional[Client] = None


def _get_client() -> Client:
    global _client
    if _client is None:
        url = os.environ.get("SUPABASE_URL")
        key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_ANON_KEY")
        if not url or not key:
            raise RuntimeError(
                "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set — "
                "copy .env.example to .env and add your Supabase project "
                "URL and service-role key (Dashboard -> Settings -> API)."
            )
        _client = create_client(url, key)
    return _client


def _documents():
    return _get_client().table("documents")


def _snapshots():
    return _get_client().table("patient_snapshots")


def ensure_indexes() -> None:
    """Called once at API startup. Kept for compatibility with the old
    MongoDB version — with Supabase the schema (tables, indexes, RLS) is
    created once via `supabase_schema.sql` in the SQL editor, so this is
    a no-op. `user_id` is indexed on documents and is the primary key of
    patient_snapshots, which is the access-control boundary for both."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_documents(user_id: str) -> List[Dict[str, Any]]:
    """Loads every previously-saved document for this user, oldest first —
    used to merge with newly-uploaded documents before rebuilding the
    timeline. Returns [] if this user has never uploaded anything. The
    extracted document body lives in the `data` JSONB column; user_id and
    uploaded_at are merged back in so callers see the same flat shape the
    old MongoDB records had."""
    response = (
        _documents()
        .select("user_id, uploaded_at, data")
        .eq("user_id", user_id)
        # id breaks ties between documents uploaded in the same batch
        # (they share one uploaded_at timestamp), keeping merge order stable.
        .order("uploaded_at, id")
        .execute()
    )
    return [
        {**row["data"], "user_id": row["user_id"], "uploaded_at": row["uploaded_at"]}
        for row in (response.data or [])
    ]


def insert_documents(user_id: str, docs: List[Dict[str, Any]]) -> None:
    """Appends newly-extracted documents for this user (append-only — never
    rewrites or touches this user's existing documents). No-op on an empty
    list."""
    if not docs:
        return
    now = _now_iso()
    rows = [{"user_id": user_id, "uploaded_at": now, "data": doc} for doc in docs]
    _documents().insert(rows).execute()


def load_patient_snapshot(user_id: str) -> Optional[Dict[str, Any]]:
    """Loads the {"patient_timeline", "cross_check_report"} snapshot last
    saved for this user, or None if they've never been processed."""
    response = (
        _snapshots()
        .select("user_id, patient_timeline, cross_check_report, lab_trends, updated_at")
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    rows = response.data or []
    if not rows:
        return None
    snapshot = rows[0]
    # Match the old MongoDB shape: drop lab_trends when it was never saved,
    # so callers' `"lab_trends" in snapshot` checks behave the same way.
    if snapshot.get("lab_trends") is None:
        snapshot.pop("lab_trends", None)
    return snapshot


def save_patient_snapshot(
    user_id: str,
    timeline: Dict[str, Any],
    cross_check: Dict[str, Any],
    lab_trends: Optional[Dict[str, Any]] = None,
) -> None:
    """Upserts the merged timeline + cross-check report (+ lab trends, if
    computed) for this user."""
    fields: Dict[str, Any] = {
        "user_id": user_id,
        "patient_timeline": timeline,
        "cross_check_report": cross_check,
        "updated_at": _now_iso(),
    }
    if lab_trends is not None:
        fields["lab_trends"] = lab_trends
    _snapshots().upsert(fields, on_conflict="user_id").execute()
