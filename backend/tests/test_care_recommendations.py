"""Regression tests for the records-based care-recommendation engine.

These pin down clinical-logic bugs that shipped in the first version:

  1. Substring keyword matching: "ast" matched "F-AST-ing Glucose" and
     produced a LIVER specialist recommendation for a rising glucose test.
  2. Rising HDL ("good" cholesterol — an improvement) was flagged as
     cardiovascular risk; only FALLING HDL is concerning.
  3. Atorvastatin (a statin) was listed as a diabetes medication, telling
     statin-only patients their records contain diabetes drugs.
  4. Within one relevance tier, results sorted by FEWEST supporting
     records first (ascending instead of descending).

The engine is pure logic — no LLM, no network — so these run offline.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from care.recommendations import (  # noqa: E402
    _contains_word,
    generate_care_recommendations,
)


def _trend(test_name, direction, explanation="trend explanation"):
    return {"test_name": test_name, "direction": direction, "explanation": explanation}


def _recs(timeline=None, cross_check=None, trends=None):
    return generate_care_recommendations(
        timeline or {},
        cross_check or {},
        {"trends": trends or []},
    )


def _by_key(recs):
    return {r["specialty_key"]: r for r in recs}


# ── Word-boundary matching ──────────────────────────────────────────────────

def test_contains_word_rejects_accidental_substrings():
    assert not _contains_word("fasting glucose", "ast")   # the original bug
    assert not _contains_word("fasting glucose", "alt")
    assert not _contains_word("albumin", "bp")
    assert not _contains_word("haldol level", "hdl")
    assert not _contains_word("alkaline phosphatase", "alt")
    # Real hits must still match, regardless of punctuation/casing handled upstream
    assert _contains_word("ast (sgot)", "ast")
    assert _contains_word("alt", "alt")
    assert _contains_word("serum creatinine", "creatinine")
    assert _contains_word("egfr", "egfr")
    assert _contains_word("hdl cholesterol", "hdl")
    assert _contains_word("non-hdl cholesterol", "hdl")
    assert _contains_word("bp (systolic)", "bp")


def test_rising_fasting_glucose_does_not_trigger_liver_recommendation():
    """Bug #1: 'ast' in 'fasting' produced a gastroenterologist card."""
    recs = _by_key(_recs(trends=[_trend("Fasting Glucose", "increasing")]))
    assert "gastroenterologist" not in recs, (
        "A rising glucose reading must not produce a liver recommendation"
    )
    # It SHOULD produce the endocrinologist (diabetes lab) recommendation.
    assert "endocrinologist" in recs
    assert recs["endocrinologist"]["relevance"] == "moderate"


def test_real_ast_alt_trends_still_trigger_liver_recommendation():
    for name in ("AST", "ALT", "AST (SGOT)", "Total Bilirubin"):
        recs = _by_key(_recs(trends=[_trend(name, "increasing")]))
        assert "gastroenterologist" in recs, f"{name} increasing must flag liver monitoring"


# ── HDL directionality ──────────────────────────────────────────────────────

def test_rising_hdl_is_not_flagged_as_cardiovascular_risk():
    """Bug #2: HDL is protective — improvement must not be called risk."""
    recs = _by_key(_recs(trends=[_trend("HDL Cholesterol", "increasing")]))
    assert "cardiologist" not in recs


def test_falling_hdl_is_flagged_as_cardiovascular_risk():
    recs = _by_key(_recs(trends=[_trend("HDL Cholesterol", "decreasing")]))
    assert "cardiologist" in recs


def test_rising_ldl_and_total_cholesterol_still_flagged():
    for name in ("LDL Cholesterol", "Total Cholesterol", "Triglycerides"):
        recs = _by_key(_recs(trends=[_trend(name, "increasing")]))
        assert "cardiologist" in recs, f"rising {name} must flag cardiovascular risk"


# ── Kidney directionality ───────────────────────────────────────────────────

def test_rising_creatinine_is_moderate_falling_egfr_is_moderate():
    # Rising creatinine = declining clearance = the concerning direction.
    recs = _by_key(_recs(trends=[_trend("Serum Creatinine", "increasing")]))
    assert recs["nephrologist"]["relevance"] == "moderate"
    # Falling eGFR = declining filtration = the concerning direction.
    recs = _by_key(_recs(trends=[_trend("eGFR", "decreasing")]))
    assert recs["nephrologist"]["relevance"] == "moderate"


