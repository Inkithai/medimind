"""
Clinician / Reviewer Feedback Loop
==================================
MediMind's safety engines produce findings; until now there was no way to
record what a human reviewer thought of them. This module adds the missing
half of a safety pipeline: a place to capture, per finding, whether a
reviewer CONFIRMED it, marked it a FALSE POSITIVE, asked for a CHANGE, or
OVERRIDDEN it (dismissed an alert — with a reason), and to turn that captured
judgement into performance metrics.

It is deliberately anonymous-friendly: there is no account, so "reviewer" is
a free-text label (e.g. "pharmacist on call") and the feedback is scoped to
the same `user_id` workspace as everything else.

Persistence model (mirrors conversation.py / jobs.py): an in-memory,
thread-safe store is the source of truth, with best-effort mirroring to a
Supabase `finding_feedback` table when one is configured. As with the rest of
the pipeline, an unreachable database never breaks the API — feedback is
still recorded in memory for the process.

This also underpins alert-fatigue management: the override verdict + reason
lets the UI suppress a re-emitted alert, and the metrics let an operator see
which rules fire most often and are most often overridden (the signal that a
rule is too noisy).

Finding identity
----------------
A finding has no natural id, so feedback keys off a deterministic fingerprint
of WHAT was found (kind + rule + the medications/labs/condition involved).
`finding_key(finding)` reproduces the same key the cross-check/feedback
endpoints use, so a review attaches to "this rule on these drugs", not to a
row id that changes every re-analysis.
"""

from __future__ import annotations

import hashlib
import threading
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

VERDICTS = ("confirmed", "false_positive", "needs_change", "overridden")
_DECIDED = ("confirmed", "false_positive", "needs_change")

_lock = threading.RLock()
# user_id -> list of feedback entries (append-only, newest last)
_store: Dict[str, List[Dict[str, Any]]] = {}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# --------------------------------------------------------------------------- #
# Deterministic finding fingerprint
# --------------------------------------------------------------------------- #


def _sig_components(finding: Dict[str, Any]) -> List[str]:
    kind = str(finding.get("finding_kind") or finding.get("kind") or "finding")
    rule = str(finding.get("rule") or "").strip().lower()
    meds = sorted(
        str(m).strip().lower()
        for m in (finding.get("medications_involved") or [])
        if str(m).strip()
    )
    cond = str(finding.get("condition") or "").strip().lower()
    lab = finding.get("lab") or {}
    organ = str(finding.get("organ") or "").strip().lower()
    parts = [kind, rule, "|".join(meds)]
    if cond:
        parts.append(cond)
    if organ:
        parts.append(organ)
    if lab and isinstance(lab, dict):
        parts.append(f"{lab.get('test', '')}:{lab.get('value', '')}")
    return parts


def finding_key(finding: Dict[str, Any]) -> str:
    raw = "::".join(_sig_components(finding))
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def finding_key_from(
    finding_kind: str = "",
    rule: str = "",
    medications_involved: Optional[List[str]] = None,
    condition: str = "",
    organ: str = "",
) -> str:
    """Return a fingerprint, or '' when the caller supplied no identity.

    POST /api/v1/findings/feedback treats an empty key as 400. Hashing an
    all-blank finding still produced a stable SHA, so a body with only
    ``verdict`` was accepted against a garbage key.
    """
    meds = [str(item).strip() for item in (medications_involved or []) if str(item).strip()]
    if not any(
        (
            str(finding_kind or "").strip(),
            str(rule or "").strip(),
            meds,
            str(condition or "").strip(),
            str(organ or "").strip(),
        )
    ):
        return ""
    return finding_key(
        {
            "finding_kind": finding_kind,
            "rule": rule,
            "medications_involved": meds,
            "condition": condition,
            "organ": organ,
        }
    )


# --------------------------------------------------------------------------- #
# Best-effort Supabase mirror (optional)
# --------------------------------------------------------------------------- #


def _mirror_save(entry: Dict[str, Any]) -> None:
    try:
        from db import _get_client  # type: ignore

        client = _get_client()
        client.table("finding_feedback").insert(
            {
                "user_id": entry["user_id"],
                "finding_key": entry["finding_key"],
                "finding_kind": entry.get("finding_kind"),
                "rule": entry.get("rule"),
                "verdict": entry["verdict"],
                "reason": entry.get("reason"),
                "note": entry.get("note"),
                "reviewer": entry.get("reviewer"),
                "created_at": entry["created_at"],
            }
        ).execute()
    except Exception:
        # Table missing / DB unreachable — in-memory store still holds it.
        return


