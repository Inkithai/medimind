"""Deterministic consultation-preparation packs for a selected MediMind flag.

The pack is a patient-facing checklist built only from the authenticated
patient's existing snapshot and source-linked care evidence. It does not call
an LLM, a provider directory, a database, or any external service. It does
not diagnose, prescribe, or make medication decisions.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urlparse

from evidence_builder import build_care_pathway_evidence

CONSULTATION_PACK_DISCLAIMER = (
    "MediMind does not diagnose conditions or replace professional medical advice. "
    "This preparation list is drawn from the uploaded record to help discuss the original information with a licensed clinician or pharmacist."  # noqa: E501
)

LOW_CONFIDENCE_THRESHOLD = 0.60


def _text(value: Any) -> str:
    return str(value or "").strip()


def _number(value: Any) -> Optional[float]:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None


def _valid_url(value: Any) -> Optional[str]:
    value = _text(value)
    if not value:
        return None
    parsed = urlparse(value)
    return value if parsed.scheme in {"https", "http"} and parsed.netloc else None


def _optional(result: Dict[str, Any], key: str, value: Any) -> None:
    if value is None:
        return
    if isinstance(value, str) and not value.strip():
        return
    result[key] = value


def _document_reason(kind: str) -> str:
    if kind == "medication":
        return "Contains medication record(s) relevant to this concern."
    if kind == "allergy":
        return "Contains a recorded allergy relevant to this concern."
    if kind == "lab_result":
        return "Contains a laboratory result relevant to this concern."
    if kind == "document":
        return "Contains information marked for review."
    if kind == "cross_check":
        return "Is referenced by the medication-safety check."
    return "Contains information relevant to this concern."


def _documents_to_bring(evidence: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Deduplicate actual source documents referenced by pathway evidence."""
    documents: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for item in evidence:
        source_file = _text(item.get("source_file"))
        if not source_file or source_file in seen:
            continue
        seen.add(source_file)
        document: Dict[str, Any] = {
            "source_file": source_file,
            "reason": _document_reason(_text(item.get("kind"))),
        }
        _optional(document, "date", _text(item.get("date")) or None)
        _optional(
            document,
            "page",
            item.get("page")
            if isinstance(item.get("page"), int) and item.get("page") > 0
            else None,
        )
        _optional(document, "document_url", _valid_url(item.get("document_url")))
        documents.append(document)
    return documents


def _same_source(item: Dict[str, Any], evidence: Dict[str, Any]) -> bool:
    if _text(evidence.get("source_file")) and _text(item.get("source_file")) != _text(
        evidence.get("source_file")
    ):
        return False
    if _text(evidence.get("date")) and _text(item.get("date")) != _text(evidence.get("date")):
        return False
    return True


def _medication_records(
    evidence: Iterable[Dict[str, Any]], timeline: Dict[str, Any]
) -> List[Dict[str, Any]]:
    """Return only medication timeline entries selected by record evidence.

    These are deliberately labelled as records to discuss, not current active
    medications: the timeline does not encode a reliable active/inactive state.
    """
    records: List[Dict[str, Any]] = []
    seen: set[Tuple[str, str, str]] = set()
    medications = timeline.get("medications_timeline") or []
    for evidence_item in evidence:
        if evidence_item.get("kind") != "medication":
            continue
        label = _text(evidence_item.get("label"))
        for medication in medications:
            if not isinstance(medication, dict) or _text(medication.get("name")) != label:
                continue
            if not _same_source(medication, evidence_item):
                continue
            key = (
                _text(medication.get("name")),
                _text(medication.get("source_file")),
                _text(medication.get("date")),
            )
            if key in seen:
                continue
            seen.add(key)
            record: Dict[str, Any] = {"name": _text(medication.get("name"))}
            _optional(record, "dose", _text(medication.get("dosage")) or None)
            _optional(record, "frequency", _text(medication.get("frequency")) or None)
            _optional(record, "source_file", _text(medication.get("source_file")) or None)
            _optional(record, "date", _text(medication.get("date")) or None)
            _optional(record, "confidence", _number(medication.get("confidence")))
            _optional(record, "document_url", _valid_url(evidence_item.get("document_url")))
            _optional(
                record,
                "page",
                evidence_item.get("page") if isinstance(evidence_item.get("page"), int) else None,
            )
            records.append(record)
    return records


def _allergy_records(
    evidence: Iterable[Dict[str, Any]], timeline: Dict[str, Any]
) -> List[Dict[str, Any]]:
    """Include allergy evidence only when the snapshot itself records it."""
    known = {
        _text(value).lower() for value in (timeline.get("known_allergies") or []) if _text(value)
    }
    for visit in timeline.get("visits") or []:
        if isinstance(visit, dict):
            known.update(
                _text(value).lower()
                for value in (visit.get("allergies_noted") or [])
                if _text(value)
            )

    allergies: List[Dict[str, Any]] = []
    seen: set[Tuple[str, str, str]] = set()
    for item in evidence:
        if item.get("kind") != "allergy":
            continue
        allergen = _text(item.get("label"))
        if not allergen or allergen.lower() not in known:
            continue
        key = (allergen, _text(item.get("source_file")), _text(item.get("date")))
        if key in seen:
            continue
        seen.add(key)
        record: Dict[str, Any] = {"allergen": allergen}
        _optional(record, "source_file", _text(item.get("source_file")) or None)
        _optional(record, "date", _text(item.get("date")) or None)
        _optional(record, "document_url", _valid_url(item.get("document_url")))
        _optional(record, "page", item.get("page") if isinstance(item.get("page"), int) else None)
        allergies.append(record)
    return allergies


