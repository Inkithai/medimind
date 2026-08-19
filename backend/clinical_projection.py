"""Deterministic normalized relational projection of the trusted JSON record.

The immutable document JSON and patient snapshot remain the recovery source of
truth. This module derives independently queryable rows with stable IDs; the
projection can be rebuilt after every correction, deletion, or re-analysis.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, Iterable, List, Mapping

ENTITY_TABLES = (
    "clinical_medications",
    "clinical_prescriptions",
    "clinical_allergies",
    "clinical_lab_results",
    "clinical_events",
    "safety_findings",
)


def _stable_id(user_id: str, kind: str, identity: Mapping[str, Any]) -> str:
    raw = json.dumps([user_id, kind, identity], sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _source_identity(item: Mapping[str, Any], index: int) -> Dict[str, Any]:
    return {
        "document_id": item.get("document_id") or "",
        "source_file": item.get("source_file") or "",
        "source_page": item.get("source_page") or 0,
        "fact_path": item.get("fact_path") or "",
        "date": item.get("date") or "",
        "index": index,
    }


def _row(user_id: str, kind: str, data: Dict[str, Any], identity: Dict[str, Any]) -> Dict[str, Any]:
    raw_date = (
        data.get("date")
        or data.get("onset_date")
        or data.get("procedure_date")
        or data.get("study_date")
    )
    from date_convention import parse_mixed_date

    parsed_date = parse_mixed_date(raw_date) if raw_date else None
    return {
        "id": _stable_id(user_id, kind, identity),
        "user_id": user_id,
        "document_id": data.get("document_id") or None,
        "event_date": parsed_date.isoformat() if parsed_date else None,
        "data": data,
    }


def _event_rows(user_id: str, timeline: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for collection, event_type in (
        ("diagnoses_timeline", "diagnosis"),
        ("symptoms_timeline", "symptom"),
        ("procedures_timeline", "procedure"),
        ("vital_signs_timeline", "vital_sign"),
        ("imaging_results_timeline", "imaging_result"),
    ):
        for index, item in enumerate(timeline.get(collection) or []):
            if not isinstance(item, dict):
                continue
            data = {**item, "event_type": event_type}
            rows.append(
                _row(user_id, "event", data, {**_source_identity(item, index), "type": event_type})
            )
    return rows


def _safety_items(
    cross_check: Dict[str, Any], dosage_report: Dict[str, Any]
) -> Iterable[tuple[str, Dict[str, Any]]]:
    for field, kind in (
        ("potential_drug_interactions", "drug_interaction"),
        ("duplicate_prescriptions", "duplicate_prescription"),
        ("conflicting_dosage_instructions", "dosage_conflict"),
        ("allergy_conflicts", "allergy_conflict"),
        ("guideline_flagged_combinations", "published_guidance_combination"),
        ("concurrent_exposure", "concurrent_duplicate_ingredient"),
        ("eml_age_conflicts", "essential_medicine_age_restriction"),
    ):
        for item in cross_check.get(field) or []:
            if isinstance(item, dict):
                yield kind, item
    for item in dosage_report.get("findings") or []:
        if isinstance(item, dict):
            yield f"dosage_{item.get('kind') or 'finding'}", item


def build_projection(
    user_id: str,
    timeline: Dict[str, Any],
    cross_check: Dict[str, Any],
    dosage_report: Dict[str, Any] | None = None,
) -> Dict[str, List[Dict[str, Any]]]:
    """Build rows for every normalized table from trusted derived data."""
    dosage_report = dosage_report or {}
    projection = {table: [] for table in ENTITY_TABLES}

    medication_ids: Dict[str, str] = {}
    for index, med in enumerate(timeline.get("medications_timeline") or []):
        if not isinstance(med, dict):
            continue
        ingredients = [
            str(v).strip().lower() for v in med.get("ingredients") or [] if str(v).strip()
        ]
        medication_key = "|".join(sorted(ingredients)) or str(med.get("name") or "").strip().lower()
        identity = {"medication": medication_key}
        med_id = _stable_id(user_id, "medication", identity)
        medication_ids[medication_key] = med_id
        if not any(row["id"] == med_id for row in projection["clinical_medications"]):
            projection["clinical_medications"].append(
                {
                    "id": med_id,
                    "user_id": user_id,
                    "document_id": None,
                    "event_date": None,
                    "data": {
                        "name": med.get("name"),
                        "ingredients": med.get("ingredients") or [],
                        "normalized_key": medication_key,
                    },
                }
            )
        prescription = {**med, "medication_id": med_id}
        prescription_row = _row(
            user_id,
            "prescription",
            prescription,
            {**_source_identity(med, index), "medication": medication_key},
        )
        prescription_row["medication_id"] = med_id
        projection["clinical_prescriptions"].append(prescription_row)

    allergy_entries = timeline.get("allergy_evidence") or []
    if allergy_entries:
        for index, item in enumerate(allergy_entries):
            if not isinstance(item, dict):
                continue
            allergy = item.get("allergy")
            projection["clinical_allergies"].append(
                _row(
                    user_id, "allergy", item, {**_source_identity(item, index), "allergy": allergy}
                )
            )
    else:
        for index, allergy in enumerate(timeline.get("known_allergies") or []):
            data = {"allergy": allergy, "date": None, "document_id": None}
            projection["clinical_allergies"].append(
                _row(user_id, "allergy", data, {"allergy": allergy, "index": index})
            )

    for index, lab in enumerate(timeline.get("lab_results_timeline") or []):
        if isinstance(lab, dict):
            projection["clinical_lab_results"].append(
                _row(
                    user_id,
                    "lab_result",
                    lab,
                    {**_source_identity(lab, index), "test": lab.get("test_name")},
                )
            )

    projection["clinical_events"] = _event_rows(user_id, timeline)

    for index, (kind, item) in enumerate(_safety_items(cross_check, dosage_report)):
        subject = (
            item.get("medications_involved")
            or item.get("medication")
            or item.get("ingredient")
            or item.get("rule")
            or item.get("explanation")
        )
        if isinstance(subject, list):
            subject = sorted(str(value).strip().lower() for value in subject)
        sources = item.get("sources") or item.get("source_documents") or []
        if isinstance(sources, list):
            sources = sorted(
                sources, key=lambda value: json.dumps(value, sort_keys=True, default=str)
            )
        identity = {"kind": kind, "subject": subject, "sources": sources}
        data = {**item, "finding_type": kind, "status": "active"}
        row = _row(user_id, "safety_finding", data, identity)
        row["issue_key"] = row["id"]
        row["finding_type"] = kind
        row["status"] = "active"
        projection["safety_findings"].append(row)

    return projection
