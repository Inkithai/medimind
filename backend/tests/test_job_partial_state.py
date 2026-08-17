"""Regression tests for failure-aware job states.

Before this change a job whose indexing stage died reported either a
generic "processing/indexing" that never advanced (the container was
killed) or a flat "ready" that hid the problem. Neither told the client the
one thing that matters: the medical record IS saved, only the derived
search index is missing.

The contract now:
  * step "saving"  — records are being written to the database.
  * step "indexing" with records_saved=True — durable write already done.
  * step "partial" — completed job, records saved, indexing did not finish,
    with {"stage": "indexing", "error": "memory_limit"|"indexing_failed",
    "files_completed": N, "indexing_completed": false}.
  * step "ready"   — everything, including the index, finished.
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
import jobs  # noqa: E402


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
    "overall_confidence": 0.92,
}

EMPTY_CROSS_CHECK = {
    "potential_drug_interactions": [], "duplicate_prescriptions": [],
    "conflicting_dosage_instructions": [], "allergy_conflicts": [],
    "overall_recommendation": "Consult a professional.",
}


def _make_client(index_side_effect=None, index_return=2):
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
        mock.patch.object(api, "cross_check_prescriptions", return_value=dict(EMPTY_CROSS_CHECK)),
        mock.patch.object(api, "index_patient_timeline",
                          side_effect=index_side_effect,
                          return_value=index_return),
    ]
    for p in patchers:
        p.start()
    return app, patchers


def _run_async_upload(app):
    with TestClient(app) as client:
        queued = client.post(
            "/api/v1/documents?async=true",
            headers={"Prefer": "respond-async"},
            files=[("files", ("rx.pdf", b"%PDF-1.4 fake-pdf", "application/pdf"))],
        )
        assert queued.status_code == 202, queued.text
        job_id = queued.json()["job_id"]
        job = client.get(f"/api/v1/jobs/{job_id}")
    return job_id, job


def test_memory_kill_during_indexing_ends_in_partial_not_failed():
    app, patchers = _make_client(index_side_effect=MemoryError())
    job_id = None
    try:
        job_id, job = _run_async_upload(app)
    finally:
        for p in patchers:
            p.stop()
        app.dependency_overrides.clear()
        if job_id:
            with jobs._JOBS_LOCK:
                jobs._JOBS.pop(job_id, None)

    assert job.status_code == 200, job.text
    body = job.json()
    # The upload itself succeeded — the job is completed, not failed.
    assert body["status"] == "completed"
    progress = body["progress"]
    assert progress["step"] == "partial", progress
    assert progress["stage"] == "indexing"
    assert progress["error"] == "memory_limit"
    assert progress["records_saved"] is True
    assert progress["indexing_completed"] is False
    assert progress["files_completed"] == 1
    # The saved record is still returned so the UI can render it immediately.
    assert body["result"]["indexed"] is False
    assert body["result"]["index_error_code"] == "memory_limit"
    assert body["result"]["documents_added"] == 1


def test_generic_indexing_failure_also_ends_in_partial():
    app, patchers = _make_client(index_side_effect=RuntimeError("chroma disk full"))
    job_id = None
    try:
        job_id, job = _run_async_upload(app)
    finally:
        for p in patchers:
            p.stop()
        app.dependency_overrides.clear()
        if job_id:
            with jobs._JOBS_LOCK:
                jobs._JOBS.pop(job_id, None)

    body = job.json()
    assert body["status"] == "completed"
    assert body["progress"]["step"] == "partial"
    assert body["progress"]["error"] == "indexing_failed"


def test_no_indexable_content_is_ready_not_partial():
    """Nothing retrievable in the documents is not a failure of indexing —
    there was simply nothing to index, so the job is fully ready."""
    app, patchers = _make_client(index_return=0)
    job_id = None
    try:
        job_id, job = _run_async_upload(app)
    finally:
        for p in patchers:
            p.stop()
        app.dependency_overrides.clear()
        if job_id:
            with jobs._JOBS_LOCK:
                jobs._JOBS.pop(job_id, None)

    body = job.json()
    assert body["status"] == "completed"
    assert body["progress"]["step"] == "ready", body["progress"]
    assert body["result"]["index_error_code"] == "no_indexable_content"


def test_successful_job_reports_ready_with_saved_metadata():
    app, patchers = _make_client()
    job_id = None
    try:
        job_id, job = _run_async_upload(app)
    finally:
        for p in patchers:
            p.stop()
        app.dependency_overrides.clear()
        if job_id:
            with jobs._JOBS_LOCK:
                jobs._JOBS.pop(job_id, None)

    body = job.json()
    assert body["status"] == "completed"
    progress = body["progress"]
    assert progress["step"] == "ready"
    assert body["result"]["indexed"] is True


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"\n{len(fns)} tests passed")
