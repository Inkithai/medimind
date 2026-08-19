"""TestClient coverage for the dedicated medication-safety HTTP surface.

GET  /api/v1/medication-safety
POST /api/v1/medication-safety/reanalyze

These tests stay offline: they mock the snapshot/rebuild helpers and never
call an LLM or a live directory.
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

try:
    from fastapi.testclient import TestClient  # noqa: E402

    import api  # noqa: E402
except ModuleNotFoundError as exc:  # pragma: no cover - local sandbox without FastAPI
    TestClient = None  # type: ignore[misc, assignment]
    api = None  # type: ignore[misc, assignment]
    _IMPORT_ERROR = exc
else:
    _IMPORT_ERROR = None


def _require_api():
    if api is not None and TestClient is not None:
        return True
    message = f"medication-safety HTTP tests require API deps ({_IMPORT_ERROR})"
    try:
        import pytest
    except ImportError:
        print(f"SKIP {message}")
        return False
    pytest.skip(message)


CLEAN_REPORT = {
    "potential_drug_interactions": [
        {
            "medications_involved": ["Warfarin", "Ibuprofen"],
            "severity": "high",
            "confidence": 0.97,
            "explanation": "Deterministic knowledge-base check.",
            "source": "curated_knowledge_base",
        }
    ],
    "duplicate_prescriptions": [],
    "conflicting_dosage_instructions": [],
    "allergy_conflicts": [],
    "overall_recommendation": "Consult a doctor or pharmacist before making any changes.",
}

SNAPSHOT = {
    "patient_timeline": {
        "visits": [],
        "medications_timeline": [
            {
                "name": "Warfarin 5 mg",
                "ingredients": ["warfarin"],
                "dosage_value": 5,
                "dosage_unit": "mg",
                "frequency_per_day": 1,
                "date": "2026-01-01",
                "source_file": "rx.pdf",
            }
        ],
        "lab_results_timeline": [],
        "known_allergies": [],
    },
    "cross_check_report": dict(CLEAN_REPORT),
    "lab_trends": {"trends": [], "insufficient_data": []},
    "dosage_report": {
        "findings": [],
        "skipped": [],
        "excluded_inactive": [],
        "note": "arithmetic check",
    },
}


async def _user():
    return "anon_safety_user"


def teardown_function():
    if api is None:
        return
    api.app.dependency_overrides.pop(api.get_current_user, None)


def _authed_client() -> TestClient:
    api.app.dependency_overrides[api.get_current_user] = _user
    return TestClient(api.app)


def test_get_medication_safety_requires_auth():
    if not _require_api():
        return
    api.app.dependency_overrides.pop(api.get_current_user, None)
    with TestClient(api.app) as client:
        response = client.get("/api/v1/medication-safety")
    assert response.status_code == 401


def test_get_medication_safety_404_without_snapshot():
    if not _require_api():
        return
    with mock.patch.object(api, "_load_snapshot_or_rebuild", return_value=None):
        with _authed_client() as client:
            response = client.get("/api/v1/medication-safety")
    assert response.status_code == 404
    assert "medication-safety" in response.json()["detail"].lower()


def test_get_medication_safety_returns_dedicated_service_contract():
    if not _require_api():
        return
    with (
        mock.patch.object(api, "_load_snapshot_or_rebuild", return_value=dict(SNAPSHOT)),
        mock.patch.object(api, "_enhanced_cross_check", return_value=dict(CLEAN_REPORT)),
    ):
        with _authed_client() as client:
            response = client.get("/api/v1/medication-safety")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["service"] == "medication_safety"
    assert body["module"] == "medication_safety.py"
    assert "not a diagnosis" in body["disclaimer"].lower()
    assert body["potential_drug_interactions"][0]["severity"] == "high"
    assert body["potential_drug_interactions"][0]["confidence"] == 0.97
    assert "dosage_report" in body
    assert body["dosage_report"]["findings"] == []


def test_get_medication_safety_computes_dosage_when_snapshot_lacks_it():
    if not _require_api():
        return
    snapshot = dict(SNAPSHOT)
    snapshot.pop("dosage_report", None)
    computed = {"findings": [{"kind": "above_max_single_dose"}], "skipped": []}
    with (
        mock.patch.object(api, "_load_snapshot_or_rebuild", return_value=snapshot),
        mock.patch.object(api, "_enhanced_cross_check", return_value=dict(CLEAN_REPORT)),
        mock.patch.object(api, "check_dosages", return_value=computed) as dosage,
    ):
        with _authed_client() as client:
            response = client.get("/api/v1/medication-safety")

    assert response.status_code == 200, response.text
    dosage.assert_called_once()
    assert response.json()["dosage_report"]["findings"][0]["kind"] == "above_max_single_dose"


def test_reanalyze_404_without_documents():
    if not _require_api():
        return
    with (
        mock.patch.object(api, "_workspace_has_active_upload", return_value=False),
        mock.patch.object(api.db, "load_documents", return_value=[]),
    ):
        with _authed_client() as client:
            response = client.post("/api/v1/medication-safety/reanalyze")
    assert response.status_code == 404


def test_reanalyze_rejects_during_active_upload():
    if not _require_api():
        return
    with mock.patch.object(api, "_workspace_has_active_upload", return_value=True):
        with _authed_client() as client:
            response = client.post("/api/v1/medication-safety/reanalyze")
    assert response.status_code == 409


def test_reanalyze_rebuilds_and_reports_counts():
    if not _require_api():
        return
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
            return_value={"available": True, "tables": {}, "safety_findings": {}},
        ) as save,
        mock.patch.object(api, "_replace_index", new=mock.AsyncMock(return_value=(True, None, 2))),
        mock.patch.object(api.audit, "record"),
    ):
        with _authed_client() as client:
            response = client.post("/api/v1/medication-safety/reanalyze")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["reanalyzed"] is True
    assert body["findings_before"] == 1
    assert body["findings_after"] == 0
    assert body["resolved_count"] == 1
    assert body["indexed"] is True
    save.assert_called_once()


if __name__ == "__main__":
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_")]
    for test in tests:
        teardown_function()
        test()
        print(f"PASS {test.__name__}")
    teardown_function()
    print(f"\n{len(tests)} tests passed")
