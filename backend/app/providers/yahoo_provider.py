"""Yahoo Finance provider adapter (Phase 11).

Calls Yahoo Finance's public (undocumented but widely used and stable in
practice) chart API directly via `httpx` rather than the `yfinance`
PyPI package -- `httpx` is already a project dependency, and adding a
whole extra library for one provider was judged unnecessary.

IMPORTANT -- environment limitation: this sandbox's outbound HTTPS proxy
does not allow `query1.finance.yahoo.com` (confirmed 403 at the proxy),
so this adapter's live network reachability could not be verified here.
Its request construction and, especially, its response parsing / error
mapping are instead verified by unit tests
(tests/test_providers_yahoo.py) against mocked HTTP responses that match
Yahoo's real, documented chart-API response shape:

    GET https://query1.finance.yahoo.com/v8/finance/chart/{symbol}
    -> {"chart": {"result": [{"meta": {
            "regularMarketPrice": <float>,
            "currency": <str>,
            "regularMarketTime": <int, unix seconds>
        }, ...}], "error": null}}

This adapter never guesses or transforms a symbol -- `provider_symbol`
is always exactly what is stored in `asset_price_configs`
(`primary_provider_symbol` / `secondary_provider_symbol`); whether a
given symbol/market is actually supported by Yahoo is a configuration
question, not something this code tries to infer (see
FINANCIAL_RULES.md, "Provider Configuration Is Data, Not Code").
"""

from datetime import datetime, timezone
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

_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
_DEFAULT_TIMEOUT_SECONDS = 10.0


class YahooFinanceProvider(PriceProvider):
    """Fetches a single latest quote for `provider_symbol` from Yahoo
    Finance's chart endpoint. Never assumes every symbol/market is
    supported -- an unsupported or unknown symbol surfaces as a
    `ProviderHTTPError` or `ProviderMalformedResponseError`, which the
    orchestrator treats like any other provider failure (try the
    secondary provider, or fall back to the latest DB observation)."""

    name = "yahoo"

    def __init__(self, timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS) -> None:
        self._timeout_seconds = timeout_seconds

    async def get_price(self, provider_symbol: str) -> ProviderQuote:
        url = _CHART_URL.format(symbol=provider_symbol)
        try:
            async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
                response = await client.get(url)
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutError(f"Yahoo Finance request timed out for {provider_symbol!r}") from exc
        except httpx.HTTPError as exc:
            raise ProviderHTTPError(f"Yahoo Finance request failed for {provider_symbol!r}: {exc}") from exc

        if response.status_code != 200:
            raise ProviderHTTPError(
                f"Yahoo Finance returned HTTP {response.status_code} for {provider_symbol!r}"
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise ProviderMalformedResponseError(
                f"Yahoo Finance response for {provider_symbol!r} was not valid JSON"
            ) from exc

        return self._parse_quote(payload, provider_symbol)

    @staticmethod
    def _parse_quote(payload: dict, provider_symbol: str) -> ProviderQuote:
        try:
            chart = payload["chart"]
        except (KeyError, TypeError) as exc:
            raise ProviderMalformedResponseError(
                f"Yahoo Finance response for {provider_symbol!r} had no 'chart' key"
            ) from exc

        if chart.get("error"):
            raise ProviderMalformedResponseError(
                f"Yahoo Finance reported an error for {provider_symbol!r}: {chart['error']}"
            )

        results = chart.get("result")
        if not results or not isinstance(results, list):
            raise ProviderMalformedResponseError(
                f"Yahoo Finance response for {provider_symbol!r} had no result -- symbol may be unsupported"
            )

        meta = results[0].get("meta")
        if not isinstance(meta, dict):
            raise ProviderMalformedResponseError(
                f"Yahoo Finance response for {provider_symbol!r} had no 'meta' object"
            )

        raw_price = meta.get("regularMarketPrice")
        if raw_price is None:
            raise ProviderMissingPriceError(
                f"Yahoo Finance response for {provider_symbol!r} had no regularMarketPrice"
            )
        try:
            price = Decimal(str(raw_price))
        except (InvalidOperation, ValueError) as exc:
            raise ProviderMissingPriceError(
                f"Yahoo Finance regularMarketPrice for {provider_symbol!r} was not a valid number: {raw_price!r}"
            ) from exc
        if price <= 0:
            raise ProviderMissingPriceError(
                f"Yahoo Finance regularMarketPrice for {provider_symbol!r} was not positive: {price}"
            )

        currency = meta.get("currency")
        if not currency or not isinstance(currency, str):
            raise ProviderMalformedResponseError(
                f"Yahoo Finance response for {provider_symbol!r} had no usable currency"
            )

        raw_timestamp = meta.get("regularMarketTime")
        if raw_timestamp is None:
            raise ProviderInvalidTimestampError(
                f"Yahoo Finance response for {provider_symbol!r} had no regularMarketTime"
            )
        try:
            timestamp = datetime.fromtimestamp(int(raw_timestamp), tz=timezone.utc)
        except (TypeError, ValueError, OSError) as exc:
            raise ProviderInvalidTimestampError(
                f"Yahoo Finance regularMarketTime for {provider_symbol!r} was not a valid timestamp: {raw_timestamp!r}"
            ) from exc

        return ProviderQuote(
            price=price,
            currency=currency,
            provider_symbol=provider_symbol,
            timestamp=timestamp,
            raw=meta,
        )
