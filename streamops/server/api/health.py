"""Node health endpoint."""

from fastapi import APIRouter, Request

from .. import SERVER_VERSION
from ..auth import require_access
from ..platform.windows import desktop_session_info


router = APIRouter(prefix="/api/v1", dependencies=[])


@router.get("/health", dependencies=[])
async def health(request: Request) -> dict[str, object]:
    await require_access()
    session = desktop_session_info()
    return {
        "status": "ok",
        "service": "streamops-node",
        "version": SERVER_VERSION,
        "capture_ready": bool(request.app.state.capture_service.ready),
        "capture_backend": request.app.state.capture_service.backend_name,
        "session_id": session.current_session_id,
        "active_console_session_id": session.active_console_session_id,
    }
