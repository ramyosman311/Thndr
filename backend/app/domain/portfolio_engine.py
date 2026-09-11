"""Pure portfolio value calculations.

No I/O, no database session, no framework imports — everything here is a
plain function/dataclass over Decimal values, independently testable and
reusable by services and future workers alike (see ARCHITECTURE.md,
"Backend Layering").

`current_price` is `Decimal | None` (Phase 11): a genuinely held asset
(`quantity > 0`) whose price cannot currently be determined (see
services/price_service.py) is represented as `None`, never as a
fabricated zero or a stale value presented as current — see
FINANCIAL_RULES.md, "Never Fabricate A Price". A zero-quantity position
always values at exactly 0 regardless of price availability -- there is
nothing to price, so its valuation is never "incomplete". This module
never fetches or converts a price itself; callers (services/
portfolio_shared.py) supply an already-resolved, already-base-currency
`current_price` per position.
"""

from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID


# Asset types treated as cash-equivalent for the Available/Investable Cash
# split (Phase 16) -- exactly the same two types Phase 15 restricted
# DEPOSIT/WITHDRAWAL to (see domain/transaction_engine.py). A position of
# either type that is NOT the configured emergency asset is "available
# cash"; everything else non-emergency is "invested market value". This
# is a presentation-level split only -- it changes neither `total_value`
# nor `investable_value`/the allocation-percentage denominator below,
# which keep their existing, separately-approved meaning (see
# FINANCIAL_RULES.md, "Investable Cash Is Not The Allocation Denominator").
_CASH_LIKE_ASSET_TYPES = frozenset({"CASH", "SAVINGS"})


@dataclass(frozen=True)
class AssetPosition:
    """A DB-independent snapshot of one asset's current position."""

    asset_id: UUID
    symbol: str
    asset_type: str
    is_emergency: bool
    strategy_bucket_id: UUID | None
    quantity: Decimal
    current_price: Decimal | None

    @property
    def value(self) -> Decimal | None:
        if self.quantity == 0:
            return Decimal("0")
        if self.current_price is None:
            return None
        return self.quantity * self.current_price

    @property
    def is_cash_like(self) -> bool:
        return self.asset_type in _CASH_LIKE_ASSET_TYPES


@dataclass(frozen=True)
class PortfolioTotals:
    total_value: Decimal
    emergency_value: Decimal
    investable_value: Decimal
    denominator_value: Decimal
    denominator_basis: str  # "investable" | "total"
    denominator_is_zero: bool
    # Phase 16: `investable_value` above is split further into the part
    # that is actual spendable cash and the part that is invested in
    # priced positions. `available_cash` = value of non-emergency
    # CASH/SAVINGS holdings only -- this, and ONLY this, is what a user
    # could deploy into a new purchase right now (see FINANCIAL_RULES.md,
    # "Available Cash vs Investable Value"). `invested_market_value` =
    # value of every other non-emergency holding. By construction:
    # investable_value == available_cash + invested_market_value, and
    # total_value == emergency_value + available_cash + invested_market_value.
    available_cash: Decimal
    invested_market_value: Decimal
    # Asset IDs held in a non-zero quantity but excluded from every sum
    # above because no usable price was available -- the valuation is
    # INCOMPLETE, never silently treated as if those positions were
    # worth zero (see FINANCIAL_RULES.md, "Incomplete Valuation Is Not
    # Zero Valuation").
    unpriced_asset_ids: frozenset[UUID] = frozenset()

    @property
    def is_complete(self) -> bool:
        return not self.unpriced_asset_ids


def calculate_portfolio_totals(
    positions: list[AssetPosition], *, emergency_excluded: bool
) -> PortfolioTotals:
    """Total Portfolio Value = Emergency Cash + Investable Portfolio, always.

    `emergency_excluded` (from portfolio_configs, never hardcoded) decides
    only which value is used as the allocation-percentage denominator:
    the investable value when excluded, the total value otherwise (see
    FINANCIAL_RULES.md, "Emergency Cash").

    A position whose value is unavailable (see `AssetPosition.value`) is
    excluded from every sum -- never counted as 0 -- and its asset_id is
    recorded in `unpriced_asset_ids` so callers can expose an incomplete
    valuation rather than a silently understated one.
    """
    emergency_value = Decimal("0")
    investable_value = Decimal("0")
    available_cash = Decimal("0")
    invested_market_value = Decimal("0")
    unpriced_asset_ids: set[UUID] = set()

    for position in positions:
        value = position.value
        if value is None:
            unpriced_asset_ids.add(position.asset_id)
            continue
        if position.is_emergency:
            emergency_value += value
        else:
            investable_value += value
            if position.is_cash_like:
                available_cash += value
            else:
                invested_market_value += value

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
        available_cash=available_cash,
        invested_market_value=invested_market_value,
        unpriced_asset_ids=frozenset(unpriced_asset_ids),
    )
