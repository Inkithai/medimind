"""
Medication Activity Windows — which prescriptions are still active?
====================================================================
Determines, at a reference date, whether each medication entry in a
patient's timeline is still an active prescription or whether its course
provably ended — the safety layer's equivalent of "end_date IS NULL ->
active" from dated prescription records, adapted to MediMind's
date + duration schema.

WHY THIS MATTERS
----------------
The safety cross-check (interactions, duplicates, dosage, allergies)
exists to surface *live* risk. A course of "amoxicillin 500 mg, 7 days"
prescribed three years ago is history, not a current exposure — but
without end-date awareness every medication in the record is treated as
currently taken, so long-finished courses keep driving interaction and
dosage findings for the patient's entire life.

RULES (deliberately conservative)
---------------------------------
A medication entry is classified INACTIVE only when its course provably
ended before the reference date:

  * date parseable AND duration stated ("5 days", "2 weeks", "1 month")
    AND date + duration < reference date  ->  inactive

Everything else stays ACTIVE:

  * no duration / open-ended ("as required", PRN) — there is no provable
    finish, so the course cannot be ruled out;
  * duration stated but the window still reaches the reference date;
  * unparseable date — cannot prove it ended (fail active, never fail
    silent);
  * no date at all — same.

This is the same philosophy as risk_timeline.py, whose
build_treatment_windows() this module reuses verbatim so activity and
concurrency windows can never disagree: an entry both features consider
"over" ends at the same computed date.

WHAT IT DOES NOT DO
-------------------
It never deletes data. Inactive entries remain in the timeline and in
medication history; they are excluded from live safety checks and listed
with reasons in the report so nothing is silently dropped.

Deterministic, no LLM calls.
"""

from datetime import date
from typing import Any, Dict, List, Optional, Union

from risk_timeline import build_treatment_windows

ACTIVE = "active"
INACTIVE = "inactive"


def _parse_reference_date(reference_date: Optional[Union[str, date]]) -> date:
    """Normalizes the reference date: None -> today, ISO 'YYYY-MM-DD' ->
    date, already a date -> as-is. Anything unparseable falls back to
    today rather than raising — this is an internal analysis parameter,
    and failing the whole safety report over it would be wrong."""
    if reference_date is None:
        return date.today()
    if isinstance(reference_date, date):
        return reference_date
    try:
        return date.fromisoformat(str(reference_date))
    except ValueError:
        return date.today()


def analyze_medication_activity(
    timeline: Dict[str, Any], reference_date: Optional[Union[str, date]] = None
) -> Dict[str, Any]:
    """
    Classifies every medication entry at the reference date.

    Returns:
      {
        "reference_date": "YYYY-MM-DD",
        "active_medications": [display names, in timeline order],
        "inactive_medications": [
          {"medication", "date", "duration", "end", "reason"}, ...
        ],
        "active_count": int,
        "inactive_count": int,
      }
    """
    entries = timeline.get("medications_timeline") or []
    windows = build_treatment_windows(timeline)
    ref = _parse_reference_date(reference_date)

    active: List[str] = []
    inactive: List[Dict[str, Any]] = []

    for med, window in zip(entries, windows):
        display = med.get("name") or " / ".join(med.get("ingredients") or []) or "unknown"
        start = window.get("start")
        end = window.get("end")

        if start is None:
            active.append(display)
            continue
        if end is None:
            # Open-ended (PRN) or unknown duration — no provable finish.
            active.append(display)
            continue
        if end >= ref:
            active.append(display)
            continue

        inactive.append({
            "medication": display,
            "date": med.get("date"),
            "duration": med.get("duration"),
            "end": end.isoformat(),
            "reason": (
                f"course ended on {end.isoformat()} "
                f"(duration '{med.get('duration')}') — before the reference date"
            ),
        })

    return {
        "reference_date": ref.isoformat(),
        "active_medications": active,
        "inactive_medications": inactive,
        "active_count": len(active),
        "inactive_count": len(inactive),
    }


def filter_active_timeline(
    timeline: Dict[str, Any], reference_date: Optional[Union[str, date]] = None
) -> Dict[str, Any]:
    """
    Returns a copy of the timeline whose medications_timeline contains
    only entries still active at the reference date (see the module rules).
    All other timeline sections are passed through unchanged.
    """
    entries = timeline.get("medications_timeline") or []
    windows = build_treatment_windows(timeline)
    ref = _parse_reference_date(reference_date)

    active_entries: List[Dict[str, Any]] = []
    for med, window in zip(entries, windows):
        start = window.get("start")
        end = window.get("end")
        if start is None or end is None or end >= ref:
            active_entries.append(med)

    return {**timeline, "medications_timeline": active_entries}
