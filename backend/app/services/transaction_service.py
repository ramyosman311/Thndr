"""Orchestrates the Transaction + Holding write path (Phase 10).

Writes to `transactions` (an immutable historical record — never
updated or deleted here) and `holdings` (the current position, fully
derived from transaction history). Both writes happen in the same
database transaction (a single `session.commit()`), so a transaction
record and its resulting holding update succeed or fail together — see
FINANCIAL_RULES.md, "Transaction Atomicity".

Reuse, not duplication: the actual BUY/SELL math lives in
`domain/transaction_engine.py`; this module only loads state, calls it,
and persists the result. It never recomputes cost basis or average cost
itself.
"""

from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.transaction_engine import (
    InsufficientCashError as DomainInsufficientCashError,
    OversellError as DomainOversellError,
    apply_buy,
    apply_deposit,
    apply_sell,
    apply_withdrawal,
)
from app.models import AssetType, Holding, Transaction
from app.repositories.portfolio_repository import get_portfolio_config
from app.repositories.transaction_repository import (
    get_asset_by_id,
    get_holding_by_asset_id_for_update,
    list_transactions as repo_list_transactions,
)
from app.schemas.transaction import HoldingSnapshotOut, TransactionOut, TransactionResultOut
from app.services import price_service
from app.services.snapshot_service import build_post_transaction_snapshot

_PRESENTATION_QUANT = Decimal("0.01")
_CASH_FLOW_ASSET_TYPES = {AssetType.CASH, AssetType.SAVINGS}


class AssetNotFoundError(Exception):
    """Raised when the referenced asset_id does not exist."""


class OversellError(Exception):
    """Raised when a SELL's quantity exceeds the currently held quantity
    (including selling an asset with no holding at all)."""


class InsufficientCashError(Exception):
    """Raised when a WITHDRAWAL's amount exceeds the currently held cash
    balance (including withdrawing from an asset with no holding at all)."""


class InvalidCashFlowAssetError(Exception):
    """Raised when a DEPOSIT/WITHDRAWAL targets an asset whose asset_type
    is not CASH or SAVINGS (Phase 15 approved design decision -- see
    DECISIONS.md, "Phase 15 Cash Flow Semantics")."""


class InvalidCashFlowAmountError(Exception):
    """Raised for a DEPOSIT/WITHDRAWAL whose price/fees don't satisfy the
    fixed 1:1 cash-unit convention (see schemas/transaction.py's
    model_validator, which already rejects this at the API boundary --
    this is a defensive re-check for any other caller of this service)."""


class PortfolioNotConfiguredError(Exception):
    """Raised when a DEPOSIT/WITHDRAWAL is attempted before any
    portfolio_configs row exists yet (mirrors the same-named exception
    already defined independently in portfolio_service.py/
    inflow_service.py -- each service raises its own per this codebase's
    established convention)."""


def _round(value: Decimal) -> Decimal:
    return value.quantize(_PRESENTATION_QUANT, rounding=ROUND_HALF_UP)


def _transaction_out(transaction: Transaction, asset_symbol: str) -> TransactionOut:
    return TransactionOut(
        id=transaction.id,
        asset_id=transaction.asset_id,
        asset_symbol=asset_symbol,
        transaction_type=transaction.transaction_type.value,
        quantity=transaction.quantity,
        price=transaction.price,
        fees=transaction.fees,
        transaction_date=transaction.transaction_date,
        notes=transaction.notes,
        created_at=transaction.created_at,
    )


