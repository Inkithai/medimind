"""Offline tests for the deterministic medication-allergy contraindication KB."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from drug_allergy_rules import (  # noqa: E402
    check_allergy_conflicts,
    merge_allergy_findings,
)


def _timeline(meds=None, allergies=None):
    return {
        "medications_timeline": meds or [],
        "known_allergies": allergies or [],
    }


def _med(name, ingredients, date="2024-01-01", source="rx.pdf"):
    return {"name": name, "ingredients": ingredients, "date": date, "source_file": source}


def test_flags_penicillin_allergy_vs_amoxicillin():
    timeline = _timeline(
        meds=[_med("Amoxicillin 500mg", ["amoxicillin"], source="a.pdf")],
        allergies=["Penicillin"],
    )
    findings = check_allergy_conflicts(timeline)
    assert len(findings) == 1
    f = findings[0]
    assert f["medication"] == "Amoxicillin 500mg"
    assert f["allergy"] == "Penicillin"
    assert f["severity"] == "high"
    assert f["source"] == "curated_knowledge_base"
    assert f["rule"] == "penicillin allergy"
    assert "anaphylaxis" in f["explanation"].lower()
    assert f["confidence"] == 0.95


def test_sulfa_alias_matches_co_trimoxazole_ingredient():
    timeline = _timeline(
        meds=[_med("Bactrim", ["trimethoprim and sulfamethoxazole"], source="a.pdf")],
        allergies=["Sulfa Drugs"],
    )
    findings = check_allergy_conflicts(timeline)
    assert len(findings) == 1
    assert findings[0]["rule"] == "sulfonamide allergy"


def test_brand_name_allergy_matches_class_member():
    # "Brufen" (a brand of ibuprofen) must resolve to the NSAID class even
    # though no medication ingredient is literally called "brufen".
    timeline = _timeline(
        meds=[_med("Ibuprofen 400mg", ["ibuprofen"], source="a.pdf")],
        allergies=["Brufen"],
    )
    findings = check_allergy_conflicts(timeline)
    assert len(findings) == 1
    assert findings[0]["rule"] == "nsaid allergy"


def test_direct_ingredient_allergy_without_a_class():
    # Paracetamol is in no allergen class here — the allergy text literally
    # names the active ingredient, so it still matches.
    timeline = _timeline(
        meds=[_med("Panadol", ["paracetamol"], source="a.pdf")],
        allergies=["paracetamol"],
    )
    findings = check_allergy_conflicts(timeline)
    assert len(findings) == 1
    assert findings[0]["rule"] == "exact allergen match"


def test_no_known_allergies_yields_no_findings():
    timeline = _timeline(
        meds=[_med("Amoxicillin", ["amoxicillin"], source="a.pdf")],
        allergies=["No known drug allergies"],
    )
    assert check_allergy_conflicts(timeline) == []


def test_exception_statement_still_matches_the_named_allergen():
    # "no known drug allergies except penicillin" names penicillin —
    # suppressing the match would be the dangerous error.
    timeline = _timeline(
        meds=[_med("Amoxicillin", ["amoxicillin"], source="a.pdf")],
        allergies=["no known drug allergies except penicillin"],
    )
    findings = check_allergy_conflicts(timeline)
    assert len(findings) == 1
    assert findings[0]["rule"] == "penicillin allergy"


def test_unrelated_allergy_yields_no_findings():
    timeline = _timeline(
        meds=[_med("Amoxicillin", ["amoxicillin"], source="a.pdf")],
        allergies=["Metformin"],
    )
    assert check_allergy_conflicts(timeline) == []


def test_same_allergy_med_pair_reported_once():
    # The same prescription line re-uploaded must not duplicate the finding.
    timeline = _timeline(
        meds=[
            _med("Amoxicillin", ["amoxicillin"], source="a.pdf"),
            _med("Amoxicillin", ["amoxicillin"], source="a.pdf"),
        ],
        allergies=["penicillin"],
    )
    findings = check_allergy_conflicts(timeline)
    assert len(findings) == 1


def test_multiple_allergies_and_medications_all_checked():
    timeline = _timeline(
        meds=[
            _med("Amoxicillin", ["amoxicillin"], source="a.pdf"),
            _med("Brufen 400mg", ["ibuprofen"], source="b.pdf"),
            _med("Metformin", ["metformin"], source="c.pdf"),
        ],
        allergies=["penicillin", "nsaids"],
    )
    findings = check_allergy_conflicts(timeline)
    assert len(findings) == 2
    rules = sorted(f["rule"] for f in findings)
    assert rules == ["nsaid allergy", "penicillin allergy"]


def test_no_medications_or_no_allergies_yields_nothing():
    assert check_allergy_conflicts(_timeline(meds=[_med("X", ["x"])])) == []
    assert check_allergy_conflicts(_timeline(allergies=["penicillin"])) == []


def test_merge_skips_pairs_the_llm_already_flagged():
    report = {
        "allergy_conflicts": [
            {
                "medication": "Amoxicillin 500mg",
                "allergy": "penicillin allergy",
                "explanation": "LLM found it",
                "confidence": 0.9,
            },
        ],
    }
    kb = check_allergy_conflicts(_timeline(
        meds=[_med("Amoxicillin 500mg", ["amoxicillin"])],
        allergies=["Penicillin"],
    ))
    merge_allergy_findings(report, kb)
    assert len(report["allergy_conflicts"]) == 1
    assert report["allergy_conflicts"][0]["explanation"] == "LLM found it"


def test_merge_adds_pairs_the_llm_missed():
    report = {"allergy_conflicts": []}
    kb = check_allergy_conflicts(_timeline(
        meds=[_med("Amoxicillin", ["amoxicillin"])],
        allergies=["Penicillin"],
    ))
    merge_allergy_findings(report, kb)
    assert len(report["allergy_conflicts"]) == 1
    assert report["allergy_conflicts"][0]["source"] == "curated_knowledge_base"


def test_findings_carry_llm_compatible_shape():
    """Every field the LLM schema and clinical_flags.py expect must exist,
    so downstream consumers treat KB findings exactly like model ones."""
    timeline = _timeline(
        meds=[_med("Amoxicillin", ["amoxicillin"])],
        allergies=["Penicillin"],
    )
    f = check_allergy_conflicts(timeline)[0]
    assert set(f) >= {"medication", "allergy", "explanation", "confidence"}
    assert isinstance(f["confidence"], float)


def test_drug_names_containing_negative_marker_substrings_are_not_misread():
    # "sulfanilamide" contains "nil" — it is a substance, not a negative
    # statement. The resolver must classify it as an unknown substance
    # (no classes, not negative) so the direct-ingredient match still works.
    from drug_allergy_rules import _resolve_allergy_classes
    assert _resolve_allergy_classes("sulfanilamide") == set()
    timeline = _timeline(
        meds=[_med("Sulfanilamide", ["sulfanilamide"], source="a.pdf")],
        allergies=["sulfanilamide"],
    )
    findings = check_allergy_conflicts(timeline)
    assert len(findings) == 1
    assert findings[0]["rule"] == "exact allergen match"
