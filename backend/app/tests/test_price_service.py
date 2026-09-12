from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.domain.price_types import PriceStatus
from app.models import AssetType
from app.repositories import price_repository
from app.services import price_service
from app.services.price_service import InvalidManualPriceError
from app.tests.conftest import make_asset


def _at(hours_ago: float, *, now: datetime | None = None) -> datetime:
    now = now or datetime.now(timezone.utc)
    return now - timedelta(hours=hours_ago)


# A fixed weekday anchor (Tuesday) for tests whose "beyond threshold"
# window must not accidentally overlap a Saturday/Sunday -- the domain
# layer's weekend-aware staleness policy (domain/stale_policy.py, Phase
# 11) deliberately excludes weekend hours from an observation's age, so
# using the real `datetime.now()` here would make these specific
# assertions flaky depending on which day of the week the suite happens
# to run on (verified: they fail when run on an actual Saturday).
# Thursday -- chosen so windows up to 72 hours before it (back to Monday)
# never touch a Saturday/Sunday, keeping every test below unambiguous
# regardless of which real day the suite happens to run on.
_WEEKDAY_NOW = datetime(2026, 1, 8, 12, 0, tzinfo=timezone.utc)


async def _make_asset(session, symbol="PRC1", **kwargs):
    asset = make_asset(symbol, **kwargs)
    session.add(asset)
    await session.commit()
    return asset


# --- get_asset_price: unavailable / current / stale --------------------------


async def test_get_asset_price_is_unavailable_when_no_observation_exists(db_session):
    asset = await _make_asset(db_session)
    result = await price_service.get_asset_price(db_session, asset)
    assert result.status == PriceStatus.UNAVAILABLE
    assert result.price is None
    assert result.is_usable is False


async def test_get_asset_price_is_current_within_threshold(db_session):
    asset = await _make_asset(db_session, asset_type=AssetType.STOCK)
    await price_repository.insert_price_observation(
        db_session,
        asset_id=asset.id,
        price=Decimal("10.50"),
        currency="EGP",
        provider="yahoo",
        recorded_at=_at(0.5),  # 30 minutes ago, within STOCK's 60-min default
        is_manual=False,
    )
    await db_session.commit()

    result = await price_service.get_asset_price(db_session, asset)
    assert result.status == PriceStatus.CURRENT
    assert result.is_stale is False
    assert result.price == Decimal("10.50")


async def test_get_asset_price_is_last_known_when_beyond_threshold(db_session):
    asset = await _make_asset(db_session, symbol="PRC2", asset_type=AssetType.STOCK)
    await price_repository.insert_price_observation(
        db_session,
        asset_id=asset.id,
        price=Decimal("10.50"),
        currency="EGP",
        provider="yahoo",
        recorded_at=_at(3, now=_WEEKDAY_NOW),  # 3 hours ago, beyond STOCK's 60-min default
        is_manual=False,
    )
    await db_session.commit()

    result = await price_service.get_asset_price(db_session, asset, reference_time=_WEEKDAY_NOW)
    assert result.status == PriceStatus.LAST_KNOWN
    assert result.is_stale is True
    assert result.price == Decimal("10.50")  # last known price is still returned, never zero


async def test_get_asset_price_uses_asset_level_stale_override(db_session):
    asset = await _make_asset(db_session, symbol="PRC3", asset_type=AssetType.STOCK)
    config = await price_repository.get_price_config_by_asset_id(db_session, asset.id)
    assert config is None
    from app.models import AssetPriceConfig

    db_session.add(AssetPriceConfig(asset_id=asset.id, stale_threshold_minutes=5))
    await price_repository.insert_price_observation(
        db_session,
        asset_id=asset.id,
        price=Decimal("10.50"),
        currency="EGP",
        provider="yahoo",
        recorded_at=_at(0.5, now=_WEEKDAY_NOW),  # 30 minutes ago -- within the STOCK default, beyond a 5-min override
        is_manual=False,
    )
    await db_session.commit()

    result = await price_service.get_asset_price(db_session, asset, reference_time=_WEEKDAY_NOW)
    assert result.status == PriceStatus.LAST_KNOWN
    assert result.is_stale is True


