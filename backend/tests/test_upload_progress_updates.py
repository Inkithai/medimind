"""Regression test: the per-file 'reading' progress event fired twice.

Deploy logs (2026-08-17) showed every file emitting two identical
``Job ... file N -> processing/reading`` updates ~400ms apart — one from
api.py's run_document() wrapper and one from process_document() itself.
Each duplicate wrote a redundant jobs-table row (an extra HTTP POST per
file) and doubled the log noise. process_document() owns the first event;
api.py must not pre-emit it.
"""

import os
import sys
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("GROQ_API_KEY", "gsk_test_123")
os.environ.setdefault("SUPABASE_URL", "https://dummy.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "dummy")
os.environ.setdefault("CLOUDINARY_CLOUD_NAME", "dummy")
os.environ.setdefault("CLOUDINARY_API_KEY", "dummy")
os.environ.setdefault("CLOUDINARY_API_SECRET", "dummy")
os.environ.setdefault("JWT_SECRET", "dummy")

from fastapi.testclient import TestClient  # noqa: E402

import api  # noqa: E402

EXTRACTED_DOC = {
    "document_type": "prescription",
    "date": "2024-03-15",
    "provider_or_doctor": "Dr. Smith",
    "patient_name": "John Doe",
    "medications": [],
    "lab_results": [],
    "allergies_noted": [],
    "clinical_notes": None,
    "overall_confidence": 0.92,
}

EMPTY_CROSS_CHECK = {
    "potential_drug_interactions": [],
    "duplicate_prescriptions": [],
    "conflicting_dosage_instructions": [],
    "allergy_conflicts": [],
    "overall_recommendation": "Consult a professional.",
}


def test_reading_step_emitted_once_per_file():
    app = api.app

    async def override_user():
        return "anon_test_user"

    progress_events = []

    def spy_update_file_progress(job_id, file_index, **kwargs):
        progress_events.append((file_index, kwargs.get("status"), kwargs.get("step")))

    def fake_process_document(path, progress_callback=None, **kwargs):
        # Mimic the real process_document(): it emits its OWN first event.
        if progress_callback:
            progress_callback("reading", "Opening and checking the document")
        return dict(EXTRACTED_DOC)

    app.dependency_overrides[api.get_current_user] = override_user
    patchers = [
        mock.patch.object(
            api.storage,
            "upload_patient_document",
            return_value={"document_url": "https://cloud/x.jpg", "cloudinary_public_id": "x"},
        ),
        mock.patch.object(api.db, "load_documents", return_value=[]),
        mock.patch.object(api.db, "insert_documents"),
        mock.patch.object(api.db, "save_patient_snapshot"),
        mock.patch.object(api, "process_document", side_effect=fake_process_document),
        mock.patch.object(api, "cross_check_prescriptions", return_value=dict(EMPTY_CROSS_CHECK)),
        mock.patch.object(api, "index_patient_timeline", return_value=2),
        mock.patch.object(api.jobs, "update_file_progress", side_effect=spy_update_file_progress),
    ]
    try:
        for p in patchers:
            p.start()
        with TestClient(app) as client:
            queued = client.post(
                "/api/v1/documents?async=true",
                headers={"Prefer": "respond-async"},
                files=[("files", ("rx.pdf", b"%PDF-1.4 fake-pdf", "application/pdf"))],
            )
            assert queued.status_code == 202, queued.text
            job_id = queued.json()["job_id"]
            job = client.get(f"/api/v1/jobs/{job_id}")
            assert job.status_code == 200, job.text
            assert job.json()["status"] == "completed", job.json()
    finally:
        for p in patchers:
            p.stop()
        app.dependency_overrides.clear()

    reading_events = [e for e in progress_events if e[2] == "reading"]
    assert len(reading_events) == 1, (
        f"expected exactly one 'reading' event for the file, got {progress_events}"
    )
    # And it must be a 'processing/reading' event, not a failure variant.
    assert reading_events[0] == (1, "processing", "reading")
