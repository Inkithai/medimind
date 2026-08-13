"""OpenStreetMap adapter: Nominatim geocoding + Overpass POI search.

Default free provider. Identify the app with CARE_USER_AGENT.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable, List, Optional

from care.models import Facility, GeoPoint, RouteEstimate, haversine_km
from care.normalizer import normalize_osm_elements

JsonFn = Callable[..., Any]

NOMINATIM_URL = os.environ.get("NOMINATIM_URL", "https://nominatim.openstreetmap.org/search")
OVERPASS_URL = os.environ.get("OVERPASS_URL", "https://overpass-api.de/api/interpreter")
USER_AGENT = os.environ.get(
    "CARE_USER_AGENT",
    "MediMind/1.0 (care navigation; https://github.com/Inkithai/medimind)",
)

_KIND_QUERY = {
    "hospital": 'nwr["amenity"="hospital"]',
    "clinic": 'nwr["amenity"~"^(clinic|doctors)$"]',
    "pharmacy": 'nwr["amenity"="pharmacy"]',
    "laboratory": 'nwr["healthcare"="laboratory"]',
    "any": 'nwr["amenity"~"^(hospital|clinic|doctors|pharmacy)$"]',
}


class OsmProvider:
    name = "openstreetmap"

    def __init__(self, http_json: Optional[JsonFn] = None) -> None:
        self._http_json = http_json or _request_json

    def geocode(self, query: str) -> Optional[GeoPoint]:
        text = (query or "").strip()
        if len(text) < 2:
            return None
        url = NOMINATIM_URL + "?" + urllib.parse.urlencode(
            {"q": text, "format": "json", "limit": 1}
        )
        payload = self._http_json(url)
        if not isinstance(payload, list) or not payload:
            return None
        hit = payload[0]
        try:
            return GeoPoint(
                latitude=float(hit["lat"]),
                longitude=float(hit["lon"]),
                label=str(hit.get("display_name") or text),
                provider=self.name,
            )
        except (KeyError, TypeError, ValueError):
            return None

    def search_nearby(self, origin: GeoPoint, kind: str, radius_m: int) -> List[Facility]:
        clause = _KIND_QUERY.get(kind) or _KIND_QUERY["any"]
        around = f"(around:{int(radius_m)},{origin.latitude:.6f},{origin.longitude:.6f})"
        body = f"[out:json][timeout:20];({clause}{around};);out center tags;"
        payload = self._http_json(OVERPASS_URL, data=body.encode("utf-8"))
        elements = payload.get("elements") if isinstance(payload, dict) else None
        if not isinstance(elements, list):
            return []
        return normalize_osm_elements(elements)

    def route(self, origin: GeoPoint, destination: GeoPoint) -> RouteEstimate:
        # OSM routing needs a separate engine (OSRM). This adapter returns a
        # straight-line estimate so the service contract stays provider-shaped.
        km = haversine_km(origin.latitude, origin.longitude, destination.latitude, destination.longitude)
        return RouteEstimate(
            origin=origin,
            destination=destination,
            distance_km=round(km, 2),
            mode="approximate_straight_line",
            provider=self.name,
            note="Straight-line distance only. Not a driving or walking route.",
        )


def _request_json(url: str, data: Optional[bytes] = None) -> Any:
    request = urllib.request.Request(
        url,
        data=data,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        method="POST" if data else "GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            raw = response.read()
    except (urllib.error.URLError, TimeoutError) as exc:
        raise RuntimeError("The facility directory is temporarily unavailable.") from exc
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("The facility directory returned an unreadable response.") from exc
