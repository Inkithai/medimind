"""Offline tests for medication activity classification (active/inactive windows)."""

import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from medication_activity import (  # noqa: E402
    analyze_medication_activity,
    filter_active_timeline,
)

TODAY = date.today().isoformat()


def _timeline(meds):
    return {"medications_timeline": meds, "known_allergies": []}


def _med(name, ingredients, d=None, duration=None):
    med = {"name": name, "ingredients": ingredients, "source_file": "rx.pdf"}
    if d:
        med["date"] = d
    if duration:
        med["duration"] = duration
    return med


def _past(days_ago):
    return (date.today() - timedelta(days=days_ago)).isoformat()


def _future(days_ahead):
    return (date.today() + timedelta(days=days_ahead)).isoformat()


def test_expired_course_is_inactive():
    timeline = _timeline([
        _med("Amoxicillin 500mg", ["amoxicillin"], d=_past(400), duration="7 days"),
    ])
    activity = analyze_medication_activity(timeline)
    assert activity["active_count"] == 0
    assert activity["inactive_count"] == 1
    assert activity["inactive_medications"][0]["medication"] == "Amoxicillin 500mg"
    assert "course ended" in activity["inactive_medications"][0]["reason"]
    assert activity["reference_date"] == TODAY


def test_open_ended_course_stays_active():
    # No stated duration -> no provable finish -> active, however old.
    timeline = _timeline([
        _med("Warfarin 5mg", ["warfarin"], d=_past(800)),
    ])
    activity = analyze_medication_activity(timeline)
    assert activity["active_count"] == 1
    assert activity["inactive_count"] == 0


def test_prn_course_stays_active():
    timeline = _timeline([
        _med("Paracetamol", ["paracetamol"], d=_past(300), duration="as required"),
    ])
    activity = analyze_medication_activity(timeline)
    assert activity["active_count"] == 1


def test_undated_entry_stays_active():
    timeline = _timeline([
        _med("Metformin", ["metformin"]),
    ])
    activity = analyze_medication_activity(timeline)
    assert activity["active_count"] == 1


def test_course_still_running_is_active():
    # Started 10 days ago for 30 days -> still running today.
    timeline = _timeline([
        _med("Amoxicillin", ["amoxicillin"], d=_past(10), duration="30 days"),
    ])
    activity = analyze_medication_activity(timeline)
    assert activity["active_count"] == 1


def test_future_dated_course_is_active():
    # Demo/test records sometimes carry future dates; with no provable end
    # they stay active rather than being dropped.
    timeline = _timeline([
        _med("Paracetamol", ["paracetamol"], d=_future(20), duration="5 days"),
    ])
    activity = analyze_medication_activity(timeline)
    assert activity["active_count"] == 1


def test_explicit_reference_date_controls_classification():
    # Course of 5 days ending 2024-01-06: inactive on 2024-03-01,
    # active on 2024-01-03 (window still reaches the reference date).
    timeline = _timeline([
        _med("Amoxicillin", ["amoxicillin"], d="2024-01-01", duration="5 days"),
    ])
    inactive = analyze_medication_activity(timeline, reference_date="2024-03-01")
    assert inactive["inactive_count"] == 1
    active = analyze_medication_activity(timeline, reference_date="2024-01-03")
    assert active["active_count"] == 1


def test_filter_active_timeline_drops_only_expired_entries():
    timeline = _timeline([
        _med("Warfarin", ["warfarin"], d=_past(60)),                       # open-ended -> active
        _med("OldCourse", ["amoxicillin"], d=_past(400), duration="7 days"),  # expired
    ])
    filtered = filter_active_timeline(timeline)
    names = [m["name"] for m in filtered["medications_timeline"]]
    assert names == ["Warfarin"]
    # other sections pass through untouched
    assert filtered["known_allergies"] == []


def test_empty_timeline_yields_empty_activity():
    activity = analyze_medication_activity(_timeline([]))
    assert activity["active_count"] == 0
    assert activity["inactive_count"] == 0
    assert activity["reference_date"] == TODAY


# ---------------------------------------------------------------------------
# Cross-check integration: activity scoping end to end
# ---------------------------------------------------------------------------

def _llm_json():
    return (
        '{"potential_drug_interactions": [], "duplicate_prescriptions": [], '
        '"conflicting_dosage_instructions": [], "allergy_conflicts": [], '
        '"overall_recommendation": "Consult a professional."}'
    )


def test_cross_check_skips_llm_when_no_active_prescriptions(monkeypatch):
    """All courses provably ended -> no live exposure -> no LLM call at all."""
    os.environ.setdefault("GROQ_API_KEY", "gsk_test_123")
    import medical_extractor

    called = []

    def fake_completion(**kwargs):
        called.append(kwargs)
        return _llm_json()

    monkeypatch.setattr(medical_extractor, "_completion_resilient", fake_completion)
    timeline = _timeline([
        _med("OldCourse", ["amoxicillin"], d=_past(400), duration="7 days"),
    ])
    report = medical_extractor.cross_check_prescriptions(timeline)
    assert called == []
    assert "No currently active prescriptions" in report["overall_recommendation"]
    assert report["medication_activity"]["inactive_count"] == 1
    assert report["reference_date"] == TODAY


def test_cross_check_scopes_llm_payload_and_kb_to_active_prescriptions(monkeypatch):
    """An expired course is excluded from the LLM payload and the
    deterministic interaction KB: warfarin (open-ended) + expired ibuprofen
    must NOT produce a warfarin+NSAID interaction finding."""
    os.environ.setdefault("GROQ_API_KEY", "gsk_test_123")
    import medical_extractor

    captured = {}

    def fake_completion(**kwargs):
        captured["user_content"] = kwargs["user_content"]
        return _llm_json()

    monkeypatch.setattr(medical_extractor, "_completion_resilient", fake_completion)
    timeline = _timeline([
        _med("Warfarin 5mg", ["warfarin"], d=_past(60)),                     # active
        _med("Brufen", ["ibuprofen"], d=_past(400), duration="5 days"),      # expired
    ])
    report = medical_extractor.cross_check_prescriptions(timeline)
    assert report["potential_drug_interactions"] == []
    assert report["medication_activity"]["active_medications"] == ["Warfarin 5mg"]
    assert report["medication_activity"]["inactive_count"] == 1
    import json as _json

    payload = _json.loads(captured["user_content"].split("\n\n", 1)[1])
    active_names = [m["name"] for m in payload["medications_timeline"]]
    assert active_names == ["Warfarin 5mg"]
    excluded_names = [e["medication"] for e in payload["excluded_inactive_medications"]]
    assert excluded_names == ["Brufen"]
