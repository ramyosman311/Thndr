"""P0-2: every non-health API route must require API_AUTH_TOKEN unless
DEV_MODE=true, and a DEV_MODE=false process must refuse to start at all
without the token configured. Mirrors the monkeypatch-the-module's-
`get_settings`-reference pattern already used by
test_seed_production_guard.py.
"""

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.core import auth as auth_module
from app.core.config import Settings
from app.core.database import engine
from app.main import app

TOKEN = "test-shared-secret"


@pytest_asyncio.fixture(autouse=True)
async def _dispose_global_engine_pool_after_each_test():
    """Same reasoning as test_health.py: these tests exercise the real
    app (and its global engine) over HTTP across multiple event loops."""
    yield
    await engine.dispose()


def _settings(*, dev_mode: bool, api_auth_token: str = "") -> Settings:
    return Settings(DEV_MODE=dev_mode, API_AUTH_TOKEN=api_auth_token)


def _require_auth(monkeypatch, *, dev_mode: bool, api_auth_token: str = "") -> None:
    monkeypatch.setattr(auth_module, "get_settings", lambda: _settings(dev_mode=dev_mode, api_auth_token=api_auth_token))


# --- Health stays public ---------------------------------------------------


@pytest.mark.asyncio
async def test_health_accessible_without_token_when_auth_enforced(monkeypatch):
    _require_auth(monkeypatch, dev_mode=False, api_auth_token=TOKEN)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/health")

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_readiness_accessible_without_token_when_auth_enforced(monkeypatch):
    _require_auth(monkeypatch, dev_mode=False, api_auth_token=TOKEN)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/health/ready")

    assert response.status_code in (200, 503)


# --- Protected routes: missing / invalid / valid token ---------------------


@pytest.mark.asyncio
async def test_protected_route_rejects_missing_token(monkeypatch):
    _require_auth(monkeypatch, dev_mode=False, api_auth_token=TOKEN)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/assets")

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_protected_route_rejects_invalid_token(monkeypatch):
    _require_auth(monkeypatch, dev_mode=False, api_auth_token=TOKEN)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/assets", headers={"Authorization": "Bearer wrong-token"})

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_protected_route_rejects_malformed_authorization_header(monkeypatch):
    _require_auth(monkeypatch, dev_mode=False, api_auth_token=TOKEN)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/assets", headers={"Authorization": TOKEN})

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_protected_route_accepts_valid_token(monkeypatch):
    _require_auth(monkeypatch, dev_mode=False, api_auth_token=TOKEN)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/assets", headers={"Authorization": f"Bearer {TOKEN}"})

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_protected_write_route_also_requires_token(monkeypatch):
    """Confirms the router-level dependency covers write endpoints too,
    not just the reads exercised above."""
    _require_auth(monkeypatch, dev_mode=False, api_auth_token=TOKEN)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/assets", json={"symbol": "X", "name": "X", "asset_type": "STOCK", "currency": "EGP"})

    assert response.status_code == 401


# --- DEV_MODE bypass ---------------------------------------------------


@pytest.mark.asyncio
async def test_dev_mode_bypasses_auth_on_protected_routes(monkeypatch):
    _require_auth(monkeypatch, dev_mode=True)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/assets")

    assert response.status_code == 200


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
    monkeypatch.setattr(auth_module, "get_settings", lambda: _settings(dev_mode=False, api_auth_token=TOKEN))

    auth_module.ensure_auth_configured()  # must not raise
