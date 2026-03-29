from __future__ import annotations

import asyncio
import base64
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from playwright.async_api import BrowserContext, Page, Playwright, async_playwright
from playwright.async_api import Error as PlaywrightError

from app.core.clients.chatgpt_images import (
    ChatGPTImageAttachmentInput,
    ChatGPTImageConversationRequest,
    ChatGPTImageEditTarget,
    _build_conversation_payload,
    _decode_data_url,
    _default_download_url,
    _extract_assistant_text,
    _extract_conversation_id,
    _extract_generated_image_refs,
    _extract_message_id,
    _extract_upstream_failure,
    _extract_status_value,
    _filename_for_generated_image,
    _json_string,
    _normalize_mime_type,
    _read_image_dimensions,
)


CHATGPT_BASE_URL = "https://chatgpt.com"
DEFAULT_VIEWPORT = {"width": 1440, "height": 960}
_EMAIL_SELECTORS = (
    "input[type='email']",
    "input[name='username']",
    "input[name='email']",
    "input[autocomplete='username']",
    "input[autocomplete='email']",
)
_PASSWORD_SELECTORS = (
    "input[type='password']",
    "input[name='password']",
    "input[autocomplete='current-password']",
)


class WorkerSettings(BaseModel):
    model_config = ConfigDict(extra="ignore")

    token: str = "codex-lb-image-worker-dev-token"
    data_dir: Path = Path("/var/lib/codex-lb/chatgpt-image-sessions")
    browser_idle_ttl_seconds: int = 600
    browser_headless: bool = True
    browser_channel: str | None = None
    browser_executable_path: Path | None = None
    browser_locale: str = "en-US"
    browser_launch_args: tuple[str, ...] = (
        "--disable-dev-shm-usage",
        "--no-sandbox",
    )
    browser_slow_mo_ms: int = 0
    browser_trace_enabled: bool = False
    browser_trace_dir: Path | None = None


def load_settings() -> WorkerSettings:
    return WorkerSettings(
        token=os.environ.get("CODEX_LB_IMAGE_WORKER_TOKEN", "codex-lb-image-worker-dev-token"),
        data_dir=Path(
            os.environ.get(
                "CODEX_LB_CHATGPT_IMAGE_SESSIONS_DIR",
                "/var/lib/codex-lb/chatgpt-image-sessions",
            )
        ),
        browser_idle_ttl_seconds=int(os.environ.get("CODEX_LB_CHATGPT_IMAGE_BROWSER_IDLE_TTL_SECONDS", "600")),
        browser_headless=_env_bool(
            "CODEX_LB_CHATGPT_IMAGE_BROWSER_HEADLESS",
            default=Path("/.dockerenv").exists(),
        ),
        browser_channel=_env_optional_str("CODEX_LB_CHATGPT_IMAGE_BROWSER_CHANNEL"),
        browser_executable_path=_env_optional_path("CODEX_LB_CHATGPT_IMAGE_BROWSER_EXECUTABLE_PATH"),
        browser_locale=os.environ.get("CODEX_LB_CHATGPT_IMAGE_BROWSER_LOCALE", "en-US").strip() or "en-US",
        browser_launch_args=_env_launch_args(
            "CODEX_LB_CHATGPT_IMAGE_BROWSER_ARGS",
            default=("--disable-dev-shm-usage", "--no-sandbox"),
        ),
        browser_slow_mo_ms=int(os.environ.get("CODEX_LB_CHATGPT_IMAGE_BROWSER_SLOW_MO_MS", "0")),
        browser_trace_enabled=_env_bool("CODEX_LB_CHATGPT_IMAGE_BROWSER_TRACE_ENABLED", default=False),
        browser_trace_dir=_env_optional_path("CODEX_LB_CHATGPT_IMAGE_BROWSER_TRACE_DIR"),
    )


