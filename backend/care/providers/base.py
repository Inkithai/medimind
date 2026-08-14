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


class ProviderUnavailableError(RuntimeError):
    """The upstream directory or geocoder failed (network, rate-limit, timeout).

    Provider adapters raise this instead of a bare RuntimeError so the service
    layer can translate it into a clean 503 response instead of an unhandled
    500. ``retryable`` marks transient failures that are worth failing over or
    retrying (429/5xx/timeouts), as opposed to permanent ones (bad request).
    """

    def __init__(self, message: str, *, retryable: bool = True) -> None:
        super().__init__(message)
        self.retryable = retryable


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


class CareProvider(Protocol):
    """Map-based directory search used by GET /api/v1/care/facilities."""

    name: str

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
        """Return normalized public facility listings near a place or point."""
        ...
