"""Mubasher provider tests: success (list and single-object response),
lastPrice/price fallback, missing/null/zero/negative price, empty list,
malformed JSON, HTTP failure, timeout, network exception, symbol/URL
construction, and request headers -- all via mocked HTTP transport (no
live network access; see providers/mubasher_provider.py's module
docstring for why -- this sandbox's outbound network blocks
www.mubasher.info, the same default-deny policy that also blocks Yahoo
Finance, EGID, and EGXAPI). The verified payload shape used below was
independently confirmed via a live network test performed OUTSIDE this
sandbox, not fabricated here.
"""

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
from app.providers.mubasher_provider import _REQUEST_HEADERS, MubasherPriceProvider

_URL_TEMPLATE = "https://www.mubasher.info/api/1/stocks/prices?symbol={symbol}&country=eg"


def _provider_with_transport(handler: httpx.MockTransport) -> MubasherPriceProvider:
    provider = MubasherPriceProvider()

    async def get_price(provider_symbol: str):
        url = _URL_TEMPLATE.format(symbol=provider_symbol)
        async with httpx.AsyncClient(transport=handler) as client:
            response = await client.get(url, headers=_REQUEST_HEADERS)
        if response.status_code != 200:
            raise ProviderHTTPError(f"Mubasher returned HTTP {response.status_code}")
        try:
            payload = response.json()
        except ValueError as exc:
            raise ProviderMalformedResponseError("not valid JSON") from exc
        return provider._parse_quote(payload, provider_symbol)

    provider.get_price = get_price  # type: ignore[method-assign]
    return provider


def _verified_item(symbol: str = "TMGH", **overrides) -> dict:
    item = {
        "symbol": symbol,
        "name": "Talaat Moustafa Group Holding",
        "lastPrice": 58.50,
        "price": 58.50,
        "change": 1.25,
        "changePercentage": 2.18,
        "updatedAt": "2026-09-10T11:30:00.000Z",
    }
    item.update(overrides)
    return item


# --- A: verified list response --------------------------------------------


@pytest.mark.asyncio
async def test_verified_list_response_returns_exact_decimal_price():
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=[_verified_item()]))
    provider = _provider_with_transport(transport)

    quote = await provider.get_price("TMGH")

    assert quote.price == Decimal("58.50")
    assert quote.currency == "EGP"
    assert quote.provider_symbol == "TMGH"
    assert quote.timestamp == datetime(2026, 9, 10, 11, 30, 0, tzinfo=timezone.utc)
    assert quote.raw["change"] == 1.25
    assert quote.raw["changePercentage"] == 2.18


# --- B: single-object response ---------------------------------------------


@pytest.mark.asyncio
async def test_single_object_response_is_supported():
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=_verified_item()))
    provider = _provider_with_transport(transport)

    quote = await provider.get_price("TMGH")

    assert quote.price == Decimal("58.50")
    assert quote.currency == "EGP"


# --- C: lastPrice missing but valid price present ---------------------------


@pytest.mark.asyncio
async def test_falls_back_to_price_when_last_price_missing():
    item = _verified_item()
    del item["lastPrice"]
    item["price"] = 61.10
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=[item]))
    provider = _provider_with_transport(transport)

    quote = await provider.get_price("TMGH")

    assert quote.price == Decimal("61.1")


# --- D: missing/null price ---------------------------------------------------


@pytest.mark.asyncio
async def test_missing_price_and_last_price_raises_missing_price_error():
    item = _verified_item()
    del item["lastPrice"]
    del item["price"]
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=[item]))
    provider = _provider_with_transport(transport)

    with pytest.raises(ProviderMissingPriceError):
        await provider.get_price("TMGH")


@pytest.mark.asyncio
async def test_null_price_raises_missing_price_error():
    item = _verified_item(lastPrice=None, price=None)
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=[item]))
    provider = _provider_with_transport(transport)

    with pytest.raises(ProviderMissingPriceError):
        await provider.get_price("TMGH")


# --- E: zero price -----------------------------------------------------------


@pytest.mark.asyncio
async def test_zero_price_raises_missing_price_error():
    item = _verified_item(lastPrice=0, price=0)
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=[item]))
    provider = _provider_with_transport(transport)

    with pytest.raises(ProviderMissingPriceError):
        await provider.get_price("TMGH")


# --- F: negative price --------------------------------------------------------


@pytest.mark.asyncio
async def test_negative_price_raises_missing_price_error():
    item = _verified_item(lastPrice=-5.0)
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=[item]))
    provider = _provider_with_transport(transport)

    with pytest.raises(ProviderMissingPriceError):
        await provider.get_price("TMGH")


# --- G: empty list -------------------------------------------------------------


