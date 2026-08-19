"""Tests for the offline OCR text layer and its extraction integration.

The OCR engine itself (Tesseract) is an optional deployment dependency, so
engine-level tests exercise the module's decision logic with mocks; the
extraction-integration tests prove the fail-open contract: OCR never blocks
a document — it either takes the text path (when confident) or leaves the
vision path exactly as it was.
"""

import os
import sys
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import medical_extractor
import ocr_service

MINIMAL_EXTRACTION = {
    "document_type": "prescription",
    "_source": {"file": "scan.pdf", "method": "mock", "page": 1},
    "date": "2026-08-01",
    "provider_or_doctor": "Dr. Smith",
    "patient_name": "Test Patient",
    "medications": [
        {
            "name": "Amoxicillin 500mg",
            "ingredients": ["amoxicillin"],
            "dosage": "500 mg",
            "frequency": "3x daily",
            "dosage_value": 500,
            "dosage_unit": "mg",
            "frequency_per_day": 3,
            "confidence": 0.9,
        },
    ],
    "lab_results": [],
    "allergies_noted": [],
    "overall_confidence": 0.9,
}

MEDICAL_OCR_TEXT = (
    "City General Hospital\nPrescription\nPatient: Test Patient\n"
    "Amoxicillin 500 mg three times daily for 7 days.\nDr. Smith\n"
)


def _blank_pdf(path):
    import fitz

    doc = fitz.open()
    doc.new_page(width=595, height=842)  # no text layer -> needs vision/OCR
    doc.save(path)
    doc.close()


# ---------------------------------------------------------------------------
# Engine availability & error contract
# ---------------------------------------------------------------------------


def test_is_tesseract_available_returns_bool_and_never_raises(monkeypatch):
    monkeypatch.setattr(ocr_service.shutil, "which", lambda name: None)
    assert ocr_service.is_tesseract_available() is False


def test_missing_engine_raises_tesseract_not_found(monkeypatch):
    monkeypatch.setattr(ocr_service.shutil, "which", lambda name: None)
    try:
        ocr_service._require_tesseract()
    except ocr_service.TesseractNotFoundError:
        pass
    else:
        raise AssertionError("expected TesseractNotFoundError")


def test_transcript_usability_gates_on_confidence_and_length():
    def res(page, text, conf):
        return ocr_service.OCRPageResult(page=page, text=text, confidence=conf)

    usable, _joined, _avg = ocr_service.transcript_is_usable(
        [res(1, "a" * 200, 92.0)], min_chars=80
    )
    assert usable is True
    # low average confidence -> not trusted
    assert ocr_service.transcript_is_usable([res(1, "a" * 200, 30.0)], min_chars=80)[0] is False
    # too little text -> not trusted
    assert ocr_service.transcript_is_usable([res(1, "short", 95.0)], min_chars=80)[0] is False
    # no readable pages -> not trusted
    assert ocr_service.transcript_is_usable([res(1, "", None)], min_chars=80)[0] is False
    # missing confidence -> trusted on text alone (fail-open toward the
    # cheaper path only when text volume is real)
    assert ocr_service.transcript_is_usable([res(1, "a" * 200, None)], min_chars=80)[0] is True


# ---------------------------------------------------------------------------
# Extraction integration: OCR text path vs vision fallback
# ---------------------------------------------------------------------------


def test_confident_ocr_takes_text_path(tmp_path, monkeypatch):
    pdf = tmp_path / "scan.pdf"
    _blank_pdf(str(pdf))

    monkeypatch.setattr(medical_extractor, "is_tesseract_available", lambda: True)
    monkeypatch.setattr(
        medical_extractor,
        "ocr_pdf_pages",
        lambda path, indices: [
            ocr_service.OCRPageResult(page=1, text=MEDICAL_OCR_TEXT, confidence=93.0)
        ],
    )
    with (
        mock.patch.object(
            medical_extractor, "extract_from_text", return_value=dict(MINIMAL_EXTRACTION)
        ) as text_mock,
        mock.patch.object(medical_extractor, "extract_from_image") as vision_mock,
    ):
        result = medical_extractor.process_document(str(pdf))

    assert vision_mock.call_count == 0  # vision never consulted
    assert text_mock.call_count == 1
    assert result["_source"]["method"] == "ocr_text_layer"
    assert result["_source"]["ocr_confidence"] == 93.0
    assert result["_source"]["ocr_pages"] == [1]


