"""Price Orchestrator tests (Phase 11, spec section 29): the generic
Primary -> Secondary -> (nothing stored) fallback chain, one provider
failure never stopping the batch, and manual-vs-automated precedence
enforced before a fetched observation is ever stored.

Uses fake in-memory providers (never real network) registered into the
orchestrator via monkeypatching `get_provider` -- this exercises the
orchestrator's own fallback/precedence logic in isolation from any
specific provider implementation.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.domain.price_types import PriceStatus
from app.models import AssetPriceConfig
from app.providers.base import ProviderHTTPError, ProviderQuote
from app.repositories import price_repository
from app.services import price_orchestrator, price_service
from app.tests.conftest import make_asset

_NOW = datetime.now(timezone.utc)


class _FakeProvider:
    def __init__(self, name: str, *, quote: ProviderQuote | None = None, error: Exception | None = None):
        self.name = name
        self._quote = quote
        self._error = error
        self.calls: list[str] = []

    async def get_price(self, provider_symbol: str) -> ProviderQuote:
        self.calls.append(provider_symbol)
        if self._error is not None:
            raise self._error
        assert self._quote is not None
        return self._quote


def _quote(price="100", currency="EGP", symbol="SYM", timestamp=None) -> ProviderQuote:
    return ProviderQuote(
        price=Decimal(price), currency=currency, provider_symbol=symbol, timestamp=timestamp or _NOW
    )


async def _make_asset_with_config(session, symbol, **config_kwargs) -> AssetPriceConfig:
    asset = make_asset(symbol)
    session.add(asset)
    await session.flush()
    config = AssetPriceConfig(asset_id=asset.id, **config_kwargs)
    session.add(config)
    await session.commit()
    await session.refresh(config)
    return config


def _patch_providers(monkeypatch, providers: dict[str, object]) -> None:
    monkeypatch.setattr(price_orchestrator, "get_provider", lambda name: providers.get(name))


# --- Scenario A: primary succeeds ---------------------------------------------


async def test_scenario_a_primary_succeeds_is_stored(db_session, monkeypatch):
    primary = _FakeProvider("primary", quote=_quote(price="55.25"))
    _patch_providers(monkeypatch, {"primary": primary})
    config = await _make_asset_with_config(
        db_session,
        "ORC-A",
        primary_provider="primary",
        primary_provider_symbol="ORC-A.SYM",
        automated_fetching_enabled=True,
    )

    outcome = await price_orchestrator.refresh_one_asset(db_session, config)
    await db_session.commit()

    assert outcome.succeeded is True
    assert outcome.stored is True
    assert outcome.provider_name == "primary"
    assert primary.calls == ["ORC-A.SYM"]

    latest = await price_repository.get_latest_price(db_session, config.asset_id)
    assert latest.price == Decimal("55.25")
    assert latest.is_manual is False


# --- Scenario B: primary fails, secondary succeeds ----------------------------


async def test_scenario_b_primary_fails_secondary_succeeds_is_stored(db_session, monkeypatch):
    primary = _FakeProvider("primary", error=ProviderHTTPError("503"))
    secondary = _FakeProvider("secondary", quote=_quote(price="60.00"))
    _patch_providers(monkeypatch, {"primary": primary, "secondary": secondary})
    config = await _make_asset_with_config(
        db_session,
        "ORC-B",
        primary_provider="primary",
        primary_provider_symbol="ORC-B.SYM",
        secondary_provider="secondary",
        secondary_provider_symbol="ORC-B.ALT",
        automated_fetching_enabled=True,
    )

    outcome = await price_orchestrator.refresh_one_asset(db_session, config)
    await db_session.commit()

    assert outcome.succeeded is True
    assert outcome.stored is True
    assert outcome.provider_name == "secondary"

    latest = await price_repository.get_latest_price(db_session, config.asset_id)
    assert latest.price == Decimal("60.00")
    assert latest.provider == "secondary"


# --- Scenario C: both fail -> latest DB observation is left untouched --------


async def test_scenario_c_both_fail_falls_back_to_latest_db_observation(db_session, monkeypatch):
    primary = _FakeProvider("primary", error=ProviderHTTPError("timeout"))
    secondary = _FakeProvider("secondary", error=ProviderHTTPError("malformed"))
    _patch_providers(monkeypatch, {"primary": primary, "secondary": secondary})
    config = await _make_asset_with_config(
        db_session,
        "ORC-C",
        primary_provider="primary",
        primary_provider_symbol="ORC-C.SYM",
        secondary_provider="secondary",
        secondary_provider_symbol="ORC-C.ALT",
        automated_fetching_enabled=True,
    )
    await price_repository.insert_price_observation(
        db_session,
        asset_id=config.asset_id,
        price=Decimal("42.00"),
        currency="EGP",
        provider="yahoo",
        recorded_at=_NOW - timedelta(hours=1),
        is_manual=False,
    )
    await db_session.commit()

    outcome = await price_orchestrator.refresh_one_asset(db_session, config)
    await db_session.commit()

    assert outcome.succeeded is False
    assert outcome.stored is False

    latest = await price_repository.get_latest_price(db_session, config.asset_id)
    assert latest.price == Decimal("42.00")  # untouched -- the pre-existing observation survives


# --- Scenario D: no provider configured, no history -> PRICE_UNAVAILABLE -----


async def test_scenario_d_no_provider_and_no_history_is_unavailable(db_session, monkeypatch):
    config = await _make_asset_with_config(db_session, "ORC-D", automated_fetching_enabled=False)

    outcome = await price_orchestrator.refresh_one_asset(db_session, config)
    await db_session.commit()

    assert outcome.succeeded is False
    assert outcome.stored is False
    assert outcome.reason == "No provider configured for automated fetching."

    asset = await price_repository.get_asset_by_id(db_session, config.asset_id)
    result = await price_service.get_asset_price(db_session, asset)
    assert result.status == PriceStatus.UNAVAILABLE


# --- Manual precedence enforced before storing --------------------------------


async def test_automated_fetch_does_not_supersede_a_newer_manual_price(db_session, monkeypatch):
    older_quote = _quote(price="70.00", timestamp=_NOW - timedelta(hours=2))
    primary = _FakeProvider("primary", quote=older_quote)
    _patch_providers(monkeypatch, {"primary": primary})
    config = await _make_asset_with_config(
        db_session,
        "ORC-E",
        primary_provider="primary",
        primary_provider_symbol="ORC-E.SYM",
        automated_fetching_enabled=True,
    )
    asset = await price_repository.get_asset_by_id(db_session, config.asset_id)
    await price_service.record_manual_price(db_session, asset, price=Decimal("99.99"), currency=asset.currency)
    await db_session.commit()

    outcome = await price_orchestrator.refresh_one_asset(db_session, config)
    await db_session.commit()

    assert outcome.succeeded is True
    assert outcome.stored is False  # fetched fine, but the manual price wins

    latest = await price_repository.get_latest_price(db_session, config.asset_id)
    assert latest.price == Decimal("99.99")
    assert latest.is_manual is True


async def test_lock_manual_blocks_supersession_even_with_a_newer_automated_timestamp(db_session, monkeypatch):
    much_newer_quote = _quote(price="70.00", timestamp=_NOW + timedelta(days=30))
    primary = _FakeProvider("primary", quote=much_newer_quote)
    _patch_providers(monkeypatch, {"primary": primary})
    config = await _make_asset_with_config(
        db_session,
        "ORC-F",
        primary_provider="primary",
        primary_provider_symbol="ORC-F.SYM",
        automated_fetching_enabled=True,
        lock_manual=True,
    )
    asset = await price_repository.get_asset_by_id(db_session, config.asset_id)
    await price_service.record_manual_price(db_session, asset, price=Decimal("15.00"), currency=asset.currency)
    await db_session.commit()

    outcome = await price_orchestrator.refresh_one_asset(db_session, config)
    await db_session.commit()

    assert outcome.stored is False
    latest = await price_repository.get_latest_price(db_session, config.asset_id)
    assert latest.price == Decimal("15.00")
    assert latest.is_manual is True


async def test_automated_fetch_supersedes_an_older_manual_price(db_session, monkeypatch):
    newer_quote = _quote(price="80.00", timestamp=_NOW)
    primary = _FakeProvider("primary", quote=newer_quote)
    _patch_providers(monkeypatch, {"primary": primary})
    config = await _make_asset_with_config(
        db_session,
        "ORC-G",
        primary_provider="primary",
        primary_provider_symbol="ORC-G.SYM",
        automated_fetching_enabled=True,
    )
    asset = await price_repository.get_asset_by_id(db_session, config.asset_id)
    await price_service.record_manual_price(
        db_session, asset, price=Decimal("50.00"), currency=asset.currency, recorded_at=_NOW - timedelta(days=1)
    )
    await db_session.commit()

    outcome = await price_orchestrator.refresh_one_asset(db_session, config)
    await db_session.commit()

    assert outcome.stored is True
    latest = await price_repository.get_latest_price(db_session, config.asset_id)
    assert latest.price == Decimal("80.00")
    assert latest.is_manual is False


# --- Batch: one asset's failure never stops the rest --------------------------


async def test_refresh_all_automated_assets_continues_past_one_failure(db_session, monkeypatch):
    failing = _FakeProvider("failing", error=ProviderHTTPError("boom"))
    working = _FakeProvider("working", quote=_quote(price="30.00"))
    _patch_providers(monkeypatch, {"failing": failing, "working": working})

    bad_config = await _make_asset_with_config(
        db_session,
        "ORC-H1",
        primary_provider="failing",
        primary_provider_symbol="ORC-H1.SYM",
        automated_fetching_enabled=True,
    )
    good_config = await _make_asset_with_config(
        db_session,
        "ORC-H2",
        primary_provider="working",
        primary_provider_symbol="ORC-H2.SYM",
        automated_fetching_enabled=True,
    )

    outcomes = await price_orchestrator.refresh_all_automated_assets(db_session)
    await db_session.commit()

    by_asset = {o.asset_id: o for o in outcomes}
    assert by_asset[bad_config.asset_id].succeeded is False
    assert by_asset[good_config.asset_id].succeeded is True
    assert by_asset[good_config.asset_id].stored is True

    latest_good = await price_repository.get_latest_price(db_session, good_config.asset_id)
    assert latest_good.price == Decimal("30.00")