@pytest.mark.asyncio
async def test_empty_list_raises_malformed_response_error():
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=[]))
    provider = _provider_with_transport(transport)

    with pytest.raises(ProviderMalformedResponseError):
        await provider.get_price("UNKNOWNSYMBOL")


# --- H: malformed JSON ----------------------------------------------------------


@pytest.mark.asyncio
async def test_malformed_json_raises_malformed_response_error():
    transport = httpx.MockTransport(lambda request: httpx.Response(200, text="not json at all"))
    provider = _provider_with_transport(transport)

    with pytest.raises(ProviderMalformedResponseError):
        await provider.get_price("TMGH")


# --- I: HTTP 403 ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_http_403_raises_provider_http_error():
    transport = httpx.MockTransport(lambda request: httpx.Response(403, text="Forbidden"))
    provider = _provider_with_transport(transport)

    with pytest.raises(ProviderHTTPError):
        await provider.get_price("TMGH")


# --- J: HTTP 500 ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_http_500_raises_provider_http_error():
    transport = httpx.MockTransport(lambda request: httpx.Response(500, text="Internal Server Error"))
    provider = _provider_with_transport(transport)

    with pytest.raises(ProviderHTTPError):
        await provider.get_price("TMGH")


# --- Missing/invalid updatedAt -----------------------------------------------------


@pytest.mark.asyncio
async def test_missing_updated_at_raises_invalid_timestamp_error():
    item = _verified_item()
    del item["updatedAt"]
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=[item]))
    provider = _provider_with_transport(transport)

    with pytest.raises(ProviderInvalidTimestampError):
        await provider.get_price("TMGH")


@pytest.mark.asyncio
async def test_invalid_updated_at_raises_invalid_timestamp_error():
    item = _verified_item(updatedAt="not-a-timestamp")
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=[item]))
    provider = _provider_with_transport(transport)

    with pytest.raises(ProviderInvalidTimestampError):
        await provider.get_price("TMGH")


# --- K: network timeout ------------------------------------------------------------


@pytest.mark.asyncio
async def test_timeout_raises_provider_timeout_error():
    provider = MubasherPriceProvider(timeout_seconds=0.01)

    def raise_timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("timed out")

    async def get_price(provider_symbol: str):
        try:
            async with httpx.AsyncClient(transport=httpx.MockTransport(raise_timeout)) as client:
                await client.get(_URL_TEMPLATE.format(symbol=provider_symbol))
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutError("timed out") from exc

    provider.get_price = get_price  # type: ignore[method-assign]

    with pytest.raises(ProviderTimeoutError):
        await provider.get_price("TMGH")


# --- L: network exception (non-timeout) -----------------------------------------


@pytest.mark.asyncio
async def test_generic_network_exception_raises_provider_http_error():
    provider = MubasherPriceProvider()

    def raise_connect_error(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    async def get_price(provider_symbol: str):
        try:
            async with httpx.AsyncClient(transport=httpx.MockTransport(raise_connect_error)) as client:
                await client.get(_URL_TEMPLATE.format(symbol=provider_symbol))
        except httpx.HTTPError as exc:
            raise ProviderHTTPError(f"Mubasher request failed: {exc}") from exc

    provider.get_price = get_price  # type: ignore[method-assign]

    with pytest.raises(ProviderHTTPError):
        await provider.get_price("TMGH")


# --- M: URL/symbol construction for TMGH, ETEL, EFID -----------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("symbol", ["TMGH", "ETEL", "EFID"])
async def test_url_construction_uses_exact_symbol_and_country_eg(symbol):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(200, json=[_verified_item(symbol=symbol)])

    transport = httpx.MockTransport(handler)
    provider = _provider_with_transport(transport)

    await provider.get_price(symbol)

    assert captured["url"] == f"https://www.mubasher.info/api/1/stocks/prices?symbol={symbol}&country=eg"


# --- N: required request headers -------------------------------------------------


@pytest.mark.asyncio
async def test_sends_expected_request_headers():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["headers"] = request.headers
        return httpx.Response(200, json=[_verified_item()])

    transport = httpx.MockTransport(handler)
    provider = _provider_with_transport(transport)

    await provider.get_price("TMGH")

    headers = captured["headers"]
    assert headers["User-Agent"] == _REQUEST_HEADERS["User-Agent"]
    assert headers["Accept"] == "application/json"
    assert headers["Referer"] == "https://www.mubasher.info/"


# --- Cross-symbol schema consistency (no accidental divergence) ------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("symbol", ["TMGH", "ETEL", "EFID"])
async def test_each_symbol_parses_via_the_identical_schema(symbol):
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json=[_verified_item(symbol=symbol, lastPrice=42.00)])
    )
    provider = _provider_with_transport(transport)

    quote = await provider.get_price(symbol)

    assert quote.price == Decimal("42.00")
    assert quote.currency == "EGP"
    assert quote.provider_symbol == symbol
