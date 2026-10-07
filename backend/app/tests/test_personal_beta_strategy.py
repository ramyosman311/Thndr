"""Personal Beta strategy (owner-confirmed): seeded configuration values.

Growth 55% target, Defensive 25% target, Free Cash 0% target, Individual
Stocks 20% MAXIMUM with no target, Gold 0% target with new buys disabled,
Emergency Cash excluded from allocation. The explicit targets total 80% on
purpose and are never normalised to 100%.
"""

from decimal import Decimal

from sqlalchemy import func, select

from app.models import (
    AllocationTarget,
    Holding,
    PortfolioConfig,
    StrategyBucket,
    Transaction,
)
from app.seed.data import EMERGENCY_ASSET_SYMBOL, SEED_ALLOCATION_TARGETS
from app.seed.seed import run_seed
from app.services.strategy_service import get_strategy_validation


async def _targets(db_session):
    rows = (
        await db_session.execute(
            select(AllocationTarget, StrategyBucket.name).join(
                StrategyBucket, AllocationTarget.strategy_bucket_id == StrategyBucket.id
            )
        )
    ).all()
    return {name: target for target, name in rows}


async def test_seeded_strategy_values(db_session, owner):
    await run_seed(db_session, owner.id)
    t = await _targets(db_session)

    assert t["Growth / Investment Funds"].target_percent == Decimal("55")
    assert t["Defensive / Fixed Income"].target_percent == Decimal("25")
    assert t["Free Cash"].target_percent == Decimal("0")

    stocks = t["Individual Stocks"]
    assert stocks.target_percent is None
    assert stocks.maximum_percent == Decimal("20")

    gold = t["Gold"]
    assert gold.target_percent == Decimal("0")
    assert gold.allow_new_buy is False


async def test_target_maximum_and_allow_new_buy_stay_independent(db_session, owner):
    await run_seed(db_session, owner.id)
    t = await _targets(db_session)
    # Target != Maximum != Allow New Buy: a maximum never becomes a target,
    # a zero target is not "no new buy", and new buys stay allowed elsewhere.
    assert t["Individual Stocks"].target_percent is None and t["Individual Stocks"].allow_new_buy is True
    assert t["Gold"].target_percent == Decimal("0") and t["Gold"].allow_new_buy is False
    assert t["Free Cash"].target_percent == Decimal("0") and t["Free Cash"].allow_new_buy is True
    for name, spec in SEED_ALLOCATION_TARGETS.items():
        assert t[name].maximum_percent == spec["maximum_percent"]


async def test_emergency_cash_excluded_and_configuration_based(db_session, owner):
    await run_seed(db_session, owner.id)
    t = await _targets(db_session)
    assert "Emergency Cash" not in t  # no allocation rule at all

    config = (await db_session.execute(select(PortfolioConfig))).scalar_one()
    assert config.emergency_excluded is True
    assert config.emergency_asset_id is not None  # wired by foreign key, not by symbol in app code
    assert EMERGENCY_ASSET_SYMBOL == "CLOUDZ"


async def test_explicit_targets_total_80_and_are_not_normalised(db_session, owner):
    await run_seed(db_session, owner.id)

    result = await get_strategy_validation(db_session, owner.id)

    assert result.total_target_percent == Decimal("80.00")
    assert result.status == "INCOMPLETE_TARGET_ALLOCATION"
    assert result.is_valid is False
    # nothing rewrote the stored values to make them sum to 100
    t = await _targets(db_session)
    total = sum((x.target_percent or Decimal("0")) for x in t.values())
    assert total == Decimal("80")
    assert t["Growth / Investment Funds"].target_percent == Decimal("55")


async def test_seed_creates_no_financial_data(db_session, owner):
    await run_seed(db_session, owner.id)
    for model in (Holding, Transaction):
        assert (await db_session.execute(select(func.count()).select_from(model))).scalar_one() == 0
