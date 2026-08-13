"""Deterministic consultation-pack tests using de-identified record data only.

No provider, clinic, address, rating, phone, or directory fixture is included:
consultation packs must remain entirely separate from provider discovery.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from consultation_pack import build_consultation_pack
from evidence_builder import build_care_pathway_evidence


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
            "medications": [{"name": "Medication B"}, {"name": "Unclear Medication"}],
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
            "ingredients": [],
            "dosage": "500 mg",
            "frequency": "twice daily",
            "date": "2026-08-04",
            "source_file": "Prescription_01.pdf",
            "confidence": 0.94,
        },
        {
            "name": "Medication B",
            "ingredients": [],
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
                {"date": "2026-07-15", "value": "1.08", "flag": "normal", "source_file": "Renal_Labs_01.pdf"},
                {"date": "2026-08-15", "value": "1.32", "flag": "normal", "source_file": "Renal_Labs_02.pdf"},
            ],
        }
    ]
}


def _snapshot(timeline=TIMELINE, cross_check=CROSS_CHECK, lab_trends=LAB_TRENDS):
    return {"patient_timeline": timeline, "cross_check_report": cross_check, "lab_trends": lab_trends}


def _flag(flag_id, issue_type, *, confidence=None, trigger="high_risk"):
    return {
        "id": flag_id,
        "issue_type": issue_type,
        "title": "Test flag",
        "evidence": "Existing record-level evidence.",
        "confidence": confidence,
        "trigger": trigger,
    }


def _pack(flag, snapshot=None):
    snapshot = snapshot or _snapshot()
    evidence = build_care_pathway_evidence(
        flag,
        snapshot["patient_timeline"],
        snapshot["cross_check_report"],
        snapshot["lab_trends"],
    )
    return build_consultation_pack(flag, snapshot, evidence)


def test_high_severity_interaction_lists_relevant_documents_and_medications():
    pack = _pack(_flag("interaction-0", "high_severity_interaction", confidence=0.91))
    assert {doc["source_file"] for doc in pack["documents_to_bring"]} == {
        "Prescription_01.pdf",
        "Prescription_02.pdf",
    }
    assert {med["name"] for med in pack["medication_records_to_discuss"]} == {"Medication A", "Medication B"}
    assert pack["clinician_questions"] == [
        "Can you verify whether these medicines should be used together?",
        "Can you confirm the dosage and frequency instructions for these medicines?",
    ]


def test_allergy_conflict_includes_only_actual_recorded_allergy():
    pack = _pack(_flag("allergy-0", "allergy_conflict", confidence=0.89))
    assert len(pack["allergies"]) == 1
    allergy = pack["allergies"][0]
    assert allergy["allergen"] == "Penicillin"
    assert allergy["source_file"] == "Prescription_01.pdf"
    assert allergy["document_url"] == "https://files.example.test/prescription-01.pdf"
    assert pack["clinician_questions"] == ["Can you review this medication against my recorded allergy?"]


def test_lab_trend_pack_includes_only_relevant_lab_results():
    pack = _pack(
        _flag("trend-confidence-0", "low_confidence_lab_trend", confidence=0.52, trigger="low_confidence")
    )
    assert {point["test"] for point in pack["relevant_lab_points"]} == {"Creatinine"}
    assert {point["source_file"] for point in pack["relevant_lab_points"]} == {
        "Renal_Labs_01.pdf",
        "Renal_Labs_02.pdf",
    }
    assert pack["medication_records_to_discuss"] == []
    assert pack["clinician_questions"] == ["Can you review the relevant results and their recorded trend?"]


def test_low_confidence_medication_has_verification_item_and_safe_question():
    pack = _pack(
        _flag("medication-confidence-2", "low_confidence_medication", confidence=0.46, trigger="low_confidence")
    )
    assert pack["low_confidence_items"][0]["label"] == "Medication information requires verification"
    assert pack["low_confidence_items"][0]["confidence"] == 0.46
    assert pack["low_confidence_items"][0]["source_file"] == "Prescription_02.pdf"
    assert pack["clinician_questions"] == [
        "Can you verify the medication information against the original prescription?"
    ]


def test_low_confidence_dosage_has_correct_question():
    pack = _pack(
        _flag(
            "conflicting_dosage_instructions-confidence-0",
            "low_confidence_dosage",
            confidence=0.45,
            trigger="low_confidence",
        )
    )
    assert pack["clinician_questions"] == ["Can you confirm the correct dosage and frequency?"]
    assert pack["low_confidence_items"][0]["label"] == "Dosage or frequency information requires verification"


def test_missing_document_url_never_creates_a_url():
    timeline = {
        "visits": [],
        "medications_timeline": [
            {
                "name": "Unlinked Medication",
                "dosage": "10 mg",
                "frequency": "once daily",
                "date": "2026-08-20",
                "source_file": "Original_Prescription.pdf",
                "confidence": 0.45,
            }
        ],
        "lab_results_timeline": [],
        "known_allergies": [],
    }
    pack = _pack(
        _flag("medication-confidence-0", "low_confidence_medication", confidence=0.45, trigger="low_confidence"),
        _snapshot(timeline=timeline, cross_check={}, lab_trends={}),
    )
    assert pack["documents_to_bring"][0]["source_file"] == "Original_Prescription.pdf"
    assert "document_url" not in pack["documents_to_bring"][0]
    assert "document_url" not in pack["medication_records_to_discuss"][0]


def test_missing_confidence_is_not_fabricated_in_verification_item():
    timeline = {
        "visits": [],
        "medications_timeline": [
            {
                "name": "Uncertain Medication",
                "date": "2026-08-20",
                "source_file": "Original_Prescription.pdf",
            }
        ],
        "lab_results_timeline": [],
        "known_allergies": [],
    }
    pack = _pack(
        _flag("medication-confidence-0", "low_confidence_medication", confidence=None, trigger="low_confidence"),
        _snapshot(timeline=timeline, cross_check={}, lab_trends={}),
    )
    assert "confidence" not in pack["low_confidence_items"][0]


def test_missing_allergy_data_returns_empty_allergy_list():
    timeline = {**TIMELINE, "known_allergies": [], "visits": [{**TIMELINE["visits"][0], "allergies_noted": []}]}
    pack = _pack(_flag("allergy-0", "allergy_conflict", confidence=0.89), _snapshot(timeline=timeline))
    assert pack["allergies"] == []


def test_unknown_flag_does_not_invent_questions_or_record_data():
    pack = _pack(_flag("unknown-0", "unknown_flag"))
    assert pack["documents_to_bring"] == []
    assert pack["medication_records_to_discuss"] == []
    assert pack["allergies"] == []
    assert pack["relevant_lab_points"] == []
    assert pack["low_confidence_items"] == []
    assert pack["clinician_questions"] == []


def test_duplicate_document_references_are_deduplicated():
    flag = _flag("interaction-0", "high_severity_interaction", confidence=0.91)
    evidence = build_care_pathway_evidence(flag, TIMELINE, CROSS_CHECK, LAB_TRENDS)
    evidence.append(dict(evidence[0]))
    pack = build_consultation_pack(flag, _snapshot(), evidence)
    assert [doc["source_file"] for doc in pack["documents_to_bring"]].count("Prescription_01.pdf") == 1


def test_patient_b_pack_cannot_contain_patient_a_record_data():
    patient_b_timeline = {
        "visits": [
            {
                "date": "2026-07-01",
                "document_type": "prescription",
                "overall_confidence": 0.9,
                "_source": {"file": "Patient_B_Only.pdf", "method": "text_layer"},
                "document_url": "https://files.example.test/patient-b-only.pdf",
                "medications": [{"name": "Medicine C"}],
                "lab_results": [],
                "allergies_noted": [],
            }
        ],
        "medications_timeline": [
            {
                "name": "Medicine C",
                "dosage": "10 mg",
                "frequency": "once daily",
                "date": "2026-07-01",
                "source_file": "Patient_B_Only.pdf",
                "confidence": 0.9,
            }
        ],
        "lab_results_timeline": [],
        "known_allergies": [],
    }
    patient_b_cross_check = {
        "potential_drug_interactions": [
            {
                "medications_involved": ["Medicine C"],
                "severity": "high",
                "confidence": 0.9,
                "explanation": "Potential interaction requires review.",
            }
        ]
    }
    pack = _pack(
        _flag("interaction-0", "high_severity_interaction", confidence=0.9),
        _snapshot(timeline=patient_b_timeline, cross_check=patient_b_cross_check, lab_trends={}),
    )
    files = {document["source_file"] for document in pack["documents_to_bring"]}
    assert files == {"Patient_B_Only.pdf"}
    assert "Prescription_01.pdf" not in files