# --- get_prices_for_assets: batch ---------------------------------------------


async def test_get_prices_for_assets_batches_multiple_assets(db_session):
    priced = await _make_asset(db_session, symbol="PRCB1")
    unpriced = await _make_asset(db_session, symbol="PRCB2")
    await price_repository.insert_price_observation(
        db_session,
        asset_id=priced.id,
        price=Decimal("5.00"),
        currency="EGP",
        provider="yahoo",
        recorded_at=_at(0.1),
        is_manual=False,
    )
    await db_session.commit()

    results = await price_service.get_prices_for_assets(db_session, [priced, unpriced])
    assert results[priced.id].status == PriceStatus.CURRENT
    assert results[unpriced.id].status == PriceStatus.UNAVAILABLE


# --- get_asset_price_in_base_currency: FX ------------------------------------


async def test_same_currency_needs_no_fx_lookup(db_session):
    asset = await _make_asset(db_session, symbol="FX1", currency="EGP")
    await price_repository.insert_price_observation(
        db_session,
        asset_id=asset.id,
        price=Decimal("100"),
        currency="EGP",
        provider="yahoo",
        recorded_at=_at(0.1),
        is_manual=False,
    )
    await db_session.commit()

    result = await price_service.get_asset_price_in_base_currency(db_session, asset, "EGP")
    assert result.status == PriceStatus.CURRENT
    assert result.price == Decimal("100")
    assert result.currency == "EGP"


async def test_valid_fx_rate_converts_the_price(db_session):
    asset = await _make_asset(db_session, symbol="FX2", currency="USD")
    await price_repository.insert_price_observation(
        db_session,
        asset_id=asset.id,
        price=Decimal("10"),
        currency="USD",
        provider="yahoo",
        recorded_at=_at(0.1),
        is_manual=False,
    )
    await price_repository.insert_fx_rate(
        db_session,
        base_currency="USD",
        quote_currency="EGP",
        rate=Decimal("49.50"),
        provider="manual",
        recorded_at=_at(0.1),
    )
    await db_session.commit()

    result = await price_service.get_asset_price_in_base_currency(db_session, asset, "EGP")
    assert result.status == PriceStatus.CURRENT
    assert result.price == Decimal("495.00")
    assert result.currency == "EGP"


async def test_missing_fx_rate_returns_currency_conversion_unavailable(db_session):
    asset = await _make_asset(db_session, symbol="FX3", currency="USD")
    await price_repository.insert_price_observation(
        db_session,
        asset_id=asset.id,
        price=Decimal("10"),
        currency="USD",
        provider="yahoo",
        recorded_at=_at(0.1),
        is_manual=False,
    )
    await db_session.commit()

    result = await price_service.get_asset_price_in_base_currency(db_session, asset, "EGP")
    assert result.status == PriceStatus.CURRENCY_CONVERSION_UNAVAILABLE
    assert result.price is None


async def test_no_native_price_never_attempts_fx_and_stays_unavailable(db_session):
    asset = await _make_asset(db_session, symbol="FX4", currency="USD")
    result = await price_service.get_asset_price_in_base_currency(db_session, asset, "EGP")
    assert result.status == PriceStatus.UNAVAILABLE
    assert result.price is None


