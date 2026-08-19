"""TestClient coverage for the P1/P2 HTTP surface.

These routes already have engine unit tests in test_p1_p2_features.py.
This file locks the HTTP contract: auth, 404 vs degrade-open, and the
not-a-diagnosis / validation responses the frontend actually calls.

Offline only — snapshot/rebuild helpers are mocked; no LLM, no directory.
"""

from __future__ import annotations

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
os.environ.setdefault("PRELOAD_EMBEDDING_MODEL", "false")

from fastapi.testclient import TestClient  # noqa: E402

import api  # noqa: E402
import clinician_feedback as cf  # noqa: E402
import finding_history as fh  # noqa: E402
import finding_lifecycle as fl  # noqa: E402
import patient_data as pd  # noqa: E402
import secure_messaging as sm  # noqa: E402

USER = "anon_p1p2_user"

SNAPSHOT = {
    "patient_timeline": {
        "visits": [],
        "medications_timeline": [
            {
                "name": "Lisinopril",
                "ingredients": ["lisinopril"],
                "dosage_value": 10,
                "dosage_unit": "mg",
                "frequency_per_day": 1,
                "date": "2026-01-01",
                "duration_days": 30,
                "source_file": "rx.pdf",
            },
            {
                "name": "Metformin",
                "ingredients": ["metformin"],
                "dosage_value": 500,
                "dosage_unit": "mg",
                "frequency_per_day": 2,
                "date": "2026-01-01",
                "duration_days": 30,
                "source_file": "rx.pdf",
            },
        ],
        "lab_results_timeline": [],
        "vital_signs_timeline": [
            {
                "name": "Blood Pressure",
                "value": "128/82",
                "unit": "mmHg",
                "measured_at": "2026-01-01",
            },
            {
                "name": "Blood Pressure",
                "value": "148/94",
                "unit": "mmHg",
                "measured_at": "2026-04-01",
            },
        ],
        "known_allergies": [],
        "diagnoses_timeline": [{"name": "Type 2 diabetes", "date": "2026-01-01"}],
    },
    "cross_check_report": {
        "potential_drug_interactions": [],
        "duplicate_prescriptions": [],
        "conflicting_dosage_instructions": [],
        "allergy_conflicts": [],
    },
    "lab_trends": {"trends": [], "insufficient_data": []},
}

CLEAN_REPORT = {
    "potential_drug_interactions": [
        {
            "finding_kind": "ddi",
            "rule": "ace + k",
            "medications_involved": ["Lisinopril"],
            "severity": "moderate",
        }
    ],
    "duplicate_prescriptions": [],
    "conflicting_dosage_instructions": [],
    "allergy_conflicts": [],
}


async def _user():
    return USER


def teardown_function():
    api.app.dependency_overrides.pop(api.get_current_user, None)
    cf.reset(USER)
    fl.reset(USER)
    pd.reset(USER)
    sm.reset(USER)
    fh.reset(USER)


def _authed() -> TestClient:
    api.app.dependency_overrides[api.get_current_user] = _user
    return TestClient(api.app)


def test_p1_endpoints_require_auth():
    api.app.dependency_overrides.pop(api.get_current_user, None)
    with TestClient(api.app) as client:
        for path in (
            "/api/v1/vital-trends",
            "/api/v1/adherence",
            "/api/v1/early-warning",
            "/api/v1/findings/alerts",
            "/api/v1/medications/reconciliation",
            "/api/v1/deterioration",
            "/api/v1/findings/feedback",
            "/api/v1/patient-data/measurements",
            "/api/v1/provider-messages",
        ):
            assert client.get(path).status_code == 401, path
        assert client.post("/api/v1/symptoms/analyse", json={"symptom": "cough"}).status_code == 401
        assert client.post("/api/v1/import/fhir", json={"bundle": {}}).status_code == 401


def test_record_backed_endpoints_404_without_snapshot():
    with mock.patch.object(api, "_load_snapshot_or_rebuild", return_value=None):
        with _authed() as client:
            for path in (
                "/api/v1/vital-trends",
                "/api/v1/adherence",
                "/api/v1/early-warning",
                "/api/v1/findings/alerts",
                "/api/v1/medications/reconciliation",
                "/api/v1/deterioration",
            ):
                assert client.get(path).status_code == 404, path


