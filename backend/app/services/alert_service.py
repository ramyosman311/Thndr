"""Orchestrates Alert Rule CRUD and alert evaluation.

CRUD (create/update) writes to `alert_rules` — ordinary configuration
management, not a read-only engine. Evaluation (`evaluate_alerts`) also
writes to `alert_rules.last_triggered_at` (that is the dedup state this
feature depends on) but never to holdings, transactions, snapshots,
allocation_targets, or portfolio_configs (Phase 8 approval, "Side
Effects").

Reuse, not duplication: allocation-related checks are driven entirely by
`portfolio_service.get_portfolio_allocation()` (Phase 5/6) — this module
never recomputes an allocation percentage itself.
"""

import logging
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.domain.alert_engine import (
    AlertCheckResult,
    check_allocation_breach,
    check_dip_buy,
    check_price_target,
    check_rebalance_suggestion,
)
from app.models import AlertRule
from app.repositories.portfolio_repository import get_portfolio_config
from app.repositories.watchlist_repository import (
    get_alert_rule_by_id,
    get_alert_rule_by_watchlist_id,
    get_watchlist_entry_by_id,
)
from app.schemas.alert import AlertEvaluationEntryOut, AlertEvaluationOut, AlertRuleOut
from app.services import price_service
from app.services.notification_dispatcher import NotificationDispatcher, NullNotificationDispatcher
from app.services.portfolio_service import PortfolioNotConfiguredError, get_portfolio_allocation
from app.services.watchlist_service import WatchlistEntryNotFoundError, list_evaluation_candidates
from app.services.watchlist_shared import to_alert_rule_out

logger = logging.getLogger(__name__)


class AlertRuleNotFoundError(Exception):
    """Raised when the referenced alert_rule_id does not exist."""


class DuplicateAlertRuleError(Exception):
    """Raised when the watchlist entry already has an alert rule."""


class InvalidAlertRuleConfigurationError(Exception):
    """Raised when an enabled check is missing its required threshold."""


def _validate_config(
    *,
    allocation_alert_enabled: bool,
    allocation_max_percent,
    price_target_enabled: bool,
    price_target,
    dip_buy_enabled: bool,
    dip_buy_price,
) -> None:
    errors = []
    if allocation_alert_enabled and allocation_max_percent is None:
        errors.append("allocation_alert_enabled requires allocation_max_percent")
    if price_target_enabled and price_target is None:
        errors.append("price_target_enabled requires price_target")
    if dip_buy_enabled and dip_buy_price is None:
        errors.append("dip_buy_enabled requires dip_buy_price")
    if errors:
        raise InvalidAlertRuleConfigurationError("; ".join(errors))


async def create_alert_rule(session: AsyncSession, watchlist_id: UUID, **fields) -> AlertRuleOut:
    watchlist = await get_watchlist_entry_by_id(session, watchlist_id)
    if watchlist is None:
        raise WatchlistEntryNotFoundError(f"Watchlist entry {watchlist_id} does not exist.")

    existing = await get_alert_rule_by_watchlist_id(session, watchlist_id)
    if existing is not None:
        raise DuplicateAlertRuleError(f"Watchlist entry {watchlist_id} already has an alert rule.")

    defaults = {
        "enabled": True,
        "allocation_alert_enabled": False,
        "allocation_max_percent": None,
        "price_target_enabled": False,
        "price_target": None,
        "dip_buy_enabled": False,
        "dip_buy_price": None,
        "telegram_enabled": False,
    }
    merged = {**defaults, **fields}
    _validate_config(
        allocation_alert_enabled=merged["allocation_alert_enabled"],
        allocation_max_percent=merged["allocation_max_percent"],
        price_target_enabled=merged["price_target_enabled"],
        price_target=merged["price_target"],
        dip_buy_enabled=merged["dip_buy_enabled"],
        dip_buy_price=merged["dip_buy_price"],
    )

    rule = AlertRule(watchlist_id=watchlist_id, **merged)
    session.add(rule)
    await session.commit()
    return to_alert_rule_out(rule)


