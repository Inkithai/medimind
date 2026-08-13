"""OpenStreetMap adapter: Nominatim geocoding + Overpass POI search.

Default free provider. Identify the app with CARE_USER_AGENT.

The public Overpass instances rate-limit shared cloud IPs aggressively, so
queries fail over across mirrors with a short backoff and identical lookups
are cached in-process. Transient upstream failures raise
ProviderUnavailableError so the service layer can answer with a clean 503
instead of an unhandled 500.
"""

from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable, Dict, Hashable, List, Optional, Tuple

from care.models import Facility, GeoPoint, RouteEstimate, haversine_km
from care.normalizer import normalize_osm_elements
from care.providers.base import ProviderUnavailableError

JsonFn = Callable[..., Any]

NOMINATIM_URL = os.environ.get("NOMINATIM_URL", "https://nominatim.openstreetmap.org/search")
DEFAULT_OVERPASS_URLS: Tuple[str, ...] = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
)
USER_AGENT = os.environ.get(
    "CARE_USER_AGENT",
    "MediMind/1.0 (care navigation; https://github.com/Inkithai/medimind)",
)
# Client timeout sits above the Overpass [timeout:20] directive so a slow but
# legitimate answer is read instead of cut off mid-stream.
HTTP_TIMEOUT_SECONDS = float(os.environ.get("CARE_HTTP_TIMEOUT", "25"))

# Transient statuses worth retrying or failing over on. Other 4xx responses
# mean the query itself is wrong, so retrying them would just burn quota.
_RETRYABLE_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})

_GEOCODE_CACHE_TTL = float(os.environ.get("CARE_GEOCODE_CACHE_TTL", "3600"))
_SEARCH_CACHE_TTL = float(os.environ.get("CARE_SEARCH_CACHE_TTL", "300"))

_MISSING = object()

_KIND_QUERY = {
    "hospital": 'nwr["amenity"="hospital"]',
    "clinic": 'nwr["amenity"~"^(clinic|doctors)$"]',
    "pharmacy": 'nwr["amenity"="pharmacy"]',
    "laboratory": 'nwr["healthcare"="laboratory"]',
    "any": 'nwr["amenity"~"^(hospital|clinic|doctors|pharmacy)$"]',
}


def _overpass_urls_from_env() -> List[str]:
    """OVERPASS_URLS (comma-separated) wins; OVERPASS_URL next; else defaults."""
    raw = os.environ.get("OVERPASS_URLS")
    if raw is not None:
        urls = [item.strip() for item in raw.split(",") if item.strip()]
        if urls:
            return urls
    single = (os.environ.get("OVERPASS_URL") or "").strip()
    if single:
        return [single]
    return list(DEFAULT_OVERPASS_URLS)


class _TTLCache:
    """Small thread-safe in-process cache.

    Directory and geocoding answers are slow-moving, and the OSM usage
    policies expect callers to cache repeated lookups instead of re-querying.
    """

    def __init__(self, ttl_seconds: float, max_entries: int = 512) -> None:
        self.ttl_seconds = max(0.0, ttl_seconds)
        self.max_entries = max(1, max_entries)
        self._store: Dict[Hashable, Tuple[float, Any]] = {}
        self._lock = threading.Lock()

    def get(self, key: Hashable) -> Any:
        if self.ttl_seconds <= 0:
            return None
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            expires_at, value = entry
            if expires_at <= time.monotonic():
                self._store.pop(key, None)
                return None
            return value

    def set(self, key: Hashable, value: Any) -> None:
        if self.ttl_seconds <= 0:
            return
        with self._lock:
            if len(self._store) >= self.max_entries:
                self._evict()
            self._store[key] = (time.monotonic() + self.ttl_seconds, value)

    def _evict(self) -> None:
        now = time.monotonic()
        expired = [key for key, (expires_at, _) in self._store.items() if expires_at <= now]
        for key in expired:
            self._store.pop(key, None)
        # dicts preserve insertion order: drop the oldest survivors first.
        while len(self._store) >= self.max_entries:
            self._store.pop(next(iter(self._store)))


