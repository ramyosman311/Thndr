"""Asset price configuration administration tests (Phase 12): valid/
invalid provider, valid/invalid stale threshold, manual lock, automated
fetching toggle."""

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.core.database import get_db_session
from app.main import app
from app.tests.conftest import make_asset


@pytest_asyncio.fixture
async def client(db_session):
    async def _override_get_db_session():
        yield db_session

    app.dependency_overrides[get_db_session] = _override_get_db_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.pop(get_db_session, None)


async def _create_asset(session, symbol="PXCFG"):
    asset = make_asset(symbol)
    session.add(asset)
    await session.commit()
    return asset


async def test_get_price_config_returns_unconfigured_default(db_session, client):
    asset = await _create_asset(db_session)
    response = await client.get(f"/api/assets/{asset.id}/price-config")
    assert response.status_code == 200
    body = response.json()
    assert body["configured"] is False
    assert body["primary_provider"] is None
    assert body["automated_fetching_enabled"] is False


async def test_get_price_config_404_for_missing_asset(client):
    response = await client.get("/api/assets/00000000-0000-0000-0000-000000000000/price-config")
    assert response.status_code == 404


async def test_put_price_config_with_valid_provider_succeeds(db_session, client):
    asset = await _create_asset(db_session, "VALIDPROV")
    response = await client.put(
        f"/api/assets/{asset.id}/price-config",
        json={
            "primary_provider": "yahoo",
            "primary_provider_symbol": "VALIDPROV.CA",
            "automated_fetching_enabled": True,
            "manual_override_enabled": True,
            "stale_threshold_minutes": 30,
            "lock_manual": False,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["configured"] is True
    assert body["primary_provider"] == "yahoo"
    assert body["stale_threshold_minutes"] == 30


async def test_put_price_config_rejects_unregistered_provider(db_session, client):
    asset = await _create_asset(db_session, "BADPROV")
    response = await client.put(
        f"/api/assets/{asset.id}/price-config",
        json={"primary_provider": "unknown-provider", "primary_provider_symbol": "X"},
    )
    assert response.status_code == 400


async def test_put_price_config_rejects_provider_without_symbol(db_session, client):
    asset = await _create_asset(db_session, "NOSYMBOL")
    response = await client.put(
        f"/api/assets/{asset.id}/price-config", json={"primary_provider": "yahoo"}
    )
    assert response.status_code == 400


async def test_put_price_config_rejects_automated_fetching_without_primary_provider(db_session, client):
    asset = await _create_asset(db_session, "NOPRIMARY")
    response = await client.put(
        f"/api/assets/{asset.id}/price-config", json={"automated_fetching_enabled": True}
    )
    assert response.status_code == 400


async def test_put_price_config_rejects_zero_stale_threshold(db_session, client):
    asset = await _create_asset(db_session, "ZEROTHRESH")
    response = await client.put(
        f"/api/assets/{asset.id}/price-config", json={"stale_threshold_minutes": 0}
    )
    assert response.status_code == 422


async def test_put_price_config_rejects_negative_stale_threshold(db_session, client):
    asset = await _create_asset(db_session, "NEGTHRESH")
    response = await client.put(
        f"/api/assets/{asset.id}/price-config", json={"stale_threshold_minutes": -5}
    )
    assert response.status_code == 422


async def test_put_price_config_manual_lock_toggle_persists(db_session, client):
    asset = await _create_asset(db_session, "LOCKTOGGLE")
    response = await client.put(f"/api/assets/{asset.id}/price-config", json={"lock_manual": True})
    assert response.status_code == 200
    assert response.json()["lock_manual"] is True

    follow_up = await client.get(f"/api/assets/{asset.id}/price-config")
    assert follow_up.json()["lock_manual"] is True


async def test_put_price_config_is_idempotent_upsert(db_session, client):
    asset = await _create_asset(db_session, "UPSERTME")
    first = await client.put(
        f"/api/assets/{asset.id}/price-config",
        json={"primary_provider": "yahoo", "primary_provider_symbol": "A", "automated_fetching_enabled": True},
    )
    assert first.status_code == 200

    second = await client.put(f"/api/assets/{asset.id}/price-config", json={"manual_override_enabled": False})
    assert second.status_code == 200
    body = second.json()
    # A full-replacement PUT with no provider fields clears the previous ones.
    assert body["primary_provider"] is None
    assert body["manual_override_enabled"] is False
