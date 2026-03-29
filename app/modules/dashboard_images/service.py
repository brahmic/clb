from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass

from app.core.clients.chatgpt_images import (
    ChatGPTImageAttachmentInput,
    ChatGPTImageConversationRequest,
    ChatGPTImageEditTarget,
    ChatGPTImageUpstreamError,
)
from app.core.clients.chatgpt_image_worker import ChatGPTImageWorkerError
from app.core.utils.sse import format_sse_event
from app.db.models import Account
from app.modules.accounts.auth_manager import AuthManager
from app.modules.dashboard_images.repository import DashboardImagesRepository
from app.modules.dashboard_images.schemas import (
    DashboardGeneratedImage,
    DashboardImagesCompletedEvent,
    DashboardImagesConversationRequest,
    DashboardImagesFailedEvent,
    DashboardImagesProgressEvent,
    DashboardImagesStartedEvent,
)
from app.modules.chatgpt_image_sessions.service import (
    ChatGPTImageSessionsService,
    ImageSessionUnavailableError,
)
from app.modules.proxy.load_balancer import LoadBalancer
from app.modules.proxy.repo_bundle import ProxyRepoFactory
from app.modules.proxy_profiles.runtime import ProxyProfileResolutionError, resolve_account_proxy_connection_from_db


@dataclass(frozen=True, slots=True)
class PreparedDashboardImageRequest:
    requested_account_id: str | None
    selected_account: Account
    mode: str
    payload: ChatGPTImageConversationRequest


class InvalidAccountSelectionError(Exception):
    def __init__(self, message: str, *, code: str = "invalid_account_selection") -> None:
        super().__init__(message)
        self.code = code


class AutoRoutingUnavailableError(Exception):
    def __init__(self, message: str, *, code: str = "routing_unavailable") -> None:
        super().__init__(message)
        self.code = code


