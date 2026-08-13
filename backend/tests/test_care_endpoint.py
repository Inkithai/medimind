"""HTTP tests for /api/v1/care/* with OSM calls mocked."""
import os
import sys
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ["GROQ_API_KEY"] = "gsk_test_123"
os.environ["SUPABASE_URL"] = "https://dummy.supabase.co"
os.environ["SUPABASE_SERVICE_ROLE_KEY"] = "dummy"
os.environ["JWT_SECRET"] = "dummy"

from fastapi.testclient import TestClient  # noqa: E402

import api  # noqa: E402
import care_finder  # noqa: E402


def _client():
    app = api.app

    async def override_user():
        return "anon_test_user"

    app.dependency_overrides[api.get_current_user] = override_user
    return app


def test_suggestion_without_records_is_general_practice():
    app = _client()
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
    app = _client()
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
    app = _client()
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
    app = _client()
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
