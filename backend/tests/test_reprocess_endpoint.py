"""Tests for the per-document reprocess endpoint and its rebuild path."""

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

STORED_DOC = {
    "_document_id": "doc_test1",
    "document_type": "prescription",
    "content_sha256": "abc123",
    "document_url": "https://res.cloudinary.com/dummy/raw/upload/mediscan/u/rx.pdf",
    "cloudinary_public_id": "mediscan/u/rx",
    "_source": {"file": "rx.pdf", "method": "vision_ocr", "page": 1},
    "uploaded_at": "2026-08-01T00:00:00+00:00",
}

NEW_EXTRACTION = {
    "document_type": "prescription",
    "date": "2026-08-01",
    "provider_or_doctor": "Dr. Smith",
    "patient_name": "Test Patient",
    "medications": [{"name": "Amoxicillin", "ingredients": ["amoxicillin"], "confidence": 0.9}],
    "lab_results": [],
    "allergies_noted": [],
    "overall_confidence": 0.9,
    "_source": {"file": "rx.pdf", "method": "text_layer", "page": 1},
}

CROSS_CHECK = {
    "potential_drug_interactions": [],
    "duplicate_prescriptions": [],
    "conflicting_dosage_instructions": [],
    "allergy_conflicts": [],
    "overall_recommendation": "Consult a professional.",
    "reference_date": "2026-08-17",
    "medication_activity": {
        "reference_date": "2026-08-17",
        "active_medications": [],
        "inactive_medications": [],
        "active_count": 0,
        "inactive_count": 0,
    },
    "antidote_reference_notes": [],
}


def _auth_override():
    async def override_user():
        return "anon_reprocess_user"

    api.app.dependency_overrides[api.get_current_user] = override_user


def teardown_function():
    api.app.dependency_overrides.pop(api.get_current_user, None)


def _pipeline_patchers():
    patchers = [
        mock.patch.object(api.db, "load_documents", return_value=[dict(STORED_DOC)]),
        mock.patch.object(
            api.storage, "download_document_bytes", return_value=b"%PDF-1.4 original"
        ),
        mock.patch.object(api, "process_document", return_value=dict(NEW_EXTRACTION)),
        mock.patch.object(api.db, "replace_document_group", return_value=1),
        mock.patch.object(api, "_prepare_current_trust_state", return_value=([], [], {}, [])),
        mock.patch.object(api, "_derive_record", return_value=({}, dict(CROSS_CHECK), {})),
        mock.patch.object(api, "check_dosages", return_value={"findings": []}),
        mock.patch.object(api, "generate_consult_triage", return_value={}),
        mock.patch.object(api.db, "save_patient_snapshot"),
        mock.patch.object(api.db, "sync_conflicts", return_value=[]),
        mock.patch.object(api, "_replace_index", return_value=(True, None, 2)),
        mock.patch.object(api.audit, "record"),
        mock.patch.object(api.graph_db, "is_configured", lambda: False),
    ]
    for p in patchers:
        p.start()
    return patchers


def _reprocess(client, doc_id="doc_test1"):
    return client.post(f"/api/v1/documents/{doc_id}/reprocess")


def test_reprocess_replaces_and_rebuilds(monkeypatch):
    _auth_override()
    patchers = _pipeline_patchers()
    try:
        with TestClient(api.app) as client:
            resp = _reprocess(client)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["documents_reprocessed"] == 1
        assert body["document_id"] == "doc_test1"
        assert body["cross_check_report"]["overall_recommendation"] == "Consult a professional."
        assert body["indexed"] is True
        assert body["document_types"]["counts"]["prescription"] == 1
        # the stored row was replaced with the fresh extraction
        replace_call = api.db.replace_document_group.call_args
        assert replace_call.kwargs["content_sha256"] == "abc123"
        assert replace_call.kwargs["pages"][0]["document_url"] == STORED_DOC["document_url"]
    finally:
        for p in patchers:
            p.stop()


def test_reprocess_missing_document_404(monkeypatch):
    _auth_override()
    monkeypatch.setattr(api.db, "load_documents", lambda uid: [])
    with TestClient(api.app) as client:
        resp = _reprocess(client, doc_id="nope")
    assert resp.status_code == 404


def test_reprocess_download_failure_502(monkeypatch):
    _auth_override()
    monkeypatch.setattr(api.db, "load_documents", lambda uid: [dict(STORED_DOC)])
    monkeypatch.setattr(
        api.storage,
        "download_document_bytes",
        lambda doc, **_kwargs: (_ for _ in ()).throw(
            api.storage.StorageDownloadError("fetch failed")
        ),
    )
    with TestClient(api.app) as client:
        resp = _reprocess(client)
    assert resp.status_code == 502


def test_reprocess_invalid_content_422(monkeypatch):
    _auth_override()
    monkeypatch.setattr(api.db, "load_documents", lambda uid: [dict(STORED_DOC)])
    monkeypatch.setattr(
        api.storage, "download_document_bytes", lambda doc, **_kwargs: b"not a document"
    )
    with TestClient(api.app) as client:
        resp = _reprocess(client)
    assert resp.status_code == 422
    assert "actually" in resp.json()["detail"] or "supported" in resp.json()["detail"]


def test_reprocess_rejects_duplicate_in_flight_job(monkeypatch):
    """A second reprocess of the same document while the first is running
    must 409 rather than launching a second extraction pipeline."""
    import routes.upload as upload_routes

    _auth_override()
    upload_routes._active_document_jobs.clear()
    try:
        assert upload_routes.register_document_job("anon_reprocess_user", "doc_test1") is True
        assert upload_routes.register_document_job("anon_reprocess_user", "doc_test1") is False
        monkeypatch.setattr(api.db, "load_documents", lambda uid: [dict(STORED_DOC)])
        with TestClient(api.app) as client:
            resp = _reprocess(client)
        assert resp.status_code == 409
        assert "already being reprocessed" in resp.json()["detail"]
    finally:
        upload_routes.unregister_document_job("anon_reprocess_user", "doc_test1")
        api.app.dependency_overrides.pop(api.get_current_user, None)


def test_reprocess_extraction_failure_502(monkeypatch):
    _auth_override()
    patchers = _pipeline_patchers()
    for p in patchers:
        p.stop()
    monkeypatch.setattr(api.db, "load_documents", lambda uid: [dict(STORED_DOC)])
    monkeypatch.setattr(
        api.storage, "download_document_bytes", lambda doc, **_kwargs: b"%PDF-1.4 original"
    )
    monkeypatch.setattr(
        api,
        "process_document",
        lambda path: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    with TestClient(api.app) as client:
        resp = _reprocess(client)
    assert resp.status_code == 502
    assert "not changed" in resp.json()["detail"]
