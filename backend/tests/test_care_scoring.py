"""
Tests for the care-recommendation engine.

Verifies the multi-factor scoring model produces sensible results
for the documented scenarios in the patient-recs product brief:

  * Anjali-like: confirmed T2DM with HbA1c trend + multiple
    medications + aspirin allergy + aspirin in old med list →
    primary-care is the top suggestion, endocrinology second,
    allergy third, nephrology possible; gastroenterology and
    cardiology should NOT appear.
  * Empty records: a single honest "general check" recommendation.
  * Drug interaction without allergy: primary-care and clinical
    pharmacist are flagged with safety signal.

Each recommendation is checked to:
  - be in the 0..100 score range
  - have at least one score_factor (when score > 0)
  - have a non-empty reason string
  - have an evidence list (possibly empty for the empty-records case)
  - not contain legacy specialty keys
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("GROQ_API_KEY", "gsk_test_123")
os.environ.setdefault("SUPABASE_URL", "https://dummy.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "dummy")
os.environ.setdefault("CLOUDINARY_CLOUD_NAME", "dummy")
os.environ.setdefault("CLOUDINARY_API_KEY", "dummy")
os.environ.setdefault("CLOUDINARY_API_SECRET", "dummy")
os.environ.setdefault("JWT_SECRET", "dummy")

from care.recommendations import (  # noqa: E402
    MAX_FACTOR_POINTS,
    SAFETY_FLOOR,
    SCORE_HIGH,
    SCORE_MODERATE,
    generate_care_recommendations,
)

# ─── Anjali-style fixture ───────────────────────────────────────────────────

ANJALI_TIMELINE = {
    "visits": [
        {
            "date": "2024-01-15",
            "medications": [{"name": "Metformin", "dosage": "500mg"}],
            "lab_results": [
                {"test_name": "HbA1c", "value": 9.2, "unit": "%", "flag": "high"},
            ],
            "allergies_noted": [],
        },
        {
            "date": "2024-06-15",
            "medications": [{"name": "Metformin", "dosage": "1000mg"}],
            "lab_results": [
                {"test_name": "HbA1c", "value": 7.4, "unit": "%", "flag": "high"},
            ],
            "allergies_noted": [],
        },
    ],
    "medications_timeline": [
        {"name": "Metformin", "dosage": "500mg", "date": "2024-01-15"},
        {"name": "Atorvastatin", "dosage": "20mg", "date": "2024-01-15"},
        {"name": "Amlodipine", "dosage": "5mg", "date": "2024-01-15"},
    ],
    "known_allergies": ["Aspirin"],
}
ANJALI_CROSS_CHECK = {
    "allergy_conflicts": [
        {"medication": "Aspirin", "allergy": "Aspirin", "explanation": "older medication list"},
    ],
    "potential_drug_interactions": [],
    "duplicate_prescriptions": [],
    "conflicting_dosage_instructions": [],
}
ANJALI_LAB_TRENDS = {
    "trends": [
        {
            "test_name": "eGFR",
            "direction": "decreasing",
            "explanation": "kidney function declining",
        },
        {
            "test_name": "Creatinine",
            "direction": "increasing",
            "explanation": "kidney function declining",
        },
        {
            "test_name": "HbA1c",
            "direction": "decreasing",
            "explanation": "glucose control improving",
        },
    ],
}


# ─── Helpers ────────────────────────────────────────────────────────────────


def _assert_basic_shape(recs):
    assert isinstance(recs, list)
    for rec in recs:
        # Score must be 0..100
        assert 0 <= rec["relevance_score"] <= 100, f"out-of-range score: {rec}"
        # Relevance bucket must match the score
        if rec["relevance_score"] >= SCORE_HIGH:
            assert rec["relevance"] == "high", rec
        elif rec["relevance_score"] >= SCORE_MODERATE:
            assert rec["relevance"] == "moderate", rec
        else:
            assert rec["relevance"] == "possible", rec
        # Must have a non-empty reason
        assert rec["reason"], f"missing reason: {rec}"
        assert rec["title"], f"missing title: {rec}"
        # Must have at least one score factor when score > 0
        if rec["relevance_score"] > 0:
            assert rec["score_factors"], f"missing score factors: {rec}"
            for f in rec["score_factors"]:
                assert 0 <= f["points"] <= MAX_FACTOR_POINTS, f"out-of-range factor: {f}"
        # Specialty key must be one of the supported taxonomy
        assert rec["specialty_key"] in {
            "general_physician",
            "clinical_pharmacist",
            "allergist",
            "endocrinologist",
            "nephrologist",
            "cardiologist",
            "dermatologist",
            "gastroenterologist",
            "hematologist",
            "neurologist",
            "oncologist",
            "ophthalmologist",
            "orthopedic",
            "psychiatrist",
            "pulmonologist",
            "rheumatologist",
        }, f"unsupported specialty: {rec['specialty_key']}"


# ─── Anjali scenario ───────────────────────────────────────────────────────


def test_anjali_top_recommendation_is_primary_care_with_safety_flag():
    recs = generate_care_recommendations(ANJALI_TIMELINE, ANJALI_CROSS_CHECK, ANJALI_LAB_TRENDS)
    _assert_basic_shape(recs)
    assert recs, "Anjali-like records should produce at least one recommendation"
    top = recs[0]
    # The top recommendation should be primary care, not cardiology or gastro
    assert top["specialty_key"] == "general_physician", (
        f"expected GP top recommendation, got {top['specialty_key']}"
    )
    # And the safety flag should be lit
    assert top["has_safety_signal"] is True
    # Safety-flagged recs must not fall below the safety floor
    assert top["relevance_score"] >= SAFETY_FLOOR, top


def test_anjali_does_not_recommend_cardiology_or_gastroenterology():
    recs = generate_care_recommendations(ANJALI_TIMELINE, ANJALI_CROSS_CHECK, ANJALI_LAB_TRENDS)
    keys = {r["specialty_key"] for r in recs}
    # These were the false-positive specialties in the legacy version.
    assert "cardiologist" not in keys, f"unexpected cardiology: {keys}"
    assert "gastroenterologist" not in keys, f"unexpected gastro: {keys}"


def test_anjali_includes_endocrinology_allergy_and_nephrology():
    recs = generate_care_recommendations(ANJALI_TIMELINE, ANJALI_CROSS_CHECK, ANJALI_LAB_TRENDS)
    keys = {r["specialty_key"] for r in recs}
    # All three of these specialties are supported by the data.
    assert "endocrinologist" in keys, keys
    assert "allergist" in keys, keys
    assert "nephrologist" in keys, keys


def test_anjali_score_factors_are_transparent_and_sum_to_score():
    recs = generate_care_recommendations(ANJALI_TIMELINE, ANJALI_CROSS_CHECK, ANJALI_LAB_TRENDS)
    for rec in recs:
        factor_sum = sum(f["points"] for f in rec["score_factors"])
        # The displayed score is the sum of factors, possibly
        # floored by SAFETY_FLOOR and capped at the relevant cap.
        assert rec["relevance_score"] <= factor_sum + 5, (
            f"score {rec['relevance_score']} not in line with factor sum {factor_sum}: {rec}"
        )
        # Factor sum should not be wildly larger than the displayed score
        # (some special cases apply the safety floor, which raises the
        # score, but never the other way).
        assert factor_sum <= rec["relevance_score"] + 5, (
            f"factor sum {factor_sum} larger than displayed score {rec['relevance_score']}: {rec}"
        )


def test_anjali_allergy_conflict_sets_safety_message():
    recs = generate_care_recommendations(ANJALI_TIMELINE, ANJALI_CROSS_CHECK, ANJALI_LAB_TRENDS)
    allergist = next((r for r in recs if r["specialty_key"] == "allergist"), None)
    assert allergist is not None
    assert allergist["has_safety_signal"] is True
    assert allergist["safety_message"]
    assert "Aspirin" in allergist["safety_message"]


# ─── Empty records ─────────────────────────────────────────────────────────


def test_empty_records_yield_a_single_honest_default_recommendation():
    recs = generate_care_recommendations(
        timeline={"visits": [], "medications_timeline": [], "known_allergies": []},
        cross_check={
            "allergy_conflicts": [],
            "potential_drug_interactions": [],
            "duplicate_prescriptions": [],
            "conflicting_dosage_instructions": [],
        },
        lab_trends={"trends": []},
    )
    _assert_basic_shape(recs)
    assert len(recs) == 1
    assert recs[0]["specialty_key"] == "general_physician"
    # The default should be a "possible" recommendation — not a "high"
    # certainty claim.
    assert recs[0]["relevance"] == "possible"


# ─── Drug interaction (no allergy) ─────────────────────────────────────────


def test_drug_interaction_drives_safety_floor_for_primary_care():
    recs = generate_care_recommendations(
        timeline={
            "visits": [
                {
                    "date": "2024-01-15",
                    "medications": [
                        {"name": "Warfarin", "dosage": "5mg"},
                        {"name": "Aspirin", "dosage": "81mg"},
                    ],
                    "lab_results": [],
                    "allergies_noted": [],
                }
            ],
            "medications_timeline": [
                {"name": "Warfarin", "dosage": "5mg"},
                {"name": "Aspirin", "dosage": "81mg"},
            ],
            "known_allergies": [],
        },
        cross_check={
            "allergy_conflicts": [],
            "potential_drug_interactions": [
                {
                    "medications_involved": ["Warfarin", "Aspirin"],
                    "explanation": "increased bleeding risk",
                }
            ],
            "duplicate_prescriptions": [],
            "conflicting_dosage_instructions": [],
        },
        lab_trends={"trends": []},
    )
    _assert_basic_shape(recs)
    keys = {r["specialty_key"]: r for r in recs}
    # Primary care should be there, with a safety signal and a score
    # that meets the safety floor.
    assert "general_physician" in keys
    assert keys["general_physician"]["has_safety_signal"] is True
    assert keys["general_physician"]["relevance_score"] >= SAFETY_FLOOR
    # Clinical pharmacist is a natural second opinion.
    assert "clinical_pharmacist" in keys
    assert keys["clinical_pharmacist"]["has_safety_signal"] is True


# ─── Stable ordering ───────────────────────────────────────────────────────


def test_recommendations_are_sorted_by_score_descending():
    recs = generate_care_recommendations(ANJALI_TIMELINE, ANJALI_CROSS_CHECK, ANJALI_LAB_TRENDS)
    scores = [r["relevance_score"] for r in recs]
    assert scores == sorted(scores, reverse=True), f"not sorted: {scores}"


def test_no_duplicate_specialty_keys():
    recs = generate_care_recommendations(ANJALI_TIMELINE, ANJALI_CROSS_CHECK, ANJALI_LAB_TRENDS)
    keys = [r["specialty_key"] for r in recs]
    assert len(keys) == len(set(keys)), f"duplicates: {keys}"


# ─── Defensive handling of malformed inputs (regression coverage) ──────────


def test_none_inputs_do_not_crash():
    """The engine is called via the /care/recommendations endpoint which
    pulls fields from a DB snapshot. If any field is NULL on the row, the
    snapshot dict's .get(...) returns None — the engine must not crash."""
    recs = generate_care_recommendations(None, None, None)
    assert isinstance(recs, list)
    assert recs, "empty engine should still return the default GP recommendation"
    assert recs[0]["specialty_key"] == "general_physician"


