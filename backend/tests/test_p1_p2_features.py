"""Offline tests for the P1/P2 longitudinal & platform features."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import vital_trends as vt  # noqa: E402
import symptom_intake as si  # noqa: E402
import preventive_care as pc  # noqa: E402
import alert_management as am  # noqa: E402
import adherence as adh  # noqa: E402
import early_warning as ew  # noqa: E402
import finding_lifecycle as fl  # noqa: E402
import fhir_ingestion as fh  # noqa: E402
import patient_data as pd  # noqa: E402
import secure_messaging as sm  # noqa: E402
import living_guidelines as lg  # noqa: E402
import clinician_feedback as cf  # noqa: E402


def _timeline(meds=None, labs=None, vitals=None, diagnoses=None):
    t = {"medications_timeline": meds or [], "lab_results_timeline": labs or [],
         "vital_signs_timeline": vitals or []}
    if diagnoses is not None:
        t["diagnoses_timeline"] = [{"name": d} for d in diagnoses]
    return t


# ---- vital trends ---------------------------------------------------------- #

def test_vital_trends_bp_hypertensive():
    tl = _timeline(vitals=[
        {"name": "Blood Pressure", "value": "128/82", "unit": "mmHg", "measured_at": "2024-01-01"},
        {"name": "Blood Pressure", "value": "148/94", "unit": "mmHg", "measured_at": "2024-04-01"},
    ])
    out = vt.track_vital_trends(tl)
    bp = [t for t in out["trends"] if t["vital"] == "blood_pressure"][0]
    assert bp["latest_flag"] == "high"
    assert bp["risk_level"] == "abnormal"
    assert bp["direction"] == "increasing"


def test_vital_trends_normal_pulse():
    tl = _timeline(vitals=[{"name": "Pulse", "value": "72", "unit": "bpm", "measured_at": "2024-01-01"}])
    out = vt.track_vital_trends(tl)
    pulse = [t for t in out["trends"] if t["vital"] == "heart_rate"][0]
    assert pulse["latest_flag"] is None


# ---- symptom intake -------------------------------------------------------- #

def test_symptom_dry_cough_finds_ace_inhibitor():
    tl = _timeline(meds=[{"name": "Lisinopril", "ingredients": ["lisinopril"], "date": "2024-01-01"}])
    out = si.analyse_symptom(tl, "I have a dry cough for a week")
    assert out["analysed"] is True
    assert any("Lisinopril" in m for m in out["findings"][0]["relevant_medications_on_record"])
    assert "not a diagnosis" in out["summary"].lower()


def test_symptom_unmatched_is_neutral():
    tl = _timeline(meds=[])
    out = si.analyse_symptom(tl, "I feel great")
    assert out["analysed"] is False


# ---- preventive care ------------------------------------------------------- #

def test_preventive_care_age_60_female():
    out = pc.generate_care_gaps(_timeline(diagnoses=["Type 2 diabetes"]), 60, "female")
    titles = {g["title"] for g in out["care_gaps"]}
    assert "Colorectal cancer screening" in titles
    assert "Mammography (breast cancer screening)" in titles
    assert "Cervical screening (Pap/HPV)" in titles
    assert any("Diabetes monitoring" in g["title"] for g in out["care_gaps"])


def test_preventive_care_no_age_only_generic():
    out = pc.generate_care_gaps(_timeline(), None, None)
    assert out["count"] >= 2  # flu + covid generic
    assert all("age 50" not in g["detail"] for g in out["care_gaps"])


# ---- alert management ------------------------------------------------------ #

def test_alert_management_suppresses_overridden_and_dedups():
    cf.reset("u")
    report = {
        "potential_drug_interactions": [
            {"finding_kind": "ddi", "rule": "warfarin + nsaid", "medications_involved": ["Warfarin", "Brufen"], "severity": "high"},
            {"finding_kind": "ddi", "rule": "warfarin + nsaid", "medications_involved": ["Warfarin", "Brufen"], "severity": "high"},  # near-dup
            {"finding_kind": "ddi", "rule": "ace + k", "medications_involved": ["Lisinopril"], "severity": "moderate"},
        ]
    }
    # mark the ace+k finding overridden
    fkey = cf.finding_key(report["potential_drug_interactions"][2])
    cf.record_feedback("u", fkey, "overridden", reason="reviewed", finding_kind="ddi", rule="ace + k")
    view = am.manage_alerts(report, "u")
    assert view["active_count"] == 1  # warfarin+nsaid collapsed, ace+k suppressed
    assert view["collapsed_duplicates"] == 1
    assert view["suppressed_count"] == 1


# ---- adherence ------------------------------------------------------------- #

def test_adherence_refill_gap_detected():
    tl = _timeline(meds=[
        {"name": "Metformin", "ingredients": ["metformin"], "date": "2024-01-01", "duration_days": 30},
        {"name": "Metformin", "ingredients": ["metformin"], "date": "2024-05-01", "duration_days": 30},
    ])
    out = adh.analyse_adherence(tl, reference_date="2024-06-01")
    # a ~91-day gap between supplies is a supply-gap signal (refill_gap or late_refill)
    assert any(s["signal"] in ("refill_gap", "late_refill") for s in out["signals"])


def test_adherence_no_signal_when_continuous():
    tl = _timeline(meds=[
        {"name": "Metformin", "ingredients": ["metformin"], "date": "2024-01-01", "duration_days": 30},
        {"name": "Metformin", "ingredients": ["metformin"], "date": "2024-01-28", "duration_days": 30},
    ])
    out = adh.analyse_adherence(tl, reference_date="2024-02-15")
    assert out["signals"] == []


# ---- early warning --------------------------------------------------------- #

def test_ews_high_score_with_abnormal_vitals():
    tl = _timeline(vitals=[
        {"name": "Respiratory rate", "value": "26", "measured_at": "2024-01-01"},
        {"name": "Oxygen saturation", "value": "89", "measured_at": "2024-01-01"},
        {"name": "Heart rate", "value": "135", "measured_at": "2024-01-01"},
    ])
    out = ew.compute_early_warning_score(tl)
    assert out["score"] >= 7
    assert out["risk_band"] == "high"


def test_ews_low_score_sparse():
    out = ew.compute_early_warning_score(_timeline())
    assert out["score"] == 0
    assert "not a diagnosis" in out["note"].lower()


# ---- finding lifecycle ----------------------------------------------------- #

def test_lifecycle_transitions_validate():
    fl.reset("u")
    finding = {"finding_kind": "ddi", "rule": "r", "medications_involved": ["A", "B"]}
    r = fl.transition("u", finding, "active")
    assert r["state"] == "active"
    fl.transition("u", finding, "reviewed")
    fl.transition("u", finding, "confirmed")
    fl.transition("u", finding, "resolved")
    assert fl.current_state("u", fl.finding_key(finding)) == "resolved"
    # illegal: resolved -> confirmed not allowed
    try:
        fl.transition("u", finding, "confirmed")
        assert False
    except ValueError:
        pass
    # reopened returns to active path
    fl.transition("u", finding, "reopened")
    fl.transition("u", finding, "active")
    assert fl.current_state("u", fl.finding_key(finding)) == "active"


def test_lifecycle_overview_counts():
    fl.reset("u")
    findings = [{"finding_kind": "ddi", "rule": "r1", "medications_involved": ["A"]}]
    fl.transition("u", findings[0], "active")
    out = fl.lifecycle_overview("u", findings)
    assert out["open_count"] == 1
    assert out["findings"][0]["lifecycle_state"] == "active"


# ---- fhir ingestion -------------------------------------------------------- #

def test_fhir_parses_bundle():
    bundle = {
        "resourceType": "Bundle",
        "entry": [
            {"resource": {"resourceType": "Patient",
                          "name": [{"given": ["Jane"], "family": "Doe"}]}},
            {"resource": {"resourceType": "MedicationStatement",
                          "medicationCodeableConcept": {"text": "Metformin 500mg"}}},
            {"resource": {"resourceType": "Observation", "code": {"text": "Glucose"},
                          "valueQuantity": {"value": 8.5, "unit": "mmol/L"}}},
            {"resource": {"resourceType": "Condition", "code": {"text": "Type 2 diabetes"}}},
            {"resource": {"resourceType": "AllergyIntolerance", "code": {"text": "Penicillin"}}},
            {"resource": {"resourceType": "ImagingStudy"}},  # ignored
        ],
    }
    out = fh.parse_fhir_bundle(bundle)
    assert out["patient_name"] == "Jane Doe"
    assert out["imported"]["medications"] == 1
    assert out["imported"]["conditions"] == 1
    assert out["imported"]["allergies"] == 1
    assert "ImagingStudy" in out["ignored_resource_types"]
    doc = out["documents"][0]
    assert doc["patient_name"] == "Jane Doe"
    assert doc["medications"][0]["name"] == "Metformin 500mg"


# ---- patient data ---------------------------------------------------------- #

def test_patient_data_augments_timeline():
    pd.reset("u")
    pd.record_measurement("u", "Blood Pressure", "140/90", unit="mmHg",
                          measured_at="2024-05-01", kind="vital")
    base = _timeline()
    aug = pd.augment_timeline(base, "u")
    assert len(aug["vital_signs_timeline"]) == 1
    assert aug["vital_signs_timeline"][0]["_source"]["file"] == "patient_reported"
    # original not mutated
    assert base["vital_signs_timeline"] == []


# ---- secure messaging ------------------------------------------------------ #

def test_secure_messaging_thread():
    sm.reset("u")
    m1 = sm.send_message("u", "Hello about my prescription", provider="Dr Smith")
    sm.send_message("u", "Follow-up: is the dose ok?", provider="Dr Smith", thread_id=m1["thread_id"])
    threads = sm.list_threads("u")
    assert len(threads) == 1
    assert threads[0]["message_count"] == 2
    msgs = sm.list_messages("u", m1["thread_id"])
    assert len(msgs) == 2


# ---- living guidelines ----------------------------------------------------- #

def test_living_guidelines_seeds_and_flags_stale():
    lg.reset()
    status = lg.registry_status(staleness_days=-1)  # force every source stale
    assert status["total"] >= 5
    assert status["stale_count"] == status["total"]
    # mark one reviewed today with a sane threshold -> not stale
    lg.mark_reviewed("drug_interactions", version="2026-08")
    status2 = lg.registry_status(staleness_days=30)
    drug = [s for s in status2["sources"] if s["key"] == "drug_interactions"][0]
    assert drug["stale"] is False
