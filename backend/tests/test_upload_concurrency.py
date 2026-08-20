"""Per-user upload concurrency guard (regression tests).

Two concurrent uploads for one user used to each load the document history,
each rebuild the snapshot from "existing + own new docs", and each replace
the whole search index — last writer wins, so the OTHER batch could
silently vanish from the snapshot (safety analysis withheld until a manual
re-analysis) and from the index until the next self-healing reindex. The
upload endpoint now claims a per-user mutex for the whole pipeline (sync
and async paths), and the other record-mutating endpoints (corrections,
conflict changes, FHIR import, reprocess, delete, re-analysis) reject 409
while one is held.
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
from routes.records import (  # noqa: E402
    has_active_upload_pipeline,
    register_active_upload,
    unregister_active_upload,
)

USER = "anon_concurrency_user"

EXTRACTED_DOC = {
    "document_type": "prescription",
    "date": "2024-03-15",
    "provider_or_doctor": "Dr. Smith",
    "patient_name": "John Doe",
    "medications": [
        {
            "name": "Paracetamol",
            "ingredients": ["Paracetamol"],
            "dosage": "500 mg",
            "frequency": "3x daily",
            "duration": "5 days",
            "dosage_value": 500,
            "dosage_unit": "mg",
            "frequency_per_day": 3,
            "is_as_needed": False,
            "confidence": 0.95,
        }
    ],
    "lab_results": [],
    "allergies_noted": [],
    "clinical_notes": None,
    "illegible_or_low_confidence_fields": [],
    "overall_confidence": 0.92,
}


def _make_client(index_chunks=2):
    app = api.app

    async def override_user():
        return USER

    app.dependency_overrides[api.get_current_user] = override_user

    patchers = [
        mock.patch.object(
            api.storage,
            "upload_patient_document",
            return_value={"document_url": "https://cloud/x.pdf", "cloudinary_public_id": "x"},
        ),
        mock.patch.object(api.db, "load_documents", return_value=[]),
        mock.patch.object(api.db, "insert_documents"),
        mock.patch.object(api.db, "save_patient_snapshot"),
        mock.patch.object(api, "process_document", return_value=dict(EXTRACTED_DOC)),
        mock.patch.object(
            api,
            "cross_check_prescriptions",
            return_value={
                "potential_drug_interactions": [],
                "duplicate_prescriptions": [],
                "conflicting_dosage_instructions": [],
                "allergy_conflicts": [],
                "overall_recommendation": "Consult a professional.",
            },
        ),
        mock.patch.object(api, "index_patient_timeline", return_value=index_chunks),
    ]
    for p in patchers:
        p.start()
    return app, patchers


def test_sync_upload_releases_mutex_after_success():
    app, patchers = _make_client()
    try:
        with TestClient(app) as client:
            resp = client.post(
                "/api/v1/documents",
                files=[("files", ("rx.pdf", b"%PDF-1.4 fake-pdf-bytes", "application/pdf"))],
            )
        assert resp.status_code == 201, resp.text
    finally:
        for p in patchers:
            p.stop()
        app.dependency_overrides.clear()
    # The pipeline is over: a follow-up upload must be allowed.
    assert has_active_upload_pipeline(USER) is False


def test_sync_upload_releases_mutex_after_failure():
    app, patchers = _make_client()
    try:
        api.process_document.side_effect = ValueError("could not be parsed as json")
        with TestClient(app) as client:
            resp = client.post(
                "/api/v1/documents",
                files=[("files", ("rx.pdf", b"%PDF-1.4 fake-pdf-bytes", "application/pdf"))],
            )
        # No usable file -> 422, but the per-user claim must be released
        # either way or the user could never upload again this process.
        assert resp.status_code == 422, resp.text
    finally:
        for p in patchers:
            p.stop()
        app.dependency_overrides.clear()
    assert has_active_upload_pipeline(USER) is False


def test_upload_rejected_while_mutex_held():
    """A concurrent upload (or a crashed-then-retried one) gets a 409 with a
    clear wait message instead of racing the in-flight pipeline."""
    app, patchers = _make_client()
    register_active_upload(USER)
    try:
        assert register_active_upload(USER) is False, "second claim must fail"
        with TestClient(app) as client:
            resp = client.post(
                "/api/v1/documents",
                files=[("files", ("rx.pdf", b"%PDF-1.4 fake-pdf-bytes", "application/pdf"))],
            )
        assert resp.status_code == 409, resp.text
        assert "still processing" in resp.json()["detail"].lower()
        # The rejected request must not have consumed the held claim.
        assert has_active_upload_pipeline(USER) is True
    finally:
        unregister_active_upload(USER)
        for p in patchers:
            p.stop()
        app.dependency_overrides.clear()
    assert has_active_upload_pipeline(USER) is False


def test_async_upload_releases_mutex_when_job_completes():
    """The 202 path releases the claim in the background task, not in the
    endpoint (which returns before the pipeline has started)."""
    app, patchers = _make_client()
    try:
        with TestClient(app) as client:
            queued = client.post(
                "/api/v1/documents?async=true",
                headers={"Prefer": "respond-async"},
                files=[("files", ("rx.pdf", b"%PDF-1.4 fake-pdf-bytes", "application/pdf"))],
            )
            assert queued.status_code == 202, queued.text
            job_id = queued.json()["job_id"]
            # TestClient runs the background task as part of the request,
            # so by now the pipeline is finished and the claim released.
            job = client.get(f"/api/v1/jobs/{job_id}")
        assert job.status_code == 200, job.text
        assert job.json()["status"] == "completed"
    finally:
        for p in patchers:
            p.stop()
        app.dependency_overrides.clear()
    assert has_active_upload_pipeline(USER) is False


def test_async_upload_rejected_while_mutex_held():
    app, patchers = _make_client()
    register_active_upload(USER)
    try:
        with TestClient(app) as client:
            resp = client.post(
                "/api/v1/documents?async=true",
                headers={"Prefer": "respond-async"},
                files=[("files", ("rx.pdf", b"%PDF-1.4 fake-pdf-bytes", "application/pdf"))],
            )
        assert resp.status_code == 409, resp.text
        assert has_active_upload_pipeline(USER) is True
    finally:
        unregister_active_upload(USER)
        for p in patchers:
            p.stop()
        app.dependency_overrides.clear()


def test_corrections_rejected_while_upload_active():
    """A correction rebuilds the snapshot + index from the currently stored
    documents; racing it against an in-flight upload lets last-writer-wins
    drop one of the two. Same 409 contract as the other record mutations."""
    app, patchers = _make_client()
    register_active_upload(USER)
    try:
        with TestClient(app) as client:
            resp = client.post(
                "/api/v1/documents/doc_123/corrections",
                json={
                    "changes": [
                        {"field_path": "medications/0/name", "corrected_value": "Panadol"}
                    ],
                    "reason": "Correct the printed brand to the generic name.",
                },
            )
        assert resp.status_code == 409, resp.text
        assert "still being processed" in resp.json()["detail"].lower()
    finally:
        unregister_active_upload(USER)
        for p in patchers:
            p.stop()
        app.dependency_overrides.clear()


def test_fhir_import_rejected_while_upload_active():
    app, patchers = _make_client()
    register_active_upload(USER)
    try:
        with TestClient(app) as client:
            resp = client.post(
                "/api/v1/import/fhir",
                json={"bundle": {"resourceType": "Bundle", "entry": []}},
            )
        assert resp.status_code == 409, resp.text
    finally:
        unregister_active_upload(USER)
        for p in patchers:
            p.stop()
        app.dependency_overrides.clear()


def test_mutex_is_per_user():
    """One user's in-flight pipeline must not block another user's upload —
    the claim is scoped to the authenticated user_id."""
    assert register_active_upload(USER) is True
    assert register_active_upload("other_user") is True
    try:
        assert has_active_upload_pipeline(USER) is True
        assert has_active_upload_pipeline("other_user") is True
        unregister_active_upload("other_user")
    finally:
        unregister_active_upload(USER)
