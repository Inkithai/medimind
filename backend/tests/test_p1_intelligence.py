"""Offline tests for the P1 backend-intelligence expansions:
expanded preventive care, symptom correlation, and guideline auto-refresh."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import preventive_care as pc  # noqa: E402
import symptom_intake as si  # noqa: E402
import living_guidelines as lg  # noqa: E402


def _timeline(meds=None, conditions=None):
    t = {"medications_timeline": meds or [], "diagnoses_timeline": []}
    if conditions is not None:
        t["diagnoses_timeline"] = [{"name": c} for c in conditions]
    return t


def _med(name, ing):
    return {"name": name, "ingredients": ing, "date": "2024-01-01"}


def _labs(t, v, u="mmol/L", flag="normal"):
    return {"test_name": t, "value": v, "unit": u, "reference_range": None, "flag": flag,
            "confidence": 0.9, "date": "2024-02-01", "source_file": "lab.pdf"}


# ---- preventive care: medication-driven monitoring ----------------------- #

def test_warfarin_triggers_inr_monitoring():
    out = pc.generate_care_gaps(_timeline(meds=[_med("Warfarin", ["warfarin"])]), 60, "male")
    titles = {g["title"] for g in out["care_gaps"]}
    assert "INR / bleeding monitoring (warfarin)" in titles


def test_methotrexate_triggers_monitoring():
    out = pc.generate_care_gaps(_timeline(meds=[_med("Methotrexate", ["methotrexate"])]), 50, "female")
    titles = {g["title"] for g in out["care_gaps"]}
    assert "Methotrexate monitoring" in titles


def test_diuretic_and_acei_monitoring():
    out = pc.generate_care_gaps(_timeline(meds=[_med("Furosemide", ["furosemide"]),
                                                _med("Ramipril", ["ramipril"])]), 70, "male")
    titles = {g["title"] for g in out["care_gaps"]}
    assert "Diuretic monitoring" in titles
    assert "ACE-inhibitor / ARB monitoring" in titles


def test_metformin_monitoring_priority_routine():
    out = pc.generate_care_gaps(_timeline(meds=[_med("Glucophage", ["metformin"])]), 55, "female")
    m = [g for g in out["care_gaps"] if g["title"] == "Metformin monitoring"]
    assert m and m[0]["priority"] == "routine"


# ---- preventive care: condition-driven monitoring ------------------------ #

def test_afib_triggers_stroke_prevention():
    out = pc.generate_care_gaps(_timeline(conditions=["Atrial fibrillation"]), 72, "male")
    titles = {g["title"] for g in out["care_gaps"]}
    assert "Stroke-prevention review" in titles


def test_hypothyroid_and_osteoporosis_monitoring():
    out = pc.generate_care_gaps(_timeline(conditions=["Hypothyroidism", "Osteoporosis"]), 68, "female")
    titles = {g["title"] for g in out["care_gaps"]}
    assert "Thyroid-function monitoring" in titles
    assert "Bone-health review" in titles


# ---- preventive care: extra screenings ----------------------------------- #

def test_aaa_screening_for_older_male():
    out = pc.generate_care_gaps(_timeline(), 66, "male")
    titles = {g["title"] for g in out["care_gaps"]}
    assert "Abdominal aortic aneurysm (AAA) screening" in titles


def test_no_aaa_for_female():
    out = pc.generate_care_gaps(_timeline(), 70, "female")
    titles = {g["title"] for g in out["care_gaps"]}
    assert "Abdominal aortic aneurysm (AAA) screening" not in titles


def test_hcv_hiv_for_adult():
    out = pc.generate_care_gaps(_timeline(), 40, "male")
    titles = {g["title"] for g in out["care_gaps"]}
    assert "Hepatitis C screening" in titles
    assert "HIV screening" in titles


def test_lung_cancer_screening_for_smoker_in_age_range():
    out = pc.generate_care_gaps(_timeline(conditions=["Smoker"]), 60, "male")
    titles = {g["title"] for g in out["care_gaps"]}
    assert "Lung-cancer screening (smoking history)" in titles
    assert "Smoking-cessation support" in titles


# ---- symptom correlation: new symptoms + drug mapping -------------------- #

def test_constipation_correlates_opioid():
    out = si.analyse_symptom(_timeline(meds=[_med("Codeine", ["codeine"])]), "severe constipation")
    assert out["analysed"] is True
    assert "Codeine" in out["findings"][0]["relevant_medications_on_record"]


def test_diarrhoea_correlates_metformin():
    out = si.analyse_symptom(_timeline(meds=[_med("Glucophage", ["metformin"])]), "diarrhoea")
    assert "Glucophage" in out["findings"][0]["relevant_medications_on_record"]


def test_neuropathy_correlates_metformin():
    out = si.analyse_symptom(_timeline(meds=[_med("Glucophage", ["metformin"])]), "numbness and tingling in feet")
    assert "Glucophage" in out["findings"][0]["relevant_medications_on_record"]


def test_frequent_infections_correlates_steroid():
    out = si.analyse_symptom(_timeline(meds=[_med("Prednisolone", ["prednisolone"])]), "keep getting infections")
    assert "Prednisolone" in out["findings"][0]["relevant_medications_on_record"]


# ---- symptom correlation: conditions + labs ----------------------------- #

def test_chest_pain_correlates_heart_condition():
    out = si.analyse_symptom(_timeline(conditions=["Coronary heart disease"]), "chest pain")
    assert out["analysed"] is True
    assert any("Coronary heart disease" in c
               for c in out["findings"][0]["relevant_conditions_on_record"])


def test_fatigue_correlates_diabetes_condition_and_glucose_lab():
    tl = _timeline(conditions=["Type 2 diabetes"])
    tl["lab_results_timeline"] = [_labs("Glucose", "12", "mmol/L", "high")]
    out = si.analyse_symptom(tl, "very tired all the time")
    f = out["findings"][0]
    assert any("diabetes" in c.lower() for c in f["relevant_conditions_on_record"])
    assert any("glucose" in l.lower() for l in f["relevant_abnormal_labs"])


def test_palpitations_correlates_thyroid_condition():
    out = si.analyse_symptom(_timeline(conditions=["Hyperthyroidism"]), "racing heartbeat")
    assert any("thyroid" in c.lower() for c in out["findings"][0]["relevant_conditions_on_record"])


def test_no_correlation_for_unrelated_record():
    out = si.analyse_symptom(_timeline(meds=[_med("Paracetamol", ["paracetamol"])]), "dizzy")
    assert out["findings"][0]["relevant_medications_on_record"] == []


# ---- living guidelines auto-refresh ------------------------------------- #

def test_refresh_flags_newer_manifest_version(monkeypatch=None):
    lg.reset()
    lg.registry_status()  # seed
    # register a known version
    lg.mark_reviewed("drug_interactions", version="2026-01")
    # manifest says a newer version exists
    lg._fetch_manifest = lambda url: {"sources": {"drug_interactions": {"version": "2026-09"}}}
    check = lg.check_for_updates()
    assert check["checked"] is True
    assert any(u["key"] == "drug_interactions" and u["latest_version"] == "2026-09"
               for u in check["updates_available"])


def test_refresh_applies_newer_version():
    lg.reset()
    lg.mark_reviewed("drug_interactions", version="2026-01")
    lg._fetch_manifest = lambda url: {"drug_interactions": {"version": "2026-09"}}
    result = lg.apply_updates()
    assert result["applied_count"] == 1
    status = lg.registry_status()
    drug = [s for s in status["sources"] if s["key"] == "drug_interactions"][0]
    assert drug["version"] == "2026-09"


def test_refresh_no_manifest_returns_manual():
    lg.reset()
    lg._fetch_manifest = lambda url: None  # simulate no/failing manifest
    check = lg.check_for_updates()
    assert check["checked"] is False
    assert "manual" in check["reason"].lower()


def test_refresh_no_update_when_versions_match():
    lg.reset()
    lg.mark_reviewed("drug_interactions", version="2026-09")
    lg._fetch_manifest = lambda url: {"drug_interactions": {"version": "2026-09"}}
    check = lg.check_for_updates()
    assert check["updates_available"] == []
