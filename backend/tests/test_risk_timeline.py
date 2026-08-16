"""Offline tests for the risk timeline + evidence grading of findings in time.

Covers: duration parsing, record-level day-first inference, treatment
windows, overlap verdicts (concurrent / possible / not_concurrent /
unknown), finding annotation, double-dosing exposure arithmetic, and the
chronological risk calendar. All deterministic — no model call.
"""
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import risk_timeline  # noqa: E402
from risk_timeline import (  # noqa: E402
    ASSUMED_COURSE_DAYS,
    CONCURRENT,
    NOT_CONCURRENT,
    POSSIBLE,
    UNKNOWN,
    annotate_findings_with_timing,
    build_treatment_windows,
    concurrent_exposure,
    infer_dayfirst,
    overlap_of,
    parse_date,
    parse_duration_days,
    risk_calendar,
)


def _med(name, ingredient, d, duration, value=None, unit=None, per_day=None, group=None):
    return {"name": name, "ingredients": [ingredient], "date": d,
            "duration": duration, "dosage_value": value, "dosage_unit": unit,
            "frequency_per_day": per_day, "source_file": f"{name}.png",
            "prescription_group": group}


def _timeline():
    return {"medications_timeline": [
        _med("Paracetamol", "Paracetamol", "09/11/2025", "14 days", 1000, "mg", 3, "rx-0"),
        _med("Diclofenac sodium", "Diclofenac", "09/11/2025", "14 days", None, None, 2, "rx-0"),
        _med("Fluconazole", "Fluconazole", "27/03/2025", "4 weeks", 150, "mg", 0.14, "rx-1"),
        _med("Cetirizine", "Cetirizine", "26/02/2026", "14 days", 10, "mg", 1, "rx-2"),
        _med("Montelukast", "Montelukast", "26/02/2026", "14 days", 10, "mg", 1, "rx-2"),
        _med("Chlorpheniramine", "Chlorpheniramine", "14/10/2023", "5 days", 4, "mg", 1, "rx-3"),
    ]}


def _report():
    return {
        "potential_drug_interactions": [
            {"medications_involved": ["Paracetamol", "Diclofenac"],
             "explanation": "Additive GI/renal risk.", "severity": "moderate",
             "confidence": 0.6},
            {"medications_involved": ["Fluconazole", "Montelukast"],
             "explanation": "CYP inhibition.", "severity": "moderate", "confidence": 0.6},
            {"medications_involved": ["Cetirizine", "Chlorpheniramine"],
             "explanation": "Additive sedation.", "severity": "moderate", "confidence": 0.6},
            {"medications_involved": ["Cetirizine", "Montelukast"],
             "explanation": "Prescribed together.", "severity": "low", "confidence": 0.5},
        ],
        "duplicate_prescriptions": [],
        "conflicting_dosage_instructions": [],
        "allergy_conflicts": [],
    }


# ---------------------------------------------------------------------------
# Primitives
# ---------------------------------------------------------------------------

def test_duration_parsing():
    assert parse_duration_days("14 days") == 14
    assert parse_duration_days("4 weeks") == 28
    assert parse_duration_days("1 month") == 30
    assert parse_duration_days("As required") is None
    assert parse_duration_days("") is None
    assert parse_duration_days(None) is None


def test_dayfirst_inferred_from_the_record():
    # "14/10/2023" can only be day-first, which settles "09/11/2025".
    assert infer_dayfirst(["09/11/2025", "14/10/2023"]) is True
    assert infer_dayfirst(["03/11/2025", "10/14/2023"]) is False
    assert parse_date("09/11/2025", dayfirst=True) == date(2025, 11, 9)
    # ISO dates are never dayfirst-mangled.
    assert parse_date("2025-11-09") == date(2025, 11, 9)
    assert parse_date("not a date") is None


def test_treatment_windows_open_vs_closed():
    windows = build_treatment_windows(_timeline())
    by_name = {w["name"]: w for w in windows}
    para = by_name["Paracetamol"]
    assert para["start"] == date(2025, 11, 9)
    assert para["end"] == date(2025, 11, 23)
    assert para["duration_known"] is True
    assert para["daily_dose"] == 3000.0


# ---------------------------------------------------------------------------
# Overlap verdicts
# ---------------------------------------------------------------------------

