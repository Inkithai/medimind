"""Mapbox adapter — configured only when MAPBOX_ACCESS_TOKEN is set."""

from __future__ import annotations

import os
from typing import List, Optional

from care.models import Facility, GeoPoint, RouteEstimate
from care.providers.base import ProviderNotConfiguredError


class MapboxProvider:
    name = "mapbox"

    def __init__(self) -> None:
        token = (os.environ.get("MAPBOX_ACCESS_TOKEN") or "").strip()
        if not token or token.startswith("your-"):
            raise ProviderNotConfiguredError(self.name)
        self.token = token

    def geocode(self, query: str) -> Optional[GeoPoint]:
        raise ProviderNotConfiguredError(self.name)

    def search_nearby(self, origin: GeoPoint, kind: str, radius_m: int) -> List[Facility]:
        raise ProviderNotConfiguredError(self.name)

    def route(self, origin: GeoPoint, destination: GeoPoint) -> RouteEstimate:
        raise ProviderNotConfiguredError(self.name)
