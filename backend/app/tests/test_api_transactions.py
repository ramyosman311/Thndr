import uuid
from decimal import Decimal

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.core.database import get_db_session
from app.main import app
from app.models import PortfolioConfig
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


async def _create_asset(session, symbol="APITXN"):
    asset = make_asset(symbol)
    session.add(asset)
    await session.commit()
    return asset


async def test_post_transaction_buy_returns_201_with_holding_snapshot(db_session, client):
    asset = await _create_asset(db_session)
    response = await client.post(
        "/api/transactions",
        json={
            "asset_id": str(asset.id),
            "transaction_type": "BUY",
            "quantity": "10",
            "price": "100.00",
            "fees": "5.00",
            "transaction_date": "2026-01-01T00:00:00Z",
            "notes": "first lot",
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["transaction"]["asset_symbol"] == "APITXN"
    assert body["transaction"]["transaction_type"] == "BUY"
    assert Decimal(body["holding"]["quantity"]) == Decimal("10")
    assert Decimal(body["holding"]["average_cost"]) == Decimal("100.5")  # (1000+5)/10
    assert body["realized_pnl"] is None


async def test_post_transaction_rejects_missing_asset(client):
    response = await client.post(
        "/api/transactions",
        json={
            "asset_id": str(uuid.uuid4()),
            "transaction_type": "BUY",
            "quantity": "1",
            "price": "10",
            "transaction_date": "2026-01-01T00:00:00Z",
        },
    )
    assert response.status_code == 404


async def test_post_transaction_rejects_negative_quantity(db_session, client):
    asset = await _create_asset(db_session, "APITXNNEG")
    response = await client.post(
        "/api/transactions",
        json={
            "asset_id": str(asset.id),
            "transaction_type": "BUY",
            "quantity": "-1",
            "price": "10",
            "transaction_date": "2026-01-01T00:00:00Z",
        },
    )
    assert response.status_code == 422


async def test_post_transaction_rejects_zero_quantity(db_session, client):
    asset = await _create_asset(db_session, "APITXNZERO")
    response = await client.post(
        "/api/transactions",
        json={
            "asset_id": str(asset.id),
            "transaction_type": "BUY",
            "quantity": "0",
            "price": "10",
            "transaction_date": "2026-01-01T00:00:00Z",
        },
    )
    assert response.status_code == 422


async def test_post_transaction_rejects_negative_price(db_session, client):
    asset = await _create_asset(db_session, "APITXNNEGPRICE")
    response = await client.post(
        "/api/transactions",
        json={
            "asset_id": str(asset.id),
            "transaction_type": "BUY",
            "quantity": "1",
            "price": "-10",
            "transaction_date": "2026-01-01T00:00:00Z",
        },
    )
    assert response.status_code == 422


async def test_post_transaction_rejects_negative_fees(db_session, client):
    asset = await _create_asset(db_session, "APITXNNEGFEES")
    response = await client.post(
        "/api/transactions",
        json={
            "asset_id": str(asset.id),
            "transaction_type": "BUY",
            "quantity": "1",
            "price": "10",
            "fees": "-1",
            "transaction_date": "2026-01-01T00:00:00Z",
        },
    )
    assert response.status_code == 422


async def test_post_transaction_rejects_unsupported_transaction_type(db_session, client):
    asset = await _create_asset(db_session, "APITXNTYPE")
    response = await client.post(
        "/api/transactions",
        json={
            "asset_id": str(asset.id),
            "transaction_type": "DIVIDEND",
            "quantity": "1",
            "price": "10",
            "transaction_date": "2026-01-01T00:00:00Z",
        },
    )
    assert response.status_code == 422


async def test_post_transaction_oversell_returns_409(db_session, client):
    asset = await _create_asset(db_session, "APITXNOVERSELL")
    await client.post(
        "/api/transactions",
        json={
            "asset_id": str(asset.id), "transaction_type": "BUY", "quantity": "5",
            "price": "100", "transaction_date": "2026-01-01T00:00:00Z",
        },
    )
    response = await client.post(
        "/api/transactions",
        json={
            "asset_id": str(asset.id), "transaction_type": "SELL", "quantity": "10",
            "price": "100", "transaction_date": "2026-01-02T00:00:00Z",
        },
    )
    assert response.status_code == 409


async def test_get_transactions_returns_history_most_recent_first(db_session, client):
    asset = await _create_asset(db_session, "APITXNHISTORY")
    await client.post(
        "/api/transactions",
        json={
            "asset_id": str(asset.id), "transaction_type": "BUY", "quantity": "1",
            "price": "10", "transaction_date": "2026-01-01T00:00:00Z", "notes": "oldest",
        },
    )
    await client.post(
        "/api/transactions",
        json={
            "asset_id": str(asset.id), "transaction_type": "BUY", "quantity": "1",
            "price": "10", "transaction_date": "2026-02-01T00:00:00Z", "notes": "newest",
        },
    )
    response = await client.get("/api/transactions")
    assert response.status_code == 200
    body = response.json()
    ours = [t for t in body if t["asset_symbol"] == "APITXNHISTORY"]
    assert ours[0]["notes"] == "newest"
    assert ours[1]["notes"] == "oldest"


async def test_portfolio_summary_reflects_transaction_after_post(db_session, client):
    db_session.add(PortfolioConfig(name="API Txn Portfolio", base_currency="EGP"))
    await db_session.commit()
    asset = await _create_asset(db_session, "APITXNREFLECT")
    await client.post(
        "/api/transactions",
        json={
            "asset_id": str(asset.id), "transaction_type": "BUY", "quantity": "10",
            "price": "50", "transaction_date": "2026-01-01T00:00:00Z",
        },
    )
    response = await client.get("/api/portfolio/summary")
    assert response.status_code == 200
    body = response.json()
    row = next(p for p in body["holdings_pnl"] if p["symbol"] == "APITXNREFLECT")
    assert Decimal(row["quantity"]) == Decimal("10")
    assert Decimal(row["average_cost"]) == Decimal("50")


async def test_transaction_endpoint_does_not_leak_internal_error_details(db_session, client):
    """A 422 from Pydantic validation must never include a raw stack
    trace — only a structured validation error."""
    asset = await _create_asset(db_session, "APITXNNOLEAK")
    response = await client.post(
        "/api/transactions",
        json={
            "asset_id": str(asset.id), "transaction_type": "BUY", "quantity": "not-a-number",
            "price": "10", "transaction_date": "2026-01-01T00:00:00Z",
        },
    )
    assert response.status_code == 422
    assert "Traceback" not in response.text
