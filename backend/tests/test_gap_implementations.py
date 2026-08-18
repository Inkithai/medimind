"""Regression coverage for the evidence/temporal safety gap implementation."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("GROQ_API_KEY", "test-key")

from consult_triage import generate_consult_triage
from date_convention import sanitize_clinical_date
from drug_interactions import check_known_interactions
from medical_extractor import _normalize_extraction_result
from reference_library import find_concurrent_depressant_risk, find_relevant_guidance


EMPTY = {
    "potential_drug_interactions": [],
    "duplicate_prescriptions": [],
    "conflicting_dosage_instructions": [],
    "allergy_conflicts": [],
}


def test_date_admission_rejects_partial_placeholders_and_keeps_complete_dates():
    assert sanitize_clinical_date("200X-07-07") is None
    assert sanitize_clinical_date("2024") is None
    assert sanitize_clinical_date("2024-07") is None
    assert sanitize_clinical_date("unknown") is None
    assert sanitize_clinical_date("2026-08-15") == "2026-08-15"
    assert sanitize_clinical_date("15 Aug 2026") == "15 Aug 2026"
    # Complete locale-ambiguous dates remain usable under the shared
    # record-wide date convention instead of being guessed independently.
    assert sanitize_clinical_date("03/11/2025") == "03/11/2025"


def test_date_admission_is_applied_recursively_to_extracted_entities():
    result = _normalize_extraction_result({
        "date": "2026-08",
        "medications": [{"start_date": "2026-08-15", "end_date": "20XX-08-20"}],
        "lab_results": [{"result_date": "15 Aug 2026"}],
        "diagnoses": [{"onset_date": "unknown"}],
    })
    assert result["date"] is None
    assert result["medications"][0] == {"start_date": "2026-08-15", "end_date": None}
    assert result["lab_results"][0]["result_date"] == "15 Aug 2026"
    assert result["diagnoses"][0]["onset_date"] is None


def _timeline(*medications):
    return {"medications_timeline": list(medications), "known_allergies": []}


def _med(name, ingredient, date="2026-08-01", duration="30 days", source="rx.pdf"):
    return {
        "name": name,
        "ingredients": [ingredient],
        "date": date,
        "duration": duration,
        "source_file": source,
    }


def test_new_deterministic_interaction_pairs_are_guaranteed():
    pairs = [
        ("Warfarin", "warfarin", "Ciprofloxacin", "ciprofloxacin"),
        ("Lisinopril", "lisinopril", "Ibuprofen", "ibuprofen"),
        ("Digoxin", "digoxin", "Furosemide", "furosemide"),
        ("Amlodipine", "amlodipine", "Simvastatin", "simvastatin"),
    ]
    for a_name, a, b_name, b in pairs:
        findings = check_known_interactions(_timeline(
            _med(a_name, a, source="a.pdf"), _med(b_name, b, source="b.pdf")
        ))
        assert findings, (a, b)
        assert findings[0]["source"] == "curated_knowledge_base"


def test_published_guidance_is_selected_and_only_flags_overlapping_courses():
    concurrent = _timeline(
        _med("Oxycodone", "oxycodone", duration="30 days", source="a.pdf"),
        _med("Diazepam", "diazepam", date="2026-08-10", duration="10 days", source="b.pdf"),
    )
    guidance = find_relevant_guidance(concurrent)
    assert any(item["id"] == "opioid-plus-depressant" for item in guidance)
    findings = find_concurrent_depressant_risk(concurrent)
    assert len(findings) == 1
    assert findings[0]["citation"]["page"] == 13

    non_overlapping = _timeline(
        _med("Oxycodone", "oxycodone", date="2026-01-01", duration="5 days", source="a.pdf"),
        _med("Diazepam", "diazepam", date="2026-08-10", duration="5 days", source="b.pdf"),
    )
    assert find_concurrent_depressant_risk(non_overlapping) == []


def test_triage_deescalates_nonconcurrent_history_without_hiding_it():
    report = generate_consult_triage({
        **EMPTY,
        "potential_drug_interactions": [{
            "medications_involved": ["A", "B"],
            "severity": "high",
            "confidence": 0.9,
            "explanation": "interaction",
            "timing": {"status": "not_concurrent", "gap_days": 100},
        }],
    })
    item = report["referral_items"][0]
    assert item["urgency"] == "routine"
    assert item["is_historical"] is True


def test_triage_escalates_concurrent_duplicate_ingredient():
    report = generate_consult_triage({
        **EMPTY,
        "concurrent_exposure": [{
            "ingredient": "paracetamol",
            "status": "concurrent",
            "window_start": "2026-08-01",
            "window_end": "2026-08-10",
            "cumulative_daily_dose": 5000,
            "dosage_unit": "mg",
        }],
    })
    item = report["referral_items"][0]
    assert item["trigger"] == "concurrent_duplicate_ingredient"
    assert item["route"] == "pharmacist"
    assert item["urgency"] == "urgent"


def test_triage_routes_persistent_abnormal_series_and_translation_risk():
    labs = {"trends": [{
        "test_name": "Creatinine",
        "confidence": 0.9,
        "data_points": [{"flag": "high"}, {"flag": "high"}],
        "crossed_into_abnormal_at": None,
        "approaching_threshold": False,
        "explanation": "Remained high.",
    }]}
    timeline = {"visits": [{
        "_source": {"file": "foreign-rx.jpg"},
        "document_language": "Sinhala",
        "ocr_confidence": 0.95,
        "translation_confidence": 0.5,
        "overall_confidence": 0.8,
        "illegible_or_low_confidence_fields": [],
    }]}
    report = generate_consult_triage(EMPTY, labs, {"findings": []}, timeline)
    triggers = {item["trigger"] for item in report["referral_items"]}
    assert "lab_persistently_abnormal" in triggers
    assert "translation_uncertain" in triggers
