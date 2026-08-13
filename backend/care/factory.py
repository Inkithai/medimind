"""Care-provider selection from server environment."""

import os

from care.errors import CareConfigurationError
from care.providers.base import CareProvider
from care.providers.google import GoogleProvider


def get_care_provider() -> CareProvider:
    """Build the selected adapter without leaking credentials outside it."""
    name = os.environ.get("CARE_PROVIDER", "").strip().lower()
    if not name:
        raise CareConfigurationError(
            "CARE_PROVIDER is not set. Set CARE_PROVIDER=google and GOOGLE_MAPS_API_KEY."
        )
    if name == "google":
        return GoogleProvider()
    raise CareConfigurationError(
        f"Unsupported CARE_PROVIDER={name!r}. This build supports 'google'."
    )
