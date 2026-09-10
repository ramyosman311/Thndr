"""Idempotent development database seeding.

Every function here is "create if missing, otherwise reuse the existing
row" — keyed on stable natural/business identifiers (asset symbol,
portfolio config name, (portfolio_config, bucket name), (portfolio_config,
strategy_bucket) pair, (portfolio_config, snapshot_at)) rather than on
generated UUIDs. Running run_seed() any number of times against the same
database produces exactly the same rows: no duplicate assets, buckets,
configuration, or snapshots.

This module contains no financial calculations and no hardcoded business
rules for engines to consume later — it only writes the initial
configuration rows that a future engine will read from the database (see
FINANCIAL_RULES.md, "Database Is the Source of Truth").
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AllocationTarget,
    Asset,
    AssetPriceConfig,
    PortfolioConfig,
    PortfolioSnapshot,
    PortfolioSnapshotItem,
    StrategyBucket,
)
from app.seed.data import (
    EMERGENCY_ASSET_SYMBOL,
    SEED_ALLOCATION_TARGETS,
    SEED_ASSET_PRICE_CONFIGS,
    SEED_ASSETS,
    SEED_PORTFOLIO_CONFIG,
    SEED_SNAPSHOTS,
    SEED_STRATEGY_BUCKETS,
)


async def seed_assets(session: AsyncSession) -> dict[str, Asset]:
    """Create any missing assets, keyed by symbol. Returns all seeded assets by symbol."""
    assets_by_symbol: dict[str, Asset] = {}
    for spec in SEED_ASSETS:
        symbol = spec["symbol"]
        result = await session.execute(select(Asset).where(Asset.symbol == symbol))
        asset = result.scalar_one_or_none()
        if asset is None:
            asset = Asset(**spec)
            session.add(asset)
            await session.flush()
        assets_by_symbol[symbol] = asset
    return assets_by_symbol


async def seed_portfolio_config(session: AsyncSession, emergency_asset: Asset) -> PortfolioConfig:
    """Create the main portfolio config if missing, keyed by name.

    Cloudz is wired as the emergency asset here, in seed data, not via any
    `if symbol == "CLOUDZ"` check in application code — a future engine
    only ever reads `portfolio_configs.emergency_asset_id`.
    """
    result = await session.execute(
        select(PortfolioConfig).where(PortfolioConfig.name == SEED_PORTFOLIO_CONFIG["name"])
    )
    config = result.scalar_one_or_none()
    if config is None:
        config = PortfolioConfig(**SEED_PORTFOLIO_CONFIG, emergency_asset_id=emergency_asset.id)
        session.add(config)
        await session.flush()
    return config


async def seed_strategy_buckets(
    session: AsyncSession, config: PortfolioConfig, assets_by_symbol: dict[str, Asset]
) -> dict[str, StrategyBucket]:
    """Create any missing strategy buckets, keyed by (portfolio_config, name),
    and assign each bucket's member assets to it."""
    buckets_by_name: dict[str, StrategyBucket] = {}
    for name, spec in SEED_STRATEGY_BUCKETS.items():
        result = await session.execute(
            select(StrategyBucket).where(
                StrategyBucket.portfolio_config_id == config.id,
                StrategyBucket.name == name,
            )
        )
        bucket = result.scalar_one_or_none()
        if bucket is None:
            bucket = StrategyBucket(
                portfolio_config_id=config.id,
                name=name,
                description=spec["description"],
            )
            session.add(bucket)
            await session.flush()
        buckets_by_name[name] = bucket

        for symbol in spec["assets"]:
            asset = assets_by_symbol[symbol]
            if asset.strategy_bucket_id != bucket.id:
                asset.strategy_bucket_id = bucket.id

    await session.flush()
    return buckets_by_name


