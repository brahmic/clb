from __future__ import annotations

from fastapi import APIRouter, Body, Depends, Request
from fastapi.responses import StreamingResponse

from app.core.auth.dependencies import set_dashboard_error_format, validate_dashboard_session
from app.core.exceptions import DashboardBadRequestError
from app.dependencies import DashboardImagesContext, get_dashboard_images_context
from app.modules.dashboard_images.schemas import DashboardImagesConversationRequest
from app.modules.dashboard_images.service import (
    AutoRoutingUnavailableError,
    InvalidAccountSelectionError,
)

router = APIRouter(
    prefix="/api/dashboard-images",
    tags=["dashboard"],
    dependencies=[Depends(validate_dashboard_session), Depends(set_dashboard_error_format)],
)


@router.post(
    "/conversation",
    responses={
        200: {
            "content": {
                "text/event-stream": {
                    "schema": {"type": "string"},
                }
            }
        }
    },
)
async def stream_dashboard_images_conversation(
    request: Request,
    payload: DashboardImagesConversationRequest = Body(...),
    context: DashboardImagesContext = Depends(get_dashboard_images_context),
) -> StreamingResponse:
    try:
        stream = await context.service.stream_conversation(payload, request.headers)
    except InvalidAccountSelectionError as exc:
        raise DashboardBadRequestError(str(exc), code=exc.code) from exc
    except AutoRoutingUnavailableError as exc:
        raise DashboardBadRequestError(str(exc), code=exc.code) from exc
    return StreamingResponse(stream, media_type="text/event-stream")
