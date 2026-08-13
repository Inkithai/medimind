"""OpenStreetMap (Overpass API) care-directory adapter.

This adapter needs no API key, no billing account, and no Google Cloud
project, so the Find Care directory keeps working when a commercial provider
is unconfigured or rejects the request. Data comes from public OpenStreetMap
listings and is normalized to ``Facility`` exactly like every other adapter.
"""

import json
import math
import os
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from care.errors import CareProviderError
from care.models import Facility


_DEFAULT_OVERPASS_ENDPOINTS = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
)

_DEFAULT_GEOCODER_URL = "https://nominatim.openstreetmap.org/search"

_USER_AGENT = "MediMind-CareDirectory/1.0 (+https://github.com/Inkithai/medimind)"

# Tag selectors per requested facility type. OpenStreetMap encodes healthcare
# sites under both the legacy ``amenity`` key and the newer ``healthcare`` key,
# so both are queried and de-duplicated by element id.
_KIND_SELECTORS: Dict[str, Tuple[str, ...]] = {
    "hospital": ('["amenity"="hospital"]', '["healthcare"="hospital"]'),
    "clinic": (
        '["amenity"="clinic"]',
        '["healthcare"="clinic"]',
        '["healthcare"="centre"]',
    ),
    "pharmacy": ('["amenity"="pharmacy"]', '["healthcare"="pharmacy"]'),
    "laboratory": ('["healthcare"="laboratory"]', '["amenity"="laboratory"]'),
    "doctor": ('["amenity"="doctors"]', '["healthcare"="doctor"]'),
}

_KIND_SELECTORS["lab"] = _KIND_SELECTORS["laboratory"]
_KIND_SELECTORS["any"] = tuple(
    selector
    for kind in ("hospital", "clinic", "pharmacy", "laboratory", "doctor")
    for selector in _KIND_SELECTORS[kind]
)

_MAX_RESULTS = 60


