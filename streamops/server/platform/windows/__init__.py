"""Windows integrations for the node server."""

from .screen import WindowsScreenCaptureBackend
from .session import DesktopSessionInfo, desktop_session_info

__all__ = ["DesktopSessionInfo", "WindowsScreenCaptureBackend", "desktop_session_info"]
