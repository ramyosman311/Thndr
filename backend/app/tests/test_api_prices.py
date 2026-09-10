import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.core.database import get_db_session
from app.main import app
from app.models import AssetPriceConfig
from app.providers.base import ProviderQuote
from app.services import price_orchestrator
from app.tests.conftest import make_asset, make_current_price


@pytest_asyncio.fixture
async def client(db_session):
    async def _override_get_db_session():
        yield db_session

    app.dependency_overrides[get_db_session] = _override_get_db_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.pop(get_db_session, None)


async def _create_asset(session, symbol="APIPRICE", currency="EGP"):
    asset = make_asset(symbol, currency=currency)
    session.add(asset)
    await session.commit()
    return asset


async def test_get_price_returns_unavailable_when_no_observation(db_session, client):
    asset = await _create_asset(db_session)
    response = await client.get(f"/api/assets/{asset.id}/price")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "PRICE_UNAVAILABLE"
    assert body["price"] is None


async def test_get_price_returns_current_after_seeding(db_session, client):
    asset = await _create_asset(db_session)
    await make_current_price(db_session, asset, Decimal("42.50"))
    await db_session.commit()

    response = await client.get(f"/api/assets/{asset.id}/price")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "CURRENT_PRICE_AVAILABLE"
    assert Decimal(body["price"]) == Decimal("42.50")
    assert body["is_stale"] is False


async def test_get_price_404_for_missing_asset(client):
    response = await client.get(f"/api/assets/{uuid.uuid4()}/price")
    assert response.status_code == 404


async def test_list_prices_returns_history_most_recent_first(db_session, client):
    asset = await _create_asset(db_session)
    await make_current_price(db_session, asset, Decimal("10"))
    await make_current_price(db_session, asset, Decimal("20"))
    await db_session.commit()

    response = await client.get(f"/api/assets/{asset.id}/prices")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 2
    assert Decimal(body[0]["price"]) == Decimal("20")  # most recent first
    assert Decimal(body[1]["price"]) == Decimal("10")


async def test_manual_price_creation_is_reflected_in_get_price(db_session, client):
    asset = await _create_asset(db_session, currency="EGP")
    response = await client.post(
        f"/api/assets/{asset.id}/price/manual", json={"price": "99.99", "currency": "EGP"}
    )
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "CURRENT_PRICE_AVAILABLE"
    assert Decimal(body["price"]) == Decimal("99.99")

    follow_up = await client.get(f"/api/assets/{asset.id}/price")
    assert Decimal(follow_up.json()["price"]) == Decimal("99.99")


async def test_manual_price_rejects_non_positive_price(db_session, client):
    asset = await _create_asset(db_session)
    response = await client.post(f"/api/assets/{asset.id}/price/manual", json={"price": "0", "currency": "EGP"})
    assert response.status_code == 422


async def test_manual_price_rejects_mismatched_currency(db_session, client):
    asset = await _create_asset(db_session, currency="EGP")
    response = await client.post(f"/api/assets/{asset.id}/price/manual", json={"price": "10", "currency": "USD"})
    assert response.status_code == 400


async def test_refresh_returns_409_when_no_provider_configured(db_session, client):
    asset = await _create_asset(db_session)
    response = await client.post(f"/api/assets/{asset.id}/price/refresh")
    assert response.status_code == 409


async def test_refresh_fetches_and_stores_a_new_price(db_session, client, monkeypatch):
    asset = await _create_asset(db_session)
    db_session.add(
        AssetPriceConfig(
            asset_id=asset.id,
            primary_provider="fake",
            primary_provider_symbol="APIPRICE.SYM",
            automated_fetching_enabled=True,
        )
    )
    await db_session.commit()

    class _FakeProvider:
        name = "fake"

        async def get_price(self, provider_symbol: str) -> ProviderQuote:
            return ProviderQuote(
                price=Decimal("123.45"),
                currency="EGP",
                provider_symbol=provider_symbol,
                timestamp=datetime.now(timezone.utc),
            )

    monkeypatch.setattr(
        price_orchestrator, "get_provider", lambda name: _FakeProvider() if name == "fake" else None
    )

    response = await client.post(f"/api/assets/{asset.id}/price/refresh")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "CURRENT_PRICE_AVAILABLE"
    assert Decimal(body["price"]) == Decimal("123.45")
    assert body["provider"] == "fake"
