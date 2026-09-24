from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from streamops.server.errors import ScreenCaptureError, WrongDesktopSessionError
from streamops.server.platform.windows.screen import WindowsScreenCaptureBackend
from streamops.server.platform.windows.session import DesktopSessionInfo


def test_dxgi_failure_falls_back_to_winrt(monkeypatch) -> None:
    expected = object()

    class Camera:
        def __init__(self, result) -> None:
            self.result = result
            self.released = False

        def grab(self, *, new_frame_only: bool):
            if isinstance(self.result, Exception):
                raise self.result
            return self.result

        def release(self) -> None:
            self.released = True

    dxgi_camera = Camera(RuntimeError("access lost"))
    winrt_camera = Camera(expected)
    cameras = [dxgi_camera, winrt_camera]
    created_backends = []

    def create(**kwargs):
        created_backends.append(kwargs["backend"])
        return cameras.pop(0)

    fake_dxcam = SimpleNamespace(create=create)
    monkeypatch.setitem(sys.modules, "dxcam", fake_dxcam)
    monkeypatch.setattr("platform.system", lambda: "Windows")
    monkeypatch.setattr(
        "streamops.server.platform.windows.screen.desktop_session_info",
        lambda: DesktopSessionInfo(1, 1),
    )
    backend = WindowsScreenCaptureBackend(0)

    assert backend.capture(0.1) is expected
    assert created_backends == ["dxgi", "winrt"]
    assert dxgi_camera.released is True
    assert winrt_camera.released is False
    assert backend.backend_name == "winrt"
    assert not cameras


def test_capture_error_reports_both_backends(monkeypatch) -> None:
    class Camera:
        def grab(self, *, new_frame_only: bool):
            raise RuntimeError("no frame")

        def release(self) -> None:
            pass

    monkeypatch.setitem(sys.modules, "dxcam", SimpleNamespace(create=lambda **_kwargs: Camera()))
    monkeypatch.setattr("platform.system", lambda: "Windows")
    monkeypatch.setattr(
        "streamops.server.platform.windows.screen.desktop_session_info",
        lambda: DesktopSessionInfo(1, 1),
    )
    backend = WindowsScreenCaptureBackend(0)

    with pytest.raises(ScreenCaptureError, match=r"DXGI or WinRT .*dxgi: .*winrt:"):
        backend.capture(0.1)


def test_wrong_session_fails_before_dxcam_import(monkeypatch) -> None:
    monkeypatch.setattr("platform.system", lambda: "Windows")
    monkeypatch.setattr(
        "streamops.server.platform.windows.screen.desktop_session_info",
        lambda: DesktopSessionInfo(0, 1),
    )
    monkeypatch.delitem(sys.modules, "dxcam", raising=False)
    backend = WindowsScreenCaptureBackend(0)

    with pytest.raises(WrongDesktopSessionError, match="current session 0, active session 1"):
        backend.start()

    assert "dxcam" not in sys.modules
