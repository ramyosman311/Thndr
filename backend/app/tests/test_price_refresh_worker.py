"""Confirms the background refresh worker's entrypoint actually wires
services/price_orchestrator.py to a real database session and commits
-- i.e. that app/workers/price_refresh.py is not a dead/unused file
(spec: "must be callable independently")."""

from datetime import datetime, timezone
from decimal import Decimal

from app.models import AssetPriceConfig
from app.providers.base import ProviderQuote
from app.repositories import price_repository
from app.services import price_orchestrator
from app.tests.conftest import make_asset
from app.workers import price_refresh


async def test_run_price_refresh_persists_a_fetched_price(db_session, monkeypatch):
    asset = make_asset("WORKER1")
    db_session.add(asset)
    await db_session.flush()
    db_session.add(
        AssetPriceConfig(
            asset_id=asset.id,
            primary_provider="fake",
            primary_provider_symbol="WORKER1.SYM",
            automated_fetching_enabled=True,
        )
    )
    await db_session.commit()

    class _FakeProvider:
        name = "fake"

        async def get_price(self, provider_symbol: str) -> ProviderQuote:
            return ProviderQuote(
                price=Decimal("77.00"), currency="EGP", provider_symbol=provider_symbol,
                timestamp=datetime.now(timezone.utc),
            )

    monkeypatch.setattr(price_orchestrator, "get_provider", lambda name: _FakeProvider() if name == "fake" else None)

    class _NoCloseSession:
        """db_session is a fixture-managed session -- prevent the
        worker's `async with` from closing it out from under the test
        fixture's own teardown."""

        async def __aenter__(self):
            return db_session

        async def __aexit__(self, *exc_info):
            return False

    monkeypatch.setattr(price_refresh, "async_session_factory", lambda: _NoCloseSession())

    await price_refresh.run_price_refresh()

    latest = await price_repository.get_latest_price(db_session, asset.id)
    assert latest is not None
    assert latest.price == Decimal("77.00")
