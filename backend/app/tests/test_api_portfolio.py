from decimal import Decimal

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.core.database import get_db_session
from app.main import app
from app.models import AssetType, Holding, PortfolioConfig, StrategyBucket
from app.tests.conftest import make_asset


@pytest_asyncio.fixture
async def client(db_session):
    """An httpx client for `app`, wired to use the exact same test-database
    session/transaction as `db_session` — so data written directly via the
    ORM in a test is immediately visible to the HTTP call, and everything
    rolls back together at teardown."""

    async def _override_get_db_session():
        yield db_session

    app.dependency_overrides[get_db_session] = _override_get_db_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.pop(get_db_session, None)


async def test_portfolio_summary_endpoint_returns_calculated_values(db_session, client):
    config = PortfolioConfig(name="API Test Portfolio", base_currency="EGP", emergency_excluded=True)
    db_session.add(config)
    await db_session.flush()

    emergency_asset = make_asset("APIEMERG", asset_type=AssetType.SAVINGS)
    db_session.add(emergency_asset)
    await db_session.flush()
    config.emergency_asset_id = emergency_asset.id
    db_session.add(Holding(asset_id=emergency_asset.id, quantity=Decimal("1"), current_price=Decimal("100000")))

    stock_asset = make_asset("APISTK")
    db_session.add(stock_asset)
    await db_session.flush()
    db_session.add(Holding(asset_id=stock_asset.id, quantity=Decimal("100"), current_price=Decimal("100")))
    await db_session.commit()

    response = await client.get("/api/portfolio/summary")
    assert response.status_code == 200
    body = response.json()

    assert body["base_currency"] == "EGP"
    assert Decimal(body["emergency_value"]) == Decimal("100000.00")
    assert Decimal(body["investable_value"]) == Decimal("10000.00")
    assert Decimal(body["total_value"]) == Decimal("110000.00")
    assert Decimal(body["denominator_value"]) == Decimal("10000.00")
    assert body["denominator_basis"] == "investable"
    assert body["emergency_excluded"] is True

    pnl_by_symbol = {p["symbol"]: p for p in body["holdings_pnl"]}
    assert "APISTK" in pnl_by_symbol
    assert Decimal(pnl_by_symbol["APISTK"]["market_value"]) == Decimal("10000.00")


async def test_portfolio_allocation_endpoint_returns_calculated_percentages(db_session, client):
    config = PortfolioConfig(name="API Alloc Portfolio", base_currency="EGP", emergency_excluded=False)
    db_session.add(config)
    await db_session.flush()

    bucket = StrategyBucket(portfolio_config_id=config.id, name="API Bucket")
    db_session.add(bucket)
    await db_session.flush()

    asset = make_asset("APIALLOC", strategy_bucket_id=bucket.id)
    db_session.add(asset)
    await db_session.flush()
    db_session.add(Holding(asset_id=asset.id, quantity=Decimal("10"), current_price=Decimal("10")))  # value 100
    await db_session.commit()

    response = await client.get("/api/portfolio/allocation")
    assert response.status_code == 200
    body = response.json()

    assert body["risk_denominator_basis"] == "total"
    bucket_out = next(b for b in body["buckets"] if b["bucket_name"] == "API Bucket")
    assert Decimal(bucket_out["actual_value"]) == Decimal("100.00")
    assert Decimal(bucket_out["total_portfolio_percent"]) == Decimal("100.00")
    assert Decimal(bucket_out["risk_allocation_percent"]) == Decimal("100.00")
    assert bucket_out["target_status"] == "NO_TARGET"
    assert bucket_out["excluded_from_risk_allocation"] is False


async def test_excluded_emergency_bucket_has_null_risk_allocation_percent_via_api(db_session, client):
    """Resolves the Phase 5 caveat at the API boundary: the bucket holding
    the emergency asset must never show a misleading (e.g. >100%) risk
    allocation percentage when excluded from risk allocation."""
    config = PortfolioConfig(name="Emergency Caveat Portfolio", base_currency="EGP", emergency_excluded=True)
    db_session.add(config)
    await db_session.flush()

    emergency_bucket = StrategyBucket(portfolio_config_id=config.id, name="Emergency Cash")
    db_session.add(emergency_bucket)
    await db_session.flush()

    emergency_asset = make_asset("CAVEATEMERG", asset_type=AssetType.SAVINGS, strategy_bucket_id=emergency_bucket.id)
    db_session.add(emergency_asset)
    await db_session.flush()
    config.emergency_asset_id = emergency_asset.id
    db_session.add(Holding(asset_id=emergency_asset.id, quantity=Decimal("1"), current_price=Decimal("100000")))

    stock_asset = make_asset("CAVEATSTK")
    db_session.add(stock_asset)
    await db_session.flush()
    db_session.add(Holding(asset_id=stock_asset.id, quantity=Decimal("100"), current_price=Decimal("100")))
    await db_session.commit()

    response = await client.get("/api/portfolio/allocation")
    assert response.status_code == 200
    body = response.json()

    emergency_out = next(b for b in body["buckets"] if b["bucket_name"] == "Emergency Cash")
    assert emergency_out["risk_allocation_percent"] is None
    assert emergency_out["excluded_from_risk_allocation"] is True
    # total_portfolio_percent stays well-defined: 100000 / 110000 * 100
    assert Decimal(emergency_out["total_portfolio_percent"]) == Decimal("90.91")


async def test_portfolio_summary_returns_404_when_not_configured(client):
    response = await client.get("/api/portfolio/summary")
    assert response.status_code == 404
    assert "detail" in response.json()


async def test_portfolio_allocation_returns_404_when_not_configured(client):
    response = await client.get("/api/portfolio/allocation")
    assert response.status_code == 404


async def test_api_calls_do_not_mutate_database(db_session, client):
    config = PortfolioConfig(name="No Mutation Portfolio", base_currency="EGP", emergency_excluded=False)
    db_session.add(config)
    await db_session.flush()
    asset = make_asset("NOMUT")
    db_session.add(asset)
    await db_session.flush()
    db_session.add(Holding(asset_id=asset.id, quantity=Decimal("1"), current_price=Decimal("42")))
    await db_session.commit()

    from sqlalchemy import func, select

    from app.models import Holding as HoldingModel

    async def holding_count():
        result = await db_session.execute(select(func.count()).select_from(HoldingModel))
        return result.scalar_one()

    before = await holding_count()
    await client.get("/api/portfolio/summary")
    await client.get("/api/portfolio/allocation")
    after = await holding_count()

    assert before == after == 1
