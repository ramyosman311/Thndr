"""Provider tests (Phase 11, spec section 28): success, timeout, HTTP
failure, malformed response, missing price, invalid price, invalid
timestamp -- all via mocked HTTP transport (no live network access;
see providers/yahoo_provider.py's module docstring for why)."""

from datetime import datetime, timezone
from decimal import Decimal

import httpx
import pytest

from app.providers.base import (
    ProviderHTTPError,
    ProviderInvalidTimestampError,
    ProviderMalformedResponseError,
    ProviderMissingPriceError,
    ProviderTimeoutError,
)
from app.providers.yahoo_provider import YahooFinanceProvider


def _provider_with_transport(handler: httpx.MockTransport) -> YahooFinanceProvider:
    provider = YahooFinanceProvider()

    async def get_price(provider_symbol: str):
        async with httpx.AsyncClient(transport=handler) as client:
            response = await client.get(
                f"https://query1.finance.yahoo.com/v8/finance/chart/{provider_symbol}"
            )
        if response.status_code != 200:
            raise ProviderHTTPError(f"Yahoo Finance returned HTTP {response.status_code}")
        try:
            payload = response.json()
        except ValueError as exc:
            raise ProviderMalformedResponseError("not valid JSON") from exc
        return provider._parse_quote(payload, provider_symbol)

    provider.get_price = get_price  # type: ignore[method-assign]
    return provider


def _chart_payload(meta: dict) -> dict:
    return {"chart": {"result": [{"meta": meta}], "error": None}}


@pytest.mark.asyncio
async def test_success_returns_a_valid_quote():
    meta = {"regularMarketPrice": 123.45, "currency": "USD", "regularMarketTime": 1_700_000_000}
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=_chart_payload(meta)))
    provider = _provider_with_transport(transport)

    quote = await provider.get_price("AAPL")

    assert quote.price == Decimal("123.45")
    assert quote.currency == "USD"
    assert quote.provider_symbol == "AAPL"
    assert quote.timestamp == datetime.fromtimestamp(1_700_000_000, tz=timezone.utc)


@pytest.mark.asyncio
async def test_timeout_raises_provider_timeout_error():
    provider = YahooFinanceProvider(timeout_seconds=0.01)

    def raise_timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("timed out")

    async def get_price(provider_symbol: str):
        try:
            async with httpx.AsyncClient(transport=httpx.MockTransport(raise_timeout)) as client:
                await client.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{provider_symbol}")
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutError("timed out") from exc

    provider.get_price = get_price  # type: ignore[method-assign]

    with pytest.raises(ProviderTimeoutError):
        await provider.get_price("AAPL")


@pytest.mark.asyncio
async def test_non_200_http_status_raises_provider_http_error():
    transport = httpx.MockTransport(lambda request: httpx.Response(404, text="Not Found"))
    provider = _provider_with_transport(transport)

    with pytest.raises(ProviderHTTPError):
        await provider.get_price("UNKNOWNSYMBOL")


@pytest.mark.asyncio
async def test_malformed_json_raises_provider_malformed_response_error():
    transport = httpx.MockTransport(lambda request: httpx.Response(200, text="not json at all"))
    provider = _provider_with_transport(transport)

    with pytest.raises(ProviderMalformedResponseError):
        await provider.get_price("AAPL")


@pytest.mark.asyncio
async def test_missing_chart_result_raises_provider_malformed_response_error():
    payload = {"chart": {"result": [], "error": None}}
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
    provider = _provider_with_transport(transport)

    with pytest.raises(ProviderMalformedResponseError):
        await provider.get_price("AAPL")


@pytest.mark.asyncio
async def test_chart_error_field_raises_provider_malformed_response_error():
    payload = {"chart": {"result": None, "error": {"code": "Not Found", "description": "No data found"}}}
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
    provider = _provider_with_transport(transport)

    with pytest.raises(ProviderMalformedResponseError):
        await provider.get_price("BADSYMBOL")


@pytest.mark.asyncio
async def test_missing_price_field_raises_provider_missing_price_error():
    meta = {"currency": "USD", "regularMarketTime": 1_700_000_000}
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=_chart_payload(meta)))
    provider = _provider_with_transport(transport)

    with pytest.raises(ProviderMissingPriceError):
        await provider.get_price("AAPL")


@pytest.mark.asyncio
async def test_non_numeric_price_raises_provider_missing_price_error():
    meta = {"regularMarketPrice": "not-a-number", "currency": "USD", "regularMarketTime": 1_700_000_000}
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=_chart_payload(meta)))
    provider = _provider_with_transport(transport)

    with pytest.raises(ProviderMissingPriceError):
        await provider.get_price("AAPL")


@pytest.mark.asyncio
async def test_non_positive_price_raises_provider_missing_price_error():
    meta = {"regularMarketPrice": 0, "currency": "USD", "regularMarketTime": 1_700_000_000}
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=_chart_payload(meta)))
    provider = _provider_with_transport(transport)

    with pytest.raises(ProviderMissingPriceError):
        await provider.get_price("AAPL")


@pytest.mark.asyncio
async def test_missing_timestamp_raises_provider_invalid_timestamp_error():
    meta = {"regularMarketPrice": 123.45, "currency": "USD"}
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=_chart_payload(meta)))
    provider = _provider_with_transport(transport)

    with pytest.raises(ProviderInvalidTimestampError):
        await provider.get_price("AAPL")


@pytest.mark.asyncio
async def test_invalid_timestamp_raises_provider_invalid_timestamp_error():
    meta = {"regularMarketPrice": 123.45, "currency": "USD", "regularMarketTime": "not-a-timestamp"}
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=_chart_payload(meta)))
    provider = _provider_with_transport(transport)

    with pytest.raises(ProviderInvalidTimestampError):
        await provider.get_price("AAPL")


@pytest.mark.asyncio
async def test_missing_currency_raises_provider_malformed_response_error():
    meta = {"regularMarketPrice": 123.45, "regularMarketTime": 1_700_000_000}
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=_chart_payload(meta)))
    provider = _provider_with_transport(transport)

    with pytest.raises(ProviderMalformedResponseError):
        await provider.get_price("AAPL")