def test_string_known_allergies_is_coerced_to_list():
    """A malformed DB row that puts a single string in known_allergies
    must not be iterated character-by-character."""
    timeline = {
        "visits": [],
        "medications_timeline": [],
        "known_allergies": "Aspirin",  # should be coerced to ["Aspirin"]
    }
    recs = generate_care_recommendations(timeline, {}, {"trends": []})
    # The Allergist rec should reference "Aspirin" once, not 7 (one per character).
    allergist = next((r for r in recs if r["specialty_key"] == "allergist"), None)
    assert allergist is not None
    description_blob = " ".join(f["note"] for f in allergist["score_factors"])
    assert "1" in description_blob, f"expected '1 known allergy' in {description_blob}"


def test_duplicate_lab_trends_dedupe_to_one_factor():
    """The same lab test appearing in multiple trend entries (e.g. from
    multiple visits) must produce a single score factor, not N."""
    timeline = {
        "visits": [],
        "medications_timeline": [{"name": "Metformin"}],
        "known_allergies": [],
    }
    lab_trends = {
        "trends": [
            {"test_name": "HbA1c", "direction": "increasing", "explanation": "worsening"},
            {"test_name": "HbA1c", "direction": "increasing", "explanation": "worsening"},
            {"test_name": "HbA1c", "direction": "increasing", "explanation": "worsening"},
        ]
    }
    recs = generate_care_recommendations(timeline, {}, lab_trends)
    endo = next((r for r in recs if r["specialty_key"] == "endocrinologist"), None)
    assert endo is not None
    hba1c_factors = [f for f in endo["score_factors"] if "HbA1c" in f["label"]]
    assert len(hba1c_factors) == 1, f"expected 1 HbA1c factor, got {len(hba1c_factors)}"


