"""End-to-end offline flow test: stub Overpass server -> OSM provider ->
API endpoint -> radius enforcement, categorization, and deduplication.

Reproduces the reported Point Pedro scenario: a raw feed containing
duplicate clinics, a hospital, laboratories, and far-away facilities, and
asserts the API returns a clean, honest result set.
"""

import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
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
from care.providers.osm import OsmProvider  # noqa: E402

# Point Pedro, Sri Lanka.
ORIGIN = {"latitude": 9.8166, "longitude": 80.2333}

_OVERPASS_ELEMENTS = [
    # Nearby clinic with address tags.
    {
        "type": "node", "id": 1, "lat": 9.8180, "lon": 80.2340,
        "tags": {"name": "Sri Ram Clinic", "healthcare": "clinic", "addr:city": "Point Pedro"},
    },
    # Same clinic mapped twice (node + way) — must deduplicate to one.
    {
        "type": "node", "id": 2, "lat": 9.8190, "lon": 80.2350,
        "tags": {"name": "Sivasakthi Clinic", "amenity": "clinic"},
    },
    {
        "type": "way", "id": 3, "center": {"lat": 9.81905, "lon": 80.23503},
        "tags": {"name": "Sivasakthi Clinic", "healthcare": "clinic", "phone": "+94 21 000 1111"},
    },
    # A hospital that must NOT be classified as a clinic.
    {
        "type": "way", "id": 4, "center": {"lat": 9.8000, "lon": 80.2200},
        "tags": {"name": "Vasantham Hospital", "healthcare": "hospital"},
    },
    # A laboratory that must NOT be classified as a clinic.
    {
        "type": "node", "id": 5, "lat": 9.8100, "lon": 80.2300,
        "tags": {"name": "CeyMed Lab", "healthcare": "laboratory"},
    },
    # A doctor's practice.
    {
        "type": "node", "id": 6, "lat": 9.8150, "lon": 80.2320,
        "tags": {"name": "Dr. Sivapalan Practice", "amenity": "doctors"},
    },
    # A pharmacy.
    {
        "type": "node", "id": 7, "lat": 9.8170, "lon": 80.2335,
        "tags": {"name": "New Medicals", "amenity": "pharmacy"},
    },
    # Unclassifiable healthcare object -> "healthcare" (Other), not clinic.
    {
        "type": "node", "id": 8, "lat": 9.8160, "lon": 80.2330,
        "tags": {"name": "Ayurvedic Center", "healthcare": "alternative"},
    },
    # ~29 km away — must be dropped for radius 5 km, kept for 50 km.
    {
        "type": "way", "id": 9, "center": {"lat": 9.66, "lon": 80.02},
        "tags": {"name": "Tellippalai Trail Cancer Hospital", "healthcare": "hospital"},
    },
    # Unnamed node — dropped.
    {"type": "node", "id": 10, "lat": 9.8161, "lon": 80.2331, "tags": {"healthcare": "clinic"}},
]


class _StubOverpass(BaseHTTPRequestHandler):
    def do_POST(self):
        body = json.dumps({"elements": _OVERPASS_ELEMENTS}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def _serve():
    server = HTTPServer(("127.0.0.1", 0), _StubOverpass)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


def _client():
    async def override_user():
        return "anon_flow_test"

    api.app.dependency_overrides[api.get_current_user] = override_user
    return TestClient(api.app)


def _search(client, radius_km, kind="any"):
    response = client.get(
        "/api/v1/care/facilities",
        params={"location": "Point Pedro", "kind": kind, "radius_km": radius_km, **ORIGIN},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_full_flow_radius_categories_and_dedupe():
    server, url = _serve()
    provider = OsmProvider(overpass_url=url)
    try:
        with mock.patch.object(api, "get_care_provider", return_value=provider):
            with _client() as client:
                results_5km = _search(client, 5)
                results_50km = _search(client, 50)
    finally:
        api.app.dependency_overrides.clear()
        server.shutdown()

    # Radius: 5 km excludes the 29 km hospital; 50 km includes it.
    names_5km = {item["name"] for item in results_5km}
    assert "Tellippalai Trail Cancer Hospital" not in names_5km
    assert all(item["distance_km"] <= 5 for item in results_5km)
    names_50km = {item["name"] for item in results_50km}
    assert "Tellippalai Trail Cancer Hospital" in names_50km
    assert all(item["distance_km"] <= 50 for item in results_50km)

    # Dedupe: the doubly-mapped clinic appears once, keeping the richer copy.
    siva = [item for item in results_50km if item["name"] == "Sivasakthi Clinic"]
    assert len(siva) == 1
    assert siva[0]["phone"] == "+94 21 000 1111"

    # Categories come from structured tags, not names, and unknowns are
    # "healthcare" (Other) — never forced into clinic.
    kinds = {item["name"]: item["kind"] for item in results_50km}
    assert kinds["Vasantham Hospital"] == "hospital"
    assert kinds["CeyMed Lab"] == "laboratory"
    assert kinds["Dr. Sivapalan Practice"] == "doctor"
    assert kinds["New Medicals"] == "pharmacy"
    assert kinds["Sri Ram Clinic"] == "clinic"
    assert kinds["Ayurvedic Center"] == "healthcare"

    # Unnamed map objects never become listings.
    assert all(item["name"] for item in results_50km)

    # Source transparency and derived locality address.
    sri_ram = next(item for item in results_50km if item["name"] == "Sri Ram Clinic")
    assert sri_ram["source"] == "OpenStreetMap"
    assert sri_ram["address"] == "Point Pedro"

    # Results are ordered by distance.
    distances = [item["distance_km"] for item in results_50km]
    assert distances == sorted(distances)


if __name__ == "__main__":
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_")]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"\n{len(tests)} tests passed")
