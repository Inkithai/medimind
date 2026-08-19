"""Deterministic, source-linked care-pathway evidence tests.

Fixtures contain only de-identified clinical record values. They intentionally
contain no doctor, clinic, rating, address, phone, or provider-directory data.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from evidence_builder import build_care_pathway_evidence, enrich_care_flag

TIMELINE = {
    "visits": [
        {
            "date": "2026-08-04",
            "document_type": "prescription",
            "overall_confidence": 0.94,
            "_source": {"file": "Prescription_01.pdf", "method": "text_layer"},
            "document_url": "https://files.example.test/prescription-01.pdf",
            "medications": [{"name": "Medication A"}],
            "lab_results": [],
            "allergies_noted": ["Penicillin"],
        },
        {
            "date": "2026-08-08",
            "document_type": "prescription",
            "overall_confidence": 0.92,
            "_source": {"file": "Prescription_02.pdf", "method": "vision_ocr", "page": 2},
            "document_url": "https://files.example.test/prescription-02.pdf",
            "medications": [{"name": "Medication B"}],
            "lab_results": [],
            "allergies_noted": [],
        },
        {
            "date": "2026-07-15",
            "document_type": "lab_report",
            "overall_confidence": 0.88,
            "_source": {"file": "Renal_Labs_01.pdf", "method": "text_layer"},
            "document_url": "https://files.example.test/renal-labs-01.pdf",
            "medications": [],
            "lab_results": [{"test_name": "Creatinine", "value": "1.08"}],
            "allergies_noted": [],
        },
        {
            "date": "2026-08-15",
            "document_type": "lab_report",
            "overall_confidence": 0.86,
            "_source": {"file": "Renal_Labs_02.pdf", "method": "text_layer"},
            "document_url": "https://files.example.test/renal-labs-02.pdf",
            "medications": [],
            "lab_results": [{"test_name": "Creatinine", "value": "1.32"}],
            "allergies_noted": [],
        },
    ],
    "medications_timeline": [
        {
            "name": "Medication A",
            "ingredients": ["Ingredient A"],
            "dosage": "500 mg",
            "frequency": "twice daily",
            "date": "2026-08-04",
            "source_file": "Prescription_01.pdf",
            "confidence": 0.94,
        },
        {
            "name": "Medication B",
            "ingredients": ["Ingredient B"],
            "dosage": "20 mg",
            "frequency": "once daily",
            "date": "2026-08-08",
            "source_file": "Prescription_02.pdf",
            "confidence": 0.92,
        },
        {
            "name": "Unclear Medication",
            "ingredients": [],
            "dosage": "",
            "frequency": "",
            "date": "2026-08-08",
            "source_file": "Prescription_02.pdf",
            "confidence": 0.46,
        },
    ],
    "lab_results_timeline": [
        {
            "test_name": "Creatinine",
            "value": "1.08",
            "unit": "mg/dL",
            "date": "2026-07-15",
            "source_file": "Renal_Labs_01.pdf",
            "confidence": 0.86,
        },
        {
            "test_name": "Creatinine",
            "value": "1.32",
            "unit": "mg/dL",
            "date": "2026-08-15",
            "source_file": "Renal_Labs_02.pdf",
            "confidence": 0.86,
        },
    ],
    "known_allergies": ["Penicillin"],
}

CROSS_CHECK = {
    "potential_drug_interactions": [
        {
            "medications_involved": ["Medication A", "Medication B"],
            "severity": "high",
            "confidence": 0.91,
            "explanation": "Potential interaction requires professional review.",
        }
    ],
    "allergy_conflicts": [
        {
            "medication": "Medication A",
            "allergy": "Penicillin",
            "confidence": 0.89,
            "explanation": "Potential conflict with the recorded allergy.",
        }
    ],
    "conflicting_dosage_instructions": [
        {
            "medication": "Medication A",
            "confidence": 0.45,
            "explanation": "Instructions differ across records.",
            "conflicting_instructions": [
                {
                    "date": "2026-08-04",
                    "source_file": "Prescription_01.pdf",
                    "dosage": "500 mg",
                    "frequency": "twice daily",
                }
            ],
        }
    ],
}

LAB_TRENDS = {
    "trends": [
        {
            "test_name": "Creatinine",
            "confidence": 0.52,
            "explanation": "Creatinine has risen across two tests.",
            "data_points": [
                {
                    "date": "2026-07-15",
                    "value": "1.08",
                    "flag": "normal",
                    "source_file": "Renal_Labs_01.pdf",
                },
                {
                    "date": "2026-08-15",
                    "value": "1.32",
                    "flag": "normal",
                    "source_file": "Renal_Labs_02.pdf",
                },
            ],
        }
    ]
}


def _flag(flag_id, issue_type):
    return {
        "id": flag_id,
        "issue_type": issue_type,
        "title": "Test flag",
        "specialty": {"label": "General Physician"},
    }


def test_interaction_evidence_resolves_actual_medications_and_documents():
    evidence = build_care_pathway_evidence(
        _flag("interaction-0", "high_severity_interaction"), TIMELINE, CROSS_CHECK, LAB_TRENDS
    )
    medication_items = [item for item in evidence if item["kind"] == "medication"]
    assert {item["label"] for item in medication_items} == {"Medication A", "Medication B"}
    assert {item["source_file"] for item in medication_items} == {
        "Prescription_01.pdf",
        "Prescription_02.pdf",
    }
    assert all(
        item["document_url"].startswith("https://files.example.test/") for item in medication_items
    )
    assert any(
        item["kind"] == "cross_check" and item["label"] == "Potential interaction detected"
        for item in evidence
    )


def test_low_confidence_medication_keeps_existing_source_document():
    evidence = build_care_pathway_evidence(
        _flag("medication-confidence-2", "low_confidence_medication"),
        TIMELINE,
        CROSS_CHECK,
        LAB_TRENDS,
    )
    assert len(evidence) == 1
    item = evidence[0]
    assert item["label"] == "Unclear Medication"
    assert item["source_file"] == "Prescription_02.pdf"
    assert item["document_url"] == "https://files.example.test/prescription-02.pdf"
    assert item["page"] == 2
    assert item["confidence"] == 0.46


def test_allergy_conflict_connects_actual_medication_and_recorded_allergy():
    evidence = build_care_pathway_evidence(
        _flag("allergy-0", "allergy_conflict"), TIMELINE, CROSS_CHECK, LAB_TRENDS
    )
    assert any(
        item["kind"] == "medication" and item["label"] == "Medication A" for item in evidence
    )
    allergy = next(item for item in evidence if item["kind"] == "allergy")
    assert allergy["label"] == "Penicillin"
    assert allergy["source_file"] == "Prescription_01.pdf"
    assert allergy["document_url"] == "https://files.example.test/prescription-01.pdf"


def test_dosage_conflict_points_to_existing_prescription_record():
    evidence = build_care_pathway_evidence(
        _flag("conflicting_dosage_instructions-confidence-0", "low_confidence_dosage"),
        TIMELINE,
        CROSS_CHECK,
        LAB_TRENDS,
    )
    assert any(
        item["kind"] == "medication" and item["source_file"] == "Prescription_01.pdf"
        for item in evidence
    )
    assert any(item["kind"] == "cross_check" for item in evidence)


def test_lab_trend_includes_actual_related_lab_results():
    evidence = build_care_pathway_evidence(
        _flag("trend-confidence-0", "low_confidence_lab_trend"), TIMELINE, CROSS_CHECK, LAB_TRENDS
    )
    assert evidence[0]["kind"] == "lab_trend"
    labs = [item for item in evidence if item["kind"] == "lab_result"]
    assert {item["source_file"] for item in labs} == {"Renal_Labs_01.pdf", "Renal_Labs_02.pdf"}
    assert {item["details"] for item in labs} == {"1.08 mg/dL", "1.32 mg/dL"}


def test_missing_source_url_does_not_create_a_url_or_confidence():
    timeline = {
        "visits": [],
        "medications_timeline": [
            {
                "name": "Medication Without Source URL",
                "date": "2026-08-20",
                "source_file": "Original_Prescription.pdf",
            }
        ],
        "lab_results_timeline": [],
    }
    evidence = build_care_pathway_evidence(
        _flag("medication-confidence-0", "low_confidence_medication"), timeline, {}, {}
    )
    assert evidence[0]["source_file"] == "Original_Prescription.pdf"
    assert "document_url" not in evidence[0]
    assert "confidence" not in evidence[0]


def test_unknown_flag_returns_empty_evidence_without_inference():
    assert (
        build_care_pathway_evidence(
            _flag("unknown-0", "unknown_flag"), TIMELINE, CROSS_CHECK, LAB_TRENDS
        )
        == []
    )


def test_enrichment_keeps_existing_fields_and_adds_route_evidence():
    flag = {
        "id": "interaction-0",
        "issue_type": "high_severity_interaction",
        "title": "Potential high-severity medication interaction",
        "evidence": "Medication A; Medication B",
        "source": "Medication safety cross-check",
        "confidence": 0.91,
        "specialty": {
            "id": "pharmacy",
            "label": "Pharmacist / prescribing doctor",
            "provider_query": "pharmacy",
        },
    }
    enriched = enrich_care_flag(flag, TIMELINE, CROSS_CHECK, LAB_TRENDS)
    assert enriched["evidence"] == flag["evidence"]
    assert len(enriched["pathway_evidence"]) >= 2
    assert "pharmacist or prescribing clinician" in enriched["care_route_explanation"].lower()
