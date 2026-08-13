"""Care-directory provider adapters."""

from .base import CareProvider
from .google import GoogleProvider

__all__ = ["CareProvider", "GoogleProvider"]
