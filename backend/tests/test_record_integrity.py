"""Offline tests for conservative cross-document integrity checks."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from record_integrity import check_record_integrity


def _visit(date, file, *, patient="John A Doe", meds=None, labs=None, allergies=None, confidence=0.9):
    return {
        "date": date,
        "patient_name": patient,
        "medications": meds or [],
        "lab_results": labs or [],
        "allergies_noted": allergies or [],
        "overall_confidence": confidence,
        "_source": {"file": file},
        "document_url": f"https://records.test/{file}",
    }


def _med(name, dosage, frequency="daily", ingredients=None):
    return {"name": name, "ingredients": ingredients or [name], "dosage": dosage, "frequency": frequency}


def _lab(name, value, unit="mg/dL"):
    return {"test_name": name, "value": value, "unit": unit, "flag": "unknown"}


def test_detects_identity_mismatch_but_ignores_middle_name_variation():
    timeline = {"visits": [
        _visit("2025-01-01", "one.pdf", patient="Mr John A Doe"),
        _visit("2025-02-01", "two.pdf", patient="John Doe"),
        _visit("2025-03-01", "three.pdf", patient="Jane Roe"),
    ]}
    report = check_record_integrity(timeline)
    identity = [issue for issue in report["issues"] if issue["category"] == "identity"]
    assert len(identity) == 1
    assert len(identity[0]["variants"]) == 2
    assert identity[0]["severity"] == "important"


def test_detects_same_date_lab_discrepancy_across_date_formats():
    timeline = {"visits": [
        _visit("2025-01-10", "one.pdf", labs=[_lab("Glucose", "90")]),
        _visit("10 Jan 2025", "two.pdf", labs=[_lab("glucose", "130")]),
    ]}
    report = check_record_integrity(timeline)
    lab = next(issue for issue in report["issues"] if issue["category"] == "lab")
    assert "differ" in lab["title"]
    assert {variant["value"] for variant in lab["variants"]} == {"90 mg/dL", "130 mg/dL"}
    assert all(variant["evidence"] for variant in lab["variants"])


def test_unit_difference_is_for_verification_not_automatic_conversion():
    timeline = {"visits": [
        _visit("2025-01-10", "one.pdf", labs=[_lab("Glucose", "90", "mg/dL")]),
        _visit("2025-01-10", "two.pdf", labs=[_lab("Glucose", "5", "mmol/L")]),
    ]}
    issue = check_record_integrity(timeline)["issues"][0]
    assert "unit conversion" in issue["explanation"]
    assert issue["severity"] == "review"


def test_detects_complete_same_date_medication_instruction_conflict():
    timeline = {"visits": [
        _visit("2025-01-10", "one.pdf", meds=[_med("Brand A", "5 mg", ingredients=["Amlodipine"])]),
        _visit("2025-01-10", "two.pdf", meds=[_med("Brand B", "10 mg", ingredients=["amlodipine"])]),
    ]}
    report = check_record_integrity(timeline)
    issue = next(issue for issue in report["issues"] if issue["category"] == "medication")
    assert issue["severity"] == "important"
    assert len(issue["variants"]) == 2


def test_missing_medication_instruction_is_not_called_a_conflict():
    timeline = {"visits": [
        _visit("2025-01-10", "one.pdf", meds=[_med("Amlodipine", "5 mg")]),
        _visit("2025-01-10", "two.pdf", meds=[_med("Amlodipine", "", frequency="")]),
    ]}
    assert check_record_integrity(timeline)["issues"] == []


def test_detects_no_known_allergies_against_named_allergy():
    timeline = {"visits": [
        _visit("2025-01-10", "one.pdf", allergies=["NKDA"]),
        _visit("2025-02-10", "two.pdf", allergies=["Penicillin"]),
    ]}
    issue = next(issue for issue in check_record_integrity(timeline)["issues"] if issue["category"] == "allergy")
    assert issue["severity"] == "important"
    assert "do not remove" in issue["suggested_action"]


def test_clean_record_reports_no_discrepancies():
    timeline = {"visits": [
        _visit("2025-01-10", "one.pdf", labs=[_lab("Glucose", "90")]),
        _visit("2025-02-10", "two.pdf", labs=[_lab("Glucose", "95")]),
    ]}
    report = check_record_integrity(timeline)
    assert report["status"] == "no_discrepancies_found"
    assert report["summary"]["issues_found"] == 0


if __name__ == "__main__":
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_")]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"\n{len(tests)} tests passed")
