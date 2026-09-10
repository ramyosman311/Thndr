"""Asset-aware price staleness classification (Phase 11).

NON-NEGOTIABLE: staleness is never one universal fixed duration (e.g.
"older than 2 hours = stale" for every asset). Each `AssetType` has a
default expected pricing frequency; an asset's own configured
`stale_threshold_minutes` (in `asset_price_configs`), when set, overrides
that default. Nothing here branches on a specific symbol — only on the
generic, data-driven `asset_type` and the asset's own configuration.

Weekend awareness: a price observation's age is computed with weekend
hours (Saturday/Sunday) excluded, so a Friday closing price checked over
the weekend is not misclassified as stale purely because calendar time
passed while markets were closed. This directly matters for
daily-cadence assets (funds, gold) whose Friday value is genuinely still
the latest available one on Saturday/Sunday. For intraday assets, this
keeps the *reported age* honest (it doesn't balloon just because a
weekend elapsed) even though such a price was typically already stale by
its own short threshold before the weekend began — which is correct: an
intraday price that's hours old is genuinely stale, weekend or not.

Disclosed limitation: this does not implement a market-holiday trading
calendar. A holiday adjacent to a weekend could still be misclassified
as stale — see FINANCIAL_RULES.md, "Stale Policy Limitations".
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

from app.models.enums import AssetType

# Default expected staleness window per asset type, in minutes. Plain
# data, never a per-symbol/per-market special case — an asset's own
# `stale_threshold_minutes` override (asset_price_configs) always wins
# over this table.
DEFAULT_STALE_THRESHOLD_MINUTES: dict[AssetType, int] = {
    AssetType.STOCK: 60,  # intraday, exchange-traded
    AssetType.ETF: 60,  # intraday, exchange-traded
    AssetType.FUND: 24 * 60,  # daily NAV
    AssetType.GOLD: 24 * 60,  # daily reference price, unless configured otherwise
    AssetType.SAVINGS: 24 * 60,
    AssetType.CASH: 24 * 60,
    AssetType.OTHER: 24 * 60,
}

_FALLBACK_THRESHOLD_MINUTES = 24 * 60

# FX rates are a separate observation domain from asset prices (see
# domain/fx.py) but share the same weekend-aware staleness algorithm.
# Most currency pairs relevant here (e.g. USD/EGP) are only meaningfully
# re-quoted on business days, so a daily default -- not an intraday one
# -- is used; there is no per-asset-type table because an FX rate isn't
# tied to an AssetType.
FX_DEFAULT_STALE_THRESHOLD_MINUTES = 24 * 60


def resolve_stale_threshold_minutes(asset_type: AssetType, override_minutes: int | None) -> int:
    """An asset-level override always wins; otherwise the asset_type
    default (see DEFAULT_STALE_THRESHOLD_MINUTES)."""
    if override_minutes is not None:
        return override_minutes
    return DEFAULT_STALE_THRESHOLD_MINUTES.get(asset_type, _FALLBACK_THRESHOLD_MINUTES)


def _weekend_seconds_between(start: datetime, end: datetime) -> float:
    """Seconds that fall on a Saturday or Sunday strictly between `start`
    and `end` (both timezone-aware, same tzinfo). Walks day-by-day so
    partial first/last days are handled correctly."""
    if end <= start:
        return 0.0
    total = 0.0
    cursor = start
    while cursor < end:
        midnight = datetime.combine(cursor.date(), datetime.min.time(), tzinfo=cursor.tzinfo)
        day_end = min(midnight + timedelta(days=1), end)
        if cursor.weekday() >= 5:  # 5 = Saturday, 6 = Sunday
            total += (day_end - cursor).total_seconds()
        cursor = day_end
    return total


@dataclass(frozen=True)
class StaleClassification:
    is_stale: bool
    threshold_minutes: int
    raw_age_seconds: float
    trading_adjusted_age_seconds: float


def classify_staleness_by_threshold(
    *, threshold_minutes: int, recorded_at: datetime, reference_time: datetime
) -> StaleClassification:
    """The shared weekend-aware algorithm, parameterized directly by an
    already-resolved threshold. Used by `classify_staleness` (asset
    prices, threshold resolved from AssetType) and by the FX staleness
    check in services/price_service.py (threshold resolved from
    FX_DEFAULT_STALE_THRESHOLD_MINUTES) so the age/weekend math is
    defined in exactly one place."""
    raw_age_seconds = max((reference_time - recorded_at).total_seconds(), 0.0)
    weekend_seconds = _weekend_seconds_between(recorded_at, reference_time)
    trading_adjusted_age_seconds = max(raw_age_seconds - weekend_seconds, 0.0)
    is_stale = trading_adjusted_age_seconds > threshold_minutes * 60
    return StaleClassification(
        is_stale=is_stale,
        threshold_minutes=threshold_minutes,
        raw_age_seconds=raw_age_seconds,
        trading_adjusted_age_seconds=trading_adjusted_age_seconds,
    )


def classify_staleness(
    *,
    asset_type: AssetType,
    recorded_at: datetime,
    reference_time: datetime,
    stale_threshold_minutes_override: int | None = None,
) -> StaleClassification:
    """Classifies one observation's staleness. Never a single universal
    duration — see module docstring."""
    threshold_minutes = resolve_stale_threshold_minutes(asset_type, stale_threshold_minutes_override)
    return classify_staleness_by_threshold(
        threshold_minutes=threshold_minutes, recorded_at=recorded_at, reference_time=reference_time
    )
