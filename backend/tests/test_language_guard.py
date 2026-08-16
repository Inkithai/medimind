"""Offline tests for the language/translation guard."""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from language_guard import (  # noqa: E402
    LanguageNormalizationError,
    assert_language_normalized,
    assess_documents_translation_risk,
    assess_translation_risk,
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
