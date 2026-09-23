"""DXGI desktop capture for Windows."""

from __future__ import annotations

import platform
import time
from typing import Any

from ...errors import ScreenCaptureError


class WindowsScreenCaptureBackend:
    def __init__(self, output_index: int) -> None:
        self.output_index = output_index
        self._camera: Any | None = None

    def start(self) -> None:
        if self._camera is not None:
            return
        if platform.system() != "Windows":
            raise ScreenCaptureError("Screen capture is supported only on Windows.")
        try:
            import dxcam

            self._camera = dxcam.create(
                device_idx=0,
                output_idx=self.output_index,
                output_color="RGB",
                backend="dxgi",
                processor_backend="numpy",
            )
        except Exception as exc:
            self._camera = None
            raise ScreenCaptureError(
                f"Could not initialize DXGI output {self.output_index}: {exc}"
            ) from exc

    def capture(self, timeout: float) -> Any:
        try:
            return self._capture_once(timeout)
        except Exception as first_error:
            self.close()
            try:
                self.start()
                return self._capture_once(timeout)
            except Exception as retry_error:
                self.close()
                raise ScreenCaptureError(
                    f"DXGI capture failed after reinitializing output {self.output_index}: {retry_error}"
                ) from first_error

    def close(self) -> None:
        camera = self._camera
        self._camera = None
        if camera is not None:
            try:
                camera.release()
            except Exception:
                pass

    def _capture_once(self, timeout: float) -> Any:
        self.start()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            frame = self._camera.grab(new_frame_only=False)
            if frame is not None:
                return frame
            time.sleep(min(0.05, max(0.0, deadline - time.monotonic())))
        raise ScreenCaptureError(f"DXGI did not return a frame within {timeout:g} seconds.")