class OpenStreetMapProvider:
    """Search the Overpass API and emit provider-neutral facilities."""

    name = "openstreetmap"

    def __init__(
        self,
        *,
        endpoints: Optional[Iterable[str]] = None,
        geocoder_url: Optional[str] = None,
        timeout_seconds: Optional[float] = None,
    ) -> None:
        configured = endpoints
        if configured is None:
            raw = os.environ.get("OVERPASS_API_URL", "").strip()
            configured = [value.strip() for value in raw.split(",") if value.strip()] or None
        self.endpoints: Tuple[str, ...] = tuple(configured or _DEFAULT_OVERPASS_ENDPOINTS)
        self.geocoder_url = (
            geocoder_url or os.environ.get("OSM_GEOCODER_URL") or _DEFAULT_GEOCODER_URL
        ).rstrip("/")
        self.timeout_seconds = timeout_seconds or _timeout_from_env()

    # ------------------------------------------------------------------
    # CareProvider protocol
    # ------------------------------------------------------------------

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
        if normalized_kind not in _KIND_SELECTORS:
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

        payload = self._overpass_json(
            _build_query(normalized_kind, radius, latitude, longitude, self.timeout_seconds)
        )
        elements = payload.get("elements")
        if not isinstance(elements, list):
            raise CareProviderError("OpenStreetMap returned an unexpected response shape.")

        facilities: List[Facility] = []
        seen: set = set()
        for element in elements:
            if not isinstance(element, dict):
                continue
            facility = _normalize(element, normalized_kind, (latitude, longitude))
            if facility is None or facility.id in seen:
                continue
            seen.add(facility.id)
            facilities.append(facility)

        facilities.sort(
            key=lambda item: item.distance_km if item.distance_km is not None else math.inf
        )
        return facilities[:_MAX_RESULTS]

    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------

    def _overpass_json(self, query: str) -> Dict[str, Any]:
        """POST an Overpass QL query, failing over between public mirrors."""
        body = urlencode({"data": query}).encode("utf-8")
        last_error: Optional[Exception] = None
        for endpoint in self.endpoints:
            request = Request(
                endpoint,
                data=body,
                method="POST",
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Accept": "application/json",
                    "User-Agent": _USER_AGENT,
                },
            )
            try:
                with urlopen(request, timeout=self.timeout_seconds) as response:
                    raw = response.read()
            except HTTPError as error:
                last_error = CareProviderError(
                    f"OpenStreetMap Overpass rejected the request (HTTP {error.code})."
                )
                continue
            except OSError as error:
                # URLError, socket/TLS/timeout failures all subclass OSError.
                last_error = CareProviderError(
                    f"OpenStreetMap Overpass could not be reached: {type(error).__name__}"
                )
                continue

            try:
                parsed = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                last_error = CareProviderError("OpenStreetMap returned invalid JSON.")
                del error
                continue
            if not isinstance(parsed, dict):
                last_error = CareProviderError("OpenStreetMap returned an unexpected response.")
                continue
            return parsed

        raise last_error or CareProviderError("OpenStreetMap Overpass is unavailable.")

    def _geocode(self, place: str) -> Tuple[float, float]:
        """Resolve a free-text area to coordinates for legacy text searches."""
        query = urlencode({"q": place, "format": "jsonv2", "limit": 1})
        request = Request(
            f"{self.geocoder_url}?{query}",
            headers={"Accept": "application/json", "User-Agent": _USER_AGENT},
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                raw = response.read()
        except HTTPError as error:
            raise CareProviderError(
                f"OpenStreetMap geocoding rejected the request (HTTP {error.code})."
            ) from error
        except OSError as error:
            raise CareProviderError(
                f"OpenStreetMap geocoding could not be reached: {type(error).__name__}"
            ) from error

        try:
            parsed = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise CareProviderError("OpenStreetMap geocoding returned invalid JSON.") from error

        if not isinstance(parsed, list) or not parsed:
            raise CareProviderError(f"No place matched {place!r}.")
        first = parsed[0]
        try:
            return float(first["lat"]), float(first["lon"])
        except (KeyError, TypeError, ValueError) as error:
            raise CareProviderError("OpenStreetMap geocoding returned no coordinates.") from error


# ----------------------------------------------------------------------
# Query building and normalization
# ----------------------------------------------------------------------

def _build_query(
    kind: str,
    radius_km: float,
    latitude: float,
    longitude: float,
    timeout_seconds: float,
) -> str:
    radius_m = int(round(radius_km * 1000))
    around = f"(around:{radius_m},{latitude:.6f},{longitude:.6f})"
    clauses = "".join(f"  nwr{selector}{around};\n" for selector in _KIND_SELECTORS[kind])
    timeout = max(5, int(timeout_seconds))
    return f"[out:json][timeout:{timeout}];\n(\n{clauses});\nout center tags {_MAX_RESULTS};"


def _normalize(
    element: Dict[str, Any],
    requested_kind: str,
    origin: Tuple[float, float],
) -> Optional[Facility]:
    tags = element.get("tags")
    if not isinstance(tags, dict):
        return None

    latitude = element.get("lat")
    longitude = element.get("lon")
    if latitude is None or longitude is None:
        center = element.get("center")
        if isinstance(center, dict):
            latitude = center.get("lat")
            longitude = center.get("lon")
    if not isinstance(latitude, (int, float)) or not isinstance(longitude, (int, float)):
        return None

    name = tags.get("name") or tags.get("name:en") or tags.get("operator")
    if not isinstance(name, str) or not name.strip():
        # Unnamed nodes are useless to a patient choosing where to travel.
        return None

    element_type = str(element.get("type") or "node")
    element_id = element.get("id")
    identifier = f"osm:{element_type}:{element_id}"

    kind = _normalized_kind(tags, requested_kind)
    distance = round(_distance_km(origin[0], origin[1], latitude, longitude), 3)

    opening_hours = tags.get("opening_hours")
    hours = [opening_hours.strip()] if isinstance(opening_hours, str) and opening_hours.strip() else None
    open_now = True if hours and hours[0] == "24/7" else None

    return Facility(
        id=identifier,
        name=name.strip(),
        kind=kind,
        latitude=float(latitude),
        longitude=float(longitude),
        address=_address(tags),
        distance_km=distance,
        rating=None,
        user_rating_count=None,
        phone=_first_string(tags, ("phone", "contact:phone", "contact:mobile")),
        website=_first_string(tags, ("website", "contact:website", "url")),
        maps_url=(
            f"https://www.openstreetmap.org/{element_type}/{element_id}"
            if element_id is not None
            else f"https://www.openstreetmap.org/?mlat={latitude}&mlon={longitude}#map=17/{latitude}/{longitude}"
        ),
        opening_hours=hours,
        open_now=open_now,
        source="OpenStreetMap public listing",
    )


def _normalized_kind(tags: Dict[str, Any], fallback: str) -> str:
    amenity = str(tags.get("amenity") or "").lower()
    healthcare = str(tags.get("healthcare") or "").lower()
    values = {amenity, healthcare}
    if "hospital" in values:
        return "hospital"
    if "pharmacy" in values or "chemist" in values:
        return "pharmacy"
    if "laboratory" in values or "sample_collection" in values:
        return "laboratory"
    if "clinic" in values or "centre" in values or "center" in values:
        return "clinic"
    if "doctors" in values or "doctor" in values:
        return "doctor"
    if fallback == "lab":
        return "laboratory"
    return fallback if fallback != "any" else "healthcare"


def _address(tags: Dict[str, Any]) -> Optional[str]:
    full = tags.get("addr:full")
    if isinstance(full, str) and full.strip():
        return full.strip()
    parts = [
        " ".join(
            value
            for value in (_clean(tags.get("addr:housenumber")), _clean(tags.get("addr:street")))
            if value
        ).strip(),
        _clean(tags.get("addr:suburb")),
        _clean(tags.get("addr:city")) or _clean(tags.get("addr:town")) or _clean(tags.get("addr:village")),
        _clean(tags.get("addr:postcode")),
    ]
    address = ", ".join(part for part in parts if part)
    return address or None


def _clean(value: Any) -> Optional[str]:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _first_string(tags: Dict[str, Any], keys: Iterable[str]) -> Optional[str]:
    for key in keys:
        value = _clean(tags.get(key))
        if value:
            return value.split(";")[0].strip()
    return None


def _timeout_from_env() -> float:
    try:
        return min(max(float(os.environ.get("CARE_PROVIDER_TIMEOUT_SECONDS", "12")), 2.0), 30.0)
    except ValueError:
        return 12.0


def _distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6371.0
    to_radians = math.pi / 180
    delta_lat = (lat2 - lat1) * to_radians
    delta_lon = (lon2 - lon1) * to_radians
    value = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1 * to_radians)
        * math.cos(lat2 * to_radians)
        * math.sin(delta_lon / 2) ** 2
    )
    return radius * 2 * math.atan2(math.sqrt(value), math.sqrt(1 - value))