async def update_alert_rule(session: AsyncSession, alert_rule_id: UUID, updates: dict) -> AlertRuleOut:
    rule = await get_alert_rule_by_id(session, alert_rule_id)
    if rule is None:
        raise AlertRuleNotFoundError(f"Alert rule {alert_rule_id} does not exist.")

    merged = {
        "allocation_alert_enabled": updates.get("allocation_alert_enabled", rule.allocation_alert_enabled),
        "allocation_max_percent": updates.get("allocation_max_percent", rule.allocation_max_percent),
        "price_target_enabled": updates.get("price_target_enabled", rule.price_target_enabled),
        "price_target": updates.get("price_target", rule.price_target),
        "dip_buy_enabled": updates.get("dip_buy_enabled", rule.dip_buy_enabled),
        "dip_buy_price": updates.get("dip_buy_price", rule.dip_buy_price),
    }
    _validate_config(**merged)

    for field_name, value in updates.items():
        setattr(rule, field_name, value)
    await session.commit()
    return to_alert_rule_out(rule)


async def get_alert_rule(session: AsyncSession, alert_rule_id: UUID) -> AlertRuleOut:
    rule = await get_alert_rule_by_id(session, alert_rule_id)
    if rule is None:
        raise AlertRuleNotFoundError(f"Alert rule {alert_rule_id} does not exist.")
    return to_alert_rule_out(rule)


async def get_alert_rule_for_watchlist(session: AsyncSession, watchlist_id: UUID) -> AlertRuleOut:
    watchlist = await get_watchlist_entry_by_id(session, watchlist_id)
    if watchlist is None:
        raise WatchlistEntryNotFoundError(f"Watchlist entry {watchlist_id} does not exist.")
    rule = await get_alert_rule_by_watchlist_id(session, watchlist_id)
    if rule is None:
        raise AlertRuleNotFoundError(f"Watchlist entry {watchlist_id} has no alert rule configured.")
    return to_alert_rule_out(rule)


async def delete_alert_rule(session: AsyncSession, alert_rule_id: UUID) -> None:
    rule = await get_alert_rule_by_id(session, alert_rule_id)
    if rule is None:
        raise AlertRuleNotFoundError(f"Alert rule {alert_rule_id} does not exist.")
    await session.delete(rule)
    await session.commit()


