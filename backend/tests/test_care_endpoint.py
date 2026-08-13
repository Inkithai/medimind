"""HTTP surface for Care Navigation stays off the medical pipeline."""
import os
import sys
from unittest import mock

from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("GROQ_API_KEY", "gsk_test_123")
os.environ.setdefault("JWT_SECRET", "test-secret-for-care")

import api  # noqa: E402
from care.models import Facility, GeoPoint, pack_facilities  # noqa: E402


def _auth():
    user_id, token = api.issue_anonymous_token()
    return {"Authorization": f"Bearer {token}", "X-User-Id": user_id}


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
