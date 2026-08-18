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

Core and trust tables are created idempotently by `supabase_schema.sql`:

    documents                    immutable extracted page/file JSON
    patient_snapshots            latest trusted derived views
    extraction_corrections       append-only field correction events
    record_conflicts             current unresolved/resolved conflict state
    conflict_resolution_events   append-only source-decision audit history

Original document JSON is never updated by the correction workflow. Rows
are removed only by explicit authenticated document/workspace deletion.

Env:
    SUPABASE_URL                e.g. https://abcdefgh.supabase.co
    SUPABASE_SERVICE_ROLE_KEY   Settings -> API -> service_role (secret)
"""

import os
import functools
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence

from supabase import Client, create_client

from evidence import normalize_document_evidence
from record_trust import apply_correction_events

_client: Optional[Client] = None


def _get_client() -> Client:
    global _client
    if _client is None:
        url = os.environ.get("SUPABASE_URL")
        # This must never fall back to SUPABASE_ANON_KEY. The tables use RLS
        # with no browser-facing policies, so an anon key will be denied and
        # using it would also hide a deployment configuration error.
        key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
        if (not url or not key or
                url.strip() in ("", "https://your-project-ref.supabase.co") or
                key.strip() in ("", "your-supabase-service-role-key")):
            raise RuntimeError(
                "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set. "
                "Use the secret service_role key (not the anon/publishable key) "
                "from Supabase Dashboard -> Settings -> API, then restart the API."
            )
        _client = create_client(url, key)
    return _client


def _documents():
    return _get_client().table("documents")


def _snapshots():
    return _get_client().table("patient_snapshots")


def _corrections():
    return _get_client().table("extraction_corrections")


def _conflicts():
    return _get_client().table("record_conflicts")


def _conflict_events():
    return _get_client().table("conflict_resolution_events")


def _referral_searches():
    return _get_client().table("referral_searches")


class SchemaNotInitializedError(RuntimeError):
    """Raised when the Supabase project is reachable but the app's tables
    (documents / patient_snapshots) do not exist — i.e. supabase_schema.sql
    has not been run against the project SUPABASE_URL points to (fresh
    project, or .env pointing at the wrong project)."""


# PostgREST surfaces a missing table as a 404 schema-cache miss with this
# code ("Could not find the table 'public.<name>' in the schema cache").
_MISSING_TABLE_CODE = "PGRST205"


def ensure_indexes() -> None:
    """Called once at API startup. Kept for compatibility with the old
    MongoDB version — with Supabase the schema (tables, indexes, RLS) is
    created once via `supabase_schema.sql` in the SQL editor, so this is
    a no-op. `user_id` is indexed on documents and is the primary key of
    patient_snapshots, which is the access-control boundary for both."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _translate_missing_schema(fn):
    """Turn PostgREST's cryptic PGRST205 schema-cache miss into instructions.

    Raw error ("Could not find the table 'public.patient_snapshots' in the
    schema cache") gives no hint about the actual fix; the translated error
    tells the operator exactly which setup step was missed.
    """
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            code = getattr(e, "code", None)
            if code == _MISSING_TABLE_CODE or _MISSING_TABLE_CODE in str(e):
                raise SchemaNotInitializedError(
                    "Supabase schema is not initialized (PostgREST "
                    f"{_MISSING_TABLE_CODE}): the app's tables "
                    f"(documents, patient_snapshots, corrections/conflicts, or chunks) "
                    f"do not exist in the project at SUPABASE_URL ({e}). Create or "
                    f"upgrade them by running "
                    "backend/supabase_schema.sql ONCE in that project's SQL editor "
                    "(Supabase Dashboard -> SQL Editor -> New query -> paste -> Run), "
                    "then retry. If the tables already exist, check that SUPABASE_URL "
                    "points at the right project."
                ) from e
            raise
    return wrapper


