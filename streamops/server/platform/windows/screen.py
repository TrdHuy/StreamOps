"""DXGI desktop capture for Windows."""

from __future__ import annotations

import platform
import time
from typing import Any

from ...errors import ScreenCaptureError, WrongDesktopSessionError
from .session import desktop_session_info


class WindowsScreenCaptureBackend:
    _BACKENDS = ("dxgi", "winrt")

    def __init__(self, output_index: int) -> None:
        self.output_index = output_index
        self._camera: Any | None = None
        self._backend_name: str | None = None

    @property
    def backend_name(self) -> str | None:
        return self._backend_name

    def start(self) -> None:
        if self._camera is not None:
            return
        backend_name = self._backend_name or self._BACKENDS[0]
        self._start_backend(backend_name)

    def _start_backend(self, backend_name: str) -> None:
        if platform.system() != "Windows":
            raise ScreenCaptureError("Screen capture is supported only on Windows.")
        session = desktop_session_info()
        if not session.is_interactive:
            raise WrongDesktopSessionError(
                session.current_session_id,
                session.active_console_session_id,
            )
        try:
            import dxcam

            self._camera = dxcam.create(
                device_idx=0,
                output_idx=self.output_index,
                output_color="RGB",
                backend=backend_name,
                processor_backend="numpy",
            )
        except Exception as exc:
            self._camera = None
            raise ScreenCaptureError(
                f"Could not initialize {backend_name.upper()} output {self.output_index}: {exc}"
            ) from exc
        self._backend_name = backend_name

    def capture(self, timeout: float) -> Any:
        backend_order = list(self._BACKENDS)
        if self._backend_name in backend_order:
            backend_order.remove(self._backend_name)
            backend_order.insert(0, self._backend_name)

        failures: list[tuple[str, Exception]] = []
        for backend_name in backend_order:
            if self._camera is None or self._backend_name != backend_name:
                self.close()
                try:
                    self._start_backend(backend_name)
                except WrongDesktopSessionError:
                    raise
                except Exception as exc:
                    failures.append((backend_name, exc))
                    continue
            try:
                return self._capture_once(timeout)
            except WrongDesktopSessionError:
                raise
            except Exception as exc:
                failures.append((backend_name, exc))
            finally:
                if failures and failures[-1][0] == backend_name:
                    self.close()

        details = "; ".join(f"{name}: {error}" for name, error in failures)
        last_error = failures[-1][1]
        raise ScreenCaptureError(
            f"Could not capture output {self.output_index} with DXGI or WinRT ({details})"
        ) from last_error

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
        backend_name = (self._backend_name or "capture").upper()
        raise ScreenCaptureError(
            f"{backend_name} did not return a frame within {timeout:g} seconds."
        )
