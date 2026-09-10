from datetime import datetime, timezone

from app.domain.stale_policy import (
    DEFAULT_STALE_THRESHOLD_MINUTES,
    classify_staleness,
    resolve_stale_threshold_minutes,
)
from app.models.enums import AssetType


def _at(y, m, d, h=0, mi=0):
    return datetime(y, m, d, h, mi, tzinfo=timezone.utc)


# --- Threshold resolution: never one universal duration ---------------------


def test_different_asset_types_have_different_default_thresholds():
    assert DEFAULT_STALE_THRESHOLD_MINUTES[AssetType.STOCK] != DEFAULT_STALE_THRESHOLD_MINUTES[AssetType.FUND]
    assert resolve_stale_threshold_minutes(AssetType.STOCK, None) == 60
    assert resolve_stale_threshold_minutes(AssetType.FUND, None) == 24 * 60


def test_asset_level_override_wins_over_asset_type_default():
    assert resolve_stale_threshold_minutes(AssetType.STOCK, 15) == 15
    assert resolve_stale_threshold_minutes(AssetType.FUND, 5) == 5


# --- Intraday (exchange-traded) ----------------------------------------------


def test_intraday_asset_within_threshold_is_not_stale():
    result = classify_staleness(
        asset_type=AssetType.STOCK,
        recorded_at=_at(2026, 3, 4, 10, 0),  # Wednesday
        reference_time=_at(2026, 3, 4, 10, 30),
    )
    assert result.is_stale is False
    assert result.threshold_minutes == 60


def test_intraday_asset_beyond_threshold_is_stale():
    result = classify_staleness(
        asset_type=AssetType.STOCK,
        recorded_at=_at(2026, 3, 4, 10, 0),
        reference_time=_at(2026, 3, 4, 12, 0),  # 2 hours later, same weekday
    )
    assert result.is_stale is True


# --- Daily NAV ---------------------------------------------------------------


def test_daily_nav_asset_within_valid_window_is_not_stale():
    result = classify_staleness(
        asset_type=AssetType.FUND,
        recorded_at=_at(2026, 3, 4, 17, 0),  # Wednesday close
        reference_time=_at(2026, 3, 5, 9, 0),  # Thursday morning, ~16h later
    )
    assert result.is_stale is False


def test_daily_nav_asset_over_threshold_is_stale():
    result = classify_staleness(
        asset_type=AssetType.FUND,
        recorded_at=_at(2026, 3, 4, 17, 0),
        reference_time=_at(2026, 3, 7, 17, 0),  # 3 days later (weekday-only) -- long overdue
    )
    assert result.is_stale is True


# --- Weekend behavior: the non-negotiable scenario ---------------------------


def test_friday_daily_nav_is_not_stale_when_checked_saturday():
    """A Friday NAV checked on Saturday must not be marked stale merely
    because the weekend passed — no new NAV could exist yet anyway."""
    friday_close = _at(2026, 3, 6, 17, 0)  # Friday
    saturday_check = _at(2026, 3, 7, 12, 0)  # Saturday, 19 raw hours later
    result = classify_staleness(asset_type=AssetType.FUND, recorded_at=friday_close, reference_time=saturday_check)
    assert result.is_stale is False


def test_friday_daily_nav_is_not_stale_when_checked_sunday():
    friday_close = _at(2026, 3, 6, 17, 0)
    sunday_check = _at(2026, 3, 8, 20, 0)  # Sunday evening, ~51 raw hours later
    result = classify_staleness(asset_type=AssetType.FUND, recorded_at=friday_close, reference_time=sunday_check)
    assert result.is_stale is False


def test_friday_daily_nav_is_not_stale_early_monday_morning():
    """Monday's own NAV typically isn't published until end of Monday's
    trading day, so early Monday morning the Friday NAV is still the
    latest genuinely available one."""
    friday_close = _at(2026, 3, 6, 17, 0)
    monday_morning = _at(2026, 3, 9, 8, 0)  # Monday 08:00 -- ~15 trading-adjusted hours
    result = classify_staleness(asset_type=AssetType.FUND, recorded_at=friday_close, reference_time=monday_morning)
    assert result.is_stale is False


def test_gold_daily_reference_price_survives_the_weekend_the_same_way():
    friday_close = _at(2026, 3, 6, 17, 0)
    saturday_check = _at(2026, 3, 7, 10, 0)
    result = classify_staleness(asset_type=AssetType.GOLD, recorded_at=friday_close, reference_time=saturday_check)
    assert result.is_stale is False


def test_intraday_price_from_friday_is_still_correctly_stale_once_monday_trading_is_underway():
    """The weekend adjustment keeps the *reported age* honest, but an
    intraday asset untouched since Friday close is genuinely stale once
    Monday trading has been open for a while -- this is correct, not a
    bug the weekend adjustment should hide."""
    friday_close = _at(2026, 3, 6, 16, 0)
    monday_late_morning = _at(2026, 3, 9, 10, 0)
    result = classify_staleness(
        asset_type=AssetType.STOCK, recorded_at=friday_close, reference_time=monday_late_morning
    )
    assert result.is_stale is True
    # Trading-adjusted age excludes the full weekend, proving the age
    # figure itself doesn't balloon from calendar time alone.
    assert result.trading_adjusted_age_seconds < result.raw_age_seconds


def test_weekend_hours_are_excluded_from_reported_age_not_just_the_stale_boolean():
    friday_close = _at(2026, 3, 6, 12, 0)
    sunday_check = _at(2026, 3, 8, 12, 0)  # exactly 48 raw hours later
    result = classify_staleness(asset_type=AssetType.FUND, recorded_at=friday_close, reference_time=sunday_check)
    # Only the Friday 12:00-24:00 (12h) and Sunday 00:00-12:00 (12h) are
    # non-weekend/weekend-boundary hours; all of Saturday (24h) and
    # Sunday 00:00-12:00 is weekend -- raw 48h minus ~36h weekend = ~12h.
    assert result.raw_age_seconds == 48 * 3600
    assert result.trading_adjusted_age_seconds < result.raw_age_seconds


# --- Asset-specific threshold override end-to-end ----------------------------


def test_asset_specific_override_changes_the_stale_outcome():
    recorded_at = _at(2026, 3, 4, 10, 0)
    reference_time = _at(2026, 3, 4, 10, 20)  # 20 minutes later

    default_result = classify_staleness(asset_type=AssetType.STOCK, recorded_at=recorded_at, reference_time=reference_time)
    assert default_result.is_stale is False  # within the 60-minute default

    overridden_result = classify_staleness(
        asset_type=AssetType.STOCK,
        recorded_at=recorded_at,
        reference_time=reference_time,
        stale_threshold_minutes_override=10,
    )
    assert overridden_result.is_stale is True  # 20 minutes exceeds a 10-minute override
