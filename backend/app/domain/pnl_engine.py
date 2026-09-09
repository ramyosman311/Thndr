"""Pure unrealized P/L calculation for a single holding.

No I/O. Only basic unrealized P/L is implemented here — realized P/L
accounting (which requires reasoning across the full transaction history:
lots, fees, prior sells) is out of scope for this phase (see
FINANCIAL_RULES.md and the Phase 5 approval, section 9).

Never calculated from portfolio_snapshots (see FINANCIAL_RULES.md,
"Snapshot != Transaction") and never fabricates a missing input — a
caller passing None for quantity/average_cost/current_price gets None
back for whichever output fields depend on it, not a guessed value.
"""

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class HoldingPnL:
    market_value: Decimal | None
    cost_basis: Decimal | None
    unrealized_pnl: Decimal | None
    unrealized_pnl_percent: Decimal | None


def calculate_holding_pnl(
    *,
    quantity: Decimal | None,
    average_cost: Decimal | None,
    current_price: Decimal | None,
) -> HoldingPnL:
    if quantity is None or current_price is None:
        market_value = None
    else:
        market_value = quantity * current_price

    if quantity is None or average_cost is None:
        cost_basis = None
    else:
        cost_basis = quantity * average_cost

    if market_value is None or cost_basis is None:
        unrealized_pnl = None
    else:
        unrealized_pnl = market_value - cost_basis

    # A zero cost basis makes the percentage mathematically undefined
    # (division by zero) — return None rather than crashing or inventing
    # a percentage, even though unrealized_pnl itself is still computable.
    if unrealized_pnl is None or cost_basis == 0:
        unrealized_pnl_percent = None
    else:
        unrealized_pnl_percent = (unrealized_pnl / cost_basis) * Decimal("100")

    return HoldingPnL(
        market_value=market_value,
        cost_basis=cost_basis,
        unrealized_pnl=unrealized_pnl,
        unrealized_pnl_percent=unrealized_pnl_percent,
    )
