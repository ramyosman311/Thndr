"""Shared ORM-to-schema mapping for the Watchlist + Alert Rules feature.

Kept separate from watchlist_service.py and alert_service.py so both can
import it without creating a circular import between the two service
modules (mirrors the existing app/services/portfolio_shared.py pattern).
"""

from app.models import AlertRule, Watchlist
from app.schemas.alert import AlertRuleOut
from app.schemas.watchlist import WatchlistOut


def to_alert_rule_out(rule: AlertRule) -> AlertRuleOut:
    return AlertRuleOut(
        id=rule.id,
        watchlist_id=rule.watchlist_id,
        enabled=rule.enabled,
        allocation_alert_enabled=rule.allocation_alert_enabled,
        allocation_max_percent=rule.allocation_max_percent,
        price_target_enabled=rule.price_target_enabled,
        price_target=rule.price_target,
        dip_buy_enabled=rule.dip_buy_enabled,
        dip_buy_price=rule.dip_buy_price,
        telegram_enabled=rule.telegram_enabled,
        last_triggered_at=rule.last_triggered_at,
    )


def to_watchlist_out(entry: Watchlist) -> WatchlistOut:
    return WatchlistOut(
        id=entry.id,
        asset_id=entry.asset_id,
        asset_symbol=entry.asset.symbol,
        enabled=entry.enabled,
        notes=entry.notes,
        added_at=entry.added_at,
        removed_at=entry.removed_at,
        alert_rule=to_alert_rule_out(entry.alert_rule) if entry.alert_rule is not None else None,
    )
