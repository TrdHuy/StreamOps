from __future__ import annotations

import sys
from types import SimpleNamespace

from streamops.server.platform.windows.screen import WindowsScreenCaptureBackend


def test_dxgi_failure_recreates_camera_once(monkeypatch) -> None:
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

    cameras = [Camera(RuntimeError("access lost")), Camera(expected)]
    fake_dxcam = SimpleNamespace(create=lambda **_kwargs: cameras.pop(0))
    monkeypatch.setitem(sys.modules, "dxcam", fake_dxcam)
    monkeypatch.setattr("platform.system", lambda: "Windows")
    backend = WindowsScreenCaptureBackend(0)

    assert backend.capture(0.1) is expected
    assert not cameras
