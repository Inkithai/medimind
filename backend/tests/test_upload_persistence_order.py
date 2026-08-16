"""Regression tests for the "records vanished after a Render OOM kill" bug.

Timeline of the production incident this file guards against:
  1. Six JPGs uploaded; all six extracted successfully (Gemini 200s).
  2. The pipeline built the timeline, ran the safety cross-check, then
     called index_patient_timeline() BEFORE writing to Supabase.
  3. Chroma downloaded the 79 MB ONNX MiniLM model and embedded every chunk
     in one shot; the container exceeded its memory limit and was killed.
  4. Because the process died inside indexing, db.insert_documents() and
     db.save_patient_snapshot() never ran. The user's dashboard was empty
     even though the logs said "+6 new, 6 total".

The invariant: the durable medical record is written FIRST, and the vector
index — derived data that can always be rebuilt — is written after. A crash
or exception during indexing may cost the search index; it must never cost
the record.
"""
import os
import sys
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

EMPTY_CROSS_CHECK = {
    "potential_drug_interactions": [], "duplicate_prescriptions": [],
    "conflicting_dosage_instructions": [], "allergy_conflicts": [],
    "overall_recommendation": "Consult a professional.",
}


def _make_client(index_side_effect=None, index_return=2):
    """TestClient with the ML pipeline / storage / Supabase mocked, plus a
    shared call-order log so tests can assert what ran before what."""
    app = api.app
    calls = []

    async def override_user():
        return "anon_test_user"

    app.dependency_overrides[api.get_current_user] = override_user

    def record(name, result=None, side_effect=None):
        def _inner(*args, **kwargs):
            calls.append(name)
            if side_effect is not None:
                raise side_effect
            return result
        return _inner

    patchers = [
        mock.patch.object(api.storage, "upload_patient_document",
                          return_value={"document_url": "https://cloud/x.jpg",
                                        "cloudinary_public_id": "x"}),
        mock.patch.object(api.db, "load_documents", return_value=[]),
        mock.patch.object(api.db, "insert_documents", side_effect=record("insert_documents")),
        mock.patch.object(api.db, "save_patient_snapshot", side_effect=record("save_patient_snapshot")),
        mock.patch.object(api, "process_document", return_value=dict(EXTRACTED_DOC)),
        mock.patch.object(api, "cross_check_prescriptions", return_value=dict(EMPTY_CROSS_CHECK)),
        mock.patch.object(api, "index_patient_timeline",
                          side_effect=record("index", result=index_return,
                                             side_effect=index_side_effect)),
    ]
    for p in patchers:
        p.start()
    return app, patchers, calls


def _upload(app):
    with TestClient(app) as client:
        return client.post(
            "/api/v1/documents",
            files=[("files", ("rx.pdf", b"fake-pdf-bytes", "application/pdf"))],
        )


def test_documents_are_persisted_before_indexing_runs():
    app, patchers, calls = _make_client()
    try:
        resp = _upload(app)
        assert resp.status_code == 201, resp.text
    finally:
        for p in patchers:
            p.stop()
        app.dependency_overrides.clear()

    assert "index" in calls and "insert_documents" in calls, calls
    assert calls.index("insert_documents") < calls.index("index"), calls
    assert calls.index("save_patient_snapshot") < calls.index("index"), calls


def test_indexing_crash_still_leaves_the_record_saved():
    """The exact production failure mode, minus the process kill: indexing
    blows up, and the upload still reports 201 with the record written."""
    app, patchers, calls = _make_client(index_side_effect=RuntimeError("onnxruntime died"))
    try:
        resp = _upload(app)
    finally:
        for p in patchers:
            p.stop()
        app.dependency_overrides.clear()

    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["indexed"] is False
    assert body["index_error_code"] == "indexing_failed"
    assert body["documents_added"] == 1
    # Persistence happened despite the indexing failure.
    assert "insert_documents" in calls and "save_patient_snapshot" in calls, calls


def test_memory_error_during_indexing_is_reported_as_memory_limit():
    """A MemoryError must be labelled so the UI can say "saved, search is
    catching up" instead of a generic failure — and must not 500."""
    app, patchers, calls = _make_client(index_side_effect=MemoryError())
    try:
        resp = _upload(app)
    finally:
        for p in patchers:
            p.stop()
        app.dependency_overrides.clear()

    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["indexed"] is False
    assert body["index_error_code"] == "memory_limit"
    assert "insert_documents" in calls, calls


def test_successful_upload_reports_no_index_error_code():
    app, patchers, _calls = _make_client()
    try:
        resp = _upload(app)
    finally:
        for p in patchers:
            p.stop()
        app.dependency_overrides.clear()

    body = resp.json()
    assert body["indexed"] is True
    assert "index_error_code" not in body
    assert "index_error" not in body


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"\n{len(fns)} tests passed")
