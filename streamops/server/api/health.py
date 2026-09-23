"""Node health endpoint."""

from fastapi import APIRouter, Request

from .. import SERVER_VERSION
from ..auth import require_access


router = APIRouter(prefix="/api/v1", dependencies=[])


@router.get("/health", dependencies=[])
async def health(request: Request) -> dict[str, object]:
    await require_access()
    return {
        "status": "ok",
        "service": "streamops-node",
        "version": SERVER_VERSION,
        "capture_ready": bool(request.app.state.capture_service.ready),
    }
