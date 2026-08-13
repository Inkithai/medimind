"""Runtime integrations for live, permitted provider-directory sources.

No provider records are stored in this repository. Each source class returns
only records received from its external API during the current request.

Supported sources:
* Geoapify Geocoding + Places (default when GEOAPIFY_API_KEY is set)
* OpenStreetMap data, geocoded with Nominatim and searched through Overpass
* Google Places API (optional future source via PROVIDER_DIRECTORY_SOURCE)

The backend, never the browser, owns API credentials and performs requests.
"""

from __future__ import annotations

import json
import os
import socket
import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


DEFAULT_TIMEOUT_SECONDS = 12

# Public Nominatim and Overpass endpoints are shared infrastructure. Keep a
# small process-wide spacing gate so simultaneous browser sessions cannot burst
# requests into either service. A deployment can raise/lower the interval only
# within this conservative bound through OSM_MIN_REQUEST_INTERVAL_SECONDS.
_OSM_REQUEST_LOCK = threading.Lock()
_LAST_OSM_REQUEST_AT = 0.0


def _osm_min_request_interval_seconds() -> float:
    try:
        return max(0.2, min(5.0, float(os.environ.get("OSM_MIN_REQUEST_INTERVAL_SECONDS", "1.0"))))
    except ValueError:
        return 1.0


def _respect_osm_request_spacing() -> None:
    global _LAST_OSM_REQUEST_AT
    with _OSM_REQUEST_LOCK:
        now = time.monotonic()
        wait_seconds = _osm_min_request_interval_seconds() - (now - _LAST_OSM_REQUEST_AT)
        if wait_seconds > 0:
            time.sleep(wait_seconds)
        _LAST_OSM_REQUEST_AT = time.monotonic()


class ProviderSearchError(RuntimeError):
    """A safe, machine-readable failure from a live provider source."""

    def __init__(self, code: str, detail: str, *, retryable: bool, http_status: int = 502):
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.retryable = retryable
        self.http_status = http_status


@dataclass(frozen=True)
class SearchOrigin:
    label: str
    latitude: float
    longitude: float


@dataclass(frozen=True)
class ProviderSourcePayload:
    source_id: str
    source_label: str
    origin: Optional[SearchOrigin]
    records: List[Dict[str, Any]]
    no_results_message: Optional[str] = None


