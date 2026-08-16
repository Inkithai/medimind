"""Regression tests: a backend restart must have zero effect on records.

Two guarantees are covered here.

1. GET /api/v1/documents reads straight from the durable `documents` table,
   so it is the authoritative answer to "did my upload survive the
   redeploy/OOM restart?" — independent of any in-process cache.

2. The dashboard reads (/patient-snapshot, /timeline, /cross-check,
   /lab-trends) reconstruct from those persisted documents when the derived
   `patient_snapshots` cache row is missing. Previously a missing snapshot
   row returned 404, which the frontend renders as the "Welcome to
   MediMind" first-run empty state — i.e. a user with six saved documents
   was told they had no records at all.
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


PERSISTED_DOC = {
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
    "lab_results": [{
        "test_name": "Hemoglobin", "value": 13.2, "unit": "g/dL",
        "reference_range": "13.0-17.0", "flag": "normal",
    }],
    "allergies_noted": ["Penicillin"],
    "clinical_notes": "Follow up in two weeks.",
    "overall_confidence": 0.92,
    "_source": {"file": "rx.pdf"},
}


def _client(documents, snapshot):
    app = api.app

    async def override_user():
        return "anon_test_user"

    app.dependency_overrides[api.get_current_user] = override_user
    patchers = [
        mock.patch.object(api.db, "load_documents", return_value=documents),
        mock.patch.object(api.db, "load_patient_snapshot", return_value=snapshot),
    ]
    for p in patchers:
        p.start()
    return app, patchers


def test_documents_endpoint_returns_persisted_rows():
    app, patchers = _client([dict(PERSISTED_DOC)] * 6, snapshot=None)
    try:
        with TestClient(app) as client:
            resp = client.get("/api/v1/documents")
    finally:
        for p in patchers:
            p.stop()
        app.dependency_overrides.clear()

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["count"] == 6
    assert len(body["documents"]) == 6
    assert body["user_id"] == "anon_test_user"


def test_documents_endpoint_returns_empty_list_not_404():
    """An empty list is a meaningful diagnostic answer ("the rows really are
    gone"); a 404 would be indistinguishable from a routing problem."""
    app, patchers = _client([], snapshot=None)
    try:
        with TestClient(app) as client:
            resp = client.get("/api/v1/documents")
    finally:
        for p in patchers:
            p.stop()
        app.dependency_overrides.clear()

    assert resp.status_code == 200, resp.text
    assert resp.json()["count"] == 0


def test_snapshot_is_rebuilt_from_documents_when_cache_row_missing():
    app, patchers = _client([dict(PERSISTED_DOC)], snapshot=None)
    try:
        with TestClient(app) as client:
            resp = client.get("/api/v1/patient-snapshot")
    finally:
        for p in patchers:
            p.stop()
        app.dependency_overrides.clear()

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["rebuilt_from_documents"] is True
    assert len(body["patient_timeline"]["visits"]) == 1
    assert body["patient_timeline"]["medications_timeline"][0]["name"] == "Paracetamol"
    assert body["patient_timeline"]["known_allergies"] == ["Penicillin"]
    # Lab trends are pure functions of the timeline, so they are rebuilt too.
    assert "lab_trends" in body
    # The safety report needs an LLM, so it comes back empty rather than
    # firing a provider call from a GET request.
    assert body["cross_check_report"]["potential_drug_interactions"] == []


def test_timeline_endpoint_rebuilds_instead_of_404():
    app, patchers = _client([dict(PERSISTED_DOC)], snapshot=None)
    try:
        with TestClient(app) as client:
            timeline = client.get("/api/v1/timeline")
            cross_check = client.get("/api/v1/cross-check")
            lab_trends = client.get("/api/v1/lab-trends")
    finally:
        for p in patchers:
            p.stop()
        app.dependency_overrides.clear()

    assert timeline.status_code == 200, timeline.text
    assert len(timeline.json()["visits"]) == 1
    assert cross_check.status_code == 200, cross_check.text
    assert lab_trends.status_code == 200, lab_trends.text


def test_user_with_no_documents_still_gets_404():
    """The first-run empty state must survive: only a user with genuinely
    zero persisted documents sees 404."""
    app, patchers = _client([], snapshot=None)
    try:
        with TestClient(app) as client:
            resp = client.get("/api/v1/patient-snapshot")
            timeline = client.get("/api/v1/timeline")
    finally:
        for p in patchers:
            p.stop()
        app.dependency_overrides.clear()

    assert resp.status_code == 404, resp.text
    assert timeline.status_code == 404, timeline.text


def test_cached_snapshot_is_replayed_against_durable_documents_before_use():
    snapshot = {
        "patient_timeline": {"visits": [], "medications_timeline": [],
                             "lab_results_timeline": [], "known_allergies": []},
        "cross_check_report": {"potential_drug_interactions": [],
                               "duplicate_prescriptions": [],
                               "conflicting_dosage_instructions": [],
                               "allergy_conflicts": [],
                               "overall_recommendation": "All good."},
        "lab_trends": {"trends": [], "insufficient_data": []},
        "updated_at": "2024-03-15T00:00:00Z",
    }
    load_documents = mock.Mock(return_value=[dict(PERSISTED_DOC)])
    app = api.app

    async def override_user():
        return "anon_test_user"

    app.dependency_overrides[api.get_current_user] = override_user
    with mock.patch.object(api.db, "load_patient_snapshot", return_value=snapshot), \
         mock.patch.object(api.db, "load_documents", load_documents):
        try:
            with TestClient(app) as client:
                resp = client.get("/api/v1/patient-snapshot")
        finally:
            app.dependency_overrides.clear()

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "rebuilt_from_documents" not in body
    assert "withheld" in body["cross_check_report"]["overall_recommendation"].lower()
    # Durable extraction/correction rows are authoritative; a legacy snapshot
    # with no matching trust fingerprint must not bypass replay.
    load_documents.assert_called_once_with("anon_test_user")


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"\n{len(fns)} tests passed")
