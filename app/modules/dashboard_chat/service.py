from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass

from app.core.openai.requests import ResponsesReasoning, ResponsesRequest
from app.core.types import JsonValue
from app.db.models import Account
from app.modules.dashboard_chat.repository import DashboardChatRepository
from app.modules.dashboard_chat.schemas import (
    DashboardChatImagePart,
    DashboardChatMessage,
    DashboardChatResponsesRequest,
    DashboardChatTextPart,
)
from app.modules.proxy.service import ProxyService


@dataclass(frozen=True, slots=True)
class DashboardChatPreparedRequest:
    payload: ResponsesRequest
    requested_account_id: str | None
    selected_account: Account | None


class InvalidAccountSelectionError(Exception):
    pass


class DashboardChatService:
    def __init__(self, repository: DashboardChatRepository, proxy_service: ProxyService) -> None:
        self._repository = repository
        self._proxy_service = proxy_service

    async def stream_responses(
        self,
        payload: DashboardChatResponsesRequest,
        headers: Mapping[str, str],
    ) -> AsyncIterator[str]:
        prepared = await self.prepare_request(payload)
        if prepared.selected_account is None:
            return self._proxy_service.stream_responses(
                prepared.payload,
                headers,
                on_account_selected=lambda account: _dashboard_chat_started_event(
                    mode="auto",
                    requested_account_id=None,
                    resolved_account_id=account.id,
                ),
            )
        return self._proxy_service.stream_responses_for_account(
            prepared.payload,
            headers,
            account=prepared.selected_account,
            start_event_payload=_dashboard_chat_started_event(
                mode="account",
                requested_account_id=prepared.requested_account_id,
                resolved_account_id=prepared.selected_account.id,
            ),
        )

    async def prepare_request(self, payload: DashboardChatResponsesRequest) -> DashboardChatPreparedRequest:
        selected_account: Account | None = None
        if payload.account_id is not None:
            selected_account = await self._repository.get_active_account(payload.account_id)
            if selected_account is None:
                raise InvalidAccountSelectionError("Selected account is unavailable")

        request_payload = ResponsesRequest(
            model=payload.model,
            instructions="",
            input=[_message_to_input_item(message) for message in payload.messages],
            reasoning=ResponsesReasoning(effort=payload.reasoning_effort) if payload.reasoning_effort else None,
            stream=True,
        )
        return DashboardChatPreparedRequest(
            payload=request_payload,
            requested_account_id=payload.account_id,
            selected_account=selected_account,
        )


def _message_to_input_item(message: DashboardChatMessage) -> dict[str, JsonValue]:
    return {
        "role": message.role,
        "content": [_message_part_to_content_part(message.role, part) for part in message.content],
    }


def _message_part_to_content_part(
    role: str,
    part: DashboardChatImagePart | DashboardChatTextPart,
) -> dict[str, JsonValue]:
    if isinstance(part, DashboardChatImagePart):
        return {
            "type": "input_image",
            "image_url": part.data_url,
        }
    return {
        "type": "output_text" if role == "assistant" else "input_text",
        "text": part.text,
    }


def _dashboard_chat_started_event(
    *,
    mode: str,
    requested_account_id: str | None,
    resolved_account_id: str | None,
) -> dict[str, JsonValue]:
    return {
        "type": "dashboard.chat.started",
        "mode": mode,
        "requestedAccountId": requested_account_id,
        "resolvedAccountId": resolved_account_id,
    }
