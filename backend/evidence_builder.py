"""Deterministic source-linked evidence for MediMind care recommendations.

This module turns an already-derived clinical flag into concise evidence from
that same patient's saved timeline, cross-check report, and lab trends. It
never calls an LLM, a provider directory, or a database. Provider discovery
remains deliberately separate from clinical evidence.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urlparse

EvidenceItem = Dict[str, Any]


def _text(value: Any) -> str:
    return str(value or "").strip()


def _normalise(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", _text(value).lower()).strip()


def _number(value: Any) -> Optional[float]:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None


def _safe_document_url(value: Any) -> Optional[str]:
    """Only expose an existing browser-safe absolute document URL.

    Uploaded source files already use Cloudinary secure URLs. The evidence
    layer must never manufacture a URL from a filename or expose a local path.
    """
    url = _text(value)
    if not url:
        return None
    parsed = urlparse(url)
    return url if parsed.scheme in {"https", "http"} and bool(parsed.netloc) else None


def _optional(target: EvidenceItem, key: str, value: Any) -> None:
    if value is None:
        return
    if isinstance(value, str) and not value.strip():
        return
    target[key] = value


def _item(kind: str, label: str, **fields: Any) -> Optional[EvidenceItem]:
    """Build a response item only when it has a real source label."""
    if not _text(label):
        return None
    item: EvidenceItem = {"kind": kind, "label": _text(label)}
    for key, value in fields.items():
        _optional(item, key, value)
    return item


def _source_visits(
    timeline: Dict[str, Any], source_file: Any, date: Any = None
) -> List[Dict[str, Any]]:
    filename = _text(source_file)
    if not filename:
        return []
    candidates = [
        visit
        for visit in (timeline.get("visits") or [])
        if isinstance(visit, dict) and _text((visit.get("_source") or {}).get("file")) == filename
    ]
    date_text = _text(date)
    dated = [visit for visit in candidates if date_text and _text(visit.get("date")) == date_text]
    return dated or candidates


def _document_fields(
    timeline: Dict[str, Any], source_file: Any, date: Any = None
) -> Dict[str, Any]:
    """Return existing source metadata for a timeline file without guessing."""
    fields: Dict[str, Any] = {}
    filename = _text(source_file)
    if filename:
        fields["source_file"] = filename
    date_text = _text(date)
    if date_text:
        fields["date"] = date_text

    visits = _source_visits(timeline, filename, date_text)
    if visits:
        visit = visits[0]
        if not fields.get("date") and _text(visit.get("date")):
            fields["date"] = _text(visit.get("date"))
        document_url = _safe_document_url(visit.get("document_url"))
        if document_url:
            fields["document_url"] = document_url
        page = (visit.get("_source") or {}).get("page")
        if isinstance(page, int) and page > 0:
            fields["page"] = page
    return fields


def _medication_matches(medication: Dict[str, Any], requested_name: Any) -> bool:
    target = _normalise(requested_name)
    if not target:
        return False
    names = [_normalise(medication.get("name"))]
    names.extend(_normalise(ingredient) for ingredient in (medication.get("ingredients") or []))
    return target in names


def _medication_item(
    timeline: Dict[str, Any], medication: Dict[str, Any]
) -> Optional[EvidenceItem]:
    name = _text(medication.get("name"))
    source = _document_fields(timeline, medication.get("source_file"), medication.get("date"))
    confidence = _number(medication.get("confidence"))
    details = " · ".join(
        part
        for part in [_text(medication.get("dosage")), _text(medication.get("frequency"))]
        if part
    )
    return _item(
        "medication",
        name,
        **source,
        confidence=confidence,
        details=details or None,
    )


def _lab_item(timeline: Dict[str, Any], lab: Dict[str, Any]) -> Optional[EvidenceItem]:
    name = _text(lab.get("test_name"))
    source = _document_fields(timeline, lab.get("source_file"), lab.get("date"))
    value = _text(lab.get("value"))
    unit = _text(lab.get("unit"))
    details = " ".join(part for part in [value, unit] if part)
    return _item(
        "lab_result",
        name,
        **source,
        confidence=_number(lab.get("confidence")),
        details=details or None,
    )


def _document_item(timeline: Dict[str, Any], visit: Dict[str, Any]) -> Optional[EvidenceItem]:
    source = _document_fields(timeline, (visit.get("_source") or {}).get("file"), visit.get("date"))
    label = _text(source.get("source_file")) or _text(visit.get("document_type"))
    return _item(
        "document",
        label,
        **source,
        confidence=_number(visit.get("overall_confidence")),
    )


def _allergy_item(timeline: Dict[str, Any], allergy: Any) -> Optional[EvidenceItem]:
    allergy_text = _text(allergy)
    if not allergy_text:
        return None
    for visit in timeline.get("visits") or []:
        if not isinstance(visit, dict):
            continue
        if allergy_text in {_text(value) for value in (visit.get("allergies_noted") or [])}:
            source = _document_fields(
                timeline, (visit.get("_source") or {}).get("file"), visit.get("date")
            )
            return _item(
                "allergy",
                allergy_text,
                **source,
                confidence=_number(visit.get("overall_confidence")),
            )
    # The allergy exists in known_allergies but no visit source is available.
    # Keep the real value, but do not invent a filename or link.
    return _item("allergy", allergy_text)


def _cross_check_item(
    label: str,
    issue: Dict[str, Any],
    *,
    timeline: Dict[str, Any],
    source_file: Any = None,
    date: Any = None,
    details: Any = None,
) -> Optional[EvidenceItem]:
    source = _document_fields(timeline, source_file, date)
    return _item(
        "cross_check",
        label,
        **source,
        confidence=_number(issue.get("confidence")),
        details=_text(details) or _text(issue.get("explanation")) or None,
    )


def _trend_item(trend: Dict[str, Any]) -> Optional[EvidenceItem]:
    test_name = _text(trend.get("test_name"))
    return _item(
        "lab_trend",
        test_name,
        confidence=_number(trend.get("confidence")),
        details=_text(trend.get("explanation")) or None,
    )


def _flag_index(flag_id: Any, prefix: str) -> Optional[int]:
    match = re.fullmatch(re.escape(prefix) + r"(\d+)", _text(flag_id))
    return int(match.group(1)) if match else None


def _deduplicate(items: Iterable[Optional[EvidenceItem]]) -> List[EvidenceItem]:
    result: List[EvidenceItem] = []
    seen: set[Tuple[Any, ...]] = set()
    for item in items:
        if item is None:
            continue
        key = (
            item.get("kind"),
            item.get("label"),
            item.get("source_file"),
            item.get("date"),
            item.get("details"),
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _interaction_evidence(
    flag: Dict[str, Any], timeline: Dict[str, Any], cross_check: Dict[str, Any]
) -> List[EvidenceItem]:
    index = _flag_index(flag.get("id"), "interaction-")
    if index is None:
        index = _flag_index(flag.get("id"), "potential_drug_interactions-confidence-")
    issues = cross_check.get("potential_drug_interactions") or []
    if index is None or index >= len(issues) or not isinstance(issues[index], dict):
        return []
    issue = issues[index]
    items: List[Optional[EvidenceItem]] = []
    involved = issue.get("medications_involved") or []
    for medication_name in involved:
        for medication in timeline.get("medications_timeline") or []:
            if isinstance(medication, dict) and _medication_matches(medication, medication_name):
                items.append(_medication_item(timeline, medication))
    items.append(_cross_check_item("Potential interaction detected", issue, timeline=timeline))
    return _deduplicate(items)


def _allergy_conflict_evidence(
    flag: Dict[str, Any], timeline: Dict[str, Any], cross_check: Dict[str, Any]
) -> List[EvidenceItem]:
    index = _flag_index(flag.get("id"), "allergy-")
    issues = cross_check.get("allergy_conflicts") or []
    if index is None or index >= len(issues) or not isinstance(issues[index], dict):
        return []
    issue = issues[index]
    items: List[Optional[EvidenceItem]] = []
    medication_name = issue.get("medication")
    for medication in timeline.get("medications_timeline") or []:
        if isinstance(medication, dict) and _medication_matches(medication, medication_name):
            items.append(_medication_item(timeline, medication))
    items.append(_allergy_item(timeline, issue.get("allergy")))
    items.append(_cross_check_item("Potential allergy conflict detected", issue, timeline=timeline))
    return _deduplicate(items)


def _medication_evidence(flag: Dict[str, Any], timeline: Dict[str, Any]) -> List[EvidenceItem]:
    index = _flag_index(flag.get("id"), "medication-confidence-")
    medications = timeline.get("medications_timeline") or []
    if index is None or index >= len(medications) or not isinstance(medications[index], dict):
        return []
    return _deduplicate([_medication_item(timeline, medications[index])])


def _visit_evidence(flag: Dict[str, Any], timeline: Dict[str, Any]) -> List[EvidenceItem]:
    index = _flag_index(flag.get("id"), "visit-confidence-")
    visits = timeline.get("visits") or []
    if index is None or index >= len(visits) or not isinstance(visits[index], dict):
        return []
    return _deduplicate([_document_item(timeline, visits[index])])


def _lab_evidence(flag: Dict[str, Any], timeline: Dict[str, Any]) -> List[EvidenceItem]:
    index = _flag_index(flag.get("id"), "lab-confidence-")
    labs = timeline.get("lab_results_timeline") or []
    if index is None or index >= len(labs) or not isinstance(labs[index], dict):
        return []
    return _deduplicate([_lab_item(timeline, labs[index])])


def _trend_evidence(
    flag: Dict[str, Any], timeline: Dict[str, Any], lab_trends: Dict[str, Any]
) -> List[EvidenceItem]:
    index = _flag_index(flag.get("id"), "trend-confidence-")
    trends = lab_trends.get("trends") or []
    if index is None or index >= len(trends) or not isinstance(trends[index], dict):
        return []
    trend = trends[index]
    test_name = _normalise(trend.get("test_name"))
    points = trend.get("data_points") or []
    items: List[Optional[EvidenceItem]] = [_trend_item(trend)]
    labs = timeline.get("lab_results_timeline") or []
    for point in points:
        if not isinstance(point, dict):
            continue
        found = False
        for lab in labs:
            if not isinstance(lab, dict) or _normalise(lab.get("test_name")) != test_name:
                continue
            if _text(point.get("source_file")) and _text(lab.get("source_file")) != _text(
                point.get("source_file")
            ):
                continue
            if _text(point.get("date")) and _text(lab.get("date")) != _text(point.get("date")):
                continue
            items.append(_lab_item(timeline, lab))
            found = True
            break
        if not found:
            # A trend point is already structured from this patient's lab
            # timeline. Preserve only fields the trend itself contains.
            fallback = {
                "test_name": trend.get("test_name"),
                "value": point.get("value"),
                "source_file": point.get("source_file"),
                "date": point.get("date"),
            }
            items.append(_lab_item(timeline, fallback))
    return _deduplicate(items)


def _conflict_evidence(
    flag: Dict[str, Any], timeline: Dict[str, Any], cross_check: Dict[str, Any]
) -> List[EvidenceItem]:
    index = _flag_index(flag.get("id"), "conflicting_dosage_instructions-confidence-")
    issues = cross_check.get("conflicting_dosage_instructions") or []
    if index is None or index >= len(issues) or not isinstance(issues[index], dict):
        return []
    issue = issues[index]
    medication_name = issue.get("medication")
    items: List[Optional[EvidenceItem]] = []
    instructions = issue.get("conflicting_instructions") or []
    for instruction in instructions:
        if not isinstance(instruction, dict):
            continue
        matched = False
        for medication in timeline.get("medications_timeline") or []:
            if not isinstance(medication, dict) or not _medication_matches(
                medication, medication_name
            ):
                continue
            if _text(instruction.get("source_file")) and _text(
                medication.get("source_file")
            ) != _text(instruction.get("source_file")):
                continue
            items.append(_medication_item(timeline, medication))
            matched = True
        if not matched:
            details = " · ".join(
                part
                for part in [_text(instruction.get("dosage")), _text(instruction.get("frequency"))]
                if part
            )
            items.append(
                _cross_check_item(
                    _text(medication_name) or "Conflicting dosage instruction",
                    issue,
                    timeline=timeline,
                    source_file=instruction.get("source_file"),
                    date=instruction.get("date"),
                    details=details or issue.get("explanation"),
                )
            )
    items.append(
        _cross_check_item(
            "Potential dosage or frequency conflict detected", issue, timeline=timeline
        )
    )
    return _deduplicate(items)


def _duplicate_evidence(
    flag: Dict[str, Any], timeline: Dict[str, Any], cross_check: Dict[str, Any]
) -> List[EvidenceItem]:
    index = _flag_index(flag.get("id"), "duplicate_prescriptions-confidence-")
    issues = cross_check.get("duplicate_prescriptions") or []
    if index is None or index >= len(issues) or not isinstance(issues[index], dict):
        return []
    issue = issues[index]
    items: List[Optional[EvidenceItem]] = []
    for occurrence in issue.get("occurrences") or []:
        if not isinstance(occurrence, dict):
            continue
        matches = [
            medication
            for medication in (timeline.get("medications_timeline") or [])
            if isinstance(medication, dict)
            and _medication_matches(medication, issue.get("medication"))
            and (
                not _text(occurrence.get("source_file"))
                or _text(medication.get("source_file")) == _text(occurrence.get("source_file"))
            )
        ]
        if matches:
            items.extend(_medication_item(timeline, medication) for medication in matches)
        else:
            items.append(
                _cross_check_item(
                    _text(issue.get("medication")) or "Potential duplicate prescription",
                    issue,
                    timeline=timeline,
                    source_file=occurrence.get("source_file"),
                    date=occurrence.get("date"),
                    details=occurrence.get("dosage") or issue.get("explanation"),
                )
            )
    items.append(
        _cross_check_item("Potential duplicate prescription detected", issue, timeline=timeline)
    )
    return _deduplicate(items)


def build_care_pathway_evidence(
    flag: Dict[str, Any],
    timeline: Dict[str, Any],
    cross_check: Dict[str, Any],
    lab_trends: Dict[str, Any],
) -> List[EvidenceItem]:
    """Return source-linked evidence for one existing clinical flag.

    An unknown or stale flag returns an empty list. That is intentional: the
    evidence layer must never reconstruct or infer evidence from a flag's free
    text when it cannot resolve the flag to the record that created it.
    """
    issue_type = _text(flag.get("issue_type"))
    if issue_type in {"high_severity_interaction", "low_confidence_interaction"}:
        return _interaction_evidence(flag, timeline, cross_check)
    if issue_type == "allergy_conflict":
        return _allergy_conflict_evidence(flag, timeline, cross_check)
    if issue_type == "low_confidence_medication":
        return _medication_evidence(flag, timeline)
    if issue_type == "low_confidence_document":
        return _visit_evidence(flag, timeline)
    if issue_type == "low_confidence_lab_result":
        return _lab_evidence(flag, timeline)
    if issue_type == "low_confidence_lab_trend":
        return _trend_evidence(flag, timeline, lab_trends)
    if issue_type == "low_confidence_dosage":
        return _conflict_evidence(flag, timeline, cross_check)
    if issue_type == "low_confidence_duplicate":
        return _duplicate_evidence(flag, timeline, cross_check)
    return []


def build_care_route_explanation(flag: Dict[str, Any], evidence: List[EvidenceItem]) -> str:
    """Produce safe deterministic care-route language from flag category.

    The text describes an existing record-level signal and the suggested
    reviewer category. It intentionally avoids diagnoses, urgency claims, and
    claims that any provider is the best choice.
    """
    issue_type = _text(flag.get("issue_type"))
    medication_count = len([item for item in evidence if item.get("kind") == "medication"])
    if issue_type in {"high_severity_interaction", "low_confidence_interaction"}:
        records = f" from {medication_count} medication record(s)" if medication_count else ""
        return (
            "MediMind identified a potential medication-safety issue"
            f"{records}. Because this concerns medication safety and prescription instructions, "
            "a pharmacist or prescribing clinician is suggested as the first professional to review it."  # noqa: E501
        )
    if issue_type == "allergy_conflict":
        return (
            "MediMind identified a potential medication and recorded-allergy conflict. "
            "A pharmacist or prescribing clinician is suggested to review the record and original documents."  # noqa: E501
        )
    if issue_type == "low_confidence_medication":
        return (
            "MediMind could not confidently interpret part of a medication record. "
            "A pharmacist or prescribing clinician can help verify the original prescription and instructions."  # noqa: E501
        )
    if issue_type == "low_confidence_dosage":
        return (
            "MediMind found a low-confidence dosage or frequency conflict signal. "
            "A pharmacist or prescribing clinician can review the original prescription instructions."  # noqa: E501
        )
    if issue_type == "low_confidence_lab_trend":
        return (
            "MediMind found a lab trend built from low-confidence source values. "
            "The original reports may be useful for a clinician to review before interpreting the trend."  # noqa: E501
        )
    if issue_type == "low_confidence_lab_result":
        return (
            "MediMind could not confidently interpret a lab-result record. "
            "A clinician can review the original report and its context."
        )
    if issue_type == "low_confidence_document":
        return (
            "MediMind could not confidently interpret part of an uploaded medical document. "
            "A clinician can review the original document and clarify the uncertain information."
        )
    if issue_type == "low_confidence_duplicate":
        return (
            "MediMind found a low-confidence duplicate-prescription signal. "
            "A pharmacist or prescribing clinician can review the original medication records."
        )
    return "MediMind identified an existing record-level flag that may warrant review by an appropriate healthcare professional."  # noqa: E501


def enrich_care_flag(
    flag: Dict[str, Any],
    timeline: Dict[str, Any],
    cross_check: Dict[str, Any],
    lab_trends: Dict[str, Any],
) -> Dict[str, Any]:
    """Add evidence and route text without changing the existing flag fields."""
    enriched = dict(flag)
    evidence = build_care_pathway_evidence(enriched, timeline, cross_check, lab_trends)
    enriched["pathway_evidence"] = evidence
    enriched["care_route_explanation"] = build_care_route_explanation(enriched, evidence)
    return enriched
