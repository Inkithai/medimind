"""Offline tests for grounded follow-up action planning."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from follow_up import build_follow_up_plan


def _visit(date, file, *, patient="John Doe", meds=None, labs=None, allergies=None):
    return {
        "date": date,
        "patient_name": patient,
        "provider_or_doctor": None,
        "medications": meds or [],
        "lab_results": labs or [],
        "allergies_noted": allergies or [],
        "overall_confidence": 0.9,
        "_source": {"file": file},
        "document_url": f"https://records.test/{file}",
    }


def _timeline():
    visits = [
        _visit(
            "2025-01-01",
            "one.pdf",
            meds=[{"name": "A", "ingredients": ["A"], "dosage": "5 mg", "frequency": "daily"}],
        ),
        _visit(
            "2025-02-01",
            "two.pdf",
            meds=[{"name": "A", "ingredients": ["A"], "dosage": "10 mg", "frequency": "daily"}],
        ),
    ]
    return {
        "visits": visits,
        "known_allergies": [],
        "medications_timeline": [],
        "lab_results_timeline": [],
    }


def test_builds_stable_high_priority_medication_task():
    cross_check = {
        "allergy_conflicts": [],
        "potential_drug_interactions": [
            {
                "medications_involved": ["A", "B"],
                "severity": "high",
                "explanation": "Potential interaction",
            }
        ],
        "conflicting_dosage_instructions": [],
        "duplicate_prescriptions": [],
    }
    first = build_follow_up_plan(_timeline(), cross_check, {"trends": []})
    second = build_follow_up_plan(_timeline(), cross_check, {"trends": []})
    task = next(task for task in first["tasks"] if task["category"] == "Medication safety")
    assert task["priority"] == "high"
    assert "before changing" in task["timing_guardrail"]
    assert (
        task["id"] == next(task for task in second["tasks"] if task["title"] == task["title"])["id"]
    )


def test_includes_record_integrity_verification_with_both_sources():
    timeline = {
        "visits": [
            _visit("2025-01-01", "john.pdf", patient="John Doe"),
            _visit("2025-02-01", "jane.pdf", patient="Jane Roe"),
        ],
        "known_allergies": [],
        "medications_timeline": [],
        "lab_results_timeline": [],
    }
    report = build_follow_up_plan(timeline, {}, {"trends": []})
    task = next(task for task in report["tasks"] if task["kind"] == "record_verification")
    assert task["priority"] == "high"
    assert {item["source_file"] for item in task["evidence"]} == {"john.pdf", "jane.pdf"}
    assert report["summary"]["record_verification"] == 1


def test_lab_task_does_not_invent_a_retest_deadline():
    trends = {
        "trends": [
            {
                "test_name": "Glucose",
                "direction": "increasing",
                "approaching_threshold": False,
                "crossed_into_abnormal_at": {"date": "2025-02-01", "flag": "high"},
                "explanation": "Glucose rose.",
                "data_points": [
                    {
                        "date": "2025-01-01",
                        "source_file": "one.pdf",
                        "value": "90",
                        "flag": "normal",
                    },
                    {
                        "date": "2025-02-01",
                        "source_file": "two.pdf",
                        "value": "130",
                        "flag": "high",
                    },
                ],
            }
        ]
    }
    report = build_follow_up_plan(_timeline(), {}, trends)
    task = next(task for task in report["tasks"] if task["category"] == "Lab trend")
    assert "does not infer a retest interval" in task["timing_guardrail"]
    assert "due_date" not in task


def test_empty_findings_produce_routine_record_review():
    timeline = {
        "visits": [_visit("2025-01-01", "one.pdf")],
        "known_allergies": [],
        "medications_timeline": [],
        "lab_results_timeline": [],
    }
    report = build_follow_up_plan(timeline, {}, {"trends": []})
    assert report["summary"]["total"] == 1
    assert report["tasks"][0]["priority"] == "low"
    assert "not medical urgency" in report["note"]


if __name__ == "__main__":
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_")]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"\n{len(tests)} tests passed")
