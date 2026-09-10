"""Analytics API tests (Phase 15): range validation, insufficient-history
reporting, response shape, and that no internal IDs/metadata ever leak."""

from datetime import datetime, timezone
from decimal import Decimal

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.core.database import get_db_session
from app.main import app
from app.models import AssetType
from app.services import transaction_service
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


async def _configure_portfolio(session):
    config = make_portfolio_config()
    session.add(config)
    await session.commit()
    return config


async def _make_cash_asset(session, symbol):
    asset = make_asset(symbol, asset_type=AssetType.CASH)
    session.add(asset)
    await session.commit()
    await make_current_price(session, asset, Decimal("1"))
    await session.commit()
    return asset


async def test_analytics_history_rejects_unsupported_range(db_session, client):
    await _configure_portfolio(db_session)
    response = await client.get("/api/portfolio/analytics/history?range=1Y")
    assert response.status_code == 422


async def test_analytics_history_404_when_no_portfolio_configured(client):
    response = await client.get("/api/portfolio/analytics/history?range=1M")
    assert response.status_code == 404


async def test_analytics_history_reports_insufficient_data_with_no_eligible_snapshots(db_session, client):
    await _configure_portfolio(db_session)
    response = await client.get("/api/portfolio/analytics/history?range=ALL")
    assert response.status_code == 200
    body = response.json()
    assert body["insufficient_history"] is True
    assert body["data"] == []
    assert body["message"]


async def test_analytics_history_shows_flat_deposit_as_zero_pnl_and_zero_twr(db_session, client):
    await _configure_portfolio(db_session)
    cash = await _make_cash_asset(db_session, "ANALYTICSCASH")
    await transaction_service.create_transaction(
        db_session, asset_id=cash.id, transaction_type="DEPOSIT", quantity=Decimal("10000"),
        price=Decimal("1"), fees=Decimal("0"), transaction_date=datetime(2026, 1, 1, tzinfo=timezone.utc), notes=None,
    )
    await transaction_service.create_transaction(
        db_session, asset_id=cash.id, transaction_type="DEPOSIT", quantity=Decimal("5000"),
        price=Decimal("1"), fees=Decimal("0"), transaction_date=datetime(2026, 1, 5, tzinfo=timezone.utc), notes=None,
    )

    response = await client.get("/api/portfolio/analytics/history?range=ALL")
    assert response.status_code == 200
    body = response.json()
    assert body["insufficient_history"] is False
    assert len(body["data"]) == 2
    last = body["data"][-1]
    assert Decimal(last["portfolio_value"]) == Decimal("15000.00")
    assert Decimal(last["invested_capital"]) == Decimal("15000.00")
    assert Decimal(last["total_pnl"]) == Decimal("0.00")
    assert Decimal(last["twr_percentage"]) == Decimal("0.00")


async def test_analytics_history_response_never_exposes_internal_ids_or_metadata(db_session, client):
    """Frontend responses must not expose database IDs, trigger_source,
    or any other internal implementation detail (Phase 15 spec, section
    11)."""
    await _configure_portfolio(db_session)
    cash = await _make_cash_asset(db_session, "ANALYTICSNOLEAK")
    await transaction_service.create_transaction(
        db_session, asset_id=cash.id, transaction_type="DEPOSIT", quantity=Decimal("1000"),
        price=Decimal("1"), fees=Decimal("0"), transaction_date=datetime(2026, 1, 1, tzinfo=timezone.utc), notes=None,
    )
    await transaction_service.create_transaction(
        db_session, asset_id=cash.id, transaction_type="DEPOSIT", quantity=Decimal("500"),
        price=Decimal("1"), fees=Decimal("0"), transaction_date=datetime(2026, 1, 2, tzinfo=timezone.utc), notes=None,
    )

    response = await client.get("/api/portfolio/analytics/history?range=ALL")
    body = response.json()
    assert set(body.keys()) == {"range", "base_currency", "data", "insufficient_history", "message"}
    for point in body["data"]:
        assert set(point.keys()) == {"date", "portfolio_value", "invested_capital", "total_pnl", "twr_percentage"}


async def test_analytics_history_1w_range_excludes_old_deposits(db_session, client):
    await _configure_portfolio(db_session)
    cash = await _make_cash_asset(db_session, "ANALYTICSRANGE")
    old_date = datetime(2020, 1, 1, tzinfo=timezone.utc)
    await transaction_service.create_transaction(
        db_session, asset_id=cash.id, transaction_type="DEPOSIT", quantity=Decimal("1000"),
        price=Decimal("1"), fees=Decimal("0"), transaction_date=old_date, notes=None,
    )
    await transaction_service.create_transaction(
        db_session, asset_id=cash.id, transaction_type="DEPOSIT", quantity=Decimal("500"),
        price=Decimal("1"), fees=Decimal("0"), transaction_date=old_date, notes=None,
    )

    response = await client.get("/api/portfolio/analytics/history?range=1W")
    body = response.json()
    assert body["insufficient_history"] is True
    assert body["data"] == []
