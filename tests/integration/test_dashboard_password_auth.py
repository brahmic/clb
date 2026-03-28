from __future__ import annotations

import pytest

from app.modules.dashboard_auth.service import get_password_rate_limiter

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_password_endpoints_setup_login_change_remove(anonymous_client):
    weak = await anonymous_client.post("/api/dashboard-auth/password/setup", json={"password": "short"})
    assert weak.status_code == 422
    assert weak.json()["error"]["code"] == "validation_error"

    setup = await anonymous_client.post(
        "/api/dashboard-auth/password/setup",
        json={"password": "password123"},
    )
    assert setup.status_code == 200
    assert setup.json()["setupRequired"] is False
    assert setup.json()["passwordRequired"] is True

    setup_again = await anonymous_client.post(
        "/api/dashboard-auth/password/setup",
        json={"password": "password123"},
    )
    assert setup_again.status_code == 409

    logout = await anonymous_client.post("/api/dashboard-auth/logout", json={})
    assert logout.status_code == 200

    invalid_login = await anonymous_client.post(
        "/api/dashboard-auth/password/login",
        json={"password": "wrong-password"},
    )
    assert invalid_login.status_code == 401
    assert invalid_login.json()["error"]["code"] == "invalid_credentials"

    login = await anonymous_client.post(
        "/api/dashboard-auth/password/login",
        json={"password": "password123"},
    )
    assert login.status_code == 200
    assert login.json()["authenticated"] is True

    bad_change = await anonymous_client.post(
        "/api/dashboard-auth/password/change",
        json={"currentPassword": "wrong-password", "newPassword": "new-password-456"},
    )
    assert bad_change.status_code == 401
    assert bad_change.json()["error"]["code"] == "invalid_credentials"

    change = await anonymous_client.post(
        "/api/dashboard-auth/password/change",
        json={"currentPassword": "password123", "newPassword": "new-password-456"},
    )
    assert change.status_code == 200

    logout_again = await anonymous_client.post("/api/dashboard-auth/logout", json={})
    assert logout_again.status_code == 200

    old_login = await anonymous_client.post(
        "/api/dashboard-auth/password/login",
        json={"password": "password123"},
    )
    assert old_login.status_code == 401

    new_login = await anonymous_client.post(
        "/api/dashboard-auth/password/login",
        json={"password": "new-password-456"},
    )
    assert new_login.status_code == 200

    bad_remove = await anonymous_client.request(
        "DELETE",
        "/api/dashboard-auth/password",
        json={"password": "wrong-password"},
    )
    assert bad_remove.status_code == 401
    assert bad_remove.json()["error"]["code"] == "invalid_credentials"

    remove = await anonymous_client.request(
        "DELETE",
        "/api/dashboard-auth/password",
        json={"password": "new-password-456"},
    )
    assert remove.status_code == 200

    session = await anonymous_client.get("/api/dashboard-auth/session")
    assert session.status_code == 200
    session_payload = session.json()
    assert session_payload["setupRequired"] is True
    assert session_payload["passwordRequired"] is False
    assert session_payload["authenticated"] is False
    assert session_payload["totpRequiredOnLogin"] is False


@pytest.mark.asyncio
async def test_password_login_rate_limit(anonymous_client):
    limiter = get_password_rate_limiter()
    limiter._failures.clear()  # noqa: SLF001

    setup = await anonymous_client.post(
        "/api/dashboard-auth/password/setup",
        json={"password": "password123"},
    )
    assert setup.status_code == 200
    await anonymous_client.post("/api/dashboard-auth/logout", json={})

    for _ in range(8):
        response = await anonymous_client.post(
            "/api/dashboard-auth/password/login",
            json={"password": "wrong-password"},
        )
        assert response.status_code == 401

    limited = await anonymous_client.post(
        "/api/dashboard-auth/password/login",
        json={"password": "wrong-password"},
    )
    assert limited.status_code == 429
    assert "Retry-After" in limited.headers

    limiter._failures.clear()  # noqa: SLF001
    success = await anonymous_client.post(
        "/api/dashboard-auth/password/login",
        json={"password": "password123"},
    )
    assert success.status_code == 200
