from __future__ import annotations

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi import Body

from app.core.auth.dependencies import set_dashboard_error_format, validate_dashboard_session
from app.core.exceptions import DashboardBadRequestError, DashboardConflictError, DashboardNotFoundError
from app.dependencies import AccountsContext, get_accounts_context
from app.modules.accounts.repository import AccountIdentityConflictError
from app.modules.accounts.schemas import (
    AccountConnectionResponse,
    AccountDeleteResponse,
    AccountImportResponse,
    AccountPauseResponse,
    AccountReactivateResponse,
    AccountsResponse,
    AccountTrendsResponse,
)
from app.modules.proxy_profiles.schemas import AccountConnectionUpdateRequest
from app.modules.proxy_profiles.repository import ProxyProfilesRepository
from app.modules.accounts.service import InvalidAuthJsonError

router = APIRouter(
    prefix="/api/accounts",
    tags=["dashboard"],
    dependencies=[Depends(validate_dashboard_session), Depends(set_dashboard_error_format)],
)


@router.get("", response_model=AccountsResponse)
async def list_accounts(
    context: AccountsContext = Depends(get_accounts_context),
) -> AccountsResponse:
    accounts = await context.service.list_accounts()
    return AccountsResponse(accounts=accounts)


@router.get("/{account_id}/trends", response_model=AccountTrendsResponse)
async def get_account_trends(
    account_id: str,
    context: AccountsContext = Depends(get_accounts_context),
) -> AccountTrendsResponse:
    result = await context.service.get_account_trends(account_id)
    if not result:
        raise DashboardNotFoundError("Account not found", code="account_not_found")
    return result


@router.post("/import", response_model=AccountImportResponse)
async def import_account(
    auth_json: UploadFile = File(...),
    context: AccountsContext = Depends(get_accounts_context),
) -> AccountImportResponse:
    raw = await auth_json.read()
    try:
        return await context.service.import_account(raw)
    except InvalidAuthJsonError as exc:
        raise DashboardBadRequestError("Invalid auth.json payload", code="invalid_auth_json") from exc
    except AccountIdentityConflictError as exc:
        raise DashboardConflictError(str(exc), code="duplicate_identity_conflict") from exc


@router.post("/{account_id}/reactivate", response_model=AccountReactivateResponse)
async def reactivate_account(
    account_id: str,
    context: AccountsContext = Depends(get_accounts_context),
) -> AccountReactivateResponse:
    success = await context.service.reactivate_account(account_id)
    if not success:
        raise DashboardNotFoundError("Account not found", code="account_not_found")
    return AccountReactivateResponse(status="reactivated")


@router.post("/{account_id}/pause", response_model=AccountPauseResponse)
async def pause_account(
    account_id: str,
    context: AccountsContext = Depends(get_accounts_context),
) -> AccountPauseResponse:
    success = await context.service.pause_account(account_id)
    if not success:
        raise DashboardNotFoundError("Account not found", code="account_not_found")
    return AccountPauseResponse(status="paused")


@router.delete("/{account_id}", response_model=AccountDeleteResponse)
async def delete_account(
    account_id: str,
    context: AccountsContext = Depends(get_accounts_context),
) -> AccountDeleteResponse:
    success = await context.service.delete_account(account_id)
    if not success:
        raise DashboardNotFoundError("Account not found", code="account_not_found")
    return AccountDeleteResponse(status="deleted")


@router.put("/{account_id}/connection", response_model=AccountConnectionResponse)
async def update_account_connection(
    account_id: str,
    payload: AccountConnectionUpdateRequest = Body(...),
    context: AccountsContext = Depends(get_accounts_context),
) -> AccountConnectionResponse:
    if payload.mode == "proxy_profile":
        if not payload.proxy_profile_id:
            raise DashboardBadRequestError("proxyProfileId is required for proxy_profile mode", code="invalid_proxy_mode")
        profile = await ProxyProfilesRepository(context.session).get_by_id(payload.proxy_profile_id)
        if profile is None:
            raise DashboardBadRequestError("Proxy profile not found", code="proxy_profile_not_found")
    elif payload.proxy_profile_id is not None:
        raise DashboardBadRequestError(
            "proxyProfileId is only allowed for proxy_profile mode",
            code="invalid_proxy_mode",
        )
    updated = await context.service.update_connection(
        account_id,
        mode=payload.mode,
        proxy_profile_id=payload.proxy_profile_id,
    )
    if not updated:
        raise DashboardNotFoundError("Account not found", code="account_not_found")
    return updated
