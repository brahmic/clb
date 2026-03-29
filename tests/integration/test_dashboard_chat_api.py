from __future__ import annotations

import json

import pytest
from sqlalchemy import select

import app.modules.proxy.service as proxy_module
from app.core.crypto import TokenEncryptor
from app.core.utils.time import utcnow
from app.db.models import Account, AccountStatus, RequestLog
from app.db.session import SessionLocal

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


@pytest.mark.asyncio
async def test_dashboard_chat_requires_dashboard_session(anonymous_client):
    response = await anonymous_client.post(
        "/api/dashboard-chat/responses",
        json={
            "model": "gpt-5.1",
            "messages": [{"role": "user", "content": [{"type": "text", "text": "hello"}]}],
        },
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "authentication_required"


@pytest.mark.asyncio
async def test_dashboard_chat_auto_mode_emits_started_event(async_client, monkeypatch):
    await _store_accounts(_make_account("acc_auto", "workspace_auto", "auto@example.com"))

    async def fake_stream(payload, headers, access_token, account_id, **_kwargs):
        assert account_id == "workspace_auto"
        assert payload.model == "gpt-5.1"
        yield 'data: {"type":"response.output_text.delta","delta":"hi"}\n\n'
        yield 'data: {"type":"response.completed","response":{"id":"resp_auto"}}\n\n'

    monkeypatch.setattr(proxy_module, "core_stream_responses", fake_stream)

    async with async_client.stream(
        "POST",
        "/api/dashboard-chat/responses",
        json={
            "model": "gpt-5.1",
            "messages": [{"role": "user", "content": [{"type": "text", "text": "hello"}]}],
        },
    ) as response:
        assert response.status_code == 200
        lines = [line async for line in response.aiter_lines() if line]

    events = _events_from_lines(lines)
    assert events[0] == {
        "type": "dashboard.chat.started",
        "mode": "auto",
        "requestedAccountId": None,
        "resolvedAccountId": "acc_auto",
    }
    assert events[1]["type"] == "response.output_text.delta"
    assert events[2]["type"] == "response.completed"


@pytest.mark.asyncio
async def test_dashboard_chat_selected_account_does_not_failover(async_client, monkeypatch):
    await _store_accounts(
        _make_account("acc_selected", "workspace_selected", "selected@example.com"),
        _make_account("acc_other", "workspace_other", "other@example.com"),
    )

    async def fake_stream(payload, headers, access_token, account_id, **_kwargs):
        assert account_id == "workspace_selected"
        yield (
            'data: {"type":"response.failed","response":{"error":{"code":"rate_limit_exceeded","message":"slow down"}}}\n\n'
        )

    monkeypatch.setattr(proxy_module, "core_stream_responses", fake_stream)

    async with async_client.stream(
        "POST",
        "/api/dashboard-chat/responses",
        json={
            "accountId": "acc_selected",
            "model": "gpt-5.1",
            "messages": [{"role": "user", "content": [{"type": "text", "text": "hello"}]}],
        },
    ) as response:
        assert response.status_code == 200
        lines = [line async for line in response.aiter_lines() if line]

    events = _events_from_lines(lines)
    assert events[0] == {
        "type": "dashboard.chat.started",
        "mode": "account",
        "requestedAccountId": "acc_selected",
        "resolvedAccountId": "acc_selected",
    }
    assert events[-1]["type"] == "response.failed"
    assert events[-1]["response"]["error"]["code"] == "rate_limit_exceeded"

    async with SessionLocal() as session:
        result = await session.execute(select(RequestLog).order_by(RequestLog.requested_at.desc()))
        logs = list(result.scalars().all())
        assert len(logs) == 1
        assert logs[0].account_id == "acc_selected"


@pytest.mark.asyncio
async def test_dashboard_chat_rejects_non_active_account_selection(async_client):
    await _store_accounts(
        _make_account(
            "acc_paused",
            "workspace_paused",
            "paused@example.com",
            status=AccountStatus.PAUSED,
        )
    )

    response = await async_client.post(
        "/api/dashboard-chat/responses",
        json={
            "accountId": "acc_paused",
            "model": "gpt-5.1",
            "messages": [{"role": "user", "content": [{"type": "text", "text": "hello"}]}],
        },
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_account_selection"


@pytest.mark.asyncio
async def test_dashboard_chat_maps_image_parts_to_input_image(async_client, monkeypatch):
    await _store_accounts(_make_account("acc_image", "workspace_image", "image@example.com"))

    async def fake_stream(payload, headers, access_token, account_id, **_kwargs):
        assert account_id == "workspace_image"
        assert payload.input == [
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": "what is this"},
                    {"type": "input_image", "image_url": "data:image/png;base64,Zm9v"},
                ],
            }
        ]
        yield 'data: {"type":"response.completed","response":{"id":"resp_image"}}\n\n'

    monkeypatch.setattr(proxy_module, "core_stream_responses", fake_stream)

    async with async_client.stream(
        "POST",
        "/api/dashboard-chat/responses",
        json={
            "model": "gpt-5.1",
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "what is this"},
                        {
                            "type": "image",
                            "dataUrl": "data:image/png;base64,Zm9v",
                            "mimeType": "image/png",
                            "filename": "test.png",
                        },
                    ],
                }
            ],
        },
    ) as response:
        assert response.status_code == 200
        lines = [line async for line in response.aiter_lines() if line]

    events = _events_from_lines(lines)
    assert events[0]["type"] == "dashboard.chat.started"
    assert events[-1]["type"] == "response.completed"
