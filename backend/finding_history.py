"""
Clinical Finding History & Audit Trail
======================================
The safety engines regenerate findings on every re-analysis, so a finding can
appear, persist, disappear, or recur across runs — and until now nothing
remembered that. This module gives every analysis run an immutable snapshot of
WHICH findings existed, so a workspace can answer the audit questions a clinical
product needs:

  * "What's NEW since last time?"
  * "What has RESOLVED (was present, now gone)?"
  * "What has PERSISTED across runs?"
  * "Show me the full change history of this record's findings."

Snapshots are keyed by the same deterministic fingerprint as clinician_feedback
(finding_kind + rule + medications/condition/lab), so identity is stable across
re-analyses. In-memory-first with a best-effort Supabase mirror; every snapshot
is also written to the existing audit log (audit.py) for an operator-visible
trail.

It records; it never mutates the report. Deterministic, no LLM.
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

from alert_management import FINDING_LISTS
from clinician_feedback import finding_key

_lock = threading.RLock()
# user_id -> list of snapshots (append-only, newest last)
_history: Dict[str, List[Dict[str, Any]]] = {}

# Which report lists count as "findings" for history purposes. Reuses the
# alert_management list so the two views agree on what a finding is.


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _collect_finding_keys(report: Dict[str, Any]) -> Set[str]:
    keys: Set[str] = set()
    for list_key in FINDING_LISTS:
        for finding in report.get(list_key) or []:
            try:
                keys.add(finding_key(finding))
            except Exception:
                continue
    return keys


def _collect_findings(report: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Flatten the report's finding lists into [{key, kind, list, severity, rule}]."""
    flat: List[Dict[str, Any]] = []
    for list_key in FINDING_LISTS:
        for finding in report.get(list_key) or []:
            try:
                flat.append(
                    {
                        "key": finding_key(finding),
                        "kind": finding.get("finding_kind") or list_key,
                        "list": list_key,
                        "severity": finding.get("severity"),
                        "rule": finding.get("rule"),
                        "subject": (finding.get("medications_involved") or [None])[0]
                        if isinstance(finding.get("medications_involved"), list)
                        else finding.get("condition") or finding.get("organ"),
                    }
                )
            except Exception:
                continue
    return flat


def _mirror(snapshot: Dict[str, Any]) -> None:
    try:
        from db import _get_client  # type: ignore

        client = _get_client()
        for f in snapshot["findings"]:
            client.table("finding_history").insert(
                {
                    "user_id": snapshot["user_id"],
                    "run_id": snapshot["run_id"],
                    "captured_at": snapshot["captured_at"],
                    "finding_key": f["key"],
                    "finding_kind": f.get("kind"),
                    "list": f.get("list"),
                    "severity": f.get("severity"),
                    "rule": f.get("rule"),
                }
            ).execute()
    except Exception:
        return


def snapshot_findings(
    user_id: str, report: Dict[str, Any], *, run_id: Optional[str] = None
) -> Dict[str, Any]:
    """Record the findings present in `report` right now, and return the diff
    against the previous snapshot (or 'initial' if this is the first)."""
    flattened = _collect_findings(report)
    current_keys = {f["key"] for f in flattened}
    run_id = run_id or _now()

    snapshot = {
        "run_id": run_id,
        "user_id": user_id,
        "captured_at": _now(),
        "finding_count": len(current_keys),
        "findings": flattened,
    }

    with _lock:
        prev = _history.setdefault(user_id, [])[-1] if _history.get(user_id) else None
        _history.setdefault(user_id, []).append(snapshot)

    previous_keys = {f["key"] for f in (prev or {}).get("findings", [])} if prev else set()
    diff = {
        "new": sorted(current_keys - previous_keys),
        "resolved": sorted(previous_keys - current_keys),
        "persisted": sorted(current_keys & previous_keys),
        "is_initial": prev is None,
    }
    snapshot["diff_vs_previous"] = diff

    # operator-visible audit trail
    try:
        import audit  # type: ignore

        audit.record(
            user_id,
            "finding_history.snapshot",
            {
                "run_id": run_id,
                "total": len(current_keys),
                "new": len(diff["new"]),
                "resolved": len(diff["resolved"]),
                "persisted": len(diff["persisted"]),
            },
        )
    except Exception:
        pass

    _mirror(snapshot)
    return snapshot


def finding_history(user_id: str, limit: int = 20) -> List[Dict[str, Any]]:
    """Chronological list of snapshots (newest last), capped at `limit`."""
    with _lock:
        snaps = list(_history.get(user_id, []))
    return snaps[-limit:]


def latest_snapshot(user_id: str) -> Optional[Dict[str, Any]]:
    with _lock:
        snaps = _history.get(user_id)
    return snaps[-1] if snaps else None


def finding_change_log(user_id: str) -> Dict[str, Any]:
    """A condensed per-finding change log: when each finding first appeared and
    last seen, plus any runs in which it was absent (resolved) then returned."""
    snaps = finding_history(user_id, limit=200)
    per_key: Dict[str, Dict[str, Any]] = {}
    for snap in snaps:
        present = {f["key"] for f in snap["findings"]}
        for f in snap["findings"]:
            entry = per_key.setdefault(
                f["key"],
                {
                    "finding_key": f["key"],
                    "kind": f.get("kind"),
                    "severity": f.get("severity"),
                    "rule": f.get("rule"),
                    "subject": f.get("subject"),
                    "first_seen": snap["captured_at"],
                    "last_seen": snap["captured_at"],
                    "seen_in_runs": 0,
                    "absent_then_recurred": False,
                },
            )
            entry["last_seen"] = snap["captured_at"]
            entry["seen_in_runs"] += 1
        # detect recurrence: a key present earlier, absent now would be handled
        # by scanning presence across runs below
    # second pass: recurrence detection
    for key, entry in per_key.items():
        was_present = False
        gap_seen = False
        for snap in snaps:
            present = key in {f["key"] for f in snap["findings"]}
            if present and gap_seen:
                entry["absent_then_recurred"] = True
            if present:
                was_present = True
            elif was_present:
                gap_seen = True
    return {
        "snapshots": len(snaps),
        "findings": sorted(per_key.values(), key=lambda e: e["last_seen"], reverse=True),
    }


def reset(user_id: Optional[str] = None) -> None:
    with _lock:
        if user_id is None:
            _history.clear()
        else:
            _history.pop(user_id, None)
