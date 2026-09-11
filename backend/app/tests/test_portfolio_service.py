from decimal import Decimal

from sqlalchemy import func, select

from app.domain.allocation_engine import TargetStatus
from app.models import (
    AllocationTarget,
    AssetType,
    Holding,
    PortfolioConfig,
    StrategyBucket,
    Transaction,
)
from app.models import Asset as AssetModel
from app.services.portfolio_service import (
    PortfolioNotConfiguredError,
    get_portfolio_allocation,
    get_portfolio_summary,
)
from app.tests.conftest import make_asset, make_current_price


async def _setup_portfolio(session, *, emergency_excluded=True):
    config = PortfolioConfig(name="Svc Test Portfolio", base_currency="EGP", emergency_excluded=emergency_excluded)
    session.add(config)
    await session.flush()

    emergency_asset = make_asset("EMERG", asset_type=AssetType.SAVINGS)
    session.add(emergency_asset)
    await session.flush()
    config.emergency_asset_id = emergency_asset.id
    session.add(Holding(asset_id=emergency_asset.id, quantity=Decimal("1")))
    await make_current_price(session, emergency_asset, Decimal("100000"))

    stock_bucket = StrategyBucket(portfolio_config_id=config.id, name="Stocks")
    session.add(stock_bucket)
    await session.flush()

    stock_asset = make_asset("STK1", strategy_bucket_id=stock_bucket.id)
    session.add(stock_asset)
    await session.flush()
    session.add(Holding(asset_id=stock_asset.id, quantity=Decimal("100")))  # 10000
    await make_current_price(session, stock_asset, Decimal("100"))

    await session.commit()
    return config, stock_bucket, emergency_asset, stock_asset


async def test_emergency_exclusion_uses_investable_denominator(db_session):
    await _setup_portfolio(db_session, emergency_excluded=True)

    summary = await get_portfolio_summary(db_session)
    assert summary.emergency_value == Decimal("100000.00")
    assert summary.investable_value == Decimal("10000.00")
    assert summary.denominator_value == Decimal("10000.00")
    assert summary.denominator_basis == "investable"


async def test_emergency_inclusion_uses_total_denominator(db_session):
    await _setup_portfolio(db_session, emergency_excluded=False)

    summary = await get_portfolio_summary(db_session)
    assert summary.denominator_value == Decimal("110000.00")
    assert summary.denominator_basis == "total"


async def test_dynamic_asset_is_automatically_included_without_code_change(db_session):
    config, stock_bucket, _, _ = await _setup_portfolio(db_session)

    new_asset = make_asset("NEWASSET", strategy_bucket_id=stock_bucket.id)
    db_session.add(new_asset)
    await db_session.flush()
    db_session.add(Holding(asset_id=new_asset.id, quantity=Decimal("10")))  # 500
    await make_current_price(db_session, new_asset, Decimal("50"))
    await db_session.commit()

    summary = await get_portfolio_summary(db_session)
    # 10000 (existing stock) + 500 (new asset) = 10500 investable
    assert summary.investable_value == Decimal("10500.00")


async def test_dynamic_strategy_bucket_is_automatically_recognized_without_code_change(db_session):
    config, _, _, _ = await _setup_portfolio(db_session)

    new_bucket = StrategyBucket(portfolio_config_id=config.id, name="Brand New Category")
    db_session.add(new_bucket)
    await db_session.flush()
    new_asset = make_asset("NEWCAT", strategy_bucket_id=new_bucket.id)
    db_session.add(new_asset)
    await db_session.flush()
    db_session.add(Holding(asset_id=new_asset.id, quantity=Decimal("1")))
    await make_current_price(db_session, new_asset, Decimal("1000"))
    await db_session.commit()

    allocation = await get_portfolio_allocation(db_session)
    bucket_names = {b.bucket_name for b in allocation.buckets}
    assert "Brand New Category" in bucket_names

    new_bucket_alloc = next(b for b in allocation.buckets if b.bucket_name == "Brand New Category")
    assert new_bucket_alloc.target_status == TargetStatus.NO_TARGET.value
    assert new_bucket_alloc.actual_value == Decimal("1000.00")


