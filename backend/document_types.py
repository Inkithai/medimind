"""
Document-type normalization and summarization
=============================================
The extractor already emits a free-form `document_type` per document;
this module pins it to a closed vocabulary deterministically so that:

  * chunk metadata and evidence weighting downstream always see one of
    the known types (retrieval._evidence_metadata has per-type
    confidence), instead of the model's arbitrary wording;
  * per-record type distributions can be reported transparently.

Normalization is keyword-based and conservative: an unrecognized value
falls back to "other" rather than guessing a clinical category.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List

# Closed vocabulary, ordered for display.
DOCUMENT_TYPES: tuple = (
    "prescription",
    "lab_report",
    "discharge_summary",
    "consultation_note",
    "imaging_report",
    "procedure_report",
    "other",
)

# Value -> synonyms that map to it. Matching is whole-word where the
# synonym is a word; multi-word phrases use substring containment.
_TYPE_SYNONYMS: Dict[str, tuple] = {
    "prescription": (
        "prescription",
        "prescriptions",
        "rx",
        "script",
        "medication chart",
        "medication list",
        "drug chart",
        "drug list",
        "repeat prescription",
    ),
    "lab_report": (
        "lab",
        "laboratory",
        "lab report",
        "lab result",
        "lab results",
        "laboratory report",
        "laboratory result",
        "laboratory results",
        "blood test",
        "blood report",
        "pathology",
        "biochemistry",
        "culture",
    ),
    "discharge_summary": (
        "discharge",
        "discharge summary",
        "discharge note",
        "discharge report",
        "discharge letter",
        "transfer summary",
    ),
    "consultation_note": (
        "consultation",
        "consult note",
        "consultation note",
        "clinic note",
        "doctor note",
        "doctor's note",
        "doctor visit",
        "opd",
        "outpatient",
        "clinic visit",
        "follow up note",
        "follow-up note",
        "progress note",
    ),
    "imaging_report": (
        "imaging",
        "xray",
        "x-ray",
        "x ray",
        "mri",
        "ct scan",
        "ct report",
        "ultrasound",
        "ultra sound",
        "mammogram",
        "radiology",
        "radiograph",
        "scan report",
        "scan result",
    ),
    "procedure_report": (
        "procedure",
        "surgical",
        "surgery",
        "operative",
        "endoscopy",
        "colonoscopy",
        "biopsy",
    ),
}


def _normalize_text(value: Any) -> str:
    return re.sub(r"[\s_]+", " ", str(value or "")).strip().lower()


def normalize_document_type(value: Any) -> str:
    """Maps any extracted document_type value onto the closed vocabulary."""
    text = _normalize_text(value)
    if not text:
        return "other"
    # A value already in the vocabulary passes through unchanged.
    if text in DOCUMENT_TYPES:
        return text
    for doc_type, synonyms in _TYPE_SYNONYMS.items():
        for synonym in synonyms:
            if " " in synonym:
                if synonym in text:
                    return doc_type
            elif re.search(rf"(?<![a-z]){re.escape(synonym)}(?![a-z])", text):
                return doc_type
    return "other"


def summarize_document_types(docs: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Counts the normalized types across a document list (the stored rows
    may predate normalization, so values are normalized on read)."""
    counts: Dict[str, int] = {t: 0 for t in DOCUMENT_TYPES}
    for doc in docs or []:
        counts[normalize_document_type(doc.get("document_type"))] += 1
    present = [t for t in DOCUMENT_TYPES if counts[t]]
    dominant = max(present, key=lambda t: counts[t]) if present else "other"
    return {
        "counts": counts,
        "types": present,
        "dominant": dominant,
        "total": sum(counts.values()),
    }
