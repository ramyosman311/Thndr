"""Mubasher Egypt provider adapter (Phase 13 follow-up).

Calls Mubasher's public stocks-prices JSON endpoint directly via `httpx`,
following the exact same construction/error-handling pattern already
established by `providers/yahoo_provider.py` -- no new HTTP client, error
model, or persistence mechanism is introduced.

IMPORTANT -- environment limitation, mock-driven only: this sandbox's
outbound HTTPS proxy denies `www.mubasher.info` (confirmed 403 at the
proxy, same default-deny policy that also blocks Yahoo Finance, EGID, and
EGXAPI from this environment -- see DECISIONS.md), so this adapter's live
network reachability could not be verified here. Its request construction
and response parsing / error mapping are instead verified by unit tests
(tests/test_providers_mubasher.py) against a payload shape independently
confirmed via a live network test performed OUTSIDE this sandbox:

    GET https://www.mubasher.info/api/1/stocks/prices?symbol={symbol}&country=eg
    -> [{"symbol": "TMGH", "name": "...", "lastPrice": 58.50, "price": 58.50,
         "change": 1.25, "changePercentage": 2.18,
         "updatedAt": "2026-09-10T11:30:00.000Z"}]

    (a single JSON object, rather than a one-element list, is also
    supported, since the endpoint's exact response shape per-symbol was
    not independently confirmed to always be a list.)

This adapter never guesses or transforms a symbol -- `provider_symbol` is
always exactly what is stored in `asset_price_configs`
(`primary_provider_symbol` / `secondary_provider_symbol`); see
FINANCIAL_RULES.md, "Provider Configuration Is Data, Not Code".

Currency: the verified payload has no currency field at all (not merely
sometimes missing -- it is simply not part of this endpoint's schema).
This is NOT treated as a malformed response, because the endpoint itself
is architecturally Egypt-only by construction (the request always sends
`country=eg`, a fixed property of this provider, not something inferred
per-asset). `EGP` is therefore used as this provider's fixed reporting
currency for every quote it returns. This is a disclosed adapter-level
decision, not a per-asset inference and not a fabricated field pulled
from the response -- see DECISIONS.md, "Mubasher Provider Decision".
"""

from datetime import datetime
from decimal import Decimal, InvalidOperation

import httpx

from app.providers.base import (
    PriceProvider,
    ProviderHTTPError,
    ProviderInvalidTimestampError,
    ProviderMalformedResponseError,
    ProviderMissingPriceError,
    ProviderQuote,
    ProviderTimeoutError,
)

_PRICES_URL = "https://www.mubasher.info/api/1/stocks/prices?symbol={symbol}&country=eg"
_DEFAULT_TIMEOUT_SECONDS = 10.0
_REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Accept": "application/json",
    "Referer": "https://www.mubasher.info/",
}

# This endpoint's schema has no currency field; see module docstring.
_FIXED_CURRENCY = "EGP"


class MubasherPriceProvider(PriceProvider):
    """Fetches a single latest quote for `provider_symbol` from Mubasher's
    Egypt stocks-prices endpoint. Never assumes every symbol is supported
    -- an unknown symbol or an empty result surfaces as a
    `ProviderMalformedResponseError`, which the orchestrator treats like
    any other provider failure (try the secondary provider, or fall back
    to the latest DB observation)."""

    name = "mubasher"

    def __init__(self, timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS) -> None:
        self._timeout_seconds = timeout_seconds

    async def get_price(self, provider_symbol: str) -> ProviderQuote:
        url = _PRICES_URL.format(symbol=provider_symbol)
        try:
            async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
                response = await client.get(url, headers=_REQUEST_HEADERS)
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutError(f"Mubasher request timed out for {provider_symbol!r}") from exc
        except httpx.HTTPError as exc:
            raise ProviderHTTPError(f"Mubasher request failed for {provider_symbol!r}: {exc}") from exc

        if response.status_code != 200:
            raise ProviderHTTPError(f"Mubasher returned HTTP {response.status_code} for {provider_symbol!r}")

        try:
            payload = response.json()
        except ValueError as exc:
            raise ProviderMalformedResponseError(
                f"Mubasher response for {provider_symbol!r} was not valid JSON"
            ) from exc

        return self._parse_quote(payload, provider_symbol)

    @staticmethod
    def _parse_quote(payload: object, provider_symbol: str) -> ProviderQuote:
        if isinstance(payload, list):
            if not payload:
                raise ProviderMalformedResponseError(
                    f"Mubasher response for {provider_symbol!r} was an empty list -- symbol may be unsupported"
                )
            item = payload[0]
        elif isinstance(payload, dict):
            item = payload
        else:
            raise ProviderMalformedResponseError(
                f"Mubasher response for {provider_symbol!r} was neither a list nor an object"
            )

        if not isinstance(item, dict):
            raise ProviderMalformedResponseError(
                f"Mubasher response item for {provider_symbol!r} was not an object"
            )

        raw_price = item.get("lastPrice")
        if raw_price is None:
            raw_price = item.get("price")
        if raw_price is None:
            raise ProviderMissingPriceError(
                f"Mubasher response for {provider_symbol!r} had no lastPrice or price"
            )
        try:
            price = Decimal(str(raw_price))
        except (InvalidOperation, ValueError) as exc:
            raise ProviderMissingPriceError(
                f"Mubasher price for {provider_symbol!r} was not a valid number: {raw_price!r}"
            ) from exc
        if price <= 0:
            raise ProviderMissingPriceError(
                f"Mubasher price for {provider_symbol!r} was not positive: {price}"
            )

        raw_timestamp = item.get("updatedAt")
        if not raw_timestamp or not isinstance(raw_timestamp, str):
            raise ProviderInvalidTimestampError(
                f"Mubasher response for {provider_symbol!r} had no updatedAt"
            )
        try:
            timestamp = datetime.fromisoformat(raw_timestamp.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ProviderInvalidTimestampError(
                f"Mubasher updatedAt for {provider_symbol!r} was not a valid timestamp: {raw_timestamp!r}"
            ) from exc

        return ProviderQuote(
            price=price,
            currency=_FIXED_CURRENCY,
            provider_symbol=provider_symbol,
            timestamp=timestamp,
            raw=item,
        )
