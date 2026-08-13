"""CareNavigationService — the only entry the API should call.

Distance is computed here so every provider is ranked the same way.
Nothing in this module reads the patient timeline or safety report.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from care.models import FACILITY_KINDS, Facility, GeoPoint, haversine_km, pack_facilities
from care.providers.base import ProviderNotConfiguredError, ProviderUnavailableError


class CareNavigationError(RuntimeError):
    def __init__(self, message: str, *, code: str, http_status: int = 502) -> None:
        super().__init__(message)
        self.code = code
        self.http_status = http_status


class CareNavigationService:
    def __init__(self, provider: Any) -> None:
        self.provider = provider

    @property
    def provider_name(self) -> str:
        return getattr(self.provider, "name", "unknown")

    def geocode(self, query: str) -> GeoPoint:
        text = (query or "").strip()
        if len(text) < 2:
            raise CareNavigationError(
                "Enter a city, neighbourhood, or postcode.",
                code="location_required",
                http_status=422,
            )
        try:
            point = self.provider.geocode(text)
        except ProviderUnavailableError as exc:
            raise CareNavigationError(
                "Location lookup is temporarily unavailable. Please try again shortly.",
                code="geocoder_unavailable",
                http_status=503,
            ) from exc
        if point is None:
            raise CareNavigationError(
                f"We couldn't find “{text}”. Try a city name or postcode.",
                code="location_not_found",
                http_status=422,
            )
        return point

    def search_facilities(
        self,
        *,
        location: str,
        kind: str = "any",
        radius_km: float = 8.0,
    ) -> Dict[str, Any]:
        chosen = kind if kind in FACILITY_KINDS else "any"
        radius_m = int(max(1.0, min(50.0, radius_km)) * 1000)
        origin = self.geocode(location)
        try:
            raw: List[Facility] = self.provider.search_nearby(origin, chosen, radius_m)
        except ProviderUnavailableError as exc:
            raise CareNavigationError(
                "The facility directory is temporarily unavailable. Please try again shortly.",
                code="directory_unavailable",
                http_status=503,
            ) from exc
        facilities: List[Facility] = []
        for item in raw:
            item.distance_km = round(
                haversine_km(origin.latitude, origin.longitude, item.latitude, item.longitude),
                2,
            )
            if chosen != "any" and item.kind != chosen:
                continue
            facilities.append(item)
        facilities.sort(key=lambda f: (f.distance_km is None, f.distance_km or 0, f.name.lower()))
        return pack_facilities(
            query=location,
            kind=chosen,
            origin=origin,
            facilities=facilities[:25],
            provider=self.provider_name,
        )

    def calculate_distance(self, origin: GeoPoint, destination: GeoPoint) -> float:
        return round(
            haversine_km(origin.latitude, origin.longitude, destination.latitude, destination.longitude),
            2,
        )

    def get_route(self, origin_query: str, destination_query: str) -> Dict[str, Any]:
        origin = self.geocode(origin_query)
        destination = self.geocode(destination_query)
        try:
            estimate = self.provider.route(origin, destination)
        except ProviderUnavailableError as exc:
            raise CareNavigationError(
                "Routing estimates are temporarily unavailable. Please try again shortly.",
                code="router_unavailable",
                http_status=503,
            ) from exc
        payload = estimate.to_dict()
        payload["disclaimer"] = (
            "Distance is a directory estimate, not live traffic or appointment availability."
        )
        return payload


def build_provider(name: Optional[str] = None) -> Any:
    chosen = (name or os.environ.get("CARE_NAVIGATION_PROVIDER") or "osm").strip().lower()
    if chosen in {"osm", "openstreetmap"}:
        from care.providers.osm import OsmProvider

        return OsmProvider()
    if chosen in {"mapbox"}:
        from care.providers.mapbox import MapboxProvider

        return MapboxProvider()
    if chosen in {"google", "google_maps"}:
        from care.providers.google import GoogleProvider

        return GoogleProvider()
    raise CareNavigationError(
        "CARE_NAVIGATION_PROVIDER must be osm, mapbox, or google.",
        code="provider_invalid",
        http_status=503,
    )


def get_care_service(provider: Any = None) -> CareNavigationService:
    try:
        return CareNavigationService(provider or build_provider())
    except ProviderNotConfiguredError as exc:
        raise CareNavigationError(
            str(exc),
            code="provider_not_configured",
            http_status=503,
        ) from exc
