"""
Medication Reconciliation (deterministic)
=========================================
medication_activity.py tells you which prescriptions are still active.
medication_history.py tells you what changed between consecutive entries.
This module answers the question a clinician actually asks at every visit and
on every discharge: "what is this patient's reconciled current medication
list, and where are the discrepancies?"

For every distinct active ingredient it classifies the state:

  * active          — supplied within an active window at the reference date
  * duplicate       — two or more ACTIVE sources supply the same ingredient
  * dose_conflict   — those duplicate sources disagree on the dose
  * discontinued    — previously supplied, course ended and never re-supplied
  * single_supply   — only one dated supply (new or historical — needs confirm)

It never invents a "stop date" the record doesn't state, and it never asserts
that a patient stopped taking something — only that the SUPPLY pattern looks
that way. Deterministic, no LLM, no diagnosis.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Optional, Set

try:
    from medication_activity import analyze_medication_activity
except Exception:  # pragma: no cover
    analyze_medication_activity = None  # type: ignore


def _ingredient_key(med: Dict[str, Any]) -> Optional[str]:
    ings = [str(i).strip().lower() for i in (med.get("ingredients") or []) if str(i).strip()]
    if ings:
        return "/".join(sorted(set(ings)))
    name = str(med.get("name") or "").strip().lower()
    return name or None


def _display(med: Dict[str, Any]) -> str:
    return med.get("name") or " / ".join(med.get("ingredients") or []) or "unknown"


def _dose_signature(med: Dict[str, Any]) -> str:
    parts = []
    for key in ("dosage", "dose", "strength", "frequency", "frequency_per_day"):
        val = med.get(key)
        if val not in (None, "", 0):
            parts.append(str(val).strip().lower())
    return "|".join(parts) or "unknown_dose"


def _parse_date(raw: Any) -> Optional[date]:
    if not raw:
        return None
    try:
        from datetime import datetime

        return datetime.fromisoformat(str(raw)[:10]).date()
    except Exception:
        return None


def reconcile_medications(timeline: Dict[str, Any], reference_date: Any = None) -> Dict[str, Any]:
    meds = list(timeline.get("medications_timeline") or [])
    if not meds:
        return {
            "reference_date": str(reference_date or date.today()),
            "reconciled_medications": [],
            "summary": {
                "total_ingredients": 0,
                "active": 0,
                "discontinued": 0,
                "duplicates": 0,
                "dose_conflicts": 0,
            },
            "note": _NOTE,
        }

    # Group every prescription line by normalized ingredient.
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for med in meds:
        key = _ingredient_key(med)
        if key:
            groups.setdefault(key, []).append(med)

    # Use the existing activity classifier to know what is active at the ref date.
    # analyze_medication_activity returns active/inactive_medications as DISPLAY
    # NAMES (strings), so we match by name/ingredient rather than by dict key.
    active_names: Set[str] = set()
    inactive_names: Set[str] = set()
    try:
        activity = analyze_medication_activity(timeline, reference_date)
        ref_str = activity.get("reference_date")
        active_names = {str(n).strip().lower() for n in (activity.get("active_medications") or [])}
        inactive_names = {
            str(n).strip().lower() for n in (activity.get("inactive_medications") or [])
        }
    except Exception:
        ref_str = str(reference_date or date.today())

    def _is_active_for(display: str, ingredient: str) -> bool:
        d = display.strip().lower()
        ing = ingredient.strip().lower()
        if d in active_names or ing in active_names:
            return True
        # tolerate display-name drift: active name contains the ingredient or vice-versa
        return any(ing and ing in an for an in active_names) or any(
            d and d in an for an in active_names
        )

    def _is_inactive_for(display: str, ingredient: str) -> bool:
        d = display.strip().lower()
        ing = ingredient.strip().lower()
        if d in inactive_names or ing in inactive_names:
            return True
        return any(ing and ing in an for an in inactive_names) or any(
            d and d in an for an in inactive_names
        )

    reconciled: List[Dict[str, Any]] = []
    counts = {"active": 0, "discontinued": 0, "duplicates": 0, "dose_conflicts": 0}

    for key, entries in groups.items():
        display = _display(entries[0])
        sources = [
            {
                "name": _display(e),
                "date": e.get("date"),
                "source_file": e.get("source_file"),
                "dose": _dose_signature(e),
            }
            for e in entries
        ]
        is_active = _is_active_for(display, key)
        active_entries = [e for e in entries if True] if is_active else []
        distinct_active_doses = {_dose_signature(e) for e in active_entries}
        dose_conflict = is_active and len(distinct_active_doses) > 1
        duplicate = is_active and len(active_entries) > 1

        # state priority
        if dose_conflict:
            state = "dose_conflict"
        elif duplicate:
            state = "duplicate"
        elif is_active:
            state = "active"
        elif _is_inactive_for(display, key):
            state = "discontinued"
        else:
            state = "single_supply"

        if state in counts:
            counts[state] += 1
        if dose_conflict:
            counts["dose_conflicts"] += 1
        elif duplicate:
            counts["duplicates"] += 1

        notes: List[str] = []
        if dose_conflict:
            notes.append(
                "Different doses for the same active ingredient are recorded concurrently — "
                "confirm the intended dose with the patient or prescriber."
            )
        elif duplicate:
            notes.append(
                "More than one active supply of this ingredient is on record — possible duplicate prescribing."  # noqa: E501
            )
        elif state == "discontinued":
            notes.append(
                "Previously supplied; no active supply at the reference date. Confirm whether it was stopped deliberately."  # noqa: E501
            )
        elif state == "single_supply":
            notes.append("Only one dated supply found — confirm whether it is current.")

        reconciled.append(
            {
                "ingredient": key,
                "display_name": _display(entries[0]),
                "state": state,
                "is_active": is_active,
                "sources": sources,
                "supply_count": len(entries),
                "active_supply_count": len(active_entries),
                "doses": sorted(distinct_active_doses)
                if is_active
                else sorted({_dose_signature(e) for e in entries}),
                "dose_conflict": dose_conflict,
                "duplicate": duplicate,
                "notes": notes,
            }
        )

    reconciled.sort(
        key=lambda r: (
            r["state"] != "dose_conflict",
            r["state"] != "duplicate",
            r["display_name"].lower(),
        )
    )

    return {
        "reference_date": ref_str,
        "reconciled_medications": reconciled,
        "summary": {
            "total_ingredients": len(reconciled),
            "active": counts["active"],
            "discontinued": counts["discontinued"],
            "duplicates": counts["duplicates"],
            "dose_conflicts": counts["dose_conflicts"],
        },
        "note": _NOTE,
    }


_NOTE = (
    "Reconciliation is inferred from the dated prescriptions on record (supply, not proof of intake). "  # noqa: E501
    "A 'duplicate' or 'dose_conflict' is a reason to check with the prescriber, not an error in your record."  # noqa: E501
)
