from fastapi.testclient import TestClient

from streamops.server.app import create_app
from streamops.server.errors import ScreenCaptureError
from streamops.server.services import ScreenCaptureService

from .conftest import FakeCaptureBackend


def test_health_reports_ready(server_config, capture_service: ScreenCaptureService) -> None:
    app = create_app(server_config, capture_service=capture_service, manage_runtime=False)

    with TestClient(app) as client:
        response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "streamops-node",
        "version": "0.1.0",
        "capture_ready": True,
    }


def test_web_ui_is_served(server_config, capture_service: ScreenCaptureService) -> None:
    app = create_app(server_config, capture_service=capture_service, manage_runtime=False)

    with TestClient(app) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert "StreamOps Node" in response.text
    assert response.headers["cache-control"] == "no-store"


def test_health_stays_online_when_desktop_capture_is_temporarily_unavailable(server_config) -> None:
    class UnavailableBackend(FakeCaptureBackend):
        def start(self) -> None:
            raise ScreenCaptureError("desktop unavailable")

        def capture(self, timeout: float):
            raise ScreenCaptureError("desktop unavailable")

    service = ScreenCaptureService(UnavailableBackend(), server_config.data_dir, 0.5)
    app = create_app(server_config, capture_service=service, manage_runtime=False)

    with TestClient(app) as client:
        health = client.get("/api/v1/health")
        capture = client.post("/api/v1/screen/capture")

    assert health.status_code == 200
    assert health.json()["capture_ready"] is False
    assert capture.status_code == 503
