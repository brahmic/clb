from __future__ import annotations

import asyncio
import base64
import binascii
import json
import logging
import re
import struct
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import cast
from urllib.parse import urlencode
from uuid import NAMESPACE_URL, uuid4, uuid5

import aiohttp

from app.core.clients.http import get_http_client
from app.core.config.settings import get_settings
from app.core.types import JsonObject, JsonValue
from app.core.utils.json_guards import is_json_list, is_json_mapping
from app.db.models import Account
from app.modules.proxy.helpers import _header_account_id

_DEFAULT_POLL_INTERVAL_SECONDS = 1.5
_DEFAULT_POLL_MAX_ATTEMPTS = 40
_DEFAULT_WEB_SESSION_TTL_SECONDS = 30 * 60
_CHATGPT_WEB_ORIGIN = "https://chatgpt.com"
_DEFAULT_WEB_USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:150.0) Gecko/20100101 Firefox/150.0"
_DEFAULT_WEB_CLIENT_VERSION = "prod-34ffa95763ddf2cc215bcd7545731a9818ca9a8b"
_DEFAULT_WEB_CLIENT_BUILD_NUMBER = "5583259"
_DEBUG_HEADER_ALLOWLIST = frozenset(
    {
        "accept",
        "content-type",
        "origin",
        "referer",
        "user-agent",
        "x-conduit-token",
        "x-openai-target-path",
        "oai-language",
        "oai-device-id",
        "oai-client-version",
        "oai-client-build-number",
        "oai-session-id",
        "cookie",
    }
)
logger = logging.getLogger(__name__)
_WEB_PROFILE_CACHE: dict[str, "_CachedWebClientProfile"] = {}


@dataclass(frozen=True, slots=True)
class ChatGPTImageAttachmentInput:
    data_url: str
    mime_type: str
    filename: str


@dataclass(frozen=True, slots=True)
class ChatGPTImageEditTarget:
    file_id: str
    original_gen_id: str | None


@dataclass(frozen=True, slots=True)
class ChatGPTImageConversationRequest:
    model: str
    prompt: str
    conversation_id: str | None
    parent_message_id: str | None
    timezone_offset_min: int
    timezone: str
    client_context: JsonObject
    attachments: tuple[ChatGPTImageAttachmentInput, ...]
    edit_target: ChatGPTImageEditTarget | None


@dataclass(frozen=True, slots=True)
class GeneratedImageAsset:
    data_url: str
    mime_type: str
    filename: str
    file_id: str
    original_gen_id: str | None
    revised_prompt: str | None


@dataclass(frozen=True, slots=True)
class ChatGPTImageConversationResult:
    conversation_id: str
    assistant_message_id: str
    parent_message_id: str
    assistant_text: str | None
    images: tuple[GeneratedImageAsset, ...]


@dataclass(frozen=True, slots=True)
class _UploadedAttachment:
    file_id: str
    filename: str
    mime_type: str
    size_bytes: int
    width: int
    height: int


@dataclass(frozen=True, slots=True)
class _PrepareConversationContext:
    conduit_token: str | None


@dataclass(frozen=True, slots=True)
class _ConversationSubmission:
    conversation_id: str
    assistant_message_id: str | None


@dataclass(frozen=True, slots=True)
class _FetchedImageRef:
    file_id: str
    original_gen_id: str | None
    mime_type: str | None
    revised_prompt: str | None
    download_url: str | None


@dataclass(frozen=True, slots=True)
class _WebClientProfile:
    language: str
    device_id: str
    session_id: str
    client_version: str
    client_build_number: str
    user_agent: str


@dataclass(frozen=True, slots=True)
class _CachedWebClientProfile:
    profile: _WebClientProfile
    expires_at_monotonic: float


