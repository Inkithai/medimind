"""Offline tests for the P0 medical-intelligence deepening:
expanded clinical rules, medication reconciliation, deterioration, finding history."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import drug_lab_interactions as dl  # noqa: E402
import renal_hepatic_dosing as rh  # noqa: E402
import condition_contraindications as cc  # noqa: E402
import medication_reconciliation as mr  # noqa: E402
import deterioration as det  # noqa: E402
import finding_history as fh  # noqa: E402


def _med(name, ing, date="2024-01-01", src="rx.pdf", **kw):
    m = {"name": name, "ingredients": ing, "date": date, "source_file": src}
    m.update(kw)
    return m


def _lab(t, v, u="mmol/L", flag="normal", date="2024-02-01"):
    return {"test_name": t, "value": v, "unit": u, "reference_range": None,
            "flag": flag, "confidence": 0.95, "date": date, "source_file": "lab.pdf"}


def _timeline(meds=None, labs=None, vitals=None, diagnoses=None):
    t = {"medications_timeline": meds or [], "lab_results_timeline": labs or [],
         "vital_signs_timeline": vitals or []}
    if diagnoses is not None:
        t["diagnoses_timeline"] = [{"name": d} for d in diagnoses]
    return t


# ---- expanded drug-lab ---------------------------------------------------- #

def test_low_platelets_plus_warfarin_is_high():
    tl = _timeline(meds=[_med("Warfarin", ["warfarin"])],
                   labs=[_lab("Platelets", "85", "10^9/L", "low")])
    f = dl.check_drug_lab_findings(tl)
    assert len(f) == 1
    assert f[0]["severity"] == "high"
    assert "platelet" in f[0]["explanation"].lower()


def test_low_hemoglobin_plus_nsaid():
    tl = _timeline(meds=[_med("Brufen", ["ibuprofen"])],
                   labs=[_lab("Hemoglobin", "8.5", "g/dL", "low")])
    f = dl.check_drug_lab_findings(tl)
    assert len(f) == 1 and "haemoglobin" in f[0]["explanation"].lower()


def test_lithium_plus_low_sodium():
    tl = _timeline(meds=[_med("Lithium", ["lithium"])],
                   labs=[_lab("Sodium", "128", "mmol/L", "low")])
    f = dl.check_drug_lab_findings(tl)
    assert any("lithium" in x["explanation"].lower() for x in f)
    assert f[0]["severity"] == "high"


def test_digoxin_plus_low_magnesium():
    tl = _timeline(meds=[_med("Digoxin", ["digoxin"])],
                   labs=[_lab("Magnesium", "0.6", "mmol/L", "low")])
    f = dl.check_drug_lab_findings(tl)
    assert len(f) == 1 and "magnesium" in f[0]["explanation"].lower()


# ---- expanded renal/hepatic ---------------------------------------------- #

def test_nitrofurantoin_plus_low_egfr():
    tl = _timeline(meds=[_med("Macrobid", ["nitrofurantoin"])],
                   labs=[_lab("eGFR", "28", "mL/min", "low")])
    f = rh.check_renal_hepatic_findings(tl)
    assert len(f) == 1 and f[0]["organ"] == "renal"
    assert "nitrofurantoin" in f[0]["explanation"].lower()


def test_fluconazole_plus_high_alt_hepatic():
    tl = _timeline(meds=[_med("Diflucan", ["fluconazole"])],
                   labs=[_lab("ALT", "130", "U/L", "high")])
    f = rh.check_renal_hepatic_findings(tl)
    assert len(f) == 1 and f[0]["organ"] == "hepatic"


# ---- expanded conditions -------------------------------------------------- #

def test_gout_plus_thiazide():
    f = cc.check_condition_contraindications(_timeline(
        meds=[_med("Hydrot", ["hydrochlorothiazide"])], diagnoses=["Gout"]))
    assert len(f) == 1 and f[0]["condition"] == "gout"


def test_epilepsy_plus_bupropion():
    f = cc.check_condition_contraindications(_timeline(
        meds=[_med("Wellbutrin", ["bupropion"])], diagnoses=["Epilepsy"]))
    assert len(f) == 1 and f[0]["condition"] == "epilepsy"


def test_heart_failure_plus_pioglitazone_is_high():
    f = cc.check_condition_contraindications(_timeline(
        meds=[_med("Actos", ["pioglitazone"])], diagnoses=["Heart failure"]))
    assert len(f) == 1 and f[0]["severity"] == "high"


def test_dementia_plus_anticholinergic():
    f = cc.check_condition_contraindications(_timeline(
        meds=[_med("Ditropan", ["oxybutynin"])], diagnoses=["Dementia"]))
    assert len(f) == 1 and f[0]["condition"] == "dementia"


# ---- medication reconciliation ------------------------------------------- #

def test_reconciliation_classifies_active_discontinued_duplicate():
    tl = _timeline(meds=[
        _med("Metformin", ["metformin"], date="2024-06-01", duration="90 days"),
        _med("Metformin", ["metformin"], date="2024-06-01", dosage="1000 mg", duration="90 days"),  # duplicate, dose conflict
        _med("Old Drug", ["terfenadine"], date="2019-01-01", duration="30 days"),  # discontinued
    ])
    out = mr.reconcile_medications(tl, reference_date="2024-07-01")
    states = {r["ingredient"]: r["state"] for r in out["reconciled_medications"]}
    assert states.get("metformin") == "dose_conflict"  # two active, diff doses
    assert states.get("terfenadine") == "discontinued"
    assert out["summary"]["dose_conflicts"] == 1


def test_reconciliation_no_conflict_when_single_active():
    tl = _timeline(meds=[_med("Lisinopril", ["lisinopril"], date="2024-06-01", duration="90 days")])
    out = mr.reconcile_medications(tl, reference_date="2024-07-01")
    assert out["reconciled_medications"][0]["state"] == "active"
    assert out["summary"]["dose_conflicts"] == 0


# ---- deterioration -------------------------------------------------------- #

def _vital(name, value, measured_at, unit=""):
    return {"name": name, "value": str(value), "unit": unit, "measured_at": measured_at}


def test_deterioration_flags_worsening_trajectory():
    tl = _timeline(vitals=[
        _vital("Respiratory rate", "14", "2024-01-10"),
        _vital("Heart rate", "70", "2024-01-10"),
        _vital("Respiratory rate", "26", "2024-02-10"),  # 3 pts
        _vital("Heart rate", "135", "2024-02-10"),       # 3 pts
    ])
    out = det.deterioration_trajectory(tl)
    assert out["point_count"] == 2
    assert out["latest_score"] >= 6
    assert out["trend"] == "worsening"
    assert out["deteriorating"] is True


def test_deterioration_stable_when_flat():
    tl = _timeline(vitals=[
        _vital("Heart rate", "72", "2024-01-10"),
        _vital("Heart rate", "74", "2024-02-10"),
    ])
    out = det.deterioration_trajectory(tl)
    assert out["trend"] in ("stable", "improving")
    assert out["deteriorating"] is False


def test_deterioration_single_point_fallback():
    out = det.deterioration_trajectory(_timeline())
    assert out["point_count"] == 0
    assert out["latest_score"] == 0


# ---- finding history ------------------------------------------------------ #

def _report(findings):
    return {"drug_lab_findings": findings}


def test_finding_history_diff_and_change_log():
    fh.reset("u")
    f1 = {"finding_kind": "drug_lab", "rule": "ace + high_k", "medications_involved": ["Lisinopril"]}
    f2 = {"finding_kind": "drug_lab", "rule": "digoxin + low_k", "medications_involved": ["Digoxin"]}

    snap1 = fh.snapshot_findings("u", _report([f1]))
    assert snap1["diff_vs_previous"]["is_initial"] is True
    assert len(snap1["diff_vs_previous"]["new"]) == 1

    snap2 = fh.snapshot_findings("u", _report([f2]))  # f1 resolved, f2 new
    d = snap2["diff_vs_previous"]
    assert d["new"] and "digoxin" in " ".join(d["new"]).lower() or len(d["new"]) == 1
    assert len(d["resolved"]) == 1
    assert len(d["persisted"]) == 0

    snap3 = fh.snapshot_findings("u", _report([f1, f2]))  # f1 recurred
    log = fh.finding_change_log("u")
    recurred = [x for x in log["findings"] if x["absent_then_recurred"]]
    assert recurred, "expected f1 to be flagged as recurred"
    assert log["snapshots"] == 3


def test_finding_history_isolated_per_user():
    fh.reset("a")
    fh.reset("b")
    f = {"finding_kind": "ddi", "rule": "r", "medications_involved": ["X"]}
    fh.snapshot_findings("a", _report([f]))
    assert len(fh.finding_history("a")) == 1
    assert len(fh.finding_history("b")) == 0
