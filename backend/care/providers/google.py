"""Google Places API (New) care-directory adapter.

This module deliberately uses the REST API rather than a browser SDK: the
Google key remains on the server and every response is normalized to
``Facility`` before it reaches the medical/application layer.
"""

from __future__ import annotations

import json
import math
import os
import re
from typing import Any, Dict, List, Optional
from urllib.error import HTTPError
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
        "places.primaryTypeDisplayName",
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
        specialty: Optional[str] = None,
        availability: Optional[str] = None,
    ) -> List[Facility]:
        normalized_kind = (kind or "any").strip().lower()
        if normalized_kind not in _KIND_QUERY:
            raise ValueError(
                "Unsupported facility type. Use any, hospital, clinic, pharmacy, laboratory, or doctor."
            )
        try:
            radius_value = float(radius_km)
        except (TypeError, ValueError) as error:
            raise ValueError("radius_km must be a finite number.") from error
        if not math.isfinite(radius_value):
            raise ValueError("radius_km must be a finite number.")
        radius = min(max(radius_value, 1.0), 50.0)

        normalized_specialty = _normalized_specialty(specialty)
        normalized_availability = _normalized_availability(availability)
        if (latitude is None) != (longitude is None):
            raise ValueError("latitude and longitude must be supplied together.")
        place = location.strip()
        if latitude is not None and longitude is not None:
            latitude, longitude = _validated_coordinates(latitude, longitude)
            origin = (latitude, longitude)
            if normalized_specialty:
                payload = self._text_payload(
                    place or "selected location",
                    normalized_kind,
                    specialty=normalized_specialty,
                    latitude=latitude,
                    longitude=longitude,
                    radius_km=radius,
                )
                response = self._request_json("places:searchText", payload)
            else:
                payload = self._nearby_payload(normalized_kind, radius, latitude, longitude)
                response = self._request_json("places:searchNearby", payload)
        else:
            if not place:
                raise ValueError("A city/area or latitude/longitude is required.")
            payload = self._text_payload(place, normalized_kind, specialty=normalized_specialty)
            response = self._request_json("places:searchText", payload)
            origin = None

        places = response.get("places", [])
        if not isinstance(places, list):
            raise CareProviderError("Google Places returned an unexpected response shape.")
        facilities: List[Facility] = []
        for item in places:
            if not isinstance(item, dict):
                continue
            facility = self._normalize(
                item,
                normalized_kind,
                origin,
                specialty=normalized_specialty,
                availability=normalized_availability,
            )
            if facility is not None and (
                origin is None
                or facility.distance_km is None
                or facility.distance_km <= radius
            ):
                facilities.append(facility)

        # Specialty and availability are provider-directory matching signals,
        # never a claim of clinical suitability. Otherwise preserve the
        # distance-only behavior used by ordinary nearby searches.
        if normalized_specialty or normalized_availability:
            facilities.sort(
                key=lambda item: (
                    -(item.ranking_score or 0.0),
                    item.distance_km if item.distance_km is not None else math.inf,
                )
            )
        elif origin is not None:
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
    def _text_payload(
        location: str,
        kind: str,
        *,
        specialty: Optional[str] = None,
        latitude: Optional[float] = None,
        longitude: Optional[float] = None,
        radius_km: Optional[float] = None,
    ) -> Dict[str, Any]:
        search_term = specialty or _KIND_QUERY[kind]
        payload: Dict[str, Any] = {
            "textQuery": f"{search_term} in {location}",
            "pageSize": 20,
        }
        if kind != "any":
            payload["includedType"] = _KIND_TO_GOOGLE_TYPES[kind][0]
            payload["strictTypeFiltering"] = False
        if latitude is not None and longitude is not None and radius_km is not None:
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
        except OSError as error:
            # URLError, socket/TLS/timeout failures all subclass OSError, so a
            # transport problem stays a CareProviderError the caller can fall
            # back from instead of an unexpected 500-class crash.
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
        *,
        specialty: Optional[str] = None,
        availability: Optional[str] = None,
    ) -> Optional[Facility]:
        if place.get("businessStatus") == "CLOSED_PERMANENTLY":
            return None
        coordinates = place.get("location") or {}
        latitude = coordinates.get("latitude")
        longitude = coordinates.get("longitude")
        try:
            latitude, longitude = _validated_coordinates(latitude, longitude)
        except ValueError:
            # A malformed provider row must not make FastAPI fail while
            # serializing the entire otherwise-valid result set.
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
        specialty_match = _specialty_match(place, name, specialty) if specialty else None
        availability_match = _availability_match(normalized_availability=availability, descriptions=descriptions, open_now=open_now)
        ranking_score, ranking_reason = _ranking_details(
            specialty=specialty,
            specialty_match=specialty_match,
            availability=availability,
            availability_match=availability_match,
            distance=distance,
            rating=float(rating) if isinstance(rating, (int, float)) else None,
        )
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
            specialty=(f"{specialty} (directory search match)" if specialty else None),
            specialty_match=specialty_match,
            availability_match=availability_match,
            ranking_score=ranking_score,
            ranking_reason=ranking_reason,
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


