"""Pure portfolio value calculations.

No I/O, no database session, no framework imports — everything here is a
plain function/dataclass over Decimal values, independently testable and
reusable by services and future workers alike (see ARCHITECTURE.md,
"Backend Layering").

`Holding.quantity` and `Holding.current_price` are NOT NULL database
columns (default 0), so an asset genuinely not held is a known zero
position here, never an "unknown" one. A caller that truly cannot supply
a current price for a held asset should not call into this module with a
fabricated price — that concern belongs to callers/repositories, not this
module.
"""

from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID


@dataclass(frozen=True)
class AssetPosition:
    """A DB-independent snapshot of one asset's current position."""

    asset_id: UUID
    symbol: str
    is_emergency: bool
    strategy_bucket_id: UUID | None
    quantity: Decimal
    current_price: Decimal

    @property
    def value(self) -> Decimal:
        return self.quantity * self.current_price


@dataclass(frozen=True)
class PortfolioTotals:
    total_value: Decimal
    emergency_value: Decimal
    investable_value: Decimal
    denominator_value: Decimal
    denominator_basis: str  # "investable" | "total"
    denominator_is_zero: bool


def calculate_portfolio_totals(
    positions: list[AssetPosition], *, emergency_excluded: bool
) -> PortfolioTotals:
    """Total Portfolio Value = Emergency Cash + Investable Portfolio, always.

    `emergency_excluded` (from portfolio_configs, never hardcoded) decides
    only which value is used as the allocation-percentage denominator:
    the investable value when excluded, the total value otherwise (see
    FINANCIAL_RULES.md, "Emergency Cash").
    """
    emergency_value = Decimal("0")
    investable_value = Decimal("0")

    for position in positions:
        if position.is_emergency:
            emergency_value += position.value
        else:
            investable_value += position.value

    total_value = emergency_value + investable_value
    if emergency_excluded:
        denominator_value = investable_value
        denominator_basis = "investable"
    else:
        denominator_value = total_value
        denominator_basis = "total"

    return PortfolioTotals(
        total_value=total_value,
        emergency_value=emergency_value,
        investable_value=investable_value,
        denominator_value=denominator_value,
        denominator_basis=denominator_basis,
        denominator_is_zero=denominator_value == 0,
    )
