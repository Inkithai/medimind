"""Local Overpass API stub for offline development/demo ONLY.

The production backend queries the real Overpass API. This stub exists so
the Find Care flow can be exercised in sandboxes without internet egress:

    python scripts/dev_overpass_stub.py --port 8900
    OSM_OVERPASS_URL=http://127.0.0.1:8900 uvicorn api:app ...

It serves a fixed set of representative OpenStreetMap-style elements
around Point Pedro / Jaffna (Sri Lanka) and honours the around:<radius>
filter in the query so radius behaviour can be demonstrated end to end.
It intentionally includes the data-quality problems the pipeline must fix
(duplicate listings, hospitals/labs that must not be shown as clinics) so
the demo proves the normalization works. Never deploy this.
"""

import json
import re
import math
import argparse
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs

# Representative sample modelled on real OSM tagging around Point Pedro.
ELEMENTS = [
    {"type": "node", "id": 101, "lat": 9.8180, "lon": 80.2340,
     "tags": {"name": "Sri Ram Clinic", "healthcare": "clinic", "addr:city": "Point Pedro"}},
    {"type": "node", "id": 102, "lat": 9.8190, "lon": 80.2355,
     "tags": {"name": "Sivasakthi Clinic", "amenity": "clinic"}},
    # Same clinic mapped twice (node + way): dedupe must collapse these.
    {"type": "way", "id": 103, "center": {"lat": 9.81902, "lon": 80.23552},
     "tags": {"name": "Sivasakthi Clinic", "healthcare": "clinic", "phone": "+94 21 226 3344"}},
    {"type": "node", "id": 104, "lat": 9.8155, "lon": 80.2310,
     "tags": {"name": "CeyMed Lab", "healthcare": "laboratory", "addr:city": "Point Pedro"}},
    {"type": "node", "id": 105, "lat": 9.8140, "lon": 80.2290,
     "tags": {"name": "Dr. Sivapalan Practice", "amenity": "doctors",
              "healthcare:speciality": "general"}},
    {"type": "node", "id": 106, "lat": 9.8172, "lon": 80.2338,
     "tags": {"name": "New Medicals Pharmacy", "amenity": "pharmacy",
              "opening_hours": "Mo-Sa 08:00-20:00"}},
    {"type": "node", "id": 107, "lat": 9.8130, "lon": 80.2260,
     "tags": {"name": "Point Pedro Base Hospital", "healthcare": "hospital",
              "amenity": "hospital", "addr:city": "Point Pedro", "phone": "+94 21 226 3261"}},
    {"type": "node", "id": 108, "lat": 9.8125, "lon": 80.2400,
     "tags": {"name": "Ayurvedic Center", "healthcare": "alternative"}},
    {"type": "node", "id": 109, "lat": 9.7800, "lon": 80.2100,
     "tags": {"name": "Vallipuram Clinic", "healthcare": "clinic",
              "addr:city": "Vallipuram"}},
    # ~13 km — inside 20 km, outside 10 km.
    {"type": "way", "id": 110, "center": {"lat": 9.7350, "lon": 80.1500},
     "tags": {"name": "Nelliady Divisional Hospital", "healthcare": "hospital"}},
    # ~29 km — inside 50 km only.
    {"type": "way", "id": 111, "center": {"lat": 9.6600, "lon": 80.0200},
     "tags": {"name": "Tellippalai Trail Cancer Hospital", "healthcare": "hospital",
              "healthcare:speciality": "oncology"}},
    # ~31 km — inside 50 km only.
    {"type": "node", "id": 112, "lat": 9.6650, "lon": 79.9990,
     "tags": {"name": "Durdans Lab Jaffna", "healthcare": "laboratory"}},
    # ~33 km — inside 50 km only.
    {"type": "way", "id": 113, "center": {"lat": 9.6615, "lon": 80.0255},
     "tags": {"name": "Jaffna Teaching Hospital", "healthcare": "hospital",
              "amenity": "hospital", "phone": "+94 21 222 2261",
              "healthcare:speciality": "general;surgery;cardiology"}},
    {"type": "node", "id": 114, "lat": 9.6640, "lon": 80.0210,
     "tags": {"name": "Appollo Clinic", "healthcare": "clinic"}},
    # Duplicate of the same Appollo Clinic (double-mapped).
    {"type": "node", "id": 115, "lat": 9.66402, "lon": 80.02103,
     "tags": {"name": "Appollo Clinic", "amenity": "clinic"}},
    # Unnamed element: providers must drop it.
    {"type": "node", "id": 116, "lat": 9.8166, "lon": 80.2333,
     "tags": {"healthcare": "clinic"}},
]


def _distance_km(lat1, lon1, lat2, lon2):
    to_rad = math.pi / 180
    dlat = (lat2 - lat1) * to_rad
    dlon = (lon2 - lon1) * to_rad
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1 * to_rad) * math.cos(lat2 * to_rad) * math.sin(dlon / 2) ** 2
    return 6371.0 * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length).decode("utf-8", "replace")
        query = parse_qs(raw).get("data", [""])[0]
        match = re.search(r"around:(\d+),([0-9.+-]+),([0-9.+-]+)", query)
        elements = ELEMENTS
        if match:
            radius_km = int(match.group(1)) / 1000
            lat, lon = float(match.group(2)), float(match.group(3))
            elements = [
                e for e in ELEMENTS
                if _distance_km(
                    lat, lon,
                    e.get("lat") or e.get("center", {}).get("lat", 0),
                    e.get("lon") or e.get("center", {}).get("lon", 0),
                ) <= radius_km
            ]
        body = json.dumps({"elements": elements}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8900)
    args = parser.parse_args()
    print(f"Dev Overpass stub (fixture data, NOT live OSM) on 127.0.0.1:{args.port}")
    HTTPServer(("127.0.0.1", args.port), Handler).serve_forever()
