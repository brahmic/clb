from __future__ import annotations

import base64
import json
from datetime import datetime, timezone

import pytest

from app.core.config.settings import get_settings
from app.modules.proxy_profiles import service as proxy_profiles_service_module

pytestmark = pytest.mark.integration

REALITY_URI = (
    "vless://11111111-1111-1111-1111-111111111111@reality.example.com:443"
    "?type=tcp&security=reality&sni=cdn.example.com&pbk=PUBLICKEY123&sid=abcd&fp=chrome#Reality"
)
WS_TLS_URI = (
    "vless://22222222-2222-2222-2222-222222222222@ws.example.com:8443"
    "?type=ws&security=tls&sni=ws.example.com&host=cdn.example.com&path=%2Fsocket#Websocket"
)
TLS_TCP_URI = (
    "vless://33333333-3333-3333-3333-333333333333@tls.example.com:11380"
    "?type=tcp&encryption=none&security=tls&fp=chrome&alpn=h2%2Chttp%2F1.1%2Ch3"
    "&sni=tls.example.com&flow=xtls-rprx-vision#Vision"
)


def _encode_jwt(payload: dict) -> str:
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    body = base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")
    return f"header.{body}.sig"


async def _import_account(async_client, *, email: str = "proxy-user@example.com", raw_account_id: str = "acc_proxy") -> str:
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
    response = await async_client.post(
        "/api/accounts/import",
        files={"auth_json": ("auth.json", json.dumps(auth_json), "application/json")},
    )
    assert response.status_code == 200
    return response.json()["accountId"]


