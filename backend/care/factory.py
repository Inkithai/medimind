"""Care-provider selection from server environment.

The directory is designed to stay available without any paid API key:

* ``CARE_PROVIDER`` unset            -> OpenStreetMap (no key, no billing)
* ``CARE_PROVIDER=osm``              -> OpenStreetMap only
* ``CARE_PROVIDER=google``           -> Google Places, with an automatic
  OpenStreetMap fallback when the key is missing/placeholder or Google
  rejects the call (unless ``CARE_FALLBACK=off``)
"""

import logging
import os
from typing import List, Optional

from care.errors import CareConfigurationError, CareProviderError
from care.models import Facility
from care.providers.base import CareProvider
from care.providers.google import GoogleProvider
from care.providers.osm_directory import OpenStreetMapProvider

logger = logging.getLogger("care")

_OSM_NAMES = {"osm", "openstreetmap", "overpass"}
_GOOGLE_NAMES = {"google", "google_places", "places"}


class FallbackProvider:
    """Try a primary provider, then fall back to a keyless public directory.

    Provider-specific failures are logged for operators; the caller only ever
    receives normalized facilities or a provider-neutral error.
    """

    def __init__(self, primary: CareProvider, fallback: CareProvider) -> None:
        self.primary = primary
        self.fallback = fallback
        self.name = f"{primary.name}+{fallback.name}"

    def search(
        self,
        location: str,
        kind: str,
        radius_km: float,
        *,
        latitude: Optional[float] = None,
        longitude: Optional[float] = None,
    ) -> List[Facility]:
        try:
            results = self.primary.search(
                location, kind, radius_km, latitude=latitude, longitude=longitude
            )
            if results:
                return results
            logger.info(
                "care directory: %s returned no results, trying %s",
                self.primary.name,
                self.fallback.name,
            )
        except ValueError:
            # Invalid user input: the fallback would reject it identically.
            raise
        except CareProviderError as error:
            logger.warning(
                "care directory: %s failed (%s); falling back to %s",
                self.primary.name,
                error,
                self.fallback.name,
            )
        return self.fallback.search(
            location, kind, radius_km, latitude=latitude, longitude=longitude
        )


def get_care_provider() -> CareProvider:
    """Build the selected adapter without leaking credentials outside it."""
    name = os.environ.get("CARE_PROVIDER", "").strip().lower()
    fallback_enabled = os.environ.get("CARE_FALLBACK", "on").strip().lower() not in {
        "off",
        "false",
        "0",
        "no",
    }

    # Default and explicit OpenStreetMap: always available, needs no key.
    if not name or name in _OSM_NAMES:
        return OpenStreetMapProvider()

    if name in _GOOGLE_NAMES:
        try:
            google = GoogleProvider()
        except CareConfigurationError as error:
            if not fallback_enabled:
                raise
            logger.warning(
                "care directory: Google is not usable (%s); using OpenStreetMap instead.",
                error,
            )
            return OpenStreetMapProvider()
        if not fallback_enabled:
            return google
        return FallbackProvider(google, OpenStreetMapProvider())

    raise CareConfigurationError(
        f"Unsupported CARE_PROVIDER={name!r}. Supported values: 'osm' (default) or 'google'."
    )
