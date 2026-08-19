"""Offline tests for deterministic dosage validation."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dosage_rules import check_dosages  # noqa: E402


def _med(name, ingredients, dosage_value, dosage_unit, frequency=None, as_needed=False):
    return {
        "name": name,
        "ingredients": ingredients,
        "dosage_value": dosage_value,
        "dosage_unit": dosage_unit,
        "frequency_per_day": frequency,
        "is_as_needed": as_needed,
        "date": "2024-01-01",
        "source_file": "rx.pdf",
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
    ok = check_dosages(
        _timeline([_med("Ibuprofen", ["ibuprofen"], 400, "mg", None, as_needed=True)])
    )
    assert ok["findings"] == []
    too_big = check_dosages(
        _timeline([_med("Ibuprofen", ["ibuprofen"], 1200, "mg", None, as_needed=True)])
    )
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
    report = check_dosages(
        _timeline(
            [
                _med("Co-codamol", ["paracetamol", "codeine"], 500, "mg", 8),
            ]
        )
    )
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
    assert "not mean a dose is safe" in report["note"].replace(
        "does NOT mean a dose is safe", "not mean a dose is safe"
    )


# ---------------------------------------------------------------------------
# Unit normalization beyond mg (§1.4)
# ---------------------------------------------------------------------------


def test_tablet_doses_converted_via_standard_strength():
    # 3 tablets x 4/day, assuming 500 mg tablets -> 1500 mg single (above
    # 1000 mg ceiling) and 6000 mg/day (above 4000 mg/day).
    report = check_dosages(_timeline([_med("Paracetamol", ["paracetamol"], 3, "tablet", 4)]))
    kinds = _kinds(report)
    assert "above_max_single_dose" in kinds
    assert "above_max_daily_dose" in kinds
    single = next(f for f in report["findings"] if f["kind"] == "above_max_single_dose")
    assert single["dose_mg"] == 1500.0
    assert single["unit_assumption"] == "assuming 500 mg tablets"
    assert single["confidence"] == 0.85  # assumption-based, below direct-mg confidence


def test_liquid_doses_converted_via_standard_strength():
    # paracetamol syrup 30 mL -> 1500 mg (assuming 50 mg/mL) -> above single ceiling.
    report = check_dosages(_timeline([_med("Paracetamol syrup", ["paracetamol"], 30, "ml", 3)]))
    kinds = _kinds(report)
    assert "above_max_single_dose" in kinds
    finding = next(f for f in report["findings"] if f["kind"] == "above_max_single_dose")
    assert finding["dose_mg"] == 1500.0
    assert "50 mg/mL" in finding["unit_assumption"]


def test_iu_doses_converted_exactly():
    # 50,000 IU vitamin D3 daily -> 1.25 mg/day, above the 0.1 mg (4000 IU) ceiling.
    report = check_dosages(_timeline([_med("Vitamin D3", ["cholecalciferol"], 50000, "IU", 1)]))
    kinds = _kinds(report)
    assert "above_max_daily_dose" in kinds
    finding = report["findings"][0]
    assert finding["dose_mg"] == 1.25
    assert "converted exactly" in finding["unit_assumption"]


def test_unconvertible_unit_reported_not_evaluated():
    # metformin has no documented liquid strength or IU factor -> the mL dose
    # is reported as not evaluated, never guessed.
    report = check_dosages(_timeline([_med("Metformin liquid", ["metformin"], 5, "ml", 2)]))
    assert report["findings"] == []
    assert len(report["skipped"]) == 1
    assert "not evaluated" in report["skipped"][0]["reason"]


def test_direct_mg_findings_keep_full_confidence_and_no_assumption():
    report = check_dosages(_timeline([_med("Paracetamol", ["paracetamol"], 1500, "mg", 3)]))
    finding = report["findings"][0]
    assert finding["confidence"] == 0.95
    assert finding["unit_assumption"] is None


# ---------------------------------------------------------------------------
# Activity scoping (§1.2)
# ---------------------------------------------------------------------------


def test_expired_course_excluded_from_dosage_checks():
    from datetime import date, timedelta

    med = _med("Paracetamol", ["paracetamol"], 1500, "mg", 3)
    med["date"] = (date.today() - timedelta(days=400)).isoformat()
    med["duration"] = "7 days"
    report = check_dosages(_timeline([med]))
    assert report["findings"] == []
    assert report["excluded_inactive"], "expired course must be listed, not dropped silently"
    assert report["excluded_inactive"][0]["medication"] == "Paracetamol"
    assert "reference_date" in report


def test_reference_date_param_scopes_activity():
    med = _med("Amoxicillin", ["amoxicillin"], 2500, "mg", 3)
    med["date"] = "2024-01-01"
    med["duration"] = "7 days"  # course ends 2024-01-08
    # After the course: excluded, no findings.
    excluded = check_dosages(_timeline([med]), reference_date="2024-03-01")
    assert excluded["findings"] == []
    assert excluded["excluded_inactive"]
    # During the course: checked and flagged.
    checked = check_dosages(_timeline([med]), reference_date="2024-01-03")
    assert "above_max_single_dose" in _kinds(checked)


def test_open_ended_course_still_checked():
    from datetime import date, timedelta

    med = _med("Paracetamol", ["paracetamol"], 1500, "mg", 3)
    med["date"] = (date.today() - timedelta(days=800)).isoformat()  # old, no duration
    report = check_dosages(_timeline([med]))
    assert "above_max_single_dose" in _kinds(report)