async def create_transaction(
    session: AsyncSession,
    *,
    asset_id: UUID,
    transaction_type: str,
    quantity: Decimal,
    price: Decimal,
    fees: Decimal,
    transaction_date: datetime,
    notes: str | None,
) -> TransactionResultOut:
    asset = await get_asset_by_id(session, asset_id)
    if asset is None:
        raise AssetNotFoundError(f"Asset {asset_id} does not exist.")

    # Row-locked for the duration of this DB transaction so a concurrent
    # BUY/SELL on the same asset serializes rather than both reading a
    # stale quantity (see FINANCIAL_RULES.md, "Transaction Concurrency").
    holding = await get_holding_by_asset_id_for_update(session, asset_id)
    current_quantity = holding.quantity if holding is not None else Decimal("0")
    current_average_cost = holding.average_cost if holding is not None else Decimal("0")

    realized_pnl: Decimal | None = None
    snapshot_pending = False
    if transaction_type == "BUY":
        result = apply_buy(
            current_quantity=current_quantity,
            current_average_cost=current_average_cost,
            purchase_quantity=quantity,
            purchase_price=price,
            fees=fees,
        )
    elif transaction_type == "SELL":
        if holding is None or current_quantity == 0:
            raise OversellError(f"Cannot sell {quantity}: no holding currently exists for this asset.")
        try:
            sell_result = apply_sell(
                current_quantity=current_quantity,
                current_average_cost=current_average_cost,
                sell_quantity=quantity,
                sell_price=price,
                fees=fees,
            )
        except DomainOversellError as exc:
            raise OversellError(str(exc)) from exc
        result = sell_result
        realized_pnl = sell_result.realized_pnl
    else:
        # DEPOSIT / WITHDRAWAL (Phase 15) -- see domain/transaction_engine.py.
        # Restricted to CASH/SAVINGS assets: quantity is the cash balance
        # itself, average_cost stays pinned at 1, never treated as
        # investment return (see FINANCIAL_RULES.md, "Cash Flow Is Not
        # Profit").
        if asset.asset_type not in _CASH_FLOW_ASSET_TYPES:
            raise InvalidCashFlowAssetError(
                f"DEPOSIT/WITHDRAWAL is only allowed for CASH/SAVINGS assets, not {asset.asset_type.value}."
            )
        if price != 1 or fees != 0:
            raise InvalidCashFlowAmountError("DEPOSIT/WITHDRAWAL requires price=1 and fees=0.")
        if transaction_type == "DEPOSIT":
            result = apply_deposit(current_quantity=current_quantity, deposit_amount=quantity)
        else:
            try:
                result = apply_withdrawal(current_quantity=current_quantity, withdrawal_amount=quantity)
            except DomainInsufficientCashError as exc:
                raise InsufficientCashError(str(exc)) from exc
        snapshot_pending = True

    if holding is None:
        holding = Holding(asset_id=asset_id, quantity=result.quantity, average_cost=result.average_cost)
        session.add(holding)
        # Also wire the in-memory relationship, not just the FK column:
        # `asset` may already be identity-mapped with `.holding` cached as
        # None from an earlier query in this same session (e.g. Phase 15's
        # snapshot valuation re-querying active assets) -- a bare
        # `session.add(holding)` does not retroactively refresh that
        # cached relationship, so a same-transaction read immediately
        # after this would otherwise see a stale "no holding" via
        # `asset.holding` even though the row now exists.
        asset.holding = holding
    else:
        holding.quantity = result.quantity
        holding.average_cost = result.average_cost

    transaction = Transaction(
        asset_id=asset_id,
        transaction_type=transaction_type,
        quantity=quantity,
        price=price,
        fees=fees,
        transaction_date=transaction_date,
        notes=notes,
    )
    session.add(transaction)

    if snapshot_pending:
        # Flush (not commit) so `transaction.id` exists and the holding
        # change above is visible to the snapshot's own valuation read --
        # the snapshot is added to the SAME still-open transaction, so it
        # commits atomically with the transaction/holding write below (see
        # services/snapshot_service.py's module docstring).
        await session.flush()
        config = await get_portfolio_config(session)
        if config is None:
            raise PortfolioNotConfiguredError("No portfolio configuration exists yet.")
        snapshot = await build_post_transaction_snapshot(session, config=config, transaction=transaction)
        session.add(snapshot)

    await session.commit()
    await session.refresh(transaction)
    await session.refresh(holding)

    # Native-currency price for the response snapshot only (Phase 11) --
    # this never influences the BUY/SELL math above, which is already
    # complete by the time this is read (see FINANCIAL_RULES.md, "Manual
    # Price Never Touches Transaction History", the same principle
    # extended to every price read here: it's for display, not part of
    # the transaction's own accounting).
    price_result = await price_service.get_asset_price(session, asset)
    current_price = price_result.price if price_result.is_usable else None

    return TransactionResultOut(
        transaction=_transaction_out(transaction, asset.symbol),
        holding=HoldingSnapshotOut(
            quantity=holding.quantity,
            average_cost=holding.average_cost,
            current_price=current_price,
            price_status=price_result.status.value,
        ),
        realized_pnl=_round(realized_pnl) if realized_pnl is not None else None,
    )


async def list_transactions(session: AsyncSession) -> list[TransactionOut]:
    transactions = await repo_list_transactions(session)
    return [_transaction_out(t, t.asset.symbol) for t in transactions]
