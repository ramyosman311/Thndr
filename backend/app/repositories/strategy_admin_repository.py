"""Data access for Strategy Bucket + Allocation Target administration
(Phase 12). Distinct from portfolio_repository.py's active-only queries
(used by the read-only Portfolio/Strategy/Inflow Engines) -- this module
also fetches inactive rows so the admin UI can list and reactivate them.
"""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AllocationTarget, StrategyBucket


async def get_strategy_bucket_by_id(session: AsyncSession, bucket_id: UUID) -> StrategyBucket | None:
    result = await session.execute(select(StrategyBucket).where(StrategyBucket.id == bucket_id))
    return result.scalar_one_or_none()


async def list_strategy_buckets(
    session: AsyncSession, portfolio_config_id: UUID, *, include_inactive: bool = False
) -> list[StrategyBucket]:
    query = (
        select(StrategyBucket)
        .where(StrategyBucket.portfolio_config_id == portfolio_config_id)
        .order_by(StrategyBucket.name)
    )
    if not include_inactive:
        query = query.where(StrategyBucket.is_active.is_(True))
    result = await session.execute(query)
    return list(result.scalars().all())


async def get_allocation_target_by_id(session: AsyncSession, target_id: UUID) -> AllocationTarget | None:
    result = await session.execute(select(AllocationTarget).where(AllocationTarget.id == target_id))
    return result.scalar_one_or_none()


async def list_allocation_targets(
    session: AsyncSession, portfolio_config_id: UUID, *, include_inactive: bool = False
) -> list[AllocationTarget]:
    query = select(AllocationTarget).where(AllocationTarget.portfolio_config_id == portfolio_config_id)
    if not include_inactive:
        query = query.where(AllocationTarget.is_active.is_(True))
    result = await session.execute(query)
    return list(result.scalars().all())
