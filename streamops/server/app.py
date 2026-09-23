"""FastAPI application factory for streamops-node."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .api.health import router as health_router
from .api.screen import router as screen_router
from .config import ServerConfig
from .errors import CaptureStorageError, NoCaptureError, ScreenCaptureError
from .platform.windows import WindowsScreenCaptureBackend
from .services import ScreenCaptureService
from .services.runtime import RuntimeLease


WEB_ROOT = Path(__file__).with_name("web")


def create_app(
    config: ServerConfig,
    *,
    capture_service: ScreenCaptureService | None = None,
    manage_runtime: bool = True,
) -> FastAPI:
    service = capture_service or ScreenCaptureService(
        WindowsScreenCaptureBackend(config.output_index),
        config.data_dir,
        config.capture_timeout,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        lease = RuntimeLease.acquire(config) if manage_runtime else None
        try:
            service.start()
            yield
        finally:
            service.close()
            if lease is not None:
                lease.release()

    app = FastAPI(title="StreamOps Node", version="0.1.0", lifespan=lifespan)
    app.state.config = config
    app.state.capture_service = service
    app.include_router(health_router)
    app.include_router(screen_router)

    @app.exception_handler(NoCaptureError)
    async def no_capture_handler(_request, exc: NoCaptureError) -> JSONResponse:
        return _error_response(404, "no_capture", str(exc))

    @app.exception_handler(ScreenCaptureError)
    async def capture_error_handler(_request, exc: ScreenCaptureError) -> JSONResponse:
        return _error_response(503, "capture_failed", str(exc))

    @app.exception_handler(CaptureStorageError)
    async def storage_error_handler(_request, exc: CaptureStorageError) -> JSONResponse:
        return _error_response(500, "capture_storage_failed", str(exc))

    @app.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse(WEB_ROOT / "index.html", headers={"Cache-Control": "no-store"})

    app.mount("/assets", StaticFiles(directory=WEB_ROOT), name="web-assets")
    return app


def _error_response(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message}},
        headers={"Cache-Control": "no-store"},
    )
