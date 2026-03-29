from __future__ import annotations

import json

import pytest

from app.core.clients.chatgpt_image_worker import ChatGPTImageWorkerError
from app.core.clients.chatgpt_images import (
    ChatGPTImageConversationRequest,
    ChatGPTImageConversationResult,
    GeneratedImageAsset,
)
from app.core.crypto import TokenEncryptor
from app.core.utils.time import utcnow
from app.db.models import Account, AccountStatus
from app.db.session import SessionLocal
from app.modules.accounts.image_session_store import ChatGPTImageSessionStatus

pytestmark = pytest.mark.integration


def _make_account(
    account_id: str,
    chatgpt_account_id: str,
    email: str,
    *,
    status: AccountStatus = AccountStatus.ACTIVE,
) -> Account:
    encryptor = TokenEncryptor()
    return Account(
        id=account_id,
        chatgpt_account_id=chatgpt_account_id,
        email=email,
        plan_type="plus",
        access_token_encrypted=encryptor.encrypt("access"),
        refresh_token_encrypted=encryptor.encrypt("refresh"),
        id_token_encrypted=encryptor.encrypt("id"),
        last_refresh=utcnow(),
        status=status,
        deactivation_reason=None,
    )


async def _store_accounts(*accounts: Account) -> None:
    async with SessionLocal() as session:
        session.add_all(accounts)
        await session.commit()


def _events_from_lines(lines: list[str]) -> list[dict]:
    events: list[dict] = []
    for line in lines:
        if line.startswith("data: "):
            events.append(json.loads(line[6:]))
    return events


def _ready_status() -> ChatGPTImageSessionStatus:
    return ChatGPTImageSessionStatus(
        status="ready",
        last_validated_at=utcnow(),
        last_error=None,
    )


class _FakeImageSessionsService:
    def __init__(
        self,
        *,
        statuses: dict[str, ChatGPTImageSessionStatus] | None = None,
        result: ChatGPTImageConversationResult | None = None,
        error: Exception | None = None,
    ) -> None:
        self._statuses = statuses or {}
        self._result = result
        self._error = error
        self.calls: list[tuple[str, str | None, ChatGPTImageConversationRequest]] = []

    def status_for_account(self, account_id: str) -> ChatGPTImageSessionStatus:
        return self._statuses.get(
            account_id,
            ChatGPTImageSessionStatus(
                status="disconnected",
                last_validated_at=None,
                last_error=None,
            ),
        )

    def statuses_for_accounts(self, account_ids: list[str]) -> dict[str, ChatGPTImageSessionStatus]:
        return {account_id: self.status_for_account(account_id) for account_id in account_ids}

    async def execute_image_conversation(
        self,
        *,
        account_id: str,
        proxy_url: str | None,
        request: ChatGPTImageConversationRequest,
    ) -> ChatGPTImageConversationResult:
        self.calls.append((account_id, proxy_url, request))
        if self._error is not None:
            raise self._error
        if self._result is None:
            raise AssertionError("Fake image sessions service was missing a result")
        return self._result


