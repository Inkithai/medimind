"""OpenStreetMap (Overpass API) care-directory adapter.

OpenStreetMap is a public geographic database, not an official registry of
verified healthcare providers, so every Facility carries
``source="OpenStreetMap"`` and the UI presents results as publicly listed
healthcare locations that must be verified with the provider.

Classification uses ONLY structured OSM tags (``healthcare=*``,
``amenity=*``, ``building=hospital``) — never the display name. Entities
whose tags don't match a supported category are surfaced as ``healthcare``
("Other"), never forced into ``clinic``.
"""

import json
import os
import socket
from typing import Any, Dict, List, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from care.errors import CareProviderError
from care.geo import distance_km
from care.models import Facility

_USER_AGENT = "MediMind/1.0 (care navigation; contact: ops@medimind.example)"

# healthcare=* is the primary healthcare tagging scheme and wins over
# amenity=* when both are present.
_HEALTHCARE_KIND = {
    "hospital": "hospital",
    "clinic": "clinic",
    "doctor": "doctor",
    "doctors": "doctor",
    "pharmacy": "pharmacy",
    "laboratory": "laboratory",
    "sample_collection": "laboratory",
}

_AMENITY_KIND = {
    "hospital": "hospital",
    "clinic": "clinic",
    "doctors": "doctor",
    "pharmacy": "pharmacy",
    "laboratory": "laboratory",
}

# Overpass tag filters per requested kind. "any" pulls every healthcare=*
# object plus the amenity spellings, so labs/doctors/pharmacies are included
# even when the mapper only used one scheme.
_KIND_FILTERS: Dict[str, List[str]] = {
    "any": [
        '["healthcare"]',
        '["amenity"~"^(hospital|clinic|doctors|pharmacy)$"]',
    ],
    "hospital": ['["healthcare"="hospital"]', '["amenity"="hospital"]'],
    "clinic": ['["healthcare"="clinic"]', '["amenity"="clinic"]'],
    "doctor": ['["healthcare"~"^doctors?$"]', '["amenity"="doctors"]'],
    "pharmacy": ['["healthcare"="pharmacy"]', '["amenity"="pharmacy"]'],
    "laboratory": ['["healthcare"~"^(laboratory|sample_collection)$"]', '["amenity"="laboratory"]'],
}


