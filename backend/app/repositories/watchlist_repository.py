"""Data access for the Watchlist + Alert Rules feature. All SQLAlchemy
queries for this domain live here (see ARCHITECTURE.md, "Backend
Layering").

P0-3C: every query over user-owned rows (watchlist entries, alert rules)
takes the caller's `portfolio_config_id` and filters on it. An id belonging
to any other portfolio is indistinguishable from one that doesn't exist.
Assets themselves are shared reference data and stay unscoped.
"""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import AlertRule, Asset, Watchlist


async def get_asset_by_id(session: AsyncSession, asset_id: UUID) -> Asset | None:
    result = await session.execute(select(Asset).where(Asset.id == asset_id))
    return result.scalar_one_or_none()


async def get_watchlist_entry_by_asset_id(
    session: AsyncSession, asset_id: UUID, portfolio_config_id: UUID
) -> Watchlist | None:
    result = await session.execute(
        select(Watchlist)
        .where(Watchlist.asset_id == asset_id, Watchlist.portfolio_config_id == portfolio_config_id)
        .options(selectinload(Watchlist.alert_rule))
    )
    return result.scalar_one_or_none()


async def get_watchlist_entry_by_id(
    session: AsyncSession, watchlist_id: UUID, portfolio_config_id: UUID
) -> Watchlist | None:
    result = await session.execute(
        select(Watchlist)
        .where(Watchlist.id == watchlist_id, Watchlist.portfolio_config_id == portfolio_config_id)
        .options(selectinload(Watchlist.alert_rule), selectinload(Watchlist.asset))
    )
    return result.scalar_one_or_none()


async def list_watchlist_entries(
    session: AsyncSession, portfolio_config_id: UUID, *, enabled_only: bool = False
) -> list[Watchlist]:
    query = (
        select(Watchlist)
        .where(Watchlist.portfolio_config_id == portfolio_config_id)
        .options(selectinload(Watchlist.asset), selectinload(Watchlist.alert_rule))
    )
    if enabled_only:
        query = query.where(Watchlist.enabled.is_(True))
    result = await session.execute(query)
    return list(result.scalars().all())


async def list_active_watchlist_entries_with_active_assets(
    session: AsyncSession, portfolio_config_id: UUID
) -> list[Watchlist]:
    """Enabled watchlist entries whose underlying asset is also active —
    the set of candidates alert evaluation should ever consider (Phase 8
    approval: "inactive assets must not be evaluated as active watchlist
    candidates"). Only this portfolio's entries (P0-3C)."""
    result = await session.execute(
        select(Watchlist)
        .join(Asset, Watchlist.asset_id == Asset.id)
        .where(
            Watchlist.portfolio_config_id == portfolio_config_id,
            Watchlist.enabled.is_(True),
            Asset.is_active.is_(True),
        )
        .options(selectinload(Watchlist.asset), selectinload(Watchlist.alert_rule))
    )
    return list(result.scalars().all())


async def get_alert_rule_by_id(
    session: AsyncSession, alert_rule_id: UUID, portfolio_config_id: UUID
) -> AlertRule | None:
    """An alert rule has two ownership paths -- its own `portfolio_config_id`
    and the watchlist entry it hangs off. Both must name the caller's
    portfolio, so a rule is only reachable if the two can never disagree
    (P0-3C)."""
    result = await session.execute(
        select(AlertRule)
        .join(Watchlist, AlertRule.watchlist_id == Watchlist.id)
        .where(
            AlertRule.id == alert_rule_id,
            AlertRule.portfolio_config_id == portfolio_config_id,
            Watchlist.portfolio_config_id == portfolio_config_id,
        )
        .options(selectinload(AlertRule.watchlist))
    )
    return result.scalar_one_or_none()


async def get_alert_rule_by_watchlist_id(
    session: AsyncSession, watchlist_id: UUID, portfolio_config_id: UUID
) -> AlertRule | None:
    result = await session.execute(
        select(AlertRule)
        .join(Watchlist, AlertRule.watchlist_id == Watchlist.id)
        .where(
            AlertRule.watchlist_id == watchlist_id,
            AlertRule.portfolio_config_id == portfolio_config_id,
            Watchlist.portfolio_config_id == portfolio_config_id,
        )
    )
    return result.scalar_one_or_none()
