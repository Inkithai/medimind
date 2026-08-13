"""Google Places API (New) care-directory adapter.

This module deliberately uses the REST API rather than a browser SDK: the
Google key remains on the server and every response is normalized to
``Facility`` before it reaches the medical/application layer.
"""

from __future__ import annotations

import json
import math
import os
import socket
from typing import Any, Dict, List, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from care.errors import CareConfigurationError, CareProviderError
from care.models import Facility, GeoPoint, RouteEstimate
from care.providers.base import ProviderNotConfiguredError


_GOOGLE_FIELD_MASK = ",".join(
    (
        "places.id",
        "places.displayName",
        "places.formattedAddress",
        "places.location",
        "places.types",
        "places.primaryType",
        "places.rating",
        "places.userRatingCount",
        "places.googleMapsUri",
        "places.websiteUri",
        "places.internationalPhoneNumber",
        "places.regularOpeningHours",
        "places.currentOpeningHours",
        "places.businessStatus",
    )
)

_KIND_TO_GOOGLE_TYPES = {
    "hospital": ["hospital", "general_hospital"],
    "clinic": ["medical_clinic", "medical_center"],
    "pharmacy": ["pharmacy"],
    "laboratory": ["medical_lab"],
    "lab": ["medical_lab"],
    "doctor": ["doctor"],
}

_KIND_QUERY = {
    "any": "healthcare facilities",
    "hospital": "hospitals",
    "clinic": "medical clinics",
    "pharmacy": "pharmacies",
    "laboratory": "medical laboratories",
    "lab": "medical laboratories",
    "doctor": "doctors",
}

_PLACEHOLDER_KEYS = {
    "",
    "ai",
    "your-google-maps-api-key",
    "your-google-places-api-key",
    "replace-me",
}


