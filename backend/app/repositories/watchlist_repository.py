"""Data access for the Watchlist + Alert Rules feature. All SQLAlchemy
queries for this domain live here (see ARCHITECTURE.md, "Backend
Layering").
"""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import AlertRule, Asset, Watchlist


async def get_asset_by_id(session: AsyncSession, asset_id: UUID) -> Asset | None:
    result = await session.execute(select(Asset).where(Asset.id == asset_id))
    return result.scalar_one_or_none()


async def get_watchlist_entry_by_asset_id(session: AsyncSession, asset_id: UUID) -> Watchlist | None:
    result = await session.execute(
        select(Watchlist).where(Watchlist.asset_id == asset_id).options(selectinload(Watchlist.alert_rule))
    )
    return result.scalar_one_or_none()


async def get_watchlist_entry_by_id(session: AsyncSession, watchlist_id: UUID) -> Watchlist | None:
    result = await session.execute(
        select(Watchlist)
        .where(Watchlist.id == watchlist_id)
        .options(
            selectinload(Watchlist.alert_rule),
            selectinload(Watchlist.asset).selectinload(Asset.holding),
        )
    )
    return result.scalar_one_or_none()


async def list_watchlist_entries(session: AsyncSession, *, enabled_only: bool = False) -> list[Watchlist]:
    query = select(Watchlist).options(
        selectinload(Watchlist.asset).selectinload(Asset.holding), selectinload(Watchlist.alert_rule)
    )
    if enabled_only:
        query = query.where(Watchlist.enabled.is_(True))
    result = await session.execute(query)
    return list(result.scalars().all())


async def list_active_watchlist_entries_with_active_assets(session: AsyncSession) -> list[Watchlist]:
    """Enabled watchlist entries whose underlying asset is also active —
    the set of candidates alert evaluation should ever consider (Phase 8
    approval: "inactive assets must not be evaluated as active watchlist
    candidates")."""
    result = await session.execute(
        select(Watchlist)
        .join(Asset, Watchlist.asset_id == Asset.id)
        .where(Watchlist.enabled.is_(True), Asset.is_active.is_(True))
        .options(
            selectinload(Watchlist.asset).selectinload(Asset.holding),
            selectinload(Watchlist.alert_rule),
        )
    )
    return list(result.scalars().all())


async def get_alert_rule_by_id(session: AsyncSession, alert_rule_id: UUID) -> AlertRule | None:
    result = await session.execute(
        select(AlertRule).where(AlertRule.id == alert_rule_id).options(selectinload(AlertRule.watchlist))
    )
    return result.scalar_one_or_none()


async def get_alert_rule_by_watchlist_id(session: AsyncSession, watchlist_id: UUID) -> AlertRule | None:
    result = await session.execute(select(AlertRule).where(AlertRule.watchlist_id == watchlist_id))
    return result.scalar_one_or_none()
