"""Offline tests for the language/translation guard."""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from language_guard import (  # noqa: E402
    UNTRANSLATED_DOC_CONFIDENCE,
    UNTRANSLATED_MED_CONFIDENCE,
    LanguageNormalizationError,
    apply_language_degradation,
    assert_language_normalized,
    assess_documents_translation_risk,
    assess_translation_risk,
    detect_normalization_failures,
)


def _doc(medications=None, ocr=None, translation=None, language=None):
    return {
        "medications": medications or [],
        "ocr_confidence": ocr,
        "translation_confidence": translation,
        "document_language": language,
        "additional_languages": [],
    }


# --- hard rejection: only on demonstrated normalization failure --------------


def test_normalized_foreign_document_passes():
    # A Japanese prescription whose ingredient resolved to an INN passes.
    doc = _doc(
        medications=[{"name": "ロキソニン", "ingredients": ["Loxoprofen"]}],
        language="Japanese",
    )
    assert_language_normalized(doc, "japanese_rx.pdf")  # no raise


def test_non_latin_ingredient_is_rejected():
    # An "ingredient" still in the source script means normalization failed.
    doc = _doc(
        medications=[{"name": "ロキソニン", "ingredients": ["ロキソプロフェン"]}],
        language="Japanese",
    )
    with pytest.raises(LanguageNormalizationError) as err:
        assert_language_normalized(doc, "japanese_rx.pdf")
    assert "Japanese" in str(err.value)
    assert "japanese_rx.pdf" in str(err.value)


def test_non_latin_name_with_no_ingredient_is_rejected():
    doc = _doc(medications=[{"name": "アスピリン", "ingredients": []}])
    with pytest.raises(LanguageNormalizationError):
        assert_language_normalized(doc, "rx.pdf")


def test_latin_name_with_no_ingredient_passes():
    # Unresolved but readable — the LLM cross-check can still reason on it.
    doc = _doc(medications=[{"name": "Panadol", "ingredients": []}])
    assert_language_normalized(doc, "rx.pdf")


def test_document_without_medications_passes():
    assert_language_normalized(_doc(), "labs.pdf")


def test_accented_latin_ingredient_passes():
    doc = _doc(medications=[{"name": "Amoxicilina", "ingredients": ["Amoxicillin"]}])
    assert_language_normalized(doc, "spanish_rx.pdf")


# --- graded risk: OCR confidence x translation confidence --------------------


def test_no_confidence_metadata_stays_silent():
    risk = assess_translation_risk(_doc())
    assert risk["flag"] == "none"
    assert risk["advice"] is None
    assert risk["effective_confidence"] is None


def test_clean_document_flags_none():
    risk = assess_translation_risk(_doc(ocr=0.98, translation=0.95))
    assert risk["flag"] == "none"


def test_axes_multiply_each_passing_alone_can_still_flag():
    # 0.65 x 0.75 = 0.4875 -> high, though each axis alone looks tolerable.
    risk = assess_translation_risk(_doc(ocr=0.65, translation=0.75))
    assert risk["effective_confidence"] == pytest.approx(0.488, abs=0.001)
    assert risk["flag"] == "high"


def test_low_ocr_advises_clearer_scan():
    risk = assess_translation_risk(_doc(ocr=0.55, translation=0.95))
    assert risk["flag"] in ("review", "high")
    assert "clearer scan" in risk["advice"]


def test_low_translation_advises_pharmacist():
    risk = assess_translation_risk(_doc(ocr=0.98, translation=0.55))
    assert risk["flag"] in ("review", "high")
    assert "pharmacist" in risk["advice"]


def test_record_rollup_reports_worst_flag_and_only_flagged_docs():
    docs = [
        {**_doc(ocr=0.98, translation=0.95), "_source": {"file": "clean.pdf"}},
        {**_doc(ocr=0.60, translation=0.70), "_source": {"file": "risky.pdf"}},
    ]
    rollup = assess_documents_translation_risk(docs)
    assert rollup["flag"] == "high"
    assert len(rollup["documents"]) == 1
    assert rollup["documents"][0]["source_file"] == "risky.pdf"
    assert rollup["note"] is not None


def test_clean_record_rollup_is_silent():
    rollup = assess_documents_translation_risk([_doc(), _doc(ocr=0.95, translation=0.95)])
    assert rollup == {"flag": "none", "documents": [], "note": None}


# --- degraded acceptance: keep the usable half of a mixed-script document ----


def test_degradation_keeps_document_and_marks_only_the_unmatched_medication():
    """A prescription where one drug resolved and one did not must keep BOTH:
    rejecting the file used to throw away the medication that was usable."""
    doc = _doc(
        medications=[
            {"name": "Metformin", "ingredients": ["Metformin"], "confidence": 0.95},
            {"name": "ලොසාටන්", "ingredients": [], "confidence": 0.9},
        ],
        language="Sinhala",
    )

    result = apply_language_degradation(doc, "rx.jpg")

    assert result["degraded"] is True
    assert result["unmatched_medications"] == ["ලොසාටන්"]
    # The resolved medication is untouched and still cross-checkable.
    resolved, unmatched = doc["medications"]
    assert "cross_check_eligible" not in resolved
    assert resolved["confidence"] == 0.95
    # The unresolved one is kept, but marked as unable to take part.
    assert unmatched["cross_check_eligible"] is False
    assert "standard English name" in unmatched["unmatched_reason"]
    assert unmatched["confidence"] == UNTRANSLATED_MED_CONFIDENCE