class OsmProvider:
    """Query the Overpass API and emit provider-neutral facilities."""

    name = "osm"

    def __init__(
        self,
        *,
        overpass_url: Optional[str] = None,
        nominatim_url: Optional[str] = None,
        timeout_seconds: Optional[float] = None,
    ) -> None:
        self.overpass_url = (
            overpass_url
            or os.environ.get("OSM_OVERPASS_URL")
            or "https://overpass-api.de/api/interpreter"
        )
        self.nominatim_url = (
            nominatim_url
            or os.environ.get("OSM_NOMINATIM_URL")
            or "https://nominatim.openstreetmap.org"
        ).rstrip("/")
        self.timeout_seconds = timeout_seconds or _timeout_from_env()

    def search(
        self,
        location: str,
        kind: str,
        radius_km: float,
        *,
        latitude: Optional[float] = None,
        longitude: Optional[float] = None,
    ) -> List[Facility]:
        normalized_kind = (kind or "any").strip().lower()
        if normalized_kind == "lab":
            normalized_kind = "laboratory"
        if normalized_kind not in _KIND_FILTERS:
            raise ValueError(
                "Unsupported facility type. Use any, hospital, clinic, pharmacy, laboratory, or doctor."
            )
        radius = min(max(float(radius_km), 1.0), 50.0)

        if (latitude is None) != (longitude is None):
            raise ValueError("latitude and longitude must be supplied together.")
        if latitude is None or longitude is None:
            place = (location or "").strip()
            if not place:
                raise ValueError("A city/area or latitude/longitude is required.")
            latitude, longitude = self._geocode(place)

        query = self._overpass_query(normalized_kind, radius, latitude, longitude)
        elements = self._request_overpass(query)

        facilities: List[Facility] = []
        for element in elements:
            facility = self._normalize(element, latitude, longitude)
            if facility is not None:
                facilities.append(facility)
        facilities.sort(
            key=lambda item: item.distance_km if item.distance_km is not None else float("inf")
        )
        return facilities

    # -- Overpass ----------------------------------------------------------

    @staticmethod
    def _overpass_query(kind: str, radius_km: float, latitude: float, longitude: float) -> str:
        radius_m = int(radius_km * 1000)
        around = f"(around:{radius_m},{latitude:.6f},{longitude:.6f})"
        clauses = "".join(f"nwr{selector}{around};" for selector in _KIND_FILTERS[kind])
        return f"[out:json][timeout:25];({clauses});out center tags;"

    def _request_overpass(self, query: str) -> List[Dict[str, Any]]:
        request = Request(
            self.overpass_url,
            data=urlencode({"data": query}).encode("utf-8"),
            method="POST",
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "User-Agent": _USER_AGENT,
            },
        )
        payload = self._read_json(request, "Overpass API")
        elements = payload.get("elements") if isinstance(payload, dict) else None
        if not isinstance(elements, list):
            raise CareProviderError("Overpass API returned an unexpected response shape.")
        return elements

    def _geocode(self, place: str) -> Tuple[float, float]:
        request = Request(
            f"{self.nominatim_url}/search?format=jsonv2&limit=1&q={quote(place)}",
            headers={"User-Agent": _USER_AGENT, "Accept": "application/json"},
        )
        payload = self._read_json(request, "Nominatim")
        if not isinstance(payload, list) or not payload:
            raise CareProviderError(f"The area {place!r} could not be located on OpenStreetMap.")
        first = payload[0]
        try:
            return float(first["lat"]), float(first["lon"])
        except (KeyError, TypeError, ValueError) as error:
            raise CareProviderError("Nominatim returned an unexpected response.") from error

    def _read_json(self, request: Request, service: str) -> Any:
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                raw = response.read()
        except HTTPError as error:
            raise CareProviderError(f"{service} rejected the request (HTTP {error.code}).") from error
        except (URLError, socket.timeout, TimeoutError) as error:
            raise CareProviderError(f"{service} could not be reached: {type(error).__name__}") from error
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise CareProviderError(f"{service} returned invalid JSON.") from error

    # -- Normalization -----------------------------------------------------

    @staticmethod
    def _normalize(
        element: Dict[str, Any], origin_lat: float, origin_lon: float
    ) -> Optional[Facility]:
        if not isinstance(element, dict):
            return None
        tags = element.get("tags")
        if not isinstance(tags, dict):
            return None

        latitude = element.get("lat")
        longitude = element.get("lon")
        if latitude is None or longitude is None:
            center = element.get("center") or {}
            latitude = center.get("lat")
            longitude = center.get("lon")
        if not isinstance(latitude, (int, float)) or not isinstance(longitude, (int, float)):
            return None

        name = tags.get("name") or tags.get("name:en")
        if not isinstance(name, str) or not name.strip():
            # Unnamed map objects are not useful directory listings.
            return None

        osm_type = element.get("type", "node")
        osm_id = element.get("id", "")
        distance = round(distance_km(origin_lat, origin_lon, float(latitude), float(longitude)), 3)

        opening = tags.get("opening_hours")
        return Facility(
            id=f"osm:{osm_type}/{osm_id}",
            name=name.strip(),
            kind=_kind_from_tags(tags),
            latitude=float(latitude),
            longitude=float(longitude),
            address=_address_from_tags(tags),
            distance_km=distance,
            phone=_first_tag(tags, "phone", "contact:phone"),
            website=_first_tag(tags, "website", "contact:website"),
            maps_url=f"https://www.openstreetmap.org/{osm_type}/{osm_id}",
            opening_hours=[opening] if isinstance(opening, str) and opening.strip() else None,
            specialties=_specialties_from_tags(tags),
            source="OpenStreetMap",
        )


def _kind_from_tags(tags: Dict[str, Any]) -> str:
    """Categorize from structured tags only — never from the display name.

    Precedence: healthcare=* (primary scheme) > amenity=* > building=hospital.
    Anything else stays 'healthcare' (Other) instead of being forced into a
    category the source never claimed.
    """
    healthcare = str(tags.get("healthcare") or "").strip().lower()
    if healthcare in _HEALTHCARE_KIND:
        return _HEALTHCARE_KIND[healthcare]
    amenity = str(tags.get("amenity") or "").strip().lower()
    if amenity in _AMENITY_KIND:
        return _AMENITY_KIND[amenity]
    if str(tags.get("building") or "").strip().lower() == "hospital":
        return "hospital"
    return "healthcare"


def _specialties_from_tags(tags: Dict[str, Any]) -> Optional[List[str]]:
    """Read healthcare:speciality=* (semicolon-separated OSM convention)."""
    raw = tags.get("healthcare:speciality") or tags.get("healthcare:specialty")
    if not isinstance(raw, str) or not raw.strip():
        return None
    values = [part.strip().replace("_", " ") for part in raw.split(";") if part.strip()]
    return values or None


def _address_from_tags(tags: Dict[str, Any]) -> Optional[str]:
    """Assemble an address from addr:* tags; derive at least a locality.

    Never fabricates a street address — parts absent from the source are
    simply omitted.
    """
    street_parts = [
        str(tags.get(key)).strip()
        for key in ("addr:housenumber", "addr:street")
        if isinstance(tags.get(key), str) and str(tags.get(key)).strip()
    ]
    locality = _first_tag(tags, "addr:city", "addr:town", "addr:village", "addr:suburb", "addr:hamlet")
    pieces: List[str] = []
    if street_parts:
        pieces.append(" ".join(street_parts))
    if locality:
        pieces.append(locality)
    return ", ".join(pieces) if pieces else None


def _first_tag(tags: Dict[str, Any], *keys: str) -> Optional[str]:
    for key in keys:
        value = tags.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _timeout_from_env() -> float:
    try:
        return min(max(float(os.environ.get("CARE_PROVIDER_TIMEOUT_SECONDS", "20")), 2.0), 30.0)
    except ValueError:
        return 20.0
