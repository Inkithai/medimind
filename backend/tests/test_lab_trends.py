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
