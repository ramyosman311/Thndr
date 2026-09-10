"""Phase 15 snapshot lifecycle: post-transaction (DEPOSIT/WITHDRAWAL) and
EOD snapshot creation, plus the financial-context computation shared by
both.

Snapshots are observations, never a second/shadow transaction system: this
module never writes to `transactions` or `holdings` -- see
services/transaction_service.py for the one place a DEPOSIT/WITHDRAWAL
transaction itself is created and its holding updated, atomically with the
post-transaction snapshot this module builds.

Valuation reuses the exact same read path the live dashboard already uses
(services/portfolio_shared.py -> services/price_service.py), so a snapshot
and the live dashboard can never silently disagree about what "total
portfolio value" means at a given instant -- no parallel pricing logic is
introduced here (see FINANCIAL_RULES.md, "Non-Blocking Valuation";
DECISIONS.md, "Phase 15 Known Limitations" for what this implies about
assets with no usable price).
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.transaction_engine import ReplayEvent, replay_cumulative_realized_pnl
from app.models import Asset, PortfolioConfig, PortfolioSnapshot, PortfolioSnapshotItem, Transaction
from app.repositories.portfolio_repository import get_active_assets
from app.repositories.snapshot_repository import get_eod_snapshot_for_utc_date, list_transactions_ordered
from app.services.portfolio_shared import load_priced_positions

_CASH_FLOW_TYPES = {"DEPOSIT", "WITHDRAWAL"}
_REPLAYABLE_TYPES = {"BUY", "SELL"}


@dataclass(frozen=True)
class SnapshotFinancials:
    total_value: Decimal
    total_cost_basis: Decimal
    invested_capital: Decimal
    realized_pnl_cumulative: Decimal
    item_values: dict[UUID, Decimal]
    is_complete: bool


async def _compute_snapshot_financials(
    session: AsyncSession, assets: list[Asset], config: PortfolioConfig
) -> SnapshotFinancials:
    """Assembles every financial field a Phase 15 snapshot row needs, as of
    right now, purely by reading already-persisted state (holdings, prices,
    transaction history) -- never by mutating any of it."""
    positions = await load_priced_positions(session, assets, config.emergency_asset_id, config.base_currency)
    position_by_asset_id = {position.asset_id: position for position in positions}

    total_value = Decimal("0")
    total_cost_basis = Decimal("0")
    item_values: dict[UUID, Decimal] = {}
    is_complete = True

    for asset in assets:
        holding = asset.holding
        if holding is None or holding.quantity == 0:
            continue
        position = position_by_asset_id.get(asset.id)
        value = position.value if position is not None else None
        total_cost_basis += holding.quantity * holding.average_cost
        if value is None:
            is_complete = False
            continue
        item_values[asset.id] = value
        total_value += value

    transactions = await list_transactions_ordered(session)
    invested_capital = Decimal("0")
    replay_events: list[ReplayEvent] = []
    for transaction in transactions:
        # `transaction_type` may be a `TransactionType` enum member (a
        # freshly DB-loaded row) or a plain str (an object still resident
        # in this session's identity map from earlier in the same
        # transaction, not yet round-tripped through the DB) --
        # TransactionType subclasses str, so plain `==`/`in` against a
        # string literal is correct either way; `.value` is deliberately
        # never used here.
        if transaction.transaction_type in _CASH_FLOW_TYPES:
            signed = transaction.quantity if transaction.transaction_type == "DEPOSIT" else -transaction.quantity
            invested_capital += signed
        elif transaction.transaction_type in _REPLAYABLE_TYPES:
            replay_events.append(
                ReplayEvent(
                    # Passed through as-is (enum member or plain str --
                    # both compare correctly against "BUY"/"SELL" since
                    # TransactionType subclasses str; never use
                    # `str(...)` here, which would give "TransactionType.
                    # BUY" via Enum's own __str__ override, not "BUY").
                    asset_id=transaction.asset_id,
                    transaction_type=transaction.transaction_type,
                    quantity=transaction.quantity,
                    price=transaction.price,
                    fees=transaction.fees,
                )
            )
    realized_pnl_cumulative = replay_cumulative_realized_pnl(replay_events)

    return SnapshotFinancials(
        total_value=total_value,
        total_cost_basis=total_cost_basis,
        invested_capital=invested_capital,
        realized_pnl_cumulative=realized_pnl_cumulative,
        item_values=item_values,
        is_complete=is_complete,
    )


def _build_snapshot(
    *,
    config: PortfolioConfig,
    snapshot_at: datetime,
    trigger_source: str,
    source_transaction_id: UUID | None,
    financials: SnapshotFinancials,
) -> PortfolioSnapshot:
    snapshot = PortfolioSnapshot(
        portfolio_config_id=config.id,
        snapshot_at=snapshot_at,
        trigger_source=trigger_source,
        source_transaction_id=source_transaction_id,
        total_cost_basis=financials.total_cost_basis,
        invested_capital=financials.invested_capital,
        realized_pnl_cumulative=financials.realized_pnl_cumulative,
    )
    snapshot.items = [
        PortfolioSnapshotItem(asset_id=asset_id, value=value) for asset_id, value in financials.item_values.items()
    ]
    return snapshot


async def build_post_transaction_snapshot(
    session: AsyncSession, *, config: PortfolioConfig, transaction: Transaction
) -> PortfolioSnapshot:
    """Builds (but does not commit) the post-flow snapshot for a just-
    applied DEPOSIT/WITHDRAWAL. Called from transaction_service.py BEFORE
    its own `session.commit()`, so the transaction, its holding update, and
    this snapshot all commit together atomically -- or none of them do (see
    FINANCIAL_RULES.md, "Transaction Atomicity", extended here to include
    the snapshot).

    `snapshot_at` uses `transaction.transaction_date` (the user-declared
    event time), not "now" -- consistent with every other read of
    transaction timing already in this codebase (e.g.
    ix_transactions_asset_id_transaction_date) and with the fact that this
    system already assumes transactions are entered in real-world
    chronological order (see DECISIONS.md, "Phase 15 Deterministic
    Ordering")."""
    assets = await get_active_assets(session)
    financials = await _compute_snapshot_financials(session, assets, config)
    return _build_snapshot(
        config=config,
        snapshot_at=transaction.transaction_date,
        trigger_source="TRANSACTION",
        source_transaction_id=transaction.id,
        financials=financials,
    )


async def create_eod_snapshot_if_missing(session: AsyncSession, *, config: PortfolioConfig) -> PortfolioSnapshot | None:
    """Idempotent: returns None (no-op) if an EOD snapshot already exists
    for today (UTC calendar day) for this portfolio -- checked first
    against the DB (matching `uq_portfolio_snapshot_eod_per_day` exactly),
    with the unique index itself as the concurrency backstop against a
    genuine race between two overlapping worker runs."""
    today = datetime.now(timezone.utc).date()
    existing = await get_eod_snapshot_for_utc_date(session, config.id, today)
    if existing is not None:
        return None

    assets = await get_active_assets(session)
    financials = await _compute_snapshot_financials(session, assets, config)
    snapshot = _build_snapshot(
        config=config,
        snapshot_at=datetime.now(timezone.utc),
        trigger_source="EOD",
        source_transaction_id=None,
        financials=financials,
    )
    session.add(snapshot)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        return None
    await session.refresh(snapshot)
    return snapshot
