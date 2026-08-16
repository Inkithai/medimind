"""Deterministic longitudinal medication findings and source attribution.

The LLM handles clinical interaction reasoning. This module handles facts that
can be derived directly from the normalized timeline: whether the same active
ingredient continued unchanged or its recorded dose/frequency changed, and
which uploaded documents support every cross-check finding.
"""

from collections import defaultdict
from typing import Any, Dict, Iterable, List, Optional, Tuple


def _medication_key(medication: Dict[str, Any]) -> Tuple[str, ...]:
    ingredients = [
        str(value).strip().lower()
        for value in medication.get("ingredients") or []
        if str(value).strip()
    ]
    if ingredients:
        return tuple(sorted(set(ingredients)))
    name = str(medication.get("name") or "").strip().lower()
    return (name,) if name else ()


def _display_name(medication: Dict[str, Any], key: Tuple[str, ...]) -> str:
    name = str(medication.get("name") or "").strip()
    return name or " / ".join(part.title() for part in key)


def _source_ref(entry: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "date": entry.get("date"),
        "source_file": entry.get("source_file"),
        "page": entry.get("source_page"),
    }


def _instruction(entry: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "dosage": entry.get("dosage"),
        "dosage_value": entry.get("dosage_value"),
        "dosage_unit": entry.get("dosage_unit"),
        "frequency": entry.get("frequency"),
        "frequency_per_day": entry.get("frequency_per_day"),
        "is_as_needed": bool(entry.get("is_as_needed", False)),
        **_source_ref(entry),
    }


def _confidence(entry: Dict[str, Any]) -> float:
    value = entry.get("confidence", 0.7)
    return float(value) if isinstance(value, (int, float)) else 0.7


def _normalized_signature(entry: Dict[str, Any]) -> Tuple[Any, ...]:
    """Comparable instruction signature, preferring normalized values."""
    dose = (
        entry.get("dosage_value"),
        str(entry.get("dosage_unit") or "").strip().lower(),
    )
    if dose[0] is None or not dose[1]:
        dose = (str(entry.get("dosage") or "").strip().lower(), "printed")
    frequency = entry.get("frequency_per_day")
    if frequency is None:
        frequency = str(entry.get("frequency") or "").strip().lower()
    return dose + (frequency, bool(entry.get("is_as_needed", False)))


def _changed_fields(previous: Dict[str, Any], current: Dict[str, Any]) -> List[str]:
    changed: List[str] = []
    previous_signature = _normalized_signature(previous)
    current_signature = _normalized_signature(current)
    if previous_signature[:2] != current_signature[:2]:
        changed.append("dosage")
    if previous_signature[2:] != current_signature[2:]:
        changed.append("frequency")
    return changed


