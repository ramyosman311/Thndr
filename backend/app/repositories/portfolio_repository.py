"""Data access for the Portfolio Engine. All SQLAlchemy queries for this
domain live here — services depend on these functions, not on raw
sessions or ORM query-building (see ARCHITECTURE.md, "Backend Layering").
"""

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import AllocationTarget, Asset, PortfolioConfig, StrategyBucket, Transaction


async def get_portfolio_config(session: AsyncSession) -> PortfolioConfig | None:
    """The single portfolio configuration row.

    The schema supports multiple portfolio_configs, but the application is
    single-portfolio for now (see ARCHITECTURE.md) — this returns the
    first row found, or None if none has been configured yet.
    """
    result = await session.execute(select(PortfolioConfig).limit(1))
    return result.scalar_one_or_none()


async def any_transaction_exists(session: AsyncSession) -> bool:
    """Whether ANY transaction has ever been recorded, system-wide.

    Used exclusively to gate a base_currency change (Phase 12, see
    FINANCIAL_RULES.md, "Base Currency Change Policy"). This is a
    system-wide check rather than a per-portfolio one because
    `transactions` carries no `portfolio_config_id` today (see
    ARCHITECTURE.md, "Domain Readiness Audit (Phase 12)") -- correct for
    the current single-portfolio architecture, and conservative (never
    under-protective) if that assumption changes later.
    """
    result = await session.execute(select(func.count()).select_from(select(Transaction.id).limit(1).subquery()))
    return result.scalar_one() > 0


async def get_active_assets(session: AsyncSession) -> list[Asset]:
    result = await session.execute(
        select(Asset).where(Asset.is_active.is_(True)).options(selectinload(Asset.holding))
    )
    return list(result.scalars().all())


async def get_active_strategy_buckets(session: AsyncSession, portfolio_config_id: UUID) -> list[StrategyBucket]:
    result = await session.execute(
        select(StrategyBucket).where(
            StrategyBucket.portfolio_config_id == portfolio_config_id,
            StrategyBucket.is_active.is_(True),
        )
    )
    return list(result.scalars().all())


async def get_active_allocation_targets(
    session: AsyncSession, portfolio_config_id: UUID
) -> list[AllocationTarget]:
    result = await session.execute(
        select(AllocationTarget).where(
            AllocationTarget.portfolio_config_id == portfolio_config_id,
            AllocationTarget.is_active.is_(True),
        )
    )
    return list(result.scalars().all())
