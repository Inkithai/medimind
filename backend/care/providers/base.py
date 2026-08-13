"""Provider contracts. Medical intelligence never imports these."""

from __future__ import annotations

from typing import List, Optional, Protocol

from care.models import Facility, GeoPoint, RouteEstimate


class ProviderNotConfiguredError(RuntimeError):
    def __init__(self, provider: str) -> None:
        self.provider = provider
        super().__init__(
            f"Care Navigation provider '{provider}' is selected but not configured."
        )


class GeocodingProvider(Protocol):
    name: str

    def geocode(self, query: str) -> Optional[GeoPoint]:
        ...


class FacilitySearchProvider(Protocol):
    name: str

    def search_nearby(
        self, origin: GeoPoint, kind: str, radius_m: int
    ) -> List[Facility]:
        ...


class RoutingProvider(Protocol):
    name: str

    def route(self, origin: GeoPoint, destination: GeoPoint) -> RouteEstimate:
        ...
