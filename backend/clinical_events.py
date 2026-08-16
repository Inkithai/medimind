"""Shared contracts for longitudinal clinical fact collections.

These collections are extracted independently so each fact keeps its own
confidence, source evidence, correction path, and chronological event date.
Terminology and units remain as documented; clinically validated coding and
unit normalization are intentionally a separate concern.
"""

from __future__ import annotations

from typing import Dict, Tuple


# collection -> fields worth using as deterministic PDF-search fallbacks.
# Keep these conservative: status labels may be model classifications rather
# than literal source text, so they are not used to locate evidence.
CLINICAL_EVENT_SEARCH_FIELDS: Dict[str, Tuple[str, ...]] = {
    "diagnoses": ("name", "code"),
    "symptoms": ("name",),
    "procedures": ("name", "body_site"),
    "vital_signs": ("name", "value", "unit"),
    "imaging_results": ("study_type", "body_site", "findings", "impression"),
}

# collection -> event-specific date field. The enclosing document date is the
# fallback when a fact has no explicit date of its own.
CLINICAL_EVENT_DATE_FIELDS: Dict[str, str] = {
    "diagnoses": "onset_date",
    "symptoms": "onset_date",
    "procedures": "procedure_date",
    "vital_signs": "measured_at",
    "imaging_results": "study_date",
}

# Public rollup keys returned by build_patient_timeline().
CLINICAL_TIMELINE_KEYS: Dict[str, str] = {
    "diagnoses": "diagnoses_timeline",
    "symptoms": "symptoms_timeline",
    "procedures": "procedures_timeline",
    "vital_signs": "vital_signs_timeline",
    "imaging_results": "imaging_results_timeline",
}

# Fields users may correct through append-only audit events. Confidence,
# evidence, IDs, source metadata, and trust state are deliberately absent.
CLINICAL_EVENT_CORRECTABLE_FIELDS: Dict[str, frozenset[str]] = {
    "diagnoses": frozenset({"name", "code", "status", "onset_date"}),
    "symptoms": frozenset({"name", "severity", "status", "onset_date"}),
    "procedures": frozenset({"name", "procedure_date", "body_site", "status", "outcome"}),
    "vital_signs": frozenset({"name", "value", "unit", "measured_at"}),
    "imaging_results": frozenset({"study_type", "body_site", "study_date", "findings", "impression"}),
}

CLINICAL_EVENT_COLLECTIONS = tuple(CLINICAL_EVENT_SEARCH_FIELDS)
ALL_FACT_COLLECTIONS = ("medications", "lab_results", *CLINICAL_EVENT_COLLECTIONS)
