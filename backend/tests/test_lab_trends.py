"""Regression tests for lab_trends.py boundary wording and direction logic.

The headline case is the "fluctuating (net increasing)" boundary bug:
_explain() used `direction.startswith("increasing")` to decide whether a
value was drifting toward the upper or lower edge of its reference range.
_direction() can return "fluctuating (net increasing)" for a noisy-but-
climbing series — that does not *start* with "increasing", so the ternary
fell through and told the patient a rising value was heading for the
BOTTOM of the range. Medically inverted, silent, HTTP 200, and only on the
approaching_threshold early-warning path.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lab_trends import track_lab_trends  # noqa: E402


def _series(test_name, values, reference_range="70-100", unit="mg/dL", flags=None):
    """Build a lab_results_timeline for one test from a list of values."""
    flags = flags or ["normal"] * len(values)
    return {
        "lab_results_timeline": [
            {
                "test_name": test_name,
                "value": str(v),
                "unit": unit,
                "reference_range": reference_range,
                "flag": f,
                "confidence": 0.9,
                "date": f"2026-{i + 1:02d}-01",
                "source_file": f"{chr(97 + i)}.pdf",
            }
            for i, (v, f) in enumerate(zip(values, flags))
        ]
    }


def _only_trend(timeline):
    result = track_lab_trends(timeline)
    assert result["trends"], "expected at least one trend"
    return result["trends"][0]


class TestFluctuatingBoundaryWording:
    """The regression that motivated this file."""

    def test_fluctuating_net_increasing_says_upper_boundary(self):
        # 75 -> 98 -> 97 in a 70-100 range: noisy, but climbing, and the
        # last reading sits 3 units from the TOP of the range.
        trend = _only_trend(_series("Glucose", [75, 98, 97]))

        assert trend["direction"] == "fluctuating (net increasing)"
        assert trend["approaching_threshold"] is True
        assert "upper boundary" in trend["explanation"], trend["explanation"]
        assert "lower boundary" not in trend["explanation"], trend["explanation"]

    def test_fluctuating_net_decreasing_says_lower_boundary(self):
        # Mirror case: noisy but falling toward the bottom of the range.
        trend = _only_trend(_series("Glucose", [95, 72, 73]))

        assert trend["direction"] == "fluctuating (net decreasing)"
        assert trend["approaching_threshold"] is True
        assert "lower boundary" in trend["explanation"], trend["explanation"]
        assert "upper boundary" not in trend["explanation"], trend["explanation"]

    def test_monotonic_increasing_still_says_upper_boundary(self):
        # The case the old startswith() check handled correctly — must not
        # regress while fixing the fluctuating one.
        trend = _only_trend(_series("Glucose", [75, 85, 97]))

        assert trend["direction"] == "increasing"
        assert trend["approaching_threshold"] is True
        assert "upper boundary" in trend["explanation"], trend["explanation"]
        assert "lower boundary" not in trend["explanation"], trend["explanation"]

    def test_monotonic_decreasing_still_says_lower_boundary(self):
        trend = _only_trend(_series("Glucose", [95, 85, 72]))

        assert trend["direction"] == "decreasing"
        assert trend["approaching_threshold"] is True
        assert "lower boundary" in trend["explanation"], trend["explanation"]
        assert "upper boundary" not in trend["explanation"], trend["explanation"]

    @pytest.mark.parametrize(
        "values,expected_word",
        [
            ([75, 98, 97], "upper"),   # fluctuating (net increasing)
            ([95, 72, 73], "lower"),   # fluctuating (net decreasing)
            ([75, 85, 97], "upper"),   # increasing
            ([95, 85, 72], "lower"),   # decreasing
        ],
    )
    def test_boundary_word_matches_net_direction(self, values, expected_word):
        """Whatever _direction() reports, the boundary word must agree with
        it. This is the invariant the bug violated."""
        trend = _only_trend(_series("Glucose", values))
        explanation = trend["explanation"]

        if not trend["approaching_threshold"]:
            pytest.skip("series did not trip the approaching-threshold path")

        assert f"{expected_word} boundary" in explanation, explanation
        wrong = "lower" if expected_word == "upper" else "upper"
        assert f"{wrong} boundary" not in explanation, explanation

    def test_direction_and_explanation_never_contradict(self):
        """The UI renders `direction` and `explanation` side by side, so a
        mismatch is visible to the user."""
        trend = _only_trend(_series("Glucose", [75, 98, 97]))

        if "increasing" in trend["direction"] and "boundary" in trend["explanation"]:
            assert "upper boundary" in trend["explanation"]
        if "decreasing" in trend["direction"] and "boundary" in trend["explanation"]:
            assert "lower boundary" in trend["explanation"]


class TestDirectionClassification:
    def test_stable_series(self):
        trend = _only_trend(_series("Glucose", [85, 85, 85]))
        assert trend["direction"] == "stable"
        assert "No concerning drift observed." in trend["explanation"]

    def test_crossing_into_high_is_reported(self):
        trend = _only_trend(
            _series("Glucose", [80, 95, 110], flags=["normal", "normal", "high"])
        )
        assert "into the 'high' range" in trend["explanation"], trend["explanation"]

    def test_already_abnormal_at_first_reading(self):
        trend = _only_trend(
            _series("Glucose", [110, 115, 120], flags=["high", "high", "high"])
        )
        assert "already outside the normal range" in trend["explanation"], trend["explanation"]

    def test_reference_range_renders_without_sign_confusion(self):
        """A '70-99' range must not render as '-99-70'."""
        trend = _only_trend(_series("Glucose", [75, 85, 90], reference_range="70-99"))
        assert "70-99 mg/dL" in trend["explanation"], trend["explanation"]


class TestWithSyntheticFixtures:
    """Wire the generator into the trend engine — the loop YGC's
    generate_lab_test_data.py was written to enable."""

    def test_generated_fluctuating_series_is_classified_and_worded_correctly(self):
        from generate_lab_test_data import generate_patient_documents
        from medical_extractor import build_patient_timeline

        docs = generate_patient_documents(
            "fixture patient", visits=4, seed=7, shape="fluctuating-rising"
        )
        # build_patient_timeline() does no demo filtering of its own — that
        # lives upstream in group_documents_by_patient(). We deliberately call
        # it directly here: these fixtures carry _source.method="synthetic",
        # which _is_demo_document() now (correctly) treats as a demo marker,
        # so routing them through the grouper would discard them.
        timeline = build_patient_timeline(docs)
        result = track_lab_trends(timeline)

        assert result["trends"], "generator produced no usable trends"
        for trend in result["trends"]:
            explanation = trend["explanation"]
            if "boundary" not in explanation:
                continue
            if "increasing" in trend["direction"]:
                assert "upper boundary" in explanation, (trend["direction"], explanation)
            elif "decreasing" in trend["direction"]:
                assert "lower boundary" in explanation, (trend["direction"], explanation)

    def test_generator_is_deterministic_under_seed(self):
        from generate_lab_test_data import generate_patient_documents

        a = generate_patient_documents("jane doe", visits=3, seed=42)
        b = generate_patient_documents("jane doe", visits=3, seed=42)
        assert a == b


class TestValueParsing:
    """A bare \\d+ search stopped at the first comma, so "150,000" became
    150 — a ~1000x understatement that reads as critical thrombocytopenia
    and inverts the trend direction."""

    @pytest.mark.parametrize("raw,expected", [
        ("150,000", 150000.0),
        ("1,234", 1234.0),
        ("1,234,567", 1234567.0),
        ("450,000", 450000.0),
        ("5.3", 5.3),
        ("95", 95.0),
        ("<5", 5.0),
        ("1.5 mg", 1.5),
        ("1.234,56", 1234.56),   # European: dot thousands, comma decimal
        ("5,3", 5.3),            # comma decimal, no 3-digit group
    ])
    def test_numeric_values_parse_at_full_magnitude(self, raw, expected):
        from lab_trends import _parse_value
        assert _parse_value(raw) == pytest.approx(expected)

    @pytest.mark.parametrize("raw", ["", "   ", None, "no digits here", True, False])
    def test_non_numeric_values_rejected(self, raw):
        from lab_trends import _parse_value
        assert _parse_value(raw) is None

    def test_platelet_count_trend_uses_real_magnitude(self):
        trend = _only_trend(_series(
            "Platelets", ["150,000", "300,000", "450,000"],
            reference_range="150,000-450,000", unit="/uL",
        ))
        values = [p["value"] for p in trend["data_points"]]
        assert values == ["150,000", "300,000", "450,000"]
        assert trend["direction"] == "increasing"


class TestReferenceRangeParsing:
    @pytest.mark.parametrize("raw,expected", [
        ("70-99", (70.0, 99.0)),
        ("70 - 99 mg/dL", (70.0, 99.0)),
        ("0.74-1.35 mg/dL", (0.74, 1.35)),
        ("Reference: 7-56 U/L", (7.0, 56.0)),
        ("70 to 99", (70.0, 99.0)),          # word separator
        ("70\u201399", (70.0, 99.0)),        # en dash
        ("-2 - 2", (-2.0, 2.0)),             # genuinely negative lower bound
        ("150,000-450,000", (150000.0, 450000.0)),
        ("5-10 x10^9/L", (5.0, 10.0)),
    ])
    def test_ranges_parse(self, raw, expected):
        from lab_trends import _parse_range
        low, high = _parse_range(raw)
        assert (low, high) == pytest.approx(expected)

    @pytest.mark.parametrize("raw", ["<5", ">10", "", None, "negative", "up to"])
    def test_unparseable_ranges_return_none_rather_than_guessing(self, raw):
        from lab_trends import _parse_range
        assert _parse_range(raw) is None

    def test_low_and_high_never_inverted(self):
        from lab_trends import _parse_range
        for raw in ["70-99", "99-70"]:
            low, high = _parse_range(raw)
            assert low <= high


class TestRecoveryWording:
    """normal -> high -> normal is a treated-and-recovered patient. The
    explanation appended 'and has stayed there since' to every crossing,
    reporting a resolved excursion as ongoing."""

    def test_returned_to_normal_is_not_described_as_ongoing(self):
        trend = _only_trend(_series(
            "Glucose", [91, 130, 88], reference_range="70-99",
            flags=["normal", "high", "normal"],
        ))
        explanation = trend["explanation"]
        assert "stayed there since" not in explanation
        assert "back within the normal range" in explanation

    def test_still_abnormal_still_says_stayed_there(self):
        trend = _only_trend(_series(
            "Glucose", [91, 103, 118], reference_range="70-99",
            flags=["normal", "high", "high"],
        ))
        assert "stayed there since" in trend["explanation"]

    def test_crossing_point_still_recorded_after_recovery(self):
        """The excursion happened; only the wording changes."""
        trend = _only_trend(_series(
            "Glucose", [91, 130, 88], reference_range="70-99",
            flags=["normal", "high", "normal"],
        ))
        assert trend["crossed_into_abnormal_at"] is not None
        assert trend["crossed_into_abnormal_at"]["flag"] == "high"

    def test_explanation_never_claims_ongoing_when_last_flag_normal(self):
        for flags in (
            ["normal", "high", "normal"],
            ["normal", "low", "normal"],
            ["normal", "high", "low", "normal"],
        ):
            trend = _only_trend(_series(
                "Marker", list(range(80, 80 + len(flags))),
                reference_range="70-99", flags=flags,
            ))
            if trend["crossed_into_abnormal_at"]:
                assert "stayed there since" not in trend["explanation"], flags


class TestUnitMismatch:
    """95 mg/dL and 5.3 mmol/L are the same glucose value. Subtracting them
    produced a steep 'fall', and the explanation relabelled every point
    with the last visit's unit ('from 95 mmol/L') — a fabricated number."""

    def _mixed_units(self):
        return {"lab_results_timeline": [
            {"test_name": "Glucose", "value": "95", "unit": "mg/dL",
             "reference_range": "70-99", "flag": "normal", "confidence": 0.95,
             "date": "2026-01-01", "source_file": "a.pdf"},
            {"test_name": "Glucose", "value": "5.3", "unit": "mmol/L",
             "reference_range": "3.9-5.5", "flag": "normal", "confidence": 0.95,
             "date": "2026-04-01", "source_file": "b.pdf"},
        ]}

    def test_incompatible_units_produce_no_trend(self):
        result = track_lab_trends(self._mixed_units())
        assert result["trends"] == []

    def test_incompatible_units_are_explained_not_silently_dropped(self):
        result = track_lab_trends(self._mixed_units())
        assert len(result["insufficient_data"]) == 1
        reason = result["insufficient_data"][0]["reason"]
        assert "unit" in reason.lower()
        assert "mg/dL" in reason and "mmol/L" in reason

    def test_no_fabricated_value_in_output(self):
        """The old output said 'from 95 mmol/L' — a number that appears in
        no source document. Nothing may assert that pairing."""
        result = track_lab_trends(self._mixed_units())
        blob = str(result)
        assert "95 mmol/L" not in blob

    @pytest.mark.parametrize("second_unit", ["mg/dl", "mg/dL ", " MG/DL", "mg/dL"])
    def test_cosmetic_unit_variation_still_trends(self, second_unit):
        """Case and whitespace differences are not real disagreements."""
        result = track_lab_trends({"lab_results_timeline": [
            {"test_name": "Glucose", "value": "75", "unit": "mg/dL",
             "reference_range": "70-99", "flag": "normal", "confidence": 0.95,
             "date": "2026-01-01", "source_file": "a.pdf"},
            {"test_name": "Glucose", "value": "95", "unit": second_unit,
             "reference_range": "70-99", "flag": "normal", "confidence": 0.95,
             "date": "2026-04-01", "source_file": "b.pdf"},
        ]})
        assert len(result["trends"]) == 1
        assert result["trends"][0]["direction"] == "increasing"

    def test_missing_units_do_not_block_trending(self):
        """Absent units are unknown, not conflicting."""
        result = track_lab_trends({"lab_results_timeline": [
            {"test_name": "Glucose", "value": "75", "unit": "",
             "reference_range": "70-99", "flag": "normal", "confidence": 0.95,
             "date": "2026-01-01", "source_file": "a.pdf"},
            {"test_name": "Glucose", "value": "95", "unit": "mg/dL",
             "reference_range": "70-99", "flag": "normal", "confidence": 0.95,
             "date": "2026-04-01", "source_file": "b.pdf"},
        ]})
        assert len(result["trends"]) == 1
