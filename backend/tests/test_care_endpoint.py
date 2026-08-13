"""HTTP tests for /api/v1/care/* — map-based Google path + legacy care_finder."""

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
os.environ.setdefault("JWT_SECRET", "test-secret-for-care-endpoints-ok")

from fastapi.testclient import TestClient  # noqa: E402

import api  # noqa: E402
import care_finder  # noqa: E402
from care.errors import CareProviderError  # noqa: E402
from care.models import Facility, GeoPoint, pack_facilities  # noqa: E402


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


def _auth():
    user_id, token = api.issue_anonymous_token()
    return {"Authorization": f"Bearer {token}", "X-User-Id": user_id}


def _client():
    async def override_user():
        return "anon_care_test"

    api.app.dependency_overrides[api.get_current_user] = override_user
    return TestClient(api.app)


def _client_with_user():
    app = api.app

    async def override_user():
        return "anon_test_user"

    app.dependency_overrides[api.get_current_user] = override_user
    return app


def test_facilities_uses_service_not_timeline():
    packed = pack_facilities(
        query="Kandy",
        kind="hospital",
        origin=GeoPoint(7.29, 80.63, "Kandy", "fake"),
        facilities=[
            Facility("1", "Hospital", "hospital", 7.3, 80.64, distance_km=1.2, provider="fake")
        ],
        provider="fake",
    )
    service = mock.Mock()
    service.search_facilities.return_value = packed
    with mock.patch.object(api, "get_care_provider", side_effect=api.CareConfigurationError("unset")):
        with mock.patch.object(api, "get_care_service", return_value=service):
            client = TestClient(api.app)
            response = client.get(
                "/api/v1/care/facilities",
                params={"location": "Kandy", "kind": "hospital"},
                headers=_auth(),
            )
    assert response.status_code == 200
    body = response.json()
    assert body["result_count"] == 1
    assert body["provider"] == "fake"
    service.search_facilities.assert_called_once()


def test_facilities_requires_auth():
    client = TestClient(api.app)
    response = client.get("/api/v1/care/facilities", params={"location": "Kandy"})
    assert response.status_code in {401, 403}


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


def test_suggestion_without_records_is_general_practice():
    app = _client_with_user()
    try:
        with mock.patch.object(api.db, "load_patient_snapshot", return_value=None):
            with TestClient(app) as client:
                resp = client.get("/api/v1/care/suggestion")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["suggested"]["id"] == "general_practice"
        assert body["has_records"] is False
        assert any(item["id"] == "cardiology" for item in body["all"])
    finally:
        app.dependency_overrides.clear()


def test_search_returns_ranked_osm_results():
    app = _client_with_user()
    payload = {
        "query": {
            "city": "Kandy",
            "specialty_id": "endocrinology",
            "specialty_label": "Endocrinology / diabetes",
            "days": ["mon"],
            "time_of_day": "morning",
            "radius_km": 8,
        },
        "location": {"lat": 7.29, "lon": 80.63, "label": "Kandy, Sri Lanka", "source": "OpenStreetMap Nominatim"},
        "suggestion": {"id": "endocrinology", "label": "Endocrinology / diabetes", "reasons": ["Medicine on your record: Metformin"]},
        "results": [{
            "id": "node/1",
            "name": "Kandy Diabetes Clinic",
            "place_type": "clinic",
            "match_kind": "specialty",
            "specialties": ["endocrinology"],
            "address": "Kandy",
            "phone": "+94 81 0000000",
            "website": None,
            "opening_hours": "Mo-Fr 08:00-16:00",
            "availability": "open",
            "lat": 7.291,
            "lon": 80.633,
            "distance_km": 0.3,
            "score": 170.0,
            "source": "OpenStreetMap",
            "source_url": "https://www.openstreetmap.org/node/1",
        }],
        "result_count": 1,
        "zero_results_hint": None,
        "source": {
            "name": "OpenStreetMap",
            "geocoder": "Nominatim",
            "directory": "Overpass API",
            "license": "ODbL",
            "attribution": "© OpenStreetMap contributors",
            "url": "https://www.openstreetmap.org/copyright",
        },
        "disclaimer": care_finder.DISCLAIMER,
    }
    try:
        with mock.patch.object(api.db, "load_patient_snapshot", return_value=None), \
             mock.patch.object(care_finder, "search_care", return_value=payload):
            with TestClient(app) as client:
                resp = client.post(
                    "/api/v1/care/search",
                    json={"city": "Kandy", "specialty": "endocrinology", "days": ["mon"], "time_of_day": "morning"},
                )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["result_count"] == 1
        assert body["results"][0]["source"] == "OpenStreetMap"
        assert "not a medical referral" in body["disclaimer"].lower()
    finally:
        app.dependency_overrides.clear()


def test_unknown_city_is_422():
    app = _client_with_user()
    try:
        with mock.patch.object(api.db, "load_patient_snapshot", return_value=None), \
             mock.patch.object(care_finder, "search_care", side_effect=care_finder.CityNotFoundError("Narnia")):
            with TestClient(app) as client:
                resp = client.post("/api/v1/care/search", json={"city": "Narnia"})
        assert resp.status_code == 422, resp.text
        body = resp.json()
        assert body["code"] == "city_not_found"
        assert body["retryable"] is False
    finally:
        app.dependency_overrides.clear()


def test_directory_outage_is_502_retryable():
    app = _client_with_user()
    try:
        with mock.patch.object(api.db, "load_patient_snapshot", return_value=None), \
             mock.patch.object(care_finder, "search_care", side_effect=care_finder.DirectoryUnavailableError()):
            with TestClient(app) as client:
                resp = client.post("/api/v1/care/search", json={"city": "Kandy"})
        assert resp.status_code == 502, resp.text
        body = resp.json()
        assert body["code"] == "directory_unavailable"
        assert body["retryable"] is True
    finally:
        app.dependency_overrides.clear()


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"\n{len(fns)} tests passed")
