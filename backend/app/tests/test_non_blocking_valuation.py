"""Mandatory non-blocking-valuation proof (Phase 11, spec section 10 and
33): every request-time read (Portfolio Summary, Portfolio Allocation,
Alert Evaluation, the Transaction response snapshot) must complete using
only what's already in `asset_prices` -- it must NEVER reach a live
PriceProvider, regardless of provider latency, timeout, or outage.

Proof strategy: monkeypatch `app.providers.registry.get_provider` --
the ONLY function anything outside services/price_orchestrator.py could
use to obtain a live provider instance -- to raise immediately if
called at all. Then exercise every request-time read path against a
real, seeded database and assert each one still returns correctly. If
any of them secretly called into the provider layer, this monkeypatch
turns that into a hard test failure rather than a slow/flaky one,
which is a stronger proof than merely asserting "no timeout occurred".
"""

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.models import AllocationTarget, Holding, PortfolioConfig, StrategyBucket
from app.providers import registry as provider_registry
from app.services import alert_service, portfolio_service, transaction_service, watchlist_service
from app.tests.conftest import make_asset, make_current_price


class _ProviderCalledError(AssertionError):
    """Raised if request-time code ever reaches the provider registry --
    the one thing Phase 11's non-blocking guarantee forbids."""


@pytest.fixture(autouse=True)
def _forbid_any_live_provider_call(monkeypatch):
    def _fail(provider_name):
        raise _ProviderCalledError(
            f"Request-time code called get_provider({provider_name!r}) -- "
            "this must NEVER happen; only services/price_orchestrator.py "
            "(the background refresh path) may resolve a live provider."
        )

    monkeypatch.setattr(provider_registry, "get_provider", _fail)


async def _seed_priced_portfolio(session):
    config = PortfolioConfig(name="Non-Blocking Test Portfolio", base_currency="EGP", emergency_excluded=False)
    session.add(config)
    await session.flush()

    bucket = StrategyBucket(portfolio_config_id=config.id, name="Bucket")
    session.add(bucket)
    await session.flush()

    asset = make_asset("NOBLOCK", strategy_bucket_id=bucket.id)
    session.add(asset)
    await session.flush()
    session.add(Holding(asset_id=asset.id, quantity=Decimal("10")))
    await make_current_price(session, asset, Decimal("100"))
    session.add(
        AllocationTarget(portfolio_config_id=config.id, strategy_bucket_id=bucket.id, target_percent=Decimal("100"))
    )
    await session.commit()
    return config, asset


async def test_portfolio_summary_never_calls_a_live_provider(db_session):
    await _seed_priced_portfolio(db_session)
    summary = await portfolio_service.get_portfolio_summary(db_session)
    assert summary.total_value == Decimal("1000.00")


async def test_portfolio_allocation_never_calls_a_live_provider(db_session):
    await _seed_priced_portfolio(db_session)
    allocation = await portfolio_service.get_portfolio_allocation(db_session)
    assert allocation.total_portfolio_value == Decimal("1000.00")


async def test_alert_evaluation_never_calls_a_live_provider(db_session):
    _, asset = await _seed_priced_portfolio(db_session)
    entry = await watchlist_service.add_to_watchlist(db_session, asset.id)
    await alert_service.create_alert_rule(db_session, entry.id, price_target_enabled=True, price_target=Decimal("50"))

    evaluation = await alert_service.evaluate_alerts(db_session)
    price_check = next(r for r in evaluation.results if r.alert_type == "PRICE_TARGET")
    assert price_check.condition_met is True  # 100 >= 50, computed from the DB observation alone


async def test_transaction_creation_never_calls_a_live_provider(db_session):
    _, asset = await _seed_priced_portfolio(db_session)
    result = await transaction_service.create_transaction(
        db_session,
        asset_id=asset.id,
        transaction_type="BUY",
        quantity=Decimal("1"),
        price=Decimal("100"),
        fees=Decimal("0"),
        transaction_date=datetime.now(timezone.utc),
        notes=None,
    )
    assert result.holding.current_price == Decimal("100")  # from the Price Service's DB read, not a live fetch
