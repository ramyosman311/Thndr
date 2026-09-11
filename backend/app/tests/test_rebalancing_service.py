"""Phase 17: Smart Rebalancing service/API-level tests — real portfolio
state loaded from the database, exercising `available_cash` (Phase 16)
as the actual BUY funding source, and Test L (no mutation)."""

from datetime import datetime, timezone
from decimal import Decimal

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.core.database import get_db_session
from app.domain.rebalancing_engine import RebalancingAction
from app.main import app
from app.models import (
    AllocationTarget,
    AssetType,
    Holding,
    PortfolioConfig,
    StrategyBucket,
    Transaction,
)
from app.services import transaction_service
from app.services.rebalancing_service import RebalancingNotConfiguredError, get_rebalancing_recommendations
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


async def _setup_portfolio(session):
    """Emergency SAVINGS asset (excluded, never touched); a real
    non-emergency CASH asset (contributes to `available_cash`); one
    underweight Growth (STOCK) bucket with a target."""
    config = make_portfolio_config(emergency_excluded=True)
    session.add(config)
    await session.flush()

    emergency_bucket = StrategyBucket(portfolio_config_id=config.id, name="Emergency Reserve")
    session.add(emergency_bucket)
    await session.flush()
    emergency_asset = make_asset("REBEMERG", asset_type=AssetType.SAVINGS, strategy_bucket_id=emergency_bucket.id)
    session.add(emergency_asset)
    await session.flush()
    config.emergency_asset_id = emergency_asset.id
    session.add(Holding(asset_id=emergency_asset.id, quantity=Decimal("1")))
    await make_current_price(session, emergency_asset, Decimal("100000"))

    cash_bucket = StrategyBucket(portfolio_config_id=config.id, name="Free Cash")
    session.add(cash_bucket)
    await session.flush()
    cash_asset = make_asset("REBCASH", asset_type=AssetType.CASH, strategy_bucket_id=cash_bucket.id)
    session.add(cash_asset)
    await session.commit()

    growth_bucket = StrategyBucket(portfolio_config_id=config.id, name="Growth")
    session.add(growth_bucket)
    await session.flush()
    growth_asset = make_asset("REBGROWTH", strategy_bucket_id=growth_bucket.id)
    session.add(growth_asset)
    await session.flush()
    session.add(Holding(asset_id=growth_asset.id, quantity=Decimal("10")))  # 1000
    await make_current_price(session, growth_asset, Decimal("100"))
    growth_target = AllocationTarget(
        portfolio_config_id=config.id, strategy_bucket_id=growth_bucket.id, target_percent=Decimal("50"), priority=1
    )
    session.add(growth_target)
    await session.commit()

    return config, cash_asset, growth_asset


async def test_available_cash_funds_an_underweight_buy_recommendation(db_session):
    config, cash_asset, growth_asset = await _setup_portfolio(db_session)

    # Deposit real, non-emergency free cash via the existing Phase 15
    # DEPOSIT path -- this is what actually populates Phase 16's
    # `available_cash`, not a plain Holding row.
    await transaction_service.create_transaction(
        db_session,
        asset_id=cash_asset.id,
        transaction_type="DEPOSIT",
        quantity=Decimal("2000"),
        price=Decimal("1"),
        fees=Decimal("0"),
        transaction_date=datetime.now(timezone.utc),
        notes=None,
    )

    result = await get_rebalancing_recommendations(db_session)

    assert result.available_cash == Decimal("2000.00")
    growth_rec = next(r for r in result.recommendations if r.bucket_name == "Growth")
    # investable = 1000 (growth) + 2000 (free cash) = 3000; target 50% = 1500; gap = 500.
    assert growth_rec.action == "BUY"
    assert growth_rec.recommended_value == Decimal("500.00")
    assert result.total_recommended_buy == Decimal("500.00")

    emergency_rec = next(r for r in result.recommendations if r.bucket_name == "Emergency Reserve")
    assert emergency_rec.action == "HOLD"
    assert emergency_rec.recommended_value is None


async def test_not_configured_raises(db_session):
    with pytest.raises(RebalancingNotConfiguredError):
        await get_rebalancing_recommendations(db_session)


async def test_l_calling_the_endpoint_never_mutates_financial_state(db_session, client):
    config, cash_asset, growth_asset = await _setup_portfolio(db_session)
    await transaction_service.create_transaction(
        db_session,
        asset_id=cash_asset.id,
        transaction_type="DEPOSIT",
        quantity=Decimal("2000"),
        price=Decimal("1"),
        fees=Decimal("0"),
        transaction_date=datetime.now(timezone.utc),
        notes=None,
    )

    async def _counts():
        return {
            "transactions": (await db_session.execute(select(func.count()).select_from(Transaction))).scalar_one(),
            "holdings": (await db_session.execute(select(func.count()).select_from(Holding))).scalar_one(),
            "allocation_targets": (
                await db_session.execute(select(func.count()).select_from(AllocationTarget))
            ).scalar_one(),
            "strategy_buckets": (
                await db_session.execute(select(func.count()).select_from(StrategyBucket))
            ).scalar_one(),
            "portfolio_configs": (
                await db_session.execute(select(func.count()).select_from(PortfolioConfig))
            ).scalar_one(),
        }

    before = await _counts()

    response = await client.get("/api/portfolio/rebalancing")
    assert response.status_code == 200
    body = response.json()
    assert any(r["action"] == "BUY" for r in body["recommendations"])

    after = await _counts()
    assert before == after

    # Calling it twice in a row must be exactly as safe and deterministic.
    response_2 = await client.get("/api/portfolio/rebalancing")
    assert response_2.json() == body


async def test_reduce_action_never_exceeds_actual_held_value_end_to_end(db_session):
    config = make_portfolio_config(emergency_excluded=False)
    db_session.add(config)
    await db_session.flush()

    bucket = StrategyBucket(portfolio_config_id=config.id, name="Overweight Stocks")
    db_session.add(bucket)
    await db_session.flush()
    asset = make_asset("REBOVER", strategy_bucket_id=bucket.id)
    db_session.add(asset)
    await db_session.flush()
    db_session.add(Holding(asset_id=asset.id, quantity=Decimal("100")))  # 10000
    await make_current_price(db_session, asset, Decimal("100"))
    target = AllocationTarget(
        portfolio_config_id=config.id, strategy_bucket_id=bucket.id, maximum_percent=Decimal("15"), priority=1
    )
    db_session.add(target)
    await db_session.commit()

    result = await get_rebalancing_recommendations(db_session)
    rec = next(r for r in result.recommendations if r.bucket_name == "Overweight Stocks")
    assert rec.action == RebalancingAction.REDUCE.value
    assert rec.recommended_value is not None
    assert rec.recommended_value <= rec.actual_value
    assert rec.recommended_value == Decimal("8500.00")  # 10000 - (15% of 10000)
