"""Data access for the Phase 15 snapshot lifecycle. All SQLAlchemy queries
for this domain live here (see ARCHITECTURE.md, "Backend Layering").
"""

from datetime import date
from uuid import UUID

from sqlalchemy import Date, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import PortfolioSnapshot, Transaction


async def get_eod_snapshot_for_utc_date(
    session: AsyncSession, portfolio_config_id: UUID, utc_date: date
) -> PortfolioSnapshot | None:
    """Mirrors the partial unique index `uq_portfolio_snapshot_eod_per_day`
    exactly (same `AT TIME ZONE 'UTC'` expression) -- used as the primary,
    non-racy idempotency check before creating an EOD snapshot; the DB
    constraint itself is the backstop for a genuine race (see
    services/snapshot_service.py)."""
    result = await session.execute(
        select(PortfolioSnapshot).where(
            PortfolioSnapshot.portfolio_config_id == portfolio_config_id,
            PortfolioSnapshot.trigger_source == "EOD",
            PortfolioSnapshot.snapshot_at.op("AT TIME ZONE")("UTC").cast(Date) == utc_date,
        )
    )
    return result.scalar_one_or_none()


async def list_snapshots_ordered(session: AsyncSession, portfolio_config_id: UUID) -> list[PortfolioSnapshot]:
    """Every snapshot for this portfolio, in the deterministic chronological
    order the TWR engine and analytics service require: (snapshot_at,
    created_at, id) ascending. `id` is a random UUIDv4 used purely as a
    final, stable tiebreaker for two snapshots sharing an identical
    `snapshot_at`/`created_at` down to stored precision -- it does not
    claim to reflect a true real-world sub-instant order the system never
    actually captured (see DECISIONS.md, "Phase 15 Deterministic
    Ordering")."""
    result = await session.execute(
        select(PortfolioSnapshot)
        .where(PortfolioSnapshot.portfolio_config_id == portfolio_config_id)
        .options(selectinload(PortfolioSnapshot.items))
        .order_by(PortfolioSnapshot.snapshot_at, PortfolioSnapshot.created_at, PortfolioSnapshot.id)
    )
    return list(result.scalars().all())


async def list_transactions_ordered(session: AsyncSession) -> list[Transaction]:
    """Every transaction, in the same deterministic chronological order as
    `list_snapshots_ordered` -- (transaction_date, created_at, id)
    ascending -- for realized-P/L replay and invested-capital summation
    (see domain/transaction_engine.py, `replay_cumulative_realized_pnl`)."""
    result = await session.execute(
        select(Transaction).order_by(Transaction.transaction_date, Transaction.created_at, Transaction.id)
    )
    return list(result.scalars().all())
