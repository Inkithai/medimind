"""Tests for _is_demo_document() placeholder detection across scripts.

The extraction prompt normalizes medication `ingredients` to the English
INN, but deliberately leaves `patient_name` and medication `name` exactly
as printed in the source language. An English-only marker check therefore
misses a demo/template page printed in Tamil or Sinhala — the common case
for a Sri Lanka deployment, where a missed template page gets ingested as
real patient data and pollutes the timeline, safety cross-check and trends.

These tests also pin the two mechanism properties that matter:
  * caseless matching via casefold() (not .upper(), a no-op for caseless
    scripts), and
  * word-boundary anchoring for space-delimited scripts, so a legitimate
    name that merely contains a marker's letters is NOT rejected — a false
    rejection of real patient data is worse than admitting a demo doc.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("GROQ_API_KEY", "gsk_test_123")

from medical_extractor import _is_demo_document  # noqa: E402


def _doc(patient_name=None, medications=None, source=None):
    doc = {
        "document_type": "prescription",
        "patient_name": patient_name,
        "medications": medications or [],
        "lab_results": [],
        "allergies_noted": [],
        "clinical_notes": None,
        "overall_confidence": 0.9,
    }
    if source is not None:
        doc["_source"] = source
    return doc


class TestStructuralMarker:
    def test_synthetic_source_method_is_a_demo_document(self):
        doc = _doc("jane doe", source={"file": "f.pdf", "method": "synthetic"})
        assert _is_demo_document(doc) is True

    def test_real_extraction_source_is_not(self):
        doc = _doc("jane doe", source={"file": "f.pdf", "method": "vision"})
        assert _is_demo_document(doc) is False

    def test_source_method_is_case_insensitive(self):
        doc = _doc("jane doe", source={"file": "f.pdf", "method": "SYNTHETIC"})
        assert _is_demo_document(doc) is True


class TestEnglishMarkers:
    @pytest.mark.parametrize("name", [
        "DEMO PATIENT", "Demo Patient", "demo patient",
        "SAMPLE", "Dummy", "placeholder", "Test Patient", "SPECIMEN",
    ])
    def test_english_placeholder_names_rejected(self, name):
        assert _is_demo_document(_doc(name)) is True

    def test_demo_medication_name_rejected(self):
        doc = _doc("jane doe", medications=[{"name": "DEMO MEDICINE", "ingredients": ["Metformin"]}])
        assert _is_demo_document(doc) is True

    def test_real_patient_kept(self):
        doc = _doc("Jane Doe", medications=[{"name": "Metformin", "ingredients": ["Metformin"]}])
        assert _is_demo_document(doc) is False


class TestMultilingualMarkers:
    """patient_name / medication name are never translated by the
    extractor, so these must be caught in their source script."""

    @pytest.mark.parametrize("name,script", [
        ("மாதிரி நோயாளி", "Tamil (sample patient)"),
        ("டெமோ", "Tamil (demo)"),
        ("නියැදිය", "Sinhala (sample)"),
        ("ආදර්ශ රෝගියා", "Sinhala (model patient)"),
        ("डेमो", "Hindi (demo)"),
        ("नमूना", "Hindi (sample)"),
        ("MUESTRA", "Spanish (sample)"),
        ("ejemplo", "Spanish (example)"),
        ("échantillon", "French (sample)"),
        ("ÉCHANTILLON", "French (sample, uppercase)"),
        ("عينة", "Arabic (sample)"),
        ("تجريبي", "Arabic (trial/demo)"),
        ("デモ", "Japanese (demo)"),
        ("サンプル", "Japanese (sample)"),
    ])
    def test_non_english_placeholder_rejected(self, name, script):
        assert _is_demo_document(_doc(name)) is True, f"missed {script}: {name}"

    def test_tamil_medication_placeholder_rejected(self):
        doc = _doc(
            "ஜேன் டோ",
            medications=[{"name": "மாதிரி", "ingredients": ["Metformin"]}],
        )
        assert _is_demo_document(doc) is True

    def test_real_tamil_prescription_kept(self):
        """A genuine Tamil prescription — name in Tamil script, ingredients
        normalized to English INN by the extractor — must NOT be rejected."""
        doc = _doc(
            "கமலா ராஜ்",
            medications=[
                {"name": "மெட்ஃபோர்மின்", "ingredients": ["Metformin"], "confidence": 0.88},
                {"name": "அம்லோடிபின்", "ingredients": ["Amlodipine"], "confidence": 0.85},
            ],
        )
        assert _is_demo_document(doc) is False

    def test_real_sinhala_prescription_kept(self):
        doc = _doc(
            "නිමල් පෙරේරා",
            medications=[{"name": "මෙට්ෆෝමින්", "ingredients": ["Metformin"]}],
        )
        assert _is_demo_document(doc) is False


class TestFalsePositiveGuards:
    """Rejecting a REAL document is worse than admitting a demo one, so
    markers are word-anchored for space-delimited scripts."""

    @pytest.mark.parametrize("name", [
        "Sampleton",        # contains "sample"
        "Demopoulos",       # contains "demo"
        "Muestras Rivera",  # Spanish surname containing "muestra"
        "Prudence Ejemplar",
    ])
    def test_names_merely_containing_a_marker_are_kept(self, name):
        assert _is_demo_document(_doc(name)) is False, f"false-rejected real name: {name}"

    def test_medication_containing_marker_substring_kept(self):
        # "Dummy" is a marker; "Dummyrol" is not a real drug but proves the
        # anchoring works on medication names too.
        doc = _doc("Jane Doe", medications=[{"name": "Sampleterol", "ingredients": ["Salmeterol"]}])
        assert _is_demo_document(doc) is False


class TestRobustness:
    def test_missing_fields_do_not_raise(self):
        assert _is_demo_document({}) is False

    def test_none_patient_name(self):
        assert _is_demo_document(_doc(None)) is False

    def test_non_dict_medication_entries_are_skipped(self):
        doc = _doc("Jane Doe", medications=["not a dict", None, 42])
        assert _is_demo_document(doc) is False

    def test_non_string_patient_name(self):
        assert _is_demo_document(_doc(12345)) is False
