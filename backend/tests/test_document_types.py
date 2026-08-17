"""Tests for document-type normalization and per-record summaries."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from document_types import (  # noqa: E402
    DOCUMENT_TYPES,
    normalize_document_type,
    summarize_document_types,
)


def test_vocabulary_values_pass_through():
    for t in DOCUMENT_TYPES:
        assert normalize_document_type(t) == t


def test_common_phrasings_normalize():
    assert normalize_document_type("Prescription") == "prescription"
    assert normalize_document_type("Rx") == "prescription"
    assert normalize_document_type("Lab Report") == "lab_report"
    assert normalize_document_type("Laboratory results") == "lab_report"
    assert normalize_document_type("blood test") == "lab_report"
    assert normalize_document_type("Discharge Summary") == "discharge_summary"
    assert normalize_document_type("discharge letter") == "discharge_summary"
    assert normalize_document_type("Consultation note") == "consultation_note"
    assert normalize_document_type("OPD visit") == "consultation_note"
    assert normalize_document_type("X-Ray") == "imaging_report"
    assert normalize_document_type("CT scan") == "imaging_report"
    assert normalize_document_type("Ultrasound") == "imaging_report"
    assert normalize_document_type("Surgical procedure") == "procedure_report"
    assert normalize_document_type("Endoscopy") == "procedure_report"


def test_unknown_or_missing_falls_back_to_other():
    assert normalize_document_type("") is not None
    assert normalize_document_type("") == "other"
    assert normalize_document_type(None) == "other"
    assert normalize_document_type("invoice") == "other"
    assert normalize_document_type("clinical_note") == "other"  # not in the vocabulary


def test_summary_counts_normalized_types():
    docs = [
        {"document_type": "Rx"},
        {"document_type": "lab report"},
        {"document_type": "Lab Report"},
        {"document_type": "invoice"},
    ]
    summary = summarize_document_types(docs)
    assert summary["counts"]["prescription"] == 1
    assert summary["counts"]["lab_report"] == 2
    assert summary["counts"]["other"] == 1
    assert summary["total"] == 4
    assert summary["dominant"] == "lab_report"
    assert set(summary["types"]) == {"prescription", "lab_report", "other"}


def test_summary_empty_list():
    summary = summarize_document_types([])
    assert summary["total"] == 0
    assert summary["dominant"] == "other"
