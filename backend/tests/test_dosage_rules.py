"""Offline tests for deterministic dosage validation."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dosage_rules import check_dosages  # noqa: E402


def _med(name, ingredients, dosage_value, dosage_unit, frequency=None, as_needed=False):
    return {
        "name": name, "ingredients": ingredients,
        "dosage_value": dosage_value, "dosage_unit": dosage_unit,
        "frequency_per_day": frequency, "is_as_needed": as_needed,
        "date": "2024-01-01", "source_file": "rx.pdf",
    }


def _timeline(meds):
    return {"medications_timeline": meds}


def _kinds(report):
    return [f["kind"] for f in report["findings"]]


def test_normal_dose_produces_no_findings():
    report = check_dosages(_timeline([_med("Paracetamol", ["paracetamol"], 500, "mg", 3)]))
    assert report["findings"] == []
    assert report["skipped"] == []


def test_single_dose_above_ceiling_is_flagged():
    report = check_dosages(_timeline([_med("Paracetamol", ["paracetamol"], 1500, "mg", 3)]))
    assert "above_max_single_dose" in _kinds(report)


def test_daily_total_above_ceiling_is_flagged():
    # 1000 mg x 5/day = 5000 mg > 4000 mg/day ceiling (single dose OK).
    report = check_dosages(_timeline([_med("Paracetamol", ["paracetamol"], 1000, "mg", 5)]))
    kinds = _kinds(report)
    assert "above_max_daily_dose" in kinds
    assert "above_max_frequency" in kinds  # 5 > 4/day too
    assert "above_max_single_dose" not in kinds


def test_gram_doses_are_converted_to_mg():
    # "1 g" normalized as value=1 unit=g -> 1000 mg, within single limit;
    # 1 g x 5/day = 5000 mg -> above daily.
    report = check_dosages(_timeline([_med("Paracetamol", ["paracetamol"], 1, "g", 5)]))
    assert "above_max_daily_dose" in _kinds(report)


def test_prn_medication_not_checked_against_daily_ceiling():
    # As-needed: no frequency -> no daily total; single-dose limit still applies.
    ok = check_dosages(_timeline([_med("Ibuprofen", ["ibuprofen"], 400, "mg", None, as_needed=True)]))
    assert ok["findings"] == []
    too_big = check_dosages(_timeline([_med("Ibuprofen", ["ibuprofen"], 1200, "mg", None, as_needed=True)]))
    assert _kinds(too_big) == ["above_max_single_dose"]


def test_subtherapeutic_dose_flagged_informational():
    report = check_dosages(_timeline([_med("Aspirin", ["aspirin"], 10, "mg", 1)]))
    assert _kinds(report) == ["below_min_single_dose"]
    # routed as informational, not a ceiling violation
    assert report["findings"][0]["kind"] == "below_min_single_dose"


def test_unknown_ingredient_is_skipped_with_reason():
    report = check_dosages(_timeline([_med("Obscurol", ["obscurodine"], 100, "mg", 2)]))
    assert report["findings"] == []
    assert len(report["skipped"]) == 1
    assert "no dosage rule" in report["skipped"][0]["reason"]


def test_combination_product_is_skipped_not_guessed():
    report = check_dosages(_timeline([
        _med("Co-codamol", ["paracetamol", "codeine"], 500, "mg", 8),
    ]))
    assert report["findings"] == []
    assert "combination product" in report["skipped"][0]["reason"]


def test_non_mass_units_are_skipped_not_guessed():
    report = check_dosages(_timeline([_med("Insulin", ["insulin glargine"], 20, "IU", 1)]))
    assert report["findings"] == []
    assert len(report["skipped"]) == 1


def test_unnormalized_dose_is_skipped():
    report = check_dosages(_timeline([_med("Paracetamol", ["paracetamol"], None, None, 3)]))
    assert report["findings"] == []
    assert "not normalized" in report["skipped"][0]["reason"]


def test_microgram_conversion():
    # levothyroxine rule is in mg (0.3 mg = 300 mcg): 500 mcg should flag.
    report = check_dosages(_timeline([_med("Levothyroxine", ["levothyroxine"], 500, "mcg", 1)]))
    assert "above_max_single_dose" in _kinds(report)


def test_every_finding_carries_consult_framing_and_source():
    report = check_dosages(_timeline([_med("Paracetamol", ["paracetamol"], 1500, "mg", 4)]))
    for finding in report["findings"]:
        assert "Consult a doctor or pharmacist" in finding["explanation"]
        assert finding["source"] == "dosage_rules"
        assert finding["source_file"] == "rx.pdf"
    assert "not mean a dose is safe" in report["note"].replace("does NOT mean a dose is safe", "not mean a dose is safe")
