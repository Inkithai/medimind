"""Deterministic question-intent routing for patient-record retrieval.

This is not a clinical classifier. It identifies which structured record
categories are likely to answer a question so specialized questions do not
silently receive unrelated context chunks.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Sequence, Tuple


INTENTS: Dict[str, Dict[str, Any]] = {
    "medication_safety": {
        "label": "Medication safety",
        "chunk_types": ["medication", "allergy", "clinical_note"],
        "minimum_evidence": 2,
    },
    "lab_trend": {
        "label": "Lab trend",
        "chunk_types": ["lab_result"],
        "minimum_evidence": 2,
    },
    "record_change": {
        "label": "Record change",
        "chunk_types": ["medication", "lab_result", "clinical_note", "allergy"],
        "minimum_evidence": 2,
    },
    "lab_result": {
        "label": "Lab result",
        "chunk_types": ["lab_result"],
        "minimum_evidence": 1,
    },
    "allergy": {
        "label": "Allergy",
        "chunk_types": ["allergy", "medication", "clinical_note"],
        "minimum_evidence": 1,
    },
    "medication": {
        "label": "Medication",
        "chunk_types": ["medication", "clinical_note"],
        "minimum_evidence": 1,
    },
    "timeline": {
        "label": "Timeline or visit",
        "chunk_types": ["clinical_note", "medication", "lab_result"],
        "minimum_evidence": 1,
    },
    "general": {
        "label": "General record question",
        "chunk_types": ["medication", "lab_result", "clinical_note", "allergy"],
        "minimum_evidence": 1,
    },
}

_SAFETY = re.compile(r"\b(safe|safety|interact(?:ion|s)?|contraindicat\w*|conflict|duplicate|overdose|allergic reaction|risk)\b", re.I)
_TREND = re.compile(r"\b(trend|over time|changed?|changing|improv\w*|wors\w*|increas\w*|decreas\w*|risen|rose|fallen|since|progress\w*)\b", re.I)
_LAB = re.compile(
    r"\b(lab|laboratory|test result|blood test|glucose|hba1c|a1c|hemoglobin|haemoglobin|cholesterol|ldl|hdl|triglyceride|creatinine|egfr|platelet|wbc|rbc|tsh|alt|ast|bilirubin)\b",
    re.I,
)
_MEDICATION = re.compile(r"\b(medication\w*|medicine\w*|drug\w*|prescri\w*|tablet\w*|capsule\w*|dose|dosage|taking|take|pharmac\w*)\b", re.I)
_ALLERGY = re.compile(r"\b(allerg\w*|anaphyl\w*|sensitive to|reaction to|nkda|no known allergies)\b", re.I)
_TIMELINE = re.compile(r"\b(timeline|history|visit|appointment|doctor note|clinical note|last report|latest report|discharge)\b", re.I)
_CHANGE = re.compile(r"\b(what changed|since my last|different from|new since|recent change)\b", re.I)


def classify_question(question: str) -> Dict[str, Any]:
    """Return a stable intent descriptor for a natural-language question."""
    text = (question or "").strip()
    has_safety = bool(_SAFETY.search(text))
    has_trend = bool(_TREND.search(text))
    has_lab = bool(_LAB.search(text))
    has_medication = bool(_MEDICATION.search(text))

    if has_safety and has_lab:
        key = "lab_result"
    elif has_safety:
        # A named medicine may not contain a generic word such as "drug".
        # Default standalone safety questions to medication/allergy context.
        key = "medication_safety"
    elif has_lab and has_trend:
        key = "lab_trend"
    elif _CHANGE.search(text) or (has_trend and not has_lab):
        key = "record_change"
    elif has_lab:
        key = "lab_result"
    elif _ALLERGY.search(text):
        key = "allergy"
    elif has_medication:
        key = "medication"
    elif _TIMELINE.search(text):
        key = "timeline"
    else:
        key = "general"

    config = INTENTS[key]
    return {
        "key": key,
        "label": config["label"],
        "chunk_types": list(config["chunk_types"]),
        "minimum_evidence": int(config["minimum_evidence"]),
        "safety_sensitive": has_safety,
    }


def route_chunks(
    documents: Sequence[str],
    metadatas: Sequence[Dict[str, Any]],
    intent: Dict[str, Any],
    limit: int,
) -> Tuple[List[str], List[Dict[str, Any]]]:
    """Keep only intent-compatible chunks while preserving vector rank."""
    allowed = set(intent.get("chunk_types", []))
    routed = [
        (document, metadata)
        for document, metadata in zip(documents, metadatas)
        if metadata.get("chunk_type") in allowed
    ]
    routed = routed[:max(1, limit)]
    return [item[0] for item in routed], [item[1] for item in routed]


def assess_evidence(intent: Dict[str, Any], metadatas: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Describe structured evidence coverage, not clinical certainty."""
    expected = int(intent.get("minimum_evidence", 1))
    count = len(metadatas)
    source_count = len({
        (metadata.get("source_file") or "", metadata.get("date") or "")
        for metadata in metadatas
    })
    types = sorted({metadata.get("chunk_type") for metadata in metadatas if metadata.get("chunk_type")})

    comparative = intent.get("key") in {"lab_trend", "record_change"}
    coverage_count = source_count if comparative else count
    if count == 0:
        level = "insufficient"
        reason = f"No {intent.get('label', 'relevant').lower()} evidence was retrieved from the uploaded records."
    elif coverage_count < expected:
        level = "limited"
        if comparative:
            reason = f"Only {source_count} distinct dated source entry was found; this comparison needs at least {expected}."
        else:
            reason = f"Only {count} relevant record item was found; this question usually needs at least {expected}."
    else:
        level = "sufficient"
        reason = f"Retrieved {count} relevant record item{'s' if count != 1 else ''} from {source_count} dated source entr{'ies' if source_count != 1 else 'y'}."

    return {
        "level": level,
        "reason": reason,
        "retrieved_chunks": count,
        "distinct_sources": source_count,
        "expected_minimum": expected,
        "evidence_types": types,
    }