def _env_bool(name: str, *, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


def _env_optional_str(name: str) -> str | None:
    raw = os.environ.get(name)
    if raw is None:
        return None
    stripped = raw.strip()
    return stripped or None


def _env_optional_path(name: str) -> Path | None:
    value = _env_optional_str(name)
    if value is None:
        return None
    return Path(value).expanduser()


def _env_launch_args(name: str, *, default: tuple[str, ...]) -> tuple[str, ...]:
    raw = os.environ.get(name)
    if raw is None:
        return default
    parts = tuple(part.strip() for part in raw.splitlines() for part in part.split(","))
    normalized = tuple(part for part in parts if part)
    return normalized or default


class ErrorEnvelope(BaseModel):
    error: dict[str, str]


class ExecuteConversationRequest(BaseModel):
    proxy_url: str | None = Field(default=None, alias="proxyUrl")
    request: dict[str, Any]
    credentials: dict[str, str] | None = None


class GeneratedImageResponse(BaseModel):
    data_url: str = Field(alias="dataUrl")
    mime_type: str = Field(alias="mimeType")
    filename: str
    file_id: str = Field(alias="fileId")
    original_gen_id: str | None = Field(default=None, alias="originalGenId")
    revised_prompt: str | None = Field(default=None, alias="revisedPrompt")


class ExecuteConversationResponse(BaseModel):
    conversation_id: str = Field(alias="conversationId")
    assistant_message_id: str = Field(alias="assistantMessageId")
    parent_message_id: str = Field(alias="parentMessageId")
    assistant_text: str | None = Field(default=None, alias="assistantText")
    images: list[GeneratedImageResponse]


class WorkerError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True, slots=True)
class AutomationCredentials:
    login_email: str
    password: str


@dataclass(slots=True)
class AccountRuntime:
    account_id: str
    proxy_url: str | None
    context: BrowserContext
    page: Page
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    last_used_monotonic: float = field(default_factory=time.monotonic)
    last_error: str | None = None
    ready: bool = False
    last_validated_at: float = 0.0