async def test_allocation_rule_changes_are_reflected_without_code_change(db_session):
    config, stock_bucket, _, stock_asset = await _setup_portfolio(db_session, emergency_excluded=False)

    target = AllocationTarget(
        portfolio_config_id=config.id,
        strategy_bucket_id=stock_bucket.id,
        maximum_percent=Decimal("5"),
        allow_new_buy=True,
    )
    db_session.add(target)
    await db_session.commit()

    allocation = await get_portfolio_allocation(db_session)
    stocks_alloc = next(b for b in allocation.buckets if b.bucket_name == "Stocks")
    assert stocks_alloc.maximum_status == "MAXIMUM_BREACHED"
    assert stocks_alloc.buy_allowed is False

    # Flip allow_new_buy in the DB only — no code change — and confirm the
    # engine still freezes buying because the maximum is what matters once
    # breached (the flag alone cannot override a breached maximum).
    target.allow_new_buy = False
    await db_session.commit()
    allocation_after = await get_portfolio_allocation(db_session)
    stocks_alloc_after = next(b for b in allocation_after.buckets if b.bucket_name == "Stocks")
    assert stocks_alloc_after.allow_new_buy is False
    assert stocks_alloc_after.buy_allowed is False


async def test_missing_portfolio_configuration_raises_explicit_error(db_session):
    try:
        await get_portfolio_summary(db_session)
        assert False, "expected PortfolioNotConfiguredError"
    except PortfolioNotConfiguredError:
        pass


async def test_portfolio_engine_has_no_side_effects(db_session):
    await _setup_portfolio(db_session)

    async def count_all():
        counts = {}
        for model in (AssetModel, Holding, AllocationTarget, StrategyBucket, PortfolioConfig, Transaction):
            result = await db_session.execute(select(func.count()).select_from(model))
            counts[model.__name__] = result.scalar_one()
        return counts

    before = await count_all()
    await get_portfolio_summary(db_session)
    await get_portfolio_allocation(db_session)
    after = await count_all()

    assert before == after


# --- Phase 11: incomplete valuation is exposed, never fabricated as zero ----


async def test_summary_reports_incomplete_valuation_for_a_held_but_unpriced_asset(db_session):
    config = PortfolioConfig(name="Unpriced Test Portfolio", base_currency="EGP", emergency_excluded=False)
    db_session.add(config)
    await db_session.flush()

    priced = make_asset("PRICEDONE")
    db_session.add(priced)
    await db_session.flush()
    db_session.add(Holding(asset_id=priced.id, quantity=Decimal("10")))
    await make_current_price(db_session, priced, Decimal("100"))

    unpriced = make_asset("UNPRICEDONE")
    db_session.add(unpriced)
    await db_session.flush()
    db_session.add(Holding(asset_id=unpriced.id, quantity=Decimal("5")))  # held, but no price observation at all

    await db_session.commit()

    summary = await get_portfolio_summary(db_session)

    assert summary.is_complete is False
    assert unpriced.id in summary.unpriced_asset_ids
    # The priced asset's value (1000) is still reported -- the unpriced
    # one is excluded from the total, never treated as worth 0.
    assert summary.total_value == Decimal("1000.00")

    unpriced_pnl = next(h for h in summary.holdings_pnl if h.symbol == "UNPRICEDONE")
    assert unpriced_pnl.current_price is None
    assert unpriced_pnl.market_value is None
    # Phase 16: no live/stale price AND no average-cost fallback (this
    # holding's average_cost is the Holding model's default of 0, so no
    # safe fallback price exists) -- still genuinely unpriced, now
    # reported as PENDING_SYNC rather than the old, more granular
    # PRICE_UNAVAILABLE string (see services/portfolio_shared.py,
    # "resolve_valuation_price").
    assert unpriced_pnl.price_status == "PENDING_SYNC"


async def test_allocation_reports_complete_valuation_when_every_position_is_priced(db_session):
    config, *_ = await _setup_portfolio(db_session, emergency_excluded=False)
    allocation = await get_portfolio_allocation(db_session)
    assert allocation.is_complete is True
    assert allocation.unpriced_asset_ids == []
