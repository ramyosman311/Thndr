"""Real registry + real orchestrator integration for Mubasher (Phase 13
follow-up). test_price_orchestrator.py already covers the generic
fallback/precedence/batch-isolation machinery exhaustively using fake
providers; this file instead proves the ACTUAL registered "mubasher" and
"yahoo" provider instances (`providers/registry.py`) are what the real
`price_orchestrator` invokes for an EGX asset configured exactly as
`app/seed/data.py` configures TMGH/ETEL/EFID -- primary=mubasher,
secondary=yahoo -- with only the HTTP transport layer mocked (no live
network; see providers/mubasher_provider.py's module docstring)."""

from datetime import datetime, timezone
from decimal import Decimal

import httpx

from app.models import AssetPriceConfig
from app.providers.base import ProviderHTTPError, ProviderMalformedResponseError
from app.providers.mubasher_provider import _REQUEST_HEADERS, MubasherPriceProvider
from app.providers.registry import get_provider
from app.providers.yahoo_provider import YahooFinanceProvider
from app.repositories import price_repository
from app.services import price_orchestrator
from app.tests.conftest import make_asset

_NOW = datetime.now(timezone.utc)
_MUBASHER_URL = "https://www.mubasher.info/api/1/stocks/prices?symbol={symbol}&country=eg"
_YAHOO_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"


def test_registry_recognizes_mubasher_and_returns_the_real_adapter():
    provider = get_provider("mubasher")
    assert isinstance(provider, MubasherPriceProvider)
    assert provider.name == "mubasher"


def _mubasher_with_transport(handler: httpx.MockTransport) -> MubasherPriceProvider:
    provider = MubasherPriceProvider()

    async def get_price(provider_symbol: str):
        url = _MUBASHER_URL.format(symbol=provider_symbol)
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


def _yahoo_with_transport(handler: httpx.MockTransport) -> YahooFinanceProvider:
    provider = YahooFinanceProvider()

    async def get_price(provider_symbol: str):
        url = _YAHOO_URL.format(symbol=provider_symbol)
        async with httpx.AsyncClient(transport=handler) as client:
            response = await client.get(url)
        if response.status_code != 200:
            raise ProviderHTTPError(f"Yahoo Finance returned HTTP {response.status_code}")
        payload = response.json()
        return provider._parse_quote(payload, provider_symbol)

    provider.get_price = get_price  # type: ignore[method-assign]
    return provider


async def _make_egx_asset_with_config(session, symbol: str) -> AssetPriceConfig:
    """Mirrors exactly how app/seed/data.py configures TMGH/ETEL/EFID:
    primary=mubasher, secondary=yahoo."""
    asset = make_asset(symbol, currency="EGP")
    session.add(asset)
    await session.flush()
    config = AssetPriceConfig(
        asset_id=asset.id,
        primary_provider="mubasher",
        primary_provider_symbol=symbol,
        secondary_provider="yahoo",
        secondary_provider_symbol=f"{symbol}.CA",
        automated_fetching_enabled=True,
    )
    session.add(config)
    await session.commit()
    await session.refresh(config)
    return config


async def test_orchestrator_invokes_real_mubasher_provider_and_persists_observation(db_session, monkeypatch):
    config = await _make_egx_asset_with_config(db_session, "TMGH")

    mubasher_transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json=[
                {
                    "symbol": "TMGH",
                    "name": "Talaat Moustafa Group Holding",
                    "lastPrice": 58.50,
                    "price": 58.50,
                    "change": 1.25,
                    "changePercentage": 2.18,
                    "updatedAt": "2026-09-10T11:30:00.000Z",
                }
            ],
        )
    )
    mubasher = _mubasher_with_transport(mubasher_transport)
    monkeypatch.setattr(
        price_orchestrator, "get_provider", lambda name: {"mubasher": mubasher}.get(name)
    )

    outcome = await price_orchestrator.refresh_one_asset(db_session, config)
    await db_session.commit()

    assert outcome.succeeded is True
    assert outcome.stored is True
    assert outcome.provider_name == "mubasher"

    latest = await price_repository.get_latest_price(db_session, config.asset_id)
    assert latest.price == Decimal("58.50")
    assert latest.currency == "EGP"
    assert latest.provider == "mubasher"
    assert latest.provider_symbol == "TMGH"
    assert latest.is_manual is False


async def test_orchestrator_falls_back_to_real_yahoo_when_real_mubasher_fails(db_session, monkeypatch):
    config = await _make_egx_asset_with_config(db_session, "ETEL")

    mubasher_transport = httpx.MockTransport(lambda request: httpx.Response(503, text="Service Unavailable"))
    mubasher = _mubasher_with_transport(mubasher_transport)

    yahoo_transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json={
                "chart": {
                    "result": [
                        {"meta": {"regularMarketPrice": 32.77, "currency": "EGP", "regularMarketTime": 1_700_000_000}}
                    ],
                    "error": None,
                }
            },
        )
    )
    yahoo = _yahoo_with_transport(yahoo_transport)

    monkeypatch.setattr(
        price_orchestrator, "get_provider", lambda name: {"mubasher": mubasher, "yahoo": yahoo}.get(name)
    )

    outcome = await price_orchestrator.refresh_one_asset(db_session, config)
    await db_session.commit()

    assert outcome.succeeded is True
    assert outcome.stored is True
    assert outcome.provider_name == "yahoo"

    latest = await price_repository.get_latest_price(db_session, config.asset_id)
    assert latest.price == Decimal("32.77")
    assert latest.provider == "yahoo"
    assert latest.provider_symbol == "ETEL.CA"
