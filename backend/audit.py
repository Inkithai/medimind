"""
Audit Logging (append-only)
=========================================
Records every data-touching API action — who (user_id), what (action),
when (created_at), and non-sensitive context (detail) — to the Supabase
`audit_log` table created by supabase_schema.sql.

Design constraints:
  * Best-effort and non-blocking: an audit failure must NEVER fail the
    request being audited. Failures degrade to a structured WARNING app-log
    line carrying the same fields, so the trail survives (in logs) even
    when the table is missing or Supabase is down.
  * No clinical payloads: `detail` carries metadata only (file names,
    counts, session ids, question lengths) — never extracted medical data,
    answers, or document contents, so the audit trail itself is not a
    second copy of PHI.
  * Append-only during normal operation: this module has no update/delete
    helpers. The only deletion path is an explicit whole-workspace privacy
    erasure, implemented centrally in db.delete_workspace_data.

Env:
    AUDIT_LOG=true|false   (default true) master switch.
"""

import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger("audit")

AUDIT_ENABLED = os.environ.get("AUDIT_LOG", "true").lower() in ("true", "1", "yes")

# Action vocabulary — keep this list in sync with call sites in api.py so
# downstream consumers can rely on a closed set of action names.
ACTIONS = (
    "documents.upload",         # files received for processing (sync or async)
    "documents.upload_result",  # pipeline finished (counts, indexed flag)
    "documents.delete",         # one physical upload permanently removed
    "records.read",             # timeline / cross-check / lab-trends / snapshot read
    "records.export",           # full-record export generated
    "qa.ask",                   # single-shot QA question answered
    "session.create",           # conversation session created
    "session.message",          # conversational turn answered
    "session.read",             # transcript read
    "session.delete",           # transcript deleted
    "care.read",                # care recommendations / facilities read
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def record(user_id: str, action: str, detail: Optional[Dict[str, Any]] = None) -> None:
    """Appends one audit event. Never raises; never blocks the caller
    beyond the single insert round-trip. When the table is unavailable the
    event is emitted as a structured app-log line instead, so the action
    is still traceable through log aggregation."""
    if not AUDIT_ENABLED:
        return
    event = {
        "user_id": user_id,
        "action": action,
        "detail": detail or {},
        "created_at": _now_iso(),
    }
    try:
        from db import _get_client
        _get_client().table("audit_log").insert(event).execute()
    except Exception as e:
        logger.warning(
            "audit fallback (table unavailable): user=%s action=%s detail=%s error=%s",
            user_id, action, detail, e,
        )
