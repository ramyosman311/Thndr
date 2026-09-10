from decimal import Decimal

from sqlalchemy import func, select

from app.domain.inflow_allocator import InflowStatus
from app.domain.strategy_validation import StrategyValidationStatus
from app.models import (
    AllocationTarget,
    Asset,
    AssetType,
    Holding,
    PortfolioConfig,
    StrategyBucket,
    Transaction,
)
from app.seed.seed import run_seed
from app.services.inflow_service import PortfolioNotConfiguredError, get_inflow_allocation
from app.services.strategy_service import get_strategy_validation
from app.tests.conftest import make_asset, make_current_price


async def _setup_portfolio(session, *, emergency_excluded=True):
    config = PortfolioConfig(name="Inflow Test Portfolio", base_currency="EGP", emergency_excluded=emergency_excluded)
    session.add(config)
    await session.flush()

    emergency_asset = make_asset("INEMERG", asset_type=AssetType.SAVINGS)
    session.add(emergency_asset)
    await session.flush()
    config.emergency_asset_id = emergency_asset.id

    emergency_bucket = StrategyBucket(portfolio_config_id=config.id, name="Emergency Cash")
    session.add(emergency_bucket)
    await session.flush()
    emergency_asset.strategy_bucket_id = emergency_bucket.id
    session.add(Holding(asset_id=emergency_asset.id, quantity=Decimal("1")))
    await make_current_price(session, emergency_asset, Decimal("100000"))

    growth_bucket = StrategyBucket(portfolio_config_id=config.id, name="Growth")
    session.add(growth_bucket)
    await session.flush()
    growth_asset = make_asset("INGROWTH", strategy_bucket_id=growth_bucket.id)
    session.add(growth_asset)
    await session.flush()
    session.add(Holding(asset_id=growth_asset.id, quantity=Decimal("40")))  # 4000
    await make_current_price(session, growth_asset, Decimal("100"))
    growth_target = AllocationTarget(
        portfolio_config_id=config.id, strategy_bucket_id=growth_bucket.id, target_percent=Decimal("55"), priority=1
    )
    session.add(growth_target)

    defensive_bucket = StrategyBucket(portfolio_config_id=config.id, name="Defensive")
    session.add(defensive_bucket)
    await session.flush()
    defensive_asset = make_asset("INDEFENSE", strategy_bucket_id=defensive_bucket.id)
    session.add(defensive_asset)
    await session.flush()
    session.add(Holding(asset_id=defensive_asset.id, quantity=Decimal("10")))  # 1000
    await make_current_price(session, defensive_asset, Decimal("100"))
    defensive_target = AllocationTarget(
        portfolio_config_id=config.id, strategy_bucket_id=defensive_bucket.id, target_percent=Decimal("25"), priority=2
    )
    session.add(defensive_target)

    await session.commit()
    return config, growth_bucket, defensive_bucket, emergency_bucket, growth_target, defensive_target


async def test_emergency_exclusion_never_receives_inflow(db_session):
    """I. investable value = 4000 + 1000 = 5000 (emergency's 100000 is
    excluded from the denominator entirely)."""
    await _setup_portfolio(db_session, emergency_excluded=True)

    result = await get_inflow_allocation(db_session, Decimal("100"))

    emergency_rec = next(r for r in result.recommendations if r.bucket_name == "Emergency Cash")
    assert emergency_rec.allocated_amount == Decimal("0.00")
    assert emergency_rec.status == InflowStatus.EMERGENCY_EXCLUDED.value
    assert emergency_rec.current_percent is None

    growth_rec = next(r for r in result.recommendations if r.bucket_name == "Growth")
    # target_value = 55% of 5000 = 2750; current 4000 already exceeds it.
    assert growth_rec.status == InflowStatus.OVER_TARGET.value
    assert growth_rec.allocated_amount == Decimal("0.00")


