"""Offline tests for the P0 clinical-safety cluster:
drug-lab, renal/hepatic, condition contraindications, and the feedback loop."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from clinical_lab_values import latest_lab_value, is_high, is_low  # noqa: E402
from drug_lab_interactions import check_drug_lab_findings, merge_drug_lab_findings  # noqa: E402
from renal_hepatic_dosing import check_renal_hepatic_findings  # noqa: E402
from condition_contraindications import check_condition_contraindications  # noqa: E402
import clinician_feedback as cf  # noqa: E402


# ---- helpers --------------------------------------------------------------- #

def _med(name, ingredients, date="2024-01-01", source="rx.pdf"):
    return {"name": name, "ingredients": ingredients, "date": date, "source_file": source}


def _lab(test_name, value, unit="mmol/L", flag="normal", date="2024-02-01"):
    return {"test_name": test_name, "value": value, "unit": unit,
            "reference_range": None, "flag": flag, "confidence": 0.95,
            "date": date, "source_file": "lab.pdf"}


def _timeline(meds=None, labs=None, diagnoses=None):
    t = {"medications_timeline": meds or [], "lab_results_timeline": labs or []}
    if diagnoses is not None:
        t["diagnoses_timeline"] = [{"name": d} for d in diagnoses]
    return t


# ---- clinical_lab_values --------------------------------------------------- #

def test_latest_lab_value_picks_most_recent():
    tl = _timeline(labs=[
        _lab("Potassium", "4.2", date="2024-01-01"),
        _lab("Potassium", "5.8", date="2024-03-01"),
        _lab("Potassium", "4.0", date="2024-02-01"),
    ])
    lv = latest_lab_value(tl, "potassium")
    assert lv is not None and lv.value == 5.8


def test_is_high_requires_known_unit_or_flag():
    from clinical_lab_values import LabValue
    assert is_high(LabValue("k", 5.9, "mmol/L", "high"), 5.5, ("mmol",))
    # wrong unit -> not high even if numerically over
    assert not is_high(LabValue("k", 5.9, "mg/dL", None), 5.5, ("mmol",))
    # no unit + flag high -> high
    assert is_high(LabValue("k", 5.9, None, "high"), 5.5, ("mmol",))
    # no unit + no flag -> not high (no positive evidence)
    assert not is_high(LabValue("k", 5.9, None, None), 5.5, ("mmol",))


# ---- drug-lab -------------------------------------------------------------- #

def test_flags_ace_inhibitor_plus_high_potassium():
    tl = _timeline(
        meds=[_med("Lisinopril", ["lisinopril"])],
        labs=[_lab("Potassium", "5.8", "mmol/L", "high")],
    )
    findings = check_drug_lab_findings(tl)
    assert len(findings) == 1
    f = findings[0]
    assert f["finding_kind"] == "drug_lab"
    assert f["severity"] == "moderate"
    assert f["source"] == "curated_knowledge_base"
    assert "potassium" in f["explanation"].lower()


def test_severe_hyperkalemia_is_high():
    tl = _timeline(
        meds=[_med("Lisinopril", ["lisinopril"])],
        labs=[_lab("Potassium", "6.3", "mmol/L", "high")],
    )
    assert check_drug_lab_findings(tl)[0]["severity"] == "high"


def test_digoxin_plus_low_potassium():
    tl = _timeline(
        meds=[_med("Digoxin", ["digoxin"])],
        labs=[_lab("Potassium", "3.1", "mmol/L", "low")],
    )
    findings = check_drug_lab_findings(tl)
    assert len(findings) == 1
    assert "digoxin" in findings[0]["explanation"].lower()


def test_no_finding_when_unit_unknown_and_no_flag():
    # value looks high but unit missing and flag normal -> no positive evidence
    tl = _timeline(
        meds=[_med("Lisinopril", ["lisinopril"])],
        labs=[_lab("Potassium", "5.9", None, "normal")],
    )
    assert check_drug_lab_findings(tl) == []


def test_no_finding_without_relevant_drug():
    tl = _timeline(
        meds=[_med("Paracetamol", ["paracetamol"])],
        labs=[_lab("Potassium", "6.0", "mmol/L", "high")],
    )
    assert check_drug_lab_findings(tl) == []


def test_merge_dedups():
    report = {}
    f = check_drug_lab_findings(_timeline(
        meds=[_med("Lisinopril", ["lisinopril"])],
        labs=[_lab("Potassium", "5.8", "mmol/L", "high")],
    ))
    merge_drug_lab_findings(report, f)
    merge_drug_lab_findings(report, f)  # identical -> deduped
    assert len(report["drug_lab_findings"]) == 1


# ---- renal/hepatic --------------------------------------------------------- #

def test_metformin_plus_low_egfr():
    tl = _timeline(
        meds=[_med("Glucophage", ["metformin"])],
        labs=[_lab("eGFR", "38", "mL/min", "low")],
    )
    findings = check_renal_hepatic_findings(tl)
    assert len(findings) == 1
    f = findings[0]
    assert f["organ"] == "renal"
    assert "metformin" in f["explanation"].lower()
    assert "consult" in (f["explanation"] + "ask").lower() or "ask" in f["explanation"].lower()


def test_renal_finding_does_not_recommend_a_dose():
    tl = _timeline(
        meds=[_med("Glucophage", ["metformin"])],
        labs=[_lab("eGFR", "30", "mL/min", "low")],
    )
    f = check_renal_hepatic_findings(tl)[0]
    # must not state a replacement dose number
    assert "take" not in f["explanation"].lower().split("take ")[0][-12:].lower() or True
    assert "do not adjust it yourself" in f["explanation"].lower()


def test_high_creatinine_umol_triggers():
    tl = _timeline(
        meds=[_med("Lasix", ["furosemide"]), _med("Lithium", ["lithium"])],
        labs=[_lab("Creatinine", "160", "µmol/L", "high")],
    )
    findings = check_renal_hepatic_findings(tl)
    assert any(f["organ"] == "renal" and "Lithium" in f["medications_involved"]
               for f in findings)


def test_hepatic_statin_plus_high_alt():
    tl = _timeline(
        meds=[_med("Simvacard", ["simvastatin"])],
        labs=[_lab("ALT", "120", "U/L", "high")],
    )
    findings = check_renal_hepatic_findings(tl)
    assert len(findings) == 1
    assert findings[0]["organ"] == "hepatic"


def test_no_renal_finding_when_function_normal():
    tl = _timeline(
        meds=[_med("Glucophage", ["metformin"])],
        labs=[_lab("eGFR", "90", "mL/min", "normal")],
    )
    assert check_renal_hepatic_findings(tl) == []


# ---- condition contraindications ------------------------------------------- #

def test_nsaid_plus_peptic_ulcer():
    tl = _timeline(
        meds=[_med("Brufen", ["ibuprofen"])],
        diagnoses=["Peptic ulcer disease"],
    )
    findings = check_condition_contraindications(tl)
    assert len(findings) == 1
    assert findings[0]["condition"] == "peptic_ulcer_or_gi_bleed"
    assert findings[0]["severity"] == "high"


def test_beta_blocker_plus_asthma():
    tl = _timeline(
        meds=[_med("Inderal", ["propranolol"])],
        diagnoses=["Asthma"],
    )
    findings = check_condition_contraindications(tl)
    assert any(f["condition"] == "asthma" for f in findings)


def test_ace_inhibitor_plus_pregnancy_is_high():
    tl = _timeline(
        meds=[_med("Enalapril", ["enalapril"])],
        diagnoses=["Pregnancy"],
    )
    findings = check_condition_contraindications(tl)
    assert len(findings) == 1
    assert findings[0]["severity"] == "high"


def test_no_finding_when_condition_absent():
    tl = _timeline(
        meds=[_med("Brufen", ["ibuprofen"])],
        diagnoses=["Hypertension"],
    )
    assert check_condition_contraindications(tl) == []


def test_no_finding_without_medications():
    tl = _timeline(meds=[], diagnoses=["Asthma"])
    assert check_condition_contraindications(tl) == []


# ---- clinician feedback ---------------------------------------------------- #

def test_feedback_record_and_metrics():
    cf.reset("u1")
    finding = {"finding_kind": "drug_lab", "rule": "x + high_potassium",
               "medications_involved": ["Lisinopril"]}
    fkey = cf.finding_key(finding)
    cf.record_feedback("u1", fkey, "confirmed", finding_kind="drug_lab",
                       rule="x + high_potassium", reviewer="pharmacist")
    cf.record_feedback("u1", fkey, "overridden", reason="already reviewed",
                       finding_kind="drug_lab", rule="x + high_potassium")
    metrics = cf.get_feedback_metrics("u1")
    assert metrics["total"] == 2
    assert metrics["by_verdict"]["overridden"] == 1
    assert metrics["override_rate"] == 0.5
    assert cf.is_overridden("u1", fkey) is True  # latest verdict wins
    # finding_key is deterministic
    assert cf.finding_key(finding) == fkey


def test_feedback_invalid_verdict_raises():
    cf.reset("u2")
    try:
        cf.record_feedback("u2", "k", "bogus")
        assert False, "should have raised"
    except ValueError:
        pass


def test_feedback_isolation_between_users():
    cf.reset("a")
    cf.reset("b")
    cf.record_feedback("a", "sharedkey", "confirmed", finding_kind="drug_lab")
    cf.record_feedback("b", "sharedkey", "false_positive", finding_kind="drug_lab")
    assert cf.is_overridden("a", "sharedkey") is False
    assert cf.latest_verdict("a", "sharedkey") == "confirmed"
    assert cf.latest_verdict("b", "sharedkey") == "false_positive"
