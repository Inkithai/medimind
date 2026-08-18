"""
Secure Provider Messaging (care-workflow thread)
================================================
provider search finds a clinician; this module is the thread that lets a
patient exchange short messages with that provider (or a stand-in contact)
about a finding — "ask about this alert", a follow-up question, a status
update. It is the communication layer that closes Find-Care -> message ->
follow-up.

Anonymous-friendly: a "provider" is identified by a free-text label and an
optional care-search result id (no account directory required). Messages are
stored per workspace; the thread is append-only. In-memory-first with a
best-effort Supabase mirror, like the other stores.

This is a store + retrieval layer; it does not itself transmit over any
external transport (email/SMS). An operator wires the chosen transport to the
recorded outbound messages. That keeps MediMind free of a messaging-vendor
dependency while giving the workflow a place to live.
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

_lock = threading.RLock()
# user_id -> list of messages
_store: Dict[str, List[Dict[str, Any]]] = {}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _mirror(msg: Dict[str, Any]) -> None:
    try:
        from db import _get_client  # type: ignore
        _get_client().table("provider_messages").insert({
            "user_id": msg["user_id"],
            "thread_id": msg["thread_id"],
            "direction": msg["direction"],
            "provider": msg["provider"],
            "finding_key": msg.get("finding_key"),
            "body": msg["body"],
            "created_at": msg["created_at"],
        }).execute()
    except Exception:
        return


def send_message(
    user_id: str,
    body: str,
    *,
    provider: str = "",
    thread_id: Optional[str] = None,
    finding_key: Optional[str] = None,
    direction: str = "outbound",
) -> Dict[str, Any]:
    body = (body or "").strip()
    if not body:
        raise ValueError("body is required")
    import hashlib, time as _time
    if thread_id is None:
        thread_id = hashlib.sha1(
            f"{user_id}:{provider or 'default'}:{_time.time()}".encode()
        ).hexdigest()[:12]
    msg = {
        "user_id": user_id,
        "thread_id": thread_id,
        "direction": direction,
        "provider": (provider or "").strip(),
        "finding_key": finding_key,
        "body": body,
        "created_at": _now(),
    }
    with _lock:
        _store.setdefault(user_id, []).append(msg)
    _mirror(msg)
    return msg


def list_messages(user_id: str, thread_id: Optional[str] = None) -> List[Dict[str, Any]]:
    with _lock:
        rows = list(_store.get(user_id, []))
    if thread_id:
        rows = [m for m in rows if m.get("thread_id") == thread_id]
    rows.sort(key=lambda m: m.get("created_at") or "")
    return rows


def list_threads(user_id: str) -> List[Dict[str, Any]]:
    threads: Dict[str, Dict[str, Any]] = {}
    for m in list_messages(user_id):
        tid = m.get("thread_id")
        t = threads.setdefault(tid, {"thread_id": tid, "provider": m.get("provider"),
                                     "message_count": 0, "last_at": m.get("created_at")})
        t["message_count"] += 1
        if (m.get("created_at") or "") > (t["last_at"] or ""):
            t["last_at"] = m.get("created_at")
            t["provider"] = m.get("provider")
    return sorted(threads.values(), key=lambda t: t.get("last_at") or "", reverse=True)


def reset(user_id: Optional[str] = None) -> None:
    with _lock:
        if user_id is None:
            _store.clear()
        else:
            _store.pop(user_id, None)
