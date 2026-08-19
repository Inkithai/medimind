"""Offline tests for the deterministic drug-interaction knowledge base."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from drug_interactions import check_known_interactions, merge_into_report  # noqa: E402


def _timeline(meds):
    return {"medications_timeline": meds, "known_allergies": []}


def _med(name, ingredients, date="2024-01-01", source="rx.pdf"):
    return {"name": name, "ingredients": ingredients, "date": date, "source_file": source}


def test_flags_anticoagulant_plus_nsaid_as_high():
    timeline = _timeline(
        [
            _med("Warfarin 5mg", ["warfarin"], source="a.pdf"),
            _med("Brufen", ["ibuprofen"], source="b.pdf"),
        ]
    )
    findings = check_known_interactions(timeline)
    assert len(findings) == 1
    f = findings[0]
    assert f["severity"] == "high"
    assert f["source"] == "curated_knowledge_base"
    assert set(f["medications_involved"]) == {"Warfarin 5mg", "Brufen"}
    assert "bleeding" in f["explanation"].lower()


def test_matches_class_members_not_just_named_pairs():
    # apixaban (anticoagulant class) + naproxen (nsaid class) — neither is
    # named directly in any rule, only via class membership.
    timeline = _timeline(
        [
            _med("Eliquis", ["apixaban"], source="a.pdf"),
            _med("Naprosyn", ["naproxen"], source="b.pdf"),
        ]
    )
    findings = check_known_interactions(timeline)
    assert len(findings) == 1
    assert findings[0]["severity"] == "high"


def test_single_combination_product_does_not_interact_with_itself():
    # One prescription line containing both sides of a rule must not be
    # flagged as a co-prescription interaction.
    timeline = _timeline(
        [
            _med("Combo", ["lisinopril", "spironolactone"], source="a.pdf"),
        ]
    )
    assert check_known_interactions(timeline) == []


def test_no_findings_for_unrelated_medications():
    timeline = _timeline(
        [
            _med("Paracetamol", ["paracetamol"], source="a.pdf"),
            _med("Cetirizine", ["cetirizine"], source="b.pdf"),
        ]
    )
    assert check_known_interactions(timeline) == []


def test_deduplicates_repeated_pairs():
    # The same two prescription lines must yield exactly one finding per
    # rule, not one per ingredient-combination permutation.
    timeline = _timeline(
        [
            _med("Warfarin", ["warfarin"], source="a.pdf"),
            _med("Ibuprofen", ["ibuprofen"], source="b.pdf"),
            _med("Ibuprofen", ["ibuprofen"], source="b.pdf"),  # exact same line duplicated
        ]
    )
    findings = check_known_interactions(timeline)
    assert len(findings) == 1


def test_merge_skips_pairs_the_llm_already_flagged():
    report = {
        "potential_drug_interactions": [
            {
                "medications_involved": ["warfarin", "ibuprofen"],
                "explanation": "LLM found it",
                "severity": "high",
                "confidence": 0.9,
            },
        ],
    }
    kb = [
        {
            "medications_involved": ["Warfarin", "Ibuprofen"],
            "explanation": "KB",
            "severity": "high",
            "confidence": 0.97,
            "source": "curated_knowledge_base",
            "rule": "x",
        },
        {
            "medications_involved": ["Sertraline", "Tramadol"],
            "explanation": "KB",
            "severity": "moderate",
            "confidence": 0.97,
            "source": "curated_knowledge_base",
            "rule": "y",
        },
    ]
    merged = merge_into_report(report, kb)
    interactions = merged["potential_drug_interactions"]
    assert len(interactions) == 2  # duplicate pair skipped, new pair appended
    assert interactions[1]["medications_involved"] == ["Sertraline", "Tramadol"]


def test_merge_into_empty_report_creates_key():
    merged = merge_into_report(
        {},
        [
            {
                "medications_involved": ["A", "B"],
                "explanation": "KB",
                "severity": "low",
                "confidence": 0.97,
                "source": "curated_knowledge_base",
                "rule": "z",
            },
        ],
    )
    assert len(merged["potential_drug_interactions"]) == 1


def test_cross_check_prescriptions_merges_kb_findings(monkeypatch):
    """The KB pass must land in the final report even when the LLM misses
    the interaction entirely."""
    os.environ.setdefault("GROQ_API_KEY", "gsk_test_123")
    import medical_extractor

    llm_report = (
        '{"potential_drug_interactions": [], "duplicate_prescriptions": [], '
        '"conflicting_dosage_instructions": [], "allergy_conflicts": [], '
        '"overall_recommendation": "Consult a professional."}'
    )
    monkeypatch.setattr(medical_extractor, "_completion_resilient", lambda **kwargs: llm_report)
    timeline = {
        "medications_timeline": [
            _med("Warfarin", ["warfarin"], source="a.pdf"),
            _med("Ibuprofen", ["ibuprofen"], source="b.pdf"),
        ],
        "known_allergies": [],
    }
    report = medical_extractor.cross_check_prescriptions(timeline)
    interactions = report["potential_drug_interactions"]
    assert len(interactions) == 1
    assert interactions[0]["source"] == "curated_knowledge_base"
    assert interactions[0]["severity"] == "high"
