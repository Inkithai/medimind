"""Offline tests for the deterministic recall check and its pipeline wiring.

Covers the check itself plus the three consumers every finding flows through:
alert management (override / near-duplicate collapse), consult triage (routes
to a pharmacist, US-market caveat), and the follow-up action queue (a stable
recall-check task). All offline — the openFDA HTTP layer is never reached
(the check reads a pre-fetched references dict, exactly as the warmed cache
would supply).
"""

import os
import sys
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import recall_check  # noqa: E402
import alert_management  # noqa: E402
import consult_triage  # noqa: E402
import follow_up  # noqa: E402


def _recalls():
    return [
        {
            "source": "FDA Enforcement Report (openFDA drug/enforcement)",
            "publisher": "test",
            "recall_number": "D-1234-2024",
            "classification": "Class I",
            "status": "Ongoing",
            "recall_initiation_date": "2024-01-05",
            "reason_for_recall": "Microbial contamination.",
            "product_description": "Losartan tablets",
            "ongoing": True,
        },
        {
            "source": "FDA Enforcement Report (openFDA drug/enforcement)",
            "publisher": "test",
            "recall_number": "D-0001-2020",
            "classification": "Class III",
            "status": "Completed",
            "recall_initiation_date": "2020-02-02",
            "reason_for_recall": "Labeling.",
            "product_description": "Losartan tablets",
            "ongoing": False,
        },
    ]


def _timeline():
    return {
        "medications_timeline": [
            {"name": "Losartan", "ingredients": ["Losartan potassium"]},
            {"name": "Paracetamol", "ingredients": ["Paracetamol"]},
        ],
        "known_allergies": [],
    }


def test_check_recalls_one_finding_per_ingredient_with_count():
    findings = recall_check.check_recalls(_timeline(), references={"losartan": _recalls()})
    assert len(findings) == 1
    f = findings[0]
    assert f["ingredient"] == "losartan"
    assert f["finding_kind"] == "openfda_recall"
    assert f["severity"] == "high"  # Class I
    assert f["recall_count"] == 2
    assert f["reference"]["recall_number"] == "D-1234-2024"
    assert "pharmacist" in f["explanation"]
    assert "US" in f["explanation"]


def test_check_recalls_never_invents_a_negative():
    assert recall_check.check_recalls({"medications_timeline": []}) == []
    assert recall_check.check_recalls(_timeline(), references={}) == []
    assert recall_check.check_recalls(_timeline(), references={"paracetamol": []}) == []


def test_check_recalls_is_cache_only_by_default():
    """Without an explicit references dict the check must call the lookup with
    fetch_missing=False — it reads the warm cache, never the network."""
    with mock.patch(
        "openfda_reference.lookup_recall_references", return_value={}
    ) as lookup:
        assert recall_check.check_recalls(_timeline()) == []
        lookup.assert_called_once()
        assert lookup.call_args.kwargs.get("fetch_missing") is False


def test_merge_recall_findings_dedupes():
    findings = recall_check.check_recalls(_timeline(), references={"losartan": _recalls()})
    report = {}
    recall_check.merge_recall_findings(report, findings)
    recall_check.merge_recall_findings(report, findings)
    assert len(report[recall_check.LIST_KEY]) == 1


def test_alert_management_includes_recalls():
    assert "openfda_recalls" in alert_management.FINDING_LISTS
    report = {
        "openfda_recalls": recall_check.check_recalls(
            _timeline(), references={"losartan": _recalls()}
        )
    }
    managed = alert_management.manage_alerts(report, "user-1")
    assert managed["active_count"] == 1
    assert managed["active_findings"][0]["finding_kind"] == "openfda_recall"


def test_consult_triage_routes_recall_to_pharmacist():
    report = {
        "openfda_recalls": recall_check.check_recalls(
            _timeline(), references={"losartan": _recalls()}
        )
    }
    triage = consult_triage.generate_consult_triage(report, {}, {}, _timeline())
    recall_items = [i for i in triage["referral_items"] if i["trigger"] == "us_fda_recall"]
    assert len(recall_items) == 1
    item = recall_items[0]
    assert item["route"] == "pharmacist"
    assert item["urgency"] == "soon"  # Class I -> soon (no emergency urgency exists)
    assert item["reference"]["recall_number"] == "D-1234-2024"
    assert "US-market" in item["why_this_route"]
    assert triage["consult_type"] == "pharmacist"


def test_follow_up_plan_includes_recall_task():
    cross_check = {
        "openfda_recalls": recall_check.check_recalls(
            _timeline(), references={"losartan": _recalls()}
        )
    }
    plan = follow_up.build_follow_up_plan(_timeline(), cross_check, {"trends": []})
    recall_tasks = [t for t in plan["tasks"] if t["kind"] == "recall_check"]
    assert len(recall_tasks) == 1
    task = recall_tasks[0]
    assert task["category"] == "Medication safety"
    assert task["priority"] == "high"  # Class I
    assert "D-1234-2024" in task["action"]
    assert "US-market" in task["timing_guardrail"]


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"\n{len(fns)} tests passed")