class BrowserWorker:
    def __init__(self, settings: WorkerSettings) -> None:
        self._settings = settings
        self._playwright: Playwright | None = None
        self._playwright_lock = asyncio.Lock()
        self._runtimes: dict[str, AccountRuntime] = {}
        self._manager_lock = asyncio.Lock()

    async def start(self) -> None:
        async with self._playwright_lock:
            if self._playwright is None:
                self._playwright = await async_playwright().start()

    async def stop(self) -> None:
        for runtime in list(self._runtimes.values()):
            if self._settings.browser_trace_enabled:
                await _stop_runtime_trace(runtime, self._settings)
            await runtime.context.close()
        self._runtimes.clear()
        async with self._playwright_lock:
            if self._playwright is not None:
                await self._playwright.stop()
                self._playwright = None

    async def disconnect_account(self, account_id: str) -> None:
        async with self._manager_lock:
            runtime = self._runtimes.pop(account_id, None)
        if runtime is not None:
            if self._settings.browser_trace_enabled:
                await _stop_runtime_trace(runtime, self._settings)
            await runtime.context.close()
        profile_dir = self._profile_dir(account_id)
        if profile_dir.exists():
            import shutil

            shutil.rmtree(profile_dir, ignore_errors=True)

    async def execute(
        self,
        account_id: str,
        proxy_url: str | None,
        request: ChatGPTImageConversationRequest,
        credentials: AutomationCredentials | None = None,
    ) -> ExecuteConversationResponse:
        runtime = await self._ensure_runtime(account_id, proxy_url)
        async with runtime.lock:
            await self._ensure_runtime_ready(runtime, credentials)
            if not runtime.ready:
                raise WorkerError("session_not_ready", runtime.last_error or "ChatGPT Images session is not ready")

            prepare_payload = {
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
                "client_contextual_info": {"app_name": "chatgpt.com"},
            }
            if request.conversation_id is not None:
                prepare_payload["conversation_id"] = request.conversation_id
            prepare_response = await _page_fetch_json(
                runtime.page,
                "/backend-api/f/conversation/prepare",
                method="POST",
                headers={"Content-Type": "application/json", "Accept": "*/*"},
                json_payload=prepare_payload,
            )
            _raise_for_page_failure(prepare_response, default_code="prepare_failed")
            conduit_token = _extract_conduit_token(prepare_response)

            uploaded_attachments: list[dict[str, Any]] = []
            for attachment in request.attachments:
                image_bytes = _decode_data_url(attachment.data_url, expected_mime_type=attachment.mime_type)
                width, height = _read_image_dimensions(image_bytes, attachment.mime_type)
                create_response = await _page_fetch_json(
                    runtime.page,
                    "/backend-api/files",
                    method="POST",
                    headers={"Content-Type": "application/json", "Accept": "application/json"},
                    json_payload={
                        "file_name": attachment.filename,
                        "file_size": len(image_bytes),
                        "use_case": "multimodal",
                        "timezone_offset_min": 0,
                        "reset_rate_limits": False,
                    },
                )
                _raise_for_page_failure(create_response, default_code="image_upload_failed")
                create_payload = create_response.get("json")
                if not isinstance(create_payload, dict):
                    raise WorkerError("image_upload_failed", "Upload session response was invalid")
                file_id = _json_string(create_payload, "file_id")
                upload_url = _json_string(create_payload, "upload_url")
                if file_id is None or upload_url is None:
                    raise WorkerError("image_upload_failed", "Upload session was missing file metadata")
                await _page_upload_bytes(runtime.page, upload_url, image_bytes, attachment.mime_type)
                await _page_fetch_json(
                    runtime.page,
                    "/backend-api/files/process_upload_stream",
                    method="POST",
                    headers={"Content-Type": "application/json", "Accept": "application/json"},
                    json_payload={
                        "file_id": file_id,
                        "use_case": "multimodal",
                        "index_for_retrieval": False,
                        "file_name": attachment.filename,
                    },
                )
                uploaded_attachments.append(
                    {
                        "file_id": file_id,
                        "filename": attachment.filename,
                        "mime_type": attachment.mime_type,
                        "size_bytes": len(image_bytes),
                        "width": width,
                        "height": height,
                    }
                )

            conversation_payload = _build_conversation_payload(
                request,
                tuple(
                    _UploadedAttachmentCompat(
                        file_id=item["file_id"],
                        filename=item["filename"],
                        mime_type=item["mime_type"],
                        size_bytes=item["size_bytes"],
                        width=item["width"],
                        height=item["height"],
                    )
                    for item in uploaded_attachments
                ),
            )
            conversation_headers = {
                "Content-Type": "application/json",
                "Accept": "text/event-stream",
            }
            if conduit_token:
                conversation_headers["x-conduit-token"] = conduit_token
            conversation_response = await _page_fetch_json(
                runtime.page,
                "/backend-api/f/conversation",
                method="POST",
                headers=conversation_headers,
                json_payload=conversation_payload,
            )
            _raise_for_page_failure(conversation_response, default_code="conversation_failed")
            conversation_payload_response = conversation_response.get("json")
            if not isinstance(conversation_payload_response, dict):
                raise WorkerError("conversation_failed", "Conversation response was invalid")
            conversation_id = _extract_conversation_id(conversation_payload_response)
            assistant_message_id = _extract_message_id(conversation_payload_response)
            if conversation_id is None:
                raise WorkerError("conversation_failed", "Conversation did not return a conversation id")

            final_payload: dict[str, Any] | None = None
            latest_status = None
            for _ in range(40):
                poll_response = await _page_fetch_json(
                    runtime.page,
                    f"/backend-api/conversation/{conversation_id}/async-status",
                    method="POST",
                    headers={"Content-Type": "application/json", "Accept": "application/json"},
                    json_payload={},
                )
                _raise_for_page_failure(poll_response, default_code="async_status_failed")
                poll_payload = poll_response.get("json")
                if not isinstance(poll_payload, dict):
                    raise WorkerError("async_status_failed", "Async status response was invalid")
                failure = _extract_upstream_failure(poll_payload)
                if failure is not None:
                    raise WorkerError(failure.code, failure.message)
                status = _extract_status_value(poll_payload)
                latest_status = status
                image_refs = _extract_generated_image_refs(poll_payload)
                if image_refs:
                    final_payload = poll_payload
                    break
                if status in {"finished_successfully", "completed", "succeeded", "done"}:
                    raise WorkerError("image_generation_empty", "Image generation completed without returning an image")
                await asyncio.sleep(1.5)
            if final_payload is None:
                raise WorkerError("image_generation_timeout", f"Timed out waiting for generated images ({latest_status or 'unknown'})")

            generated_images: list[GeneratedImageResponse] = []
            assistant_text = _extract_assistant_text(final_payload)
            resolved_assistant_message_id = _extract_message_id(final_payload) or assistant_message_id
            if resolved_assistant_message_id is None:
                raise WorkerError("invalid_generation_response", "Missing assistant message id")

            for image_ref in _extract_generated_image_refs(final_payload):
                download_url = image_ref.download_url or _default_download_url(image_ref.file_id, conversation_id)
                fetched = await _page_fetch_bytes(runtime.page, download_url)
                _raise_for_page_failure(fetched, default_code="image_fetch_failed")
                mime_type = image_ref.mime_type or _normalize_mime_type(_header_value(fetched, "content-type")) or "image/png"
                filename = _filename_for_generated_image(image_ref.file_id, mime_type)
                generated_images.append(
                    GeneratedImageResponse(
                        dataUrl=f"data:{mime_type};base64,{fetched['base64']}",
                        mimeType=mime_type,
                        filename=filename,
                        fileId=image_ref.file_id,
                        originalGenId=image_ref.original_gen_id,
                        revisedPrompt=image_ref.revised_prompt,
                    )
                )

            runtime.ready = True
            runtime.last_error = None
            runtime.last_validated_at = time.monotonic()

            return ExecuteConversationResponse(
                conversationId=conversation_id,
                assistantMessageId=resolved_assistant_message_id,
                parentMessageId=resolved_assistant_message_id,
                assistantText=assistant_text,
                images=generated_images,
            )

    async def _ensure_runtime(self, account_id: str, proxy_url: str | None) -> AccountRuntime:
        await self.start()
        async with self._manager_lock:
            await self._prune_idle_runtimes()
            current = self._runtimes.get(account_id)
            if current is not None and current.proxy_url == proxy_url:
                current.last_used_monotonic = time.monotonic()
                return current
            if current is not None:
                if self._settings.browser_trace_enabled:
                    await _stop_runtime_trace(current, self._settings)
                await current.context.close()
                self._runtimes.pop(account_id, None)
            if self._playwright is None:
                raise WorkerError("playwright_unavailable", "Playwright runtime was not initialized")
            profile_dir = self._profile_dir(account_id)
            profile_dir.mkdir(parents=True, exist_ok=True)
            try:
                context = await self._playwright.chromium.launch_persistent_context(
                    user_data_dir=str(profile_dir),
                    headless=self._settings.browser_headless,
                    viewport=DEFAULT_VIEWPORT,
                    proxy={"server": proxy_url} if proxy_url else None,
                    channel=self._settings.browser_channel,
                    executable_path=(
                        str(self._settings.browser_executable_path)
                        if self._settings.browser_executable_path is not None
                        else None
                    ),
                    locale=self._settings.browser_locale,
                    args=list(self._settings.browser_launch_args),
                    slow_mo=self._settings.browser_slow_mo_ms,
                )
            except PlaywrightError as exc:
                raise WorkerError(
                    "browser_launch_failed",
                    "Failed to launch ChatGPT Images browser runtime. "
                    "If you are using the host-browser transport, verify the local Playwright/Chrome setup.",
                ) from exc
            page = context.pages[0] if context.pages else await context.new_page()
            runtime = AccountRuntime(
                account_id=account_id,
                proxy_url=proxy_url,
                context=context,
                page=page,
            )
            if self._settings.browser_trace_enabled:
                await _start_runtime_trace(runtime, self._settings)
            self._runtimes[account_id] = runtime
            return runtime

    async def _prune_idle_runtimes(self) -> None:
        now = time.monotonic()
        for account_id, runtime in list(self._runtimes.items()):
            if now - runtime.last_used_monotonic <= self._settings.browser_idle_ttl_seconds:
                continue
            if self._settings.browser_trace_enabled:
                await _stop_runtime_trace(runtime, self._settings)
            await runtime.context.close()
            self._runtimes.pop(account_id, None)

    def _profile_dir(self, account_id: str) -> Path:
        return self._settings.data_dir / "profiles" / account_id

    async def _refresh_runtime_status(self, runtime: AccountRuntime, *, force: bool = False) -> None:
        if not force and runtime.ready and time.monotonic() - runtime.last_validated_at < 10.0:
            return
        try:
            await runtime.page.goto(CHATGPT_BASE_URL, wait_until="domcontentloaded")
            await _raise_if_cloudflare_challenge(runtime.page)
            check_payload = {
                "action": "next",
                "fork_from_shared_post": False,
                "parent_message_id": str(uuid4()),
                "model": "gpt-5-3",
                "timezone_offset_min": 0,
                "timezone": "UTC",
                "conversation_mode": {"kind": "primary_assistant"},
                "system_hints": [],
                "attachment_mime_types": [],
                "supports_buffering": True,
                "supported_encodings": ["v1"],
                "client_contextual_info": {"app_name": "chatgpt.com"},
            }
            response = await _page_fetch_json(
                runtime.page,
                "/backend-api/f/conversation/prepare",
                method="POST",
                headers={"Content-Type": "application/json", "Accept": "*/*"},
                json_payload=check_payload,
            )
            _raise_for_page_failure(response, default_code="validation_failed")
            runtime.ready = True
            runtime.last_error = None
            runtime.last_validated_at = time.monotonic()
        except Exception as exc:
            runtime.ready = False
            runtime.last_error = str(exc)

    async def _ensure_runtime_ready(
        self,
        runtime: AccountRuntime,
        credentials: AutomationCredentials | None,
    ) -> None:
        await self._refresh_runtime_status(runtime, force=True)
        if runtime.ready or credentials is None:
            return
        await self._attempt_auto_login(runtime.page, credentials)
        await self._refresh_runtime_status(runtime, force=True)
        if not runtime.ready:
            raise WorkerError("image_login_failed", runtime.last_error or "Automatic ChatGPT login failed")

    async def _attempt_auto_login(self, page: Page, credentials: AutomationCredentials) -> None:
        await page.goto(CHATGPT_BASE_URL, wait_until="domcontentloaded")
        await _raise_if_cloudflare_challenge(page)
        if await _page_has_prepare_access(page):
            return

        await _click_first_visible(
            page,
            [
                "button:has-text('Log in')",
                "a:has-text('Log in')",
                "button:has-text('Continue with email')",
            ],
            timeout_ms=4_000,
            required=False,
        )
        if not _url_matches_login(page.url):
            try:
                await page.goto("https://auth.openai.com/log-in", wait_until="domcontentloaded")
            except PlaywrightError:
                await page.goto(CHATGPT_BASE_URL, wait_until="domcontentloaded")
        await _raise_if_cloudflare_challenge(page)

        await _click_first_visible(
            page,
            [
                "button:has-text('Continue with email')",
                "button:has-text('Continue with Email')",
            ],
            timeout_ms=4_000,
            required=False,
        )

        email_input = await _wait_for_first_visible(page, _EMAIL_SELECTORS, timeout_ms=15_000)
        if email_input is not None:
            await email_input.fill(credentials.login_email)
            if not await _click_first_visible(
                page,
                [
                    "button:has-text('Continue')",
                    "button:has-text('Next')",
                    "button:has-text('Continue with email')",
                ],
                timeout_ms=3_000,
                required=False,
            ):
                await page.keyboard.press("Enter")

        password_input = await _wait_for_first_visible(page, _PASSWORD_SELECTORS, timeout_ms=20_000)
        if password_input is None:
            raise WorkerError("image_login_failed", "Password input did not appear during ChatGPT login")

        await password_input.fill(credentials.password)
        if not await _click_first_visible(
            page,
            [
                "button:has-text('Continue')",
                "button:has-text('Log in')",
                "button:has-text('Sign in')",
            ],
            timeout_ms=3_000,
            required=False,
        ):
            await page.keyboard.press("Enter")

        try:
            await page.wait_for_load_state("networkidle", timeout=15_000)
        except PlaywrightError:
            pass
        await page.goto(CHATGPT_BASE_URL, wait_until="domcontentloaded")
        await _raise_if_cloudflare_challenge(page)


