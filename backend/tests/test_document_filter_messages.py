"""Rejection messages must not claim something the extraction never said.

The accept/reject DECISION coerces a missing or non-numeric confidence to
0.0 — that part is deliberate and unchanged. The MESSAGE used to print the
coerced value, so a document that reported no score at all was told
"overall_confidence=0.0" (as if the model had read it and scored it zero)
and a string score produced "overall_confidence=high is below 0.35". Both
send a user off to re-photograph a document for the wrong reason.

Run with: pytest tests/test_document_filter_messages.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from document_filter import (  # noqa: E402
    LOW_CONFIDENCE_THRESHOLD,
    looks_like_medical_document,
    rejection_reason,
)


def _empty(document_type, **extra):
    doc = {
        "document_type": document_type,
        "medications": [],
        "lab_results": [],
        "allergies_noted": [],
        "diagnoses_or_conditions": [],
    }
    doc.update(extra)
    return doc


def test_missing_score_is_not_reported_as_zero():
    reason = rejection_reason(_empty("prescription"))

    assert "no confidence score was reported" in reason
    assert "0.0" not in reason


def test_null_score_is_described_as_empty():
    reason = rejection_reason(_empty("prescription", overall_confidence=None))

    assert "came back empty" in reason
    assert "0.0" not in reason


def test_non_numeric_score_is_not_compared_against_the_threshold():
    reason = rejection_reason(_empty("prescription", overall_confidence="high"))

    assert "not a number" in reason
    # The nonsense "overall_confidence=high is below 0.35" must be gone.
    assert "is below" not in reason


def test_real_low_score_is_still_quoted_with_the_threshold():
    reason = rejection_reason(_empty("lab_report", overall_confidence=0.12))

    assert "0.12" in reason
    assert str(LOW_CONFIDENCE_THRESHOLD) in reason


def test_unrecognized_type_message_does_not_mention_confidence_at_all():
    """Confidence plays no part in that branch's decision, so quoting it
    only invited the user to fix the wrong thing."""
    reason = rejection_reason(_empty("other", overall_confidence=0.99))

    assert "classified as 'other'" in reason
    assert "confidence" not in reason


def test_boolean_score_is_treated_as_no_score_by_the_decision():
    # True would otherwise pass `isinstance(x, int)` and clear the threshold.
    doc = _empty("prescription", overall_confidence=True)

    assert looks_like_medical_document(doc) is False
    assert "not a number" in rejection_reason(doc)


def test_decision_still_accepts_a_confident_recognized_type():
    assert looks_like_medical_document(_empty("prescription", overall_confidence=0.9)) is True


def test_decision_still_rejects_a_missing_score():
    assert looks_like_medical_document(_empty("prescription")) is False
