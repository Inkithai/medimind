"""Endpoint contract for explicit medication-safety re-analysis."""

import os
import sys
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("GROQ_API_KEY", "test-key")
os.environ.setdefault("SUPABASE_URL", "https://dummy.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "dummy")
os.environ.setdefault("CLOUDINARY_CLOUD_NAME", "dummy")
os.environ.setdefault("CLOUDINARY_API_KEY", "dummy")
os.environ.setdefault("CLOUDINARY_API_SECRET", "dummy")
os.environ.setdefault("JWT_SECRET", "dummy")

from fastapi.testclient import TestClient  # noqa: E402

import api  # noqa: E402


async def _user():
    return "safety-user"


def teardown_function():
    api.app.dependency_overrides.pop(api.get_current_user, None)


def test_reanalysis_rebuilds_persists_indexes_and_reports_counts():
    api.app.dependency_overrides[api.get_current_user] = _user
    old = {"potential_drug_interactions": [{"medications_involved": ["A", "B"]}]}
    clean = {
        "potential_drug_interactions": [],
        "duplicate_prescriptions": [],
        "conflicting_dosage_instructions": [],
        "allergy_conflicts": [],
    }
    timeline = {
        "visits": [],
        "medications_timeline": [],
        "lab_results_timeline": [],
        "known_allergies": [],
    }
    with (
        mock.patch.object(api, "_workspace_has_active_upload", return_value=False),
        mock.patch.object(api.db, "load_documents", return_value=[{"patient_name": "A"}]),
        mock.patch.object(
            api.db, "load_patient_snapshot", return_value={"cross_check_report": old}
        ),
        mock.patch.object(api, "_prepare_current_trust_state", return_value=([], [], {}, [])),
        mock.patch.object(
            api,
            "_derive_record",
            new=mock.AsyncMock(return_value=(timeline, clean, {"trends": []})),
        ),
        mock.patch.object(
            api.db,
            "save_patient_snapshot",
            return_value={
                "available": True,
                "tables": {},
                "safety_findings": {"created": 0, "updated": 0, "unchanged": 0, "removed": 1},
            },
        ) as save,
        mock.patch.object(api, "_replace_index", new=mock.AsyncMock(return_value=(True, None, 2))),
        mock.patch.object(api.audit, "record"),
    ):
        with TestClient(api.app) as client:
            response = client.post("/api/v1/medication-safety/reanalyze")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["reanalyzed"] is True
    assert body["findings_before"] == 1
    assert body["findings_after"] == 0
    assert body["resolved_count"] == 1
    assert body["indexed"] is True
    save.assert_called_once()


def test_reanalysis_rejects_during_active_upload():
    api.app.dependency_overrides[api.get_current_user] = _user
    with mock.patch.object(api, "_workspace_has_active_upload", return_value=True):
        with TestClient(api.app) as client:
            response = client.post("/api/v1/medication-safety/reanalyze")
    assert response.status_code == 409