class GoogleProvider:
    """Search Google Places API (New) and emit provider-neutral facilities."""

    name = "google"

    def __init__(
        self,
        api_key: Optional[str] = None,
        *,
        base_url: Optional[str] = None,
        timeout_seconds: Optional[float] = None,
    ) -> None:
        key = (api_key if api_key is not None else os.environ.get("GOOGLE_MAPS_API_KEY", "")).strip()
        if key.lower() in _PLACEHOLDER_KEYS or key.startswith("your-"):
            raise CareConfigurationError(
                "CARE_PROVIDER=google requires a real GOOGLE_MAPS_API_KEY. "
                "Enable Places API (New) and billing for the key's Google Cloud project."
            )
        self.api_key = key
        self.base_url = (
            base_url
            or os.environ.get("GOOGLE_PLACES_BASE_URL")
            or "https://places.googleapis.com/v1"
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
        if normalized_kind not in _KIND_QUERY:
            raise ValueError(
                "Unsupported facility type. Use any, hospital, clinic, pharmacy, laboratory, or doctor."
            )
        radius = min(max(float(radius_km), 1.0), 50.0)

        if (latitude is None) != (longitude is None):
            raise ValueError("latitude and longitude must be supplied together.")
        if latitude is not None and longitude is not None:
            payload = self._nearby_payload(normalized_kind, radius, latitude, longitude)
            response = self._request_json("places:searchNearby", payload)
            origin = (latitude, longitude)
        else:
            place = location.strip()
            if not place:
                raise ValueError("A city/area or latitude/longitude is required.")
            payload = self._text_payload(place, normalized_kind)
            response = self._request_json("places:searchText", payload)
            origin = None

        places = response.get("places", [])
        if not isinstance(places, list):
            raise CareProviderError("Google Places returned an unexpected response shape.")
        facilities: List[Facility] = []
        for item in places:
            if not isinstance(item, dict):
                continue
            facility = self._normalize(item, normalized_kind, origin)
            if facility is not None:
                facilities.append(facility)

        # Google does not claim a medical ranking here. With coordinates,
        # ordering is distance-only; text searches retain Google's relevance
        # order and are presented as public listings.
        if origin is not None:
            facilities.sort(key=lambda item: item.distance_km if item.distance_km is not None else math.inf)
        return facilities

    def geocode(self, query: str) -> Optional[GeoPoint]:
        """Legacy CareNavigationService hook — Places search is the primary path."""
        raise ProviderNotConfiguredError(self.name)

    def search_nearby(self, origin: GeoPoint, kind: str, radius_m: int) -> List[Facility]:
        return self.search(
            origin.label or "",
            kind,
            max(radius_m, 1000) / 1000.0,
            latitude=origin.latitude,
            longitude=origin.longitude,
        )

    def route(self, origin: GeoPoint, destination: GeoPoint) -> RouteEstimate:
        raise ProviderNotConfiguredError(self.name)

    @staticmethod
    def _nearby_payload(
        kind: str,
        radius_km: float,
        latitude: float,
        longitude: float,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "maxResultCount": 20,
            "rankPreference": "DISTANCE",
            "locationRestriction": {
                "circle": {
                    "center": {"latitude": latitude, "longitude": longitude},
                    "radius": radius_km * 1000,
                }
            },
        }
        if kind == "any":
            payload["includedTypes"] = [
                "hospital",
                "general_hospital",
                "medical_clinic",
                "medical_center",
                "pharmacy",
                "medical_lab",
                "doctor",
            ]
        else:
            payload["includedTypes"] = _KIND_TO_GOOGLE_TYPES[kind]
        return payload

    @staticmethod
    def _text_payload(location: str, kind: str) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "textQuery": f"{_KIND_QUERY[kind]} in {location}",
            "pageSize": 20,
        }
        if kind != "any":
            payload["includedType"] = _KIND_TO_GOOGLE_TYPES[kind][0]
            payload["strictTypeFiltering"] = False
        return payload

    def _request_json(self, operation: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        body = json.dumps(payload).encode("utf-8")
        request = Request(
            f"{self.base_url}/{operation}",
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "X-Goog-Api-Key": self.api_key,
                "X-Goog-FieldMask": _GOOGLE_FIELD_MASK,
            },
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                raw = response.read()
        except HTTPError as error:
            raw = error.read()
            detail = _google_error_detail(raw).replace(self.api_key, "[redacted]")
            raise CareProviderError(
                f"Google Places API rejected the request (HTTP {error.code}): {detail}"
            ) from error
        except (URLError, socket.timeout, TimeoutError) as error:
            raise CareProviderError(f"Google Places API could not be reached: {type(error).__name__}") from error

        try:
            parsed = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise CareProviderError("Google Places API returned invalid JSON.") from error
        if not isinstance(parsed, dict):
            raise CareProviderError("Google Places API returned an unexpected response.")
        return parsed

    @staticmethod
    def _normalize(
        place: Dict[str, Any],
        requested_kind: str,
        origin: Optional[tuple],
    ) -> Optional[Facility]:
        if place.get("businessStatus") == "CLOSED_PERMANENTLY":
            return None
        coordinates = place.get("location") or {}
        latitude = coordinates.get("latitude")
        longitude = coordinates.get("longitude")
        if not isinstance(latitude, (int, float)) or not isinstance(longitude, (int, float)):
            return None

        display_name = place.get("displayName") or {}
        name = display_name.get("text") if isinstance(display_name, dict) else None
        if not isinstance(name, str) or not name.strip():
            name = "Healthcare facility"

        google_types = place.get("types") if isinstance(place.get("types"), list) else []
        primary_type = place.get("primaryType")
        kind = _normalized_kind(primary_type, google_types, requested_kind)
        distance = None
        if origin is not None:
            distance = round(_distance_km(origin[0], origin[1], latitude, longitude), 3)

        regular_hours = place.get("regularOpeningHours") or {}
        current_hours = place.get("currentOpeningHours") or {}
        descriptions = regular_hours.get("weekdayDescriptions")
        if not isinstance(descriptions, list):
            descriptions = None
        open_now = current_hours.get("openNow")
        if not isinstance(open_now, bool):
            open_now = regular_hours.get("openNow")
        if not isinstance(open_now, bool):
            open_now = None

        rating = place.get("rating")
        rating_count = place.get("userRatingCount")
        return Facility(
            id=str(place.get("id") or f"google:{latitude}:{longitude}"),
            name=name.strip(),
            kind=kind,
            latitude=float(latitude),
            longitude=float(longitude),
            address=_optional_string(place.get("formattedAddress")),
            distance_km=distance,
            rating=float(rating) if isinstance(rating, (int, float)) else None,
            user_rating_count=int(rating_count) if isinstance(rating_count, int) else None,
            phone=_optional_string(place.get("internationalPhoneNumber")),
            website=_optional_string(place.get("websiteUri")),
            maps_url=_optional_string(place.get("googleMapsUri")),
            opening_hours=descriptions,
            open_now=open_now,
            source="Google Places public listing",
            provider="google",
        )


def _normalized_kind(primary_type: Any, google_types: List[Any], fallback: str) -> str:
    values = [primary_type, *google_types]
    if "hospital" in values or "general_hospital" in values:
        return "hospital"
    if "medical_clinic" in values or "medical_center" in values:
        return "clinic"
    if "pharmacy" in values:
        return "pharmacy"
    if "medical_lab" in values:
        return "laboratory"
    if "doctor" in values:
        return "doctor"
    if fallback == "lab":
        return "laboratory"
    return fallback if fallback != "any" else "healthcare"


def _optional_string(value: Any) -> Optional[str]:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _timeout_from_env() -> float:
    try:
        return min(max(float(os.environ.get("CARE_PROVIDER_TIMEOUT_SECONDS", "12")), 2.0), 30.0)
    except ValueError:
        return 12.0


def _google_error_detail(raw: bytes) -> str:
    try:
        payload = json.loads(raw.decode("utf-8"))
        error = payload.get("error", {}) if isinstance(payload, dict) else {}
        status = error.get("status")
        message = error.get("message")
        if status and message:
            return f"{status}: {message}"
        if message:
            return str(message)
    except (UnicodeDecodeError, json.JSONDecodeError):
        pass
    return "request rejected; verify Places API (New), billing, key restrictions, and quota"


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
