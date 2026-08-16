"""Offline tests for the identity guard (different-patient detection)."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from identity_guard import (  # noqa: E402
    build_identity_review,
    build_known_identity,
    check_batch_identity,
    _estimate_birth_year,
    _name_similarity,
)


def _doc(name, age=None, gender=None, date="2024-01-01"):
    return {"patient_name": name, "patient_age": age, "patient_gender": gender, "date": date}


# --- name similarity -------------------------------------------------------

def test_same_name_with_ocr_variance_matches():
    assert _name_similarity("Ramesh Kumar", "Ramesh Kumaar") > 0.85


def test_token_order_is_ignored():
    assert _name_similarity("Kumar Ramesh", "Ramesh Kumar") > 0.95


def test_honorifics_are_stripped():
    assert _name_similarity("Mr. Ramesh Kumar", "Ramesh Kumar") > 0.95


def test_different_people_score_low():
    assert _name_similarity("Suresh Babu", "Ramesh Kumar") < 0.55


def test_missing_name_is_not_evidence_of_mismatch():
    assert _name_similarity(None, "Ramesh Kumar") == 1.0


# --- birth-year estimation --------------------------------------------------

def test_birth_year_from_age_and_document_date():
    assert _estimate_birth_year(_doc("X", age=49, date="2024-03-15")) == 1975


def test_age_differences_across_years_are_consistent():
    # Same person: 45 on a 2020 document, 49 on a 2024 one.
    a = _estimate_birth_year(_doc("X", age=45, date="2020-06-01"))
    b = _estimate_birth_year(_doc("X", age=49, date="2024-06-01"))
    assert abs(a - b) <= 1


def test_absurd_age_is_ignored():
    assert _estimate_birth_year(_doc("X", age=250)) is None
    assert _estimate_birth_year(_doc("X", age=None)) is None


# --- batch checking against history ------------------------------------------

def test_matching_upload_proceeds():
    existing = [_doc("Ramesh Kumar", age=48, gender="male", date="2023-05-01")]
    result = check_batch_identity({"rx.pdf": [_doc("Ramesh Kumar", age=49, gender="male")]}, existing)
    assert result["accepted_files"] == ["rx.pdf"]
    assert result["held"] == []


def test_clearly_different_patient_is_held():
    existing = [_doc("Ramesh Kumar", age=48, gender="male", date="2023-05-01")]
    result = check_batch_identity({"other.pdf": [_doc("Suresh Babu", age=29, gender="male")]}, existing)
    assert result["accepted_files"] == []
    assert len(result["held"]) == 1
    held = result["held"][0]
    assert held["source_files"] == ["other.pdf"]
    assert any(s["field"] == "name" and s["severity"] == "strong" for s in held["signals"])


def test_partial_acceptance_not_all_or_nothing():
    existing = [_doc("Ramesh Kumar", age=48, gender="male", date="2023-05-01")]
    result = check_batch_identity({
        "mine.pdf": [_doc("Ramesh Kumar", age=49)],
        "not_mine.pdf": [_doc("Suresh Babu", age=29)],
    }, existing)
    assert result["accepted_files"] == ["mine.pdf"]
    assert len(result["held"]) == 1


def test_single_weak_signal_does_not_hold():
    # Borderline name spelling alone (weak, similarity ~0.72) must not hold
    # the document — it takes a strong signal or two weak ones.
    existing = [_doc("Ramesh Kumar", age=48, gender="male", date="2023-05-01")]
    result = check_batch_identity(
        {"rx.pdf": [_doc("Ramesh Coomer", gender="male")]}, existing
    )
    assert result["accepted_files"] == ["rx.pdf"], result["held"]


def test_two_weak_signals_together_hold():
    # Borderline name (~0.72, weak) + conflicting birth year (weak) => held.
    existing = [_doc("Ramesh Kumar", age=48, gender="male", date="2023-05-01")]
    result = check_batch_identity(
        {"rx.pdf": [_doc("Ramesh Coomer", age=20, date="2024-01-01")]}, existing
    )
    assert result["accepted_files"] == []
    assert len(result["held"]) == 1


def test_document_without_identity_fields_always_passes():
    existing = [_doc("Ramesh Kumar", age=48, gender="male", date="2023-05-01")]
    result = check_batch_identity({"labs.pdf": [_doc(None)]}, existing)
    assert result["accepted_files"] == ["labs.pdf"]


# --- new-account self-consistency --------------------------------------------

def test_first_upload_with_consistent_batch_accepts_everything():
    result = check_batch_identity({
        "a.pdf": [_doc("Ramesh Kumar")],
        "b.pdf": [_doc("Ramesh Kumaar")],  # OCR variance
    }, existing_docs=[])
    assert sorted(result["accepted_files"]) == ["a.pdf", "b.pdf"]
    assert result["held"] == []


def test_first_upload_with_disagreeing_batch_holds_minority_group():
    result = check_batch_identity({
        "a.pdf": [_doc("Ramesh Kumar")],
        "b.pdf": [_doc("Ramesh Kumar")],
        "c.pdf": [_doc("Suresh Babu")],
    }, existing_docs=[])
    assert sorted(result["accepted_files"]) == ["a.pdf", "b.pdf"]
    assert len(result["held"]) == 1
    assert result["held"][0]["source_files"] == ["c.pdf"]


# --- known identity + review block -------------------------------------------

def test_known_identity_aggregates_history():
    known = build_known_identity([
        _doc("Ramesh Kumar", age=48, gender="male", date="2023-05-01"),
        _doc("Ramesh Kumaar", age=49, gender="male", date="2024-05-01"),
    ])
    assert known["document_patient_names"] == ["Ramesh Kumar"]  # fuzzy-deduped
    assert known["gender"] == "male"
    assert known["estimated_birth_year"] == 1975


def test_review_block_mentions_confirmation_flag():
    review = build_identity_review(
        [{"patient_name": "Suresh Babu", "source_files": ["x.pdf"], "signals": [], "score": 2, "threshold": 2,
          "estimated_birth_year": None, "gender": None, "message": "m"}],
        {"document_patient_names": ["Ramesh Kumar"], "estimated_birth_year": None, "gender": None},
    )
    assert review["error"] == "patient_name_mismatch"
    assert "confirm_identity_mismatch=true" in review["message"]
