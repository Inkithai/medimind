"""Care Navigation — decoupled from medical intelligence.

The medical pipeline (extract → timeline → safety → labs → Ask AI) never
imports this package. This module only helps a user find nearby facilities
after they choose to look. It does not diagnose or rank clinical quality.

Provider credentials, request formats, and provider-specific errors stay in
this package and are never exposed to the browser.
"""

from care.errors import CareConfigurationError, CareProviderError
from care.factory import FallbackProvider, get_care_provider
from care.models import Facility
from care.service import CareNavigationError, CareNavigationService, get_care_service

__all__ = [
    "CareConfigurationError",
    "CareNavigationError",
    "CareNavigationService",
    "CareProviderError",
    "Facility",
    "FallbackProvider",
    "get_care_provider",
    "get_care_service",
]
