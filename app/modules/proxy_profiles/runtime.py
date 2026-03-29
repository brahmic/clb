from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from urllib.parse import parse_qs, unquote, urlparse
from uuid import uuid4

from app.core.config.settings import get_settings
from app.core.config.settings_cache import get_settings_cache
from app.core.crypto import TokenEncryptor
from app.db.session import get_background_session
from app.db.models import Account, ProxyProfile

logger = logging.getLogger(__name__)

XRAY_LOCAL_PORT_MIN = 20080
XRAY_LOCAL_PORT_MAX = 20979


class ProxyProfileValidationError(ValueError):
    pass


class ProxyProfileResolutionError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ParsedVlessProfile:
    transport_kind: str
    server_host: str
    server_port: int


@dataclass(frozen=True, slots=True)
class ResolvedProxyConnection:
    mode: str
    profile_id: str | None = None
    profile_name: str | None = None
    local_proxy_port: int | None = None

    @property
    def proxy_url(self) -> str | None:
        if self.local_proxy_port is None:
            return None
        return f"http://{get_settings().xray_sidecar_host}:{self.local_proxy_port}"


def parse_vless_uri(uri: str) -> ParsedVlessProfile:
    parsed = urlparse(uri.strip())
    if parsed.scheme.lower() != "vless":
        raise ProxyProfileValidationError("Only vless:// URIs are supported")
    if not parsed.username:
        raise ProxyProfileValidationError("VLESS URI must include a user id")
    if not parsed.hostname or parsed.port is None:
        raise ProxyProfileValidationError("VLESS URI must include server host and port")
    query = {key: values[-1] for key, values in parse_qs(parsed.query, keep_blank_values=True).items()}
    network = (query.get("type") or "tcp").lower()
    security = (query.get("security") or "").lower()
    if security == "reality" and network == "tcp":
        if not query.get("pbk"):
            raise ProxyProfileValidationError("Reality VLESS requires pbk")
        if not query.get("sni"):
            raise ProxyProfileValidationError("Reality VLESS requires sni")
        return ParsedVlessProfile(
            transport_kind="reality_tcp",
            server_host=parsed.hostname,
            server_port=parsed.port,
        )
    if security == "tls" and network == "ws":
        if not query.get("sni"):
            raise ProxyProfileValidationError("WS/TLS VLESS requires sni")
        return ParsedVlessProfile(
            transport_kind="ws_tls",
            server_host=parsed.hostname,
            server_port=parsed.port,
        )
    if security == "tls" and network == "tcp":
        if not query.get("sni"):
            raise ProxyProfileValidationError("TCP/TLS VLESS requires sni")
        return ParsedVlessProfile(
            transport_kind="tls_tcp",
            server_host=parsed.hostname,
            server_port=parsed.port,
        )
    raise ProxyProfileValidationError("Supported VLESS modes are Reality/TCP, WS/TLS, and TCP/TLS only")


def encrypt_vless_uri(uri: str) -> bytes:
    return TokenEncryptor().encrypt(uri.strip())


def decrypt_vless_uri(encrypted: bytes) -> str:
    return TokenEncryptor().decrypt(encrypted)


def allocate_proxy_port(used_ports: Iterable[int]) -> int:
    reserved = set(used_ports)
    for port in range(XRAY_LOCAL_PORT_MIN, XRAY_LOCAL_PORT_MAX + 1):
        if port not in reserved:
            return port
    raise ProxyProfileValidationError("No free local proxy ports available")


def build_xray_config(profiles: list[ProxyProfile]) -> dict[str, object]:
    inbounds: list[dict[str, object]] = []
    outbounds: list[dict[str, object]] = [{"tag": "direct", "protocol": "freedom"}]
    rules: list[dict[str, object]] = []
    for profile in profiles:
        profile_uri = decrypt_vless_uri(profile.uri_encrypted)
        outbound_tag = f"profile-{profile.id}"
        inbound_tag = f"inbound-{profile.id}"
        inbounds.append(
            {
                "tag": inbound_tag,
                "listen": "0.0.0.0",
                "port": profile.local_proxy_port,
                "protocol": "http",
                "settings": {"allowTransparent": False},
            }
        )
        outbounds.append(_build_vless_outbound(profile, profile_uri, outbound_tag))
        rules.append({"type": "field", "inboundTag": [inbound_tag], "outboundTag": outbound_tag})
    return {
        "log": {"loglevel": "info"},
        "inbounds": inbounds,
        "outbounds": outbounds,
        "routing": {"domainStrategy": "AsIs", "rules": rules},
    }


