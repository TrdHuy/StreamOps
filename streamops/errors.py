"""Shared exception types for StreamOps."""


class StreamOpsError(Exception):
    """Base class for user-facing StreamOps failures."""


class ConfigError(StreamOpsError):
    """Raised when scene configuration is missing or invalid."""


class ObsConnectionError(StreamOpsError):
    """Raised when StreamOps cannot connect or authenticate with OBS."""


class ObsRequestError(StreamOpsError):
    """Raised when OBS rejects a websocket request."""


class VerificationError(StreamOpsError):
    """Raised when a scene cannot be verified."""
