"""Pure BUY/SELL -> Holding update calculations (Phase 10).

No I/O, no database session. Average-cost accounting: this module never
tracks individual purchase lots (no FIFO/LIFO). On BUY, cost basis and
quantity are simply added and a new blended average cost is derived; on
SELL, the sold quantity's cost is removed at the *current* average cost,
and the average cost of the remaining position is unchanged by
construction — removing a proportional slice of cost basis at the same
per-unit cost cannot change the per-unit cost of what remains. That
invariant is computed explicitly here (not just carried over) so it is
directly testable and so the position lands on exactly 0 when fully
closed, rather than relying on an assumption.

Fees increase cost basis on BUY and reduce realized sale proceeds on
SELL — never silently dropped. All arithmetic is Decimal; nothing here
rounds intermediate values, only the Decimal results are returned at full
precision — presentation rounding stays a service/API-boundary concern
(see FINANCIAL_RULES.md, "Precision").

Realized P/L is computed here only as an immediate, explicit result of
one specific SELL call — it is never stored as a separate ledger/lot
subsystem, and it is never combined with unrealized P/L (calculated
independently in pnl_engine.py from the resulting holding's average
cost and a separately-supplied current price).
"""

from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID


class OversellError(ValueError):
    """Raised when a SELL's quantity exceeds the currently held quantity."""


class InsufficientCashError(ValueError):
    """Raised when a WITHDRAWAL's amount exceeds the currently held cash
    balance (Phase 15's mirror of OversellError for DEPOSIT/WITHDRAWAL)."""


@dataclass(frozen=True)
class HoldingAfterBuy:
    quantity: Decimal
    average_cost: Decimal


@dataclass(frozen=True)
class HoldingAfterSell:
    quantity: Decimal
    average_cost: Decimal
    realized_pnl: Decimal


@dataclass(frozen=True)
class HoldingAfterCashFlow:
    quantity: Decimal
    average_cost: Decimal


def apply_buy(
    *,
    current_quantity: Decimal,
    current_average_cost: Decimal,
    purchase_quantity: Decimal,
    purchase_price: Decimal,
    fees: Decimal,
) -> HoldingAfterBuy:
    """gross_cost = purchase_quantity * purchase_price
    total_cost = gross_cost + fees
    new_quantity = current_quantity + purchase_quantity
    new_cost_basis = (current_quantity * current_average_cost) + total_cost
    new_average_cost = new_cost_basis / new_quantity
    """
    if purchase_quantity <= 0:
        raise ValueError("purchase_quantity must be greater than 0")
    if purchase_price < 0:
        raise ValueError("purchase_price must not be negative")
    if fees < 0:
        raise ValueError("fees must not be negative")

    gross_cost = purchase_quantity * purchase_price
    total_cost = gross_cost + fees

    old_cost_basis = current_quantity * current_average_cost
    new_quantity = current_quantity + purchase_quantity
    new_cost_basis = old_cost_basis + total_cost
    new_average_cost = new_cost_basis / new_quantity

    return HoldingAfterBuy(quantity=new_quantity, average_cost=new_average_cost)


def apply_sell(
    *,
    current_quantity: Decimal,
    current_average_cost: Decimal,
    sell_quantity: Decimal,
    sell_price: Decimal,
    fees: Decimal,
) -> HoldingAfterSell:
    """cost_removed = sell_quantity * current_average_cost
    remaining_quantity = current_quantity - sell_quantity
    remaining_cost_basis = (current_quantity * current_average_cost) - cost_removed
    remaining_average_cost = remaining_cost_basis / remaining_quantity (0 when fully closed)

    realized_pnl = (sell_quantity * sell_price - fees) - cost_removed
    — sale proceeds (net of fees) minus the proportional cost basis
    removed. This is a plain, explicit, immediate computation for this
    one sale; it is never persisted as a running realized-P/L ledger.
    """
    if sell_quantity <= 0:
        raise ValueError("sell_quantity must be greater than 0")
    if sell_price < 0:
        raise ValueError("sell_price must not be negative")
    if fees < 0:
        raise ValueError("fees must not be negative")
    if sell_quantity > current_quantity:
        raise OversellError(
            f"Cannot sell {sell_quantity}: only {current_quantity} currently held."
        )

    cost_removed = sell_quantity * current_average_cost
    remaining_quantity = current_quantity - sell_quantity

    if remaining_quantity == 0:
        # No residual quantity or cost basis may remain once a position
        # is fully closed — average cost is undefined for zero units,
        # reported as exactly 0 rather than left dangling at the old value.
        remaining_average_cost = Decimal("0")
    else:
        remaining_cost_basis = (current_quantity * current_average_cost) - cost_removed
        remaining_average_cost = remaining_cost_basis / remaining_quantity

    sale_proceeds_net_of_fees = (sell_quantity * sell_price) - fees
    realized_pnl = sale_proceeds_net_of_fees - cost_removed

    return HoldingAfterSell(
        quantity=remaining_quantity,
        average_cost=remaining_average_cost,
        realized_pnl=realized_pnl,
    )