async def seed_allocation_targets(
    session: AsyncSession, config: PortfolioConfig, buckets_by_name: dict[str, StrategyBucket]
) -> list[AllocationTarget]:
    """Create any missing allocation targets, keyed by (portfolio_config, strategy_bucket)."""
    targets: list[AllocationTarget] = []
    for bucket_name, spec in SEED_ALLOCATION_TARGETS.items():
        bucket = buckets_by_name[bucket_name]
        result = await session.execute(
            select(AllocationTarget).where(
                AllocationTarget.portfolio_config_id == config.id,
                AllocationTarget.strategy_bucket_id == bucket.id,
            )
        )
        target = result.scalar_one_or_none()
        if target is None:
            target = AllocationTarget(
                portfolio_config_id=config.id,
                strategy_bucket_id=bucket.id,
                **spec,
            )
            session.add(target)
            await session.flush()
        targets.append(target)
    return targets


async def seed_snapshots(
    session: AsyncSession, config: PortfolioConfig, assets_by_symbol: dict[str, Asset]
) -> list[PortfolioSnapshot]:
    """Create any missing snapshots, keyed by (portfolio_config, snapshot_at).

    A snapshot that already exists at that timestamp is left untouched
    (its items are not re-created or modified) — snapshots are historical
    records, not something a reseed should mutate.
    """
    snapshots: list[PortfolioSnapshot] = []
    for spec in SEED_SNAPSHOTS:
        result = await session.execute(
            select(PortfolioSnapshot).where(
                PortfolioSnapshot.portfolio_config_id == config.id,
                PortfolioSnapshot.snapshot_at == spec["snapshot_at"],
            )
        )
        snapshot = result.scalar_one_or_none()
        if snapshot is None:
            snapshot = PortfolioSnapshot(
                portfolio_config_id=config.id,
                snapshot_at=spec["snapshot_at"],
                label=spec["label"],
            )
            session.add(snapshot)
            await session.flush()
            for symbol, value in spec["values"].items():
                session.add(
                    PortfolioSnapshotItem(
                        snapshot_id=snapshot.id,
                        asset_id=assets_by_symbol[symbol].id,
                        value=value,
                    )
                )
            await session.flush()
        snapshots.append(snapshot)
    return snapshots


async def seed_asset_price_configs(
    session: AsyncSession, assets_by_symbol: dict[str, Asset]
) -> dict[str, AssetPriceConfig]:
    """Create any missing asset price configs, keyed by asset_id (Phase 13).

    Only ever touches the symbols listed in SEED_ASSET_PRICE_CONFIGS --
    deliberately not all assets (see that constant's own comment for why
    BWA/AZN/CLOUDZ/GOLD are excluded). A config that already exists for an
    asset (e.g. edited later via the Phase 12 admin UI) is left untouched,
    same "create if missing" rule as every other seed function here."""
    configs_by_symbol: dict[str, AssetPriceConfig] = {}
    for symbol, spec in SEED_ASSET_PRICE_CONFIGS.items():
        asset = assets_by_symbol[symbol]
        result = await session.execute(
            select(AssetPriceConfig).where(AssetPriceConfig.asset_id == asset.id)
        )
        config = result.scalar_one_or_none()
        if config is None:
            config = AssetPriceConfig(asset_id=asset.id, **spec)
            session.add(config)
            await session.flush()
        configs_by_symbol[symbol] = config
    return configs_by_symbol


async def run_seed(session: AsyncSession) -> None:
    """Run the full idempotent seed sequence and commit."""
    assets_by_symbol = await seed_assets(session)
    emergency_asset = assets_by_symbol[EMERGENCY_ASSET_SYMBOL]
    config = await seed_portfolio_config(session, emergency_asset)
    buckets_by_name = await seed_strategy_buckets(session, config, assets_by_symbol)
    await seed_allocation_targets(session, config, buckets_by_name)
    await seed_snapshots(session, config, assets_by_symbol)
    await seed_asset_price_configs(session, assets_by_symbol)
    await session.commit()