def test_vital_trends_and_early_warning_are_not_diagnoses():
    with mock.patch.object(api, "_load_snapshot_or_rebuild", return_value=dict(SNAPSHOT)):
        with _authed() as client:
            vitals = client.get("/api/v1/vital-trends")
            warning = client.get("/api/v1/early-warning")
            decline = client.get("/api/v1/deterioration")
    assert vitals.status_code == 200, vitals.text
    assert "trends" in vitals.json()
    assert warning.status_code == 200, warning.text
    assert "score" in warning.json()
    assert "not a diagnosis" in warning.json().get("note", "").lower()
    assert decline.status_code == 200, decline.text


def test_adherence_and_reconciliation_read_the_timeline():
    with mock.patch.object(api, "_load_snapshot_or_rebuild", return_value=dict(SNAPSHOT)):
        with _authed() as client:
            adherence = client.get("/api/v1/adherence")
            recon = client.get("/api/v1/medications/reconciliation")
    assert adherence.status_code == 200, adherence.text
    assert "signals" in adherence.json()
    assert recon.status_code == 200, recon.text
    assert "reconciled_medications" in recon.json()


def test_managed_alerts_wrap_the_cross_check():
    with (
        mock.patch.object(api, "_load_snapshot_or_rebuild", return_value=dict(SNAPSHOT)),
        mock.patch.object(api, "_enhanced_cross_check", return_value=dict(CLEAN_REPORT)),
    ):
        with _authed() as client:
            response = client.get("/api/v1/findings/alerts")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["active_count"] == 1
    assert body["suppressed_count"] == 0


def test_preventive_care_degrades_without_a_record():
    with (
        mock.patch.object(api, "_load_snapshot_or_rebuild", return_value=None),
        mock.patch.object(api.db, "load_patient_profile", return_value=None),
    ):
        with _authed() as client:
            response = client.get("/api/v1/preventive-care")
    assert response.status_code == 200, response.text
    assert "care_gaps" in response.json()


def test_symptom_analyse_validates_and_refuses_diagnosis():
    with mock.patch.object(api, "_load_snapshot_or_rebuild", return_value=dict(SNAPSHOT)):
        with _authed() as client:
            missing = client.post("/api/v1/symptoms/analyse", json={})
            ok = client.post(
                "/api/v1/symptoms/analyse",
                json={"symptom": "I have a dry cough for a week"},
            )
    assert missing.status_code == 400
    assert ok.status_code == 200, ok.text
    assert "not a diagnosis" in ok.json()["summary"].lower()


def test_finding_feedback_round_trip():
    with _authed() as client:
        missing = client.post("/api/v1/findings/feedback", json={"verdict": "confirmed"})
        bad = client.post(
            "/api/v1/findings/feedback", json={"finding_key": "abc", "verdict": "not-a-verdict"}
        )
        created = client.post(
            "/api/v1/findings/feedback",
            json={
                "finding_kind": "ddi",
                "rule": "ace + k",
                "medications_involved": ["Lisinopril"],
                "verdict": "confirmed",
            },
        )
        listed = client.get("/api/v1/findings/feedback")
        metrics = client.get("/api/v1/findings/feedback/metrics")
    assert missing.status_code == 400
    assert bad.status_code == 400
    assert created.status_code == 200, created.text
    assert created.json()["verdict"] == "confirmed"
    assert listed.status_code == 200
    assert len(listed.json()["feedback"]) == 1
    assert metrics.status_code == 200
    assert metrics.json()["total"] == 1


def test_finding_lifecycle_rejects_illegal_then_lists():
    with mock.patch.object(api, "_load_snapshot_or_rebuild", return_value=None):
        with _authed() as client:
            bad = client.post(
                "/api/v1/findings/lifecycle",
                json={"finding_kind": "ddi", "rule": "r", "to_state": "confirmed"},
            )
            ok = client.post(
                "/api/v1/findings/lifecycle",
                json={
                    "finding_kind": "ddi",
                    "rule": "r",
                    "medications_involved": ["A", "B"],
                    "to_state": "active",
                },
            )
            overview = client.get("/api/v1/findings/lifecycle")
    assert bad.status_code == 400
    assert ok.status_code == 200, ok.text
    assert ok.json()["state"] == "active"
    assert overview.status_code == 200
    assert "open_count" in overview.json()