class OsmProvider:
    name = "openstreetmap"

    def __init__(
        self,
        http_json: Optional[JsonFn] = None,
        *,
        overpass_urls: Optional[List[str]] = None,
        max_attempts_per_endpoint: int = 2,
        backoff_seconds: float = 0.4,
        geocode_cache_ttl: float = _GEOCODE_CACHE_TTL,
        search_cache_ttl: float = _SEARCH_CACHE_TTL,
    ) -> None:
        self._http_json = http_json or _fetch_json
        if overpass_urls:
            self._overpass_urls = [u for u in (item.strip() for item in overpass_urls) if u]
        else:
            self._overpass_urls = _overpass_urls_from_env()
        self._max_attempts = max(1, int(max_attempts_per_endpoint))
        self._backoff = max(0.0, float(backoff_seconds))
        self._geocode_cache = _TTLCache(geocode_cache_ttl)
        self._search_cache = _TTLCache(search_cache_ttl)

    def _call(self, urls: List[str], data: Optional[bytes] = None) -> Any:
        """Try each endpoint in order, retrying transient failures briefly."""
        last_error: Optional[ProviderUnavailableError] = None
        for url in urls:
            for attempt in range(self._max_attempts):
                try:
                    return self._http_json(url, data=data)
                except ProviderUnavailableError as exc:
                    last_error = exc
                    # Permanent failures (e.g. HTTP 400) mean the query itself
                    # is rejected — every mirror would answer the same way.
                    if not exc.retryable:
                        raise
                    if attempt + 1 >= self._max_attempts:
                        break
                    if self._backoff:
                        time.sleep(self._backoff)
        raise ProviderUnavailableError(
            "The facility directory is temporarily unavailable."
        ) from last_error

    def geocode(self, query: str) -> Optional[GeoPoint]:
        text = (query or "").strip()
        if len(text) < 2:
            return None
        key = ("geocode", text.casefold())
        hit = self._geocode_cache.get(key)
        if hit is not None:
            return None if hit is _MISSING else hit
        url = NOMINATIM_URL + "?" + urllib.parse.urlencode(
            {"q": text, "format": "json", "limit": 1}
        )
        payload = self._call([url])
        point: Optional[GeoPoint] = None
        if isinstance(payload, list) and payload:
            first = payload[0]
            try:
                point = GeoPoint(
                    latitude=float(first["lat"]),
                    longitude=float(first["lon"]),
                    label=str(first.get("display_name") or text),
                    provider=self.name,
                )
            except (KeyError, TypeError, ValueError):
                point = None
        self._geocode_cache.set(key, point if point is not None else _MISSING)
        return point

    def search_nearby(self, origin: GeoPoint, kind: str, radius_m: int) -> List[Facility]:
        clause = _KIND_QUERY.get(kind) or _KIND_QUERY["any"]
        around = f"(around:{int(radius_m)},{origin.latitude:.6f},{origin.longitude:.6f})"
        body = f"[out:json][timeout:20];({clause}{around};);out center tags;"
        key = ("overpass", body)
        payload = self._search_cache.get(key)
        if payload is None:
            payload = self._call(list(self._overpass_urls), data=body.encode("utf-8"))
            self._search_cache.set(key, payload)
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


def _fetch_json(url: str, data: Optional[bytes] = None) -> Any:
    """Single HTTP attempt. Failures surface as ProviderUnavailableError."""
    request = urllib.request.Request(
        url,
        data=data,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        method="POST" if data else "GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        raise ProviderUnavailableError(
            f"Directory endpoint returned HTTP {exc.code}.",
            retryable=exc.code in _RETRYABLE_STATUS,
        ) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ProviderUnavailableError(
            f"Directory endpoint unreachable: {exc}", retryable=True
        ) from exc
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        # Mirrors occasionally serve an HTML error page with a 200 status;
        # treat it as transient so the next mirror gets a chance.
        raise ProviderUnavailableError(
            "Directory endpoint returned an unreadable response.", retryable=True
        ) from exc