class _UploadedAttachmentCompat:
    def __init__(
        self,
        *,
        file_id: str,
        filename: str,
        mime_type: str,
        size_bytes: int,
        width: int,
        height: int,
    ) -> None:
        self.file_id = file_id
        self.filename = filename
        self.mime_type = mime_type
        self.size_bytes = size_bytes
        self.width = width
        self.height = height


async def _page_fetch_json(
    page: Page,
    path: str,
    *,
    method: str,
    headers: dict[str, str],
    json_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return await page.evaluate(
        """async ({ path, method, headers, jsonPayload }) => {
          const response = await fetch(path, {
            method,
            credentials: "include",
            headers,
            body: jsonPayload === null ? undefined : JSON.stringify(jsonPayload),
          });
          const text = await response.text();
          const responseHeaders = {};
          for (const [key, value] of response.headers.entries()) {
            responseHeaders[key] = value;
          }
          let json = null;
          try {
            json = JSON.parse(text);
          } catch {}
          return { status: response.status, text, json, headers: responseHeaders };
        }""",
        {
            "path": path,
            "method": method,
            "headers": headers,
            "jsonPayload": json_payload,
        },
    )


async def _page_has_prepare_access(page: Page) -> bool:
    probe_payload = {
        "action": "next",
        "fork_from_shared_post": False,
        "parent_message_id": str(uuid4()),
        "model": "gpt-5-3",
        "timezone_offset_min": 0,
        "timezone": "UTC",
        "conversation_mode": {"kind": "primary_assistant"},
        "system_hints": [],
        "attachment_mime_types": [],
        "supports_buffering": True,
        "supported_encodings": ["v1"],
        "client_contextual_info": {"app_name": "chatgpt.com"},
    }
    response = await _page_fetch_json(
        page,
        "/backend-api/f/conversation/prepare",
        method="POST",
        headers={"Content-Type": "application/json", "Accept": "*/*"},
        json_payload=probe_payload,
    )
    status = response.get("status")
    return isinstance(status, int) and status < 400


async def _raise_if_cloudflare_challenge(page: Page) -> None:
    if "__cf_chl_rt_tk=" in page.url or "/cdn-cgi/challenge-platform/" in page.url:
        raise WorkerError(
            "cloudflare_challenge",
            "ChatGPT blocked the browser session with a Cloudflare challenge; automatic login cannot proceed from this environment",
        )
    try:
        body_text = await page.text_content("body", timeout=2_000)
    except PlaywrightError:
        body_text = None
    if body_text and "Enable JavaScript and cookies to continue" in body_text:
        raise WorkerError(
            "cloudflare_challenge",
            "ChatGPT blocked the browser session with a Cloudflare challenge; automatic login cannot proceed from this environment",
        )


async def _start_runtime_trace(runtime: AccountRuntime, settings: WorkerSettings) -> None:
    trace_dir = settings.browser_trace_dir or settings.data_dir / "traces"
    trace_dir.mkdir(parents=True, exist_ok=True)
    await runtime.context.tracing.start(screenshots=True, snapshots=True, sources=False)


async def _stop_runtime_trace(runtime: AccountRuntime, settings: WorkerSettings) -> None:
    trace_dir = settings.browser_trace_dir or settings.data_dir / "traces"
    trace_dir.mkdir(parents=True, exist_ok=True)
    trace_path = trace_dir / f"{runtime.account_id}-{int(time.time())}.zip"
    try:
        await runtime.context.tracing.stop(path=str(trace_path))
    except PlaywrightError:
        return


async def _page_fetch_bytes(page: Page, path: str) -> dict[str, Any]:
    return await page.evaluate(
        """async ({ path }) => {
          const response = await fetch(path, { credentials: "include" });
          const responseHeaders = {};
          for (const [key, value] of response.headers.entries()) {
            responseHeaders[key] = value;
          }
          const buffer = await response.arrayBuffer();
          const bytes = new Uint8Array(buffer);
          let binary = "";
          for (const byte of bytes) {
            binary += String.fromCharCode(byte);
          }
          return {
            status: response.status,
            headers: responseHeaders,
            base64: btoa(binary),
            text: "",
          };
        }""",
        {"path": path},
    )


async def _page_upload_bytes(page: Page, upload_url: str, content: bytes, mime_type: str) -> None:
    payload = {
        "uploadUrl": upload_url,
        "mimeType": mime_type,
        "base64": base64.b64encode(content).decode("ascii"),
    }
    response = await page.evaluate(
        """async ({ uploadUrl, mimeType, base64 }) => {
          const binary = atob(base64);
          const bytes = Uint8Array.from(binary, (char) => char.charCodeAt(0));
          const result = await fetch(uploadUrl, {
            method: "PUT",
            headers: { "Content-Type": mimeType },
            body: bytes,
          });
          return { status: result.status, text: await result.text() };
        }""",
        payload,
    )
    _raise_for_page_failure(response, default_code="image_upload_failed")


def _raise_for_page_failure(response: dict[str, Any], *, default_code: str) -> None:
    status = response.get("status")
    if not isinstance(status, int):
        raise WorkerError(default_code, "Browser request did not return a valid status")
    payload = response.get("json")
    failure = _extract_upstream_failure(payload) if isinstance(payload, (dict, list)) else None
    if failure is not None:
        raise WorkerError(failure.code, failure.message)
    if status >= 400:
        text = response.get("text")
        if isinstance(text, str) and text.strip():
            raise WorkerError(default_code, text.strip())
        raise WorkerError(default_code, f"Browser request failed with status {status}")


def _extract_conduit_token(response: dict[str, Any]) -> str | None:
    headers = response.get("headers")
    if isinstance(headers, dict):
        for key, value in headers.items():
            if key.lower() == "x-conduit-token" and isinstance(value, str) and value.strip():
                return value.strip()
    payload = response.get("json")
    if isinstance(payload, dict):
        value = payload.get("conduit_token") or payload.get("conduitToken")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _header_value(response: dict[str, Any], key: str) -> str | None:
    headers = response.get("headers")
    if not isinstance(headers, dict):
        return None
    for header_name, header_value in headers.items():
        if header_name.lower() == key.lower() and isinstance(header_value, str):
            return header_value
    return None


def _url_matches_login(url: str) -> bool:
    return bool(re.search(r"auth\.openai\.com|login|signin|sign-in", url, re.IGNORECASE))


async def _wait_for_first_visible(
    page: Page,
    selectors: tuple[str, ...],
    *,
    timeout_ms: int,
):
    for selector in selectors:
        locator = page.locator(selector).first
        try:
            await locator.wait_for(state="visible", timeout=timeout_ms)
            return locator
        except PlaywrightError:
            continue
    return None


async def _click_first_visible(
    page: Page,
    selectors: list[str],
    *,
    timeout_ms: int,
    required: bool,
) -> bool:
    for selector in selectors:
        locator = page.locator(selector).first
        try:
            await locator.wait_for(state="visible", timeout=timeout_ms)
            await locator.click()
            return True
        except PlaywrightError:
            continue
    if required:
        raise WorkerError("image_login_failed", "Could not find expected ChatGPT login control")
    return False


settings = load_settings()
worker = BrowserWorker(settings)
app = FastAPI(title="chatgpt-image-worker", version="0.1.0")


@app.on_event("startup")
async def _startup() -> None:
    await worker.start()


@app.on_event("shutdown")
async def _shutdown() -> None:
    await worker.stop()


def _authorize(authorization: str = Header(default="")) -> None:
    if authorization != f"Bearer {settings.token}":
        raise HTTPException(status_code=401, detail={"error": {"code": "unauthorized", "message": "Unauthorized"}})


@app.exception_handler(WorkerError)
async def _handle_worker_error(_request, exc: WorkerError):
    return JSONResponse(
        status_code=400,
        content=ErrorEnvelope(error={"code": exc.code, "message": exc.message}).model_dump(),
    )

@app.delete("/internal/accounts/{account_id}/session", dependencies=[Depends(_authorize)])
async def disconnect_account_session(account_id: str) -> dict[str, str]:
    await worker.disconnect_account(account_id)
    return {"status": "ok"}


@app.post("/internal/accounts/{account_id}/execute", response_model=ExecuteConversationResponse, dependencies=[Depends(_authorize)])
async def execute_conversation(account_id: str, payload: ExecuteConversationRequest) -> ExecuteConversationResponse:
    request = _parse_conversation_request_payload(payload.request)
    credentials = _parse_credentials_payload(payload.credentials)
    return await worker.execute(account_id, payload.proxy_url, request, credentials)


def _parse_conversation_request_payload(payload: dict[str, Any]) -> ChatGPTImageConversationRequest:
    model = payload.get("model")
    prompt = payload.get("prompt")
    timezone_offset_min = payload.get("timezoneOffsetMin")
    timezone = payload.get("timezone")
    if not isinstance(model, str) or not model.strip():
        raise WorkerError("invalid_request", "Conversation request is missing model")
    if not isinstance(prompt, str) or not prompt.strip():
        raise WorkerError("invalid_request", "Conversation request is missing prompt")
    if not isinstance(timezone_offset_min, int):
        raise WorkerError("invalid_request", "Conversation request is missing timezoneOffsetMin")
    if not isinstance(timezone, str) or not timezone.strip():
        raise WorkerError("invalid_request", "Conversation request is missing timezone")

    client_context_raw = payload.get("clientContext")
    client_context: dict[str, str | int | float | bool | None] = {}
    if isinstance(client_context_raw, dict):
        for key, value in client_context_raw.items():
            if not isinstance(key, str):
                continue
            if isinstance(value, (str, int, float, bool)) or value is None:
                client_context[key] = value

    attachments_raw = payload.get("attachments")
    attachments = []
    if isinstance(attachments_raw, list):
        for item in attachments_raw:
            if not isinstance(item, dict):
                raise WorkerError("invalid_request", "Conversation attachment payload was invalid")
            data_url = item.get("dataUrl")
            mime_type = item.get("mimeType")
            filename = item.get("filename")
            if not isinstance(data_url, str) or not isinstance(mime_type, str) or not isinstance(filename, str):
                raise WorkerError("invalid_request", "Conversation attachment payload was incomplete")
            attachments.append(
                ChatGPTImageAttachmentInput(
                    data_url=data_url,
                    mime_type=mime_type,
                    filename=filename,
                )
            )

    edit_target_raw = payload.get("editTarget")
    edit_target = None
    if edit_target_raw is not None:
        if not isinstance(edit_target_raw, dict):
            raise WorkerError("invalid_request", "Conversation edit target payload was invalid")
        file_id = edit_target_raw.get("fileId")
        original_gen_id = edit_target_raw.get("originalGenId")
        if not isinstance(file_id, str) or not file_id.strip():
            raise WorkerError("invalid_request", "Conversation edit target is missing fileId")
        if original_gen_id is not None and not isinstance(original_gen_id, str):
            raise WorkerError("invalid_request", "Conversation edit target originalGenId was invalid")
        edit_target = ChatGPTImageEditTarget(
            file_id=file_id,
            original_gen_id=original_gen_id,
        )

    conversation_id = payload.get("conversationId")
    if conversation_id is not None and not isinstance(conversation_id, str):
        raise WorkerError("invalid_request", "Conversation conversationId was invalid")
    parent_message_id = payload.get("parentMessageId")
    if parent_message_id is not None and not isinstance(parent_message_id, str):
        raise WorkerError("invalid_request", "Conversation parentMessageId was invalid")

    return ChatGPTImageConversationRequest(
        model=model,
        prompt=prompt,
        conversation_id=conversation_id,
        parent_message_id=parent_message_id,
        timezone_offset_min=timezone_offset_min,
        timezone=timezone,
        client_context=client_context,
        attachments=tuple(attachments),
        edit_target=edit_target,
    )


def _parse_credentials_payload(payload: dict[str, str] | None) -> AutomationCredentials | None:
    if payload is None:
        return None
    login_email = payload.get("loginEmail")
    password = payload.get("password")
    if not isinstance(login_email, str) or not login_email.strip():
        raise WorkerError("invalid_request", "Conversation credentials are missing loginEmail")
    if not isinstance(password, str) or not password.strip():
        raise WorkerError("invalid_request", "Conversation credentials are missing password")
    return AutomationCredentials(login_email=login_email.strip(), password=password)
