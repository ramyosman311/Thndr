from decimal import Decimal

from sqlalchemy import func, select

from app.models import (
    AllocationTarget,
    Asset,
    AssetPriceConfig,
    PortfolioConfig,
    PortfolioSnapshot,
    PortfolioSnapshotItem,
    StrategyBucket,
    Transaction,
)
from app.models.enums import AssetType
from app.seed.data import (
    PORTFOLIO_CONFIG_NAME,
    SEED_ALLOCATION_TARGETS,
    SEED_ASSET_PRICE_CONFIGS,
    SEED_ASSETS,
    SEED_SNAPSHOTS,
    SEED_STRATEGY_BUCKETS,
)
from app.seed.seed import run_seed


async def _count(session, model) -> int:
    result = await session.execute(select(func.count()).select_from(model))
    return result.scalar_one()


async def test_seed_creates_expected_assets(db_session):
    await run_seed(db_session)

    assert await _count(db_session, Asset) == len(SEED_ASSETS)
    result = await db_session.execute(select(Asset.symbol))
    symbols = {row[0] for row in result.all()}
    assert symbols == {spec["symbol"] for spec in SEED_ASSETS}


async def test_seed_creates_expected_strategy_buckets(db_session):
    await run_seed(db_session)

    assert await _count(db_session, StrategyBucket) == len(SEED_STRATEGY_BUCKETS)
    result = await db_session.execute(select(StrategyBucket.name))
    names = {row[0] for row in result.all()}
    assert names == set(SEED_STRATEGY_BUCKETS.keys())


async def test_seed_creates_expected_portfolio_configuration(db_session):
    await run_seed(db_session)

    assert await _count(db_session, PortfolioConfig) == 1
    result = await db_session.execute(select(PortfolioConfig))
    config = result.scalar_one()
    assert config.name == PORTFOLIO_CONFIG_NAME
    assert config.base_currency == "EGP"


async def test_seed_configures_cloudz_as_emergency_asset_and_excludes_it(db_session):
    await run_seed(db_session)

    result = await db_session.execute(select(PortfolioConfig))
    config = result.scalar_one()
    await db_session.refresh(config, attribute_names=["emergency_asset"])

    assert config.emergency_asset is not None
    assert config.emergency_asset.symbol == "CLOUDZ"
    assert config.emergency_excluded is True


async def test_seed_allocation_targets_persist_independently(db_session):
    await run_seed(db_session)

    result = await db_session.execute(
        select(AllocationTarget, StrategyBucket.name)
        .join(StrategyBucket, AllocationTarget.strategy_bucket_id == StrategyBucket.id)
    )
    targets_by_bucket = {name: target for target, name in result.all()}

    assert set(targets_by_bucket.keys()) == set(SEED_ALLOCATION_TARGETS.keys())

    growth = targets_by_bucket["Growth / Investment Funds"]
    assert growth.target_percent == Decimal("55.00")
    assert growth.allow_new_buy is True

    defensive = targets_by_bucket["Defensive / Fixed Income"]
    assert defensive.target_percent == Decimal("25.00")

    free_cash = targets_by_bucket["Free Cash"]
    assert free_cash.target_percent == Decimal("5.00")

    # "Emergency Cash" bucket has no allocation rule: excluded from
    # allocation math entirely via portfolio_configs, not given a weight.
    assert "Emergency Cash" not in targets_by_bucket


async def test_seed_individual_stocks_maximum_is_not_a_target(db_session):
    await run_seed(db_session)

    result = await db_session.execute(
        select(AllocationTarget)
        .join(StrategyBucket, AllocationTarget.strategy_bucket_id == StrategyBucket.id)
        .where(StrategyBucket.name == "Individual Stocks")
    )
    target = result.scalar_one()

    assert target.target_percent is None
    assert target.maximum_percent == Decimal("15.00")


async def test_seed_gold_new_buy_target_is_zero_and_disabled(db_session):
    await run_seed(db_session)

    result = await db_session.execute(
        select(AllocationTarget)
        .join(StrategyBucket, AllocationTarget.strategy_bucket_id == StrategyBucket.id)
        .where(StrategyBucket.name == "Gold")
    )
    target = result.scalar_one()

    assert target.target_percent == Decimal("0.00")
    assert target.allow_new_buy is False


async def test_seed_assigns_assets_to_correct_buckets(db_session):
    await run_seed(db_session)

    result = await db_session.execute(
        select(Asset.symbol, StrategyBucket.name)
        .join(StrategyBucket, Asset.strategy_bucket_id == StrategyBucket.id)
    )
    bucket_by_symbol = dict(result.all())

    assert bucket_by_symbol["CLOUDZ"] == "Emergency Cash"
    assert bucket_by_symbol["BWA"] == "Growth / Investment Funds"
    assert bucket_by_symbol["AZN"] == "Defensive / Fixed Income"
    assert bucket_by_symbol["GOLD"] == "Gold"
    for symbol in ("TMGH", "ETEL", "EFID"):
        assert bucket_by_symbol[symbol] == "Individual Stocks"


