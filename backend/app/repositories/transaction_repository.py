"""Data access for the Transaction + Holding write path (Phase 10). All
SQLAlchemy queries for this domain live here (see ARCHITECTURE.md,
"Backend Layering").
"""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Asset, Holding, Transaction


async def get_asset_by_id(session: AsyncSession, asset_id: UUID) -> Asset | None:
    result = await session.execute(select(Asset).where(Asset.id == asset_id))
    return result.scalar_one_or_none()


async def get_holding_by_asset_id_for_update(session: AsyncSession, asset_id: UUID) -> Holding | None:
    """Locks the holding row (`SELECT ... FOR UPDATE`) for the duration of
    the caller's transaction, so two concurrent BUY/SELL requests against
    the same asset serialize instead of both reading a stale quantity —
    see FINANCIAL_RULES.md, "Transaction Concurrency"."""
    result = await session.execute(
        select(Holding).where(Holding.asset_id == asset_id).with_for_update()
    )
    return result.scalar_one_or_none()


async def list_transactions(session: AsyncSession) -> list[Transaction]:
    """Newest first, by the actual transaction timestamp -- never DB
    insertion order (see FINANCIAL_RULES.md, "Transaction History Order").
    `created_at`/`id` are deterministic tie-breakers for transactions
    sharing the same `transaction_date` (e.g. two same-day backdated
    entries), so the result order is stable and reproducible rather than
    depending on the database's arbitrary tie-break for equal sort keys."""
    result = await session.execute(
        select(Transaction)
        .options(selectinload(Transaction.asset))
        .order_by(Transaction.transaction_date.desc(), Transaction.created_at.desc(), Transaction.id.desc())
    )
    return list(result.scalars().all())
