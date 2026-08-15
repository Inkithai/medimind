"""Google Places API (New) care-directory adapter.

This module deliberately uses the REST API rather than a browser SDK: the
Google key remains on the server and every response is normalized to
``Facility`` before it reaches the medical/application layer.

Two rules hold everywhere in this file:

* No field is invented. A rating, phone number, address, or opening hour is
  emitted only when Google published it; otherwise the field stays ``None``
  and the UI renders "Not available".
* ``Facility.kind`` is always one of the five UI categories (or ``other``),
  so the category counts and the rendered cards can never disagree.
"""

import json
import math
import os
import socket
from typing import Any, Dict, List, Optional, Sequence, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import quote_plus
from urllib.request import Request, urlopen

from care.errors import CareConfigurationError, CareProviderError
from care.models import Facility


_GOOGLE_FIELD_MASK = ",".join(
    (
        "places.id",
        "places.displayName",
        "places.formattedAddress",
        "places.shortFormattedAddress",
        "places.location",
        "places.types",
        "places.primaryType",
        "places.primaryTypeDisplayName",
        "places.rating",
        "places.userRatingCount",
        "places.googleMapsUri",
        "places.websiteUri",
        "places.internationalPhoneNumber",
        "places.nationalPhoneNumber",
        "places.regularOpeningHours",
        "places.currentOpeningHours",
        "places.businessStatus",
    )
)

#: Canonical UI categories. ``other`` is the explicit bucket for a healthcare
#: place Google does not classify as one of the five — it is still shown under
#: "All" and counted, so totals always add up.
FACILITY_KINDS = ("hospital", "clinic", "pharmacy", "laboratory", "doctor", "other")

_KIND_TO_GOOGLE_TYPES = {
    "hospital": ["hospital", "general_hospital"],
    "clinic": ["medical_clinic", "medical_center"],
    "pharmacy": ["pharmacy", "drugstore"],
    "laboratory": ["medical_lab"],
    "lab": ["medical_lab"],
    "doctor": ["doctor", "dentist", "physiotherapist"],
}

_ANY_INCLUDED_TYPES = [
    "hospital",
    "general_hospital",
    "medical_clinic",
    "medical_center",
    "pharmacy",
    "drugstore",
    "medical_lab",
    "doctor",
    "dentist",
    "physiotherapist",
]

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
        if key.lower() in _PLACEHOLDER_KEYS:
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
        specialty: Optional[str] = None,
    ) -> List[Facility]:
        normalized_kind = (kind or "any").strip().lower()
        if normalized_kind not in _KIND_QUERY:
            raise ValueError(
                "Unsupported facility type. Use any, hospital, clinic, pharmacy, laboratory, or doctor."
            )
        radius = min(max(float(radius_km), 1.0), 50.0)
        specialty_term = (specialty or "").strip() or None

        if (latitude is None) != (longitude is None):
            raise ValueError("latitude and longitude must be supplied together.")

        origin: Optional[Tuple[float, float]] = None
        if latitude is not None and longitude is not None:
            origin = (latitude, longitude)
            if specialty_term:
                # A specialty is a free-text signal, so Nearby Search (which only
                # accepts place types) cannot express it. Text Search biased to the
                # same circle keeps the search area while honouring the specialty.
                payload = self._text_payload(
                    location.strip(),
                    normalized_kind,
                    specialty_term,
                    circle=(latitude, longitude, radius),
                )
                response = self._request_json("places:searchText", payload)
            else:
                payload = self._nearby_payload(normalized_kind, radius, latitude, longitude)
                response = self._request_json("places:searchNearby", payload)
        else:
            place = location.strip()
            if not place:
                raise ValueError("A city/area or latitude/longitude is required.")
            payload = self._text_payload(place, normalized_kind, specialty_term)
            response = self._request_json("places:searchText", payload)

        places = response.get("places", [])
        if not isinstance(places, list):
            raise CareProviderError("Google Places returned an unexpected response shape.")
        facilities: List[Facility] = []
        seen_ids = set()
        for item in places:
            if not isinstance(item, dict):
                continue
            facility = self._normalize(item, normalized_kind, origin, specialty_term)
            if facility is None or facility.id in seen_ids:
                continue
            seen_ids.add(facility.id)
            facilities.append(facility)

        if origin is not None and radius:
            # Text Search only biases towards the circle, so trim anything the
            # user would not consider "nearby" (10% tolerance for rounding).
            facilities = [
                facility
                for facility in facilities
                if facility.distance_km is None or facility.distance_km <= radius * 1.1
            ]

        # Google does not claim a medical ranking here. With coordinates,
        # ordering is distance-only; text searches retain Google's relevance
        # order and are presented as public listings.
        if origin is not None:
            facilities.sort(
                key=lambda item: item.distance_km if item.distance_km is not None else math.inf
            )
        return facilities

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
            payload["includedTypes"] = list(_ANY_INCLUDED_TYPES)
        else:
            payload["includedTypes"] = _KIND_TO_GOOGLE_TYPES[kind]
        return payload

    @staticmethod
    def _text_payload(
        location: str,
        kind: str,
        specialty: Optional[str] = None,
        circle: Optional[Tuple[float, float, float]] = None,
    ) -> Dict[str, Any]:
        subject = f"{specialty} {_KIND_QUERY[kind]}".strip() if specialty else _KIND_QUERY[kind]
        payload: Dict[str, Any] = {
            "textQuery": f"{subject} in {location}" if location else subject,
            "pageSize": 20,
        }
        if kind != "any":
            payload["includedType"] = _KIND_TO_GOOGLE_TYPES[kind][0]
            payload["strictTypeFiltering"] = False
        if circle is not None:
            latitude, longitude, radius_km = circle
            payload["locationBias"] = {
                "circle": {
                    "center": {"latitude": latitude, "longitude": longitude},
                    "radius": radius_km * 1000,
                }
            }
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
        origin: Optional[Tuple[float, float]],
        specialty: Optional[str] = None,
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
            # Never invent an identity: an unnamed listing is not actionable.
            return None
        name = name.strip()

        google_types = [value for value in (place.get("types") or []) if isinstance(value, str)]
        primary_type = place.get("primaryType")
        kind = normalize_kind(primary_type, google_types, requested_kind)
        distance = None
        if origin is not None:
            distance = round(_distance_km(origin[0], origin[1], latitude, longitude), 3)

        regular_hours = place.get("regularOpeningHours") or {}
        current_hours = place.get("currentOpeningHours") or {}
        descriptions = regular_hours.get("weekdayDescriptions")
        if not isinstance(descriptions, list) or not descriptions:
            descriptions = None
        else:
            descriptions = [line for line in descriptions if isinstance(line, str)] or None
        open_now = current_hours.get("openNow")
        if not isinstance(open_now, bool):
            open_now = regular_hours.get("openNow")
        if not isinstance(open_now, bool):
            open_now = None

        rating = place.get("rating")
        rating_count = place.get("userRatingCount")
        address = _optional_string(place.get("formattedAddress")) or _optional_string(
            place.get("shortFormattedAddress")
        )
        specialty_label = _specialty_label(place)
        return Facility(
            id=str(place.get("id") or f"google:{latitude}:{longitude}"),
            name=name,
            kind=kind,
            latitude=float(latitude),
            longitude=float(longitude),
            address=address,
            distance_km=distance,
            rating=float(rating) if isinstance(rating, (int, float)) else None,
            user_rating_count=int(rating_count) if isinstance(rating_count, int) else None,
            phone=_optional_string(place.get("internationalPhoneNumber"))
            or _optional_string(place.get("nationalPhoneNumber")),
            website=_optional_string(place.get("websiteUri")),
            maps_url=_optional_string(place.get("googleMapsUri"))
            or google_maps_url(name, address, latitude, longitude),
            opening_hours=descriptions,
            open_now=open_now,
            specialty=specialty_label,
            specialty_match=_specialty_match(specialty, name, google_types, specialty_label),
            source="Google Places public listing",
        )


