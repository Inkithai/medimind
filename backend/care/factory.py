"""Care-provider selection from server environment."""

import os

from care.errors import CareConfigurationError
from care.providers.base import CareProvider
from care.providers.google import GoogleProvider
from care.providers.osm import OsmProvider


def get_care_provider() -> CareProvider:
    """Build the selected adapter without leaking credentials outside it.

    Defaults to OpenStreetMap, which needs no API key. Set
    CARE_PROVIDER=google plus GOOGLE_MAPS_API_KEY to use Google Places.
    """
    name = os.environ.get("CARE_PROVIDER", "osm").strip().lower() or "osm"
    if name in ("osm", "openstreetmap", "overpass"):
        return OsmProvider()
    if name == "google":
        return GoogleProvider()
    raise CareConfigurationError(
        f"Unsupported CARE_PROVIDER={name!r}. This build supports 'osm' and 'google'."
    )
