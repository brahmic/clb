from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.modules.proxy_profiles import runtime as runtime_module
from app.modules.proxy_profiles.runtime import (
    ProxyProfileResolutionError,
    ProxyProfileValidationError,
    build_xray_config,
    encrypt_vless_uri,
    parse_vless_uri,
    resolve_account_proxy_connection,
)

pytestmark = pytest.mark.unit

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


def _profile(
    profile_id: str,
    *,
    name: str,
    transport_kind: str,
    server_host: str,
    server_port: int,
    local_proxy_port: int,
    uri: str,
):
    return SimpleNamespace(
        id=profile_id,
        name=name,
        protocol="vless",
        transport_kind=transport_kind,
        server_host=server_host,
        server_port=server_port,
        local_proxy_port=local_proxy_port,
        uri_encrypted=encrypt_vless_uri(uri),
    )


def test_parse_vless_uri_supports_reality_tcp():
    parsed = parse_vless_uri(REALITY_URI)

    assert parsed.transport_kind == "reality_tcp"
    assert parsed.server_host == "reality.example.com"
    assert parsed.server_port == 443


def test_parse_vless_uri_supports_ws_tls():
    parsed = parse_vless_uri(WS_TLS_URI)

    assert parsed.transport_kind == "ws_tls"
    assert parsed.server_host == "ws.example.com"
    assert parsed.server_port == 8443


def test_parse_vless_uri_supports_tls_tcp():
    parsed = parse_vless_uri(TLS_TCP_URI)

    assert parsed.transport_kind == "tls_tcp"
    assert parsed.server_host == "tls.example.com"
    assert parsed.server_port == 11380


def test_parse_vless_uri_rejects_unsupported_variant():
    with pytest.raises(ProxyProfileValidationError):
        parse_vless_uri(
            "vless://33333333-3333-3333-3333-333333333333@grpc.example.com:443"
            "?type=grpc&security=tls&sni=grpc.example.com#Unsupported"
        )


def test_build_xray_config_uses_stable_local_ports():
    profile_a = _profile(
        "profile-a",
        name="Profile A",
        transport_kind="reality_tcp",
        server_host="reality.example.com",
        server_port=443,
        local_proxy_port=20080,
        uri=REALITY_URI,
    )
    profile_b = _profile(
        "profile-b",
        name="Profile B",
        transport_kind="ws_tls",
        server_host="ws.example.com",
        server_port=8443,
        local_proxy_port=20081,
        uri=WS_TLS_URI,
    )
    profile_c = _profile(
        "profile-c",
        name="Profile C",
        transport_kind="tls_tcp",
        server_host="tls.example.com",
        server_port=11380,
        local_proxy_port=20082,
        uri=TLS_TCP_URI,
    )

    config = build_xray_config([profile_a, profile_b, profile_c])

    assert [entry["port"] for entry in config["inbounds"]] == [20080, 20081, 20082]
    assert [entry["tag"] for entry in config["outbounds"]] == [
        "direct",
        "profile-profile-a",
        "profile-profile-b",
        "profile-profile-c",
    ]
    assert config["routing"]["rules"] == [
        {"type": "field", "inboundTag": ["inbound-profile-a"], "outboundTag": "profile-profile-a"},
        {"type": "field", "inboundTag": ["inbound-profile-b"], "outboundTag": "profile-profile-b"},
        {"type": "field", "inboundTag": ["inbound-profile-c"], "outboundTag": "profile-profile-c"},
    ]
    tls_tcp_outbound = next(entry for entry in config["outbounds"] if entry["tag"] == "profile-profile-c")
    assert tls_tcp_outbound["settings"]["vnext"][0]["users"][0]["flow"] == "xtls-rprx-vision"
    assert tls_tcp_outbound["streamSettings"]["network"] == "tcp"
    assert tls_tcp_outbound["streamSettings"]["security"] == "tls"
    assert tls_tcp_outbound["streamSettings"]["tlsSettings"]["serverName"] == "tls.example.com"
    assert tls_tcp_outbound["streamSettings"]["tlsSettings"]["fingerprint"] == "chrome"
    assert tls_tcp_outbound["streamSettings"]["tlsSettings"]["alpn"] == ["h2", "http/1.1", "h3"]
    serialized = json.dumps(config)
    assert '"protocol": "http"' in serialized
    assert '"protocol": "vless"' in serialized


@pytest.mark.asyncio
async def test_resolve_account_proxy_connection_prefers_assigned_profile():
    assigned_profile = _profile(
        "profile-1",
        name="Assigned",
        transport_kind="reality_tcp",
        server_host="reality.example.com",
        server_port=443,
        local_proxy_port=20080,
        uri=REALITY_URI,
    )
    account = SimpleNamespace(proxy_assignment_mode="proxy_profile", proxy_profile_id="profile-1")

    async def _resolve_profile(profile_id: str):
        return assigned_profile if profile_id == "profile-1" else None

    connection = await resolve_account_proxy_connection(account, _resolve_profile)

    assert connection.mode == "proxy_profile"
    assert connection.profile_id == "profile-1"
    assert connection.local_proxy_port == 20080
    assert connection.proxy_url == "http://xray-client:20080"


@pytest.mark.asyncio
async def test_resolve_account_proxy_connection_inherits_direct_without_default(monkeypatch):
    account = SimpleNamespace(proxy_assignment_mode="inherit_default", proxy_profile_id=None)

    class _SettingsCache:
        async def get(self):
            return SimpleNamespace(default_proxy_profile_id=None)

    monkeypatch.setattr(runtime_module, "get_settings_cache", lambda: _SettingsCache())

    async def _resolve_profile(_: str):
        raise AssertionError("default profile lookup should not happen")

    connection = await resolve_account_proxy_connection(account, _resolve_profile)

    assert connection.mode == "inherit_default"
    assert connection.profile_id is None
    assert connection.proxy_url is None


@pytest.mark.asyncio
async def test_resolve_account_proxy_connection_fails_closed_when_default_profile_missing(monkeypatch):
    account = SimpleNamespace(proxy_assignment_mode="inherit_default", proxy_profile_id=None)

    class _SettingsCache:
        async def get(self):
            return SimpleNamespace(default_proxy_profile_id="missing-profile")

    monkeypatch.setattr(runtime_module, "get_settings_cache", lambda: _SettingsCache())

    async def _resolve_profile(_: str):
        return None

    with pytest.raises(ProxyProfileResolutionError):
        await resolve_account_proxy_connection(account, _resolve_profile)
