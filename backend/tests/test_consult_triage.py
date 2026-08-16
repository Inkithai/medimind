"""Offline tests for the deterministic consult-triage routing layer."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from consult_triage import generate_consult_triage  # noqa: E402


EMPTY_CROSS_CHECK = {
    "potential_drug_interactions": [],
    "duplicate_prescriptions": [],
    "conflicting_dosage_instructions": [],
    "allergy_conflicts": [],
    "overall_recommendation": "Consult a professional.",
}


def test_no_findings_means_no_consult_but_never_a_clean_bill():
    report = generate_consult_triage(EMPTY_CROSS_CHECK, {"trends": []}, {"findings": []})
    assert report["consult_needed"] is False
    assert report["consult_type"] is None
    assert report["referral_items"] == []
    assert "not a clean bill of health" in report["summary"]
    assert report["emergency_advice"]  # standing advice always present


def test_allergy_conflict_routes_to_doctor_urgent():
    cross_check = {**EMPTY_CROSS_CHECK, "allergy_conflicts": [{
        "medication": "Amoxicillin", "allergy": "Penicillin",
        "explanation": "Penicillin-class antibiotic.", "confidence": 0.9,
    }]}
    report = generate_consult_triage(cross_check)
    assert report["consult_needed"] is True
    assert report["consult_type"] == "doctor"
    assert report["urgency"] == "urgent"
    item = report["doctor_actions"][0]
    assert item["trigger"] == "allergy_conflict"
    assert item["specialty"]["key"] == "general_physician"


def test_high_interaction_to_doctor_moderate_to_pharmacist():
    cross_check = {**EMPTY_CROSS_CHECK, "potential_drug_interactions": [
        {"medications_involved": ["Warfarin", "Ibuprofen"], "explanation": "bleeding",
         "severity": "high", "confidence": 0.95},
        {"medications_involved": ["Sertraline", "Tramadol"], "explanation": "serotonin",
         "severity": "moderate", "confidence": 0.8},
    ]}
    report = generate_consult_triage(cross_check)
    assert len(report["doctor_actions"]) == 1
    assert report["doctor_actions"][0]["urgency"] == "urgent"
    assert len(report["pharmacist_actions"]) == 1
    assert report["pharmacist_actions"][0]["urgency"] == "soon"


def test_duplicates_and_dosage_conflicts_route_to_pharmacist():
    cross_check = {
        **EMPTY_CROSS_CHECK,
        "duplicate_prescriptions": [{"medication": "Metformin", "explanation": "dup", "confidence": 0.9}],
        "conflicting_dosage_instructions": [{"medication": "Metformin", "explanation": "conflict", "confidence": 0.85}],
    }
    report = generate_consult_triage(cross_check)
    assert report["consult_type"] == "pharmacist"
    assert {i["trigger"] for i in report["pharmacist_actions"]} == {
        "duplicate_prescription", "conflicting_dosage_instructions",
    }
    assert all(i["urgency"] == "soon" for i in report["pharmacist_actions"])


def test_dosage_ceiling_findings_route_to_doctor_urgent():
    dosage = {"findings": [{
        "kind": "above_max_daily_dose", "medication": "Paracetamol",
        "ingredient": "paracetamol", "explanation": "5000 mg/day", "confidence": 0.95,
    }]}
    report = generate_consult_triage(EMPTY_CROSS_CHECK, None, dosage)
    assert report["consult_type"] == "doctor"
    assert report["urgency"] == "urgent"
    assert report["doctor_actions"][0]["trigger"] == "dosage_above_max_daily_dose"


def test_subtherapeutic_dose_routes_to_pharmacist_routine():
    dosage = {"findings": [{
        "kind": "below_min_single_dose", "medication": "Aspirin",
        "ingredient": "aspirin", "explanation": "10 mg", "confidence": 0.95,
    }]}
    report = generate_consult_triage(EMPTY_CROSS_CHECK, None, dosage)
    assert report["consult_type"] == "pharmacist"
    assert report["pharmacist_actions"][0]["urgency"] == "routine"


def test_lab_crossing_routes_to_doctor_with_mapped_specialty():
    lab_trends = {"trends": [{
        "test_name": "HbA1c", "confidence": 0.95,
        "crossed_into_abnormal_at": {"date": "2024-04-20", "flag": "high"},
        "approaching_threshold": False,
    }]}
    report = generate_consult_triage(EMPTY_CROSS_CHECK, lab_trends)
    item = report["doctor_actions"][0]
    assert item["urgency"] == "soon"
    assert item["specialty"]["key"] == "endocrinologist"
    assert report["recommended_specialties"][0]["key"] == "endocrinologist"


def test_lab_approaching_boundary_is_routine():
    lab_trends = {"trends": [{
        "test_name": "Creatinine", "confidence": 0.9,
        "crossed_into_abnormal_at": None, "approaching_threshold": True,
    }]}
    report = generate_consult_triage(EMPTY_CROSS_CHECK, lab_trends)
    item = report["doctor_actions"][0]
    assert item["urgency"] == "routine"
    assert item["specialty"]["key"] == "nephrologist"


def test_unmapped_lab_falls_back_to_gp_never_losing_the_referral():
    lab_trends = {"trends": [{
        "test_name": "Some Obscure Assay", "confidence": 0.9,
        "crossed_into_abnormal_at": {"date": "2024-01-01", "flag": "high"},
        "approaching_threshold": False,
    }]}
    report = generate_consult_triage(EMPTY_CROSS_CHECK, lab_trends)
    assert report["doctor_actions"][0]["specialty"]["key"] == "general_physician"


def test_low_confidence_never_lowers_urgency():
    cross_check = {**EMPTY_CROSS_CHECK, "allergy_conflicts": [{
        "medication": "Amoxicillin", "allergy": "Penicillin",
        "explanation": "barely legible", "confidence": 0.4,
    }]}
    report = generate_consult_triage(cross_check)
    item = report["doctor_actions"][0]
    assert item["urgency"] == "urgent"            # unchanged
    assert "confidence_caveat" in item             # caveat instead
    assert "urgency is unchanged" in item["confidence_caveat"]


def test_referral_items_sorted_most_urgent_first_and_doctor_wins_type():
    cross_check = {
        **EMPTY_CROSS_CHECK,
        "duplicate_prescriptions": [{"medication": "X", "explanation": "d", "confidence": 0.9}],
        "allergy_conflicts": [{"medication": "A", "allergy": "B", "explanation": "a", "confidence": 0.9}],
    }
    lab_trends = {"trends": [{
        "test_name": "ALT", "confidence": 0.9,
        "crossed_into_abnormal_at": None, "approaching_threshold": True,
    }]}
    report = generate_consult_triage(cross_check, lab_trends)
    urgencies = [i["urgency"] for i in report["referral_items"]]
    assert urgencies == sorted(urgencies, key={"routine": 0, "soon": 1, "urgent": 2}.get, reverse=True)
    assert report["consult_type"] == "doctor"
    assert report["urgency"] == "urgent"


def test_no_emergency_urgency_level_exists():
    cross_check = {**EMPTY_CROSS_CHECK, "allergy_conflicts": [{
        "medication": "A", "allergy": "B", "explanation": "x", "confidence": 1.0,
    }]}
    report = generate_consult_triage(cross_check)
    assert all(i["urgency"] in ("routine", "soon", "urgent") for i in report["referral_items"])
    assert "emergency care immediately" in report["emergency_advice"]


def test_specialties_deduplicated_with_triggers_merged():
    lab_trends = {"trends": [
        {"test_name": "ALT", "confidence": 0.9,
         "crossed_into_abnormal_at": {"date": "2024-01-01", "flag": "high"}, "approaching_threshold": False},
        {"test_name": "AST", "confidence": 0.9,
         "crossed_into_abnormal_at": {"date": "2024-01-01", "flag": "high"}, "approaching_threshold": False},
    ]}
    report = generate_consult_triage(EMPTY_CROSS_CHECK, lab_trends)
    specialties = report["recommended_specialties"]
    assert len(specialties) == 1
    assert specialties[0]["key"] == "gastroenterologist"
    assert set(specialties[0]["triggered_by"]) == {"ALT", "AST"}


# ---------------------------------------------------------------------------
# Regression: specialty matching used PLAIN SUBSTRING on the test name, so
# any word containing a short keyword's letters hijacked the route —
# "Fasting Lipid Profile" contains "ast" (f-ast-ing) and was sent to a
# hepatologist instead of cardiology, and "Hemoglobin A1c" never matched
# "hba1c" and fell through to the hematologist below it.
# ---------------------------------------------------------------------------

from consult_triage import _specialty_for_lab  # noqa: E402


def test_fasting_lipid_panel_routes_to_cardiology_not_hepatology():
    for name in ("Fasting Lipid Profile", "Fasting Lipids", "Fasting Lipid Panel"):
        assert _specialty_for_lab(name)["key"] == "cardiologist", name


def test_keywords_do_not_fire_inside_unrelated_words():
    # "fasting" contains "ast"; "standby" contains no keyword but the
    # boundary checks guard the whole map against this class of error.
    assert _specialty_for_lab("Fasting ESR")["key"] != "gastroenterologist"
    assert _specialty_for_lab("ESR")["key"] == "general_physician"
    assert _specialty_for_lab("Vitamin B12")["key"] == "general_physician"


def test_abbreviations_and_full_names_both_match():
    assert _specialty_for_lab("ALT")["key"] == "gastroenterologist"
    assert _specialty_for_lab("AST")["key"] == "gastroenterologist"
    assert _specialty_for_lab("Alkaline Phosphatase")["key"] == "gastroenterologist"
    assert _specialty_for_lab("PT/INR")["key"] == "hematologist"
    assert _specialty_for_lab("Total Platelet Count")["key"] == "hematologist"


def test_a1c_spellings_route_to_endocrinology():
    for name in ("HbA1c", "Hemoglobin A1c", "Glycated Haemoglobin (HbA1c)"):
        assert _specialty_for_lab(name)["key"] == "endocrinologist", name
    # A plain haemoglobin count is still haematology.
    assert _specialty_for_lab("Haemoglobin")["key"] == "hematologist"


def test_free_thyroid_spellings_match():
    assert _specialty_for_lab("Free T4")["key"] == "endocrinologist"
    assert _specialty_for_lab("FT4")["key"] == "endocrinologist"
    assert _specialty_for_lab("FT3")["key"] == "endocrinologist"


def test_troponin_bnp_family_intact():
    assert _specialty_for_lab("Troponin I")["key"] == "cardiologist"
    assert _specialty_for_lab("NT-proBNP")["key"] == "cardiologist"
    assert _specialty_for_lab("Triglycerides")["key"] == "cardiologist"