async def test_seed_creates_five_snapshots_with_seven_items_each(db_session):
    await run_seed(db_session)

    assert await _count(db_session, PortfolioSnapshot) == 5

    result = await db_session.execute(select(PortfolioSnapshot.id))
    for (snapshot_id,) in result.all():
        item_count = await db_session.execute(
            select(func.count()).select_from(PortfolioSnapshotItem).where(
                PortfolioSnapshotItem.snapshot_id == snapshot_id
            )
        )
        assert item_count.scalar_one() == 7


async def test_seed_snapshot_values_match_exactly(db_session):
    await run_seed(db_session)

    first_seed_snapshot = SEED_SNAPSHOTS[0]
    result = await db_session.execute(
        select(PortfolioSnapshot).where(PortfolioSnapshot.snapshot_at == first_seed_snapshot["snapshot_at"])
    )
    snapshot = result.scalar_one()

    items_result = await db_session.execute(
        select(Asset.symbol, PortfolioSnapshotItem.value)
        .join(Asset, PortfolioSnapshotItem.asset_id == Asset.id)
        .where(PortfolioSnapshotItem.snapshot_id == snapshot.id)
    )
    values_by_symbol = dict(items_result.all())

    for symbol, expected_value in first_seed_snapshot["values"].items():
        assert values_by_symbol[symbol] == expected_value


async def test_seed_creates_no_transactions(db_session):
    await run_seed(db_session)

    assert await _count(db_session, Transaction) == 0


async def test_seed_is_idempotent_when_run_twice(db_session):
    await run_seed(db_session)
    await run_seed(db_session)

    assert await _count(db_session, Asset) == len(SEED_ASSETS)
    assert await _count(db_session, StrategyBucket) == len(SEED_STRATEGY_BUCKETS)
    assert await _count(db_session, PortfolioConfig) == 1
    assert await _count(db_session, AllocationTarget) == len(SEED_ALLOCATION_TARGETS)
    assert await _count(db_session, PortfolioSnapshot) == 5
    assert await _count(db_session, PortfolioSnapshotItem) == 5 * 7
    assert await _count(db_session, AssetPriceConfig) == len(SEED_ASSET_PRICE_CONFIGS)


# --- Phase 13: EGX price configuration seeding ----------------------------


async def test_seed_creates_price_configs_only_for_egx_equities(db_session):
    """Only TMGH/ETEL/EFID (asset_type=STOCK, market="EGX") get a seeded
    price config -- see SEED_ASSET_PRICE_CONFIGS's own comment for why
    BWA/AZN (FUND-type, not exchange-traded equities) are excluded."""
    await run_seed(db_session)

    assert set(SEED_ASSET_PRICE_CONFIGS.keys()) == {"TMGH", "ETEL", "EFID"}
    assert await _count(db_session, AssetPriceConfig) == 3

    result = await db_session.execute(select(Asset).where(Asset.symbol.in_(["BWA", "AZN"])))
    fund_assets = result.scalars().all()
    assert len(fund_assets) == 2
    for asset in fund_assets:
        assert asset.asset_type == AssetType.FUND
        assert asset.market is None


async def test_seed_egx_price_configs_use_mubasher_primary_yahoo_secondary(db_session):
    """Mubasher is primary for every seeded EGX equity, with Yahoo
    retained as the secondary fallback (not dropped) -- see
    SEED_ASSET_PRICE_CONFIGS's own comment for why."""
    await run_seed(db_session)

    result = await db_session.execute(select(Asset).where(Asset.symbol.in_(SEED_ASSET_PRICE_CONFIGS)))
    assets_by_symbol = {asset.symbol: asset for asset in result.scalars().all()}

    result = await db_session.execute(
        select(AssetPriceConfig).where(
            AssetPriceConfig.asset_id.in_([a.id for a in assets_by_symbol.values()])
        )
    )
    configs_by_asset_id = {c.asset_id: c for c in result.scalars().all()}

    provider_symbols_seen = set()
    for symbol, spec in SEED_ASSET_PRICE_CONFIGS.items():
        asset = assets_by_symbol[symbol]
        config = configs_by_asset_id[asset.id]
        assert config.primary_provider == "mubasher"
        assert config.primary_provider_symbol == spec["primary_provider_symbol"]
        assert config.secondary_provider == "yahoo"
        assert config.secondary_provider_symbol == spec["secondary_provider_symbol"]
        assert config.automated_fetching_enabled == spec["automated_fetching_enabled"]
        # No two EGX assets accidentally share one primary provider symbol.
        assert config.primary_provider_symbol not in provider_symbols_seen
        provider_symbols_seen.add(config.primary_provider_symbol)


async def test_seed_does_not_assign_any_provider_to_non_egx_assets(db_session):
    await run_seed(db_session)

    non_egx_symbols = {spec["symbol"] for spec in SEED_ASSETS} - set(SEED_ASSET_PRICE_CONFIGS)
    assert non_egx_symbols == {"CLOUDZ", "BWA", "AZN", "GOLD"}

    result = await db_session.execute(select(Asset).where(Asset.symbol.in_(non_egx_symbols)))
    assets = result.scalars().all()
    result = await db_session.execute(
        select(AssetPriceConfig).where(AssetPriceConfig.asset_id.in_([a.id for a in assets]))
    )
    assert result.scalars().all() == []
