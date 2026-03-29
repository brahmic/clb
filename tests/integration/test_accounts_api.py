from __future__ import annotations

import base64
import json
from datetime import UTC, datetime, timedelta

import pytest

from app.core.auth import generate_unique_account_id
from app.modules.accounts.image_session_store import AccountImageSessionStore
from app.modules.accounts.image_session_store import ChatGPTImageSessionStatus

pytestmark = pytest.mark.integration


def _encode_jwt(payload: dict) -> str:
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    body = base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")
    return f"header.{body}.sig"


def _import_payload(email: str, raw_account_id: str) -> dict:
    return {
        "tokens": {
            "idToken": _encode_jwt(
                {
                    "email": email,
                    "chatgpt_account_id": raw_account_id,
                    "https://api.openai.com/auth": {"chatgpt_plan_type": "plus"},
                }
            ),
            "accessToken": "access",
            "refreshToken": "refresh",
            "accountId": raw_account_id,
        },
    }


class _FakeImageSessionsService:
    def __init__(self) -> None:
        self.store = AccountImageSessionStore()
        self.statuses: dict[str, ChatGPTImageSessionStatus] = {}

    def status_for_account(self, account_id: str) -> ChatGPTImageSessionStatus:
        return self.statuses.get(
            account_id,
            ChatGPTImageSessionStatus(
                status="disconnected",
                last_validated_at=None,
                last_error=None,
            ),
        )

    async def disconnect_account(self, *, account_id: str) -> ChatGPTImageSessionStatus:
        self.statuses[account_id] = self.store.clear(account_id)
        return self.statuses[account_id]


@pytest.mark.asyncio
async def test_import_and_list_accounts(async_client):
    email = "tester@example.com"
    raw_account_id = "acc_explicit"
    payload = {
        "email": email,
        "chatgpt_account_id": "acc_payload",
        "https://api.openai.com/auth": {"chatgpt_plan_type": "plus"},
    }
    auth_json = {
        "tokens": {
            "idToken": _encode_jwt(payload),
            "accessToken": "access",
            "refreshToken": "refresh",
            "accountId": raw_account_id,
        },
    }

    expected_account_id = generate_unique_account_id(raw_account_id, email)
    files = {"auth_json": ("auth.json", json.dumps(auth_json), "application/json")}
    response = await async_client.post("/api/accounts/import", files=files)
    assert response.status_code == 200
    data = response.json()
    assert data["accountId"] == expected_account_id
    assert data["email"] == email
    assert data["planType"] == "plus"

    list_response = await async_client.get("/api/accounts")
    assert list_response.status_code == 200
    accounts = list_response.json()["accounts"]
    assert any(account["accountId"] == expected_account_id for account in accounts)


@pytest.mark.asyncio
async def test_reactivate_missing_account_returns_404(async_client):
    response = await async_client.post("/api/accounts/missing/reactivate")
    assert response.status_code == 404
    payload = response.json()
    assert payload["error"]["code"] == "account_not_found"


@pytest.mark.asyncio
async def test_pause_missing_account_returns_404(async_client):
    response = await async_client.post("/api/accounts/missing/pause")
    assert response.status_code == 404
    payload = response.json()
    assert payload["error"]["code"] == "account_not_found"


@pytest.mark.asyncio
async def test_pause_account(async_client):
    email = "pause@example.com"
    raw_account_id = "acc_pause"
    payload = {
        "email": email,
        "chatgpt_account_id": raw_account_id,
        "https://api.openai.com/auth": {"chatgpt_plan_type": "plus"},
    }
    auth_json = {
        "tokens": {
            "idToken": _encode_jwt(payload),
            "accessToken": "access",
            "refreshToken": "refresh",
            "accountId": raw_account_id,
        },
    }

    expected_account_id = generate_unique_account_id(raw_account_id, email)
    files = {"auth_json": ("auth.json", json.dumps(auth_json), "application/json")}
    response = await async_client.post("/api/accounts/import", files=files)
    assert response.status_code == 200

    pause = await async_client.post(f"/api/accounts/{expected_account_id}/pause")
    assert pause.status_code == 200
    assert pause.json()["status"] == "paused"

    accounts = await async_client.get("/api/accounts")
    assert accounts.status_code == 200
    data = accounts.json()["accounts"]
    matched = next((account for account in data if account["accountId"] == expected_account_id), None)
    assert matched is not None
    assert matched["status"] == "paused"