class ChatGPTImageUpstreamError(Exception):
    def __init__(self, code: str, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


ProgressReporter = Callable[[str, str | None], Awaitable[None] | None]


class ChatGPTImagesClient:
    async def run_conversation(
        self,
        *,
        account: Account,
        access_token: str,
        request: ChatGPTImageConversationRequest,
        headers: Mapping[str, str],
        proxy_url: str | None,
        cookies: Mapping[str, str] | None = None,
        progress: ProgressReporter | None = None,
    ) -> ChatGPTImageConversationResult:
        filtered_headers = _build_chatgpt_headers(
            inbound=headers,
            access_token=access_token,
            account=account,
            cookies=cookies,
        )
        await _report_progress(progress, "preparing", "Preparing ChatGPT image session")
        prepare_context = await self._post_prepare(
            headers=filtered_headers,
            request=request,
            proxy_url=proxy_url,
        )

        uploaded_attachments: list[_UploadedAttachment] = []
        if request.attachments:
            await _report_progress(progress, "uploading", "Uploading reference images")
        for attachment in request.attachments:
            uploaded_attachments.append(
                await self._upload_attachment(
                    attachment=attachment,
                    headers=filtered_headers,
                    proxy_url=proxy_url,
                )
            )

        await _report_progress(progress, "submitting", "Submitting image request")
        submission = await self._submit_conversation(
            request=request,
            uploaded_attachments=tuple(uploaded_attachments),
            headers=filtered_headers,
            prepare_context=prepare_context,
            proxy_url=proxy_url,
        )

        await _report_progress(progress, "processing", "Waiting for generated images")
        return await self._poll_until_complete(
            conversation_id=submission.conversation_id,
            assistant_message_id=submission.assistant_message_id,
            headers=filtered_headers,
            proxy_url=proxy_url,
            progress=progress,
        )

    async def _post_prepare(
        self,
        *,
        headers: Mapping[str, str],
        request: ChatGPTImageConversationRequest,
        proxy_url: str | None,
    ) -> _PrepareConversationContext:
        payload: JsonObject = {
            "action": "next",
            "fork_from_shared_post": False,
            "parent_message_id": request.parent_message_id or str(uuid4()),
            "model": request.model,
            "timezone_offset_min": request.timezone_offset_min,
            "timezone": request.timezone,
            "conversation_mode": {"kind": "primary_assistant"},
            "system_hints": [],
            "attachment_mime_types": sorted({attachment.mime_type for attachment in request.attachments}),
            "supports_buffering": True,
            "supported_encodings": ["v1"],
            "client_contextual_info": {"app_name": _client_app_name(request.client_context)},
        }
        if request.conversation_id is not None:
            payload["conversation_id"] = request.conversation_id
        request_headers = _prepare_headers(headers)
        try:
            response_headers, response_payload = await self._request_json_with_headers(
                method="POST",
                url=f"{get_settings().upstream_base_url.rstrip('/')}/f/conversation/prepare",
                headers=request_headers,
                json_payload=payload,
                proxy_url=proxy_url,
                allow_empty=True,
            )
        except ChatGPTImageUpstreamError as exc:
            logger.warning(
                "ChatGPT images prepare failed: code=%s status=%s headers=%s payload=%s message=%s",
                exc.code,
                exc.status_code,
                _summarize_headers_for_log(request_headers),
                payload,
                exc.message,
            )
            raise
        conduit_token = _header_or_payload_token(response_headers, response_payload)
        logger.info(
            "ChatGPT images prepare ok: response_headers=%s payload=%s conduit_token_present=%s",
            _summarize_headers_for_log(response_headers),
            _summarize_json_value(response_payload),
            conduit_token is not None,
        )
        return _PrepareConversationContext(conduit_token=conduit_token)

    async def _upload_attachment(
        self,
        *,
        attachment: ChatGPTImageAttachmentInput,
        headers: Mapping[str, str],
        proxy_url: str | None,
    ) -> _UploadedAttachment:
        image_bytes = _decode_data_url(attachment.data_url, expected_mime_type=attachment.mime_type)
        width, height = _read_image_dimensions(image_bytes, attachment.mime_type)
        create_payload: JsonObject = {
            "file_name": attachment.filename,
            "file_size": len(image_bytes),
            "use_case": "multimodal",
            "timezone_offset_min": 0,
            "reset_rate_limits": False,
        }
        create_response = await self._request_json(
            "POST",
            f"{get_settings().upstream_base_url.rstrip('/')}/files",
            headers=_json_headers(headers),
            json_payload=create_payload,
            proxy_url=proxy_url,
        )
        file_id = _json_string(create_response, "file_id")
        upload_url = _json_string(create_response, "upload_url")
        if not file_id or not upload_url:
            raise ChatGPTImageUpstreamError(
                "invalid_upload_response",
                "Upstream file upload session did not include file metadata",
            )

        await self._upload_file_bytes(
            upload_url=upload_url,
            content=image_bytes,
            mime_type=attachment.mime_type,
        )
        await self._request_json(
            "POST",
            f"{get_settings().upstream_base_url.rstrip('/')}/files/process_upload_stream",
            headers=_json_headers(headers),
            json_payload={
                "file_id": file_id,
                "use_case": "multimodal",
                "index_for_retrieval": False,
                "file_name": attachment.filename,
            },
            proxy_url=proxy_url,
            allow_empty=True,
        )
        return _UploadedAttachment(
            file_id=file_id,
            filename=attachment.filename,
            mime_type=attachment.mime_type,
            size_bytes=len(image_bytes),
            width=width,
            height=height,
        )

    async def _submit_conversation(
        self,
        *,
        request: ChatGPTImageConversationRequest,
        uploaded_attachments: tuple[_UploadedAttachment, ...],
        headers: Mapping[str, str],
        prepare_context: _PrepareConversationContext,
        proxy_url: str | None,
    ) -> _ConversationSubmission:
        payload = _build_conversation_payload(request, uploaded_attachments)
        request_headers = _conversation_headers(headers, prepare_context, request.conversation_id)
        logger.info(
            "ChatGPT images conversation request: headers=%s payload=%s",
            _summarize_headers_for_log(request_headers),
            _sanitize_conversation_payload_for_log(payload),
        )
        try:
            response = await self._request_json(
                "POST",
                f"{get_settings().upstream_base_url.rstrip('/')}/f/conversation",
                headers=request_headers,
                json_payload=payload,
                proxy_url=proxy_url,
                allow_text=True,
            )
        except ChatGPTImageUpstreamError as exc:
            logger.warning(
                "ChatGPT images conversation failed: code=%s status=%s headers=%s payload=%s message=%s",
                exc.code,
                exc.status_code,
                _summarize_headers_for_log(request_headers),
                _sanitize_conversation_payload_for_log(payload),
                exc.message,
            )
            raise
        logger.info("ChatGPT images conversation response: payload=%s", _summarize_json_value(response))
        conversation_id = _extract_conversation_id(response)
        if not conversation_id:
            raise ChatGPTImageUpstreamError(
                "invalid_conversation_response",
                "Upstream image conversation did not return a conversation id",
            )
        return _ConversationSubmission(
            conversation_id=conversation_id,
            assistant_message_id=_extract_message_id(response),
        )

    async def _poll_until_complete(
        self,
        *,
        conversation_id: str,
        assistant_message_id: str | None,
        headers: Mapping[str, str],
        proxy_url: str | None,
        progress: ProgressReporter | None,
    ) -> ChatGPTImageConversationResult:
        status_url = (
            f"{get_settings().upstream_base_url.rstrip('/')}/conversation/"
            f"{conversation_id}/async-status"
        )
        latest_failure: ChatGPTImageUpstreamError | None = None
        for attempt in range(_DEFAULT_POLL_MAX_ATTEMPTS):
            payload = await self._request_json(
                "POST",
                status_url,
                headers=_json_headers(headers),
                json_payload={},
                proxy_url=proxy_url,
            )
            try:
                parsed = await self._extract_completion_result(
                    payload=payload,
                    fallback_conversation_id=conversation_id,
                    fallback_assistant_message_id=assistant_message_id,
                    headers=headers,
                    proxy_url=proxy_url,
                    progress=progress,
                )
            except ChatGPTImageUpstreamError as exc:
                if exc.code == "image_generation_in_progress":
                    latest_failure = exc
                    await _report_progress(
                        progress,
                        "processing",
                        f"Waiting for generated images ({attempt + 1}/{_DEFAULT_POLL_MAX_ATTEMPTS})",
                    )
                    await asyncio.sleep(_DEFAULT_POLL_INTERVAL_SECONDS)
                    continue
                raise
            if parsed is not None:
                return parsed
            await _report_progress(
                progress,
                "processing",
                f"Waiting for generated images ({attempt + 1}/{_DEFAULT_POLL_MAX_ATTEMPTS})",
            )
            await asyncio.sleep(_DEFAULT_POLL_INTERVAL_SECONDS)
        if latest_failure is not None:
            raise latest_failure
        raise ChatGPTImageUpstreamError("image_generation_timeout", "Timed out waiting for generated images")

    async def _extract_completion_result(
        self,
        *,
        payload: JsonValue,
        fallback_conversation_id: str,
        fallback_assistant_message_id: str | None,
        headers: Mapping[str, str],
        proxy_url: str | None,
        progress: ProgressReporter | None,
    ) -> ChatGPTImageConversationResult | None:
        failure = _extract_upstream_failure(payload)
        if failure is not None:
            raise failure

        status = _extract_status_value(payload)
        image_refs = tuple(_extract_generated_image_refs(payload))
        assistant_message_id = _extract_message_id(payload) or fallback_assistant_message_id
        conversation_id = _extract_conversation_id(payload) or fallback_conversation_id
        assistant_text = _extract_assistant_text(payload)

        if not image_refs:
            if status in {"finished_successfully", "completed", "succeeded", "done"} and assistant_message_id:
                raise ChatGPTImageUpstreamError(
                    "image_generation_empty",
                    "Image generation completed without returning an image",
                )
            if status is not None and status not in {"pending", "in_progress", "running", "queued"}:
                raise ChatGPTImageUpstreamError(
                    "image_generation_incomplete",
                    f"Unexpected image generation status: {status}",
                )
            return None

        if assistant_message_id is None:
            raise ChatGPTImageUpstreamError(
                "invalid_generation_response",
                "Upstream image generation result did not include an assistant message id",
            )

        await _report_progress(progress, "fetching", "Fetching generated images")
        images = [
            await self._fetch_generated_image(
                ref=ref,
                conversation_id=conversation_id,
                headers=headers,
                proxy_url=proxy_url,
            )
            for ref in image_refs
        ]
        return ChatGPTImageConversationResult(
            conversation_id=conversation_id,
            assistant_message_id=assistant_message_id,
            parent_message_id=assistant_message_id,
            assistant_text=assistant_text,
            images=tuple(images),
        )

    async def _fetch_generated_image(
        self,
        *,
        ref: _FetchedImageRef,
        conversation_id: str,
        headers: Mapping[str, str],
        proxy_url: str | None,
    ) -> GeneratedImageAsset:
        url = ref.download_url or _default_download_url(ref.file_id, conversation_id)
        resolved_url = _absolute_upstream_url(url)
        session = get_http_client().session
        timeout = aiohttp.ClientTimeout(total=min(get_settings().proxy_request_budget_seconds, 60.0))
        async with session.get(
            resolved_url,
            headers=_binary_headers(headers),
            proxy=proxy_url,
            timeout=timeout,
        ) as response:
            if response.status >= 400:
                raise await _raise_upstream_error(response, default_code="image_fetch_failed")
            content = await response.read()
            mime_type = ref.mime_type or _normalize_mime_type(response.headers.get("Content-Type"))
        if mime_type is None:
            mime_type = "image/png"
        filename = _filename_for_generated_image(ref.file_id, mime_type)
        return GeneratedImageAsset(
            data_url=f"data:{mime_type};base64,{base64.b64encode(content).decode('ascii')}",
            mime_type=mime_type,
            filename=filename,
            file_id=ref.file_id,
            original_gen_id=ref.original_gen_id,
            revised_prompt=ref.revised_prompt,
        )

    async def _upload_file_bytes(
        self,
        *,
        upload_url: str,
        content: bytes,
        mime_type: str,
    ) -> None:
        session = get_http_client().session
        timeout = aiohttp.ClientTimeout(total=min(get_settings().proxy_request_budget_seconds, 60.0))
        async with session.put(
            upload_url,
            data=content,
            headers={"Content-Type": mime_type},
            timeout=timeout,
        ) as response:
            if response.status >= 400:
                raise await _raise_upstream_error(response, default_code="image_upload_failed")

    async def _request_json(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        proxy_url: str | None,
        json_payload: JsonValue | None = None,
        allow_empty: bool = False,
        allow_text: bool = False,
    ) -> JsonValue:
        _, payload = await self._request_json_with_headers(
            method=method,
            url=url,
            headers=headers,
            proxy_url=proxy_url,
            json_payload=json_payload,
            allow_empty=allow_empty,
            allow_text=allow_text,
        )
        return payload

    async def _request_json_with_headers(
        self,
        *,
        method: str,
        url: str,
        headers: Mapping[str, str],
        proxy_url: str | None,
        json_payload: JsonValue | None = None,
        allow_empty: bool = False,
        allow_text: bool = False,
    ) -> tuple[Mapping[str, str], JsonValue]:
        session = get_http_client().session
        timeout = aiohttp.ClientTimeout(total=min(get_settings().proxy_request_budget_seconds, 120.0))
        async with session.request(
            method,
            url,
            headers=dict(headers),
            json=json_payload,
            proxy=proxy_url,
            timeout=timeout,
        ) as response:
            if response.status >= 400:
                raise await _raise_upstream_error(response, default_code="upstream_error")
            response_headers = dict(response.headers)
            text = await response.text()
        stripped = text.strip()
        if not stripped:
            if allow_empty:
                return response_headers, {}
            raise ChatGPTImageUpstreamError("empty_upstream_response", "Upstream returned an empty response")
        try:
            return response_headers, cast(JsonValue, json.loads(stripped))
        except json.JSONDecodeError:
            if allow_text:
                return response_headers, {"raw_text": stripped}
            raise ChatGPTImageUpstreamError("invalid_upstream_json", "Upstream returned invalid JSON")


def _build_chatgpt_headers(
    *,
    inbound: Mapping[str, str],
    access_token: str,
    account: Account,
    cookies: Mapping[str, str] | None,
) -> dict[str, str]:
    profile = _resolve_web_client_profile(account=account, inbound=inbound, cookies=cookies)
    headers: dict[str, str] = {
        "Authorization": f"Bearer {access_token}",
        "User-Agent": profile.user_agent,
        "OAI-Language": profile.language,
        "OAI-Device-Id": profile.device_id,
        "OAI-Client-Version": profile.client_version,
        "OAI-Client-Build-Number": profile.client_build_number,
        "OAI-Session-Id": profile.session_id,
    }
    accept_language = _header_accept_language(inbound)
    if accept_language is not None:
        headers["Accept-Language"] = accept_language
    if cookies:
        headers["Cookie"] = _format_cookie_header(cookies)
    sanitized_account_id = _header_account_id(account.chatgpt_account_id)
    if sanitized_account_id:
        headers["chatgpt-account-id"] = sanitized_account_id
    return headers


def _json_headers(headers: Mapping[str, str]) -> dict[str, str]:
    merged = dict(headers)
    merged["Content-Type"] = "application/json"
    return merged


def _prepare_headers(headers: Mapping[str, str]) -> dict[str, str]:
    merged = _json_headers(headers)
    merged["Accept"] = "*/*"
    merged["Origin"] = _upstream_origin()
    merged["Referer"] = _upstream_referer(None)
    merged["X-OpenAI-Target-Path"] = "/backend-api/f/conversation/prepare"
    merged["X-OpenAI-Target-Route"] = "/backend-api/f/conversation/prepare"
    return merged


def _conversation_headers(
    headers: Mapping[str, str],
    prepare_context: _PrepareConversationContext,
    conversation_id: str | None,
) -> dict[str, str]:
    merged = _json_headers(headers)
    merged["Accept"] = "text/event-stream"
    merged["Origin"] = _upstream_origin()
    merged["Referer"] = _upstream_referer(conversation_id)
    merged["X-OpenAI-Target-Path"] = "/backend-api/f/conversation"
    merged["X-OpenAI-Target-Route"] = "/backend-api/f/conversation"
    if prepare_context.conduit_token is not None:
        merged["x-conduit-token"] = prepare_context.conduit_token
    return merged


def _binary_headers(headers: Mapping[str, str]) -> dict[str, str]:
    merged = dict(headers)
    merged["Accept"] = "image/*,*/*"
    merged.pop("Content-Type", None)
    return merged


def _build_conversation_payload(
    request: ChatGPTImageConversationRequest,
    attachments: tuple[_UploadedAttachment, ...],
) -> JsonObject:
    prompt = request.prompt.strip()
    parts: list[JsonValue]
    metadata: JsonObject = {
        "attachments": [],
        "developer_mode_connector_ids": [],
        "selected_sources": [],
        "selected_github_repos": [],
        "selected_all_github_repos": False,
        "serialization_metadata": {"custom_symbol_offsets": []},
    }
    if attachments:
        parts = [
            {
                "content_type": "image_asset_pointer",
                "asset_pointer": f"sediment://{attachment.file_id}",
                "size_bytes": attachment.size_bytes,
                "width": attachment.width,
                "height": attachment.height,
            }
            for attachment in attachments
        ]
        parts.append(prompt)
        metadata["attachments"] = [
            {
                "id": attachment.file_id,
                "size": attachment.size_bytes,
                "name": attachment.filename,
                "mime_type": attachment.mime_type,
                "width": attachment.width,
                "height": attachment.height,
                "source": "local",
                "is_big_paste": False,
            }
            for attachment in attachments
        ]
    else:
        parts = [prompt]

    content: JsonObject = {
        "content_type": "multimodal_text",
        "parts": parts,
    }

    if request.edit_target is not None:
        metadata["dalle"] = {
            "from_client": {
                "operation": {
                    "type": "transformation",
                    "original_gen_id": request.edit_target.original_gen_id,
                    "original_file_id": request.edit_target.file_id,
                }
            }
        }

    message: JsonObject = {
        "id": str(uuid4()),
        "author": {"role": "user"},
        "create_time": round(time.time(), 3),
        "content": content,
        "metadata": metadata,
    }
    payload: JsonObject = {
        "action": "next",
        "messages": [message],
        "parent_message_id": request.parent_message_id or str(uuid4()),
        "model": request.model,
        "timezone_offset_min": request.timezone_offset_min,
        "timezone": request.timezone,
        "conversation_mode": {"kind": "primary_assistant"},
        "enable_message_followups": True,
        "system_hints": [],
        "supports_buffering": True,
        "supported_encodings": ["v1"],
        "client_contextual_info": request.client_context,
        "paragen_cot_summary_display_override": "allow",
        "force_parallel_switch": "auto",
    }
    if request.conversation_id is not None:
        payload["conversation_id"] = request.conversation_id
    return payload


async def _report_progress(progress: ProgressReporter | None, phase: str, message: str | None) -> None:
    if progress is None:
        return
    result = progress(phase, message)
    if result is not None:
        await result


async def _raise_upstream_error(
    response: aiohttp.ClientResponse,
    *,
    default_code: str,
) -> ChatGPTImageUpstreamError:
    try:
        payload = cast(JsonValue, await response.json(content_type=None))
    except Exception:
        payload = None
    if is_json_mapping(payload):
        error = cast(Mapping[str, JsonValue], payload.get("error", {})) if is_json_mapping(payload.get("error")) else None
        if error is not None:
            code = cast(str | None, error.get("code")) or default_code
            message = cast(str | None, error.get("message")) or response.reason or "Request failed"
            return ChatGPTImageUpstreamError(code, message, status_code=response.status)
    text = await response.text()
    message = text.strip() or response.reason or "Request failed"
    return ChatGPTImageUpstreamError(default_code, message, status_code=response.status)


def _decode_data_url(data_url: str, *, expected_mime_type: str) -> bytes:
    prefix = f"data:{expected_mime_type};base64,"
    if not data_url.startswith(prefix):
        raise ChatGPTImageUpstreamError("invalid_image_data", "Attachment data URL did not match its MIME type")
    try:
        return base64.b64decode(data_url[len(prefix) :], validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ChatGPTImageUpstreamError("invalid_image_data", "Attachment image data was not valid base64") from exc


def _read_image_dimensions(image_bytes: bytes, mime_type: str) -> tuple[int, int]:
    if mime_type == "image/png":
        return _read_png_dimensions(image_bytes)
    if mime_type == "image/jpeg":
        return _read_jpeg_dimensions(image_bytes)
    if mime_type == "image/webp":
        return _read_webp_dimensions(image_bytes)
    raise ChatGPTImageUpstreamError("unsupported_image_type", f"Unsupported image MIME type: {mime_type}")


def _read_png_dimensions(image_bytes: bytes) -> tuple[int, int]:
    if len(image_bytes) < 24 or image_bytes[:8] != b"\x89PNG\r\n\x1a\n":
        raise ChatGPTImageUpstreamError("invalid_image_data", "PNG image was invalid")
    return struct.unpack(">II", image_bytes[16:24])


def _read_jpeg_dimensions(image_bytes: bytes) -> tuple[int, int]:
    if len(image_bytes) < 4 or image_bytes[:2] != b"\xff\xd8":
        raise ChatGPTImageUpstreamError("invalid_image_data", "JPEG image was invalid")
    offset = 2
    while offset + 9 < len(image_bytes):
        if image_bytes[offset] != 0xFF:
            offset += 1
            continue
        marker = image_bytes[offset + 1]
        offset += 2
        if marker in {0xD8, 0xD9}:
            continue
        if offset + 2 > len(image_bytes):
            break
        segment_length = struct.unpack(">H", image_bytes[offset : offset + 2])[0]
        if segment_length < 2 or offset + segment_length > len(image_bytes):
            break
        if marker in {
            0xC0,
            0xC1,
            0xC2,
            0xC3,
            0xC5,
            0xC6,
            0xC7,
            0xC9,
            0xCA,
            0xCB,
            0xCD,
            0xCE,
            0xCF,
        }:
            if offset + 7 > len(image_bytes):
                break
            height, width = struct.unpack(">HH", image_bytes[offset + 3 : offset + 7])
            return width, height
        offset += segment_length
    raise ChatGPTImageUpstreamError("invalid_image_data", "JPEG dimensions could not be read")


def _read_webp_dimensions(image_bytes: bytes) -> tuple[int, int]:
    if len(image_bytes) < 16 or image_bytes[:4] != b"RIFF" or image_bytes[8:12] != b"WEBP":
        raise ChatGPTImageUpstreamError("invalid_image_data", "WebP image was invalid")
    chunk_type = image_bytes[12:16]
    if chunk_type == b"VP8X":
        if len(image_bytes) < 30:
            raise ChatGPTImageUpstreamError("invalid_image_data", "WebP VP8X image was invalid")
        width = 1 + int.from_bytes(image_bytes[24:27], "little")
        height = 1 + int.from_bytes(image_bytes[27:30], "little")
        return width, height
    if chunk_type == b"VP8L":
        if len(image_bytes) < 25:
            raise ChatGPTImageUpstreamError("invalid_image_data", "WebP VP8L image was invalid")
        bits = int.from_bytes(image_bytes[21:25], "little")
        width = (bits & 0x3FFF) + 1
        height = ((bits >> 14) & 0x3FFF) + 1
        return width, height
    if chunk_type == b"VP8 ":
        if len(image_bytes) < 30:
            raise ChatGPTImageUpstreamError("invalid_image_data", "WebP VP8 image was invalid")
        width, height = struct.unpack("<HH", image_bytes[26:30])
        return width & 0x3FFF, height & 0x3FFF
    raise ChatGPTImageUpstreamError("invalid_image_data", "Unsupported WebP encoding")


def _extract_upstream_failure(payload: JsonValue) -> ChatGPTImageUpstreamError | None:
    payload_mapping = cast(Mapping[str, JsonValue], payload) if is_json_mapping(payload) else None
    if payload_mapping is None:
        return None
    error_mapping = payload_mapping.get("error")
    if is_json_mapping(error_mapping):
        error = cast(Mapping[str, JsonValue], error_mapping)
        code = cast(str | None, error.get("code")) or "upstream_error"
        message = cast(str | None, error.get("message")) or "Upstream request failed"
        return ChatGPTImageUpstreamError(code, message)
    status = _extract_status_value(payload_mapping)
    if status in {"failed", "error", "finished_with_error"}:
        message = _extract_nested_message(payload_mapping) or "Upstream image generation failed"
        return ChatGPTImageUpstreamError("image_generation_failed", message)
    return None


def _extract_status_value(payload: JsonValue) -> str | None:
    for candidate in _walk_json_values(payload):
        if is_json_mapping(candidate):
            mapping = cast(Mapping[str, JsonValue], candidate)
            for key in ("status", "state"):
                value = mapping.get(key)
                if isinstance(value, str):
                    return value
    return None


def _extract_nested_message(payload: JsonValue) -> str | None:
    for candidate in _walk_json_values(payload):
        if is_json_mapping(candidate):
            mapping = cast(Mapping[str, JsonValue], candidate)
            value = mapping.get("message")
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def _extract_conversation_id(payload: JsonValue) -> str | None:
    return _extract_first_string(payload, {"conversation_id", "conversationId"}) or _extract_raw_text_field(
        payload,
        "conversation_id",
    )


def _extract_message_id(payload: JsonValue) -> str | None:
    return _extract_first_string(payload, {"message_id", "messageId"}) or _extract_raw_text_field(
        payload,
        "message_id",
    )


def _extract_assistant_text(payload: JsonValue) -> str | None:
    texts: list[str] = []
    for candidate in _walk_json_values(payload):
        if is_json_mapping(candidate):
            mapping = cast(Mapping[str, JsonValue], candidate)
            content_type = mapping.get("content_type")
            if content_type == "text" and isinstance(mapping.get("text"), str):
                texts.append(cast(str, mapping["text"]))
    if texts:
        return "\n".join(texts)
    for candidate in _walk_json_values(payload):
        if is_json_mapping(candidate):
            mapping = cast(Mapping[str, JsonValue], candidate)
            parts = mapping.get("parts")
            if is_json_list(parts):
                strings = [part for part in parts if isinstance(part, str) and part.strip()]
                if strings:
                    return "\n".join(cast(list[str], strings))
    return None


def _extract_generated_image_refs(payload: JsonValue) -> list[_FetchedImageRef]:
    refs: list[_FetchedImageRef] = []
    seen_file_ids: set[str] = set()
    for candidate in _walk_json_values(payload):
        if not is_json_mapping(candidate):
            continue
        mapping = cast(Mapping[str, JsonValue], candidate)
        file_id = _extract_file_id(mapping)
        if file_id is None or file_id in seen_file_ids:
            continue
        content_type = mapping.get("content_type")
        asset_pointer = mapping.get("asset_pointer")
        if content_type != "image_asset_pointer" and not (
            isinstance(asset_pointer, str) and asset_pointer.startswith("sediment://")
        ):
            continue
        metadata = cast(Mapping[str, JsonValue], mapping.get("metadata")) if is_json_mapping(mapping.get("metadata")) else {}
        dalle = cast(Mapping[str, JsonValue], metadata.get("dalle")) if is_json_mapping(metadata.get("dalle")) else {}
        refs.append(
            _FetchedImageRef(
                file_id=file_id,
                original_gen_id=_string_or_none(dalle.get("gen_id"))
                or _string_or_none(metadata.get("original_gen_id"))
                or _string_or_none(mapping.get("original_gen_id")),
                mime_type=_normalize_mime_type(_string_or_none(mapping.get("mime_type"))),
                revised_prompt=_string_or_none(dalle.get("revised_prompt"))
                or _string_or_none(metadata.get("revised_prompt"))
                or _string_or_none(mapping.get("revised_prompt")),
                download_url=_string_or_none(mapping.get("download_url")) or _string_or_none(mapping.get("url")),
            )
        )
        seen_file_ids.add(file_id)
    return refs


def _extract_file_id(mapping: Mapping[str, JsonValue]) -> str | None:
    direct = _string_or_none(mapping.get("file_id")) or _string_or_none(mapping.get("fileId")) or _string_or_none(mapping.get("id"))
    if direct and direct.startswith("file_"):
        return direct
    asset_pointer = mapping.get("asset_pointer")
    if isinstance(asset_pointer, str) and asset_pointer.startswith("sediment://file_"):
        return asset_pointer.removeprefix("sediment://")
    return None


def _extract_first_string(payload: JsonValue, keys: set[str]) -> str | None:
    for candidate in _walk_json_values(payload):
        if is_json_mapping(candidate):
            mapping = cast(Mapping[str, JsonValue], candidate)
            for key in keys:
                value = mapping.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
    return None


def _extract_raw_text_field(payload: JsonValue, field_name: str) -> str | None:
    if not is_json_mapping(payload):
        return None
    raw_text = cast(Mapping[str, JsonValue], payload).get("raw_text")
    if not isinstance(raw_text, str):
        return None
    match = re.search(rf'"{re.escape(field_name)}"\s*:\s*"([^"]+)"', raw_text)
    if match is None:
        return None
    value = match.group(1).strip()
    return value or None


def _walk_json_values(value: JsonValue) -> list[JsonValue]:
    values: list[JsonValue] = [value]
    if is_json_mapping(value):
        mapping = cast(Mapping[str, JsonValue], value)
        for nested in mapping.values():
            values.extend(_walk_json_values(nested))
    elif is_json_list(value):
        for nested in cast(list[JsonValue], value):
            values.extend(_walk_json_values(nested))
    return values


def _default_download_url(file_id: str, conversation_id: str) -> str:
    query = urlencode({"conversation_id": conversation_id})
    return f"/files/download/{file_id}?{query}"


def _absolute_upstream_url(url: str) -> str:
    if url.startswith("http://") or url.startswith("https://"):
        return url
    return f"{get_settings().upstream_base_url.rstrip('/')}/{url.lstrip('/')}"


def _filename_for_generated_image(file_id: str, mime_type: str) -> str:
    extension = {
        "image/jpeg": "jpg",
        "image/webp": "webp",
    }.get(mime_type, "png")
    return f"{file_id}.{extension}"


def _normalize_mime_type(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.split(";", maxsplit=1)[0].strip().lower()
    if normalized in {"image/png", "image/jpeg", "image/webp"}:
        return normalized
    return None


def _json_string(payload: JsonValue, key: str) -> str | None:
    if not is_json_mapping(payload):
        return None
    value = cast(Mapping[str, JsonValue], payload).get(key)
    return value if isinstance(value, str) and value.strip() else None


def _string_or_none(value: JsonValue | None) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _header_language(headers: Mapping[str, str]) -> str:
    for key, value in headers.items():
        if key.lower() == "oai-language" and value.strip():
            return value.strip()
    for key, value in headers.items():
        if key.lower() == "accept-language" and value.strip():
            return value.split(",", maxsplit=1)[0].strip()
    return "en-US"


def _header_accept_language(headers: Mapping[str, str]) -> str | None:
    for key, value in headers.items():
        if key.lower() == "accept-language" and value.strip():
            return value.strip()
    return None


def _resolve_web_client_profile(
    *,
    account: Account,
    inbound: Mapping[str, str],
    cookies: Mapping[str, str] | None,
) -> _WebClientProfile:
    account_key = account.chatgpt_account_id or account.id
    cached = _WEB_PROFILE_CACHE.get(account_key)
    now = time.monotonic()
    language = _cookie_value(cookies, "oai-locale") or _header_language(inbound)
    if cached is not None and cached.expires_at_monotonic > now and cached.profile.language == language:
        return cached.profile

    profile = _WebClientProfile(
        language=language,
        device_id=_cookie_value(cookies, "oai-did")
        or str(uuid5(NAMESPACE_URL, f"codex-lb:chatgpt-images:device:{account_key}")),
        session_id=str(uuid4()),
        client_version=_DEFAULT_WEB_CLIENT_VERSION,
        client_build_number=_DEFAULT_WEB_CLIENT_BUILD_NUMBER,
        user_agent=_DEFAULT_WEB_USER_AGENT,
    )
    _WEB_PROFILE_CACHE[account_key] = _CachedWebClientProfile(
        profile=profile,
        expires_at_monotonic=now + _DEFAULT_WEB_SESSION_TTL_SECONDS,
    )
    return profile


def _cookie_value(cookies: Mapping[str, str] | None, key: str) -> str | None:
    if cookies is None:
        return None
    value = cookies.get(key)
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _format_cookie_header(cookies: Mapping[str, str]) -> str:
    return "; ".join(f"{name}={value}" for name, value in cookies.items())


def _header_or_payload_token(headers: Mapping[str, str], payload: JsonValue) -> str | None:
    for key, value in headers.items():
        if key.lower() == "x-conduit-token":
            return value.strip() or None
    if is_json_mapping(payload):
        payload_mapping = cast(Mapping[str, JsonValue], payload)
        for key in ("x_conduit_token", "x-conduit-token", "conduit_token", "conduitToken"):
            token = _string_or_none(payload_mapping.get(key))
            if token is not None:
                return token
    return None


def _upstream_origin() -> str:
    return _CHATGPT_WEB_ORIGIN


def _upstream_referer(conversation_id: str | None) -> str:
    origin = _upstream_origin()
    if conversation_id:
        return f"{origin}/c/{conversation_id}"
    return origin


def _client_app_name(client_context: Mapping[str, JsonValue]) -> str:
    return _string_or_none(client_context.get("app_name")) or "chatgpt.com"


def _summarize_headers_for_log(headers: Mapping[str, str]) -> dict[str, str]:
    summary: dict[str, str] = {}
    for key, value in headers.items():
        if key.lower() not in _DEBUG_HEADER_ALLOWLIST:
            continue
        if key.lower() in {"x-conduit-token", "cookie"}:
            summary[key] = "<present>" if value.strip() else "<empty>"
        else:
            summary[key] = value
    return summary


def _sanitize_conversation_payload_for_log(payload: JsonValue) -> JsonValue:
    if not is_json_mapping(payload):
        return payload
    payload_mapping = cast(Mapping[str, JsonValue], payload)
    sanitized = dict(payload_mapping)
    messages = payload_mapping.get("messages")
    if is_json_list(messages):
        sanitized_messages: list[JsonValue] = []
        for message in cast(list[JsonValue], messages):
            if not is_json_mapping(message):
                sanitized_messages.append(message)
                continue
            message_mapping = cast(Mapping[str, JsonValue], message)
            sanitized_message = dict(message_mapping)
            content = message_mapping.get("content")
            if is_json_mapping(content):
                content_mapping = cast(Mapping[str, JsonValue], content)
                sanitized_content = dict(content_mapping)
                parts = content_mapping.get("parts")
                if is_json_list(parts):
                    sanitized_parts: list[JsonValue] = []
                    for part in cast(list[JsonValue], parts):
                        if isinstance(part, str):
                            sanitized_parts.append(part)
                            continue
                        if is_json_mapping(part):
                            part_mapping = cast(Mapping[str, JsonValue], part)
                            sanitized_part = dict(part_mapping)
                            if "asset_pointer" in sanitized_part:
                                sanitized_part["asset_pointer"] = "<asset_pointer>"
                            sanitized_parts.append(sanitized_part)
                            continue
                        sanitized_parts.append(part)
                    sanitized_content["parts"] = sanitized_parts
                sanitized_message["content"] = sanitized_content
            sanitized_messages.append(sanitized_message)
        sanitized["messages"] = sanitized_messages
    return sanitized


def _summarize_json_value(value: JsonValue) -> JsonValue:
    if is_json_mapping(value):
        mapping = cast(Mapping[str, JsonValue], value)
        summary: dict[str, JsonValue] = {}
        for key in sorted(mapping.keys()):
            nested = mapping[key]
            if key == "raw_text" and isinstance(nested, str):
                summary[key] = nested[:500]
            elif is_json_mapping(nested):
                summary[key] = {"keys": sorted(cast(Mapping[str, JsonValue], nested).keys())}
            elif is_json_list(nested):
                summary[key] = {"length": len(cast(list[JsonValue], nested))}
            else:
                summary[key] = nested
        return summary
    return value
