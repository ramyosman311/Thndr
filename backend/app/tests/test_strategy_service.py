from decimal import Decimal

from sqlalchemy import func, select

from app.domain.strategy_validation import StrategyValidationStatus
from app.models import (
    AllocationTarget,
    AssetType,
    PortfolioConfig,
    StrategyBucket,
)
from app.seed.seed import run_seed
from app.services.strategy_service import PortfolioNotConfiguredError, get_strategy_validation
from app.tests.conftest import make_asset


async def _setup_two_bucket_portfolio(session, *, emergency_excluded=True):
    config = PortfolioConfig(name="Strategy Test Portfolio", base_currency="EGP", emergency_excluded=emergency_excluded)
    session.add(config)
    await session.flush()

    emergency_asset = make_asset("STRATEMERG", asset_type=AssetType.SAVINGS)
    session.add(emergency_asset)
    await session.flush()
    config.emergency_asset_id = emergency_asset.id

    emergency_bucket = StrategyBucket(portfolio_config_id=config.id, name="Emergency Cash")
    session.add(emergency_bucket)
    await session.flush()
    emergency_asset.strategy_bucket_id = emergency_bucket.id

    bucket_a = StrategyBucket(portfolio_config_id=config.id, name="Bucket A")
    session.add(bucket_a)
    await session.flush()
    target_a = AllocationTarget(
        portfolio_config_id=config.id, strategy_bucket_id=bucket_a.id, target_percent=Decimal("100"), priority=1
    )
    session.add(target_a)
    await session.commit()

    return config, bucket_a, emergency_bucket


async def test_current_seeded_configuration_returns_85_percent_incomplete(db_session):
    """Uses the real Phase 4 seed data (not a hand-built substitute) to
    verify the engine reports exactly what the Phase 6 approval demands:
    85% total, INCOMPLETE_TARGET_ALLOCATION — never silently rewritten."""
    await run_seed(db_session)

    result = await get_strategy_validation(db_session)

    assert result.status == StrategyValidationStatus.INCOMPLETE_TARGET_ALLOCATION.value
    assert result.total_target_percent == Decimal("85.00")
    assert result.is_valid is False
    max_only_names = {r.bucket_name for r in result.maximum_only_rows}
    assert max_only_names == {"Individual Stocks"}
    target_names = {r.bucket_name for r in result.target_rows}
    assert target_names == {"Growth / Investment Funds", "Defensive / Fixed Income", "Gold", "Free Cash"}
    # Emergency Cash has no allocation_targets row in the seed at all, so
    # it appears in neither list.
    assert "Emergency Cash" not in max_only_names
    assert "Emergency Cash" not in target_names


async def test_inactive_allocation_target_does_not_contribute(db_session):
    config, bucket_a, _ = await _setup_two_bucket_portfolio(db_session, emergency_excluded=False)

    bucket_b = StrategyBucket(portfolio_config_id=config.id, name="Bucket B")
    db_session.add(bucket_b)
    await db_session.flush()
    inactive_target = AllocationTarget(
        portfolio_config_id=config.id,
        strategy_bucket_id=bucket_b.id,
        target_percent=Decimal("50"),  # would push the total to 150 if it counted
        is_active=False,
    )
    db_session.add(inactive_target)
    await db_session.commit()

    result = await get_strategy_validation(db_session)
    assert result.total_target_percent == Decimal("100.00")
    assert result.status == StrategyValidationStatus.VALID.value


