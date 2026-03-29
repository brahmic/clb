from __future__ import annotations

from fastapi import APIRouter, Body, Depends, Request
from fastapi.responses import StreamingResponse

from app.core.auth.dependencies import set_dashboard_error_format, validate_dashboard_session
from app.core.exceptions import DashboardBadRequestError
from app.dependencies import DashboardChatContext, get_dashboard_chat_context
from app.modules.dashboard_chat.schemas import DashboardChatResponsesRequest
from app.modules.dashboard_chat.service import InvalidAccountSelectionError

router = APIRouter(
    prefix="/api/dashboard-chat",
    tags=["dashboard"],
    dependencies=[Depends(validate_dashboard_session), Depends(set_dashboard_error_format)],
)


@router.post(
    "/responses",
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
async def stream_dashboard_chat_responses(
    request: Request,
    payload: DashboardChatResponsesRequest = Body(...),
    context: DashboardChatContext = Depends(get_dashboard_chat_context),
) -> StreamingResponse:
    try:
        stream = await context.service.stream_responses(payload, request.headers)
    except InvalidAccountSelectionError as exc:
        raise DashboardBadRequestError(str(exc), code="invalid_account_selection") from exc
    return StreamingResponse(stream, media_type="text/event-stream")
