"""Shared price-result vocabulary (Phase 11).

No I/O. These types are the common language between the Price Service
(read path), the Price Orchestrator (background-refresh write path), and
every valuation consumer (Portfolio/P&L/Allocation Engines, API schemas).
See FINANCIAL_RULES.md, "Price Result States".
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum


class PriceStatus(str, Enum):
    """What kind of price (if any) is usable for valuation right now.

    `CURRENT_PRICE_AVAILABLE`: a non-stale observation exists.
    `LAST_KNOWN_PRICE`: a real observation exists but is stale (per
    domain/stale_policy.py) — usable for valuation, but must never be
    presented to a user as live (see FINANCIAL_RULES.md, "Last-Known
    Price").
    `PRICE_UNAVAILABLE`: no observation exists at all. Never substitute
    zero or any other fabricated value.
    `CURRENCY_CONVERSION_UNAVAILABLE`: a price exists in the asset's own
    currency, but no FX rate exists to convert it into the portfolio's
    base currency — valuation must not proceed for this asset.
    """

    CURRENT = "CURRENT_PRICE_AVAILABLE"
    LAST_KNOWN = "LAST_KNOWN_PRICE"
    UNAVAILABLE = "PRICE_UNAVAILABLE"
    CURRENCY_CONVERSION_UNAVAILABLE = "CURRENCY_CONVERSION_UNAVAILABLE"


@dataclass(frozen=True)
class PriceResult:
    """The outcome of resolving "what price should we use for this asset
    right now" — always in the asset's OWN currency (see
    FINANCIAL_RULES.md, "FX Conversion" for how/when this gets converted
    into a portfolio's base currency separately)."""

    status: PriceStatus
    price: Decimal | None
    currency: str | None
    provider: str | None
    provider_symbol: str | None
    recorded_at: datetime | None
    age_seconds: float | None
    is_stale: bool
    reason: str | None = None

    @property
    def is_usable(self) -> bool:
        """True when `price` is a real, non-None Decimal a caller may
        multiply by a quantity — true for both CURRENT and LAST_KNOWN,
        false for the two unavailable states."""
        return self.status in (PriceStatus.CURRENT, PriceStatus.LAST_KNOWN)


def unavailable_price_result(reason: str) -> PriceResult:
    """The one place `PRICE_UNAVAILABLE` results are constructed, so every
    caller reports the same shape — never a fabricated zero price."""
    return PriceResult(
        status=PriceStatus.UNAVAILABLE,
        price=None,
        currency=None,
        provider=None,
        provider_symbol=None,
        recorded_at=None,
        age_seconds=None,
        is_stale=False,
        reason=reason,
    )