@pytest.fixture(autouse=True)
def _xray_runtime_paths(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEX_LB_XRAY_CONFIG_PATH", str(tmp_path / "xray" / "config.json"))
    monkeypatch.setenv("CODEX_LB_XRAY_RELOAD_MARKER_PATH", str(tmp_path / "xray" / "reload.marker"))
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_proxy_profiles_crud_updates_runtime_config_and_default_setting(async_client):
    created = await async_client.post(
        "/api/proxy-profiles",
        json={"name": "Primary", "vlessUri": REALITY_URI},
    )
    assert created.status_code == 200
    profile = created.json()
    assert profile["name"] == "Primary"
    assert profile["protocol"] == "vless"
    assert profile["transportKind"] == "reality_tcp"
    assert profile["serverHost"] == "reality.example.com"
    assert profile["serverPort"] == 443
    assert "vlessUri" not in profile

    updated = await async_client.put(
        f"/api/proxy-profiles/{profile['id']}",
        json={"name": "Secondary", "vlessUri": WS_TLS_URI},
    )
    assert updated.status_code == 200
    updated_profile = updated.json()
    assert updated_profile["name"] == "Secondary"
    assert updated_profile["transportKind"] == "ws_tls"
    assert updated_profile["serverHost"] == "ws.example.com"
    assert updated_profile["serverPort"] == 8443

    listed = await async_client.get("/api/proxy-profiles")
    assert listed.status_code == 200
    assert listed.json()["profiles"] == [updated_profile]

    settings_update = await async_client.put(
        "/api/settings",
        json={
            "stickyThreadsEnabled": False,
            "preferEarlierResetAccounts": False,
            "defaultProxyProfileId": profile["id"],
        },
    )
    assert settings_update.status_code == 200
    assert settings_update.json()["defaultProxyProfileId"] == profile["id"]

    settings_response = await async_client.get("/api/settings")
    assert settings_response.status_code == 200
    assert settings_response.json()["defaultProxyProfileId"] == profile["id"]

    config_path = get_settings().xray_config_path
    assert config_path.exists() is True
    config_payload = json.loads(config_path.read_text(encoding="utf-8"))
    assert [entry["port"] for entry in config_payload["inbounds"]] == [updated_profile["localProxyPort"]]
    assert config_payload["routing"]["rules"][0]["outboundTag"] == f"profile-{profile['id']}"


@pytest.mark.asyncio
async def test_proxy_profile_delete_clears_default_and_resets_account_assignment(async_client):
    created = await async_client.post(
        "/api/proxy-profiles",
        json={"name": "Assigned", "vlessUri": REALITY_URI},
    )
    assert created.status_code == 200
    profile = created.json()

    settings_update = await async_client.put(
        "/api/settings",
        json={
            "stickyThreadsEnabled": False,
            "preferEarlierResetAccounts": False,
            "defaultProxyProfileId": profile["id"],
        },
    )
    assert settings_update.status_code == 200

    account_id = await _import_account(async_client)
    assignment = await async_client.put(
        f"/api/accounts/{account_id}/connection",
        json={"mode": "proxy_profile", "proxyProfileId": profile["id"]},
    )
    assert assignment.status_code == 200
    assert assignment.json()["mode"] == "proxy_profile"

    deleted = await async_client.delete(f"/api/proxy-profiles/{profile['id']}")
    assert deleted.status_code == 200
    assert deleted.json()["id"] == profile["id"]

    settings_response = await async_client.get("/api/settings")
    assert settings_response.status_code == 200
    assert settings_response.json()["defaultProxyProfileId"] is None

    accounts_response = await async_client.get("/api/accounts")
    assert accounts_response.status_code == 200
    account = next(item for item in accounts_response.json()["accounts"] if item["accountId"] == account_id)
    assert account["proxyAssignmentMode"] == "inherit_default"
    assert account["proxyProfileId"] is None

    profiles_response = await async_client.get("/api/proxy-profiles")
    assert profiles_response.status_code == 200
    assert profiles_response.json()["profiles"] == []


@pytest.mark.asyncio
async def test_proxy_profiles_reject_invalid_uri(async_client):
    response = await async_client.post(
        "/api/proxy-profiles",
        json={"name": "Broken", "vlessUri": "vless://id@example.com:443?type=grpc&security=tls"},
    )
    assert response.status_code == 400
    payload = response.json()
    assert payload["error"]["code"] == "invalid_proxy_profile"


@pytest.mark.asyncio
async def test_proxy_profiles_accept_tls_tcp_vision_uri(async_client):
    created = await async_client.post(
        "/api/proxy-profiles",
        json={"name": "Vision", "vlessUri": TLS_TCP_URI},
    )
    assert created.status_code == 200
    profile = created.json()
    assert profile["transportKind"] == "tls_tcp"
    assert profile["serverHost"] == "tls.example.com"
    assert profile["serverPort"] == 11380

    config_path = get_settings().xray_config_path
    config_payload = json.loads(config_path.read_text(encoding="utf-8"))
    outbound = next(entry for entry in config_payload["outbounds"] if entry["tag"] == f"profile-{profile['id']}")
    assert outbound["settings"]["vnext"][0]["users"][0]["flow"] == "xtls-rprx-vision"
    assert outbound["streamSettings"]["network"] == "tcp"
    assert outbound["streamSettings"]["security"] == "tls"
    assert outbound["streamSettings"]["tlsSettings"]["serverName"] == "tls.example.com"
    assert outbound["streamSettings"]["tlsSettings"]["fingerprint"] == "chrome"
    assert outbound["streamSettings"]["tlsSettings"]["alpn"] == ["h2", "http/1.1", "h3"]


@pytest.mark.asyncio
async def test_account_connection_endpoint_validates_mode_and_profile(async_client):
    account_id = await _import_account(async_client, email="validate@example.com", raw_account_id="acc_validate")

    missing_profile = await async_client.put(
        f"/api/accounts/{account_id}/connection",
        json={"mode": "proxy_profile"},
    )
    assert missing_profile.status_code == 400
    assert missing_profile.json()["error"]["code"] == "invalid_proxy_mode"

    invalid_direct = await async_client.put(
        f"/api/accounts/{account_id}/connection",
        json={"mode": "direct", "proxyProfileId": "profile-1"},
    )
    assert invalid_direct.status_code == 400
    assert invalid_direct.json()["error"]["code"] == "invalid_proxy_mode"

    not_found = await async_client.put(
        f"/api/accounts/{account_id}/connection",
        json={"mode": "proxy_profile", "proxyProfileId": "missing-profile"},
    )
    assert not_found.status_code == 400
    assert not_found.json()["error"]["code"] == "proxy_profile_not_found"

    created = await async_client.post(
        "/api/proxy-profiles",
        json={"name": "Specific", "vlessUri": REALITY_URI},
    )
    assert created.status_code == 200
    profile_id = created.json()["id"]

    assigned = await async_client.put(
        f"/api/accounts/{account_id}/connection",
        json={"mode": "proxy_profile", "proxyProfileId": profile_id},
    )
    assert assigned.status_code == 200
    assert assigned.json() == {
        "accountId": account_id,
        "mode": "proxy_profile",
        "proxyProfileId": profile_id,
    }


@pytest.mark.asyncio
async def test_proxy_profile_statuses_return_probe_results(async_client, monkeypatch):
    created = await async_client.post(
        "/api/proxy-profiles",
        json={"name": "Observed", "vlessUri": REALITY_URI},
    )
    assert created.status_code == 200
    profile = created.json()

    async def _fake_probe(profile_row):
        return proxy_profiles_service_module.ProxyProfileStatusData(
            profile_id=profile_row.id,
            status="ok",
            egress_ip="203.0.113.77",
            last_error=None,
            checked_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            latency_ms=95,
        )

    monkeypatch.setattr(proxy_profiles_service_module, "probe_proxy_profile", _fake_probe)

    response = await async_client.get("/api/proxy-profiles/statuses")
    assert response.status_code == 200
    assert response.json() == {
        "statuses": [
            {
                "profileId": profile["id"],
                "status": "ok",
                "egressIp": "203.0.113.77",
                "lastError": None,
                "checkedAt": "2026-01-01T00:00:00Z",
                "latencyMs": 95,
            }
        ]
    }
