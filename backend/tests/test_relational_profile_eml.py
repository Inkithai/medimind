"""Normalized projection, profile API, and full-list age safety tests."""

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
from clinical_projection import build_projection  # noqa: E402
from eml_safety import evaluate_age_restrictions  # noqa: E402


def test_projection_builds_independent_stable_entity_rows():
    timeline = {
        "medications_timeline": [{
            "name": "Amoxil", "ingredients": ["amoxicillin"], "date": "2026-08-10",
            "document_id": "doc-1", "source_file": "rx.pdf", "source_page": 1,
            "dosage": "500 mg",
        }],
        "lab_results_timeline": [{
            "test_name": "Creatinine", "value": "1.2", "date": "2026-08-11",
            "document_id": "doc-2", "source_file": "lab.pdf", "source_page": 1,
        }],
        "known_allergies": ["penicillin"],
        "diagnoses_timeline": [{
            "name": "Hypertension", "date": "2026-08-01", "document_id": "doc-3",
            "source_file": "note.pdf", "source_page": 1,
        }],
    }
    safety = {"allergy_conflicts": [{
        "medication": "Amoxil", "allergy": "penicillin", "explanation": "conflict"
    }]}
    first = build_projection("user-1", timeline, safety)
    second = build_projection("user-1", timeline, safety)
    assert first == second
    assert len(first["clinical_medications"]) == 1
    assert len(first["clinical_prescriptions"]) == 1
    assert first["clinical_prescriptions"][0]["data"]["medication_id"] == first["clinical_medications"][0]["id"]
    assert len(first["clinical_lab_results"]) == 1
    assert len(first["clinical_allergies"]) == 1
    assert len(first["clinical_events"]) == 1
    assert len(first["safety_findings"]) == 1


def test_age_restriction_evaluator_is_conservative_and_cited():
    rows = [
        {"wanted": "medicine-a", "restriction": "not for use in children under 12 years", "source_page": 44, "population": "children"},
        {"wanted": "medicine-b", "restriction": "specialist use only", "source_page": 45},
    ]
    findings = evaluate_age_restrictions(8, rows)
    assert len(findings) == 1
    assert findings[0]["medication"] == "medicine-a"
    assert findings[0]["source_page"] == 44
    assert findings[0]["grounded"] is True
    assert evaluate_age_restrictions(15, rows) == []


async def _user():
    return "profile-user"


def teardown_function():
    api.app.dependency_overrides.pop(api.get_current_user, None)


def test_age_conflict_flows_into_urgent_doctor_triage():
    from consult_triage import generate_consult_triage
    report = generate_consult_triage({
        "potential_drug_interactions": [], "duplicate_prescriptions": [],
        "conflicting_dosage_instructions": [], "allergy_conflicts": [],
        "eml_age_conflicts": [{
            "medication": "medicine-a", "restriction": "under 12 years",
            "explanation": "Published age restriction.", "confidence": 0.95,
            "source_page": 44, "population": "children",
        }],
    })
    item = report["doctor_actions"][0]
    assert item["trigger"] == "essential_medicine_age_restriction"
    assert item["urgency"] == "urgent"
    assert item["reference"]["page"] == 44


def test_profile_get_and_put_are_authenticated_and_validated():
    api.app.dependency_overrides[api.get_current_user] = _user
    saved = {
        "user_id": "profile-user", "legal_name": "Jane Doe",
        "date_of_birth": "1990-01-02", "preferred_name": None,
        "phone": None, "emergency_contact": None, "preferred_language": "en",
    }
    with mock.patch.object(api.db, "load_patient_profile", return_value=None), \
         mock.patch.object(api.db, "save_patient_profile", return_value=saved) as save, \
         mock.patch.object(api.audit, "record"):
        with TestClient(api.app) as client:
            empty = client.get("/api/v1/profile")
            response = client.put("/api/v1/profile", json={
                "legal_name": " Jane Doe ", "date_of_birth": "1990-01-02",
                "preferred_language": "en",
            })
            invalid = client.put("/api/v1/profile", json={"date_of_birth": "03/11/1990"})
    assert empty.status_code == 200
    assert response.status_code == 200
    assert response.json()["legal_name"] == "Jane Doe"
    assert invalid.status_code == 422
    save.assert_called_once()
