"""Give the hardened OsmProvider the map-based ``CareProvider.search`` shape.

``OsmProvider`` (care/providers/osm.py) already carries the Overpass mirror
failover, retry/backoff, and TTL caching this project needs, but it speaks the
older ``geocode`` + ``search_nearby`` contract used by CareNavigationService.
``GET /api/v1/care/facilities`` instead expects the ``CareProvider`` protocol:
one ``search(location, kind, radius_km, latitude=, longitude=)`` call.

This adapter bridges the two rather than duplicating the networking, so the
keyless OpenStreetMap directory can serve map-confirmed searches and act as the
fallback when a commercial provider is unconfigured or rejects a request.
"""

from __future__ import annotations

from typing import List, Optional

from care.errors import CareProviderError
from care.models import Facility, GeoPoint, haversine_km
from care.providers.base import ProviderUnavailableError
from care.providers.osm import OsmProvider

# The wire accepts a few aliases the Overpass query builder does not.
_KIND_ALIASES = {
    "lab": "laboratory",
    "doctor": "clinic",
    "healthcare": "any",
    "": "any",
}

_SUPPORTED_KINDS = {"any", "hospital", "clinic", "pharmacy", "laboratory", "lab", "doctor", "healthcare"}

_MAX_RESULTS = 60


class OpenStreetMapProvider:
    """Keyless directory adapter backed by Nominatim + Overpass."""

    name = "openstreetmap"

    def __init__(self, provider: Optional[OsmProvider] = None) -> None:
        self._provider = provider or OsmProvider()

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
        if normalized_kind not in _SUPPORTED_KINDS:
            raise ValueError(
                "Unsupported facility type. Use any, hospital, clinic, pharmacy, laboratory, or doctor."
            )
        query_kind = _KIND_ALIASES.get(normalized_kind, normalized_kind)
        radius = min(max(float(radius_km), 1.0), 50.0)

        if (latitude is None) != (longitude is None):
            raise ValueError("latitude and longitude must be supplied together.")

        try:
            if latitude is not None and longitude is not None:
                origin = GeoPoint(
                    latitude=latitude,
                    longitude=longitude,
                    label=(location or "").strip() or "Selected location",
                    provider=self.name,
                )
            else:
                place = (location or "").strip()
                if not place:
                    raise ValueError("A city/area or latitude/longitude is required.")
                resolved = self._provider.geocode(place)
                if resolved is None:
                    # An unknown place is an empty directory, not a failure.
                    return []
                origin = resolved

            facilities = self._provider.search_nearby(
                origin, query_kind, int(round(radius * 1000))
            )
        except ProviderUnavailableError as error:
            # Translate into the error the care factory/route already handle.
            raise CareProviderError(str(error)) from error

        for facility in facilities:
            facility.distance_km = round(
                haversine_km(
                    origin.latitude, origin.longitude, facility.latitude, facility.longitude
                ),
                3,
            )
            if not facility.maps_url:
                facility.maps_url = facility.source_url
            facility.source = "OpenStreetMap public listing"

        facilities.sort(
            key=lambda item: item.distance_km if item.distance_km is not None else float("inf")
        )
        return facilities[:_MAX_RESULTS]