@pytest.mark.asyncio
async def test_dashboard_images_requires_dashboard_session(anonymous_client):
    response = await anonymous_client.post(
        "/api/dashboard-images/conversation",
        json={"model": "gpt-5.3", "prompt": "Generate a door"},
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "authentication_required"


@pytest.mark.asyncio
async def test_dashboard_images_auto_mode_emits_started_and_completed(app_instance, async_client):
    await _store_accounts(_make_account("acc_auto", "workspace_auto", "auto@example.com"))
    fake_service = _FakeImageSessionsService(
        statuses={"acc_auto": _ready_status()},
        result=ChatGPTImageConversationResult(
            conversation_id="conv_1",
            assistant_message_id="msg_1",
            parent_message_id="msg_1",
            assistant_text="Updated as requested",
            images=(
                GeneratedImageAsset(
                    data_url="data:image/png;base64,ZmFrZQ==",
                    mime_type="image/png",
                    filename="file_generated_1.png",
                    file_id="file_generated_1",
                    original_gen_id="gen_1",
                    revised_prompt="Bright white door",
                ),
            ),
        ),
    )
    app_instance.state.chatgpt_image_sessions_service = fake_service

    async with async_client.stream(
        "POST",
        "/api/dashboard-images/conversation",
        json={"model": "gpt-5.3", "prompt": "Replace the door", "timezone": "UTC"},
    ) as response:
        assert response.status_code == 200
        lines = [line async for line in response.aiter_lines() if line]

    events = _events_from_lines(lines)
    assert events[0] == {
        "type": "dashboard.images.started",
        "mode": "auto",
        "requestedAccountId": None,
        "resolvedAccountId": "acc_auto",
    }
    assert events[1]["type"] == "dashboard.images.progress"
    assert events[-1]["type"] == "dashboard.images.completed"
    assert events[-1]["conversationId"] == "conv_1"
    assert events[-1]["images"][0]["fileId"] == "file_generated_1"
    assert fake_service.calls == [
        (
            "acc_auto",
            None,
            ChatGPTImageConversationRequest(
                model="gpt-5.3",
                prompt="Replace the door",
                conversation_id=None,
                parent_message_id=None,
                timezone_offset_min=0,
                timezone="UTC",
                client_context={},
                attachments=(),
                edit_target=None,
            ),
        )
    ]


@pytest.mark.asyncio
async def test_dashboard_images_selected_account_does_not_failover(app_instance, async_client):
    await _store_accounts(
        _make_account("acc_selected", "workspace_selected", "selected@example.com"),
        _make_account("acc_other", "workspace_other", "other@example.com"),
    )
    fake_service = _FakeImageSessionsService(
        statuses={
            "acc_selected": _ready_status(),
            "acc_other": _ready_status(),
        },
        error=ChatGPTImageWorkerError("rate_limit_exceeded", "slow down"),
    )
    app_instance.state.chatgpt_image_sessions_service = fake_service

    async with async_client.stream(
        "POST",
        "/api/dashboard-images/conversation",
        json={
            "accountId": "acc_selected",
            "model": "gpt-5.3",
            "prompt": "Replace the door",
            "timezone": "UTC",
        },
    ) as response:
        assert response.status_code == 200
        lines = [line async for line in response.aiter_lines() if line]

    events = _events_from_lines(lines)
    assert events[0] == {
        "type": "dashboard.images.started",
        "mode": "account",
        "requestedAccountId": "acc_selected",
        "resolvedAccountId": "acc_selected",
    }
    assert events[-1] == {
        "type": "dashboard.images.failed",
        "code": "rate_limit_exceeded",
        "message": "slow down",
    }
    assert [call[0] for call in fake_service.calls] == ["acc_selected"]


@pytest.mark.asyncio
async def test_dashboard_images_rejects_non_active_account_selection(async_client):
    await _store_accounts(
        _make_account(
            "acc_paused",
            "workspace_paused",
            "paused@example.com",
            status=AccountStatus.PAUSED,
        )
    )

    response = await async_client.post(
        "/api/dashboard-images/conversation",
        json={"accountId": "acc_paused", "model": "gpt-5.3", "prompt": "Replace the door", "timezone": "UTC"},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_account_selection"


@pytest.mark.asyncio
async def test_dashboard_images_requires_ready_image_session_for_explicit_account(app_instance, async_client):
    await _store_accounts(_make_account("acc_needs_connect", "workspace_cookie", "cookie@example.com"))
    app_instance.state.chatgpt_image_sessions_service = _FakeImageSessionsService()

    response = await async_client.post(
        "/api/dashboard-images/conversation",
        json={
            "accountId": "acc_needs_connect",
            "model": "gpt-5.3",
            "prompt": "Generate",
            "timezone": "UTC",
        },
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "image_session_unavailable"
