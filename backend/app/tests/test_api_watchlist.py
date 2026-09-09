import uuid
from decimal import Decimal

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


async def _create_asset(session, symbol="APIWATCH", is_active=True):
    asset = make_asset(symbol, is_active=is_active)
    session.add(asset)
    await session.commit()
    return asset


async def test_add_watchlist_entry_returns_201(db_session, client):
    asset = await _create_asset(db_session)
    response = await client.post("/api/watchlist", json={"asset_id": str(asset.id), "notes": "keep an eye"})
    assert response.status_code == 201
    body = response.json()
    assert body["asset_id"] == str(asset.id)
    assert body["asset_symbol"] == "APIWATCH"
    assert body["enabled"] is True
    assert body["notes"] == "keep an eye"
    assert body["alert_rule"] is None


async def test_add_watchlist_entry_rejects_missing_asset(client):
    response = await client.post("/api/watchlist", json={"asset_id": str(uuid.uuid4())})
    assert response.status_code == 404


async def test_add_watchlist_entry_rejects_inactive_asset(db_session, client):
    asset = await _create_asset(db_session, symbol="APIINACTIVE", is_active=False)
    response = await client.post("/api/watchlist", json={"asset_id": str(asset.id)})
    assert response.status_code == 409


async def test_add_watchlist_entry_rejects_duplicate(db_session, client):
    asset = await _create_asset(db_session, symbol="APIDUP")
    await client.post("/api/watchlist", json={"asset_id": str(asset.id)})
    response = await client.post("/api/watchlist", json={"asset_id": str(asset.id)})
    assert response.status_code == 409


async def test_list_watchlist_returns_entries(db_session, client):
    asset = await _create_asset(db_session, symbol="APILIST")
    await client.post("/api/watchlist", json={"asset_id": str(asset.id)})
    response = await client.get("/api/watchlist")
    assert response.status_code == 200
    body = response.json()
    assert any(e["asset_symbol"] == "APILIST" for e in body)


async def test_list_watchlist_enabled_only_filter(db_session, client):
    asset = await _create_asset(db_session, symbol="APIENABLEDONLY")
    add_response = await client.post("/api/watchlist", json={"asset_id": str(asset.id)})
    watchlist_id = add_response.json()["id"]
    await client.delete(f"/api/watchlist/{watchlist_id}")

    response = await client.get("/api/watchlist", params={"enabled_only": True})
    body = response.json()
    assert not any(e["id"] == watchlist_id for e in body)

    response_all = await client.get("/api/watchlist", params={"enabled_only": False})
    body_all = response_all.json()
    assert any(e["id"] == watchlist_id for e in body_all)


async def test_patch_watchlist_entry_updates_notes_and_enabled(db_session, client):
    asset = await _create_asset(db_session, symbol="APIPATCH")
    add_response = await client.post("/api/watchlist", json={"asset_id": str(asset.id)})
    watchlist_id = add_response.json()["id"]

    response = await client.patch(f"/api/watchlist/{watchlist_id}", json={"enabled": False, "notes": "paused"})
    assert response.status_code == 200
    body = response.json()
    assert body["enabled"] is False
    assert body["notes"] == "paused"


async def test_patch_watchlist_entry_rejects_missing_entry(client):
    response = await client.patch(f"/api/watchlist/{uuid.uuid4()}", json={"enabled": False})
    assert response.status_code == 404


async def test_delete_watchlist_entry_is_logical_removal(db_session, client):
    asset = await _create_asset(db_session, symbol="APIDELETE")
    add_response = await client.post("/api/watchlist", json={"asset_id": str(asset.id)})
    watchlist_id = add_response.json()["id"]

    response = await client.delete(f"/api/watchlist/{watchlist_id}")
    assert response.status_code == 200
    body = response.json()
    assert body["enabled"] is False
    assert body["removed_at"] is not None


async def test_delete_watchlist_entry_rejects_missing_entry(client):
    response = await client.delete(f"/api/watchlist/{uuid.uuid4()}")
    assert response.status_code == 404


async def test_create_watchlist_alert_rule_returns_201(db_session, client):
    asset = await _create_asset(db_session, symbol="APIALERTRULE")
    add_response = await client.post("/api/watchlist", json={"asset_id": str(asset.id)})
    watchlist_id = add_response.json()["id"]

    response = await client.post(
        f"/api/watchlist/{watchlist_id}/alerts",
        json={"price_target_enabled": True, "price_target": "150.00"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["watchlist_id"] == watchlist_id
    assert Decimal(body["price_target"]) == Decimal("150.00")


async def test_create_watchlist_alert_rule_rejects_invalid_configuration(db_session, client):
    asset = await _create_asset(db_session, symbol="APIALERTINVALID")
    add_response = await client.post("/api/watchlist", json={"asset_id": str(asset.id)})
    watchlist_id = add_response.json()["id"]

    response = await client.post(f"/api/watchlist/{watchlist_id}/alerts", json={"dip_buy_enabled": True})
    assert response.status_code == 400


async def test_create_watchlist_alert_rule_rejects_duplicate(db_session, client):
    asset = await _create_asset(db_session, symbol="APIALERTDUP")
    add_response = await client.post("/api/watchlist", json={"asset_id": str(asset.id)})
    watchlist_id = add_response.json()["id"]
    await client.post(f"/api/watchlist/{watchlist_id}/alerts", json={})

    response = await client.post(f"/api/watchlist/{watchlist_id}/alerts", json={})
    assert response.status_code == 409


async def test_get_watchlist_alert_rule_returns_404_when_none_configured(db_session, client):
    asset = await _create_asset(db_session, symbol="APIALERTNONE")
    add_response = await client.post("/api/watchlist", json={"asset_id": str(asset.id)})
    watchlist_id = add_response.json()["id"]

    response = await client.get(f"/api/watchlist/{watchlist_id}/alerts")
    assert response.status_code == 404


async def test_get_watchlist_alert_rule_returns_it_when_configured(db_session, client):
    asset = await _create_asset(db_session, symbol="APIALERTGET")
    add_response = await client.post("/api/watchlist", json={"asset_id": str(asset.id)})
    watchlist_id = add_response.json()["id"]
    await client.post(f"/api/watchlist/{watchlist_id}/alerts", json={"dip_buy_enabled": True, "dip_buy_price": "50"})

    response = await client.get(f"/api/watchlist/{watchlist_id}/alerts")
    assert response.status_code == 200
    assert Decimal(response.json()["dip_buy_price"]) == Decimal("50")