def test_concurrent_courses_are_live_risks():
    report = _report()
    annotate_findings_with_timing(report, _timeline())
    by_pair = {" + ".join(f["medications_involved"]): f["timing"]
               for f in report["potential_drug_interactions"]}

    timing = by_pair["Paracetamol + Diclofenac"]
    assert timing["status"] == CONCURRENT
    assert timing["window_start"] == "2025-11-09"
    assert timing["overlap_days"] == 15
    # Same prescription -> same window, also concurrent.
    assert by_pair["Cetirizine + Montelukast"]["status"] == CONCURRENT


def test_never_concurrent_findings_marked_historical():
    report = _report()
    annotate_findings_with_timing(report, _timeline())
    by_pair = {" + ".join(f["medications_involved"]): f["timing"]
               for f in report["potential_drug_interactions"]}

    for pair, min_gap in (("Fluconazole + Montelukast", 300),
                          ("Cetirizine + Chlorpheniramine", 800)):
        timing = by_pair[pair]
        assert timing["status"] == NOT_CONCURRENT, (pair, timing)
        assert timing["gap_days"] > min_gap
        assert "never taken at the same time" in timing["note"]

    summary = report["timing_summary"]
    assert summary["concurrent"] == 2
    assert summary["not_concurrent"] == 2


def test_unknown_duration_is_possible_never_concurrent():
    open_ended = {"medications_timeline": [
        _med("DrugA", "druga", "01/01/2026", "As required", 10, "mg", 1, "g1"),
        _med("DrugB", "drugb", "05/01/2026", "14 days", 10, "mg", 1, "g2"),
    ]}
    report = {"potential_drug_interactions": [
        {"medications_involved": ["DrugA", "DrugB"], "explanation": "x",
         "severity": "low", "confidence": 0.5}]}
    annotate_findings_with_timing(report, open_ended)
    assert report["potential_drug_interactions"][0]["timing"]["status"] == POSSIBLE


def test_undatable_is_unknown():
    no_dates = {"medications_timeline": [
        _med("DrugA", "druga", None, None, 10, "mg", 1, "g1"),
        _med("DrugB", "drugb", None, None, 10, "mg", 1, "g2"),
    ]}
    report = {"potential_drug_interactions": [
        {"medications_involved": ["DrugA", "DrugB"], "explanation": "x",
         "severity": "low", "confidence": 0.5}]}
    annotate_findings_with_timing(report, no_dates)
    assert report["potential_drug_interactions"][0]["timing"]["status"] == UNKNOWN


# ---------------------------------------------------------------------------
# Concurrent double-dosing exposure
# ---------------------------------------------------------------------------

def test_concurrent_exposure_arithmetic():
    doubled = {"medications_timeline": [
        _med("Panadol", "Paracetamol", "09/11/2025", "14 days", 1000, "mg", 3, "rx-A"),
        _med("Calpol", "Paracetamol", "12/11/2025", "10 days", 500, "mg", 4, "rx-B"),
        # Same prescription uploaded twice must NOT count as a second course.
        _med("Panadol", "Paracetamol", "09/11/2025", "14 days", 1000, "mg", 3, "rx-A"),
    ]}
    exposures = concurrent_exposure(doubled)
    assert len(exposures) == 2
    assert all(e["ingredient"] == "paracetamol" for e in exposures)
    top = exposures[0]
    assert top["cumulative_daily_dose"] == 5000.0
    assert top["window_start"] == "2025-11-12"
    assert "for a pharmacist or doctor to judge" in top["note"]


def test_single_course_no_exposure():
    single = {"medications_timeline": [
        _med("Panadol", "Paracetamol", "09/11/2025", "14 days", 1000, "mg", 3, "rx-A")]}
    assert concurrent_exposure(single) == []


# ---------------------------------------------------------------------------
# Calendar
# ---------------------------------------------------------------------------

def test_risk_calendar_most_recent_first_with_historical_bucket():
    report = _report()
    calendar = risk_calendar(report, _timeline())
    assert calendar[0]["window_start"] == "2026-02-26", calendar[0]
    assert calendar[0]["label"] == "2026-02-26 to 2026-03-12"
    assert calendar[-1]["label"] == "Not concurrent, or dates unreadable"
    # Every finding appears exactly once somewhere in the calendar.
    total = sum(len(p["risks"]) for p in calendar)
    assert total == len(report["potential_drug_interactions"])


def test_overlap_of_disjoint_windows_reports_gap():
    a = {"start": date(2025, 1, 1), "end": date(2025, 1, 10), "duration_known": True}
    b = {"start": date(2025, 3, 1), "end": date(2025, 3, 5), "duration_known": True}
    result = overlap_of(a, b)
    assert result["status"] == NOT_CONCURRENT
    assert result["gap_days"] == 50


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"\n{len(fns)} tests passed")
