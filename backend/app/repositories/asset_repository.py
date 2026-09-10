"""Data access for Asset administration (Phase 12). All SQLAlchemy
queries for creating/editing/activating/deleting assets live here (see
ARCHITECTURE.md, "Backend Layering").
"""

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Asset, AssetPrice, Holding, PortfolioSnapshotItem, StrategyBucket, Transaction, Watchlist


async def get_asset_by_id(session: AsyncSession, asset_id: UUID) -> Asset | None:
    result = await session.execute(select(Asset).where(Asset.id == asset_id))
    return result.scalar_one_or_none()


async def get_asset_by_symbol(session: AsyncSession, symbol: str) -> Asset | None:
    result = await session.execute(select(Asset).where(Asset.symbol == symbol))
    return result.scalar_one_or_none()


async def list_assets(session: AsyncSession, *, include_inactive: bool = False) -> list[Asset]:
    query = select(Asset).order_by(Asset.symbol)
    if not include_inactive:
        query = query.where(Asset.is_active.is_(True))
    result = await session.execute(query)
    return list(result.scalars().all())


async def strategy_bucket_exists(session: AsyncSession, strategy_bucket_id: UUID) -> bool:
    result = await session.execute(select(StrategyBucket.id).where(StrategyBucket.id == strategy_bucket_id))
    return result.scalar_one_or_none() is not None


async def asset_has_transaction_or_price_history(session: AsyncSession, asset_id: UUID) -> bool:
    """A narrower check than `asset_has_historical_data` -- used to gate
    a currency change specifically, since only transactions and price
    observations were actually recorded in the asset's (old) currency
    (a holding's quantity/average_cost/current_price carry no currency
    of their own; a watchlist/snapshot-item row carries no price
    either)."""
    for check in (
        select(Transaction.id).where(Transaction.asset_id == asset_id),
        select(AssetPrice.id).where(AssetPrice.asset_id == asset_id),
    ):
        result = await session.execute(select(func.count()).select_from(check.limit(1).subquery()))
        if result.scalar_one() > 0:
            return True
    return False


async def asset_has_historical_data(session: AsyncSession, asset_id: UUID) -> bool:
    """True if the asset has ANY holding, transaction, watchlist entry,
    snapshot item, or price observation on record. A hard delete is only
    ever permitted when this is False (see FINANCIAL_RULES.md, "Asset
    Deletion Policy") -- deliberately stricter than the DB's own FK
    behavior (price observations CASCADE at the DB level as pricing
    metadata, but still count as financial history for this check)."""
    checks = (
        select(Holding.id).where(Holding.asset_id == asset_id),
        select(Transaction.id).where(Transaction.asset_id == asset_id),
        select(Watchlist.id).where(Watchlist.asset_id == asset_id),
        select(PortfolioSnapshotItem.id).where(PortfolioSnapshotItem.asset_id == asset_id),
        select(AssetPrice.id).where(AssetPrice.asset_id == asset_id),
    )
    for check in checks:
        result = await session.execute(select(func.count()).select_from(check.limit(1).subquery()))
        if result.scalar_one() > 0:
            return True
    return False
