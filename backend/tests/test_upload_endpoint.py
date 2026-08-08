"""Offline tests for the /api/v1/documents upload endpoint.

Mocks the ML pipeline (process_document), storage, Supabase, and the
indexer so no network is involved. Verifies the response contract:
  - indexed=True when the indexer reports >0 chunks,
  - indexed=False + index_error when the indexer reports 0 chunks
    (the "No indexable content ... but indexed=True" contradiction).
"""
import os
import sys
import json
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ["GROQ_API_KEY"] = "gsk_test_123"
os.environ["SUPABASE_URL"] = "https://dummy.supabase.co"
os.environ["SUPABASE_SERVICE_ROLE_KEY"] = "dummy"
os.environ["CLOUDINARY_CLOUD_NAME"] = "dummy"
os.environ["CLOUDINARY_API_KEY"] = "dummy"
os.environ["CLOUDINARY_API_SECRET"] = "dummy"
os.environ["JWT_SECRET"] = "dummy"

from fastapi.testclient import TestClient  # noqa: E402

import api  # noqa: E402
import db  # noqa: E402


EXTRACTED_DOC = {
    "document_type": "prescription",
    "date": "2024-03-15",
    "provider_or_doctor": "Dr. Smith",
    "patient_name": "John Doe",
    "medications": [{
        "name": "Paracetamol", "ingredients": ["Paracetamol"], "dosage": "500 mg",
        "frequency": "3x daily", "duration": "5 days", "dosage_value": 500,
        "dosage_unit": "mg", "frequency_per_day": 3, "is_as_needed": False,
        "confidence": 0.95,
    }],
    "lab_results": [],
    "allergies_noted": [],
    "clinical_notes": None,
    "illegible_or_low_confidence_fields": [],
    "overall_confidence": 0.92,
}


def _make_client(index_chunks):
    """Build a TestClient with the ML pipeline / persistence mocked.

    index_chunks: what the mocked index_patient_timeline should return.
    """
    app = api.app

    async def override_user():
        return "anon_test_user"

    app.dependency_overrides[api.get_current_user] = override_user

    patchers = [
        mock.patch.object(api.storage, "upload_patient_document",
                          return_value={"document_url": "https://cloud/x.jpg",
                                        "cloudinary_public_id": "x"}),
        mock.patch.object(api.db, "load_documents", return_value=[]),
        mock.patch.object(api.db, "insert_documents"),
        mock.patch.object(api.db, "save_patient_snapshot"),
        mock.patch.object(api, "process_document", return_value=dict(EXTRACTED_DOC)),
        mock.patch.object(api, "cross_check_prescriptions", return_value={
            "potential_drug_interactions": [], "duplicate_prescriptions": [],
            "conflicting_dosage_instructions": [], "allergy_conflicts": [],
            "overall_recommendation": "Consult a professional.",
        }),
        mock.patch.object(api, "index_patient_timeline", return_value=index_chunks),
    ]
    for p in patchers:
        p.start()
    return app, patchers


def test_upload_indexed_true_when_chunks_exist():
    app, patchers = _make_client(index_chunks=2)
    try:
        with TestClient(app) as client:
            resp = client.post(
                "/api/v1/documents",
                files=[("files", ("rx.pdf", b"fake-pdf-bytes", "application/pdf"))],
            )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["indexed"] is True
        assert "index_error" not in body
        assert body["documents_added"] == 1
    finally:
        for p in patchers:
            p.stop()
        app.dependency_overrides.clear()


def test_upload_indexed_false_when_no_indexable_content():
    app, patchers = _make_client(index_chunks=0)
    try:
        with TestClient(app) as client:
            resp = client.post(
                "/api/v1/documents",
                files=[("files", ("rx.pdf", b"fake-pdf-bytes", "application/pdf"))],
            )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["indexed"] is False
        assert "no medications, lab results, clinical notes" in body["index_error"]
    finally:
        for p in patchers:
            p.stop()
        app.dependency_overrides.clear()


def test_index_exception_reports_indexed_false():
    app, patchers = _make_client(index_chunks=2)
    try:
        api.index_patient_timeline.side_effect = RuntimeError("chroma disk full")
        with TestClient(app) as client:
            resp = client.post(
                "/api/v1/documents",
                files=[("files", ("rx.pdf", b"fake-pdf-bytes", "application/pdf"))],
            )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["indexed"] is False
        assert body["index_error"] == "chroma disk full"
    finally:
        for p in patchers:
            p.stop()
        app.dependency_overrides.clear()


NON_MEDICAL_DOC = {
    "document_type": "other",
    "medications": [],
    "lab_results": [],
    "allergies_noted": [],
    "clinical_notes": None,
    "overall_confidence": 0.0,
}


