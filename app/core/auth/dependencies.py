from __future__ import annotations

import logging

from fastapi import Request, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.clients.usage import UsageFetchError, fetch_usage
from app.core.config.settings_cache import get_settings_cache
from app.core.exceptions import DashboardAuthError, ProxyAuthError, ProxyUpstreamError
from app.db.session import get_background_session
from app.modules.accounts.repository import AccountsRepository
from app.modules.api_keys.repository import ApiKeysRepository
from app.modules.api_keys.service import ApiKeyData, ApiKeyInvalidError, ApiKeysService
from app.modules.dashboard_auth.service import DASHBOARD_SESSION_COOKIE, get_dashboard_session_store

logger = logging.getLogger(__name__)

_bearer = HTTPBearer(description="API key (e.g. sk-clb-…)", auto_error=False)


def has_valid_dashboard_session(
    session_id: str | None,
    *,
    password_hash: str | None,
    totp_required_on_login: bool,
) -> bool:
    if password_hash is None:
        return False

    state = get_dashboard_session_store().get(session_id)
    if state is None or not state.password_verified:
        return False
    if totp_required_on_login and not state.totp_verified:
        return False
    return True


# --- Error format markers ---


def set_openai_error_format(request: Request) -> None:
    request.state.error_format = "openai"


def set_dashboard_error_format(request: Request) -> None:
    request.state.error_format = "dashboard"


# --- Proxy API key auth ---


async def validate_proxy_api_key(
    credentials: HTTPAuthorizationCredentials | None = Security(_bearer),
) -> ApiKeyData | None:
    authorization = None if credentials is None else f"Bearer {credentials.credentials}"
    return await validate_proxy_api_key_authorization(authorization)


async def validate_proxy_api_key_authorization(authorization: str | None) -> ApiKeyData | None:
    settings = await get_settings_cache().get()
    if not settings.api_key_auth_enabled:
        return None

    token = _extract_bearer_token(authorization)
    if not token:
        raise ProxyAuthError("Missing API key in Authorization header")

    async with get_background_session() as session:
        service = ApiKeysService(ApiKeysRepository(session))
        try:
            return await service.validate_key(token)
        except ApiKeyInvalidError as exc:
            raise ProxyAuthError(str(exc)) from exc


# --- Dashboard session auth ---


async def validate_dashboard_session(request: Request) -> None:
    settings = await get_settings_cache().get()
    if settings.password_hash is None:
        logger.warning(
            "dashboard_auth_migration_inconsistency password_hash is NULL"
            " while dashboard access was requested metric=dashboard_auth_migration_inconsistency"
        )
        raise DashboardAuthError("Authentication is required")

    session_id = request.cookies.get(DASHBOARD_SESSION_COOKIE)
    if not has_valid_dashboard_session(
        session_id,
        password_hash=settings.password_hash,
        totp_required_on_login=settings.totp_required_on_login,
    ):
        state = get_dashboard_session_store().get(session_id)
        if settings.totp_required_on_login and state is not None and state.password_verified and not state.totp_verified:
            raise DashboardAuthError("TOTP verification is required for dashboard access", code="totp_required")
        raise DashboardAuthError("Authentication is required")


# --- Codex usage caller identity auth ---


async def validate_codex_usage_identity(request: Request) -> None:
    token = _extract_bearer_token(request.headers.get("Authorization"))
    if not token:
        raise ProxyAuthError("Missing ChatGPT token in Authorization header")

    raw_account_id = request.headers.get("chatgpt-account-id")
    account_id = raw_account_id.strip() if raw_account_id else ""
    if not account_id:
        raise ProxyAuthError("Missing chatgpt-account-id header")

    async with get_background_session() as session:
        accounts_repo = AccountsRepository(session)
        is_authorized = await accounts_repo.exists_active_chatgpt_account_id(account_id)
    if not is_authorized:
        raise ProxyAuthError("Unknown or inactive chatgpt-account-id")

    try:
        await fetch_usage(access_token=token, account_id=account_id)
    except UsageFetchError as exc:
        if exc.status_code == 429:
            from app.core.exceptions import ProxyRateLimitError

            raise ProxyRateLimitError(exc.message) from exc
        if exc.status_code in (401, 403):
            raise ProxyAuthError("Invalid ChatGPT token or chatgpt-account-id") from exc
        raise ProxyUpstreamError("Unable to validate ChatGPT credentials at this time") from exc


def _extract_bearer_token(authorization: str | None) -> str | None:
    if authorization is None:
        return None
    prefix = "bearer "
    value = authorization.strip()
    if not value.lower().startswith(prefix):
        return None
    token = value[len(prefix) :].strip()
    if not token:
        return None
    return token
