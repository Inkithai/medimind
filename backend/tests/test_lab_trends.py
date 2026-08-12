"""Regression tests for lab_trends.py boundary wording, recovery, units.

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

os.environ.setdefault("GROQ_API_KEY", "gsk_test_123")

from lab_trends import (  # noqa: E402
    _convert_value,
    _crossing_point,
    _relapsed,
    _returned_to_normal,
    lab_trends_payload_is_stale,
    resolve_lab_trends,
    track_lab_trends,
)


def _series(test_name, values, reference_range="70-100", unit="mg/dL", flags=None, units=None):
    """Build a lab_results_timeline for one test from a list of values."""
    flags = flags or ["normal"] * len(values)
    units = units or [unit] * len(values)
    return {
        "lab_results_timeline": [
            {
                "test_name": test_name,
                "value": str(v),
                "unit": u,
                "reference_range": reference_range,
                "flag": f,
                "confidence": 0.9,
                "date": f"2026-{i + 1:02d}-01",
                "source_file": f"{chr(97 + i)}.pdf",
            }
            for i, (v, f, u) in enumerate(zip(values, flags, units))
        ]
    }


def _only_trend(timeline):
    result = track_lab_trends(timeline)
    assert result["trends"], f"expected at least one trend, got {result}"
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
        assert trend["returned_to_normal"] is False

    def test_already_abnormal_at_first_reading(self):
        trend = _only_trend(
            _series("Glucose", [110, 115, 120], flags=["high", "high", "high"])
        )
        assert "already outside the normal range" in trend["explanation"], trend["explanation"]
        assert trend["returned_to_normal"] is False

    def test_reference_range_renders_without_sign_confusion(self):
        """A '70-99' range must not render as '-99-70'."""
        trend = _only_trend(_series("Glucose", [75, 85, 90], reference_range="70-99"))
        assert "70-99 mg/dL" in trend["explanation"], trend["explanation"]


class TestWithSyntheticFixtures:
    """Wire the generator into the trend engine — the loop YGC's
    generate_lab_test_data.py was written to enable."""

    def test_generated_fluctuating_series_is_classified_and_worded_correctly(self):
        from generate_lab_test_data import generate_patient_documents

        docs = generate_patient_documents(
            "fixture patient", visits=4, seed=7, shape="fluctuating-rising"
        )
        # Flatten the generator's process_document()-shaped output the same
        # way build_patient_timeline() does, without importing the extractor
        # (it pulls in pdfplumber/openai at module import).
        timeline = {
            "lab_results_timeline": [
                {
                    **lab,
                    "date": doc.get("date"),
                    "source_file": (doc.get("_source") or {}).get("file"),
                }
                for doc in docs
                for lab in doc.get("lab_results") or []
            ]
        }
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


class TestReturnedToNormalHelper:
    """_returned_to_normal used to be defined, tested via wording only,
    and never called — _explain() inlined the same condition and the API
    never exposed the boolean the UI needs to drop the red badge."""

    def test_helper_true_after_crossing_then_recovery(self):
        points = [
            {"flag": "normal", "date": "a"},
            {"flag": "high", "date": "b"},
            {"flag": "normal", "date": "c"},
        ]
        assert _returned_to_normal(points, _crossing_point(points)) is True

    def test_helper_false_while_still_abnormal(self):
        points = [
            {"flag": "normal", "date": "a"},
            {"flag": "high", "date": "b"},
        ]
        assert _returned_to_normal(points, _crossing_point(points)) is False

    def test_helper_false_when_never_abnormal(self):
        points = [
            {"flag": "normal", "date": "a"},
            {"flag": "normal", "date": "b"},
        ]
        assert _returned_to_normal(points, _crossing_point(points)) is False

    def test_helper_true_when_started_abnormal_then_recovered(self):
        points = [
            {"flag": "high", "date": "a"},
            {"flag": "normal", "date": "b"},
        ]
        assert _returned_to_normal(points, _crossing_point(points)) is True


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
        assert trend["returned_to_normal"] is True

    def test_still_abnormal_still_says_stayed_there(self):
        trend = _only_trend(_series(
            "Glucose", [91, 103, 118], reference_range="70-99",
            flags=["normal", "high", "high"],
        ))
        assert "stayed there since" in trend["explanation"]
        assert trend["returned_to_normal"] is False

    def test_crossing_point_still_recorded_after_recovery(self):
        """The excursion happened; only the wording (and badge tone) change."""
        trend = _only_trend(_series(
            "Glucose", [91, 130, 88], reference_range="70-99",
            flags=["normal", "high", "normal"],
        ))
        assert trend["crossed_into_abnormal_at"] is not None
        assert trend["crossed_into_abnormal_at"]["flag"] == "high"
        assert trend["returned_to_normal"] is True

    def test_started_abnormal_then_recovered(self):
        trend = _only_trend(_series(
            "Glucose", [130, 88], reference_range="70-99",
            flags=["high", "normal"],
        ))
        assert trend["returned_to_normal"] is True
        assert "back within the normal range" in trend["explanation"]
        assert "stayed there since" not in trend["explanation"]

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
                assert trend["returned_to_normal"] is True


class TestRelapseWording:
    """high → normal → high is a relapse. The 'has remained' branch only
    fires when first *and* last are abnormal and there was no return to
    normal in between; a relapse used to get no narrative (or the
    'stayed there since' wording, which is false)."""

    def test_relapse_is_described(self):
        trend = _only_trend(_series(
            "Glucose", [130, 88, 125], reference_range="70-99",
            flags=["high", "normal", "high"],
        ))
        explanation = trend["explanation"]
        assert "returned to normal" in explanation
        assert "crossed back" in explanation
        assert "stayed there since" not in explanation
        assert "has remained" not in explanation
        assert trend["returned_to_normal"] is False

    def test_relapse_helper(self):
        points = [
            {"flag": "high"},
            {"flag": "normal"},
            {"flag": "high"},
        ]
        assert _relapsed(points) is True
        assert _relapsed(points[:2]) is False
        assert _relapsed([{"flag": "high"}, {"flag": "high"}]) is False

    def test_always_abnormal_still_says_remained(self):
        trend = _only_trend(_series(
            "Glucose", [130, 140, 150], reference_range="70-99",
            flags=["high", "high", "high"],
        ))
        assert "has remained 'high'" in trend["explanation"]
        assert "crossed back" not in trend["explanation"]


class TestUnitConversion:
    """95 mg/dL and 5.3 mmol/L are the same glucose value. Subtracting
    them used to produce a steep 'fall' labelled 'from 95 mmol/L'. The
    series is now converted via the glucose molar mass and trended."""

    def _mixed_glucose(self, second_value="5.3", second_flag="normal"):
        return {"lab_results_timeline": [
            {"test_name": "Glucose", "value": "95", "unit": "mg/dL",
             "reference_range": "70-99", "flag": "normal", "confidence": 0.95,
             "date": "2026-01-01", "source_file": "a.pdf"},
            {"test_name": "Glucose", "value": second_value, "unit": "mmol/L",
             "reference_range": "3.9-5.5", "flag": second_flag, "confidence": 0.95,
             "date": "2026-04-01", "source_file": "b.pdf"},
        ]}

    def test_equivalent_glucose_is_stable_not_a_crash(self):
        trend = _only_trend(self._mixed_glucose())
        assert trend["direction"] == "stable"
        assert trend["unit"] == "mmol/L"
        assert "95 mmol/L" not in trend["explanation"]
        assert "converted" in trend["explanation"].lower()

    def test_converted_point_keeps_the_source_reading(self):
        trend = _only_trend(self._mixed_glucose())
        first = trend["data_points"][0]
        assert first["original_value"] == "95"
        assert first["original_unit"] == "mg/dL"
        # 95 mg/dL ≈ 5.27 mmol/L — not 95, not 5.3 on the nose.
        assert float(first["value"]) == pytest.approx(95 * 10 / 180.156, rel=1e-3)

    def test_real_rise_across_units_is_still_increasing(self):
        # 95 mg/dL ≈ 5.27 mmol/L; 7.0 mmol/L is a real jump.
        trend = _only_trend(self._mixed_glucose(second_value="7.0", second_flag="high"))
        assert trend["direction"] == "increasing"
        assert trend["crossed_into_abnormal_at"]["flag"] == "high"

    def test_no_fabricated_unconverted_pairing(self):
        result = track_lab_trends(self._mixed_glucose())
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

    def test_hemoglobin_gdl_to_gl_needs_no_molar_mass(self):
        trend = _only_trend(_series(
            "Hemoglobin", [13.5, 135], unit="g/dL",
            reference_range="13-17",
            units=["g/dL", "g/L"],
        ))
        assert trend["direction"] == "stable"
        assert trend["unit"] == "g/L"
        assert float(trend["data_points"][0]["value"]) == pytest.approx(135.0)

    def test_creatinine_mgdl_to_umol(self):
        # 0.92 mg/dL * 88.4 ≈ 81.3 µmol/L
        result = track_lab_trends({"lab_results_timeline": [
            {"test_name": "Creatinine", "value": "0.92", "unit": "mg/dL",
             "reference_range": "0.74-1.35", "flag": "normal", "confidence": 0.95,
             "date": "2026-01-01", "source_file": "a.pdf"},
            {"test_name": "Creatinine", "value": "81", "unit": "µmol/L",
             "reference_range": "65-120", "flag": "normal", "confidence": 0.95,
             "date": "2026-04-01", "source_file": "b.pdf"},
        ]})
        assert len(result["trends"]) == 1
        assert result["trends"][0]["direction"] == "stable"

    def test_unknown_analyte_mixed_molar_units_still_declined(self):
        result = track_lab_trends({"lab_results_timeline": [
            {"test_name": "Mystery Marker", "value": "95", "unit": "mg/dL",
             "reference_range": "70-99", "flag": "normal", "confidence": 0.95,
             "date": "2026-01-01", "source_file": "a.pdf"},
            {"test_name": "Mystery Marker", "value": "5.3", "unit": "mmol/L",
             "reference_range": "3.9-5.5", "flag": "normal", "confidence": 0.95,
             "date": "2026-04-01", "source_file": "b.pdf"},
        ]})
        assert result["trends"] == []
        assert len(result["insufficient_data"]) == 1
        assert "unit" in result["insufficient_data"][0]["reason"].lower()

    def test_incompatible_dimensions_still_declined(self):
        result = track_lab_trends({"lab_results_timeline": [
            {"test_name": "ALT", "value": "24", "unit": "U/L",
             "reference_range": "7-56", "flag": "normal", "confidence": 0.95,
             "date": "2026-01-01", "source_file": "a.pdf"},
            {"test_name": "ALT", "value": "0.4", "unit": "µkat/L",
             "reference_range": "0.12-0.93", "flag": "normal", "confidence": 0.95,
             "date": "2026-04-01", "source_file": "b.pdf"},
        ]})
        assert result["trends"] == []
        assert "unit" in result["insufficient_data"][0]["reason"].lower()

    def test_convert_value_glucose_round_trip(self):
        mmol = _convert_value(95.0, "mg/dL", "mmol/L", 180.156)
        back = _convert_value(mmol, "mmol/L", "mg/dL", 180.156)
        assert mmol == pytest.approx(5.273, rel=1e-3)
        assert back == pytest.approx(95.0, rel=1e-6)


class TestStalePayload:
    def test_missing_returned_to_normal_is_stale(self):
        payload = {
            "trends": [{"test_name": "Glucose", "explanation": "back within the normal range"}],
            "insufficient_data": [],
        }
        assert lab_trends_payload_is_stale(payload) is True

    def test_current_payload_is_fresh(self):
        trend = _only_trend(_series("Glucose", [80, 85]))
        assert lab_trends_payload_is_stale({"trends": [trend], "insufficient_data": []}) is False

    def test_unit_decline_payload_is_stale(self):
        payload = {
            "trends": [],
            "insufficient_data": [{
                "test_name": "Glucose",
                "reason": "readings use 2 different units (mg/dL, mmol/L) — values are not directly comparable",
            }],
        }
        assert lab_trends_payload_is_stale(payload) is True

    def test_resolve_recomputes_stale_recovery(self):
        timeline = _series(
            "Glucose", [91, 130, 88], reference_range="70-99",
            flags=["normal", "high", "normal"],
        )
        stale = {
            "trends": [{
                "test_name": "Glucose",
                "crossed_into_abnormal_at": {"date": "2026-02-01", "flag": "high"},
                "explanation": "has stayed there since",
            }],
            "insufficient_data": [],
        }
        fresh = resolve_lab_trends(timeline, stale)
        assert fresh["trends"][0]["returned_to_normal"] is True
        assert "stayed there since" not in fresh["trends"][0]["explanation"]