def _build_vless_outbound(profile: ProxyProfile, uri: str, outbound_tag: str) -> dict[str, object]:
    parsed = urlparse(uri.strip())
    query = {key: values[-1] for key, values in parse_qs(parsed.query, keep_blank_values=True).items()}
    user: dict[str, object] = {"id": parsed.username, "encryption": "none"}
    flow = query.get("flow")
    if flow:
        user["flow"] = flow
    stream_settings: dict[str, object]
    if profile.transport_kind == "reality_tcp":
        stream_settings = {
            "network": "tcp",
            "security": "reality",
            "realitySettings": {
                "serverName": query["sni"],
                "fingerprint": query.get("fp") or "chrome",
                "publicKey": query["pbk"],
                "shortId": query.get("sid", ""),
                "spiderX": unquote(query.get("spx", "/") or "/"),
            },
        }
    elif profile.transport_kind == "tls_tcp":
        tls_settings: dict[str, object] = {
            "serverName": query["sni"],
            "allowInsecure": False,
        }
        if query.get("fp"):
            tls_settings["fingerprint"] = query["fp"]
        if query.get("alpn"):
            tls_settings["alpn"] = [entry for entry in query["alpn"].split(",") if entry]
        stream_settings = {
            "network": "tcp",
            "security": "tls",
            "tlsSettings": tls_settings,
        }
    else:
        headers: dict[str, str] = {}
        host_header = query.get("host")
        if host_header:
            headers["Host"] = host_header
        tls_settings: dict[str, object] = {"serverName": query["sni"], "allowInsecure": False}
        if query.get("alpn"):
            tls_settings["alpn"] = [entry for entry in query["alpn"].split(",") if entry]
        stream_settings = {
            "network": "ws",
            "security": "tls",
            "tlsSettings": tls_settings,
            "wsSettings": {
                "path": unquote(query.get("path", "/") or "/"),
                "headers": headers,
            },
        }
    return {
        "tag": outbound_tag,
        "protocol": "vless",
        "settings": {
            "vnext": [
                {
                    "address": profile.server_host,
                    "port": profile.server_port,
                    "users": [user],
                }
            ]
        },
        "streamSettings": stream_settings,
    }


def sync_xray_sidecar_config(profiles: list[ProxyProfile]) -> None:
    settings = get_settings()
    config_path = settings.xray_config_path
    config_path.parent.mkdir(parents=True, exist_ok=True)
    payload = build_xray_config(profiles)
    temp_path = config_path.with_name(f"{config_path.name}.{uuid4().hex}.tmp")
    temp_path.write_text(json.dumps(payload, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    temp_path.replace(config_path)
    _touch(settings.xray_reload_marker_path)


def _touch(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()


async def resolve_account_proxy_connection(
    account: Account,
    resolve_profile_by_id,
) -> ResolvedProxyConnection:
    if account.proxy_assignment_mode == "direct":
        return ResolvedProxyConnection(mode="direct")
    if account.proxy_assignment_mode == "proxy_profile":
        if not account.proxy_profile_id:
            raise ProxyProfileResolutionError("Account proxy profile is not configured")
        profile = await resolve_profile_by_id(account.proxy_profile_id)
        if profile is None:
            raise ProxyProfileResolutionError("Assigned proxy profile is missing")
        return ResolvedProxyConnection(
            mode="proxy_profile",
            profile_id=profile.id,
            profile_name=profile.name,
            local_proxy_port=profile.local_proxy_port,
        )
    settings = await get_settings_cache().get()
    if not settings.default_proxy_profile_id:
        return ResolvedProxyConnection(mode="inherit_default")
    profile = await resolve_profile_by_id(settings.default_proxy_profile_id)
    if profile is None:
        logger.warning("Default proxy profile missing profile_id=%s", settings.default_proxy_profile_id)
        raise ProxyProfileResolutionError("Default proxy profile is missing")
    return ResolvedProxyConnection(
        mode="inherit_default",
        profile_id=profile.id,
        profile_name=profile.name,
        local_proxy_port=profile.local_proxy_port,
    )


async def resolve_account_proxy_connection_from_db(account: Account) -> ResolvedProxyConnection:
    from app.modules.proxy_profiles.repository import ProxyProfilesRepository

    async with get_background_session() as session:
        repository = ProxyProfilesRepository(session)
        return await resolve_account_proxy_connection(account, repository.get_by_id)