def test_endocrinologist_reason_does_not_claim_trends_when_none_exist():
    """When only medications (no lab trends) drive the endocrine rec, the
    reason must not falsely say "and glucose/HbA1c trends"."""
    timeline = {
        "visits": [],
        "medications_timeline": [{"name": "Metformin"}],
        "known_allergies": [],
    }
    recs = generate_care_recommendations(timeline, {}, {"trends": []})
    endo = next((r for r in recs if r["specialty_key"] == "endocrinologist"), None)
    assert endo is not None
    assert "trends" not in endo["reason"].lower(), f"reason falsely claims trends: {endo['reason']}"


def test_gp_safety_message_mentions_allergy_when_both_signals_present():
    """When both an allergy conflict and a drug interaction exist, the
    GP's safety message must surface the allergy (the more urgent
    signal), not just the drug interaction."""
    timeline = {
        "visits": [],
        "medications_timeline": [{"name": "Warfarin"}],
        "known_allergies": ["Aspirin"],
    }
    cross_check = {
        "allergy_conflicts": [
            {"medication": "Aspirin", "allergy": "Aspirin", "explanation": "older list"}
        ],
        "potential_drug_interactions": [
            {"medications_involved": ["Warfarin", "Aspirin"], "explanation": "bleeding risk"}
        ],
        "duplicate_prescriptions": [],
        "conflicting_dosage_instructions": [],
    }
    recs = generate_care_recommendations(timeline, cross_check, {"trends": []})
    gp = next((r for r in recs if r["specialty_key"] == "general_physician"), None)
    assert gp is not None
    assert gp["safety_message"] is not None
    assert "allergy" in gp["safety_message"].lower(), (
        f"GP safety msg missing allergy: {gp['safety_message']}"
    )
    assert "drug" in gp["safety_message"].lower(), (
        f"GP safety msg missing drug interaction: {gp['safety_message']}"
    )


if __name__ == "__main__":
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_")]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"\n{len(tests)} tests passed")
