"""Screen capture endpoints."""

from fastapi import APIRouter, Depends, Request, Response

from ..auth import require_access
from ..services import ScreenCaptureService


router = APIRouter(prefix="/api/v1/screen", dependencies=[Depends(require_access)])


def _service(request: Request) -> ScreenCaptureService:
    return request.app.state.capture_service


@router.post("/capture")
async def capture_screen(request: Request) -> dict[str, object]:
    metadata = await _service(request).capture()
    return metadata.api_payload()


@router.get("/latest")
async def latest_screen(request: Request) -> Response:
    latest = _service(request).latest()
    metadata = latest.metadata
    return Response(
        content=latest.content,
        media_type=metadata.content_type,
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
            "X-Capture-Id": metadata.capture_id,
            "X-Captured-At": metadata.captured_at,
            "X-Image-Width": str(metadata.width),
            "X-Image-Height": str(metadata.height),
        },
    )