def _lab_points(
    evidence: Iterable[Dict[str, Any]], timeline: Dict[str, Any]
) -> List[Dict[str, Any]]:
    points: List[Dict[str, Any]] = []
    seen: set[Tuple[str, str, str, str]] = set()
    labs = timeline.get("lab_results_timeline") or []
    for evidence_item in evidence:
        if evidence_item.get("kind") != "lab_result":
            continue
        test_name = _text(evidence_item.get("label"))
        for lab in labs:
            if not isinstance(lab, dict) or _text(lab.get("test_name")) != test_name:
                continue
            if not _same_source(lab, evidence_item):
                continue
            key = (
                _text(lab.get("test_name")),
                _text(lab.get("value")),
                _text(lab.get("source_file")),
                _text(lab.get("date")),
            )
            if key in seen:
                continue
            seen.add(key)
            point: Dict[str, Any] = {
                "test": _text(lab.get("test_name")),
                "value": _text(lab.get("value")),
            }
            _optional(point, "unit", _text(lab.get("unit")) or None)
            _optional(point, "date", _text(lab.get("date")) or None)
            _optional(point, "source_file", _text(lab.get("source_file")) or None)
            _optional(point, "confidence", _number(lab.get("confidence")))
            _optional(point, "document_url", _valid_url(evidence_item.get("document_url")))
            _optional(
                point,
                "page",
                evidence_item.get("page") if isinstance(evidence_item.get("page"), int) else None,
            )
            points.append(point)
    return points


def _low_confidence_label(issue_type: str) -> str:
    return {
        "low_confidence_medication": "Medication information requires verification",
        "low_confidence_dosage": "Dosage or frequency information requires verification",
        "low_confidence_lab_result": "Lab result requires verification",
        "low_confidence_lab_trend": "Lab trend source values require verification",
        "low_confidence_document": "Document information requires verification",
        "low_confidence_interaction": "Medication interaction signal requires verification",
        "low_confidence_duplicate": "Duplicate-prescription signal requires verification",
    }.get(issue_type, "Information requires verification")


def _low_confidence_items(
    flag: Dict[str, Any], evidence: Iterable[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    if flag.get("trigger") != "low_confidence":
        return []
    # Prefer the existing flag confidence. Older snapshots can lack it, in
    # which case reuse an existing source-evidence confidence when available;
    # never synthesize a percentage.
    confidence = _number(flag.get("confidence"))
    source_candidates = [
        item
        for item in evidence
        if item.get("kind") in {"medication", "lab_result", "lab_trend", "document", "cross_check"}
    ]
    source = source_candidates[0] if source_candidates else {}
    if confidence is None:
        confidence = _number(source.get("confidence"))
    record: Dict[str, Any] = {
        "type": _text(flag.get("issue_type")) or "unknown",
        "label": _low_confidence_label(_text(flag.get("issue_type"))),
        "reason": _text(flag.get("evidence"))
        or "The existing record contains low-confidence information.",
    }
    _optional(record, "confidence", confidence)
    _optional(record, "source_file", _text(source.get("source_file")) or None)
    _optional(record, "date", _text(source.get("date")) or None)
    _optional(record, "document_url", _valid_url(source.get("document_url")))
    _optional(record, "page", source.get("page") if isinstance(source.get("page"), int) else None)
    return [record]


def _clinician_questions(issue_type: str) -> List[str]:
    """Safe deterministic prompts for clinician discussion only."""
    templates = {
        "high_severity_interaction": [
            "Can you verify whether these medicines should be used together?",
            "Can you confirm the dosage and frequency instructions for these medicines?",
        ],
        "low_confidence_interaction": [
            "Can you review the possible medication interaction using the original records?",
        ],
        "allergy_conflict": [
            "Can you review this medication against my recorded allergy?",
        ],
        "low_confidence_dosage": [
            "Can you confirm the correct dosage and frequency?",
        ],
        "low_confidence_medication": [
            "Can you verify the medication information against the original prescription?",
        ],
        "low_confidence_lab_result": [
            "Can you review this result using the original laboratory report?",
        ],
        "low_confidence_lab_trend": [
            "Can you review the relevant results and their recorded trend?",
        ],
        "low_confidence_document": [
            "Can you verify the unclear information in the original document?",
        ],
        "low_confidence_duplicate": [
            "Can you review whether these medication records are duplicates?",
        ],
    }
    return list(templates.get(issue_type, []))


def build_consultation_pack(
    flag: Dict[str, Any],
    snapshot: Dict[str, Any],
    pathway_evidence: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Build a source-grounded preparation pack for one selected flag.

    ``pathway_evidence`` is normally supplied by Phase 1. The optional
    deterministic fallback makes the function safe for older callers while
    remaining scoped to the same snapshot.
    """
    timeline = snapshot.get("patient_timeline") or {}
    cross_check = snapshot.get("cross_check_report") or {}
    lab_trends = snapshot.get("lab_trends") or {}
    evidence = list(pathway_evidence or [])
    if not evidence:
        evidence = build_care_pathway_evidence(flag, timeline, cross_check, lab_trends)

    return {
        "documents_to_bring": _documents_to_bring(evidence),
        # This intentionally avoids calling historical records "current".
        "medication_records_to_discuss": _medication_records(evidence, timeline),
        "allergies": _allergy_records(evidence, timeline),
        "relevant_lab_points": _lab_points(evidence, timeline),
        "low_confidence_items": _low_confidence_items(flag, evidence),
        "clinician_questions": _clinician_questions(_text(flag.get("issue_type"))),
        "disclaimer": CONSULTATION_PACK_DISCLAIMER,
    }
