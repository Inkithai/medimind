"""Deterministic issue-to-specialty recommendation rules.

These rules choose a directory search term; they do not diagnose the patient
or certify that a returned provider is medically suitable. Every response
includes the evidence and reason shown to the user.
"""

import re
from typing import Any, Dict, Iterable, List, Tuple

SPECIALTY_RULES: List[Tuple[Tuple[str, ...], str, str]] = [
    (
        ("drug interaction", "medication interaction"),
        "Prescribing doctor or clinical pharmacist",
        "clinical pharmacist",
    ),
    (
        ("heart", "cardiac", "cardio", "chest pain", "troponin", "blood pressure", "hypertension"),
        "Cardiologist",
        "cardiology",
    ),
    (("skin", "rash", "eczema", "psoriasis", "dermat"), "Dermatologist", "dermatology"),
    (
        ("digest", "stomach", "bowel", "abdominal", "liver", "alt", "ast", "bilirubin", "gastro"),
        "Gastroenterologist",
        "gastroenterology",
    ),
    (
        (
            "blood",
            "anemia",
            "anaemia",
            "hemoglobin",
            "haemoglobin",
            "platelet",
            "white blood",
            "hemat",
        ),
        "Hematologist",
        "hematology",
    ),
    (
        ("glucose", "hba1c", "diabetes", "thyroid", "tsh", "endocr"),
        "Endocrinologist",
        "endocrinology",
    ),
    (("kidney", "renal", "creatinine", "egfr", "nephro"), "Nephrologist", "nephrology"),
]