def _timeout_seconds() -> int:
    try:
        return max(3, min(30, int(os.environ.get("PROVIDER_SEARCH_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS))))
    except ValueError:
        return DEFAULT_TIMEOUT_SECONDS


def _read_json(
    url: str,
    *,
    method: str = "GET",
    headers: Optional[Dict[str, str]] = None,
    body: Optional[Dict[str, Any]] = None,
    form_body: Optional[Dict[str, str]] = None,
) -> Any:
    if body is not None and form_body is not None:
        raise ValueError("Use either JSON body or form body, not both.")
    encoded_body = json.dumps(body).encode("utf-8") if body is not None else None
    request_headers = {"Accept": "application/json", **(headers or {})}
    if form_body is not None:
        encoded_body = urlencode(form_body).encode("utf-8")
        request_headers.setdefault("Content-Type", "application/x-www-form-urlencoded")
    elif encoded_body is not None:
        request_headers.setdefault("Content-Type", "application/json")

    request = Request(url, data=encoded_body, headers=request_headers, method=method)
    try:
        with urlopen(request, timeout=_timeout_seconds()) as response:  # nosec B310: configured HTTPS public APIs only
            raw = response.read().decode("utf-8")
    except HTTPError as exc:
        # Do not expose an upstream response body: it can contain credentials,
        # project IDs, or source-specific implementation details.
        if exc.code in {408, 504}:
            raise ProviderSearchError(
                "provider_timeout",
                "The live provider directory took too long to respond. Please try again.",
                retryable=True,
                http_status=504,
            ) from exc
        if exc.code == 429:
            raise ProviderSearchError(
                "provider_rate_limited",
                "The live provider directory is rate-limited right now. Please try again shortly.",
                retryable=True,
                http_status=429,
            ) from exc
        if exc.code in (401, 403):
            raise ProviderSearchError(
                "provider_authorization_failed",
                "The live provider directory is not available because its server configuration was rejected.",
                retryable=False,
                http_status=503,
            ) from exc
        if 500 <= exc.code <= 599:
            raise ProviderSearchError(
                "provider_service_unavailable",
                "The live provider directory is temporarily unavailable. Please try again later.",
                retryable=True,
                http_status=503,
            ) from exc
        raise ProviderSearchError(
            "provider_request_failed",
            "The live provider directory could not complete this request.",
            retryable=True,
            http_status=502,
        ) from exc
    except (socket.timeout, TimeoutError):
        raise ProviderSearchError(
            "provider_timeout",
            "The live provider directory took too long to respond. Please try again.",
            retryable=True,
            http_status=504,
        )
    except URLError as exc:
        if isinstance(getattr(exc, "reason", None), socket.timeout):
            raise ProviderSearchError(
                "provider_timeout",
                "The live provider directory took too long to respond. Please try again.",
                retryable=True,
                http_status=504,
            ) from exc
        raise ProviderSearchError(
            "provider_network_error",
            "The live provider directory could not be reached. Check your connection and try again.",
            retryable=True,
            http_status=503,
        ) from exc

    try:
        return json.loads(raw)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ProviderSearchError(
            "provider_invalid_response",
            "The live provider directory returned an unreadable response. Please try again later.",
            retryable=True,
            http_status=502,
        ) from exc


class GooglePlacesSource:
    source_id = "google_places"
    source_label = "Google Places"

    def __init__(self, api_key: str):
        self.api_key = api_key

    def _geocode(self, location: str) -> Optional[SearchOrigin]:
        query = urlencode({"address": location, "key": self.api_key})
        payload = _read_json(f"https://maps.googleapis.com/maps/api/geocode/json?{query}")
        if not isinstance(payload, dict):
            raise ProviderSearchError(
                "provider_invalid_response",
                "Google Places returned an unexpected location response.",
                retryable=True,
            )
        status = payload.get("status")
        if status == "ZERO_RESULTS":
            return None
        if status != "OK":
            if status in {"OVER_QUERY_LIMIT", "OVER_DAILY_LIMIT", "RESOURCE_EXHAUSTED"}:
                raise ProviderSearchError(
                    "provider_rate_limited",
                    "Google Places is rate-limited right now. Please try again shortly.",
                    retryable=True,
                    http_status=429,
                )
            if status in {"REQUEST_DENIED", "INVALID_REQUEST"}:
                raise ProviderSearchError(
                    "provider_authorization_failed",
                    "Google Places rejected the backend directory configuration.",
                    retryable=False,
                    http_status=503,
                )
            raise ProviderSearchError(
                "provider_location_failed",
                "Google Places could not locate that city or area. Check the spelling and try again.",
                retryable=False,
                http_status=422,
            )
        results = payload.get("results")
        if not isinstance(results, list) or not results:
            return None
        result = results[0] if isinstance(results[0], dict) else {}
        geometry = result.get("geometry") if isinstance(result.get("geometry"), dict) else {}
        coordinates = geometry.get("location") if isinstance(geometry.get("location"), dict) else {}
        try:
            return SearchOrigin(
                label=str(result.get("formatted_address") or location),
                latitude=float(coordinates["lat"]),
                longitude=float(coordinates["lng"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ProviderSearchError(
                "provider_invalid_response",
                "Google Places returned a location without usable coordinates.",
                retryable=True,
            ) from exc

    def search(self, location: str, specialty: Dict[str, Any]) -> ProviderSourcePayload:
        origin = self._geocode(location)
        if origin is None:
            return ProviderSourcePayload(
                source_id=self.source_id,
                source_label=self.source_label,
                origin=None,
                records=[],
                no_results_message="Google Places could not locate that city or area. Check the spelling and try again.",
            )

        query = f"{specialty.get('provider_query') or 'doctor'} near {location}"
        payload = _read_json(
            "https://places.googleapis.com/v1/places:searchText",
            method="POST",
            headers={
                "X-Goog-Api-Key": self.api_key,
                "X-Goog-FieldMask": ",".join(
                    [
                        "places.id",
                        "places.displayName",
                        "places.formattedAddress",
                        "places.location",
                        "places.rating",
                        "places.userRatingCount",
                        "places.nationalPhoneNumber",
                        "places.internationalPhoneNumber",
                        "places.regularOpeningHours",
                        "places.currentOpeningHours",
                        "places.googleMapsUri",
                        "places.types",
                        "places.primaryType",
                    ]
                ),
            },
            body={
                "textQuery": query,
                "maxResultCount": 20,
                "locationBias": {
                    "circle": {
                        "center": {"latitude": origin.latitude, "longitude": origin.longitude},
                        "radius": 30000.0,
                    }
                },
            },
        )
        if not isinstance(payload, dict):
            raise ProviderSearchError(
                "provider_invalid_response",
                "Google Places returned an unexpected provider response.",
                retryable=True,
            )
        places = payload.get("places", [])
        if not isinstance(places, list):
            raise ProviderSearchError(
                "provider_invalid_response",
                "Google Places returned provider data in an unsupported format.",
                retryable=True,
            )
        return ProviderSourcePayload(
            source_id=self.source_id,
            source_label=self.source_label,
            origin=origin,
            records=[place for place in places if isinstance(place, dict)],
            no_results_message=(
                "No matching providers were returned by Google Places for this city or area. "
                "Try a broader area or the broader provider category shown above."
                if not places
                else None
            ),
        )


class OpenStreetMapSource:
    source_id = "openstreetmap"
    source_label = "OpenStreetMap (Nominatim + Overpass; © OpenStreetMap contributors)"

    def __init__(self, user_agent: str):
        if not user_agent.strip():
            raise ProviderSearchError(
                "provider_configuration_missing",
                "OpenStreetMap search requires OSM_NOMINATIM_USER_AGENT to identify this application to the public service.",
                retryable=False,
                http_status=503,
            )
        self.user_agent = user_agent.strip()
        self.nominatim_url = os.environ.get("OSM_NOMINATIM_URL", "https://nominatim.openstreetmap.org/search")
        self.overpass_url = os.environ.get("OSM_OVERPASS_URL", "https://overpass-api.de/api/interpreter")
        try:
            self.radius_meters = max(1000, min(50000, int(os.environ.get("OSM_PROVIDER_SEARCH_RADIUS_METERS", "20000"))))
        except ValueError:
            self.radius_meters = 20000

    @property
    def _headers(self) -> Dict[str, str]:
        return {"User-Agent": self.user_agent, "Accept-Language": "en"}

    def _geocode(self, location: str) -> Optional[SearchOrigin]:
        query = urlencode({"q": location, "format": "jsonv2", "limit": 1, "addressdetails": 1})
        _respect_osm_request_spacing()
        payload = _read_json(f"{self.nominatim_url}?{query}", headers=self._headers)
        if not isinstance(payload, list):
            raise ProviderSearchError(
                "provider_invalid_response",
                "OpenStreetMap returned an unexpected location response.",
                retryable=True,
            )
        if not payload:
            return None
        result = payload[0] if isinstance(payload[0], dict) else {}
        try:
            return SearchOrigin(
                label=str(result.get("display_name") or location),
                latitude=float(result["lat"]),
                longitude=float(result["lon"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ProviderSearchError(
                "provider_invalid_response",
                "OpenStreetMap returned a location without usable coordinates.",
                retryable=True,
            ) from exc

    def search(self, location: str, specialty: Dict[str, Any]) -> ProviderSourcePayload:
        origin = self._geocode(location)
        if origin is None:
            return ProviderSourcePayload(
                source_id=self.source_id,
                source_label=self.source_label,
                origin=None,
                records=[],
                no_results_message="OpenStreetMap could not locate that city or area. Check the spelling and try again.",
            )

        # The query only obtains real map records. Specialty selection happens
        # after normalization/ranking because OSM specialty tags are incomplete
        # in many regions; broad doctor/clinic/hospital results remain useful
        # when a narrowly tagged specialty is unavailable.
        query = f"""[out:json][timeout:15];
(
  nwr[\"amenity\"~\"^(doctors|clinic|hospital|pharmacy)$\"](around:{self.radius_meters},{origin.latitude},{origin.longitude});
  nwr[\"healthcare\"~\"^(doctor|clinic|hospital|pharmacy)$\"](around:{self.radius_meters},{origin.latitude},{origin.longitude});
);
out center tags;"""
        _respect_osm_request_spacing()
        payload = _read_json(
            self.overpass_url,
            method="POST",
            headers=self._headers,
            form_body={"data": query},
        )
        if not isinstance(payload, dict) or not isinstance(payload.get("elements"), list):
            raise ProviderSearchError(
                "provider_invalid_response",
                "OpenStreetMap returned provider data in an unsupported format.",
                retryable=True,
            )
        records = [record for record in payload["elements"] if isinstance(record, dict)]
        return ProviderSourcePayload(
            source_id=self.source_id,
            source_label=self.source_label,
            origin=origin,
            records=records,
            no_results_message=(
                "No nearby doctor, clinic, hospital, or pharmacy records were returned by OpenStreetMap. "
                "Try a broader area or a nearby city."
                if not records
                else None
            ),
        )


_GEOAPIFY_CATEGORIES = {
    "cardiology": "healthcare.clinic_or_praxis.cardiology,healthcare.clinic_or_praxis,healthcare.hospital",
    "pulmonology": "healthcare.clinic_or_praxis.pulmonology,healthcare.clinic_or_praxis,healthcare.hospital",
    "dermatology": "healthcare.clinic_or_praxis.dermatology,healthcare.clinic_or_praxis,healthcare.hospital",
    "pharmacy": "healthcare.pharmacy",
    "general_practice": "healthcare.clinic_or_praxis.general,healthcare.clinic_or_praxis,healthcare.hospital",
}


def _geoapify_key() -> Optional[str]:
    raw = (os.environ.get("GEOAPIFY_API_KEY") or "").strip()
    if not raw or raw.lower().startswith("your-"):
        return None
    return raw


def _osm_user_agent() -> str:
    return (
        os.environ.get("OSM_NOMINATIM_USER_AGENT")
        or os.environ.get("OSM_USER_AGENT")
        or "MediMind/1.0 (healthcare record assistant; https://github.com/Inkithai/medimind)"
    ).strip()


class GeoapifyPlacesSource:
    source_id = "geoapify"
    source_label = "Geoapify"

    def __init__(self, api_key: str):
        if not api_key:
            raise ProviderSearchError(
                "provider_configuration_missing",
                "Geoapify is selected but GEOAPIFY_API_KEY is not configured on the backend.",
                retryable=False,
                http_status=503,
            )
        self.api_key = api_key
        self.geocode_url = os.environ.get("GEOAPIFY_GEOCODE_URL", "https://api.geoapify.com/v1/geocode/search")
        self.places_url = os.environ.get("GEOAPIFY_PLACES_URL", "https://api.geoapify.com/v2/places")
        try:
            self.radius_meters = max(1000, min(50000, int(os.environ.get("OSM_PROVIDER_SEARCH_RADIUS_METERS", "20000"))))
        except ValueError:
            self.radius_meters = 20000

    def _geocode(self, location: str) -> Optional[SearchOrigin]:
        query = urlencode({"text": location, "format": "json", "limit": 1, "apiKey": self.api_key})
        payload = _read_json(f"{self.geocode_url}?{query}")
        if not isinstance(payload, dict):
            raise ProviderSearchError(
                "provider_invalid_response",
                "Geoapify returned an unexpected location response.",
                retryable=True,
            )
        results = payload.get("results")
        if not isinstance(results, list) or not results:
            return None
        hit = results[0] if isinstance(results[0], dict) else {}
        try:
            return SearchOrigin(
                label=str(hit.get("formatted") or hit.get("city") or location),
                latitude=float(hit["lat"]),
                longitude=float(hit["lon"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ProviderSearchError(
                "provider_invalid_response",
                "Geoapify returned a location without usable coordinates.",
                retryable=True,
            ) from exc

    def search(self, location: str, specialty: Dict[str, Any]) -> ProviderSourcePayload:
        origin = self._geocode(location)
        if origin is None:
            return ProviderSourcePayload(
                source_id=self.source_id,
                source_label=self.source_label,
                origin=None,
                records=[],
                no_results_message="Geoapify could not locate that city or area. Check the spelling and try again.",
            )
        specialty_id = str((specialty or {}).get("id") or "general_practice")
        categories = _GEOAPIFY_CATEGORIES.get(specialty_id) or _GEOAPIFY_CATEGORIES["general_practice"]
        query = urlencode(
            {
                "categories": categories,
                "filter": f"circle:{origin.longitude},{origin.latitude},{self.radius_meters}",
                "bias": f"proximity:{origin.longitude},{origin.latitude}",
                "limit": 40,
                "apiKey": self.api_key,
            }
        )
        payload = _read_json(f"{self.places_url}?{query}")
        if not isinstance(payload, dict) or not isinstance(payload.get("features"), list):
            raise ProviderSearchError(
                "provider_invalid_response",
                "Geoapify returned provider data in an unsupported format.",
                retryable=True,
            )
        records = [feature for feature in payload["features"] if isinstance(feature, dict)]
        return ProviderSourcePayload(
            source_id=self.source_id,
            source_label=self.source_label,
            origin=origin,
            records=records,
            no_results_message=(
                "No nearby clinic, doctor, or hospital records were returned by Geoapify. "
                "Try a broader area or a nearby city."
                if not records
                else None
            ),
        )


class HybridDirectorySource:
    """Geoapify first when keyed; OpenStreetMap otherwise. Never says a source failed."""

    def search(self, location: str, specialty: Dict[str, Any]) -> ProviderSourcePayload:
        key = _geoapify_key()
        if key:
            try:
                payload = GeoapifyPlacesSource(key).search(location, specialty)
                if payload.records:
                    return payload
            except ProviderSearchError:
                pass
        return OpenStreetMapSource(_osm_user_agent()).search(location, specialty)


def get_provider_source() -> Any:
    """Create the configured live provider source; never substitute mock data."""
    source = os.environ.get("PROVIDER_DIRECTORY_SOURCE", "auto").strip().lower()
    if source in {"", "auto", "hybrid"}:
        return HybridDirectorySource()
    if source in {"geoapify"}:
        key = _geoapify_key()
        if not key:
            raise ProviderSearchError(
                "provider_configuration_missing",
                "Geoapify is selected but GEOAPIFY_API_KEY is not configured on the backend.",
                retryable=False,
                http_status=503,
            )
        return GeoapifyPlacesSource(key)
    if source in {"google", "google_places", "googleplaces"}:
        api_key = os.environ.get("GOOGLE_PLACES_API_KEY", "").strip()
        if not api_key or api_key.startswith("your-"):
            raise ProviderSearchError(
                "provider_configuration_missing",
                "Google Places is selected but GOOGLE_PLACES_API_KEY is not configured on the backend.",
                retryable=False,
                http_status=503,
            )
        return GooglePlacesSource(api_key)
    if source in {"openstreetmap", "osm"}:
        return OpenStreetMapSource(_osm_user_agent())
    raise ProviderSearchError(
        "provider_configuration_invalid",
        "PROVIDER_DIRECTORY_SOURCE must be auto, geoapify, openstreetmap, or google_places.",
        retryable=False,
        http_status=503,
    )