async def test_stale_fx_rate_is_still_used_but_marks_the_result_last_known(db_session):
    asset = await _make_asset(db_session, symbol="FX5", currency="USD")
    await price_repository.insert_price_observation(
        db_session,
        asset_id=asset.id,
        price=Decimal("10"),
        currency="USD",
        provider="yahoo",
        recorded_at=_at(0.1, now=_WEEKDAY_NOW),  # fresh asset price
        is_manual=False,
    )
    await price_repository.insert_fx_rate(
        db_session,
        base_currency="USD",
        quote_currency="EGP",
        rate=Decimal("49.50"),
        provider="manual",
        recorded_at=_at(72, now=_WEEKDAY_NOW),  # 3 days ago -- beyond the FX default 24h threshold
    )
    await db_session.commit()

    result = await price_service.get_asset_price_in_base_currency(
        db_session, asset, "EGP", reference_time=_WEEKDAY_NOW
    )
    assert result.status == PriceStatus.LAST_KNOWN
    assert result.is_stale is True
    assert result.price == Decimal("495.00")  # still converted and usable, just flagged stale


# --- get_prices_for_assets_in_base_currency: batch FX ------------------------


async def test_batch_base_currency_conversion_shares_one_fx_rate_across_assets(db_session):
    usd_asset_1 = await _make_asset(db_session, symbol="BFX1", currency="USD")
    usd_asset_2 = await _make_asset(db_session, symbol="BFX2", currency="USD")
    egp_asset = await _make_asset(db_session, symbol="BFX3", currency="EGP")
    for asset, price in ((usd_asset_1, "10"), (usd_asset_2, "20"), (egp_asset, "300")):
        await price_repository.insert_price_observation(
            db_session,
            asset_id=asset.id,
            price=Decimal(price),
            currency=asset.currency,
            provider="yahoo",
            recorded_at=_at(0.1),
            is_manual=False,
        )
    await price_repository.insert_fx_rate(
        db_session,
        base_currency="USD",
        quote_currency="EGP",
        rate=Decimal("49.50"),
        provider="manual",
        recorded_at=_at(0.1),
    )
    await db_session.commit()

    results = await price_service.get_prices_for_assets_in_base_currency(
        db_session, [usd_asset_1, usd_asset_2, egp_asset], "EGP"
    )

    assert results[usd_asset_1.id].price == Decimal("495.00")
    assert results[usd_asset_1.id].currency == "EGP"
    assert results[usd_asset_2.id].price == Decimal("990.00")
    assert results[egp_asset.id].price == Decimal("300")  # already EGP, untouched


async def test_batch_base_currency_conversion_reports_unavailable_per_asset_without_fx(db_session):
    usd_asset = await _make_asset(db_session, symbol="BFX4", currency="USD")
    await price_repository.insert_price_observation(
        db_session,
        asset_id=usd_asset.id,
        price=Decimal("10"),
        currency="USD",
        provider="yahoo",
        recorded_at=_at(0.1),
        is_manual=False,
    )
    await db_session.commit()

    results = await price_service.get_prices_for_assets_in_base_currency(db_session, [usd_asset], "EGP")
    assert results[usd_asset.id].status == PriceStatus.CURRENCY_CONVERSION_UNAVAILABLE


# --- record_manual_price ------------------------------------------------------


async def test_record_manual_price_stores_a_manual_observation(db_session):
    asset = await _make_asset(db_session, symbol="MAN1", currency="EGP")
    observation = await price_service.record_manual_price(db_session, asset, price=Decimal("42"), currency="EGP")
    await db_session.commit()

    assert observation.is_manual is True
    assert observation.provider == "manual"
    assert observation.price == Decimal("42")

    result = await price_service.get_asset_price(db_session, asset)
    assert result.status == PriceStatus.CURRENT
    assert result.price == Decimal("42")


async def test_record_manual_price_rejects_non_positive_price(db_session):
    asset = await _make_asset(db_session, symbol="MAN2", currency="EGP")
    with pytest.raises(InvalidManualPriceError):
        await price_service.record_manual_price(db_session, asset, price=Decimal("0"), currency="EGP")


async def test_record_manual_price_rejects_mismatched_currency(db_session):
    asset = await _make_asset(db_session, symbol="MAN3", currency="EGP")
    with pytest.raises(InvalidManualPriceError):
        await price_service.record_manual_price(db_session, asset, price=Decimal("10"), currency="USD")