# --- DEPOSIT / WITHDRAWAL (Phase 15) ---------------------------------------
#
# Restricted at the service layer to assets whose asset_type is CASH or
# SAVINGS (see services/transaction_service.py). For those assets, quantity
# IS the cash balance, denominated 1:1 in the asset's own currency --
# average_cost is always pinned at exactly 1 so cost_basis (quantity *
# average_cost) always equals quantity and no artificial unrealized P/L is
# ever generated for holding cash (see FINANCIAL_RULES.md, "Cash Flow Is
# Not Profit"). Mixing BUY/SELL and DEPOSIT/WITHDRAWAL on the SAME asset is
# undefined behavior and not guarded against here -- see DECISIONS.md,
# "Phase 15 Known Limitations".

_CASH_UNIT_COST = Decimal("1")


def apply_deposit(*, current_quantity: Decimal, deposit_amount: Decimal) -> HoldingAfterCashFlow:
    """new_quantity = current_quantity + deposit_amount; average_cost stays
    pinned at 1. A deposit is external capital, never investment return --
    see domain/twr_engine.py, which is the only place a deposit's effect on
    performance is ever measured."""
    if deposit_amount <= 0:
        raise ValueError("deposit_amount must be greater than 0")
    return HoldingAfterCashFlow(quantity=current_quantity + deposit_amount, average_cost=_CASH_UNIT_COST)


def apply_withdrawal(*, current_quantity: Decimal, withdrawal_amount: Decimal) -> HoldingAfterCashFlow:
    """new_quantity = current_quantity - withdrawal_amount; average_cost
    stays pinned at 1. Rejected if it would drive the cash balance
    negative -- the same oversell-style guard `apply_sell` already uses,
    applied here to a cash balance instead of a share count."""
    if withdrawal_amount <= 0:
        raise ValueError("withdrawal_amount must be greater than 0")
    if withdrawal_amount > current_quantity:
        raise InsufficientCashError(
            f"Cannot withdraw {withdrawal_amount}: only {current_quantity} currently held."
        )
    return HoldingAfterCashFlow(quantity=current_quantity - withdrawal_amount, average_cost=_CASH_UNIT_COST)


# --- Cumulative realized P/L replay (Phase 15) -----------------------------


@dataclass(frozen=True)
class ReplayEvent:
    """One BUY/SELL event, already resolved to plain values, for replay
    through `replay_cumulative_realized_pnl` below. Deliberately excludes
    DEPOSIT/WITHDRAWAL (they never produce realized P/L) and carries no
    ordering information itself -- the caller is responsible for supplying
    events in the exact deterministic order to replay (see
    repositories/transaction_repository.py, `list_transactions_ordered`)."""

    asset_id: UUID
    transaction_type: str  # "BUY" | "SELL"
    quantity: Decimal
    price: Decimal
    fees: Decimal


def replay_cumulative_realized_pnl(events: list[ReplayEvent]) -> Decimal:
    """Derives cumulative realized P/L across all-time SELL activity, as of
    the end of the given (already chronologically ordered) event list, by
    replaying each BUY/SELL through the exact same apply_buy/apply_sell
    used for the live write path -- never a separately maintained ledger
    (see FINANCIAL_RULES.md, "Realized P/L Is Never A Running Ledger", and
    models/snapshot.py's `realized_pnl_cumulative` column docstring).

    Pure re-derivation from immutable transaction history: given the same
    events in the same order, this always returns the same result. Assets
    are tracked independently of one another (a SELL on one asset never
    reads state accumulated from a different asset)."""
    state: dict[UUID, tuple[Decimal, Decimal]] = {}
    total_realized = Decimal("0")

    for event in events:
        current_quantity, current_average_cost = state.get(event.asset_id, (Decimal("0"), Decimal("0")))
        if event.transaction_type == "BUY":
            result = apply_buy(
                current_quantity=current_quantity,
                current_average_cost=current_average_cost,
                purchase_quantity=event.quantity,
                purchase_price=event.price,
                fees=event.fees,
            )
            state[event.asset_id] = (result.quantity, result.average_cost)
        elif event.transaction_type == "SELL":
            result = apply_sell(
                current_quantity=current_quantity,
                current_average_cost=current_average_cost,
                sell_quantity=event.quantity,
                sell_price=event.price,
                fees=event.fees,
            )
            state[event.asset_id] = (result.quantity, result.average_cost)
            total_realized += result.realized_pnl

    return total_realized
