"""Data access for the Portfolio Engine. All SQLAlchemy queries for this
domain live here — services depend on these functions, not on raw
sessions or ORM query-building (see ARCHITECTURE.md, "Backend Layering").
"""

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import AllocationTarget, Asset, Holding, PortfolioConfig, StrategyBucket, Transaction


async def get_portfolio_config_for_user(session: AsyncSession, user_id: UUID) -> PortfolioConfig | None:
    """The authenticated user's own portfolio configuration, or None.

    Ownership is the ONLY selector: `portfolio_configs.user_id == user_id`,
    where `user_id` is always the verified Supabase identity
    (`get_current_user().id`), never a client-supplied value. There is
    deliberately no unscoped "the first portfolio" lookup anywhere in the
    codebase (P0-3C) -- rows with a NULL owner are never returned here.

    The product is single-portfolio-per-user today (POST /portfolio/config
    rejects a second one, see services/portfolio_config_service.py). If
    more than one ever exists for a user the choice is still deterministic
    (oldest first), never arbitrary.
    """
    result = await session.execute(
        select(PortfolioConfig)
        .where(PortfolioConfig.user_id == user_id)
        .order_by(PortfolioConfig.created_at, PortfolioConfig.id)
        .limit(1)
    )
    return result.scalar_one_or_none()


async def list_owned_portfolio_configs(session: AsyncSession) -> list[PortfolioConfig]:
    """Every portfolio that has a verified owner -- for background workers
    that legitimately act on all users' portfolios (EOD snapshots, Telegram
    delivery). They must iterate this explicitly rather than pick one.
    Unowned (legacy, pre-ownership) portfolios are excluded: their holdings/
    transactions carry no owner link either, so computing anything for them
    would silently produce wrong (empty) results."""
    result = await session.execute(
        select(PortfolioConfig)
        .where(PortfolioConfig.user_id.is_not(None))
        .order_by(PortfolioConfig.created_at, PortfolioConfig.id)
    )
    return list(result.scalars().all())


async def any_transaction_exists(session: AsyncSession, portfolio_config_id: UUID) -> bool:
    """Whether ANY transaction has been recorded in THIS portfolio.

    Used exclusively to gate a base_currency change (Phase 12, see
    FINANCIAL_RULES.md, "Base Currency Change Policy"). Scoped to the
    portfolio (P0-3C): one user's history must neither block nor permit
    another user's base-currency change.
    """
    result = await session.execute(
        select(func.count()).select_from(
            select(Transaction.id).where(Transaction.portfolio_config_id == portfolio_config_id).limit(1).subquery()
        )
    )
    return result.scalar_one() > 0


async def get_active_assets(session: AsyncSession, portfolio_config_id: UUID) -> list[Asset]:
    """Active (global) assets, each with ONLY this portfolio's holding
    loaded into `asset.holding`.

    Assets are shared market/reference data, but a holding belongs to one
    portfolio -- so the eager load is explicitly restricted to the caller's
    portfolio. Every consumer of `asset.holding` goes through this query,
    so it can never see another user's position.

    `populate_existing` is essential, not an optimization: `Asset` rows are
    shared across portfolios, and a session that serves more than one
    portfolio (a background worker iterating portfolios) keeps each asset in
    its identity map with `asset.holding` already loaded for the FIRST
    portfolio -- without it the second portfolio would silently be valued
    from the first one's holdings."""
    result = await session.execute(
        select(Asset)
        .where(Asset.is_active.is_(True))
        .options(selectinload(Asset.holding.and_(Holding.portfolio_config_id == portfolio_config_id)))
        .execution_options(populate_existing=True)
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
