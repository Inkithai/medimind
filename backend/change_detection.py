"""Deterministic, evidence-linked change detection across patient records.

This module deliberately avoids an LLM. It compares consecutive dated visits
from the assembled patient timeline and describes only changes supported by
structured extraction. In particular, a medication missing from a later
record is *not* called "stopped": medical documents are often incomplete and
an omission is not evidence of discontinuation.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

try:
    from dateutil import parser as date_parser
except ImportError:  # pragma: no cover - production requirements include dateutil
    date_parser = None


_NUMBER = re.compile(r"[-+]?\d+(?:\.\d+)?")


def _date(value: Any) -> Optional[datetime]:
    if not value or not isinstance(value, str):
        return None
    if date_parser is not None:
        try:
            # Record ordering is day-level; strip timezone metadata so mixed
            # offset-aware and date-only extractions remain sortable.
            return date_parser.parse(value, fuzzy=True).replace(tzinfo=None)
        except (TypeError, ValueError, OverflowError):
            pass
    # Keep the engine useful in minimal/offline environments too.
    normalized = value.strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized).replace(tzinfo=None)
    except ValueError:
        pass
    for pattern in ("%d %b %Y", "%d %B %Y", "%b %d %Y", "%B %d %Y", "%d/%m/%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(value.strip().replace(",", ""), pattern)
        except ValueError:
            continue
    return None


def _number(value: Any) -> Optional[float]:
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str):
        return None
    match = _NUMBER.search(value.replace(",", ""))
    if not match:
        return None
    try:
        return float(match.group())
    except ValueError:
        return None


def _key(value: Any) -> str:
    """Conservative matching key; punctuation/case differences are ignored."""
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def _medication_key(medication: Dict[str, Any]) -> str:
    ingredients = sorted(_key(item) for item in medication.get("ingredients", []) if _key(item))
    return " + ".join(ingredients) if ingredients else _key(medication.get("name"))


def _source(visit: Dict[str, Any]) -> Dict[str, Any]:
    raw_source = visit.get("_source") or {}
    return {
        "date": visit.get("date"),
        "source_file": raw_source.get("file"),
        "document_url": visit.get("document_url"),
    }


def _evidence(before: Dict[str, Any], after: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [_source(before), _source(after)]


def _display_number(value: float) -> str:
    return f"{value:g}"


def _medication_changes(before: Dict[str, Any], after: Dict[str, Any]) -> List[Dict[str, Any]]:
    old_meds = {_medication_key(m): m for m in before.get("medications", []) if _medication_key(m)}
    new_meds = {_medication_key(m): m for m in after.get("medications", []) if _medication_key(m)}
    changes: List[Dict[str, Any]] = []

    # Only compare medication lists when both documents actually contain one.
    # A lab report with no medication section must not imply discontinuation.
    if not old_meds or not new_meds:
        return changes

    for key, med in new_meds.items():
        if key not in old_meds:
            name = med.get("name") or key
            changes.append({
                "category": "medication",
                "kind": "newly_documented",
                "importance": "review",
                "title": f"{name} appears in the newer medication list",
                "description": (
                    "This medicine was not listed in the preceding comparable record. "
                    "That supports ‘newly documented’, but does not prove when it was started."
                ),
                "before": None,
                "after": med.get("dosage") or med.get("frequency") or "Listed",
                "evidence": _evidence(before, after),
            })
            continue

        old = old_meds[key]
        fields = ("dosage", "frequency", "duration")
        modified = [field for field in fields if _key(old.get(field)) != _key(med.get(field))]
        if modified:
            name = med.get("name") or old.get("name") or key
            old_instruction = ", ".join(str(old.get(f)) for f in fields if old.get(f)) or "No instruction extracted"
            new_instruction = ", ".join(str(med.get(f)) for f in fields if med.get(f)) or "No instruction extracted"
            changes.append({
                "category": "medication",
                "kind": "instruction_changed",
                "importance": "attention",
                "title": f"Instructions changed for {name}",
                "description": f"The extracted {', '.join(modified)} differs between these records.",
                "before": old_instruction,
                "after": new_instruction,
                "evidence": _evidence(before, after),
            })

    return changes


def _lab_changes(before: Dict[str, Any], after: Dict[str, Any]) -> List[Dict[str, Any]]:
    old_labs = {_key(lab.get("test_name")): lab for lab in before.get("lab_results", []) if _key(lab.get("test_name"))}
    new_labs = {_key(lab.get("test_name")): lab for lab in after.get("lab_results", []) if _key(lab.get("test_name"))}
    changes: List[Dict[str, Any]] = []

    if not old_labs or not new_labs:
        return changes

    for key, lab in new_labs.items():
        old = old_labs.get(key)
        if old is None:
            changes.append({
                "category": "lab",
                "kind": "newly_measured",
                "importance": "info",
                "title": f"{lab.get('test_name') or key} is newly shown",
                "description": "This test appears in the newer report but not the preceding lab report.",
                "before": None,
                "after": f"{lab.get('value', 'Unknown')} {lab.get('unit') or ''}".strip(),
                "evidence": _evidence(before, after),
            })
            continue

        old_value = _number(old.get("value"))
        new_value = _number(lab.get("value"))
        # Never calculate a numeric delta across unlike units. Unit
        # conversion needs test-specific clinical knowledge and belongs in a
        # separately validated layer.
        units_comparable = _key(old.get("unit")) == _key(lab.get("unit"))
        old_flag = _key(old.get("flag")) or "unknown"
        new_flag = _key(lab.get("flag")) or "unknown"
        name = lab.get("test_name") or old.get("test_name") or key
        unit = lab.get("unit") or old.get("unit") or ""

        if old_flag != new_flag:
            important = new_flag in {"high", "low"} and old_flag == "normal"
            changes.append({
                "category": "lab",
                "kind": "status_changed",
                "importance": "attention" if important else "review",
                "title": f"{name} changed from {old_flag} to {new_flag}",
                "description": "The status is taken from each report’s extracted reference-range flag.",
                "before": f"{old.get('value', 'Unknown')} {unit} ({old_flag})".strip(),
                "after": f"{lab.get('value', 'Unknown')} {unit} ({new_flag})".strip(),
                "evidence": _evidence(before, after),
            })
        elif units_comparable and old_value is not None and new_value is not None and old_value != new_value:
            delta = new_value - old_value
            percent = (delta / abs(old_value) * 100) if old_value else None
            direction = "increased" if delta > 0 else "decreased"
            percent_text = f" ({abs(percent):.1f}%)" if percent is not None else ""
            changes.append({
                "category": "lab",
                "kind": "value_changed",
                "importance": "review" if old_flag in {"high", "low"} else "info",
                "title": f"{name} {direction}{percent_text}",
                "description": (
                    f"A change of {_display_number(abs(delta))} {unit}".strip()
                    + ". Clinical meaning depends on context and the laboratory’s reference range."
                ),
                "before": f"{_display_number(old_value)} {unit}".strip(),
                "after": f"{_display_number(new_value)} {unit}".strip(),
                "evidence": _evidence(before, after),
            })

    return changes


def _allergy_changes(before: Dict[str, Any], after: Dict[str, Any]) -> List[Dict[str, Any]]:
    old = {_key(item) for item in (before.get("allergies_noted") or []) if _key(item)}
    changes = []
    for allergy in after.get("allergies_noted") or []:
        if _key(allergy) and _key(allergy) not in old:
            changes.append({
                "category": "allergy",
                "kind": "newly_documented",
                "importance": "attention",
                "title": f"Allergy newly documented: {allergy}",
                "description": "This allergy appears in the newer record and was not extracted from the preceding record.",
                "before": None,
                "after": allergy,
                "evidence": _evidence(before, after),
            })
    return changes


def _compare(before: Dict[str, Any], after: Dict[str, Any]) -> Dict[str, Any]:
    changes = (
        _lab_changes(before, after)
        + _medication_changes(before, after)
        + _allergy_changes(before, after)
    )
    order = {"attention": 0, "review": 1, "info": 2}
    changes.sort(key=lambda item: (order.get(item["importance"], 9), item["category"], item["title"]))
    return {
        "from_date": before.get("date"),
        "to_date": after.get("date"),
        "from_source": _source(before),
        "to_source": _source(after),
        "changes": changes,
        "change_count": len(changes),
    }


def detect_record_changes(timeline: Dict[str, Any]) -> Dict[str, Any]:
    """Compare consecutive dated visits and return newest comparison first."""
    dated: List[Tuple[datetime, int, Dict[str, Any]]] = []
    for index, visit in enumerate(timeline.get("visits", [])):
        parsed = _date(visit.get("date"))
        if parsed is not None:
            dated.append((parsed, index, visit))
    dated.sort(key=lambda item: (item[0], item[1]))

    comparisons = [_compare(dated[i - 1][2], dated[i][2]) for i in range(1, len(dated))]
    comparisons.reverse()
    total = sum(item["change_count"] for item in comparisons)
    attention = sum(
        1 for comparison in comparisons for change in comparison["changes"]
        if change["importance"] == "attention"
    )

    return {
        "latest": comparisons[0] if comparisons else None,
        "comparisons": comparisons,
        "summary": {
            "dated_records": len(dated),
            "comparisons": len(comparisons),
            "changes_found": total,
            "attention_items": attention,
        },
        "method": "Deterministic comparison of structured fields; no generative model is used.",
        "note": (
            "A record may be incomplete. ‘Newly documented’ does not prove a medicine was started on that date, "
            "and an omitted medicine is never treated as stopped. Do not change treatment without a clinician."
        ),
    }
