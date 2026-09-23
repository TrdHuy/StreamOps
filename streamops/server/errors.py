"""Errors owned by the standalone StreamOps node server."""


class ServerError(Exception):
    """Base class for user-facing node server failures."""


class ServerConfigError(ServerError):
    """Raised when node server configuration is invalid."""


class RuntimeStateError(ServerError):
    """Raised when the node runtime cannot be started safely."""


class ScreenCaptureError(ServerError):
    """Raised when the Windows capture backend cannot produce an image."""


class CaptureStorageError(ServerError):
    """Raised when a captured image cannot be persisted."""


class NoCaptureError(ServerError):
    """Raised when no successful screen capture exists yet."""
