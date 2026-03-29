from __future__ import annotations

from fastapi import APIRouter, Body, Depends

from app.core.auth.dependencies import set_dashboard_error_format, validate_dashboard_session
from app.core.config.settings_cache import get_settings_cache
from app.core.exceptions import DashboardBadRequestError, DashboardConflictError, DashboardNotFoundError
from app.dependencies import ProxyProfilesContext, get_proxy_profiles_context
from app.modules.proxy_profiles.runtime import ProxyProfileValidationError
from app.modules.proxy_profiles.service import ProxyProfileNameConflictError
from app.modules.proxy_profiles.schemas import (
    ProxyProfileCreateRequest,
    ProxyProfileResponse,
    ProxyProfileStatusesResponse,
    ProxyProfileStatusResponse,
    ProxyProfilesResponse,
    ProxyProfileUpdateRequest,
)

router = APIRouter(
    prefix="/api/proxy-profiles",
    tags=["dashboard"],
    dependencies=[Depends(validate_dashboard_session), Depends(set_dashboard_error_format)],
)


@router.get("", response_model=ProxyProfilesResponse)
async def list_proxy_profiles(
    context: ProxyProfilesContext = Depends(get_proxy_profiles_context),
) -> ProxyProfilesResponse:
    profiles = [ProxyProfileResponse.model_validate(profile) for profile in await context.service.list_profiles()]
    return ProxyProfilesResponse(profiles=profiles)


@router.get("/statuses", response_model=ProxyProfileStatusesResponse)
async def list_proxy_profile_statuses(
    context: ProxyProfilesContext = Depends(get_proxy_profiles_context),
) -> ProxyProfileStatusesResponse:
    statuses = [ProxyProfileStatusResponse.model_validate(status) for status in await context.service.list_profile_statuses()]
    return ProxyProfileStatusesResponse(statuses=statuses)


@router.post("", response_model=ProxyProfileResponse)
async def create_proxy_profile(
    payload: ProxyProfileCreateRequest = Body(...),
    context: ProxyProfilesContext = Depends(get_proxy_profiles_context),
) -> ProxyProfileResponse:
    try:
        created = await context.service.create_profile(name=payload.name, vless_uri=payload.vless_uri)
    except ProxyProfileValidationError as exc:
        raise DashboardBadRequestError(str(exc), code="invalid_proxy_profile") from exc
    except ProxyProfileNameConflictError as exc:
        raise DashboardConflictError(str(exc), code="duplicate_proxy_profile_name") from exc
    await get_settings_cache().invalidate()
    return ProxyProfileResponse.model_validate(created)


@router.put("/{profile_id}", response_model=ProxyProfileResponse)
async def update_proxy_profile(
    profile_id: str,
    payload: ProxyProfileUpdateRequest = Body(...),
    context: ProxyProfilesContext = Depends(get_proxy_profiles_context),
) -> ProxyProfileResponse:
    try:
        updated = await context.service.update_profile(profile_id, name=payload.name, vless_uri=payload.vless_uri)
    except ProxyProfileValidationError as exc:
        raise DashboardBadRequestError(str(exc), code="invalid_proxy_profile") from exc
    except ProxyProfileNameConflictError as exc:
        raise DashboardConflictError(str(exc), code="duplicate_proxy_profile_name") from exc
    if updated is None:
        raise DashboardNotFoundError("Proxy profile not found", code="proxy_profile_not_found")
    await get_settings_cache().invalidate()
    return ProxyProfileResponse.model_validate(updated)


@router.delete("/{profile_id}", response_model=ProxyProfileResponse)
async def delete_proxy_profile(
    profile_id: str,
    context: ProxyProfilesContext = Depends(get_proxy_profiles_context),
) -> ProxyProfileResponse:
    profile = await context.repository.get_by_id(profile_id)
    if profile is None:
        raise DashboardNotFoundError("Proxy profile not found", code="proxy_profile_not_found")
    response = ProxyProfileResponse(
        id=profile.id,
        name=profile.name,
        protocol=profile.protocol,
        transport_kind=profile.transport_kind,
        server_host=profile.server_host,
        server_port=profile.server_port,
        local_proxy_port=profile.local_proxy_port,
    )
    deleted = await context.service.delete_profile(profile_id)
    if not deleted:
        raise DashboardNotFoundError("Proxy profile not found", code="proxy_profile_not_found")
    await get_settings_cache().invalidate()
    return response
