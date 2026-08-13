"""Care Navigation — decoupled from medical intelligence.

The medical pipeline (extract → timeline → safety → labs → Ask AI) never
imports this package. This module only helps a user find nearby facilities
after they choose to look. It does not diagnose or rank clinical quality.
"""

from care.service import CareNavigationError, CareNavigationService, get_care_service

__all__ = ["CareNavigationError", "CareNavigationService", "get_care_service"]
