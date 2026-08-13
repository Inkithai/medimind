"""Google adapter — configured only when GOOGLE_MAPS_API_KEY is set."""

from __future__ import annotations

import os
from typing import List, Optional

from care.models import Facility, GeoPoint, RouteEstimate
from care.providers.base import ProviderNotConfiguredError


class GoogleProvider:
    name = "google"

    def __init__(self) -> None:
        key = (os.environ.get("GOOGLE_MAPS_API_KEY") or "").strip()
        if not key or key.startswith("your-"):
            raise ProviderNotConfiguredError(self.name)
        self.api_key = key

    def geocode(self, query: str) -> Optional[GeoPoint]:
        raise ProviderNotConfiguredError(self.name)

    def search_nearby(self, origin: GeoPoint, kind: str, radius_m: int) -> List[Facility]:
        raise ProviderNotConfiguredError(self.name)

    def route(self, origin: GeoPoint, destination: GeoPoint) -> RouteEstimate:
        raise ProviderNotConfiguredError(self.name)