def test_unavailable_ocr_keeps_vision_path(tmp_path, monkeypatch):
    pdf = tmp_path / "scan.pdf"
    _blank_pdf(str(pdf))

    monkeypatch.setattr(medical_extractor, "is_tesseract_available", lambda: False)
    with (
        mock.patch.object(medical_extractor, "extract_from_text") as text_mock,
        mock.patch.object(
            medical_extractor,
            "extract_from_image",
            return_value=dict(MINIMAL_EXTRACTION),
        ) as vision_mock,
    ):
        result = medical_extractor.process_document(str(pdf))

    assert text_mock.call_count == 0
    assert vision_mock.call_count == 1
    page = result["pages"][0] if result.get("multi_page") else result
    assert page["_source"]["method"] == "vision_ocr"


def test_low_confidence_ocr_keeps_vision_path(tmp_path, monkeypatch):
    pdf = tmp_path / "scan.pdf"
    _blank_pdf(str(pdf))

    monkeypatch.setattr(medical_extractor, "is_tesseract_available", lambda: True)
    monkeypatch.setattr(
        medical_extractor,
        "ocr_pdf_pages",
        lambda path, indices: [
            ocr_service.OCRPageResult(page=1, text=MEDICAL_OCR_TEXT, confidence=25.0)
        ],
    )
    with (
        mock.patch.object(medical_extractor, "extract_from_text") as text_mock,
        mock.patch.object(
            medical_extractor,
            "extract_from_image",
            return_value=dict(MINIMAL_EXTRACTION),
        ),
    ):
        result = medical_extractor.process_document(str(pdf))

    assert text_mock.call_count == 0
    page = result["pages"][0] if result.get("multi_page") else result
    assert page["_source"]["method"] == "vision_ocr"


def test_non_medical_ocr_text_keeps_vision_path(tmp_path, monkeypatch):
    pdf = tmp_path / "scan.pdf"
    _blank_pdf(str(pdf))

    monkeypatch.setattr(medical_extractor, "is_tesseract_available", lambda: True)
    monkeypatch.setattr(
        medical_extractor,
        "ocr_pdf_pages",
        lambda path, indices: [
            ocr_service.OCRPageResult(
                page=1,
                text="Curriculum vitae\nEducation\nWork Experience\nSkills\nReferences",
                confidence=96.0,
            )
        ],
    )
    with (
        mock.patch.object(medical_extractor, "extract_from_text") as text_mock,
        mock.patch.object(
            medical_extractor,
            "extract_from_image",
            return_value=dict(MINIMAL_EXTRACTION),
        ),
    ):
        result = medical_extractor.process_document(str(pdf))

    assert text_mock.call_count == 0  # never accepts a non-medical OCR read
    page = result["pages"][0] if result.get("multi_page") else result
    assert page["_source"]["method"] == "vision_ocr"


def test_ocr_failure_never_blocks_extraction(tmp_path, monkeypatch):
    """OCR raising inside the pre-pass must leave the vision path intact."""
    pdf = tmp_path / "scan.pdf"
    _blank_pdf(str(pdf))

    monkeypatch.setattr(medical_extractor, "is_tesseract_available", lambda: True)
    monkeypatch.setattr(
        medical_extractor,
        "ocr_pdf_pages",
        lambda path, indices: (_ for _ in ()).throw(ocr_service.InvalidPDFError("bad pdf")),
    )
    with mock.patch.object(
        medical_extractor, "extract_from_image", return_value=dict(MINIMAL_EXTRACTION)
    ):
        result = medical_extractor.process_document(str(pdf))
    page = result["pages"][0] if result.get("multi_page") else result
    assert page["_source"]["method"] == "vision_ocr"