async def test_emergency_toggle_changes_behavior_dynamically(db_session):
    """J. Flipping emergency_excluded in the DB changes the investable
    denominator used for target-gap math, with no code change."""
    config, growth_bucket, defensive_bucket, emergency_bucket, *_ = await _setup_portfolio(
        db_session, emergency_excluded=True
    )

    excluded_result = await get_inflow_allocation(db_session, Decimal("100"))
    growth_excluded = next(r for r in excluded_result.recommendations if r.bucket_name == "Growth")
    # investable = 5000, target 55% = 2750, current 4000 -> OVER_TARGET
    assert growth_excluded.status == InflowStatus.OVER_TARGET.value

    config.emergency_excluded = False
    await db_session.commit()

    included_result = await get_inflow_allocation(db_session, Decimal("100"))
    growth_included = next(r for r in included_result.recommendations if r.bucket_name == "Growth")
    # investable = 105000 (total, emergency now included), target 55% = 57750, current 4000 -> huge gap
    assert growth_included.status == InflowStatus.ELIGIBLE
    assert growth_included.allocated_amount == Decimal("100.00")


async def test_seeded_85_percent_strategy_reported_and_not_invented(db_session):
    """K. Uses the real Phase 4 seed. strategy_status must be
    INCOMPLETE_TARGET_ALLOCATION, and Individual Stocks (maximum-only)
    must never receive a share of the inflow even though it's the
    "missing" 15%.

    The seed itself leaves all holdings empty (Phase 4 approval,
    "Holdings"), so a small holding is added here to give the portfolio a
    nonzero investable value — otherwise every bucket would report
    NO_CAPACITY rather than exercising the specific behaviors under test.
    """
    await run_seed(db_session)

    tmgh = (await db_session.execute(select(Asset).where(Asset.symbol == "TMGH"))).scalar_one()
    db_session.add(Holding(asset_id=tmgh.id, quantity=Decimal("10")))  # value 1000
    await make_current_price(db_session, tmgh, Decimal("100"))
    await db_session.commit()

    result = await get_inflow_allocation(db_session, Decimal("1000"))

    assert result.strategy_status == StrategyValidationStatus.INCOMPLETE_TARGET_ALLOCATION.value
    assert result.strategy_is_valid is False

    stocks_rec = next(r for r in result.recommendations if r.bucket_name == "Individual Stocks")
    assert stocks_rec.allocated_amount == Decimal("0.00")
    assert stocks_rec.status == InflowStatus.NO_TARGET.value
    assert stocks_rec.current_value == Decimal("1000.00")  # TMGH's value still visible, just not a destination

    gold_rec = next(r for r in result.recommendations if r.bucket_name == "Gold")
    assert gold_rec.allocated_amount == Decimal("0.00")
    assert gold_rec.status == InflowStatus.BUY_DISABLED.value

    emergency_rec = next(r for r in result.recommendations if r.bucket_name == "Emergency Cash")
    assert emergency_rec.allocated_amount == Decimal("0.00")
    assert emergency_rec.status == InflowStatus.EMERGENCY_EXCLUDED.value

    # BWA (Growth / Investment Funds) has no holdings, so its gap is the
    # full 55% of the 1000 investable value = 550, and it has top priority.
    growth_rec = next(r for r in result.recommendations if r.bucket_name == "Growth / Investment Funds")
    assert growth_rec.target_gap == Decimal("550.00")
    assert growth_rec.allocated_amount == Decimal("550.00")
    assert growth_rec.status == InflowStatus.ELIGIBLE.value


async def test_strategy_engine_is_reused_not_duplicated(db_session):
    """T. The strategy_status reported by the inflow allocator must match
    the Strategy Engine's own validation for the identical DB state —
    proving it's the same computation, not a re-implementation."""
    await run_seed(db_session)

    inflow_result = await get_inflow_allocation(db_session, Decimal("500"))
    strategy_result = await get_strategy_validation(db_session)

    assert inflow_result.strategy_status == strategy_result.status
    assert inflow_result.strategy_is_valid == strategy_result.is_valid


