"""Portfolio configuration administration tests (Phase 12): create,
update name, valid/invalid base currency, emergency asset validation,
and the base-currency change protection once transactions exist."""

from datetime import datetime, timezone
from decimal import Decimal

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.core.database import get_db_session
from app.main import app
from app.models import Transaction, TransactionType
from app.tests.conftest import make_asset, make_portfolio_config


@pytest_asyncio.fixture
async def client(db_session):
    async def _override_get_db_session():
        yield db_session

    app.dependency_overrides[get_db_session] = _override_get_db_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.pop(get_db_session, None)


async def test_get_config_404_when_none_exists(client):
    response = await client.get("/api/portfolio/config")
    assert response.status_code == 404


async def test_create_config_succeeds_when_none_exists(db_session, client):
    response = await client.post(
        "/api/portfolio/config", json={"name": "My Portfolio", "base_currency": "EGP"}
    )
    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "My Portfolio"
    assert body["base_currency"] == "EGP"
    assert body["emergency_excluded"] is False


async def test_create_config_rejects_when_one_already_exists(db_session, client):
    db_session.add(make_portfolio_config())
    await db_session.commit()

    response = await client.post("/api/portfolio/config", json={"name": "Second", "base_currency": "USD"})
    assert response.status_code == 409


async def test_create_config_rejects_invalid_emergency_asset(db_session, client):
    response = await client.post(
        "/api/portfolio/config",
        json={
            "name": "Bad Emergency",
            "base_currency": "EGP",
            "emergency_asset_id": "00000000-0000-0000-0000-000000000000",
        },
    )
    assert response.status_code == 400


async def test_update_config_name(db_session, client):
    db_session.add(make_portfolio_config(name="Old Name"))
    await db_session.commit()

    response = await client.patch("/api/portfolio/config", json={"name": "New Name"})
    assert response.status_code == 200
    assert response.json()["name"] == "New Name"


async def test_update_config_telegram_enabled(db_session, client):
    """Phase 14: telegram_enabled is the portfolio-level master switch
    gating Telegram delivery -- must be updatable through the same admin
    mechanism as every other field, not stuck at its Phase 3 default."""
    db_session.add(make_portfolio_config())
    await db_session.commit()

    response = await client.patch("/api/portfolio/config", json={"telegram_enabled": True})
    assert response.status_code == 200
    assert response.json()["telegram_enabled"] is True

    response = await client.patch("/api/portfolio/config", json={"telegram_enabled": False})
    assert response.status_code == 200
    assert response.json()["telegram_enabled"] is False


async def test_update_config_base_currency_allowed_with_no_transactions(db_session, client):
    db_session.add(make_portfolio_config(base_currency="EGP"))
    await db_session.commit()

    response = await client.patch("/api/portfolio/config", json={"base_currency": "USD"})
    assert response.status_code == 200
    assert response.json()["base_currency"] == "USD"


async def test_update_config_base_currency_blocked_once_a_transaction_exists(db_session, client):
    config = make_portfolio_config(base_currency="EGP")
    db_session.add(config)
    asset = make_asset("PCFGTXN")
    db_session.add(asset)
    await db_session.flush()
    db_session.add(
        Transaction(
            asset_id=asset.id, transaction_type=TransactionType.BUY, quantity=Decimal("1"), price=Decimal("10"),
            transaction_date=datetime.now(timezone.utc),
        )
    )
    await db_session.commit()

    response = await client.patch("/api/portfolio/config", json={"base_currency": "USD"})
    assert response.status_code == 409
    # base_currency must remain untouched; financial history is preserved.
    unchanged = await client.get("/api/portfolio/config")
    assert unchanged.json()["base_currency"] == "EGP"


async def test_update_config_rejects_invalid_currency_code(db_session, client):
    db_session.add(make_portfolio_config())
    await db_session.commit()

    response = await client.patch("/api/portfolio/config", json={"base_currency": "1"})
    assert response.status_code == 422


async def test_update_config_sets_and_clears_emergency_asset(db_session, client):
    db_session.add(make_portfolio_config())
    emergency_asset = make_asset("EMERGADMIN")
    db_session.add(emergency_asset)
    await db_session.commit()

    set_response = await client.patch(
        "/api/portfolio/config", json={"emergency_asset_id": str(emergency_asset.id), "emergency_excluded": True}
    )
    assert set_response.status_code == 200
    assert set_response.json()["emergency_asset_id"] == str(emergency_asset.id)
    assert set_response.json()["emergency_excluded"] is True

    clear_response = await client.patch("/api/portfolio/config", json={"clear_emergency_asset": True})
    assert clear_response.status_code == 200
    assert clear_response.json()["emergency_asset_id"] is None


async def test_update_config_rejects_invalid_emergency_asset(db_session, client):
    db_session.add(make_portfolio_config())
    await db_session.commit()

    response = await client.patch(
        "/api/portfolio/config", json={"emergency_asset_id": "00000000-0000-0000-0000-000000000000"}
    )
    assert response.status_code == 400


async def test_update_config_404_when_none_exists(client):
    response = await client.patch("/api/portfolio/config", json={"name": "Nope"})
    assert response.status_code == 404