async def evaluate_alerts(
    session: AsyncSession, notifier: NotificationDispatcher | None = None
) -> AlertEvaluationOut:
    """Evaluate every enabled alert rule on every enabled watchlist entry
    whose asset is active. Returns one entry per check performed (not
    just new triggers) so the caller gets a full diagnostic response;
    `is_new_trigger` marks which ones are new events for a notifier to
    deliver.

    Writes only to `alert_rules.last_triggered_at` — never to holdings,
    transactions, snapshots, allocation_targets, or portfolio_configs.

    Notification delivery is gated by strict AND semantics (Phase 14
    approval): a new trigger is only ever handed to `notifier.dispatch()`
    when ALL of (1) Telegram is globally configured/enabled
    (`TELEGRAM_ENABLED` + both credentials set), (2) this portfolio's
    `telegram_enabled` master switch is on, and (3) this specific rule's
    own `telegram_enabled` opt-in is on. Any one of these being
    false/missing means no delivery — evaluated here regardless of which
    concrete `notifier` was supplied, so a caller passing a real
    `TelegramNotificationDispatcher` still cannot bypass the gate. The
    default `notifier` (when the caller passes none, as the on-demand
    `POST /api/alerts/evaluate` route always does) remains
    `NullNotificationDispatcher` — this function never constructs a
    live-HTTP-capable dispatcher itself; only
    `app/workers/alert_notify.py` does that, out-of-band from any
    user-facing request (see ARCHITECTURE.md, "Workers").

    A `notifier.dispatch()` failure is isolated here as a second layer of
    defense (the real Telegram dispatcher already never raises) so that
    even a future/alternate `NotificationDispatcher` implementation can
    never break evaluation.
    """
    notifier = notifier or NullNotificationDispatcher()

    settings = get_settings()
    telegram_globally_configured = bool(
        settings.telegram_enabled and settings.telegram_bot_token and settings.telegram_chat_id
    )
    portfolio_config = await get_portfolio_config(session)
    portfolio_telegram_enabled = bool(portfolio_config and portfolio_config.telegram_enabled)

    try:
        allocation = await get_portfolio_allocation(session)
        bucket_by_id = {str(b.strategy_bucket_id): b for b in allocation.buckets}
    except PortfolioNotConfiguredError:
        bucket_by_id = {}

    candidates = await list_evaluation_candidates(session)

    # Batched, native-currency prices for every candidate asset (Phase
    # 11) -- price_target/dip_buy thresholds are configured in the
    # asset's own currency, so no base-currency conversion applies here.
    # This is a Price Service DB read, never a live provider call (see
    # FINANCIAL_RULES.md, "Non-Blocking Valuation").
    candidate_assets = [watchlist_entry.asset for watchlist_entry in candidates]
    prices = await price_service.get_prices_for_assets(session, candidate_assets)

    results: list[AlertEvaluationEntryOut] = []
    for watchlist_entry in candidates:
        rule = watchlist_entry.alert_rule
        if rule is None or not rule.enabled:
            continue

        asset = watchlist_entry.asset
        bucket = bucket_by_id.get(str(asset.strategy_bucket_id)) if asset.strategy_bucket_id else None
        price_result = prices.get(asset.id)
        current_price = price_result.price if price_result is not None and price_result.is_usable else None

        previously_triggered = rule.last_triggered_at is not None
        checks: list[AlertCheckResult] = []

        if rule.allocation_alert_enabled:
            checks.append(
                check_allocation_breach(
                    allocation_max_percent=rule.allocation_max_percent,
                    risk_allocation_percent=bucket.risk_allocation_percent if bucket else None,
                    previously_triggered=previously_triggered,
                )
            )
            checks.append(
                check_rebalance_suggestion(
                    bucket_name=bucket.bucket_name if bucket else None,
                    maximum_status=bucket.maximum_status if bucket else None,
                    target_status=bucket.target_status if bucket else None,
                    previously_triggered=previously_triggered,
                )
            )
        if rule.price_target_enabled:
            checks.append(
                check_price_target(
                    price_target=rule.price_target, current_price=current_price, previously_triggered=previously_triggered
                )
            )
        if rule.dip_buy_enabled:
            checks.append(
                check_dip_buy(
                    dip_buy_price=rule.dip_buy_price,
                    current_price=current_price,
                    previously_triggered=previously_triggered,
                )
            )

        # Only one shared last_triggered_at exists per rule row (see
        # domain/alert_engine.py docstring, "Known limitation") — the
        # persisted state follows whether ANY enabled check is currently
        # met, aggregated across this evaluation pass.
        any_condition_met = any(c.condition_met for c in checks)
        if any_condition_met and not previously_triggered:
            rule.last_triggered_at = datetime.now(timezone.utc)
        elif not any_condition_met and previously_triggered:
            rule.last_triggered_at = None

        for check in checks:
            results.append(
                AlertEvaluationEntryOut(
                    alert_rule_id=rule.id,
                    watchlist_id=watchlist_entry.id,
                    asset_symbol=asset.symbol,
                    alert_type=check.alert_type.value,
                    condition_met=check.condition_met,
                    is_new_trigger=check.is_new_trigger,
                    should_clear=check.should_clear,
                    reason=check.reason,
                    current_value=check.current_value,
                    threshold_value=check.threshold_value,
                )
            )
            if check.is_new_trigger:
                should_notify = (
                    telegram_globally_configured and portfolio_telegram_enabled and rule.telegram_enabled
                )
                if should_notify:
                    try:
                        await notifier.dispatch(
                            check, asset_symbol=asset.symbol, watchlist_id=str(watchlist_entry.id)
                        )
                    except Exception:
                        logger.exception(
                            "Notification dispatch failed for watchlist %s; evaluation continues.",
                            watchlist_entry.id,
                        )

    await session.commit()
    return AlertEvaluationOut(results=results)