async def test_dynamic_asset_and_target_recognized_without_code_change(db_session):
    """P + Q. Adding a brand-new asset/bucket/target, and changing an
    existing target's percent, both take effect with no code change."""
    config, growth_bucket, defensive_bucket, *_ = await _setup_portfolio(db_session, emergency_excluded=False)

    new_bucket = StrategyBucket(portfolio_config_id=config.id, name="Freshly Added")
    db_session.add(new_bucket)
    await db_session.flush()
    new_asset = make_asset("INNEW", strategy_bucket_id=new_bucket.id)
    db_session.add(new_asset)
    await db_session.flush()
    db_session.add(Holding(asset_id=new_asset.id, quantity=Decimal("0"), current_price=Decimal("0")))
    db_session.add(
        AllocationTarget(
            portfolio_config_id=config.id, strategy_bucket_id=new_bucket.id, target_percent=Decimal("10"), priority=5
        )
    )
    await db_session.commit()

    result = await get_inflow_allocation(db_session, Decimal("10"))
    new_rec = next(r for r in result.recommendations if r.bucket_name == "Freshly Added")
    assert new_rec.target_gap is not None  # engine recognized the dynamic bucket/target automatically

    # Q: change an existing target's percent and confirm the gap changes.
    target = (
        await db_session.execute(
            select(AllocationTarget).where(AllocationTarget.strategy_bucket_id == growth_bucket.id)
        )
    ).scalar_one()
    before_gap = next(r for r in result.recommendations if r.bucket_name == "Growth").target_gap
    target.target_percent = Decimal("10")
    await db_session.commit()
    after_result = await get_inflow_allocation(db_session, Decimal("10"))
    after_gap = next(r for r in after_result.recommendations if r.bucket_name == "Growth").target_gap
    assert after_gap != before_gap


async def test_dynamic_allow_new_buy_toggle_changes_result(db_session):
    """R."""
    config, growth_bucket, *_ = await _setup_portfolio(db_session, emergency_excluded=False)

    before = await get_inflow_allocation(db_session, Decimal("50"))
    growth_before = next(r for r in before.recommendations if r.bucket_name == "Growth")
    assert growth_before.allocated_amount == Decimal("50.00")

    target = (
        await db_session.execute(
            select(AllocationTarget).where(AllocationTarget.strategy_bucket_id == growth_bucket.id)
        )
    ).scalar_one()
    target.allow_new_buy = False
    await db_session.commit()

    after = await get_inflow_allocation(db_session, Decimal("50"))
    growth_after = next(r for r in after.recommendations if r.bucket_name == "Growth")
    assert growth_after.allocated_amount == Decimal("0.00")
    assert growth_after.status == InflowStatus.BUY_DISABLED.value


async def test_missing_portfolio_configuration_raises_explicit_error(db_session):
    try:
        await get_inflow_allocation(db_session, Decimal("100"))
        assert False, "expected PortfolioNotConfiguredError"
    except PortfolioNotConfiguredError:
        pass


async def test_zero_amount_is_rejected_at_service_layer(db_session):
    await _setup_portfolio(db_session, emergency_excluded=False)
    try:
        await get_inflow_allocation(db_session, Decimal("0"))
        assert False, "expected ValueError"
    except ValueError:
        pass


async def test_inflow_allocator_has_no_side_effects(db_session):
    """O. Calling the allocator repeatedly must never write to the DB."""
    await run_seed(db_session)

    async def counts():
        result = {}
        for model in (Asset, Holding, AllocationTarget, StrategyBucket, PortfolioConfig, Transaction):
            r = await db_session.execute(select(func.count()).select_from(model))
            result[model.__name__] = r.scalar_one()
        return result

    before = await counts()
    await get_inflow_allocation(db_session, Decimal("1000"))
    await get_inflow_allocation(db_session, Decimal("5000"))
    after = await counts()

    assert before == after