def _sources(items: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    result: List[Dict[str, Any]] = []
    seen = set()
    for item in items:
        source = {
            "date": item.get("date"),
            "source_file": item.get("source_file"),
            "page": item.get("page") or item.get("source_page"),
        }
        key = (source["date"], source["source_file"], source["page"])
        if source["source_file"] and key not in seen:
            seen.add(key)
            result.append(source)
    return result


def _specialty_for_text(text: str) -> Tuple[str, str, str]:
    normalized = text.lower()
    for keywords, label, query in SPECIALTY_RULES:
        matched = next(
            (
                keyword
                for keyword in keywords
                if (
                    re.search(rf"\b{re.escape(keyword)}\b", normalized)
                    if len(keyword) <= 4
                    else keyword in normalized
                )
            ),
            None,
        )
        if matched:
            return (
                label,
                query,
                f"The record mentions “{matched}”, which maps to {label.lower()} directory results.",  # noqa: E501
            )
    return (
        "General physician",
        "general physician",
        "No reliable specialty-specific keyword was found, so a general physician is the safest starting point.",  # noqa: E501
    )


def _low_confidence_context(
    timeline: Dict[str, Any],
    cross_check: Dict[str, Any],
    lab_trends: Dict[str, Any],
) -> Tuple[List[Dict[str, Any]], str, int]:
    """Collect explicit low-confidence findings and text for specialty mapping."""
    evidence: List[Dict[str, Any]] = []
    context: List[str] = []
    finding_count = 0

    for visit in timeline.get("visits", []) or []:
        confidence = visit.get("overall_confidence")
        low_fields = visit.get("illegible_or_low_confidence_fields", []) or []
        if (isinstance(confidence, (int, float)) and confidence < 0.6) or low_fields:
            finding_count += 1
            source = visit.get("_source", {}) or {}
            evidence.append(
                {
                    "date": visit.get("date"),
                    "source_file": source.get("file"),
                    "source_page": source.get("page"),
                }
            )
            context.extend(str(value) for value in visit.get("diagnoses_or_conditions", []) or [])
            context.append(str(visit.get("clinical_notes") or ""))
            context.extend(
                str(item.get("test_name") or "") for item in visit.get("lab_results", []) or []
            )

    for collection, label_field in (
        ("medications_timeline", "name"),
        ("lab_results_timeline", "test_name"),
    ):
        for item in timeline.get(collection, []) or []:
            confidence = item.get("confidence")
            if isinstance(confidence, (int, float)) and confidence < 0.6:
                finding_count += 1
                evidence.append(item)
                context.append(str(item.get(label_field) or ""))

    for section in (
        "potential_drug_interactions",
        "duplicate_prescriptions",
        "conflicting_dosage_instructions",
        "allergy_conflicts",
    ):
        for item in cross_check.get(section, []) or []:
            confidence = item.get("confidence")
            if isinstance(confidence, (int, float)) and confidence < 0.6:
                finding_count += 1
                evidence.extend(
                    item.get("sources", [])
                    or item.get("occurrences", [])
                    or item.get("conflicting_instructions", [])
                    or []
                )
                if section == "potential_drug_interactions":
                    context.append("drug interaction")
                context.append(str(item.get("explanation") or ""))

    for trend in lab_trends.get("trends", []) or []:
        confidence = trend.get("confidence")
        if isinstance(confidence, (int, float)) and confidence < 0.6:
            finding_count += 1
            evidence.extend(trend.get("data_points", []) or [])
            context.append(str(trend.get("test_name") or ""))

    return _sources(evidence), " ".join(context), finding_count


def recommend_care(
    timeline: Dict[str, Any],
    cross_check: Dict[str, Any],
    lab_trends: Dict[str, Any],
) -> Dict[str, Any]:
    """Choose a specialty/search category from the strongest available flag."""
    high_interactions = [
        item
        for item in cross_check.get("potential_drug_interactions", []) or []
        if item.get("severity") == "high"
    ]
    if high_interactions:
        names = sorted(
            {
                str(name)
                for item in high_interactions
                for name in item.get("medications_involved", []) or []
                if str(name).strip()
            }
        )
        return {
            "triggered": True,
            "issue_type": "high_risk_drug_interaction",
            "specialty": "Prescribing doctor or clinical pharmacist",
            "specialty_query": "clinical pharmacist",
            "facility_kind": "pharmacy",
            "urgency": "prompt",
            "reason": (
                f"A high-severity potential interaction was flagged for {', '.join(names) or 'recorded medicines'}. "  # noqa: E501
                "A prescribing doctor or clinical pharmacist can verify the medicines and instructions."  # noqa: E501
            ),
            "evidence": _sources(
                source for item in high_interactions for source in item.get("sources", []) or []
            ),
            "disclaimer": _disclaimer(),
        }

    allergy_conflicts = cross_check.get("allergy_conflicts", []) or []
    if allergy_conflicts:
        return {
            "triggered": True,
            "issue_type": "allergy_medication_conflict",
            "specialty": "Allergist or prescribing doctor",
            "specialty_query": "allergist",
            "facility_kind": "doctor",
            "urgency": "prompt",
            "reason": (
                "A recorded medicine may conflict with a documented allergy. An allergist or the "
                "prescribing clinician should review the original records before any medication change."  # noqa: E501
            ),
            "evidence": _sources(
                source for item in allergy_conflicts for source in item.get("sources", []) or []
            ),
            "disclaimer": _disclaimer(),
        }

    serious_trends = [
        trend for trend in lab_trends.get("trends", []) or [] if trend.get("risk_level") == "high"
    ]
    if serious_trends:
        trend = serious_trends[0]
        specialty, specialty_query, mapping_reason = _specialty_for_text(
            str(trend.get("test_name") or "")
        )
        return {
            "triggered": True,
            "issue_type": "serious_lab_trend",
            "specialty": specialty,
            "specialty_query": specialty_query,
            "facility_kind": "doctor",
            "urgency": "prompt",
            "reason": f"{trend.get('risk_reason', 'A serious numeric trend was detected.')} {mapping_reason}",  # noqa: E501
            "evidence": _sources(trend.get("data_points", []) or []),
            "disclaimer": _disclaimer(),
        }

    low_confidence_evidence, low_confidence_text, low_confidence_count = _low_confidence_context(
        timeline, cross_check, lab_trends
    )
    if low_confidence_count:
        specialty, specialty_query, mapping_reason = _specialty_for_text(low_confidence_text)
        return {
            "triggered": True,
            "issue_type": "low_confidence_finding",
            "specialty": specialty,
            "specialty_query": specialty_query,
            "facility_kind": "pharmacy" if specialty_query == "clinical pharmacist" else "doctor",
            "urgency": "routine",
            "reason": (
                f"{low_confidence_count} extracted or AI-assisted finding(s) have low confidence and "  # noqa: E501
                f"should be checked against the original records by a professional. {mapping_reason}"  # noqa: E501
            ),
            "evidence": low_confidence_evidence,
            "disclaimer": _disclaimer(),
        }

    interactions = cross_check.get("potential_drug_interactions", []) or []
    if interactions:
        return {
            "triggered": False,
            "issue_type": "drug_interaction_review",
            "specialty": "Prescribing doctor or clinical pharmacist",
            "specialty_query": "clinical pharmacist",
            "facility_kind": "pharmacy",
            "urgency": "routine",
            "reason": (
                "A potential medication interaction was recorded. A prescribing doctor or clinical "
                "pharmacist is the relevant professional to verify the medicines, doses, and timing."  # noqa: E501
            ),
            "evidence": _sources(
                source for item in interactions for source in item.get("sources", []) or []
            ),
            "disclaimer": _disclaimer(),
        }

    # Explicit diagnoses/conditions and clinical notes can provide a useful
    # category even when there is no high-risk trigger.
    diagnosis_text = " ".join(
        str(item.get("name") or "") for item in timeline.get("diagnoses_timeline", []) or []
    )
    note_text = " ".join(
        str(visit.get("clinical_notes") or "") for visit in timeline.get("visits", []) or []
    )
    specialty, specialty_query, reason = _specialty_for_text(f"{diagnosis_text} {note_text}")
    return {
        "triggered": False,
        "issue_type": "record_context" if diagnosis_text or note_text else "general_guidance",
        "specialty": specialty,
        "specialty_query": specialty_query,
        "facility_kind": "doctor",
        "urgency": "routine",
        "reason": reason,
        "evidence": _sources(timeline.get("diagnoses_timeline", []) or []),
        "disclaimer": _disclaimer(),
    }


def _disclaimer() -> str:
    return (
        "This is not a diagnosis or a referral. MediMind matched words and safety flags in the "
        "uploaded records to a directory search category. Verify specialty and availability with "
        "the provider, and do not start or stop medication based on this result."
    )
