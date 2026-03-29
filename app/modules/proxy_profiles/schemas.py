from __future__ import annotations

from datetime import datetime

from pydantic import Field

from app.modules.shared.schemas import DashboardModel


class ProxyProfileResponse(DashboardModel):
    id: str
    name: str
    protocol: str = Field(pattern=r"^vless$")
    transport_kind: str = Field(pattern=r"^(reality_tcp|ws_tls|tls_tcp)$")
    server_host: str
    server_port: int
    local_proxy_port: int


class ProxyProfilesResponse(DashboardModel):
    profiles: list[ProxyProfileResponse] = Field(default_factory=list)


class ProxyProfileStatusResponse(DashboardModel):
    profile_id: str
    status: str = Field(pattern=r"^(ok|error)$")
    egress_ip: str | None = None
    last_error: str | None = None
    checked_at: datetime
    latency_ms: int | None = None


class ProxyProfileStatusesResponse(DashboardModel):
    statuses: list[ProxyProfileStatusResponse] = Field(default_factory=list)


class ProxyProfileCreateRequest(DashboardModel):
    name: str = Field(min_length=1, max_length=120)
    vless_uri: str = Field(min_length=1)


class ProxyProfileUpdateRequest(DashboardModel):
    name: str = Field(min_length=1, max_length=120)
    vless_uri: str | None = Field(default=None, min_length=1)


class AccountConnectionUpdateRequest(DashboardModel):
    mode: str = Field(pattern=r"^(inherit_default|direct|proxy_profile)$")
    proxy_profile_id: str | None = None


class AccountConnectionResponse(DashboardModel):
    account_id: str
    mode: str = Field(pattern=r"^(inherit_default|direct|proxy_profile)$")
    proxy_profile_id: str | None = None
