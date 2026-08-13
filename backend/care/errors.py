"""Internal care-provider errors.

Routes log these messages for operators but return a provider-neutral message
to clients. API keys are never included in an exception message.
"""


class CareError(RuntimeError):
    """Base class for expected care-directory failures."""


class CareConfigurationError(CareError):
    """The selected provider is missing required server configuration."""


class CareProviderError(CareError):
    """The provider rejected or could not complete a directory request."""
