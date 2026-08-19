"""Tests for upload content validation (magic-byte sniffing)."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from upload_validation import detect_content_kind, validate_upload_content  # noqa: E402

PDF = b"%PDF-1.7\nreal-ish"
PNG = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF"
WEBP = b"RIFF\x24\x00\x00\x00WEBPVP8 "


def test_detect_kinds():
    assert detect_content_kind(PDF) == "pdf"
    assert detect_content_kind(PNG) == "png"
    assert detect_content_kind(JPEG) == "jpeg"
    assert detect_content_kind(WEBP) == "webp"


def test_detect_rejects_unknown_and_empty():
    assert detect_content_kind(b"") is None
    assert detect_content_kind(b"hello world") is None
    assert detect_content_kind(b"MZ\x90\x00") is None  # an executable, not a doc


def test_webp_requires_the_webp_tag():
    # A RIFF container that is NOT webp (e.g. a .wav) must not pass as webp.
    assert detect_content_kind(b"RIFF\x24\x00\x00\x00WAVEfmt ") is None


def test_valid_file_passes():
    assert validate_upload_content(PDF, "rx.pdf") is None
    assert validate_upload_content(JPEG, "photo.jpg") is None
    assert validate_upload_content(PNG, "scan.png") is None
    assert validate_upload_content(WEBP, "scan.webp") is None


def test_empty_file_rejected():
    msg = validate_upload_content(b"", "rx.pdf")
    assert msg and "empty" in msg


def test_mismatched_extension_rejected():
    msg = validate_upload_content(JPEG, "rx.pdf")
    assert msg and "actually JPEG" in msg
    msg = validate_upload_content(PDF, "photo.jpg")
    assert msg and "actually PDF" in msg


def test_unknown_content_rejected():
    msg = validate_upload_content(b"hello world", "rx.pdf")
    assert msg and "supported document type" in msg


def test_unsupported_extension_rejected():
    msg = validate_upload_content(PDF, "notes.txt")
    assert msg and "unsupported file extension" in msg


# ---------------------------------------------------------------------------
# Upload pipeline: one bad file is rejected per-file, the batch continues
# ---------------------------------------------------------------------------


def test_pipeline_rejects_mismatched_content_per_file():
    import os as _os
    from unittest import mock

    _os.environ.setdefault("GROQ_API_KEY", "gsk_test_123")
    _os.environ.setdefault("SUPABASE_URL", "https://dummy.supabase.co")
    _os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "dummy")
    _os.environ.setdefault("CLOUDINARY_CLOUD_NAME", "dummy")
    _os.environ.setdefault("CLOUDINARY_API_KEY", "dummy")
    _os.environ.setdefault("CLOUDINARY_API_SECRET", "dummy")
    _os.environ.setdefault("JWT_SECRET", "dummy")

    from fastapi.testclient import TestClient

    import api

    EXTRACTED = {
        "document_type": "prescription",
        "date": "2026-08-01",
        "provider_or_doctor": "Dr. Smith",
        "patient_name": "Test Patient",
        "medications": [],
        "lab_results": [],
        "allergies_noted": [],
        "overall_confidence": 0.9,
        "_source": {"file": "good.pdf", "method": "text_layer", "page": 1},
    }
    CLEAN = {
        "potential_drug_interactions": [],
        "duplicate_prescriptions": [],
        "conflicting_dosage_instructions": [],
        "allergy_conflicts": [],
        "overall_recommendation": "Consult a professional.",
    }

    async def override_user():
        return "anon_validation_user"

    api.app.dependency_overrides[api.get_current_user] = override_user
    patchers = [
        mock.patch.object(
            api.storage,
            "upload_patient_document",
            return_value={"document_url": "https://cloud/x.pdf", "cloudinary_public_id": "x"},
        ),
        mock.patch.object(api.db, "load_documents", return_value=[]),
        mock.patch.object(api.db, "insert_documents"),
        mock.patch.object(api.db, "save_patient_snapshot"),
        mock.patch.object(api, "process_document", return_value=dict(EXTRACTED)),
        mock.patch.object(api, "cross_check_prescriptions", return_value=dict(CLEAN)),
        mock.patch.object(api, "index_patient_timeline", return_value=2),
        mock.patch.object(api.audit, "record"),
        mock.patch.object(api.graph_db, "is_configured", lambda: False),
    ]
    for p in patchers:
        p.start()
    try:
        with TestClient(api.app) as client:
            resp = client.post(
                "/api/v1/documents",
                files=[
                    ("files", ("good.pdf", b"%PDF-1.4 good", "application/pdf")),
                    ("files", ("bad.pdf", b"hello world", "application/pdf")),
                ],
            )
        api.app.dependency_overrides.pop(api.get_current_user, None)
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["files_added"] == 1
        failed = {f["file"]: f for f in body["failed_files"]}
        assert "bad.pdf" in failed
        assert failed["bad.pdf"]["code"] == "invalid_file_content"
        assert failed["bad.pdf"]["retryable"] is False
        assert api.process_document.call_count == 1  # bad file never extracted
    finally:
        api.app.dependency_overrides.pop(api.get_current_user, None)
        for p in patchers:
            p.stop()


def test_pdf_with_leading_bom_is_accepted():
    # The PDF spec allows the %PDF header anywhere in the first 1024 bytes;
    # real-world PDFs with a leading BOM must not be rejected.
    bom_pdf = b"\xef\xbb\xbf%PDF-1.7\n1 0 obj\n"
    assert detect_content_kind(bom_pdf) == "pdf"
    assert validate_upload_content(bom_pdf, "rx.pdf") is None


def test_pdf_header_past_first_1024_bytes_still_rejected():
    junk = b"x" * 1100 + b"%PDF-1.7"
    assert detect_content_kind(junk) is None
