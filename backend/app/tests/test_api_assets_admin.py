"""Asset administration tests (Phase 12): create/update/activate/
deactivate/delete, duplicate prevention, and the safe-deletion policy."""

from decimal import Decimal

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.core.database import get_db_session
from app.main import app
from app.models import Holding, StrategyBucket
from app.tests.conftest import make_asset, make_current_price, make_portfolio_config


@pytest_asyncio.fixture
async def client(db_session):
    async def _override_get_db_session():
        yield db_session

    app.dependency_overrides[get_db_session] = _override_get_db_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.pop(get_db_session, None)


async def test_create_asset_succeeds_with_valid_data(db_session, client):
    response = await client.post(
        "/api/assets",
        json={"symbol": "NEWCO", "name": "New Co", "asset_type": "STOCK", "currency": "EGP"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["symbol"] == "NEWCO"
    assert body["is_active"] is True
    assert body["market"] is None
    assert body["strategy_bucket_id"] is None


async def test_create_asset_rejects_duplicate_symbol(db_session, client):
    db_session.add(make_asset("DUPCO"))
    await db_session.commit()

    response = await client.post(
        "/api/assets", json={"symbol": "DUPCO", "name": "Dup Co", "asset_type": "STOCK", "currency": "EGP"}
    )
    assert response.status_code == 409


async def test_create_asset_rejects_invalid_asset_type(db_session, client):
    response = await client.post(
        "/api/assets", json={"symbol": "BADTYPE", "name": "Bad Type", "asset_type": "CRYPTO", "currency": "EGP"}
    )
    assert response.status_code == 422


async def test_create_asset_rejects_invalid_currency(db_session, client):
    response = await client.post(
        "/api/assets", json={"symbol": "BADCUR", "name": "Bad Currency", "asset_type": "STOCK", "currency": "1"}
    )
    assert response.status_code == 422


async def test_create_asset_rejects_unknown_strategy_bucket(db_session, client):
    response = await client.post(
        "/api/assets",
        json={
            "symbol": "BADBUCKET",
            "name": "Bad Bucket",
            "asset_type": "STOCK",
            "currency": "EGP",
            "strategy_bucket_id": "00000000-0000-0000-0000-000000000000",
        },
    )
    assert response.status_code == 400


async def test_update_asset_edits_name_and_market(db_session, client):
    asset = make_asset("EDITCO")
    db_session.add(asset)
    await db_session.commit()

    response = await client.patch(f"/api/assets/{asset.id}", json={"name": "Renamed Co", "market": "EGX"})
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Renamed Co"
    assert body["market"] == "EGX"


async def test_update_asset_reassigns_strategy_bucket(db_session, client):
    config = make_portfolio_config()
    db_session.add(config)
    await db_session.flush()
    bucket = StrategyBucket(portfolio_config_id=config.id, name="Growth")
    db_session.add(bucket)
    asset = make_asset("REASSIGN")
    db_session.add(asset)
    await db_session.commit()

    response = await client.patch(f"/api/assets/{asset.id}", json={"strategy_bucket_id": str(bucket.id)})
    assert response.status_code == 200
    assert response.json()["strategy_bucket_id"] == str(bucket.id)

    clear_response = await client.patch(f"/api/assets/{asset.id}", json={"clear_strategy_bucket": True})
    assert clear_response.status_code == 200
    assert clear_response.json()["strategy_bucket_id"] is None


async def test_update_asset_currency_allowed_with_no_history(db_session, client):
    asset = make_asset("FREECUR", currency="EGP")
    db_session.add(asset)
    await db_session.commit()

    response = await client.patch(f"/api/assets/{asset.id}", json={"currency": "USD"})
    assert response.status_code == 200
    assert response.json()["currency"] == "USD"


async def test_update_asset_currency_blocked_when_price_history_exists(db_session, client):
    asset = make_asset("PRICEDCUR", currency="EGP")
    db_session.add(asset)
    await db_session.flush()
    await make_current_price(db_session, asset, Decimal("10"))
    await db_session.commit()

    response = await client.patch(f"/api/assets/{asset.id}", json={"currency": "USD"})
    assert response.status_code == 409
    # Currency must remain untouched.
    unchanged = await client.get(f"/api/assets/{asset.id}")
    assert unchanged.json()["currency"] == "EGP"


async def test_update_asset_currency_blocked_when_transaction_history_exists(db_session, client):
    from datetime import datetime, timezone

    from app.models import Transaction, TransactionType

    asset = make_asset("TXNCUR", currency="EGP")
    db_session.add(asset)
    await db_session.flush()
    db_session.add(
        Transaction(
            asset_id=asset.id, transaction_type=TransactionType.BUY, quantity=Decimal("1"), price=Decimal("10"),
            transaction_date=datetime.now(timezone.utc),
        )
    )
    await db_session.commit()

    response = await client.patch(f"/api/assets/{asset.id}", json={"currency": "USD"})
    assert response.status_code == 409


async def test_activate_and_deactivate_asset(db_session, client):
    asset = make_asset("TOGGLE", is_active=True)
    db_session.add(asset)
    await db_session.commit()

    deactivated = await client.post(f"/api/assets/{asset.id}/deactivate")
    assert deactivated.status_code == 200
    assert deactivated.json()["is_active"] is False

    reactivated = await client.post(f"/api/assets/{asset.id}/activate")
    assert reactivated.status_code == 200
    assert reactivated.json()["is_active"] is True


async def test_deactivated_asset_still_listed_with_include_inactive(db_session, client):
    asset = make_asset("STILLLISTED", is_active=False)
    db_session.add(asset)
    await db_session.commit()

    default_listing = await client.get("/api/assets")
    assert not any(a["symbol"] == "STILLLISTED" for a in default_listing.json())

    full_listing = await client.get("/api/assets?include_inactive=true")
    assert any(a["symbol"] == "STILLLISTED" for a in full_listing.json())


async def test_delete_asset_succeeds_with_no_historical_data(db_session, client):
    asset = make_asset("DELETEME")
    db_session.add(asset)
    await db_session.commit()

    response = await client.delete(f"/api/assets/{asset.id}")
    assert response.status_code == 204

    follow_up = await client.get(f"/api/assets/{asset.id}")
    assert follow_up.status_code == 404


async def test_delete_asset_blocked_when_holding_exists(db_session, client):
    asset = make_asset("HASHOLDING")
    db_session.add(asset)
    await db_session.flush()
    db_session.add(Holding(asset_id=asset.id, quantity=Decimal("1")))
    await db_session.commit()

    response = await client.delete(f"/api/assets/{asset.id}")
    assert response.status_code == 409

    still_there = await client.get(f"/api/assets/{asset.id}")
    assert still_there.status_code == 200


async def test_delete_asset_blocked_when_price_history_exists(db_session, client):
    asset = make_asset("HASPRICEHIST")
    db_session.add(asset)
    await db_session.flush()
    await make_current_price(db_session, asset, Decimal("5"))
    await db_session.commit()

    response = await client.delete(f"/api/assets/{asset.id}")
    assert response.status_code == 409


async def test_delete_asset_404_for_missing_asset(client):
    response = await client.delete("/api/assets/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404