def test_malformed_tesseract_rows_do_not_crash_ocr_image(monkeypatch):
    """Tesseract output arrays can carry blank/absent row fields; the row
    assembler must treat them as unreadable rather than raising."""

    class FakePytesseract:
        Output = type("Output", (), {"DICT": "dict"})

        def image_to_data(self, *args, **kwargs):
            return {
                "text": ["word1", "word2"],
                "conf": ["96", "-1"],
                "block_num": ["1", ""],  # blank where an int is expected
                "par_num": ["1", "1"],
                "line_num": ["1", "1"],
            }

    monkeypatch.setattr(ocr_service.shutil, "which", lambda name: "/usr/bin/tesseract")
    monkeypatch.setattr(ocr_service, "_require_tesseract", lambda: FakePytesseract())
    from PIL import Image

    img = Image.new("RGB", (40, 40), "white")
    result = ocr_service.ocr_image(img)
    # Crash-tolerance is the contract: a malformed row must not raise, and
    # both recognized words must survive (the blank field degrades to a
    # line break rather than killing the page).
    assert "word1" in result.text and "word2" in result.text
    assert result.confidence == 96.0


def test_ocr_evidence_quotes_are_attributed_to_their_page():
    """Multi-page OCR transcripts must not pin every quote to page 1."""
    from evidence import locate_ocr_text_evidence

    ocr_text = (
        "--- Page 1 ---\nCity General Hospital\nPrescription\n"
        "--- Page 2 ---\nAmoxicillin 500 mg three times daily for 7 days.\nDr. Smith\n"
    )
    document = {
        "field_evidence": {
            "provider_or_doctor": [
                {"quote": "Dr. Smith", "page": 1, "locator": "page_quote"},
            ],
            "clinical_notes": [
                {
                    "quote": "Amoxicillin 500 mg three times daily",
                    "page": 1,
                    "locator": "page_quote",
                },
            ],
        },
        "medications": [],
        "lab_results": [],
        "allergies_noted": [],
    }
    locate_ocr_text_evidence(ocr_text, document)

    provider = document["field_evidence"]["provider_or_doctor"][0]
    note = document["field_evidence"]["clinical_notes"][0]
    assert provider["page"] == 2
    assert provider["locator"] == "ocr_text_search"
    assert note["page"] == 2
    assert note["locator"] == "ocr_text_search"
    assert note["confidence"] == 0.7  # page attribution, not geometry


def test_ocr_evidence_quote_not_found_keeps_default_page():
    from evidence import locate_ocr_text_evidence

    ocr_text = "--- Page 1 ---\nCity General Hospital\nPrescription\n"
    document = {
        "field_evidence": {
            "provider_or_doctor": [
                {"quote": "Dr. Nowhere", "page": 1, "locator": "page_quote"},
            ],
        },
    }
    locate_ocr_text_evidence(ocr_text, document)
    region = document["field_evidence"]["provider_or_doctor"][0]
    assert region["page"] == 1  # unchanged — never guessed onto another page
    assert region["locator"] == "page_quote"


def test_ocr_quote_search_tolerates_ocr_line_breaks():
    """A quote split across OCR lines must still be located."""
    from evidence import locate_ocr_text_evidence

    ocr_text = "--- Page 1 ---\nAmoxicillin 500 mg three times\ndaily for 7 days.\n"
    document = {
        "field_evidence": {
            "clinical_notes": [
                {"quote": "Amoxicillin 500 mg three times daily for 7 days", "page": 1},
            ],
        },
    }
    locate_ocr_text_evidence(ocr_text, document)
    assert document["field_evidence"]["clinical_notes"][0]["page"] == 1
    assert document["field_evidence"]["clinical_notes"][0]["locator"] == "ocr_text_search"
