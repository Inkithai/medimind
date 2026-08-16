"""Offline tests for source-grounded appointment preparation."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from appointment_prep import build_appointment_prep


def _visit(date, file, *, meds=None, labs=None, allergies=None, doctor=None):
    return {
        "date": date,
        "provider_or_doctor": doctor,
        "_source": {"file": file},
        "document_url": f"https://records.test/{file}",
        "medications": meds or [],
        "lab_results": labs or [],
        "allergies_noted": allergies or [],
    }


def _med(name, dosage="10 mg"):
    return {"name": name, "ingredients": [name], "dosage": dosage, "frequency": "daily", "duration": None}


def _timeline():
    visits = [
        _visit("2025-01-01", "old.pdf", meds=[_med("Medicine A", "5 mg")], doctor="Dr One"),
        _visit("2025-03-01", "new.pdf", meds=[_med("Medicine A", "10 mg"), _med("Medicine B")], allergies=["Penicillin"], doctor="Dr Two"),
    ]
    return {
        "visits": visits,
        "known_allergies": ["Penicillin"],
        "medications_timeline": [],
        "lab_results_timeline": [],
    }


def test_builds_prioritized_questions_and_latest_medication_handoff():
    cross_check = {
        "allergy_conflicts": [{"medication": "Medicine B", "allergy": "Penicillin", "explanation": "Potential conflict"}],
        "potential_drug_interactions": [{
            "medications_involved": ["Medicine A", "Medicine B"],
            "severity": "high",
            "explanation": "May interact",
        }],
        "conflicting_dosage_instructions": [],
        "duplicate_prescriptions": [],
    }
    report = build_appointment_prep(_timeline(), cross_check, {"trends": []})
    assert report["priorities"][0]["level"] == "important"
    assert any("safe" in item["question"].lower() for item in report["priorities"])
    assert report["handoff"]["latest_medication_record"]["source_file"] == "new.pdf"
    assert [item["name"] for item in report["handoff"]["latest_documented_medications"]] == ["Medicine A", "Medicine B"]
    assert report["handoff"]["providers_documented"] == ["Dr One", "Dr Two"]
    assert all(item["evidence"] for item in report["priorities"][:2])


def test_lab_crossing_creates_cited_question():
    trends = {"trends": [{
        "test_name": "Glucose",
        "direction": "increasing",
        "approaching_threshold": False,
        "crossed_into_abnormal_at": {"date": "2025-03-01", "flag": "high"},
        "explanation": "Glucose rose across two tests.",
        "data_points": [
            {"date": "2025-01-01", "source_file": "old.pdf", "value": "90", "flag": "normal"},
            {"date": "2025-03-01", "source_file": "new.pdf", "value": "130", "flag": "high"},
        ],
    }]}
    report = build_appointment_prep(_timeline(), {}, trends)
    item = next(item for item in report["priorities"] if item["category"] == "Lab trend")
    assert item["level"] == "important"
    assert "outside" in item["question"]
    assert [e["source_file"] for e in item["evidence"]] == ["old.pdf", "new.pdf"]


def test_no_findings_produces_safe_record_review_fallback():
    timeline = {
        "visits": [_visit("2025-01-01", "only.pdf")],
        "known_allergies": [],
        "medications_timeline": [],
        "lab_results_timeline": [],
    }
    report = build_appointment_prep(timeline, {}, {"trends": []})
    assert len(report["priorities"]) == 1
    assert report["priorities"][0]["id"] == "record-review"
    assert report["priorities"][0]["level"] == "routine"


def test_does_not_label_latest_medication_record_as_current_list():
    report = build_appointment_prep(_timeline(), {}, {"trends": []})
    assert "latest medication-containing record" in report["note"]
    assert "may not represent everything currently taken" in report["note"]


if __name__ == "__main__":
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_")]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"\n{len(tests)} tests passed")
