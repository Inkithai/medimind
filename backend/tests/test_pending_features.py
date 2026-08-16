"""Regression tests for the completed feature-checklist items."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("GROQ_API_KEY", "gsk_test_123")

from care.recommendation import recommend_care  # noqa: E402
from lab_trends import track_lab_trends  # noqa: E402
from medical_extractor import EXTRACTION_JSON_SCHEMA, build_patient_timeline  # noqa: E402
from medication_history import (  # noqa: E402
    detect_medication_transitions,
    enrich_cross_check_sources,
)


def _medication(date, source, dosage_value=500, frequency_per_day=2, page=1):
    return {
        "name": "Metformin",
        "ingredients": ["Metformin"],
        "dosage": f"{dosage_value} mg",
        "dosage_value": dosage_value,
        "dosage_unit": "mg",
        "frequency": f"{frequency_per_day} times daily",
        "frequency_per_day": frequency_per_day,
        "is_as_needed": False,
        "confidence": 0.94,
        "date": date,
        "source_file": source,
        "source_page": page,
    }


def test_diagnoses_are_structured_and_preserve_document_page_sources():
    assert "diagnoses_or_conditions" in EXTRACTION_JSON_SCHEMA["properties"]
    assert "diagnoses_or_conditions" in EXTRACTION_JSON_SCHEMA["required"]
    timeline = build_patient_timeline([{
        "document_type": "discharge_summary",
        "date": "2026-01-01",
        "medications": [],
        "lab_results": [],
        "allergies_noted": [],
        "diagnoses_or_conditions": ["Hypertension"],
        "clinical_notes": "Follow-up advised",
        "_source": {"file": "discharge.pdf", "method": "vision_ocr", "page": 3},
    }])
    diagnosis = timeline["diagnoses_timeline"][0]
    assert diagnosis["name"] == "Hypertension"
    assert diagnosis["date"] is None, "a document date is not an explicit diagnosis date"
    assert diagnosis["document_date"] == "2026-01-01"
    assert diagnosis["source_file"] == "discharge.pdf"
    assert diagnosis["source_page"] == 3


def test_medication_changes_continuations_and_sources_are_deterministic():
    timeline = {
        "medications_timeline": [
            _medication("2026-01-01", "visit-1.pdf"),
            _medication("2026-02-01", "visit-2.pdf"),
            _medication("2026-03-01", "visit-3.pdf", dosage_value=1000, page=2),
        ],
        "visits": [{
            "date": "2025-12-01",
            "allergies_noted": ["Metformin"],
            "_source": {"file": "allergies.pdf", "page": 4},
        }],
    }
    findings = detect_medication_transitions(timeline)

    assert len(findings["medication_continuations"]) == 1
    assert len(findings["medication_changes"]) == 1
    change = findings["medication_changes"][0]
    assert change["changed_fields"] == ["dosage"]
    assert change["sources"][1] == {
        "date": "2026-03-01",
        "source_file": "visit-3.pdf",
        "page": 2,
    }

    report = {
        "potential_drug_interactions": [{
            "medications_involved": ["Metformin", "Other"],
            "severity": "moderate",
            "confidence": 0.8,
            "explanation": "test",
        }],
        "allergy_conflicts": [{
            "medication": "Metformin",
            "allergy": "Metformin",
            "confidence": 0.8,
            "explanation": "test",
        }],
        "duplicate_prescriptions": [],
        "conflicting_dosage_instructions": [],
    }
    enrich_cross_check_sources(report, timeline)
    assert len(report["potential_drug_interactions"][0]["sources"]) == 3
    allergy_sources = report["allergy_conflicts"][0]["sources"]
    assert allergy_sources[0]["source_file"] == "visit-1.pdf"
    assert allergy_sources[-1] == {
        "date": "2025-12-01",
        "source_file": "allergies.pdf",
        "page": 4,
    }


def test_repeated_worsening_abnormal_labs_are_high_risk():
    report = track_lab_trends({
        "lab_results_timeline": [
            {"test_name": "ALT", "value": "45", "unit": "U/L", "reference_range": "7-56", "flag": "normal", "confidence": 0.95, "date": "2026-01-01", "source_file": "one.pdf"},
            {"test_name": "ALT", "value": "85", "unit": "U/L", "reference_range": "7-56", "flag": "high", "confidence": 0.95, "date": "2026-02-01", "source_file": "two.pdf"},
            {"test_name": "ALT", "value": "120", "unit": "U/L", "reference_range": "7-56", "flag": "high", "confidence": 0.95, "date": "2026-03-01", "source_file": "three.pdf"},
        ]
    })
    trend = report["trends"][0]
    assert trend["risk_level"] == "high"
    assert trend["professional_review_recommended"] is True
    assert "professional review" in trend["risk_reason"].lower()


def test_issue_to_specialty_rules_cover_safety_and_body_systems():
    interaction = recommend_care(
        {},
        {"potential_drug_interactions": [{
            "severity": "high",
            "medications_involved": ["Warfarin", "Aspirin"],
            "sources": [{"date": "2026-01-01", "source_file": "rx.pdf", "page": 1}],
        }], "allergy_conflicts": []},
        {"trends": []},
    )
    assert interaction["triggered"] is True
    assert interaction["specialty_query"] == "clinical pharmacist"

    cardiac = recommend_care(
        {},
        {"potential_drug_interactions": [], "allergy_conflicts": []},
        {"trends": [{
            "test_name": "Troponin",
            "risk_level": "high",
            "risk_reason": "Repeated abnormal values.",
            "data_points": [{"date": "2026-01-01", "source_file": "lab.pdf"}],
        }]},
    )
    assert cardiac["specialty"] == "Cardiologist"
    assert "troponin" in cardiac["reason"].lower()

    specialty_cases = {
        "Persistent skin rash": "Dermatologist",
        "Digestive and abdominal condition": "Gastroenterologist",
        "Blood platelet disorder": "Hematologist",
    }
    for condition, expected_specialty in specialty_cases.items():
        mapped = recommend_care(
            {"diagnoses_timeline": [{"name": condition, "source_file": "note.pdf"}], "visits": []},
            {"potential_drug_interactions": [], "allergy_conflicts": []},
            {"trends": []},
        )
        assert mapped["specialty"] == expected_specialty
        assert expected_specialty.lower() in mapped["reason"].lower()

    low_confidence = recommend_care(
        {
            "diagnoses_timeline": [],
            "medications_timeline": [],
            "lab_results_timeline": [],
            "visits": [{
                "date": "2026-04-01",
                "overall_confidence": 0.45,
                "illegible_or_low_confidence_fields": ["heart condition wording"],
                "diagnoses_or_conditions": ["Possible heart condition"],
                "clinical_notes": None,
                "lab_results": [],
                "_source": {"file": "unclear-note.jpg", "page": 1},
            }],
        },
        {"potential_drug_interactions": [], "allergy_conflicts": []},
        {"trends": []},
    )
    assert low_confidence["triggered"] is True
    assert low_confidence["issue_type"] == "low_confidence_finding"
    assert low_confidence["specialty"] == "Cardiologist"
    assert low_confidence["evidence"][0]["source_file"] == "unclear-note.jpg"

    general = recommend_care(
        {"diagnoses_timeline": [], "visits": []}, 
        {"potential_drug_interactions": [], "allergy_conflicts": []},
        {"trends": []},
    )
    assert general["specialty"] == "General physician"
