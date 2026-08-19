"""Offline endpoint tests for the safety pipeline: identity guard on upload,
consult-triage / dosage-report endpoints, and snapshot enrichment."""

import os
import sys
from datetime import date, timedelta
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


def _extracted_doc(patient_name="John Doe", overdose=False):
    # Date-relative: the 5-day course must still be active when the safety
    # pipeline runs (activity scoping excludes provably ended courses), on
    # whatever day the test executes.
    doc_date = (date.today() - timedelta(days=2)).isoformat()
    return {
        "document_type": "prescription",
        "date": doc_date,
        "provider_or_doctor": "Dr. Smith",
        "patient_name": patient_name,
        "patient_age": 49,
        "patient_gender": "male",
        "document_language": "English",
        "additional_languages": [],
        "ocr_confidence": 0.95,
        "translation_confidence": 0.95,
        "medications": [
            {
                "name": "Paracetamol",
                "ingredients": ["Paracetamol"],
                "dosage": "1500 mg" if overdose else "500 mg",
                "frequency": "4x daily" if overdose else "3x daily",
                "duration": "5 days",
                "dosage_value": 1500 if overdose else 500,
                "dosage_unit": "mg",
                "frequency_per_day": 4 if overdose else 3,
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


CLEAN_CROSS_CHECK = {
    "potential_drug_interactions": [],
    "duplicate_prescriptions": [],
    "conflicting_dosage_instructions": [],
    "allergy_conflicts": [],
    "overall_recommendation": "Consult a professional.",
}


def _client_with_pipeline(extract_result, existing_docs=None):
    async def override_user():
        return "anon_safety_user"

    api.app.dependency_overrides[api.get_current_user] = override_user
    patchers = [
        mock.patch.object(
            api.storage,
            "upload_patient_document",
            return_value={"document_url": "https://cloud/x.pdf", "cloudinary_public_id": "x"},
        ),
        mock.patch.object(api.db, "load_documents", return_value=existing_docs or []),
        mock.patch.object(api.db, "insert_documents"),
        mock.patch.object(api.db, "save_patient_snapshot"),
        mock.patch.object(api, "process_document", return_value=extract_result),
        mock.patch.object(api, "cross_check_prescriptions", return_value=dict(CLEAN_CROSS_CHECK)),
        mock.patch.object(api, "index_patient_timeline", return_value=2),
        mock.patch.object(api.audit, "record"),
    ]
    for p in patchers:
        p.start()
    return patchers


def teardown_function():
    api.app.dependency_overrides.pop(api.get_current_user, None)


def _upload(client, filename="rx.pdf", confirm=False):
    data = {"confirm_identity_mismatch": "true"} if confirm else {}
    return client.post(
        "/api/v1/documents",
        files=[("files", (filename, b"%PDF-1.4 fake", "application/pdf"))],
        data=data,
    )


def test_upload_response_includes_safety_reports():
    patchers = _client_with_pipeline(_extracted_doc())
    try:
        with TestClient(api.app) as client:
            resp = _upload(client)
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["dosage_report"]["findings"] == []
        assert body["consult_triage"]["consult_needed"] is False
        assert body["translation_risk"]["flag"] == "none"
        assert "identity_review_needed" not in body
    finally:
        for p in patchers:
            p.stop()


def test_overdose_flows_from_dosage_rules_into_triage():
    patchers = _client_with_pipeline(_extracted_doc(overdose=True))
    try:
        with TestClient(api.app) as client:
            resp = _upload(client)
        assert resp.status_code == 201, resp.text
        body = resp.json()
        kinds = {f["kind"] for f in body["dosage_report"]["findings"]}
        assert "above_max_single_dose" in kinds
        assert "above_max_daily_dose" in kinds
        triage = body["consult_triage"]
        assert triage["consult_needed"] is True
        assert triage["consult_type"] == "doctor"
        assert triage["urgency"] == "urgent"
    finally:
        for p in patchers:
            p.stop()


def test_identity_mismatch_holds_document_with_409():
    existing = [
        {
            "patient_name": "Ramesh Kumar",
            "patient_age": 48,
            "patient_gender": "male",
            "date": "2023-05-01",
        }
    ]
    patchers = _client_with_pipeline(
        _extracted_doc(patient_name="Suresh Babu"), existing_docs=existing
    )
    try:
        with TestClient(api.app) as client:
            resp = _upload(client, filename="not_mine.pdf")
        assert resp.status_code == 409, resp.text
        assert "don't match" in resp.json()["detail"]
    finally:
        for p in patchers:
            p.stop()


def test_identity_mismatch_confirmed_proceeds():
    existing = [
        {
            "patient_name": "Ramesh Kumar",
            "patient_age": 48,
            "patient_gender": "male",
            "date": "2023-05-01",
        }
    ]
    patchers = _client_with_pipeline(
        _extracted_doc(patient_name="Suresh Babu"), existing_docs=existing
    )
    try:
        with TestClient(api.app) as client:
            resp = _upload(client, filename="not_mine.pdf", confirm=True)
        assert resp.status_code == 201, resp.text
        assert resp.json()["documents_added"] == 1
    finally:
        for p in patchers:
            p.stop()


def test_matching_identity_passes_without_confirmation():
    existing = [
        {
            "patient_name": "John Doe",
            "patient_age": 48,
            "patient_gender": "male",
            "date": "2023-05-01",
        }
    ]
    patchers = _client_with_pipeline(
        _extracted_doc(patient_name="John Doe"), existing_docs=existing
    )
    try:
        with TestClient(api.app) as client:
            resp = _upload(client)
        assert resp.status_code == 201, resp.text
        assert "identity_review_needed" not in resp.json()
    finally:
        for p in patchers:
            p.stop()


SNAPSHOT = {
    "patient_timeline": {
        "visits": [],
        "medications_timeline": [
            {
                "name": "Paracetamol",
                "ingredients": ["paracetamol"],
                "dosage_value": 1500,
                "dosage_unit": "mg",
                "frequency_per_day": 4,
                "is_as_needed": False,
                "date": "2024-03-15",
                "source_file": "rx.pdf",
            }
        ],
        "lab_results_timeline": [],
        "known_allergies": [],
    },
    "cross_check_report": dict(CLEAN_CROSS_CHECK),
    "lab_trends": {"trends": [], "insufficient_data": []},
    "updated_at": "2024-03-16T00:00:00+00:00",
}


def _plain_client():
    async def override_user():
        return "anon_safety_user"

    api.app.dependency_overrides[api.get_current_user] = override_user
    return TestClient(api.app)


def test_consult_triage_endpoint_recomputes_for_old_snapshots():
    with (
        mock.patch.object(api.db, "load_patient_snapshot", return_value=dict(SNAPSHOT)),
        mock.patch.object(api.db, "load_documents", return_value=[]),
        mock.patch.object(api.audit, "record"),
    ):
        with _plain_client() as client:
            resp = client.get("/api/v1/consult-triage")
        assert resp.status_code == 200, resp.text
        triage = resp.json()
        assert triage["consult_needed"] is True  # overdose in the snapshot
        assert triage["consult_type"] == "doctor"


def test_dosage_report_endpoint_recomputes_for_old_snapshots():
    with (
        mock.patch.object(api.db, "load_patient_snapshot", return_value=dict(SNAPSHOT)),
        mock.patch.object(api.db, "load_documents", return_value=[]),
        mock.patch.object(api.audit, "record"),
    ):
        with _plain_client() as client:
            resp = client.get("/api/v1/dosage-report")
        assert resp.status_code == 200, resp.text
        kinds = {f["kind"] for f in resp.json()["findings"]}
        assert "above_max_single_dose" in kinds


def test_patient_snapshot_includes_derived_safety_reports():
    with (
        mock.patch.object(api.db, "load_patient_snapshot", return_value=dict(SNAPSHOT)),
        mock.patch.object(api.db, "load_documents", return_value=[]),
        mock.patch.object(api.audit, "record"),
    ):
        with _plain_client() as client:
            resp = client.get("/api/v1/patient-snapshot")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert "dosage_report" in body
        assert "consult_triage" in body


def test_triage_endpoint_404_without_records():
    with (
        mock.patch.object(api.db, "load_patient_snapshot", return_value=None),
        mock.patch.object(api.db, "load_documents", return_value=[]),
    ):
        with _plain_client() as client:
            assert client.get("/api/v1/consult-triage").status_code == 404
            assert client.get("/api/v1/dosage-report").status_code == 404
