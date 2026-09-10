"""Resolves a provider-name string (as stored in
`asset_price_configs.primary_provider` / `secondary_provider`) into a
`PriceProvider` instance for the background orchestrator to call.

"manual" is deliberately NOT registered here. Manual price entry is a
push (a user submits a value), not a pull (`get_price(symbol) ->
quote`), so it does not fit the `PriceProvider` Protocol shape at all.
Manual submissions are written directly by
`services/price_service.record_manual_price`, never by asking a fake
"ManualProvider" to "fetch" a price (see FINANCIAL_RULES.md, "Manual
Pricing Is Not A Provider").

This module holds no provider credentials -- it only wires up which
provider class handles which name (see ARCHITECTURE.md, "Adding A New
Provider").
"""

from app.providers.base import PriceProvider
from app.providers.yahoo_provider import YahooFinanceProvider

_PROVIDERS: dict[str, PriceProvider] = {
    "yahoo": YahooFinanceProvider(),
}


def get_provider(provider_name: str | None) -> PriceProvider | None:
    """Returns the registered provider for `provider_name`, or None if
    unset or unregistered (e.g. an asset configured for an EGX/fund-NAV
    provider that has no implemented adapter yet -- see
    FINANCIAL_RULES.md, "Unconfigured Providers Are Not Errors")."""
    if provider_name is None:
        return None
    return _PROVIDERS.get(provider_name)


def is_registered_provider_name(provider_name: str) -> bool:
    """Used by Phase 12 asset-price-config administration to validate a
    submitted provider name against the actual registry -- never assume
    a string is a valid provider merely because it was entered (see
    FINANCIAL_RULES.md, "Provider Configuration Is Data, Not Code")."""
    return provider_name in _PROVIDERS


def registered_provider_names() -> list[str]:
    """The full set of currently implemented provider names, for the
    admin UI to offer as choices rather than a free-text field."""
    return sorted(_PROVIDERS)