def normalize_kind(primary_type: Any, google_types: Sequence[Any], fallback: str) -> str:
    """Map Google place types onto exactly one canonical UI category.

    The same function backs the category chips, the counts, and the rendered
    cards, so a listing can never be counted under a category it is not shown
    in (the "7 found / 0 shown" class of bug).
    """
    values = {value for value in (primary_type, *google_types) if isinstance(value, str)}
    if values & {"hospital", "general_hospital"}:
        return "hospital"
    if values & {"medical_clinic", "medical_center"}:
        return "clinic"
    if values & {"pharmacy", "drugstore"}:
        return "pharmacy"
    if values & {"medical_lab"}:
        return "laboratory"
    if values & {"doctor", "dentist", "physiotherapist", "chiropractor"}:
        return "doctor"
    normalized_fallback = (fallback or "").strip().lower()
    if normalized_fallback == "lab":
        return "laboratory"
    if normalized_fallback in FACILITY_KINDS:
        return normalized_fallback
    return "other"


def google_maps_url(
    name: Optional[str],
    address: Optional[str],
    latitude: float,
    longitude: float,
) -> str:
    """Build a Google Maps search URL from the facility's name + address/point.

    Used only when Google did not return a canonical ``googleMapsUri``. The
    coordinates keep the pin on the right building even when two facilities
    share a name.
    """
    parts = [part for part in (name, address) if part]
    query = ", ".join(parts) if parts else f"{latitude},{longitude}"
    return f"https://www.google.com/maps/search/?api=1&query={quote_plus(query)}"


def _specialty_label(place: Dict[str, Any]) -> Optional[str]:
    """Google's own primary-type label, e.g. "Dentist" — never a guess."""
    display = place.get("primaryTypeDisplayName")
    if isinstance(display, dict):
        return _optional_string(display.get("text"))
    return None


def _specialty_match(
    specialty: Optional[str],
    name: str,
    google_types: Sequence[str],
    specialty_label: Optional[str],
) -> Optional[bool]:
    """Whether the listing visibly matches the requested specialty.

    ``None`` means "not asked", so the UI shows nothing rather than implying a
    negative clinical judgement.
    """
    if not specialty:
        return None
    needle = specialty.strip().lower()
    if not needle:
        return None
    haystack = " ".join(
        [name.lower(), " ".join(google_types).lower(), (specialty_label or "").lower()]
    )
    # Match on the word stem so "gastroenterologist" also matches
    # "gastroenterology" in a facility name.
    stem = needle.rstrip("y").rstrip("ist").rstrip("s")[:8] or needle
    return stem in haystack


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