def test_degradation_lowers_document_confidence_but_stays_above_the_filter_floor():
    """The degraded score must flag the document without making a later
    stage drop it as non-medical (document_filter's 0.35 threshold)."""
    from document_filter import LOW_CONFIDENCE_THRESHOLD, looks_like_medical_document

    doc = _doc(medications=[{"name": "アスピリン", "ingredients": []}])
    doc["document_type"] = "prescription"
    doc["overall_confidence"] = 0.95

    apply_language_degradation(doc, "rx.pdf")

    assert doc["overall_confidence"] == UNTRANSLATED_DOC_CONFIDENCE
    assert UNTRANSLATED_DOC_CONFIDENCE > LOW_CONFIDENCE_THRESHOLD
    assert looks_like_medical_document(doc) is True


def test_degradation_never_raises_a_confidence():
    doc = _doc(medications=[{"name": "アスピリン", "ingredients": [], "confidence": 0.1}])
    doc["overall_confidence"] = 0.2

    apply_language_degradation(doc, "rx.pdf")

    assert doc["overall_confidence"] == 0.2
    assert doc["medications"][0]["confidence"] == 0.1


def test_degradation_is_a_no_op_for_a_cleanly_translated_document():
    doc = _doc(
        medications=[{"name": "ロキソニン", "ingredients": ["Loxoprofen"], "confidence": 0.9}],
        language="Japanese",
    )
    doc["overall_confidence"] = 0.9

    result = apply_language_degradation(doc, "japanese_rx.pdf")

    assert result["degraded"] is False
    assert doc["overall_confidence"] == 0.9
    assert "translation_incomplete" not in doc
    assert "cross_check_eligible" not in doc["medications"][0]


def test_degradation_marks_a_medication_once_even_with_several_bad_ingredients():
    doc = _doc(
        medications=[{"name": "混合薬", "ingredients": ["アスピリン", "カフェイン"]}],
    )

    result = apply_language_degradation(doc, "rx.pdf")

    assert result["unmatched_medications"] == ["混合薬"]
    assert len(result["problems"]) == 2  # both ingredients are reported


def test_degradation_reports_the_document_languages_and_advice():
    doc = _doc(medications=[{"name": "アスピリン", "ingredients": []}], language="Japanese")

    result = apply_language_degradation(doc, "rx.pdf")

    assert result["languages"] == ["Japanese"]
    assert result["file"] == "rx.pdf"
    assert "cannot be compared" in result["message"]
    assert "generic" in result["advice"]
    assert doc["translation_incomplete"] is True


def test_detector_backs_both_the_refusal_and_the_degradation():
    """assert_language_normalized and apply_language_degradation must agree
    about what failed — they share one detector so they cannot drift."""
    doc = _doc(medications=[{"name": "アスピリン", "ingredients": []}])
    failures = detect_normalization_failures(doc)

    assert len(failures) == 1
    with pytest.raises(LanguageNormalizationError):
        assert_language_normalized(dict(doc), "rx.pdf")
    assert apply_language_degradation(doc, "rx.pdf")["degraded"] is True


def test_non_dict_medication_entries_do_not_crash_the_detector():
    doc = _doc(medications=["not a dict", None])
    assert detect_normalization_failures(doc) == []
    assert apply_language_degradation(doc, "rx.pdf")["degraded"] is False


def test_degraded_document_is_always_high_translation_risk():
    """A drug name left untranslated is demonstrated failure; the model's
    own (often high) translation_confidence must not override it."""
    doc = _doc(
        medications=[{"name": "アスピリン", "ingredients": []}],
        ocr=0.95,
        translation=0.95,
    )
    apply_language_degradation(doc, "rx.pdf")

    risk = assess_translation_risk(doc)

    assert risk["flag"] == "high"
    assert "generic" in (risk["advice"] or "")


def test_degraded_document_flags_the_record_banner():
    doc = _doc(medications=[{"name": "アスピリン", "ingredients": []}], ocr=0.95, translation=0.95)
    doc["_source"] = {"file": "rx.pdf"}
    apply_language_degradation(doc, "rx.pdf")

    summary = assess_documents_translation_risk([doc])

    assert summary["flag"] == "high"
    assert summary["documents"][0]["source_file"] == "rx.pdf"
    assert summary["documents"][0]["translation_incomplete"] is True


def test_clean_document_with_no_confidence_fields_stays_silent():
    # Unchanged behaviour: absence of metadata is still not evidence of risk.
    assert assess_translation_risk(_doc())["flag"] == "none"
