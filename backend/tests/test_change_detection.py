"""Offline tests for deterministic, conservative record change detection."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from change_detection import detect_record_changes


def _visit(date, file, *, medications=None, labs=None, allergies=None):
    return {
        "date": date,
        "_source": {"file": file},
        "medications": medications or [],
        "lab_results": labs or [],
        "allergies_noted": allergies or [],
    }


def _med(name, dosage, frequency="once daily", ingredients=None):
    return {
        "name": name,
        "ingredients": ingredients or [name],
        "dosage": dosage,
        "frequency": frequency,
        "duration": None,
    }


def _lab(name, value, flag="normal", unit="mg/dL"):
    return {"test_name": name, "value": value, "flag": flag, "unit": unit}


def test_detects_flag_instruction_and_allergy_changes_with_sources():
    timeline = {
        "visits": [
            _visit(
                "2025-01-10", "old.pdf",
                medications=[_med("Metformin", "500 mg")],
                labs=[_lab("Glucose", "95")],
            ),
            _visit(
                "2025-04-10", "new.pdf",
                medications=[_med("Metformin", "1000 mg")],
                labs=[_lab("Glucose", "132", "high")],
                allergies=["Penicillin"],
            ),
        ]
    }
    report = detect_record_changes(timeline)
    assert report["summary"] == {
        "dated_records": 2,
        "comparisons": 1,
        "changes_found": 3,
        "attention_items": 3,
    }
    kinds = {(item["category"], item["kind"]) for item in report["latest"]["changes"]}
    assert kinds == {
        ("lab", "status_changed"),
        ("medication", "instruction_changed"),
        ("allergy", "newly_documented"),
    }
    assert report["latest"]["changes"][0]["evidence"] == [
        {"date": "2025-01-10", "source_file": "old.pdf", "document_url": None},
        {"date": "2025-04-10", "source_file": "new.pdf", "document_url": None},
    ]


def test_does_not_call_missing_medication_stopped_or_compare_to_lab_only_record():
    timeline = {
        "visits": [
            _visit("2025-01-10", "rx.pdf", medications=[_med("Aspirin", "75 mg")]),
            _visit("2025-02-10", "lab.pdf", labs=[_lab("LDL", "110")]),
        ]
    }
    report = detect_record_changes(timeline)
    assert report["latest"]["changes"] == []
    assert "omitted medicine is never treated as stopped" in report["note"]


def test_matches_medication_by_normalized_ingredient_and_ignores_case():
    timeline = {
        "visits": [
            _visit("10 Jan 2025", "a.pdf", medications=[_med("Brand A", "5 mg", ingredients=["AMLODIPINE"])]),
            _visit("11 Feb 2025", "b.pdf", medications=[_med("Brand B", "10 mg", ingredients=["amlodipine"])]),
        ]
    }
    changes = detect_record_changes(timeline)["latest"]["changes"]
    assert len(changes) == 1
    assert changes[0]["kind"] == "instruction_changed"


def test_orders_comparisons_newest_first_and_skips_undated_records():
    timeline = {
        "visits": [
            _visit(None, "unknown.pdf", labs=[_lab("Glucose", "1")]),
            _visit("2025-01-01", "one.pdf", labs=[_lab("Glucose", "90")]),
            _visit("2025-02-01", "two.pdf", labs=[_lab("Glucose", "95")]),
            _visit("2025-03-01", "three.pdf", labs=[_lab("Glucose", "100")]),
        ]
    }
    report = detect_record_changes(timeline)
    assert report["summary"]["dated_records"] == 3
    assert [item["to_date"] for item in report["comparisons"]] == ["2025-03-01", "2025-02-01"]


def test_does_not_calculate_delta_across_different_units():
    timeline = {
        "visits": [
            _visit("2025-01-01", "one.pdf", labs=[_lab("Glucose", "90", unit="mg/dL")]),
            _visit("2025-02-01", "two.pdf", labs=[_lab("Glucose", "5", unit="mmol/L")]),
        ]
    }
    assert detect_record_changes(timeline)["latest"]["changes"] == []


def test_single_record_has_no_comparison():
    report = detect_record_changes({"visits": [_visit("2025-01-01", "only.pdf")]})
    assert report["latest"] is None
    assert report["comparisons"] == []


if __name__ == "__main__":
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_")]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"\n{len(tests)} tests passed")