@_translate_missing_schema
def load_documents(user_id: str, include_corrections: bool = True) -> List[Dict[str, Any]]:
    """Load this user's immutable extractions, optionally replaying corrections.

    ``documents.data`` is append-only and is never rewritten.  Older rows did
    not contain ``_document_id``; for those rows the Postgres identity is
    exposed as ``db:<id>`` so they can participate in correction/audit APIs
    without a destructive backfill.
    """
    response = (
        _documents()
        .select("id, user_id, uploaded_at, data")
        .eq("user_id", user_id)
        .order("uploaded_at")
        .order("id")
        .execute()
    )
    docs = []
    for row in response.data or []:
        data = dict(row["data"] or {})
        data.setdefault("_document_id", f"db:{row['id']}")
        source = data.get("_source") if isinstance(data.get("_source"), dict) else {}
        data = normalize_document_evidence(
            data,
            default_page=int(source.get("page") or 1),
            vision=source.get("method") == "vision_ocr",
        )
        docs.append({**data, "user_id": row["user_id"], "uploaded_at": row["uploaded_at"]})
    if include_corrections and docs:
        docs = apply_correction_events(docs, load_correction_events(user_id))
    return docs


@_translate_missing_schema
def insert_documents(user_id: str, docs: List[Dict[str, Any]]) -> None:
    """Appends newly-extracted documents for this user (append-only — never
    rewrites or touches this user's existing documents). No-op on an empty
    list."""
    if not docs:
        return
    now = _now_iso()
    rows = [{"user_id": user_id, "uploaded_at": now, "data": doc} for doc in docs]
    _documents().insert(rows).execute()


