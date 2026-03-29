from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from datetime import datetime
from uuid import uuid4

import aiohttp

from app.core.clients.http import get_http_client
from app.core.config.settings import get_settings
from app.core.utils.time import utcnow
from app.db.models import ProxyProfile
from app.modules.proxy_profiles.repository import ProxyProfilesRepository
from app.modules.proxy_profiles.runtime import (
    allocate_proxy_port,
    encrypt_vless_uri,
    parse_vless_uri,
    sync_xray_sidecar_config,
)


class ProxyProfileNameConflictError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ProxyProfileData:
    id: str
    name: str
    protocol: str
    transport_kind: str
    server_host: str
    server_port: int
    local_proxy_port: int


@dataclass(frozen=True, slots=True)
class ProxyProfileStatusData:
    profile_id: str
    status: str
    egress_ip: str | None
    last_error: str | None
    checked_at: datetime
    latency_ms: int | None


class ProxyProfilesService:
    def __init__(
        self,
        repository: ProxyProfilesRepository,
    ) -> None:
        self._repository = repository

    async def list_profiles(self) -> list[ProxyProfileData]:
        return [_to_data(profile) for profile in await self._repository.list_profiles()]

    async def create_profile(self, *, name: str, vless_uri: str) -> ProxyProfileData:
        normalized_name = name.strip()
        existing = await self._repository.get_by_name(normalized_name)
        if existing is not None:
            raise ProxyProfileNameConflictError("Proxy profile name must be unique")
        parsed = parse_vless_uri(vless_uri)
        used_ports = await self._repository.list_used_ports()
        profile = ProxyProfile(
            id=uuid4().hex,
            name=normalized_name,
            protocol="vless",
            transport_kind=parsed.transport_kind,
            server_host=parsed.server_host,
            server_port=parsed.server_port,
            local_proxy_port=allocate_proxy_port(used_ports),
            uri_encrypted=encrypt_vless_uri(vless_uri),
        )
        saved = await self._repository.create(profile)
        await self.sync_runtime()
        return _to_data(saved)

    async def update_profile(self, profile_id: str, *, name: str, vless_uri: str | None) -> ProxyProfileData | None:
        profile = await self._repository.get_by_id(profile_id)
        if profile is None:
            return None
        normalized_name = name.strip()
        existing = await self._repository.get_by_name(normalized_name)
        if existing is not None and existing.id != profile_id:
            raise ProxyProfileNameConflictError("Proxy profile name must be unique")
        profile.name = normalized_name
        if vless_uri is not None:
            parsed = parse_vless_uri(vless_uri)
            profile.transport_kind = parsed.transport_kind
            profile.server_host = parsed.server_host
            profile.server_port = parsed.server_port
            profile.uri_encrypted = encrypt_vless_uri(vless_uri)
        saved = await self._repository.save(profile)
        await self.sync_runtime()
        return _to_data(saved)

    async def delete_profile(self, profile_id: str) -> bool:
        await self._repository.clear_default_profile(profile_id)
        await self._repository.reset_account_assignments(profile_id)
        deleted = await self._repository.delete(profile_id)
        if deleted:
            await self.sync_runtime()
        return deleted

    async def sync_runtime(self) -> None:
        sync_xray_sidecar_config(await self._repository.list_profiles())

    async def list_profile_statuses(self) -> list[ProxyProfileStatusData]:
        profiles = await self._repository.list_profiles()
        if not profiles:
            return []
        return list(await asyncio.gather(*(probe_proxy_profile(profile) for profile in profiles)))


def _to_data(profile: ProxyProfile) -> ProxyProfileData:
    return ProxyProfileData(
        id=profile.id,
        name=profile.name,
        protocol=profile.protocol,
        transport_kind=profile.transport_kind,
        server_host=profile.server_host,
        server_port=profile.server_port,
        local_proxy_port=profile.local_proxy_port,
    )


async def probe_proxy_profile(profile: ProxyProfile) -> ProxyProfileStatusData:
    started = time.monotonic()
    checked_at = utcnow()
    proxy_url = f"http://{get_settings().xray_sidecar_host}:{profile.local_proxy_port}"
    timeout = aiohttp.ClientTimeout(total=5.0)
    try:
        async with get_http_client().session.get(
            "https://api.ipify.org?format=json",
            timeout=timeout,
            proxy=proxy_url,
            headers={"Accept": "application/json"},
        ) as response:
            latency_ms = int((time.monotonic() - started) * 1000)
            if response.status >= 400:
                message = (await response.text()).strip() or f"Probe failed ({response.status})"
                return ProxyProfileStatusData(
                    profile_id=profile.id,
                    status="error",
                    egress_ip=None,
                    last_error=message,
                    checked_at=checked_at,
                    latency_ms=latency_ms,
                )
            payload = await response.json(content_type=None)
            ip_value = payload.get("ip") if isinstance(payload, dict) else None
            if not isinstance(ip_value, str) or not ip_value.strip():
                return ProxyProfileStatusData(
                    profile_id=profile.id,
                    status="error",
                    egress_ip=None,
                    last_error="Probe returned an invalid IP payload",
                    checked_at=checked_at,
                    latency_ms=latency_ms,
                )
            return ProxyProfileStatusData(
                profile_id=profile.id,
                status="ok",
                egress_ip=ip_value.strip(),
                last_error=None,
                checked_at=checked_at,
                latency_ms=latency_ms,
            )
    except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
        return ProxyProfileStatusData(
            profile_id=profile.id,
            status="error",
            egress_ip=None,
            last_error=str(exc) or exc.__class__.__name__,
            checked_at=checked_at,
            latency_ms=int((time.monotonic() - started) * 1000),
        )
