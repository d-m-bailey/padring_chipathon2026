class IntegrationError(ValueError):
    """Base exception for deterministic integration/configuration errors."""


class ConfigError(IntegrationError):
    """Input configuration is invalid."""


class NotFinalizedError(IntegrationError):
    """The live specification explicitly leaves this behavior unresolved."""