@pytest.mark.asyncio
async def test_delete_missing_account_returns_404(async_client):
    response = await async_client.delete("/api/accounts/missing")
    assert response.status_code == 404
    payload = response.json()
    assert payload["error"]["code"] == "account_not_found"


@pytest.mark.asyncio
async def test_chatgpt_image_session_status_and_disconnect(app_instance, async_client):
    email = "images@example.com"
    raw_account_id = "acc_images"
    expected_account_id = generate_unique_account_id(raw_account_id, email)
    files = {"auth_json": ("auth.json", json.dumps(_import_payload(email, raw_account_id)), "application/json")}
    imported = await async_client.post("/api/accounts/import", files=files)
    assert imported.status_code == 200

    fake_service = _FakeImageSessionsService()
    app_instance.state.chatgpt_image_sessions_service = fake_service

    initial = await async_client.get(f"/api/accounts/{expected_account_id}/chatgpt-image-session")
    assert initial.status_code == 200
    assert initial.json() == {
        "accountId": expected_account_id,
        "status": "disconnected",
        "lastValidatedAt": None,
        "lastError": None,
    }
    fake_service.statuses[expected_account_id] = fake_service.store.set_ready(
        expected_account_id,
        validated_at=datetime.now(UTC),
    )

    ready = await async_client.get(f"/api/accounts/{expected_account_id}/chatgpt-image-session")
    assert ready.status_code == 200
    assert ready.json()["status"] == "ready"
    assert ready.json()["lastValidatedAt"] is not None


@pytest.mark.asyncio
async def test_update_and_clear_chatgpt_image_credentials(async_client):
    email = "images-creds@example.com"
    raw_account_id = "acc_image_creds"
    expected_account_id = generate_unique_account_id(raw_account_id, email)
    files = {"auth_json": ("auth.json", json.dumps(_import_payload(email, raw_account_id)), "application/json")}
    imported = await async_client.post("/api/accounts/import", files=files)
    assert imported.status_code == 200

    updated = await async_client.put(
        f"/api/accounts/{expected_account_id}/chatgpt-image-credentials",
        json={"loginEmail": "worker@example.com", "password": "secret-password"},
    )
    assert updated.status_code == 200
    assert updated.json()["accountId"] == expected_account_id
    assert updated.json()["configured"] is True
    assert updated.json()["loginEmail"] == "worker@example.com"
    assert updated.json()["updatedAt"] is not None

    listed = await async_client.get("/api/accounts")
    assert listed.status_code == 200
    account = next(item for item in listed.json()["accounts"] if item["accountId"] == expected_account_id)
    assert account["chatgptImageCredentials"] == {
        "configured": True,
        "loginEmail": "worker@example.com",
        "updatedAt": updated.json()["updatedAt"],
    }

    cleared = await async_client.delete(f"/api/accounts/{expected_account_id}/chatgpt-image-credentials")
    assert cleared.status_code == 200
    assert cleared.json() == {
        "accountId": expected_account_id,
        "configured": False,
        "loginEmail": None,
        "updatedAt": None,
    }

    listed = await async_client.get("/api/accounts")
    assert listed.status_code == 200
    account = next(item for item in listed.json()["accounts"] if item["accountId"] == expected_account_id)
    assert account["chatgptImageSession"]["status"] == "ready"
    assert account["chatgptImageSession"]["lastValidatedAt"] is not None

    disconnected = await async_client.delete(f"/api/accounts/{expected_account_id}/chatgpt-image-session")
    assert disconnected.status_code == 200
    assert disconnected.json() == {
        "accountId": expected_account_id,
        "status": "disconnected",
        "lastValidatedAt": None,
        "lastError": None,
    }
