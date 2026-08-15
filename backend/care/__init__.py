"""Provider-neutral care navigation.

The medical pipeline only consumes normalized Facility dictionaries. Provider
credentials, request formats, and provider-specific errors stay in this
package and are never exposed to the browser.
"""

from .errors import CareConfigurationError, CareProviderError
from .factory import get_care_provider
from .models import Facility
from .postprocess import finalize as finalize_facilities
from .specialty import suggest_specialty

__all__ = [
    "CareConfigurationError",
    "CareProviderError",
    "Facility",
    "finalize_facilities",
    "get_care_provider",
    "suggest_specialty",
]