class DashboardImagesService:
    def __init__(
        self,
        repository: DashboardImagesRepository,
        repo_factory: ProxyRepoFactory,
        image_sessions_service: ChatGPTImageSessionsService | None = None,
    ) -> None:
        self._repository = repository
        self._repo_factory = repo_factory
        self._load_balancer = LoadBalancer(repo_factory)
        self._image_sessions = image_sessions_service or ChatGPTImageSessionsService()

    async def stream_conversation(
        self,
        payload: DashboardImagesConversationRequest,
        headers: Mapping[str, str],
    ) -> AsyncIterator[str]:
        prepared = await self.prepare_request(payload)
        return self._stream_prepared_conversation(prepared, headers)

    async def prepare_request(
        self,
        payload: DashboardImagesConversationRequest,
    ) -> PreparedDashboardImageRequest:
        selected_account: Account
        mode: str
        if payload.account_id is not None:
            explicit_account = await self._repository.get_active_account(payload.account_id)
            if explicit_account is None:
                raise InvalidAccountSelectionError("Selected account is unavailable")
            if not self._image_sessions.is_account_routable(explicit_account.id):
                raise InvalidAccountSelectionError(
                    "Selected account does not have ChatGPT Images automation configured",
                    code="image_session_unavailable",
                )
            selected_account = explicit_account
            mode = "account"
        else:
            active_account_ids = await self._repository.list_active_account_ids()
            excluded_account_ids = [
                account_id
                for account_id in active_account_ids
                if not self._image_sessions.is_account_routable(account_id)
            ]
            if len(excluded_account_ids) == len(active_account_ids) and active_account_ids:
                raise AutoRoutingUnavailableError(
                    "No active account has ChatGPT Images automation configured",
                    code="image_session_unavailable",
                )
            selection = await self._load_balancer.select_account(
                model=payload.model,
                exclude_account_ids=excluded_account_ids,
            )
            if selection.account is None:
                raise AutoRoutingUnavailableError(
                    selection.error_message or "No available account could serve this image request",
                    code=selection.error_code or "routing_unavailable",
                )
            selected_account = selection.account
            mode = "auto"

        return PreparedDashboardImageRequest(
            requested_account_id=payload.account_id,
            selected_account=selected_account,
            mode=mode,
            payload=ChatGPTImageConversationRequest(
                model=payload.model,
                prompt=payload.prompt,
                conversation_id=payload.conversation_id,
                parent_message_id=payload.parent_message_id,
                timezone_offset_min=payload.timezone_offset_min,
                timezone=payload.timezone,
                client_context=payload.client_context,
                attachments=tuple(
                    ChatGPTImageAttachmentInput(
                        data_url=attachment.data_url,
                        mime_type=attachment.mime_type,
                        filename=attachment.filename,
                    )
                    for attachment in payload.attachments
                ),
                edit_target=(
                    ChatGPTImageEditTarget(
                        file_id=payload.edit_target.file_id,
                        original_gen_id=payload.edit_target.original_gen_id,
                    )
                    if payload.edit_target is not None
                    else None
                ),
            ),
        )

    async def _stream_prepared_conversation(
        self,
        prepared: PreparedDashboardImageRequest,
        _headers: Mapping[str, str],
    ) -> AsyncIterator[str]:
        yield format_sse_event(
            DashboardImagesStartedEvent(
                mode=prepared.mode,  # type: ignore[arg-type]
                requested_account_id=prepared.requested_account_id,
                resolved_account_id=prepared.selected_account.id,
            ).model_dump(by_alias=True)
        )

        try:
            fresh_account = await self._ensure_fresh_account(prepared.selected_account)
            connection = await resolve_account_proxy_connection_from_db(fresh_account)
        except ProxyProfileResolutionError as exc:
            yield format_sse_event(
                DashboardImagesFailedEvent(
                    code="proxy_connection_unavailable",
                    message=str(exc),
                ).model_dump(by_alias=True)
            )
            return
        except Exception:
            yield format_sse_event(
                DashboardImagesFailedEvent(
                    code="account_preparation_failed",
                    message="Failed to prepare the selected account for image generation",
                ).model_dump(by_alias=True)
            )
            return

        image_session_status = self._image_sessions.status_for_account(fresh_account.id)
        if image_session_status.status != "ready":
            yield _progress_event("starting_browser", "Starting ChatGPT browser session")
            if self._image_sessions.can_auto_bootstrap(fresh_account.id):
                yield _progress_event("logging_in", "Logging into ChatGPT")
            yield _progress_event("checking_access", "Checking ChatGPT access")

        if prepared.payload.attachments:
            yield _progress_event("uploading", "Uploading reference images")
        if prepared.payload.edit_target is not None:
            yield _progress_event("editing", "Preparing image transformation")
        yield _progress_event("processing", "Waiting for generated images")

        try:
            result = await self._image_sessions.execute_image_conversation(
                account_id=fresh_account.id,
                proxy_url=connection.proxy_url,
                request=prepared.payload,
            )
        except ImageSessionUnavailableError as exc:
            yield format_sse_event(
                DashboardImagesFailedEvent(code=exc.code, message=str(exc)).model_dump(by_alias=True)
            )
            return
        except ChatGPTImageWorkerError as exc:
            yield format_sse_event(
                DashboardImagesFailedEvent(code=exc.code, message=exc.message).model_dump(by_alias=True)
            )
            return
        except ChatGPTImageUpstreamError as exc:
            yield format_sse_event(
                DashboardImagesFailedEvent(code=exc.code, message=exc.message).model_dump(by_alias=True)
            )
            return

        yield format_sse_event(
            DashboardImagesCompletedEvent(
                conversation_id=result.conversation_id,
                assistant_message_id=result.assistant_message_id,
                parent_message_id=result.parent_message_id,
                assistant_text=result.assistant_text,
                images=[
                    DashboardGeneratedImage(
                        data_url=image.data_url,
                        mime_type=image.mime_type,
                        filename=image.filename,
                        file_id=image.file_id,
                        original_gen_id=image.original_gen_id,
                        revised_prompt=image.revised_prompt,
                    )
                    for image in result.images
                ],
            ).model_dump(by_alias=True)
        )

    async def _ensure_fresh_account(self, account: Account) -> Account:
        async with self._repo_factory() as repos:
            manager = AuthManager(repos.accounts)
            return await manager.ensure_fresh(account)


def _progress_event(phase: str, message: str | None) -> str:
    return format_sse_event(
        DashboardImagesProgressEvent(phase=phase, message=message).model_dump(by_alias=True)
    )