def _normalized_specialty(value: Optional[str]) -> Optional[str]:
    if value is None or not value.strip():
        return None
    normalized = " ".join(value.strip().split())
    if len(normalized) > 80 or not all(character.isalnum() or character in " -/&" for character in normalized):
        raise ValueError("specialty contains unsupported characters or is too long.")
    return normalized


def _normalized_availability(value: Optional[str]) -> Optional[str]:
    normalized = (value or "").strip().lower().replace("-", "_")
    if normalized in {"", "any"}:
        return None
    if normalized not in {"today", "this_week", "evening", "weekend"}:
        raise ValueError("availability must be any, today, this_week, evening, or weekend.")
    return normalized


def _specialty_match(place: Dict[str, Any], name: str, specialty: str) -> float:
    display_type = place.get("primaryTypeDisplayName") or {}
    display_type_text = display_type.get("text") if isinstance(display_type, dict) else ""
    searchable = " ".join([
        name,
        str(place.get("primaryType") or ""),
        str(display_type_text or ""),
        " ".join(str(value) for value in place.get("types", []) or []),
    ]).lower().replace("_", " ")
    ignored = {"doctor", "physician", "clinical", "specialist", "or", "and"}
    tokens = [token.lower() for token in specialty.replace("/", " ").split() if token.lower() not in ignored]
    direct = sum(1 for token in tokens if token in searchable)
    # Google already returned the place for this specialty text query, so 0.6
    # is a provider relevance match; explicit words in the listing raise it.
    return round(min(1.0, 0.6 + (0.4 * direct / max(1, len(tokens)))), 2)


def _availability_match(
    *,
    normalized_availability: Optional[str],
    descriptions: Optional[List[str]],
    open_now: Optional[bool],
) -> Optional[bool]:
    if not normalized_availability:
        return None
    if normalized_availability == "today":
        return open_now
    if not descriptions:
        return None
    lowered = [str(value).lower() for value in descriptions]
    if normalized_availability == "this_week":
        return any("closed" not in value for value in lowered)
    if normalized_availability == "weekend":
        weekend_rows = [value for value in lowered if value.startswith(("saturday", "sunday"))]
        return any("closed" not in value for value in weekend_rows) if weekend_rows else None
    if normalized_availability == "evening":
        for value in lowered:
            if "24 hours" in value:
                return True
            pm_hours = [int(match.group(1)) for match in re.finditer(r"\b(\d{1,2})(?::\d{2})?\s*pm\b", value)]
            twenty_four_hour = [int(match.group(1)) for match in re.finditer(r"\b([01]?\d|2[0-3]):\d{2}\b", value)]
            if any(6 <= hour <= 11 for hour in pm_hours) or any(hour >= 18 for hour in twenty_four_hour):
                return True
        return False
    return None


def _ranking_details(
    *,
    specialty: Optional[str],
    specialty_match: Optional[float],
    availability: Optional[str],
    availability_match: Optional[bool],
    distance: Optional[float],
    rating: Optional[float],
) -> tuple:
    if not specialty and not availability:
        return None, None
    score = (specialty_match or 0.0) * 60
    if availability_match is True:
        score += 15
    elif availability_match is False:
        score -= 5
    if rating is not None:
        score += max(0.0, min(5.0, rating)) * 2
    if distance is not None:
        score -= min(distance, 50.0) * 2
    reasons = []
    if specialty:
        reasons.append(f"specialty search match {round((specialty_match or 0) * 100)}%")
    if distance is not None:
        reasons.append(f"{distance:g} km away")
    if rating is not None:
        reasons.append(f"rating {rating:g}/5")
    if availability:
        if availability_match is True:
            reasons.append(f"listed hours match {availability.replace('_', ' ')}")
        elif availability_match is False:
            reasons.append(f"listed hours do not match {availability.replace('_', ' ')}")
        else:
            reasons.append("availability not supplied by the directory")
    return round(score, 2), "; ".join(reasons)


def _validated_coordinates(latitude: Any, longitude: Any) -> tuple:
    """Return finite, in-range coordinates or reject malformed input.

    Python's JSON decoder accepts non-standard ``NaN`` values by default, and
    booleans are subclasses of integers. Letting either through can later make
    distance math or FastAPI's strict JSON encoder fail the whole request.
    """
    if (
        isinstance(latitude, bool)
        or isinstance(longitude, bool)
        or not isinstance(latitude, (int, float))
        or not isinstance(longitude, (int, float))
    ):
        raise ValueError("latitude and longitude must be finite numbers.")
    latitude_value = float(latitude)
    longitude_value = float(longitude)
    if not math.isfinite(latitude_value) or not math.isfinite(longitude_value):
        raise ValueError("latitude and longitude must be finite numbers.")
    if not -90.0 <= latitude_value <= 90.0:
        raise ValueError("latitude must be between -90 and 90.")
    if not -180.0 <= longitude_value <= 180.0:
        raise ValueError("longitude must be between -180 and 180.")
    return latitude_value, longitude_value


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
    # Floating-point rounding near antipodal points can put the haversine a
    # few ulps outside [0, 1], which would otherwise raise in sqrt().
    value = min(1.0, max(0.0, value))
    return radius * 2 * math.atan2(math.sqrt(value), math.sqrt(1 - value))
