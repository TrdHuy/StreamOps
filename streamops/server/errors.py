"""Errors owned by the standalone StreamOps node server."""


class ServerError(Exception):
    """Base class for user-facing node server failures."""


class ServerConfigError(ServerError):
    """Raised when node server configuration is invalid."""


class RuntimeStateError(ServerError):
    """Raised when the node runtime cannot be started safely."""


class ScreenCaptureError(ServerError):
    """Raised when the Windows capture backend cannot produce an image."""


class WrongDesktopSessionError(ScreenCaptureError):
    """Raised when capture is attempted outside the active desktop session."""

    def __init__(self, current_session_id: int, active_session_id: int) -> None:
        self.current_session_id = current_session_id
        self.active_session_id = active_session_id
        super().__init__(
            "Screen capture requires the active Windows console session "
            f"(current session {current_session_id}, active session {active_session_id})."
        )


class CaptureStorageError(ServerError):
    """Raised when a captured image cannot be persisted."""


class NoCaptureError(ServerError):
    """Raised when no successful screen capture exists yet."""