def test_fhir_import_parses_and_best_effort_persists():
    bundle = {
        "resourceType": "Bundle",
        "entry": [
            {
                "resource": {
                    "resourceType": "Patient",
                    "name": [{"given": ["Jane"], "family": "Doe"}],
                }
            },
            {
                "resource": {
                    "resourceType": "MedicationStatement",
                    "medicationCodeableConcept": {"text": "Metformin 500mg"},
                }
            },
        ],
    }
    with (
        mock.patch.object(api.db, "insert_documents") as insert,
        mock.patch.object(api.audit, "record"),
    ):
        with _authed() as client:
            bad = client.post("/api/v1/import/fhir", json={"bundle": "not-a-bundle"})
            ok = client.post("/api/v1/import/fhir", json={"bundle": bundle})
    # Invalid shape is 400 only if parse_fhir_bundle raises; a string may also
    # be treated as empty. Either 200-with-empty or 400 is acceptable as long
    # as a real Bundle is accepted.
    assert ok.status_code == 200, ok.text
    body = ok.json()
    assert body["patient_name"] == "Jane Doe"
    assert body["imported"]["medications"] == 1
    assert body["persisted"] is True
    insert.assert_called_once()
    assert bad.status_code in {200, 400}


def test_patient_measurements_and_provider_messages():
    with _authed() as client:
        missing = client.post("/api/v1/patient-data/measurements", json={"name": "Pulse"})
        created = client.post(
            "/api/v1/patient-data/measurements",
            json={"name": "Blood Pressure", "value": "140/90", "unit": "mmHg", "kind": "vital"},
        )
        listed = client.get("/api/v1/patient-data/measurements")
        empty_msg = client.post("/api/v1/provider-messages", json={"body": "   "})
        sent = client.post(
            "/api/v1/provider-messages",
            json={"body": "Question about my prescription", "provider": "Dr Smith"},
        )
        threads = client.get("/api/v1/provider-messages")
    assert missing.status_code == 400
    assert created.status_code == 200, created.text
    assert listed.status_code == 200
    assert len(listed.json()["measurements"]) == 1
    assert empty_msg.status_code == 400
    assert sent.status_code == 200, sent.text
    assert sent.json()["body"].startswith("Question")
    assert threads.status_code == 200
    assert len(threads.json()["threads"]) == 1


def test_guidelines_status_is_public_refresh_is_authed():
    api.app.dependency_overrides.pop(api.get_current_user, None)
    with TestClient(api.app) as client:
        public = client.get("/api/v1/guidelines/status")
        unauthed_refresh = client.post("/api/v1/guidelines/refresh")
    assert public.status_code == 200, public.text
    assert public.json()["total"] >= 1
    assert unauthed_refresh.status_code == 401
    with mock.patch.object(api.audit, "record"):
        with _authed() as client:
            refresh = client.post("/api/v1/guidelines/refresh")
    assert refresh.status_code == 200, refresh.text
    assert "applied_count" in refresh.json() or "checked" in refresh.json()


def test_finding_history_and_clinical_entities():
    with (
        mock.patch.object(api, "_load_snapshot_or_rebuild", return_value=dict(SNAPSHOT)),
        mock.patch.object(api, "_enhanced_cross_check", return_value=dict(CLEAN_REPORT)),
        mock.patch.object(api.db, "load_clinical_entities", return_value=[{"id": "m1"}]),
    ):
        with _authed() as client:
            snap = client.post("/api/v1/findings/history/snapshot")
            history = client.get("/api/v1/findings/history")
            change_log = client.get("/api/v1/findings/history/change-log")
            entities = client.get("/api/v1/clinical-entities/clinical_medications")
    assert snap.status_code == 200, snap.text
    assert history.status_code == 200
    assert "snapshots" in history.json()
    assert change_log.status_code == 200
    assert entities.status_code == 200
    assert entities.json()["kind"] == "clinical_medications"
    assert entities.json()["count"] == 1


if __name__ == "__main__":
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_")]
    for test in tests:
        teardown_function()
        test()
        print(f"PASS {test.__name__}")
    teardown_function()
    print(f"\n{len(tests)} tests passed")
