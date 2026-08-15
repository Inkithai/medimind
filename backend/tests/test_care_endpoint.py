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
        assert provider.calls[0][3] == {
            "latitude": 9.668,
            "longitude": 80.015,
            "specialty": None,
        }
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


def test_specialty_is_forwarded_to_the_provider():
    provider = FakeProvider()
    try:
        with mock.patch.object(api, "get_care_provider", return_value=provider):
            with _client() as client:
                response = client.get(
                    "/api/v1/care/facilities",
                    params={
                        "location": "Colombo",
                        "kind": "any",
                        "radius_km": 5,
                        "specialty": "  gastroenterologist  ",
                    },
                )
        assert response.status_code == 200, response.text
        assert provider.calls[0][3]["specialty"] == "gastroenterologist"
    finally:
        api.app.dependency_overrides.clear()


def test_response_exposes_every_card_field_including_explicit_nulls():
    """The client can distinguish "not available" from "not returned"."""
    provider = FakeProvider()
    try:
        with mock.patch.object(api, "get_care_provider", return_value=provider):
            with _client() as client:
                response = client.get(
                    "/api/v1/care/facilities",
                    params={"location": "Jaffna", "kind": "hospital", "radius_km": 8},
                )
        facility = response.json()[0]
        for field in (
            "name",
            "kind",
            "address",
            "distance_km",
            "rating",
            "user_rating_count",
            "phone",
            "opening_hours",
            "open_now",
            "maps_url",
            "specialty",
            "specialty_match",
        ):
            assert field in facility, field
        # The fake provider supplied none of these — they must be null, not invented.
        assert facility["rating"] is None
        assert facility["phone"] is None
        assert facility["opening_hours"] is None
    finally:
        api.app.dependency_overrides.clear()


if __name__ == "__main__":
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_")]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"\n{len(tests)} tests passed")
