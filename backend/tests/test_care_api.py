"""Authenticated API checks for the local-care extension.

The tests intentionally do not contain or fabricate provider records. The
live-search compatibility test uses an empty source response only, so no
provider, clinic, address, rating, phone, or directory data is introduced.
"""

import os
import sys
from unittest import mock

import jwt
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ["GROQ_API_KEY"] = "gsk_test_123"
TEST_JWT_SECRET = "care-api-test-secret-with-at-least-thirty-two-characters"
os.environ["JWT_SECRET"] = TEST_JWT_SECRET

import api  # noqa: E402
from provider_sources import ProviderSourcePayload, SearchOrigin  # noqa: E402


SNAPSHOT = {
    "patient_timeline": {
        "visits": [
            {
                "date": "2026-08-04",
                "document_type": "prescription",
                "overall_confidence": 0.94,
                "_source": {"file": "Prescription_01.pdf", "method": "text_layer"},
                "document_url": "https://files.example.test/prescription-01.pdf",
                "medications": [{"name": "Medicine A"}],
                "lab_results": [],
                "allergies_noted": [],
            },
            {
                "date": "2026-08-08",
                "document_type": "prescription",
                "overall_confidence": 0.94,
                "_source": {"file": "Prescription_02.pdf", "method": "text_layer"},
                "document_url": "https://files.example.test/prescription-02.pdf",
                "medications": [{"name": "Medicine B"}],
                "lab_results": [],
                "allergies_noted": [],
            },
        ],
        "medications_timeline": [
            {
                "name": "Medicine A",
                "ingredients": [],
                "dosage": "500 mg",
                "frequency": "twice daily",
                "date": "2026-08-04",
                "source_file": "Prescription_01.pdf",
                "confidence": 0.94,
            },
            {
                "name": "Medicine B",
                "ingredients": [],
                "dosage": "20 mg",
                "frequency": "once daily",
                "date": "2026-08-08",
                "source_file": "Prescription_02.pdf",
                "confidence": 0.94,
            },
        ],
        "lab_results_timeline": [],
        "known_allergies": [],
    },
    "cross_check_report": {
        "potential_drug_interactions": [
            {
                "medications_involved": ["Medicine A", "Medicine B"],
                "severity": "high",
                "confidence": 0.9,
                "explanation": "Potential interaction requires review.",
            }
        ],
        "allergy_conflicts": [],
        "duplicate_prescriptions": [],
        "conflicting_dosage_instructions": [],
    },
    "lab_trends": {"trends": []},
}


def _headers(user_id="anon_care_test"):
    token = jwt.encode({"user_id": user_id, "sub": user_id}, TEST_JWT_SECRET, algorithm="HS256")
    return {"Authorization": f"Bearer {token}", "X-User-Id": user_id}


def _authenticated_test_env():
    return mock.patch.dict(os.environ, {"JWT_SECRET": TEST_JWT_SECRET})


def test_context_is_authenticated_and_returns_existing_flag_only():
    with _authenticated_test_env(), mock.patch.object(api.db, "load_patient_snapshot", return_value=SNAPSHOT):
        with TestClient(api.app) as client:
            response = client.get("/api/v1/care-recommendations", headers=_headers())
    assert response.status_code == 200
    body = response.json()
    assert body["eligible"] is True
    flag = body["flags"][0]
    assert flag["id"] == "interaction-0"
    assert flag["specialty"]["id"] == "pharmacy"
    assert flag["specialty"]["primary"]["id"] == "pharmacy"
    assert flag["specialty"]["alternative"]["id"] == "general_practice"
    assert {item["source_file"] for item in flag["pathway_evidence"] if item.get("source_file")} == {
        "Prescription_01.pdf",
        "Prescription_02.pdf",
    }


def test_search_reports_missing_live_source_configuration_without_provider_fallback():
    old_source = os.environ.get("PROVIDER_DIRECTORY_SOURCE")
    old_agent = os.environ.pop("OSM_NOMINATIM_USER_AGENT", None)
    os.environ["PROVIDER_DIRECTORY_SOURCE"] = "openstreetmap"
    try:
        with _authenticated_test_env(), mock.patch.object(api.db, "load_patient_snapshot", return_value=SNAPSHOT):
            with TestClient(api.app) as client:
                response = client.post(
                    "/api/v1/care-recommendations/search",
                    headers=_headers(),
                    json={"flag_id": "interaction-0", "location": "Negombo", "availability": "weekends"},
                )
        assert response.status_code == 503
        body = response.json()
        assert body["code"] == "provider_configuration_missing"
        assert "provider" not in body
    finally:
        if old_source is None:
            os.environ.pop("PROVIDER_DIRECTORY_SOURCE", None)
        else:
            os.environ["PROVIDER_DIRECTORY_SOURCE"] = old_source
        if old_agent is not None:
            os.environ["OSM_NOMINATIM_USER_AGENT"] = old_agent


