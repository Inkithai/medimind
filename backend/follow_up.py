"""Grounded follow-up action queue.

Combines existing appointment-preparation priorities and record-integrity
checks into stable, patient-manageable tasks. The engine never invents a
clinical deadline. Reminder dates and completion state belong to the user and
are stored by the frontend, not inferred here.
"""

from __future__ import annotations

import hashlib
from typing import Any, Dict, Iterable, List

from appointment_prep import build_appointment_prep
from record_integrity import check_record_integrity


def _stable_id(kind: str, title: str, evidence: Iterable[Dict[str, Any]]) -> str:
    source_markers = sorted(
        f"{item.get('date') or ''}|{item.get('source_file') or ''}"
        for item in evidence
    )
    raw = f"{kind}|{title}|{'|'.join(source_markers)}"
    return "followup-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _task(
    kind: str,
    category: str,
    priority: str,
    title: str,
    action: str,
    reason: str,
    evidence: List[Dict[str, Any]],
    timing_guardrail: str,
) -> Dict[str, Any]:
    return {
        "id": _stable_id(kind, title, evidence),
        "kind": kind,
        "category": category,
        "priority": priority,
        "title": title,
        "action": action,
        "reason": reason,
        "evidence": evidence,
        "timing_guardrail": timing_guardrail,
    }


def build_follow_up_plan(
    timeline: Dict[str, Any],
    cross_check: Dict[str, Any],
    lab_trends: Dict[str, Any],
) -> Dict[str, Any]:
    """Return a deduplicated, stable action queue from record-backed findings."""
    appointment = build_appointment_prep(timeline, cross_check, lab_trends)
    integrity = check_record_integrity(timeline)
    tasks: List[Dict[str, Any]] = []

    for issue in integrity["issues"]:
        evidence = [
            source
            for variant in issue.get("variants", [])
            for source in variant.get("evidence", [])
        ]
        priority = "high" if issue["severity"] == "important" else "medium"
        tasks.append(_task(
            "record_verification",
            "Record integrity",
            priority,
            issue["title"],
            issue["suggested_action"],
            issue["explanation"],
            evidence,
            "Verify before relying on the conflicting field for a care decision.",
        ))

    for item in appointment["priorities"]:
        # The appointment fallback is still useful, but should not crowd out
        # concrete findings when the queue already has work to do.
        if item["id"] == "record-review" and tasks:
            continue
        priority = {"important": "high", "review": "medium", "routine": "low"}.get(item["level"], "medium")
        category = item["category"]
        if category == "Medication safety":
            guardrail = "Review with a clinician or pharmacist before changing how you take a medicine."
        elif category == "Lab trend":
            guardrail = "Choose a reminder date with your clinician; MediMind does not infer a retest interval."
        else:
            guardrail = "Use your next appropriate clinician conversation; this is not an emergency-timing recommendation."
        tasks.append(_task(
            "clinical_question",
            category,
            priority,
            item["title"],
            item["question"],
            item["rationale"],
            item.get("evidence", []),
            guardrail,
        ))

    # The same underlying discrepancy can appear in integrity and appointment
    # prep. Keep the higher-priority first occurrence by normalized title.
    order = {"high": 0, "medium": 1, "low": 2}
    tasks.sort(key=lambda item: (order.get(item["priority"], 9), item["category"], item["title"]))
    seen_titles = set()
    deduped = []
    for task in tasks:
        marker = " ".join(task["title"].lower().split())
        if marker in seen_titles:
            continue
        seen_titles.add(marker)
        deduped.append(task)

    high = sum(task["priority"] == "high" for task in deduped)
    medium = sum(task["priority"] == "medium" for task in deduped)
    return {
        "tasks": deduped,
        "summary": {
            "total": len(deduped),
            "high_priority": high,
            "medium_priority": medium,
            "record_verification": sum(task["kind"] == "record_verification" for task in deduped),
        },
        "method": "Tasks are assembled deterministically from safety checks, lab trends, recent changes, and record-integrity findings.",
        "note": (
            "Priority indicates what to place earlier in your review list, not medical urgency. MediMind does not set clinical deadlines. "
            "You choose reminder dates; seek urgent care based on symptoms and professional guidance, not this queue."
        ),
    }
