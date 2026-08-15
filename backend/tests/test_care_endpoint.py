"""Offline API contract tests for provider-neutral care navigation."""

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

from fastapi.testclient import TestClient  # noqa: E402

import api  # noqa: E402
from care.errors import CareProviderError  # noqa: E402
from care.models import Facility  # noqa: E402


class FakeProvider:
    name = "fake"

    def __init__(self, error=None):
        self.error = error
        self.calls = []

    def search(self, location, kind, radius_km, **coordinates):
        self.calls.append((location, kind, radius_km, coordinates))
        if self.error:
            raise self.error
        return [
            Facility(
                id="facility-1",
                name="Jaffna Teaching Hospital",
                kind="hospital",
                latitude=9.668,
                longitude=80.015,
                source="Test public listing",
            )
        ]


def _client():
    async def override_user():
        return "anon_care_test"

    api.app.dependency_overrides[api.get_current_user] = override_user
    return TestClient(api.app)


def test_endpoint_returns_normalized_facility_list_and_forwards_coordinates():
    provider = FakeProvider()
    try:
        with mock.patch.object(api, "get_care_provider", return_value=provider):
            with _client() as client:
                response = client.get(
                    "/api/v1/care/facilities",
                    params={
                        "location": "Jaffna",
                        "kind": "hospital",
                        "radius_km": 8,
                        "latitude": 9.668,
                        "longitude": 80.015,
                    },
                )
        assert response.status_code == 200, response.text
        assert response.json()[0]["name"] == "Jaffna Teaching Hospital"
        assert provider.calls[0][1] == "hospital"
        assert provider.calls[0][3] == {"latitude": 9.668, "longitude": 80.015}
    finally:
        api.app.dependency_overrides.clear()


def test_provider_failure_is_neutral_and_does_not_expose_credentials():
    provider = FakeProvider(CareProviderError("Google said key=secret-key is invalid"))
    try:
        with mock.patch.object(api, "get_care_provider", return_value=provider):
            with _client() as client:
                response = client.get(
                    "/api/v1/care/facilities",
                    params={"location": "Jaffna", "kind": "hospital", "radius_km": 8},
                )
        assert response.status_code == 503
        assert response.json()["detail"] == (
            "The facility directory is temporarily unavailable. Please try again shortly."
        )
        assert "secret-key" not in response.text
    finally:
        api.app.dependency_overrides.clear()


class OutOfRadiusProvider:
    """Provider that misbehaves and returns results beyond the radius."""

    name = "fake"

    def search(self, location, kind, radius_km, **coordinates):
        return [
            Facility(
                id="near",
                name="Near Clinic",
                kind="clinic",
                latitude=9.670,
                longitude=80.016,
                source="Test public listing",
            ),
            Facility(
                id="far",
                name="Far Hospital",
                kind="hospital",
                latitude=9.90,
                longitude=80.30,  # ~40 km away
                source="Test public listing",
            ),
            Facility(  # exact duplicate id — must be removed
                id="near",
                name="Near Clinic",
                kind="clinic",
                latitude=9.670,
                longitude=80.016,
                source="Test public listing",
            ),
        ]


def test_endpoint_enforces_radius_and_dedupes_regardless_of_provider():
    try:
        with mock.patch.object(api, "get_care_provider", return_value=OutOfRadiusProvider()):
            with _client() as client:
                response = client.get(
                    "/api/v1/care/facilities",
                    params={
                        "location": "Jaffna",
                        "kind": "any",
                        "radius_km": 5,
                        "latitude": 9.668,
                        "longitude": 80.015,
                    },
                )
        assert response.status_code == 200, response.text
        payload = response.json()
        assert [item["id"] for item in payload] == ["near"]
        assert all(item["distance_km"] is not None and item["distance_km"] <= 5 for item in payload)
    finally:
        api.app.dependency_overrides.clear()


def test_specialty_suggestion_weak_evidence_yields_no_specialty():
    visits = [{"clinical_notes": "digest", "overall_confidence": 0.3}]
    snapshot = {"patient_timeline": {"visits": visits}}
    try:
        with mock.patch.object(api.db, "load_patient_snapshot", return_value=snapshot):
            with _client() as client:
                response = client.get("/api/v1/care/specialty-suggestion")
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["specialty"] is None
        assert payload["evidence_level"] == "weak"
        assert payload["headline"] == "No specific specialty identified"
        assert payload["search_options"][0] == "General Medicine"
        assert "not a diagnosis" in payload["disclaimer"]
    finally:
        api.app.dependency_overrides.clear()


def test_specialty_suggestion_survives_snapshot_failure():
    try:
        with mock.patch.object(api.db, "load_patient_snapshot", side_effect=RuntimeError("db down")):
            with _client() as client:
                response = client.get("/api/v1/care/specialty-suggestion")
        assert response.status_code == 200, response.text
        assert response.json()["specialty"] is None
    finally:
        api.app.dependency_overrides.clear()


if __name__ == "__main__":
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_")]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"\n{len(tests)} tests passed")
