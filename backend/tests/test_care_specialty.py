"""Safety tests for evidence-graded specialty suggestion.

The core rule under test: low-confidence / ambiguous evidence must NEVER
produce a specific specialty. Only explicit, high-confidence documented
evidence may surface one — and even then only as a possible
directory-search category, never as advice.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from care.specialty import (  # noqa: E402
    EVIDENCE_MODERATE,
    EVIDENCE_NONE,
    EVIDENCE_STRONG,
    EVIDENCE_WEAK,
    GENERAL_MEDICINE,
    suggest_specialty,
)


def _visit(notes, confidence=0.9, **extra):
    return {"clinical_notes": notes, "overall_confidence": confidence, **extra}


# -- Weak evidence must not become a specialty -------------------------------

def test_isolated_digest_word_with_low_confidence_yields_no_specialty():
    suggestion = suggest_specialty([_visit("patient reports digest issue", confidence=0.2)])
    assert suggestion.specialty is None
    assert suggestion.evidence_level == EVIDENCE_WEAK
    assert suggestion.headline == "No specific specialty identified"
    assert "not sufficient" in suggestion.explanation
    assert suggestion.search_options[0] == GENERAL_MEDICINE


def test_isolated_digest_word_even_at_high_confidence_yields_no_specialty():
    # "digest" alone is ambiguous regardless of OCR confidence.
    suggestion = suggest_specialty([_visit("digest", confidence=0.95)])
    assert suggestion.specialty is None
    assert suggestion.evidence_level == EVIDENCE_WEAK


def test_single_moderate_symptom_alone_is_not_enough():
    suggestion = suggest_specialty([_visit("patient reports heartburn", confidence=0.9)])
    assert suggestion.specialty is None
    assert suggestion.evidence_level == EVIDENCE_WEAK


def test_low_confidence_document_downgrades_even_explicit_terms():
    # A garbled scan that "mentions" gastritis must stay weak evidence.
    suggestion = suggest_specialty([_visit("gastritis ??? illegible", confidence=0.1)])
    assert suggestion.specialty is None
    assert suggestion.evidence_level == EVIDENCE_WEAK


def test_no_evidence_yields_none_level_with_general_medicine_option():
    suggestion = suggest_specialty([_visit("routine checkup, all normal", confidence=0.9)])
    assert suggestion.specialty is None
    assert suggestion.evidence_level == EVIDENCE_NONE
    assert GENERAL_MEDICINE in suggestion.search_options


def test_empty_records_are_handled():
    suggestion = suggest_specialty([])
    assert suggestion.specialty is None
    assert suggestion.evidence_level == EVIDENCE_NONE


# -- Moderate evidence: possible category, user chooses ----------------------

def test_multiple_related_symptoms_surface_possible_category_only():
    suggestion = suggest_specialty(
        [_visit("persistent vomiting and abdominal pain for two weeks", confidence=0.9)]
    )
    assert suggestion.evidence_level == EVIDENCE_MODERATE
    assert suggestion.specialty == "Gastroenterology"
    assert suggestion.headline.startswith("Possible specialty match")
    assert "not as a diagnosis" in suggestion.explanation
    assert suggestion.search_options[0] == GENERAL_MEDICINE
    assert "Gastroenterology" in suggestion.search_options


def test_conflicting_moderate_evidence_reduces_specificity():
    suggestion = suggest_specialty(
        [
            _visit("abdominal pain and heartburn", confidence=0.9),
            _visit("chest pain and palpitations", confidence=0.9),
        ]
    )
    assert suggestion.specialty is None
    assert suggestion.headline == "No specific specialty identified"
    assert GENERAL_MEDICINE in suggestion.search_options


# -- Strong evidence: possible relevant specialty, still not advice ----------

def test_documented_diagnosis_surfaces_possible_specialty():
    suggestion = suggest_specialty(
        [_visit("Diagnosis: peptic ulcer disease. Endoscopy performed.", confidence=0.92)]
    )
    assert suggestion.evidence_level == EVIDENCE_STRONG
    assert suggestion.specialty == "Gastroenterology"
    assert "not a diagnosis" in suggestion.explanation


def test_explicit_referral_is_strong_evidence():
    suggestion = suggest_specialty(
        [_visit("Patient referred to gastroenterology clinic for review", confidence=0.9)]
    )
    assert suggestion.evidence_level == EVIDENCE_STRONG
    assert suggestion.specialty == "Gastroenterology"


def test_referral_in_low_confidence_document_is_ignored():
    suggestion = suggest_specialty(
        [_visit("referred to gastroenterology (illegible)", confidence=0.2)]
    )
    assert suggestion.evidence_level == EVIDENCE_WEAK
    assert suggestion.specialty is None


# -- Wording safety -----------------------------------------------------------

def test_no_output_contains_directive_medical_advice():
    cases = [
        [],
        [_visit("digest", confidence=0.2)],
        [_visit("abdominal pain and blood in stool", confidence=0.9)],
        [_visit("Diagnosis: Crohn disease", confidence=0.95)],
    ]
    banned = [
        "you need a",
        "you need to",
        "go to a",
        "we recommend",
        "medimind recommends",
        "best for you",
        "must see",
        "professional review suggested",
    ]
    for visits in cases:
        suggestion = suggest_specialty(visits)
        combined = " ".join(
            filter(None, [suggestion.headline, suggestion.explanation, suggestion.hint or "", suggestion.disclaimer])
        ).lower()
        for phrase in banned:
            assert phrase not in combined, f"banned phrase {phrase!r} in {combined!r}"


def test_every_suggestion_offers_general_medicine_first():
    for visits in ([], [_visit("digest", confidence=0.3)], [_visit("gastritis", confidence=0.9)]):
        suggestion = suggest_specialty(visits)
        assert suggestion.search_options[0] == GENERAL_MEDICINE


if __name__ == "__main__":
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_")]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"\n{len(tests)} tests passed")