def test_partial_batch_keeps_good_files_and_reports_failures():
    """One bad file must NOT kill the whole batch: the good file is merged,
    the request stays 201, and every failed file shows up in failed_files
    with its kind (not_medical / transient)."""
    from document_filter import NonMedicalDocumentError

    app, patchers = _make_client(index_chunks=2)
    try:
        api.process_document.side_effect = [
            dict(EXTRACTED_DOC),                                # good
            dict(NON_MEDICAL_DOC),                              # extraction ok but not medical
            NonMedicalDocumentError("cv.pdf", "raw text analysis indicates a CV"),
            RuntimeError("provider kept rate-limiting (HTTP 429)"),
        ]
        with TestClient(app) as client:
            resp = client.post(
                "/api/v1/documents",
                files=[
                    ("files", ("rx.pdf", b"fake-pdf", "application/pdf")),
                    ("files", ("receipt.jpg", b"fake-jpg", "image/jpeg")),
                    ("files", ("cv.pdf", b"fake-cv", "application/pdf")),
                    ("files", ("lab.jpg", b"fake-lab", "image/jpeg")),
                ],
            )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["documents_added"] == 1
        failed = body["failed_files"]
    finally:
        for p in patchers:
            p.stop()
        app.dependency_overrides.clear()
    by_file = {f["file"]: f for f in failed}
    assert set(by_file) == {"receipt.jpg", "cv.pdf", "lab.jpg"}, by_file
    assert by_file["receipt.jpg"]["kind"] == "not_medical"
    assert by_file["cv.pdf"]["kind"] == "not_medical"
    assert by_file["lab.jpg"]["kind"] == "transient"


def test_all_files_transient_failure_is_502():
    """Provider-side failure on every file -> retryable 502 (not a
    misleading 'not a medical document' 422)."""
    app, patchers = _make_client(index_chunks=2)
    try:
        api.process_document.side_effect = RuntimeError(
            "Model 'qwen/x' repeatedly failed to return valid structured JSON. "
            "Root cause hint: the provider rate-limited (HTTP 429) 5 attempt(s)"
        )
        with TestClient(app) as client:
            resp = client.post(
                "/api/v1/documents",
                files=[("files", ("a.jpg", b"a", "image/jpeg")), ("files", ("b.jpg", b"b", "image/jpeg"))],
            )
        assert resp.status_code == 502, resp.text
        assert "rate-limit" in resp.json()["detail"]
    finally:
        for p in patchers:
            p.stop()
        app.dependency_overrides.clear()


def test_async_job_exposes_independent_file_progress():
    """A parent job keeps one terminal row per input file and does not lose
    those rows when the parent advances to ready."""
    from document_filter import NonMedicalDocumentError

    app, patchers = _make_client(index_chunks=2)
    try:
        api.process_document.side_effect = [
            dict(EXTRACTED_DOC),
            NonMedicalDocumentError("notes.jpg", "no clinical content"),
        ]
        with TestClient(app) as client:
            queued = client.post(
                "/api/v1/documents?async=true",
                headers={"Prefer": "respond-async"},
                files=[
                    ("files", ("rx.pdf", b"fake-pdf", "application/pdf")),
                    ("files", ("notes.jpg", b"fake-jpg", "image/jpeg")),
                ],
            )
            assert queued.status_code == 202, queued.text
            job = client.get(f"/api/v1/jobs/{queued.json()['job_id']}")

        assert job.status_code == 200, job.text
        body = job.json()
        assert body["status"] == "completed"
        progress = body["progress"]
        assert progress["step"] == "ready"
        assert progress["total_files"] == 2
        assert progress["processed_files"] == 2
        assert progress["successful_files"] == 1
        assert progress["failed_files"] == 1
        by_name = {item["name"]: item for item in progress["files"]}
        assert by_name["rx.pdf"]["status"] == "completed"
        assert by_name["rx.pdf"]["step"] == "ready"
        assert by_name["notes.jpg"]["status"] == "failed"
        assert by_name["notes.jpg"]["error_code"] == "not_medical"
        assert "medical" in by_name["notes.jpg"]["error"].lower()
    finally:
        for patcher in patchers:
            patcher.stop()
        app.dependency_overrides.clear()


def test_hard_provider_quota_stops_queued_files_after_first_call():
    """A terminal provider quota opens the batch circuit breaker rather than
    sending every queued file into the same doomed request/retry ladder."""
    from medical_extractor import ProviderRateLimitError

    app, patchers = _make_client(index_chunks=2)
    try:
        api.process_document.side_effect = ProviderRateLimitError(
            provider="gemini",
            model="gemini-3.6-flash",
            hard_quota=True,
        )
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/documents",
                files=[
                    ("files", ("a.jpg", b"a", "image/jpeg")),
                    ("files", ("b.jpg", b"b", "image/jpeg")),
                    ("files", ("c.jpg", b"c", "image/jpeg")),
                ],
            )
        assert response.status_code == 502, response.text
        assert api.process_document.call_count == 1
        payload = response.json()
        detail = payload["detail"]
        assert payload["code"] == "provider_quota_exhausted"
        assert payload["retryable"] is False
        assert "no usable quota" in detail
        assert "structured JSON" not in detail
        assert "gemini-3.6-flash" not in detail
    finally:
        for patcher in patchers:
            patcher.stop()
        app.dependency_overrides.clear()


def test_all_files_non_medical_still_422():
    """Every file genuinely non-medical -> 422 with the per-file reason,
    same contract as before per-file resilience."""
    from document_filter import NonMedicalDocumentError

    app, patchers = _make_client(index_chunks=2)
    try:
        api.process_document.side_effect = [
            NonMedicalDocumentError("boarding.jpg", "classified as 'other' with no medications, lab results, or allergies found"),
            dict(NON_MEDICAL_DOC),
        ]
        with TestClient(app) as client:
            resp = client.post(
                "/api/v1/documents",
                files=[("files", ("boarding.jpg", b"a", "image/jpeg")), ("files", ("zoom.png", b"b", "image/png"))],
            )
        assert resp.status_code == 422, resp.text
        detail = resp.json()["detail"]
        assert "boarding.jpg" in detail and "zoom.png" in detail
    finally:
        for p in patchers:
            p.stop()
        app.dependency_overrides.clear()


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"\n{len(fns)} tests passed")
