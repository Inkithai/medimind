"""
Safety-Finding Lifecycle (state machine)
========================================
clinician_feedback.py records a reviewer's VERDICT on a finding. This module
gives each finding a separate LIFECYCLE state, so a workspace can answer
"which findings are still open, which have been resolved, which were
reopened?" across time — the workflow layer alert-fatigue and triage need.

States (per finding, per workspace):

    new -> active -> reviewed -> confirmed
                          |        |
                          |        +-> resolved
                          +--------+-> dismissed
    any (*) --------------> reopened (returns to active)

Transitions are validated against an allowed-edges table so an illegal move
(e.g. resolving an already-dismissed finding) is rejected rather than
silently corrupting the state. Newest state wins. In-memory-first with a
best-effort Supabase mirror, mirroring clinician_feedback.

Keyed by the same deterministic finding fingerprint clinician_feedback uses.
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from clinician_feedback import finding_key

NEW = "new"
ACTIVE = "active"
REVIEWED = "reviewed"
CONFIRMED = "confirmed"
DISMISSED = "dismissed"
RESOLVED = "resolved"
REOPENED = "reopened"

OPEN_STATES = {NEW, ACTIVE, REVIEWED, REOPENED}
CLOSED_STATES = {CONFIRMED, DISMISSED, RESOLVED}
ALL_STATES = OPEN_STATES | CLOSED_STATES

# allowed transitions FROM -> {allowed TO}
_TRANSITIONS: Dict[str, set] = {
    NEW: {ACTIVE, REVIEWED, DISMISSED},
    ACTIVE: {REVIEWED, CONFIRMED, DISMISSED, RESOLVED},
    REVIEWED: {CONFIRMED, DISMISSED, RESOLVED, ACTIVE},
    CONFIRMED: {RESOLVED, REOPENED},
    DISMISSED: {REOPENED, ACTIVE},
    RESOLVED: {REOPENED, ACTIVE},
    REOPENED: {ACTIVE, REVIEWED, CONFIRMED, DISMISSED, RESOLVED},
}

_lock = threading.RLock()
# (user_id, finding_key) -> list of state events (append-only)
_history: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _mirror(event: Dict[str, Any]) -> None:
    try:
        from db import _get_client  # type: ignore

        _get_client().table("finding_lifecycle").insert(
            {
                "user_id": event["user_id"],
                "finding_key": event["finding_key"],
                "from_state": event.get("from_state"),
                "to_state": event["to_state"],
                "reason": event.get("reason"),
                "actor": event.get("actor"),
                "at": event["at"],
            }
        ).execute()
    except Exception:
        return


def current_state(user_id: str, fkey: str) -> Optional[str]:
    with _lock:
        events = _history.get((user_id, fkey))
    if not events:
        return None
    return events[-1]["to_state"]


def transition(
    user_id: str,
    finding: Dict[str, Any],
    to_state: str,
    *,
    reason: str = "",
    actor: str = "",
) -> Dict[str, Any]:
    fkey = (
        finding_key(finding)
        if "finding_kind" in finding or "rule" in finding
        else finding.get("finding_key")
    )
    if to_state not in ALL_STATES:
        raise ValueError(f"unknown state {to_state}")
    prev = current_state(user_id, fkey) or NEW
    if to_state == prev:
        return {"finding_key": fkey, "state": prev, "unchanged": True}
    allowed = _TRANSITIONS.get(prev, set())
    if to_state not in allowed:
        raise ValueError(f"illegal transition {prev} -> {to_state}")
    event = {
        "user_id": user_id,
        "finding_key": fkey,
        "from_state": prev,
        "to_state": to_state,
        "reason": (reason or "").strip(),
        "actor": (actor or "").strip(),
        "at": _now(),
    }
    with _lock:
        _history.setdefault((user_id, fkey), []).append(event)
    _mirror(event)
    return {"finding_key": fkey, "state": to_state, "from_state": prev, "transitioned": True}


def history(user_id: str, fkey: Optional[str] = None) -> List[Dict[str, Any]]:
    with _lock:
        if fkey:
            return list(_history.get((user_id, fkey), []))
        out = []
        for (uid, _fk), events in _history.items():
            if uid == user_id:
                out.extend(events)
        return out


def lifecycle_overview(user_id: str, findings: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Stamp a list of findings with their current lifecycle state and return
    open/closed counts."""
    stamped: List[Dict[str, Any]] = []
    counts = {s: 0 for s in ALL_STATES}
    for finding in findings:
        f = dict(finding)
        fkey = finding_key(finding)
        st = current_state(user_id, fkey) or NEW
        f["finding_key"] = fkey
        f["lifecycle_state"] = st
        f["is_open"] = st in OPEN_STATES
        counts[st] = counts.get(st, 0) + 1
        stamped.append(f)
    return {
        "findings": stamped,
        "open_count": sum(counts[s] for s in OPEN_STATES),
        "closed_count": sum(counts[s] for s in CLOSED_STATES),
        "by_state": counts,
    }


def reset(user_id: Optional[str] = None) -> None:
    with _lock:
        if user_id is None:
            _history.clear()
        else:
            for key in [k for k in _history if k[0] == user_id]:
                _history.pop(key, None)
