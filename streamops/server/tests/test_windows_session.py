from streamops.server.platform.windows.session import DesktopSessionInfo, NO_ACTIVE_CONSOLE_SESSION


def test_matching_console_session_is_interactive() -> None:
    assert DesktopSessionInfo(1, 1).is_interactive is True


def test_service_and_disconnected_sessions_are_not_interactive() -> None:
    assert DesktopSessionInfo(0, 1).is_interactive is False
    assert DesktopSessionInfo(1, NO_ACTIVE_CONSOLE_SESSION).is_interactive is False