def test_improving_kidney_markers_are_only_possible():
    recs = _by_key(_recs(trends=[_trend("Serum Creatinine", "decreasing")]))
    assert recs["nephrologist"]["relevance"] == "possible"
    recs = _by_key(_recs(trends=[_trend("eGFR", "increasing")]))
    assert recs["nephrologist"]["relevance"] == "possible"


# ── Diabetes medication classification ─────────────────────────────────────

def test_atorvastatin_alone_is_not_a_diabetes_medication():
    """Bug #3: a statin-only patient must not get a diabetes-management card."""
    timeline = {
        "medications_timeline": [
            {"name": "Atorvastatin 20mg", "ingredients": ["Atorvastatin"], "dosage": "20 mg"},
        ],
    }
    recs = _by_key(_recs(timeline=timeline))
    assert "endocrinologist" not in recs


def test_metformin_triggers_diabetes_recommendation():
    timeline = {
        "medications_timeline": [
            {"name": "Metformin 500mg", "ingredients": ["Metformin"], "dosage": "500 mg"},
        ],
    }
    recs = _by_key(_recs(timeline=timeline))
    assert "endocrinologist" in recs
    assert recs["endocrinologist"]["title"] == "Diabetes management"


def test_diabetes_med_matched_via_normalized_ingredients():
    """Brand names carry the ingredient in `ingredients`, not `name`."""
    timeline = {
        "medications_timeline": [
            {"name": "Glucophage", "ingredients": ["Metformin"], "dosage": "500 mg"},
        ],
    }
    recs = _by_key(_recs(timeline=timeline))
    assert "endocrinologist" in recs


# ── Sorting ─────────────────────────────────────────────────────────────────

def test_more_supporting_records_sort_first_within_a_tier():
    """Bug #4: within one relevance tier, most-evidence must come first."""
    timeline = {
        # 3 diabetes meds → endocrinologist (moderate, 3 records)
        "medications_timeline": [
            {"name": "Metformin", "ingredients": ["Metformin"], "dosage": "500 mg"},
            {"name": "Insulin Glargine", "ingredients": ["Insulin"], "dosage": "10 IU"},
            {"name": "Sitagliptin", "ingredients": ["Sitagliptin"], "dosage": "100 mg"},
        ],
        # 1 allergy → allergist (moderate, 1 record)
        "known_allergies": ["Penicillin"],
    }
    recs = _recs(timeline=timeline)
    moderate = [r for r in recs if r["relevance"] == "moderate"]
    assert [r["specialty_key"] for r in moderate] == ["endocrinologist", "allergist"], (
        "the recommendation with the most supporting records must sort first"
    )


def test_high_relevance_sorts_before_moderate():
    cross_check = {
        "allergy_conflicts": [
            {"medication": "Amoxicillin", "allergy": "Penicillin", "explanation": "cross-reactive"},
            {"medication": "Ampicillin", "allergy": "Penicillin", "explanation": "cross-reactive"},
        ],
    }
    timeline = {
        "medications_timeline": [
            {"name": "Metformin", "ingredients": ["Metformin"], "dosage": "500 mg"},
        ],
    }
    recs = _recs(timeline=timeline, cross_check=cross_check)
    assert recs[0]["specialty_key"] == "allergist"
    assert recs[0]["relevance"] == "high"


# ── Fallback behaviour ──────────────────────────────────────────────────────

def test_empty_records_produce_generic_gp_recommendation():
    recs = _recs()
    assert len(recs) == 1
    assert recs[0]["specialty_key"] == "general_physician"
    assert recs[0]["relevance"] == "possible"


def test_med_safety_issues_produce_gp_reconciliation():
    cross_check = {
        "potential_drug_interactions": [
            {"medications_involved": ["Warfarin", "Aspirin"], "explanation": "bleeding risk"},
        ],
        "duplicate_prescriptions": [
            {"medication": "Paracetamol", "explanation": "two sources"},
        ],
        "conflicting_dosage_instructions": [
            {"medication": "Metoprolol", "explanation": "50 vs 100 mg"},
        ],
    }
    recs = _by_key(_recs(cross_check=cross_check))
    gp = recs["general_physician"]
    assert gp["relevance"] == "high"  # 3 issues
    assert gp["title"] == "Medication reconciliation"
    assert len(gp["evidence"]) == 3


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"\n{len(fns)} tests passed")
