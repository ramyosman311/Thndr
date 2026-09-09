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

from app.domain.transaction_engine import OversellError as DomainOversellError, apply_buy, apply_sell
from app.models import Holding, Transaction
from app.repositories.transaction_repository import (
    get_asset_by_id,
    get_holding_by_asset_id_for_update,
    list_transactions as repo_list_transactions,
)
from app.schemas.transaction import HoldingSnapshotOut, TransactionOut, TransactionResultOut

_PRESENTATION_QUANT = Decimal("0.01")


class AssetNotFoundError(Exception):
    """Raised when the referenced asset_id does not exist."""


class OversellError(Exception):
    """Raised when a SELL's quantity exceeds the currently held quantity
    (including selling an asset with no holding at all)."""


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
    if transaction_type == "BUY":
        result = apply_buy(
            current_quantity=current_quantity,
            current_average_cost=current_average_cost,
            purchase_quantity=quantity,
            purchase_price=price,
            fees=fees,
        )
    else:
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

    if holding is None:
        holding = Holding(asset_id=asset_id, quantity=result.quantity, average_cost=result.average_cost)
        session.add(holding)
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

    await session.commit()
    await session.refresh(transaction)
    await session.refresh(holding)

    return TransactionResultOut(
        transaction=_transaction_out(transaction, asset.symbol),
        holding=HoldingSnapshotOut(
            quantity=holding.quantity,
            average_cost=holding.average_cost,
            current_price=holding.current_price,
        ),
        realized_pnl=_round(realized_pnl) if realized_pnl is not None else None,
    )


async def list_transactions(session: AsyncSession) -> list[TransactionOut]:
    transactions = await repo_list_transactions(session)
    return [_transaction_out(t, t.asset.symbol) for t in transactions]