async def test_emergency_exclusion_changes_validation_dynamically(db_session):
    config, bucket_a, emergency_bucket = await _setup_two_bucket_portfolio(db_session, emergency_excluded=True)

    emergency_target = AllocationTarget(
        portfolio_config_id=config.id,
        strategy_bucket_id=emergency_bucket.id,
        target_percent=Decimal("50"),  # would push the total to 150 if it participated
    )
    db_session.add(emergency_target)
    await db_session.commit()

    excluded_result = await get_strategy_validation(db_session)
    assert excluded_result.total_target_percent == Decimal("100.00")
    assert excluded_result.status == StrategyValidationStatus.VALID.value
    assert any(r.bucket_name == "Emergency Cash" for r in excluded_result.excluded_emergency_rows)

    # Flip emergency_excluded in the DB only — no code change — and the
    # emergency bucket's rule must now participate.
    config.emergency_excluded = False
    await db_session.commit()

    included_result = await get_strategy_validation(db_session)
    assert included_result.total_target_percent == Decimal("150.00")
    assert included_result.status == StrategyValidationStatus.OVERALLOCATED_TARGET_ALLOCATION.value


async def test_dynamic_new_bucket_and_target_are_recognized_without_code_change(db_session):
    config, bucket_a, _ = await _setup_two_bucket_portfolio(db_session, emergency_excluded=False)

    new_bucket = StrategyBucket(portfolio_config_id=config.id, name="Freshly Created Category")
    db_session.add(new_bucket)
    await db_session.flush()
    db_session.add(
        AllocationTarget(
            portfolio_config_id=config.id,
            strategy_bucket_id=new_bucket.id,
            target_percent=Decimal("0"),
        )
    )
    await db_session.commit()

    result_after = await get_strategy_validation(db_session)
    assert "Freshly Created Category" in {r.bucket_name for r in result_after.target_rows}
    # bucket_a=100 + new bucket=0 => still 100, VALID
    assert result_after.total_target_percent == Decimal("100.00")
    assert result_after.status == StrategyValidationStatus.VALID.value


async def test_changing_maximum_percent_does_not_change_target_sum(db_session):
    config, bucket_a, _ = await _setup_two_bucket_portfolio(db_session, emergency_excluded=False)

    bucket_b = StrategyBucket(portfolio_config_id=config.id, name="Max Only Bucket")
    db_session.add(bucket_b)
    await db_session.flush()
    target_b = AllocationTarget(
        portfolio_config_id=config.id, strategy_bucket_id=bucket_b.id, maximum_percent=Decimal("15")
    )
    db_session.add(target_b)
    await db_session.commit()

    before = await get_strategy_validation(db_session)
    assert before.total_target_percent == Decimal("100.00")

    target_b.maximum_percent = Decimal("40")
    await db_session.commit()

    after = await get_strategy_validation(db_session)
    assert after.total_target_percent == Decimal("100.00")
    assert before.status == after.status == StrategyValidationStatus.VALID.value


async def test_changing_allow_new_buy_does_not_change_target_sum(db_session):
    config, bucket_a, _ = await _setup_two_bucket_portfolio(db_session, emergency_excluded=False)

    target_a = (
        await db_session.execute(
            select(AllocationTarget).where(AllocationTarget.strategy_bucket_id == bucket_a.id)
        )
    ).scalar_one()
    assert target_a.allow_new_buy is True

    before = await get_strategy_validation(db_session)
    target_a.allow_new_buy = False
    await db_session.commit()
    after = await get_strategy_validation(db_session)

    assert before.total_target_percent == after.total_target_percent == Decimal("100.00")


async def test_missing_portfolio_configuration_raises_explicit_error(db_session):
    try:
        await get_strategy_validation(db_session)
        assert False, "expected PortfolioNotConfiguredError"
    except PortfolioNotConfiguredError:
        pass


async def test_strategy_engine_has_no_side_effects(db_session):
    await run_seed(db_session)

    async def count_all():
        counts = {}
        for model in (AllocationTarget, StrategyBucket, PortfolioConfig):
            result = await db_session.execute(select(func.count()).select_from(model))
            counts[model.__name__] = result.scalar_one()
        return counts

    before = await count_all()
    await get_strategy_validation(db_session)
    await get_strategy_validation(db_session)
    after = await count_all()

    assert before == after
