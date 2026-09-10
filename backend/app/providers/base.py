"""The PriceProvider abstraction (Phase 11).

The core financial system (domain/, services/price_service.py, the
Portfolio/P&L/Allocation Engines) never knows how a provider obtains its
data — it only ever sees a `ProviderQuote` or a `ProviderError` subclass.
Adding a new provider means implementing this Protocol; nothing else in
the codebase needs to change (see ARCHITECTURE.md, "Price Provider
Abstraction").

Providers are used ONLY by the background refresh path
(services/price_orchestrator.py, app/workers/price_refresh.py) — never
by a request/response valuation read. See FINANCIAL_RULES.md,
"Non-Blocking Valuation".
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Protocol


@dataclass(frozen=True)
class ProviderQuote:
    """A raw quote as reported by one provider — not yet validated
    against manual precedence or stale policy; that happens in
    services/price_orchestrator.py and services/price_service.py."""

    price: Decimal
    currency: str
    provider_symbol: str
    timestamp: datetime
    raw: dict[str, Any] | None = None


class ProviderError(Exception):
    """Base class for every way a provider can fail to produce a usable
    quote. The orchestrator catches this (never a bare Exception) so one
    provider's failure can never take down the whole refresh batch or
    escape into a valuation request."""


class ProviderTimeoutError(ProviderError):
    """The provider did not respond within the configured timeout."""


class ProviderHTTPError(ProviderError):
    """The provider responded with a non-success HTTP status."""


class ProviderMalformedResponseError(ProviderError):
    """The response could not be parsed into the expected shape at all."""


class ProviderMissingPriceError(ProviderError):
    """The response parsed, but contained no usable price field."""


class ProviderInvalidTimestampError(ProviderError):
    """The response's price timestamp was missing or not a sane value."""


class PriceProvider(Protocol):
    """Implemented by every price provider adapter (Yahoo Finance, a
    future EGX/fund-NAV adapter, ...). `provider_symbol` is always taken
    from the asset's own configuration (`asset_price_configs`) — a
    provider never infers a symbol from an asset's internal `symbol`
    field or any other business identifier (see FINANCIAL_RULES.md,
    "Provider Configuration Is Data, Not Code")."""

    name: str

    async def get_price(self, provider_symbol: str) -> ProviderQuote:
        """Raises a `ProviderError` subclass on any failure — never
        returns a fabricated or partial quote."""
        ...
