from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import aiohttp
from aiohttp import ClientTimeout

from app.core.clients.chatgpt_images import (
    ChatGPTImageConversationRequest,
    ChatGPTImageConversationResult,
    GeneratedImageAsset,
)
from app.core.clients.http import get_http_client
from app.core.config.settings import get_settings
from app.core.types import JsonObject


class ChatGPTImageWorkerError(Exception):
    def __init__(self, code: str, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


class ChatGPTImageWorkerClient:
    async def disconnect_account_session(self, *, account_id: str) -> None:
        await self._request_json(
            "DELETE",
            f"/internal/accounts/{account_id}/session",
            allow_empty=True,
        )

    async def execute_conversation(
        self,
        *,
        account_id: str,
        proxy_url: str | None,
        request: ChatGPTImageConversationRequest,
        login_email: str | None = None,
        password: str | None = None,
    ) -> ChatGPTImageConversationResult:
        payload = {
            "proxyUrl": proxy_url,
            "request": _serialize_conversation_request(request),
            "credentials": (
                {
                    "loginEmail": login_email,
                    "password": password,
                }
                if login_email and password
                else None
            ),
        }
        response = await self._request_json(
            "POST",
            f"/internal/accounts/{account_id}/execute",
            json_payload=payload,
        )
        if not isinstance(response, dict):
            raise ChatGPTImageWorkerError("invalid_worker_response", "Worker execute response was invalid")
        conversation_id = _json_string(response, "conversationId")
        assistant_message_id = _json_string(response, "assistantMessageId")
        parent_message_id = _json_string(response, "parentMessageId")
        images_raw = response.get("images")
        if (
            conversation_id is None
            or assistant_message_id is None
            or parent_message_id is None
            or not isinstance(images_raw, list)
        ):
            raise ChatGPTImageWorkerError("invalid_worker_response", "Worker execute response was incomplete")
        images: list[GeneratedImageAsset] = []
        for image in images_raw:
            if not isinstance(image, dict):
                raise ChatGPTImageWorkerError("invalid_worker_response", "Worker returned an invalid image payload")
            data_url = _json_string(image, "dataUrl")
            mime_type = _json_string(image, "mimeType")
            filename = _json_string(image, "filename")
            file_id = _json_string(image, "fileId")
            if data_url is None or mime_type is None or filename is None or file_id is None:
                raise ChatGPTImageWorkerError("invalid_worker_response", "Worker returned an incomplete image payload")
            images.append(
                GeneratedImageAsset(
                    data_url=data_url,
                    mime_type=mime_type,
                    filename=filename,
                    file_id=file_id,
                    original_gen_id=image.get("originalGenId") if isinstance(image.get("originalGenId"), str) else None,
                    revised_prompt=image.get("revisedPrompt") if isinstance(image.get("revisedPrompt"), str) else None,
                )
            )
        assistant_text = response.get("assistantText") if isinstance(response.get("assistantText"), str) else None
        return ChatGPTImageConversationResult(
            conversation_id=conversation_id,
            assistant_message_id=assistant_message_id,
            parent_message_id=parent_message_id,
            assistant_text=assistant_text,
            images=tuple(images),
        )

    async def _request_json(
        self,
        method: str,
        path: str,
        *,
        json_payload: JsonObject | None = None,
        allow_empty: bool = False,
    ) -> JsonObject:
        client = get_http_client()
        url = f"{get_settings().image_worker_base_url.rstrip('/')}{path}"
        headers = {
            "Authorization": f"Bearer {get_settings().image_worker_token}",
            "Accept": "application/json",
        }
        if json_payload is not None:
            headers["Content-Type"] = "application/json"
        try:
            async with client.session.request(
                method,
                url,
                headers=headers,
                json=json_payload,
                timeout=ClientTimeout(total=90.0),
            ) as response:
                text = await response.text()
                if response.status >= 400:
                    payload = _try_parse_json(text)
                    if isinstance(payload, dict):
                        error = payload.get("error")
                        if isinstance(error, dict):
                            code = error.get("code")
                            message = error.get("message")
                            if isinstance(code, str) and isinstance(message, str):
                                raise ChatGPTImageWorkerError(code, message, status_code=response.status)
                    raise ChatGPTImageWorkerError(
                        "worker_request_failed",
                        text.strip() or f"Worker request failed with status {response.status}",
                        status_code=response.status,
                    )
                if not text.strip():
                    if allow_empty:
                        return {}
                    raise ChatGPTImageWorkerError("invalid_worker_response", "Worker returned an empty response")
                payload = _try_parse_json(text)
                if not isinstance(payload, dict):
                    raise ChatGPTImageWorkerError("invalid_worker_response", "Worker returned non-JSON data")
                return payload
        except (aiohttp.ClientError, TimeoutError) as exc:
            base_url = get_settings().image_worker_base_url.rstrip("/")
            raise ChatGPTImageWorkerError(
                "image_worker_unavailable",
                f"ChatGPT Images worker is unavailable at {base_url}",
            ) from exc


def _serialize_conversation_request(request: ChatGPTImageConversationRequest) -> JsonObject:
    return {
        "model": request.model,
        "prompt": request.prompt,
        "conversationId": request.conversation_id,
        "parentMessageId": request.parent_message_id,
        "timezoneOffsetMin": request.timezone_offset_min,
        "timezone": request.timezone,
        "clientContext": request.client_context,
        "attachments": [
            {
                "dataUrl": attachment.data_url,
                "mimeType": attachment.mime_type,
                "filename": attachment.filename,
            }
            for attachment in request.attachments
        ],
        "editTarget": (
            {
                "fileId": request.edit_target.file_id,
                "originalGenId": request.edit_target.original_gen_id,
            }
            if request.edit_target is not None
            else None
        ),
    }


def _try_parse_json(text: str) -> Any:
    import json

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _json_string(payload: Mapping[str, object], key: str) -> str | None:
    value = payload.get(key)
    if isinstance(value, str) and value.strip():
        return value
    return None
