"""Router-level authentication (P0-3C): every non-health API route requires a
verified Supabase JWT, optionally accompanied by the internal proxy token.

Supersedes the P0-2 shared-token tests: `Authorization` now carries the
user's Supabase JWT, so the old "Authorization: Bearer <API_AUTH_TOKEN>"
contract no longer exists -- the legacy shared token is explicitly asserted
to be rejected as a credential below. These tests drive the REAL app over
HTTP against the test database with REAL signed JWTs (see conftest.py);
nothing here stubs the auth dependency.
"""

from datetime import timedelta

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.core import auth as auth_module
from app.core.config import Settings
from app.core.database import engine
from app.main import app
from app.tests.conftest import TEST_INTERNAL_TOKEN, make_jwt

LEGACY_SHARED_TOKEN = TEST_INTERNAL_TOKEN


@pytest_asyncio.fixture(autouse=True)
async def _dispose_global_engine_pool_after_each_test():
    """Same reasoning as test_health.py: some tests here exercise the real
    app (and its global engine) over HTTP across multiple event loops."""
    yield
    await engine.dispose()


def _settings(*, dev_mode: bool, api_auth_token: str = "") -> Settings:
    return Settings(DEV_MODE=dev_mode, API_AUTH_TOKEN=api_auth_token)


# --- Health stays public ---------------------------------------------------


async def test_health_accessible_without_credentials(supabase_auth):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.get("/api/health")

    assert response.status_code == 200


async def test_readiness_accessible_without_credentials(supabase_auth):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.get("/api/health/ready")

    assert response.status_code in (200, 503)


# --- Protected routes: missing / invalid / expired / valid JWT -------------


async def test_protected_route_rejects_missing_authorization(client_for):
    async with client_for(None) as ac:
        response = await ac.get("/api/assets")

    assert response.status_code == 401


async def test_protected_route_rejects_malformed_authorization_header(client_for, user_a):
    async with client_for(None) as ac:
        response = await ac.get("/api/assets", headers={"Authorization": make_jwt(user_a.id)})  # no "Bearer "

    assert response.status_code == 401


async def test_protected_route_rejects_invalid_jwt(client_for):
    async with client_for(None) as ac:
        response = await ac.get("/api/assets", headers={"Authorization": "Bearer not-a-real-jwt"})

    assert response.status_code == 401


async def test_protected_route_rejects_expired_jwt(client_for, user_a):
    token = make_jwt(user_a.id, expires_in=timedelta(minutes=-5))
    async with client_for(None) as ac:
        response = await ac.get("/api/assets", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 401


async def test_protected_route_accepts_valid_jwt(client_for, user_a):
    async with client_for(user_a) as ac:
        response = await ac.get("/api/assets")

    assert response.status_code == 200


async def test_protected_write_route_also_requires_jwt(client_for):
    async with client_for(None) as ac:
        response = await ac.post(
            "/api/assets", json={"symbol": "X", "name": "X", "asset_type": "STOCK", "currency": "EGP"}
        )

    assert response.status_code == 401


async def test_every_non_health_route_is_protected(client_for):
    """The router-level dependency covers every mounted route, including any
    added later -- no non-health route is reachable without a credential."""
    unprotected = []
    async with client_for(None) as ac:
        for route in app.routes:
            path = getattr(route, "path", "")
            if not path.startswith("/api/") or path.startswith("/api/health"):
                continue
            for method in getattr(route, "methods", set()) - {"HEAD", "OPTIONS"}:
                concrete = path.replace("{", "0").replace("}", "0")
                # path params are concrete placeholders; body-less is fine --
                # auth runs before any body validation or handler
                response = await ac.request(method, concrete)
                if response.status_code != 401:
                    unprotected.append((method, path, response.status_code))
    assert unprotected == []


# --- The legacy shared token is no longer a credential ---------------------


async def test_legacy_shared_token_as_bearer_is_rejected(client_for):
    async with client_for(None) as ac:
        response = await ac.get("/api/assets", headers={"Authorization": f"Bearer {LEGACY_SHARED_TOKEN}"})

    assert response.status_code == 401


# --- DEV_MODE is not an authentication or ownership bypass -----------------


async def test_dev_mode_does_not_bypass_authentication(monkeypatch, db_session, supabase_auth):
    monkeypatch.setattr(
        auth_module,
        "get_settings",
        lambda: Settings(DEV_MODE=True, SUPABASE_URL="https://test-project.supabase.co"),
    )
    from app.core.database import get_db_session

    async def _override():
        yield db_session

    app.dependency_overrides[get_db_session] = _override
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.get("/api/assets")
    finally:
        app.dependency_overrides.pop(get_db_session, None)

    assert response.status_code == 401


# --- Internal proxy token: optional-if-present, never identity -------------


async def test_valid_jwt_without_internal_token_is_allowed(client_for, user_a):
    """A native/Capacitor client sends only the JWT."""
    async with client_for(user_a) as ac:
        response = await ac.get("/api/assets")

    assert response.status_code == 200


async def test_valid_jwt_with_correct_internal_token_is_allowed(client_for, user_a):
    """The web path: Vercel proxy forwards the JWT plus the internal token."""
    async with client_for(user_a) as ac:
        response = await ac.get("/api/assets", headers={"X-Internal-Proxy-Token": TEST_INTERNAL_TOKEN})

    assert response.status_code == 200


async def test_valid_jwt_with_incorrect_internal_token_is_rejected(client_for, user_a):
    async with client_for(user_a) as ac:
        response = await ac.get("/api/assets", headers={"X-Internal-Proxy-Token": "wrong-token"})

    assert response.status_code == 401


async def test_correct_internal_token_alone_is_never_identity(client_for):
    """The internal token is a server-to-server trust signal, not a user:
    with no JWT, a correct token still gets 401."""
    async with client_for(None) as ac:
        response = await ac.get("/api/assets", headers={"X-Internal-Proxy-Token": TEST_INTERNAL_TOKEN})

    assert response.status_code == 401


async def test_expired_jwt_with_correct_internal_token_is_rejected(client_for, user_a):
    token = make_jwt(user_a.id, expires_in=timedelta(minutes=-1))
    async with client_for(None) as ac:
        response = await ac.get(
            "/api/assets",
            headers={"Authorization": f"Bearer {token}", "X-Internal-Proxy-Token": TEST_INTERNAL_TOKEN},
        )

    assert response.status_code == 401


async def test_unauthenticated_responses_leak_nothing(client_for):
    async with client_for(None) as ac:
        response = await ac.get("/api/portfolio/summary")

    assert response.status_code == 401
    assert response.json() == {"detail": "Not authenticated"}


# --- Fail-closed startup guard ---------------------------------------------


def test_startup_fails_closed_when_token_missing_in_production_mode(monkeypatch, capsys):
    monkeypatch.setattr(auth_module, "get_settings", lambda: _settings(dev_mode=False, api_auth_token=""))

    with pytest.raises(SystemExit) as exc_info:
        auth_module.ensure_auth_configured()

    assert exc_info.value.code == 1
    assert "API_AUTH_TOKEN" in capsys.readouterr().err


def test_startup_succeeds_when_dev_mode_true_even_without_token(monkeypatch):
    monkeypatch.setattr(auth_module, "get_settings", lambda: _settings(dev_mode=True, api_auth_token=""))

    auth_module.ensure_auth_configured()  # must not raise


def test_startup_succeeds_when_token_present_in_production_mode(monkeypatch):
    monkeypatch.setattr(auth_module, "get_settings", lambda: _settings(dev_mode=False, api_auth_token="tok"))

    auth_module.ensure_auth_configured()  # must not raise
