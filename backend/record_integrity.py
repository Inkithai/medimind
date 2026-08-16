"""Deterministic cross-document record-integrity checks.

These checks surface discrepancies for human verification. They never decide
which source is correct, rewrite the patient record, or call a discrepancy a
clinical diagnosis. Checks are intentionally limited to structured fields
where both sides can be cited.
"""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime
from typing import Any, DefaultDict, Dict, Iterable, List, Optional, Tuple

try:
    from dateutil import parser as date_parser  # noqa: F401  (presence check only)
    from date_convention import infer_dayfirst, parse_mixed_date
except ImportError:  # pragma: no cover
    date_parser = None


_NO_ALLERGY = {
    "nkda",
    "nka",
    "no known allergies",
    "no known drug allergies",
    "no known medication allergies",
}
_NAME_TITLES = {"mr", "mrs", "ms", "miss", "dr", "master", "patient"}


def _key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def _canonical_date(value: Any, dayfirst: bool = True) -> Optional[str]:
    if not value or not isinstance(value, str):
        return None
    if date_parser is not None:
        # Same record-level day/month convention as the rest of the
        # pipeline: same-document grouping must agree with the timeline
        # sort and the risk windows on ambiguous dates like "03/11/2025".
        parsed = parse_mixed_date(value, dayfirst=dayfirst)
        if parsed is not None:
            return parsed.isoformat()
    value = value.strip()
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        pass
    for pattern in ("%d %b %Y", "%d %B %Y", "%b %d %Y", "%B %d %Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(value.replace(",", ""), pattern).date().isoformat()
        except ValueError:
            continue
    return None


def _source(visit: Dict[str, Any]) -> Dict[str, Any]:
    raw = visit.get("_source") or {}
    return {
        "date": visit.get("date"),
        "source_file": raw.get("file"),
        "document_url": visit.get("document_url"),
    }


def _dedupe_sources(items: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    result = []
    for item in items:
        marker = (item.get("date"), item.get("source_file"), item.get("document_url"))
        if marker in seen:
            continue
        seen.add(marker)
        result.append(item)
    return result


def _name_parts(value: Any) -> Tuple[str, ...]:
    return tuple(part for part in _key(value).split() if part not in _NAME_TITLES)


def _same_person_name(left: Tuple[str, ...], right: Tuple[str, ...]) -> bool:
    if left == right:
        return True
    if len(left) >= 2 and len(right) >= 2:
        # Treat matching first + last names as the same identity when one
        # record includes middle names/initials and another does not.
        return left[0] == right[0] and left[-1] == right[-1]
    return False


def _medication_key(medication: Dict[str, Any]) -> str:
    ingredients = sorted(_key(item) for item in medication.get("ingredients", []) if _key(item))
    return " + ".join(ingredients) if ingredients else _key(medication.get("name"))


def _confidence(visits: Iterable[Dict[str, Any]], default: float = 0.75) -> float:
    values = [
        float(visit["overall_confidence"])
        for visit in visits
        if isinstance(visit.get("overall_confidence"), (int, float))
    ]
    value = min(values) if values else default
    return round(max(0.0, min(value, 1.0)), 2)


def _issue(
    category: str,
    severity: str,
    title: str,
    explanation: str,
    variants: List[Dict[str, Any]],
    action: str,
    confidence: float,
) -> Dict[str, Any]:
    return {
        "category": category,
        "severity": severity,
        "title": title,
        "explanation": explanation,
        "variants": variants,
        "suggested_action": action,
        "confidence": confidence,
    }


def _identity_issues(visits: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    named = [(visit, _name_parts(visit.get("patient_name"))) for visit in visits if _name_parts(visit.get("patient_name"))]
    groups: List[List[Tuple[Dict[str, Any], Tuple[str, ...]]]] = []
    for item in named:
        for group in groups:
            if _same_person_name(item[1], group[0][1]):
                group.append(item)
                break
        else:
            groups.append([item])
    if len(groups) < 2:
        return []

    variants = []
    all_visits = []
    for group in groups:
        group_visits = [item[0] for item in group]
        all_visits.extend(group_visits)
        variants.append({
            "label": "Patient name",
            "value": group[0][0].get("patient_name"),
            "evidence": _dedupe_sources(_source(visit) for visit in group_visits),
        })
    return [_issue(
        "identity", "important", "Possible patient identity mismatch",
        "Uploaded records contain patient names that do not match on first and last name. This may indicate a mixed-patient workspace or an extraction error.",
        variants,
        "Verify the names against the original documents before relying on combined trends or answers.",
        _confidence(all_visits),
    )]


def _lab_issues(visits: List[Dict[str, Any]], dayfirst: bool = True) -> List[Dict[str, Any]]:
    groups: DefaultDict[Tuple[str, str], List[Tuple[Dict[str, Any], Dict[str, Any]]]] = defaultdict(list)
    for visit in visits:
        date = _canonical_date(visit.get("date"), dayfirst=dayfirst)
        if not date:
            continue
        for lab in visit.get("lab_results", []) or []:
            test = _key(lab.get("test_name"))
            if test:
                groups[(date, test)].append((visit, lab))

    issues = []
    for (date, _), entries in groups.items():
        if len(entries) < 2:
            continue
        values: DefaultDict[Tuple[str, str], List[Tuple[Dict[str, Any], Dict[str, Any]]]] = defaultdict(list)
        for visit, lab in entries:
            values[(_key(lab.get("value")), _key(lab.get("unit")))].append((visit, lab))
        if len(values) < 2:
            continue
        test_name = entries[0][1].get("test_name") or "Lab result"
        variants = []
        units = set()
        for (_, unit_key), group in values.items():
            lab = group[0][1]
            units.add(unit_key)
            display = f"{lab.get('value', 'Unknown')} {lab.get('unit') or ''}".strip()
            variants.append({
                "label": f"{test_name} on {date}",
                "value": display,
                "evidence": _dedupe_sources(_source(visit) for visit, _lab in group),
            })
        units_differ = len(units) > 1
        issues.append(_issue(
            "lab", "review", f"Same-date {test_name} results differ",
            (
                "The same test and date appear with different values or units. They could be separate samples, a unit conversion, a corrected result, or an extraction error."
                if units_differ else
                "The same test and date appear with different values. They could be separate samples, a corrected result, or an extraction error."
            ),
            variants,
            "Compare the original reports, including collection times and units; ask the laboratory or clinician which result should be used.",
            _confidence(visit for visit, _lab in entries),
        ))
    return issues


def _medication_issues(visits: List[Dict[str, Any]], dayfirst: bool = True) -> List[Dict[str, Any]]:
    groups: DefaultDict[Tuple[str, str], List[Tuple[Dict[str, Any], Dict[str, Any]]]] = defaultdict(list)
    for visit in visits:
        date = _canonical_date(visit.get("date"), dayfirst=dayfirst)
        if not date:
            continue
        for medication in visit.get("medications", []) or []:
            med_key = _medication_key(medication)
            if med_key:
                groups[(date, med_key)].append((visit, medication))

    issues = []
    for (date, _), entries in groups.items():
        if len(entries) < 2:
            continue
        instructions: DefaultDict[Tuple[str, str], List[Tuple[Dict[str, Any], Dict[str, Any]]]] = defaultdict(list)
        for visit, med in entries:
            dosage, frequency = _key(med.get("dosage")), _key(med.get("frequency"))
            # Missing instructions are incomplete evidence, not a conflict.
            if dosage and frequency:
                instructions[(dosage, frequency)].append((visit, med))
        if len(instructions) < 2:
            continue
        name = entries[0][1].get("name") or "Medication"
        variants = []
        included_visits = []
        for group in instructions.values():
            med = group[0][1]
            included_visits.extend(visit for visit, _med in group)
            variants.append({
                "label": f"{name} instruction on {date}",
                "value": f"{med.get('dosage')} · {med.get('frequency')}",
                "evidence": _dedupe_sources(_source(visit) for visit, _med in group),
            })
        issues.append(_issue(
            "medication", "important", f"Same-date instructions differ for {name}",
            "Records dated the same day contain different complete dosage/frequency instructions for the same medication or active ingredient.",
            variants,
            "Verify the original prescription and ask a clinician or pharmacist which instruction is intended before making any change.",
            _confidence(included_visits),
        ))
    return issues


def _allergy_issues(visits: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    negatives = []
    positives = []
    for visit in visits:
        for allergy in visit.get("allergies_noted", []) or []:
            item = (visit, allergy)
            if _key(allergy) in _NO_ALLERGY:
                negatives.append(item)
            elif _key(allergy):
                positives.append(item)
    if not negatives or not positives:
        return []
    return [_issue(
        "allergy", "important", "Allergy statements conflict across records",
        "At least one record says there are no known allergies while another names a specific allergy.",
        [
            {
                "label": "No-allergy statement",
                "value": negatives[0][1],
                "evidence": _dedupe_sources(_source(visit) for visit, _value in negatives),
            },
            {
                "label": "Documented allergies",
                "value": ", ".join(sorted({str(value) for _visit, value in positives})),
                "evidence": _dedupe_sources(_source(visit) for visit, _value in positives),
            },
        ],
        "Confirm the allergy history with the patient and clinician; do not remove an allergy based only on a conflicting document.",
        _confidence([visit for visit, _value in negatives + positives]),
    )]


def check_record_integrity(timeline: Dict[str, Any]) -> Dict[str, Any]:
    """Return all source-linked discrepancies in a patient timeline."""
    visits = timeline.get("visits", []) or []
    dayfirst = infer_dayfirst([visit.get("date") for visit in visits]) if date_parser else True
    issues = (
        _identity_issues(visits)
        + _allergy_issues(visits)
        + _medication_issues(visits, dayfirst=dayfirst)
        + _lab_issues(visits, dayfirst=dayfirst)
    )
    category_order = {"identity": 0, "allergy": 1, "medication": 2, "lab": 3}
    severity_order = {"important": 0, "review": 1}
    issues.sort(key=lambda item: (severity_order.get(item["severity"], 9), category_order.get(item["category"], 9), item["title"]))
    for index, item in enumerate(issues, 1):
        item["id"] = f"integrity-{index}"

    important = sum(item["severity"] == "important" for item in issues)
    return {
        "status": "needs_verification" if issues else "no_discrepancies_found",
        "summary": {
            "records_checked": len(visits),
            "issues_found": len(issues),
            "important_issues": important,
        },
        "issues": issues,
        "checks_performed": [
            "patient identity consistency",
            "same-date lab result consistency",
            "same-date medication instruction consistency",
            "allergy statement consistency",
        ],
        "method": "Deterministic comparison of structured fields; no generative model chooses which source is correct.",
        "note": (
            "A discrepancy is a prompt to verify the original records, not proof that either source is wrong. "
            "Different collection times, corrected reports, unit conversions, and extraction uncertainty can explain apparent conflicts."
        ),
    }
