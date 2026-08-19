"""Offline tests for audit logging and the /api/v1/export endpoint."""

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
import audit  # noqa: E402

SNAPSHOT = {
    "patient_timeline": {
        "visits": [],
        "medications_timeline": [
            {
                "name": "Metformin",
                "ingredients": ["metformin"],
                "dosage": "500 mg",
                "date": "2024-03-15",
                "source_file": "rx.pdf",
            },
        ],
        "lab_results_timeline": [],
        "known_allergies": [],
    },
    "cross_check_report": {"overall_recommendation": "Consult a professional."},
    "lab_trends": {"trends": [], "insufficient_data": []},
    "updated_at": "2024-03-16T00:00:00+00:00",
}


def _client():
    async def override_user():
        return "anon_export_user"

    api.app.dependency_overrides[api.get_current_user] = override_user
    return TestClient(api.app)


def teardown_function():
    api.app.dependency_overrides.pop(api.get_current_user, None)


def test_export_json_returns_native_envelope_and_audits():
    with (
        mock.patch.object(api.db, "load_patient_snapshot", return_value=dict(SNAPSHOT)),
        mock.patch.object(api.db, "load_documents", return_value=[]),
        mock.patch.object(api.audit, "record") as rec,
    ):
        with _client() as client:
            resp = client.get("/api/v1/export?format=json")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["format"] == "medimind-record-export"
        assert body["user_id"] == "anon_export_user"
        rec.assert_called_once_with("anon_export_user", "records.export", {"format": "json"})


def test_export_fhir_returns_bundle():
    with (
        mock.patch.object(api.db, "load_patient_snapshot", return_value=dict(SNAPSHOT)),
        mock.patch.object(api.db, "load_documents", return_value=[]),
    ):
        with _client() as client:
            resp = client.get("/api/v1/export?format=fhir")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["resourceType"] == "Bundle"
        types = {e["resource"]["resourceType"] for e in body["entry"]}
        assert {"Patient", "MedicationStatement", "Provenance"} <= types


def test_export_unknown_format_is_400():
    with (
        mock.patch.object(api.db, "load_patient_snapshot", return_value=dict(SNAPSHOT)),
        mock.patch.object(api.db, "load_documents", return_value=[]),
    ):
        with _client() as client:
            resp = client.get("/api/v1/export?format=csv")
        assert resp.status_code == 400


def test_export_without_record_is_404():
    with (
        mock.patch.object(api.db, "load_patient_snapshot", return_value=None),
        mock.patch.object(api.db, "load_documents", return_value=[]),
    ):
        with _client() as client:
            resp = client.get("/api/v1/export?format=json")
        assert resp.status_code == 404


def test_audit_record_swallows_supabase_failure():
    with mock.patch("db._get_client", side_effect=RuntimeError("supabase down")):
        # Must not raise.
        audit.record("u", "qa.ask", {"question_chars": 10})


def test_audit_record_inserts_event():
    fake_table = mock.MagicMock()
    fake_client = mock.MagicMock()
    fake_client.table.return_value = fake_table
    with mock.patch("db._get_client", return_value=fake_client):
        audit.record("u1", "documents.upload", {"file_count": 2})
    fake_client.table.assert_called_once_with("audit_log")
    inserted = fake_table.insert.call_args[0][0]
    assert inserted["user_id"] == "u1"
    assert inserted["action"] == "documents.upload"
    assert inserted["detail"] == {"file_count": 2}


def test_audit_disabled_is_noop():
    with mock.patch.object(audit, "AUDIT_ENABLED", False), mock.patch("db._get_client") as client:
        audit.record("u", "qa.ask", {})
        client.assert_not_called()
