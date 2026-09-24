from __future__ import annotations

import asyncio
import time

from fastapi.testclient import TestClient
from PIL import Image

from streamops.server.app import create_app
from streamops.server.errors import ScreenCaptureError, WrongDesktopSessionError
from streamops.server.services import ScreenCaptureService

from .conftest import FakeCaptureBackend


def test_latest_returns_404_before_first_capture(server_config) -> None:
    service = ScreenCaptureService(FakeCaptureBackend(), server_config.data_dir, 0.5)
    app = create_app(server_config, capture_service=service, manage_runtime=False)

    with TestClient(app) as client:
        response = client.get("/api/v1/screen/latest")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "no_capture"


def test_wrong_desktop_session_has_specific_error_code(server_config) -> None:
    class WrongSessionBackend(FakeCaptureBackend):
        def start(self) -> None:
            raise WrongDesktopSessionError(0, 1)

        def capture(self, timeout: float):
            raise WrongDesktopSessionError(0, 1)

    service = ScreenCaptureService(WrongSessionBackend(), server_config.data_dir, 0.5)
    app = create_app(server_config, capture_service=service, manage_runtime=False)

    with TestClient(app) as client:
        response = client.post("/api/v1/screen/capture")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "wrong_desktop_session"
    assert "current session 0, active session 1" in response.json()["error"]["message"]


def test_capture_and_latest_image_contract(server_config) -> None:
    service = ScreenCaptureService(FakeCaptureBackend(), server_config.data_dir, 0.5)
    app = create_app(server_config, capture_service=service, manage_runtime=False)

    with TestClient(app) as client:
        capture = client.post("/api/v1/screen/capture")
        latest = client.get(capture.json()["latest_url"])

    assert capture.status_code == 200
    assert capture.json()["width"] == 8
    assert capture.json()["height"] == 6
    assert latest.status_code == 200
    assert latest.headers["content-type"] == "image/png"
    assert latest.headers["cache-control"].startswith("no-store")
    assert latest.headers["x-capture-id"] == capture.json()["capture_id"]
    assert latest.content.startswith(b"\x89PNG")


def test_repeated_capture_gets_new_id(server_config) -> None:
    backend = FakeCaptureBackend(
        [Image.new("RGB", (4, 3), "red"), Image.new("RGB", (4, 3), "green")]
    )
    service = ScreenCaptureService(backend, server_config.data_dir, 0.5)
    app = create_app(server_config, capture_service=service, manage_runtime=False)

    with TestClient(app) as client:
        first = client.post("/api/v1/screen/capture").json()
        second = client.post("/api/v1/screen/capture").json()

    assert first["capture_id"] != second["capture_id"]
    assert first["latest_url"] != second["latest_url"]


def test_failed_capture_preserves_previous_image(server_config) -> None:
    backend = FakeCaptureBackend(
        [Image.new("RGB", (5, 4), "green"), ScreenCaptureError("capture unavailable")]
    )
    service = ScreenCaptureService(backend, server_config.data_dir, 0.5)
    app = create_app(server_config, capture_service=service, manage_runtime=False)

    with TestClient(app) as client:
        first = client.post("/api/v1/screen/capture")
        first_image = client.get(first.json()["latest_url"])
        failed = client.post("/api/v1/screen/capture")
        retained = client.get("/api/v1/screen/latest")

    assert failed.status_code == 503
    assert failed.json()["error"]["code"] == "capture_failed"
    assert retained.content == first_image.content
    assert retained.headers["x-capture-id"] == first.json()["capture_id"]


def test_storage_failure_preserves_previous_image(server_config, monkeypatch) -> None:
    backend = FakeCaptureBackend(
        [Image.new("RGB", (5, 4), "green"), Image.new("RGB", (5, 4), "red")]
    )
    service = ScreenCaptureService(backend, server_config.data_dir, 0.5)
    app = create_app(server_config, capture_service=service, manage_runtime=False)

    with TestClient(app) as client:
        first = client.post("/api/v1/screen/capture")
        first_image = client.get(first.json()["latest_url"])
        monkeypatch.setattr(
            "streamops.server.services.screen_capture.os.replace",
            lambda *_args: (_ for _ in ()).throw(OSError("disk unavailable")),
        )
        failed = client.post("/api/v1/screen/capture")
        retained = client.get("/api/v1/screen/latest")

    assert failed.status_code == 500
    assert failed.json()["error"]["code"] == "capture_storage_failed"
    assert retained.content == first_image.content
    assert retained.headers["x-capture-id"] == first.json()["capture_id"]


def test_capture_requests_are_serialized(server_config) -> None:
    class TrackingBackend(FakeCaptureBackend):
        def __init__(self) -> None:
            super().__init__()
            self.active = 0
            self.maximum_active = 0

        def capture(self, timeout: float):
            self.active += 1
            self.maximum_active = max(self.maximum_active, self.active)
            time.sleep(0.03)
            self.active -= 1
            return Image.new("RGB", (3, 2), "blue")

    backend = TrackingBackend()
    service = ScreenCaptureService(backend, server_config.data_dir, 0.5)
    service.start()
    try:
        asyncio.run(_capture_twice(service))
    finally:
        service.close()

    assert backend.maximum_active == 1


async def _capture_twice(service: ScreenCaptureService) -> None:
    first, second = await asyncio.gather(service.capture(), service.capture())
    assert first.capture_id != second.capture_id
