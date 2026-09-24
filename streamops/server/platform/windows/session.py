"""Windows desktop session discovery."""

from __future__ import annotations

import ctypes
from dataclasses import dataclass
import os


NO_ACTIVE_CONSOLE_SESSION = 0xFFFFFFFF


@dataclass(frozen=True)
class DesktopSessionInfo:
    current_session_id: int
    active_console_session_id: int

    @property
    def is_interactive(self) -> bool:
        return (
            self.active_console_session_id != NO_ACTIVE_CONSOLE_SESSION
            and self.current_session_id == self.active_console_session_id
        )


def desktop_session_info() -> DesktopSessionInfo:
    kernel32 = ctypes.windll.kernel32
    current_session = ctypes.c_uint()
    if not kernel32.ProcessIdToSessionId(os.getpid(), ctypes.byref(current_session)):
        raise ctypes.WinError()
    active_session = int(kernel32.WTSGetActiveConsoleSessionId())
    return DesktopSessionInfo(
        current_session_id=int(current_session.value),
        active_console_session_id=active_session,
    )
