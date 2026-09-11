"""Phase 18: Smart Recommendations service/API-level tests — real
portfolio state loaded from the database via the Phase 17 loader,
exercising Test J (no mutation + deterministic repeated request against
the real HTTP endpoint)."""

from datetime import datetime, timezone
from decimal import Decimal

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.core.database import get_db_session
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
from app.services.rebalancing_service import RebalancingNotConfiguredError
from app.services.recommendation_service import get_portfolio_recommendations
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
    """Same shape as test_rebalancing_service.py's fixture: an emergency
    SAVINGS asset (excluded, never touched), a real non-emergency CASH
    asset (contributes to `available_cash`), and one underweight Growth
    (STOCK) bucket with a target -- so a real BUY recommendation is
    always present to check no-mutation/determinism against."""
    config = make_portfolio_config(emergency_excluded=True)
    session.add(config)
    await session.flush()

    emergency_bucket = StrategyBucket(portfolio_config_id=config.id, name="Emergency Reserve")
    session.add(emergency_bucket)
    await session.flush()
    emergency_asset = make_asset("RECEMERG", asset_type=AssetType.SAVINGS, strategy_bucket_id=emergency_bucket.id)
    session.add(emergency_asset)
    await session.flush()
    config.emergency_asset_id = emergency_asset.id
    session.add(Holding(asset_id=emergency_asset.id, quantity=Decimal("1")))
    await make_current_price(session, emergency_asset, Decimal("100000"))

    cash_bucket = StrategyBucket(portfolio_config_id=config.id, name="Free Cash")
    session.add(cash_bucket)
    await session.flush()
    cash_asset = make_asset("RECCASH", asset_type=AssetType.CASH, strategy_bucket_id=cash_bucket.id)
    session.add(cash_asset)
    await session.commit()

    growth_bucket = StrategyBucket(portfolio_config_id=config.id, name="Growth")
    session.add(growth_bucket)
    await session.flush()
    growth_asset = make_asset("RECGROWTH", strategy_bucket_id=growth_bucket.id)
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


async def test_not_configured_raises(db_session):
    with pytest.raises(RebalancingNotConfiguredError):
        await get_portfolio_recommendations(db_session)


async def test_recommendations_use_the_same_amount_as_rebalancing(db_session):
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

    result = await get_portfolio_recommendations(db_session)
    growth_rec = next(r for r in result.recommendations if r.target_category == "Growth")
    assert growth_rec.type == "CASH_DEPLOYMENT"
    assert growth_rec.suggested_action == "BUY"
    # investable = 1000 (growth) + 2000 (free cash) = 3000; target 50% = 1500; gap = 500.
    assert growth_rec.amount == Decimal("500.00")

    # Emergency Reserve must never appear as a target of any recommendation.
    assert all(r.target_category != "Emergency Reserve" for r in result.recommendations)


async def test_j_calling_the_endpoint_never_mutates_financial_state_and_is_deterministic(db_session, client):
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

    response = await client.get("/api/portfolio/recommendations")
    assert response.status_code == 200
    body = response.json()
    assert any(r["suggested_action"] == "BUY" for r in body["recommendations"])

    after = await _counts()
    assert before == after

    # Calling it twice in a row must be exactly as safe and deterministic
    # -- including the `id` field, which must never be a random UUID.
    response_2 = await client.get("/api/portfolio/recommendations")
    body_2 = response_2.json()
    assert [r["id"] for r in body["recommendations"]] == [r["id"] for r in body_2["recommendations"]]
    assert [r["amount"] for r in body["recommendations"]] == [r["amount"] for r in body_2["recommendations"]]
    assert [r["type"] for r in body["recommendations"]] == [r["type"] for r in body_2["recommendations"]]
