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


class OversellError(ValueError):
    """Raised when a SELL's quantity exceeds the currently held quantity."""


@dataclass(frozen=True)
class HoldingAfterBuy:
    quantity: Decimal
    average_cost: Decimal


@dataclass(frozen=True)
class HoldingAfterSell:
    quantity: Decimal
    average_cost: Decimal
    realized_pnl: Decimal


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