def _mirror_load(user_id: str) -> Optional[List[Dict[str, Any]]]:
    try:
        from db import _get_client  # type: ignore

        client = _get_client()
        resp = (
            client.table("finding_feedback")
            .select("finding_key,finding_kind,rule,verdict,reason,note,reviewer,created_at")
            .eq("user_id", user_id)
            .order("created_at")
            .execute()
        )
        rows = getattr(resp, "data", None) or []
        for row in rows:
            row["user_id"] = user_id
        return rows or None
    except Exception:
        return None


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #


def record_feedback(
    user_id: str,
    finding_key_value: str,
    verdict: str,
    *,
    finding_kind: str = "",
    rule: str = "",
    reason: str = "",
    note: str = "",
    reviewer: str = "",
) -> Dict[str, Any]:
    if verdict not in VERDICTS:
        raise ValueError(f"verdict must be one of {VERDICTS}")
    entry = {
        "user_id": user_id,
        "finding_key": finding_key_value,
        "finding_kind": finding_kind,
        "rule": rule,
        "verdict": verdict,
        "reason": (reason or "").strip(),
        "note": (note or "").strip(),
        "reviewer": (reviewer or "").strip(),
        "created_at": _now_iso(),
    }
    with _lock:
        _store.setdefault(user_id, []).append(entry)
    _mirror_save(entry)
    return entry


def list_feedback(user_id: str) -> List[Dict[str, Any]]:
    with _lock:
        local = list(_store.get(user_id, []))
    mirrored = _mirror_load(user_id)
    if mirrored:
        # merge, de-duping on (finding_key, verdict, created_at)
        seen = {(e["finding_key"], e["verdict"], e["created_at"]) for e in local}
        merged = list(local)
        for row in mirrored:
            sig = (row.get("finding_key"), row.get("verdict"), row.get("created_at"))
            if sig not in seen:
                seen.add(sig)
                merged.append(row)
        merged.sort(key=lambda e: e.get("created_at") or "")
        return merged
    return local


def latest_verdict(user_id: str, fkey: str) -> Optional[str]:
    """Most recent verdict for a given finding key, or None. Powers alert
    suppression (alert-fatigue management)."""
    latest: Optional[str] = None
    latest_ts = -1.0
    for entry in list_feedback(user_id):
        if entry.get("finding_key") != fkey:
            continue
        try:
            ts = time.mktime(datetime.fromisoformat(entry["created_at"]).timetuple())
        except Exception:
            ts = 0.0
        if ts >= latest_ts:
            latest_ts = ts
            latest = entry.get("verdict")
    return latest


def is_overridden(user_id: str, fkey: str) -> bool:
    return latest_verdict(user_id, fkey) == "overridden"


def get_feedback_metrics(user_id: str) -> Dict[str, Any]:
    entries = list_feedback(user_id)
    total = len(entries)
    by_verdict = Counter(e["verdict"] for e in entries)
    decided = sum(by_verdict[v] for v in _DECIDED)
    overrides = by_verdict.get("overridden", 0)

    def _rate(num: int, den: int) -> Optional[float]:
        return round(num / den, 3) if den else None

    by_kind: Dict[str, Counter] = defaultdict(Counter)
    by_rule: Dict[str, Counter] = defaultdict(Counter)
    for e in entries:
        by_kind[e.get("finding_kind") or "unknown"][e["verdict"]] += 1
        by_rule[e.get("rule") or "unknown"][e["verdict"]] += 1

    # noisiest rules = highest override count (alert-fatigue signal)
    noisiest = sorted(
        (
            {
                "rule": r,
                "total": sum(c.values()),
                "overrides": c.get("overridden", 0),
                "false_positives": c.get("false_positive", 0),
            }
            for r, c in by_rule.items()
        ),
        key=lambda x: (x["overrides"] + x["false_positives"], x["total"]),
        reverse=True,
    )[:10]

    return {
        "total": total,
        "decided": decided,
        "by_verdict": dict(by_verdict),
        "confirmation_rate": _rate(by_verdict.get("confirmed", 0), decided),
        "false_positive_rate": _rate(by_verdict.get("false_positive", 0), decided),
        "override_rate": _rate(overrides, total),
        "by_finding_kind": {k: dict(v) for k, v in by_kind.items()},
        "noisiest_rules": noisiest,
    }


def reset(user_id: Optional[str] = None) -> None:
    """Test/dev helper. Clears the in-memory store for a user (or all)."""
    with _lock:
        if user_id is None:
            _store.clear()
        else:
            _store.pop(user_id, None)