class EmptyLiveSource:
    """Live-source shaped test double with no provider records whatsoever."""

    def search(self, location, specialty):
        return ProviderSourcePayload(
            source_id="test_empty_source",
            source_label="Empty live-source test",
            origin=SearchOrigin(label=location, latitude=0.0, longitude=0.0),
            records=[],
            no_results_message="No records returned.",
        )


def test_search_response_preserves_existing_fields_and_adds_clinical_evidence():
    # No provider data is returned or asserted. This only proves the existing
    # zero-result response remains compatible while clinical evidence is added.
    with _authenticated_test_env(), \
         mock.patch.object(api.db, "load_patient_snapshot", return_value=SNAPSHOT), \
         mock.patch("care_recommendations.get_provider_source", return_value=EmptyLiveSource()):
        with TestClient(api.app) as client:
            response = client.post(
                "/api/v1/care-recommendations/search",
                headers=_headers(),
                json={"flag_id": "interaction-0", "location": "Negombo", "availability": "evenings"},
            )
    assert response.status_code == 200
    body = response.json()
    assert {"clinical_flag", "specialty", "location", "availability", "provenance", "ranking_method", "providers", "no_results_message", "disclaimer"} <= set(body)
    assert body["providers"] == []
    assert body["no_results_message"] == "No records returned."
    assert len(body["evidence"]) >= 2
    assert body["care_route_explanation"]
    assert "consultation_pack" in body
    assert body["consultation_pack"]["medication_records_to_discuss"]
    assert body["consultation_pack"]["clinician_questions"]


def test_evidence_cannot_leak_between_authenticated_patient_snapshots():
    patient_a = SNAPSHOT
    patient_b = {
        **SNAPSHOT,
        "patient_timeline": {
            **SNAPSHOT["patient_timeline"],
            "visits": [
                {
                    "date": "2026-07-01",
                    "document_type": "prescription",
                    "overall_confidence": 0.9,
                    "_source": {"file": "Patient_B_Only.pdf", "method": "text_layer"},
                    "document_url": "https://files.example.test/patient-b-only.pdf",
                    "medications": [{"name": "Medicine C"}],
                    "lab_results": [],
                    "allergies_noted": [],
                }
            ],
            "medications_timeline": [
                {
                    "name": "Medicine C",
                    "ingredients": [],
                    "dosage": "10 mg",
                    "frequency": "once daily",
                    "date": "2026-07-01",
                    "source_file": "Patient_B_Only.pdf",
                    "confidence": 0.9,
                }
            ],
        },
        "cross_check_report": {
            "potential_drug_interactions": [
                {
                    "medications_involved": ["Medicine C"],
                    "severity": "high",
                    "confidence": 0.9,
                    "explanation": "Potential interaction requires review.",
                }
            ],
            "allergy_conflicts": [],
            "duplicate_prescriptions": [],
            "conflicting_dosage_instructions": [],
        },
    }

    def snapshot_for(user_id):
        return patient_a if user_id == "anon_patient_a" else patient_b

    with _authenticated_test_env(), mock.patch.object(api.db, "load_patient_snapshot", side_effect=snapshot_for):
        with TestClient(api.app) as client:
            response_a = client.get("/api/v1/care-recommendations", headers=_headers("anon_patient_a"))
            response_b = client.get("/api/v1/care-recommendations", headers=_headers("anon_patient_b"))
    evidence_a = response_a.json()["flags"][0]["pathway_evidence"]
    evidence_b = response_b.json()["flags"][0]["pathway_evidence"]
    files_a = {item.get("source_file") for item in evidence_a}
    files_b = {item.get("source_file") for item in evidence_b}
    assert "Patient_B_Only.pdf" not in files_a
    assert "Prescription_01.pdf" not in files_b
    assert "Patient_B_Only.pdf" in files_b
