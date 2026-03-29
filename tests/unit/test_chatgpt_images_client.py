from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID

import pytest

import app.core.clients.chatgpt_images as chatgpt_images_module
from app.core.clients.chatgpt_images import (
    ChatGPTImageAttachmentInput,
    ChatGPTImageConversationRequest,
    ChatGPTImageEditTarget,
    ChatGPTImagesClient,
)
from app.db.models import Account, AccountStatus

_ONE_BY_ONE_PNG = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/a7sAAAAASUVORK5CYII="
)


class FakeResponse:
    def __init__(
        self,
        *,
        status: int = 200,
        json_body: object | None = None,
        text_body: str | None = None,
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status = status
        self.reason = "OK" if status < 400 else "Bad Request"
        self._json_body = json_body
        self._text_body = text_body if text_body is not None else json.dumps(json_body) if json_body is not None else ""
        self._body = body if body is not None else self._text_body.encode("utf-8")
        self.headers = headers or {}

    async def __aenter__(self) -> "FakeResponse":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False

    async def json(self, *, content_type: str | None = None):
        if self._json_body is None:
            raise ValueError("No JSON body")
        return self._json_body

    async def text(self) -> str:
        return self._text_body

    async def read(self) -> bytes:
        return self._body


class FakeSession:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self._responses = responses
        self.calls: list[dict[str, object]] = []

    def request(self, method: str, url: str, **kwargs) -> FakeResponse:
        self.calls.append({"method": method, "url": url, **kwargs})
        if not self._responses:
            raise AssertionError(f"Unexpected request: {method} {url}")
        return self._responses.pop(0)

    def put(self, url: str, **kwargs) -> FakeResponse:
        return self.request("PUT", url, **kwargs)

    def get(self, url: str, **kwargs) -> FakeResponse:
        return self.request("GET", url, **kwargs)


def _make_account() -> Account:
    return Account(
        id="acc_1",
        chatgpt_account_id="workspace_1",
        email="user@example.com",
        plan_type="plus",
        access_token_encrypted=b"",
        refresh_token_encrypted=b"",
        id_token_encrypted=b"",
        status=AccountStatus.ACTIVE,
        last_refresh=datetime.now(UTC),
    )


@pytest.mark.asyncio
async def test_client_uploads_reference_images_and_maps_them_to_asset_pointers(monkeypatch):
    fake_session = FakeSession(
        [
            FakeResponse(json_body={}, headers={"x-conduit-token": "conduit_123"}),
            FakeResponse(json_body={"file_id": "file_ref_1", "upload_url": "https://upload.example/ref_1"}),
            FakeResponse(text_body="uploaded"),
            FakeResponse(json_body={}),
            FakeResponse(json_body={"conversation_id": "conv_1", "message_id": "msg_pending_1"}),
            FakeResponse(
                json_body={
                    "status": "finished_successfully",
                    "conversation_id": "conv_1",
                    "message_id": "msg_asst_1",
                    "messages": [
                        {
                            "id": "msg_asst_1",
                            "content": {
                                "parts": [
                                    "Updated as requested",
                                    {
                                        "content_type": "image_asset_pointer",
                                        "asset_pointer": "sediment://file_generated_1",
                                        "metadata": {
                                            "dalle": {
                                                "gen_id": "gen_1",
                                                "revised_prompt": "Bright white door",
                                            }
                                        },
                                    },
                                ]
                            },
                        }
                    ],
                }
            ),
            FakeResponse(body=b"fake-image", headers={"Content-Type": "image/png"}),
        ]
    )
    monkeypatch.setattr(
        chatgpt_images_module,
        "get_http_client",
        lambda: SimpleNamespace(session=fake_session),
    )

    client = ChatGPTImagesClient()
    result = await client.run_conversation(
        account=_make_account(),
        access_token="access",
        request=ChatGPTImageConversationRequest(
            model="gpt-5.3",
            prompt="Replace the dark door with a bright white one",
            conversation_id=None,
            parent_message_id=None,
            timezone_offset_min=-180,
            timezone="Europe/Moscow",
            client_context={"app_name": "chatgpt.com", "page_width": 1512},
            attachments=(
                ChatGPTImageAttachmentInput(
                    data_url=_ONE_BY_ONE_PNG,
                    mime_type="image/png",
                    filename="hallway.png",
                ),
            ),
            edit_target=None,
        ),
        headers={"X-Test": "1"},
        proxy_url=None,
        cookies={"oai-did": "device-cookie", "cf_clearance": "cf-cookie"},
    )

    prepare_call = next(
        call
        for call in fake_session.calls
        if call["method"] == "POST" and str(call["url"]).endswith("/f/conversation/prepare")
    )
    conversation_call = next(
        call
        for call in fake_session.calls
        if call["method"] == "POST" and str(call["url"]).endswith("/f/conversation")
    )
    prepare_payload = prepare_call["json"]
    prepare_headers = prepare_call["headers"]
    payload = conversation_call["json"]
    headers = conversation_call["headers"]
    assert prepare_payload["action"] == "next"
    assert prepare_payload["system_hints"] == []
    assert prepare_payload["attachment_mime_types"] == ["image/png"]
    assert prepare_payload["client_contextual_info"] == {"app_name": "chatgpt.com"}
    UUID(prepare_payload["parent_message_id"])
    assert prepare_headers["Accept"] == "*/*"
    assert prepare_headers["Origin"] == "https://chatgpt.com"
    assert prepare_headers["Referer"] == "https://chatgpt.com"
    assert prepare_headers["User-Agent"].startswith("Mozilla/5.0")
    assert prepare_headers["OAI-Language"] == "en-US"
    assert prepare_headers["OAI-Client-Version"].startswith("prod-")
    assert prepare_headers["OAI-Client-Build-Number"] == "5583259"
    assert prepare_headers["OAI-Device-Id"] == "device-cookie"
    UUID(prepare_headers["OAI-Session-Id"])
    assert prepare_headers["Cookie"] == "oai-did=device-cookie; cf_clearance=cf-cookie"
    assert "X-Test" not in prepare_headers
    assert payload["system_hints"] == []
    assert payload["messages"][0]["content"]["content_type"] == "multimodal_text"
    assert payload["messages"][0]["content"]["parts"][0]["content_type"] == "image_asset_pointer"
    assert payload["messages"][0]["content"]["parts"][0]["asset_pointer"] == "sediment://file_ref_1"
    assert payload["messages"][0]["metadata"]["attachments"][0]["id"] == "file_ref_1"
    assert payload["messages"][0]["metadata"]["developer_mode_connector_ids"] == []
    assert payload["messages"][0]["metadata"]["selected_sources"] == []
    assert "recipient" not in payload["messages"][0]
    UUID(payload["parent_message_id"])
    assert headers["x-conduit-token"] == "conduit_123"
    assert headers["Accept"] == "text/event-stream"
    assert headers["Origin"] == "https://chatgpt.com"
    assert headers["Referer"] == "https://chatgpt.com"
    assert headers["OAI-Device-Id"] == "device-cookie"
    assert headers["OAI-Session-Id"] == prepare_headers["OAI-Session-Id"]
    assert headers["Cookie"] == "oai-did=device-cookie; cf_clearance=cf-cookie"
    assert "X-Test" not in headers
    assert result.conversation_id == "conv_1"
    assert result.assistant_message_id == "msg_asst_1"
    assert result.images[0].file_id == "file_generated_1"
    assert result.images[0].original_gen_id == "gen_1"
    assert result.images[0].revised_prompt == "Bright white door"


@pytest.mark.asyncio
async def test_client_sends_transformation_metadata_for_edit_followups(monkeypatch):
    fake_session = FakeSession(
        [
            FakeResponse(json_body={}, headers={"x-conduit-token": "conduit_456"}),
            FakeResponse(json_body={"conversation_id": "conv_1", "message_id": "msg_pending_2"}),
            FakeResponse(
                json_body={
                    "status": "finished_successfully",
                    "conversation_id": "conv_1",
                    "message_id": "msg_asst_2",
                    "messages": [
                        {
                            "id": "msg_asst_2",
                            "content": {
                                "parts": [
                                    {
                                        "content_type": "image_asset_pointer",
                                        "asset_pointer": "sediment://file_generated_2",
                                        "metadata": {"dalle": {"gen_id": "gen_2"}},
                                    }
                                ]
                            },
                        }
                    ],
                }
            ),
            FakeResponse(body=b"edited-image", headers={"Content-Type": "image/png"}),
        ]
    )
    monkeypatch.setattr(
        chatgpt_images_module,
        "get_http_client",
        lambda: SimpleNamespace(session=fake_session),
    )

    client = ChatGPTImagesClient()
    await client.run_conversation(
        account=_make_account(),
        access_token="access",
        request=ChatGPTImageConversationRequest(
            model="gpt-5.3",
            prompt="Swap the dark door for a bright white one",
            conversation_id="conv_1",
            parent_message_id="msg_asst_1",
            timezone_offset_min=-180,
            timezone="Europe/Moscow",
            client_context={"app_name": "chatgpt.com", "page_width": 1512},
            attachments=(),
            edit_target=ChatGPTImageEditTarget(file_id="file_generated_1", original_gen_id="gen_1"),
        ),
        headers={"X-Test": "1"},
        proxy_url=None,
        cookies={"oai-did": "device-cookie-edit"},
    )

    conversation_call = next(
        call
        for call in fake_session.calls
        if call["method"] == "POST" and str(call["url"]).endswith("/f/conversation")
    )
    payload = conversation_call["json"]
    headers = conversation_call["headers"]
    assert payload["conversation_id"] == "conv_1"
    assert payload["parent_message_id"] == "msg_asst_1"
    assert "recipient" not in payload["messages"][0]
    assert payload["messages"][0]["metadata"]["dalle"]["from_client"]["operation"] == {
        "type": "transformation",
        "original_gen_id": "gen_1",
        "original_file_id": "file_generated_1",
    }
    assert headers["x-conduit-token"] == "conduit_456"
    assert headers["Referer"] == "https://chatgpt.com/c/conv_1"
    assert headers["OAI-Device-Id"] == "device-cookie-edit"