def detect_medication_transitions(timeline: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
    """Detect recorded changes and continuations across distinct visits.

    Findings describe what the uploaded documents say; they do not infer that
    a clinician intentionally changed or renewed treatment.
    """
    groups: Dict[Tuple[str, ...], List[Dict[str, Any]]] = defaultdict(list)
    for medication in timeline.get("medications_timeline", []) or []:
        key = _medication_key(medication)
        if key:
            groups[key].append(medication)

    changes: List[Dict[str, Any]] = []
    continuations: List[Dict[str, Any]] = []
    seen_pairs = set()
    for key, occurrences in groups.items():
        for previous, current in zip(occurrences, occurrences[1:], strict=False):
            previous_source = (previous.get("date"), previous.get("source_file"), previous.get("source_page"))
            current_source = (current.get("date"), current.get("source_file"), current.get("source_page"))
            pair_key = (key, previous_source, current_source)
            if previous_source == current_source or pair_key in seen_pairs:
                continue
            seen_pairs.add(pair_key)
            medication_name = _display_name(current, key)
            changed_fields = _changed_fields(previous, current)
            finding = {
                "medication": medication_name,
                "previous": _instruction(previous),
                "current": _instruction(current),
                "sources": [_source_ref(previous), _source_ref(current)],
                "confidence": round(
                    min(
                        _confidence(previous),
                        _confidence(current),
                        0.97,
                    ),
                    2,
                ),
            }
            if changed_fields:
                changes.append({
                    **finding,
                    "changed_fields": changed_fields,
                    "explanation": (
                        f"The recorded {' and '.join(changed_fields)} for {medication_name} differs "
                        "between these visits. This is an observation from the documents, not an "
                        "instruction to change treatment. Confirm the intended instructions with the "
                        "prescriber or pharmacist."
                    ),
                })
            else:
                continuations.append({
                    **finding,
                    "explanation": (
                        f"{medication_name} appears in consecutive visits with the same normalized "
                        "dose and frequency. This may represent continuation, but the prescriber or "
                        "pharmacist should confirm whether it remains current."
                    ),
                })

    return {"medication_changes": changes, "medication_continuations": continuations}


def _matches_name(entry: Dict[str, Any], names: Iterable[str]) -> bool:
    haystack = " ".join([
        str(entry.get("name") or ""),
        *[str(value) for value in entry.get("ingredients") or []],
    ]).lower().strip()
    if not haystack:
        return False
    return any(str(name).strip().lower() in haystack or haystack in str(name).strip().lower() for name in names if str(name).strip())


def _unique_sources(entries: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    sources: List[Dict[str, Any]] = []
    seen = set()
    for entry in entries:
        source = _source_ref(entry)
        key = (source["date"], source["source_file"], source["page"])
        if key in seen or not source["source_file"]:
            continue
        seen.add(key)
        sources.append(source)
    return sources


def enrich_cross_check_sources(report: Dict[str, Any], timeline: Dict[str, Any]) -> Dict[str, Any]:
    """Attach traceable source documents/pages to every safety finding."""
    medications = timeline.get("medications_timeline", []) or []
    visits = timeline.get("visits", []) or []

    for interaction in report.get("potential_drug_interactions", []) or []:
        names = interaction.get("medications_involved") or []
        resolved = _unique_sources(entry for entry in medications if _matches_name(entry, names))
        if resolved:
            interaction["sources"] = resolved
        else:
            interaction.setdefault("sources", [])

    for conflict in report.get("allergy_conflicts", []) or []:
        name = conflict.get("medication") or ""
        allergy = str(conflict.get("allergy") or "").strip().lower()
        medication_entries = [entry for entry in medications if _matches_name(entry, [name])]
        allergy_entries = []
        for visit in visits:
            noted = [str(value).strip().lower() for value in visit.get("allergies_noted", []) or []]
            if allergy and any(allergy in value or value in allergy for value in noted if value):
                source = visit.get("_source", {}) or {}
                allergy_entries.append({
                    "date": visit.get("date"),
                    "source_file": source.get("file"),
                    "source_page": source.get("page"),
                })
        resolved = _unique_sources([*medication_entries, *allergy_entries])
        if resolved:
            conflict["sources"] = resolved
        else:
            conflict.setdefault("sources", [])

    # Existing duplicate/conflict shapes already contain source rows. Add the
    # page when it can be resolved from the flattened medication timeline.
    for duplicate in report.get("duplicate_prescriptions", []) or []:
        for occurrence in duplicate.get("occurrences", []) or []:
            if not occurrence.get("page"):
                occurrence["page"] = _find_page(medications, occurrence)
    for conflict in report.get("conflicting_dosage_instructions", []) or []:
        for instruction in conflict.get("conflicting_instructions", []) or []:
            if not instruction.get("page"):
                instruction["page"] = _find_page(medications, instruction)

    return report


def _find_page(entries: List[Dict[str, Any]], source: Dict[str, Any]) -> Optional[int]:
    for entry in entries:
        if (
            entry.get("source_file") == source.get("source_file")
            and entry.get("date") == source.get("date")
        ):
            page = entry.get("source_page")
            return int(page) if isinstance(page, int) else None
    return None