@_translate_missing_schema
def load_patient_snapshot(user_id: str) -> Optional[Dict[str, Any]]:
    """Loads the {"patient_timeline", "cross_check_report"} snapshot last
    saved for this user, or None if they've never been processed."""
    try:
        response = (
            _snapshots()
            .select("user_id, patient_timeline, cross_check_report, lab_trends, derived_reports, updated_at")
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
    except Exception as e:
        # Older deployments predate the derived_reports column (PGRST204 /
        # column-missing) — retry with the legacy column list.
        if "derived_reports" not in str(e):
            raise
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
    # Flatten derived_reports back out for callers.
    derived = snapshot.pop("derived_reports", None) or {}
    if derived.get("dosage_report") is not None:
        snapshot["dosage_report"] = derived["dosage_report"]
    if derived.get("consult_triage") is not None:
        snapshot["consult_triage"] = derived["consult_triage"]
    return snapshot


@_translate_missing_schema
def save_patient_snapshot(
    user_id: str,
    timeline: Dict[str, Any],
    cross_check: Dict[str, Any],
    lab_trends: Optional[Dict[str, Any]] = None,
    dosage_report: Optional[Dict[str, Any]] = None,
    consult_triage: Optional[Dict[str, Any]] = None,
) -> None:
    """Upserts the merged timeline + cross-check report (+ lab trends,
    dosage report, and consult triage, if computed) for this user.

    dosage_report / consult_triage are written into the derived_reports
    JSONB column (added by supabase_schema.sql) so older deployments whose
    table predates the column keep working: the upsert retries without
    derived_reports if PostgREST reports the column missing."""
    fields: Dict[str, Any] = {
        "user_id": user_id,
        "patient_timeline": timeline,
        "cross_check_report": cross_check,
        "updated_at": _now_iso(),
    }
    if lab_trends is not None:
        fields["lab_trends"] = lab_trends
    derived: Dict[str, Any] = {}
    if dosage_report is not None:
        derived["dosage_report"] = dosage_report
    if consult_triage is not None:
        derived["consult_triage"] = consult_triage
    if derived:
        fields["derived_reports"] = derived
        try:
            _snapshots().upsert(fields, on_conflict="user_id").execute()
            return
        except Exception as e:
            # PGRST204 = unknown column in schema cache (table predates the
            # derived_reports migration). Fall back to the legacy shape so
            # the snapshot itself is never lost over a derived report.
            if "derived_reports" not in str(e):
                raise
            fields.pop("derived_reports", None)
    _snapshots().upsert(fields, on_conflict="user_id").execute()


@_translate_missing_schema
def replace_document_group(
    user_id: str,
    *,
    content_sha256: Optional[str],
    source_file: Optional[str],
    pages: Sequence[Dict[str, Any]],
) -> int:
    """Replaces every stored row belonging to one physical file (all pages
    of a multi-page document share its content_sha256) with freshly
    extracted pages, then inserts the new rows. Returns how many rows were
    replaced. Used by the per-document reprocess endpoint.

    Falls back to matching on the stored source filename for rows that
    predate the content-hash field. Never touches rows of other files.
    """
    response = _documents().select("id, data").eq("user_id", user_id).execute()
    matched_ids: List[Any] = []
    for row in response.data or []:
        data = row.get("data") if isinstance(row.get("data"), dict) else {}
        if content_sha256 and data.get("content_sha256") == content_sha256:
            matched_ids.append(row["id"])
        elif not content_sha256 and source_file and (data.get("_source") or {}).get("file") == source_file:
            matched_ids.append(row["id"])
    if matched_ids:
        _documents().delete().in_("id", matched_ids).execute()
    if pages:
        insert_documents(user_id, list(pages))
    return len(matched_ids)


@_translate_missing_schema
def delete_document_group(
    user_id: str,
    *,
    content_sha256: Optional[str],
    cloudinary_public_id: Optional[str],
    source_file: Optional[str],
    document_id: str,
) -> int:
    """Delete one physical upload, including every extracted page row.

    New uploads share a content hash and Cloudinary id across all pages.
    Older rows fall back to their source filename, then finally to the exact
    application document id. Every query remains scoped to ``user_id``.
    """
    response = _documents().select("id, data").eq("user_id", user_id).execute()
    matched_ids: List[Any] = []
    for row in response.data or []:
        data = row.get("data") if isinstance(row.get("data"), dict) else {}
        row_document_id = str(data.get("_document_id") or f"db:{row['id']}")
        same_upload = False
        if content_sha256:
            same_upload = data.get("content_sha256") == content_sha256
        elif cloudinary_public_id:
            same_upload = data.get("cloudinary_public_id") == cloudinary_public_id
        elif source_file:
            same_upload = (data.get("_source") or {}).get("file") == source_file
        else:
            same_upload = row_document_id == document_id
        if same_upload:
            matched_ids.append(row["id"])
    if matched_ids:
        _documents().delete().eq("user_id", user_id).in_("id", matched_ids).execute()
    return len(matched_ids)


@_translate_missing_schema
def delete_document_corrections(user_id: str, document_ids: Sequence[str]) -> None:
    """Remove correction events whose source document has been deleted."""
    ids = [str(value) for value in document_ids if value]
    if ids:
        _corrections().delete().eq("user_id", user_id).in_("document_id", ids).execute()


@_translate_missing_schema
def clear_conflict_history(user_id: str) -> None:
    """Clear derived conflict state before rebuilding it from remaining sources."""
    _conflict_events().delete().eq("user_id", user_id).execute()
    _conflicts().delete().eq("user_id", user_id).execute()


@_translate_missing_schema
def delete_patient_snapshot(user_id: str) -> None:
    _snapshots().delete().eq("user_id", user_id).execute()


@_translate_missing_schema
def delete_workspace_data(user_id: str) -> Dict[str, int]:
    """Permanently remove all persisted records owned by one workspace.

    Optional tables may not exist on older deployments; a missing optional
    table is skipped, while every other storage failure aborts the request so
    the UI never claims deletion completed when it did not.
    """
    tables = [
        ("conflict_resolution_events", "user_id"),
        ("record_conflicts", "user_id"),
        ("extraction_corrections", "user_id"),
        ("referral_searches", "user_id"),
        ("conversation_sessions", "user_id"),
        ("jobs", "user_id"),
        ("chunks", "patient_key"),
        ("patient_snapshots", "user_id"),
        ("documents", "user_id"),
        # Audit metadata is deleted last so no user-linked residue remains.
        ("audit_log", "user_id"),
    ]
    client = _get_client()
    deleted: Dict[str, int] = {}
    for table_name, field in tables:
        try:
            response = client.table(table_name).delete().eq(field, user_id).execute()
            deleted[table_name] = len(response.data or [])
        except Exception as exc:
            if getattr(exc, "code", None) == _MISSING_TABLE_CODE or _MISSING_TABLE_CODE in str(exc):
                deleted[table_name] = 0
                continue
            raise
    return deleted


@_translate_missing_schema
def save_referral_search(user_id: str, search: Dict[str, Any]) -> None:
    """Appends one referral-trail record (finding -> specialty -> search ->
    ranked providers) for this user. Append-only; see referral_trail.py
    for the record shape. The table is created by supabase_schema.sql."""
    _referral_searches().insert({
        "user_id": user_id,
        "created_at": _now_iso(),
        "search": search,
    }).execute()


@_translate_missing_schema
def load_referral_searches(user_id: str, limit: int = 20) -> List[Dict[str, Any]]:
    """Returns this user's referral-trail history, newest first."""
    response = (
        _referral_searches()
        .select("id, created_at, search")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .order("id", desc=True)
        .limit(max(1, min(100, limit)))
        .execute()
    )
    return list(response.data or [])


@_translate_missing_schema
def load_correction_events(user_id: str, document_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """Return immutable correction events in replay/audit order."""
    query = _corrections().select(
        "id, correction_batch_id, user_id, document_id, field_path, original_value, "
        "previous_value, corrected_value, reason, created_at"
    ).eq("user_id", user_id)
    if document_id is not None:
        query = query.eq("document_id", document_id)
    response = query.order("created_at").order("id").execute()
    return list(response.data or [])


@_translate_missing_schema
def insert_correction_events(user_id: str, events: Sequence[Dict[str, Any]]) -> None:
    """Append a validated correction batch; original document rows stay intact."""
    if not events:
        return
    rows = []
    for event in events:
        if event.get("user_id") != user_id:
            raise ValueError("Correction event user_id does not match the authenticated user.")
        rows.append({
            "id": event["id"],
            "correction_batch_id": event["correction_batch_id"],
            "user_id": user_id,
            "document_id": event["document_id"],
            "field_path": event["field_path"],
            "original_value": event.get("original_value"),
            "previous_value": event.get("previous_value"),
            "corrected_value": event.get("corrected_value"),
            "reason": event["reason"],
            "created_at": event.get("created_at") or _now_iso(),
        })
    _corrections().insert(rows).execute()


@_translate_missing_schema
def load_conflicts(user_id: str, include_inactive: bool = False) -> List[Dict[str, Any]]:
    query = _conflicts().select(
        "conflict_id, user_id, status, authoritative_document_id, resolution_note, "
        "data, detected_at, updated_at, resolved_at"
    ).eq("user_id", user_id)
    response = query.order("updated_at", desc=True).execute()
    rows: List[Dict[str, Any]] = []
    for row in response.data or []:
        if not include_inactive and row.get("status") == "superseded":
            continue
        data = dict(row.get("data") or {})
        data.update({
            "conflict_id": row["conflict_id"],
            "user_id": row["user_id"],
            "status": row.get("status") or "unresolved",
            "authoritative_document_id": row.get("authoritative_document_id"),
            "resolution_note": row.get("resolution_note"),
            "detected_at": row.get("detected_at"),
            "updated_at": row.get("updated_at"),
            "resolved_at": row.get("resolved_at"),
        })
        rows.append(data)
    return rows


@_translate_missing_schema
def sync_conflicts(user_id: str, detected_conflicts: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Persist current detections while preserving still-valid resolutions.

    Conflicts that disappear after a correction are retained as superseded
    audit records rather than deleted.
    """
    now = _now_iso()
    existing_rows = load_conflicts(user_id, include_inactive=True)
    existing = {str(item.get("conflict_id")): item for item in existing_rows}
    active_ids = set()
    rows = []
    for detected in detected_conflicts:
        conflict_id = str(detected["conflict_id"])
        active_ids.add(conflict_id)
        old = existing.get(conflict_id) or {}
        source_ids = {str(item.get("document_id")) for item in detected.get("items", [])}
        authoritative = str(old.get("authoritative_document_id") or "")
        keep_resolution = old.get("status") == "resolved" and authoritative in source_ids
        status = "resolved" if keep_resolution else "unresolved"
        data = {
            key: value for key, value in detected.items()
            if key not in {
                "user_id", "status", "authoritative_document_id", "resolution_note",
                "detected_at", "updated_at", "resolved_at",
            }
        }
        rows.append({
            "conflict_id": conflict_id,
            "user_id": user_id,
            "status": status,
            "authoritative_document_id": authoritative if keep_resolution else None,
            "resolution_note": old.get("resolution_note") if keep_resolution else None,
            "data": data,
            "detected_at": old.get("detected_at") or now,
            "updated_at": now,
            "resolved_at": old.get("resolved_at") if keep_resolution else None,
        })
    if rows:
        _conflicts().upsert(rows, on_conflict="user_id,conflict_id").execute()

    for old in existing_rows:
        conflict_id = str(old.get("conflict_id"))
        if conflict_id in active_ids or old.get("status") == "superseded":
            continue
        _conflicts().update({"status": "superseded", "updated_at": now}).eq(
            "conflict_id", conflict_id
        ).eq("user_id", user_id).execute()
    return load_conflicts(user_id)


@_translate_missing_schema
def set_conflict_resolution(
    user_id: str,
    conflict_id: str,
    *,
    status: str,
    authoritative_document_id: Optional[str],
    note: Optional[str],
) -> Dict[str, Any]:
    """Resolve or reopen a conflict and append an immutable workflow event."""
    if status not in {"resolved", "unresolved"}:
        raise ValueError("Conflict status must be resolved or unresolved.")
    current = next(
        (item for item in load_conflicts(user_id) if item.get("conflict_id") == conflict_id),
        None,
    )
    if current is None:
        raise KeyError(conflict_id)
    if status == "resolved":
        source_ids = {str(item.get("document_id")) for item in current.get("items", [])}
        if not authoritative_document_id or authoritative_document_id not in source_ids:
            raise ValueError("The authoritative document must be one of the conflicting sources.")
    else:
        authoritative_document_id = None

    now = _now_iso()
    old_status = current.get("status") or "unresolved"
    event_id = f"resolution_{__import__('uuid').uuid4().hex}"
    _conflict_events().insert({
        "id": event_id,
        "user_id": user_id,
        "conflict_id": conflict_id,
        "old_status": old_status,
        "new_status": status,
        "authoritative_document_id": authoritative_document_id,
        "note": (note or "").strip() or None,
        "created_at": now,
    }).execute()
    fields = {
        "status": status,
        "authoritative_document_id": authoritative_document_id,
        "resolution_note": (note or "").strip() or None,
        "updated_at": now,
        "resolved_at": now if status == "resolved" else None,
    }
    _conflicts().update(fields).eq("conflict_id", conflict_id).eq("user_id", user_id).execute()
    return next(item for item in load_conflicts(user_id) if item.get("conflict_id") == conflict_id)


@_translate_missing_schema
def load_conflict_events(user_id: str, conflict_id: Optional[str] = None) -> List[Dict[str, Any]]:
    query = _conflict_events().select("*").eq("user_id", user_id)
    if conflict_id is not None:
        query = query.eq("conflict_id", conflict_id)
    response = query.order("created_at", desc=True).execute()
    return list(response.data or [])
