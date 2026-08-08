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


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"\n{len(fns)} tests passed")
