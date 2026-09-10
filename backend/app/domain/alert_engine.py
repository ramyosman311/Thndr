"""Pure Alert Engine: evaluates configured watchlist alert conditions
against explicit, already-computed inputs.

No I/O. No database session, no HTTP, no Telegram — this module never
sends a notification and never executes a trade; it only decides whether
a condition is currently true and whether that fact is *new* since the
last evaluation (see FINANCIAL_RULES.md, "Alert Engine Rules").

Reuse, not duplication: allocation-related checks accept the already-
computed `risk_allocation_percent`/`maximum_status`/`target_status`
produced by `allocation_engine.evaluate_bucket_allocation` (Phase 5/6),
passed in as plain scalars — this module never recomputes
`current_value / portfolio_value` itself, and works identically whether
the caller passes the raw domain result or the already-serialized API
schema output (both carry the same values).

Price data: `current_price` is taken as an explicit input (in practice,
`holdings.current_price`, which already exists and is already the
"current price" the Portfolio Engine uses — see FINANCIAL_RULES.md). No
market-data provider is invented here; a `None` price means "unknown",
never a fabricated value.

Deduplication ("edge-triggered" latch): each check receives
`previously_triggered: bool` (derived by the caller from whether the
alert rule's `last_triggered_at` is currently set) and returns
`is_new_trigger` (condition just became true) and `should_clear`
(condition just became false, so the rule should be re-armed for a
future trigger). The same underlying condition can therefore trigger
again after it clears — this module never sets a permanent "never again"
state.

Known limitation (see the Phase 8 report): `alert_rules` has exactly one
shared `last_triggered_at` column per row, not one per condition type.
When more than one check type is enabled on the same rule
simultaneously, `previously_triggered` reflects whether *any* of that
row's conditions was last known to be triggered, not each type
independently. This is accurate and useful when a rule has a single
condition type enabled (the common case), and is a disclosed
simplification otherwise — robust independent history would need a
dedicated event table (already listed as a deferred table, `alert_events`,
in DATABASE.md).
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import Enum

from app.domain.allocation_engine import MaximumStatus, TargetStatus


class AlertType(str, Enum):
    ALLOCATION_BREACH = "ALLOCATION_BREACH"
    PRICE_TARGET = "PRICE_TARGET"
    DIP_BUY = "DIP_BUY"
    REBALANCE_SUGGESTED = "REBALANCE_SUGGESTED"
    INCOME_MATURITY = "INCOME_MATURITY"


@dataclass(frozen=True)
class AlertCheckResult:
    alert_type: AlertType
    condition_met: bool
    is_new_trigger: bool
    should_clear: bool
    reason: str
    current_value: Decimal | None = None
    threshold_value: Decimal | None = None


def _edge(condition_met: bool, previously_triggered: bool) -> tuple[bool, bool]:
    """Shared edge-detection: (is_new_trigger, should_clear)."""
    is_new_trigger = condition_met and not previously_triggered
    should_clear = (not condition_met) and previously_triggered
    return is_new_trigger, should_clear


def check_allocation_breach(
    *,
    allocation_max_percent: Decimal | None,
    risk_allocation_percent: Decimal | None,
    previously_triggered: bool,
) -> AlertCheckResult:
    """Triggers when the asset's bucket's risk_allocation_percent (from
    the Allocation Engine, not recomputed here) reaches or exceeds the
    user-configured `allocation_max_percent` watch threshold on this
    alert rule (independent of, and typically stricter than, the
    bucket's own configured `allocation_targets.maximum_percent` — this
    is a personal early-warning level, not the strategy's cap)."""
    if allocation_max_percent is None:
        return AlertCheckResult(AlertType.ALLOCATION_BREACH, False, False, False, "not configured")
    current = risk_allocation_percent
    if current is None:
        return AlertCheckResult(
            AlertType.ALLOCATION_BREACH,
            False,
            False,
            False,
            "risk allocation percent is undefined for this bucket (excluded from risk allocation)",
            threshold_value=allocation_max_percent,
        )
    condition_met = current >= allocation_max_percent
    is_new_trigger, should_clear = _edge(condition_met, previously_triggered)
    reason = (
        f"allocation {current}% >= watch threshold {allocation_max_percent}%"
        if condition_met
        else f"allocation {current}% below watch threshold {allocation_max_percent}%"
    )
    return AlertCheckResult(
        AlertType.ALLOCATION_BREACH, condition_met, is_new_trigger, should_clear, reason, current, allocation_max_percent
    )


def check_price_target(
    *, price_target: Decimal | None, current_price: Decimal | None, previously_triggered: bool
) -> AlertCheckResult:
    """Triggers when current_price reaches or exceeds price_target."""
    if price_target is None:
        return AlertCheckResult(AlertType.PRICE_TARGET, False, False, False, "not configured")
    if current_price is None:
        return AlertCheckResult(
            AlertType.PRICE_TARGET, False, False, False, "current price unknown", threshold_value=price_target
        )
    condition_met = current_price >= price_target
    is_new_trigger, should_clear = _edge(condition_met, previously_triggered)
    reason = (
        f"price {current_price} >= target {price_target}"
        if condition_met
        else f"price {current_price} below target {price_target}"
    )
    return AlertCheckResult(
        AlertType.PRICE_TARGET, condition_met, is_new_trigger, should_clear, reason, current_price, price_target
    )


def check_dip_buy(
    *, dip_buy_price: Decimal | None, current_price: Decimal | None, previously_triggered: bool
) -> AlertCheckResult:
    """Triggers when current_price falls to or below dip_buy_price."""
    if dip_buy_price is None:
        return AlertCheckResult(AlertType.DIP_BUY, False, False, False, "not configured")
    if current_price is None:
        return AlertCheckResult(
            AlertType.DIP_BUY, False, False, False, "current price unknown", threshold_value=dip_buy_price
        )
    condition_met = current_price <= dip_buy_price
    is_new_trigger, should_clear = _edge(condition_met, previously_triggered)
    reason = (
        f"price {current_price} <= dip level {dip_buy_price}"
        if condition_met
        else f"price {current_price} above dip level {dip_buy_price}"
    )
    return AlertCheckResult(
        AlertType.DIP_BUY, condition_met, is_new_trigger, should_clear, reason, current_price, dip_buy_price
    )


def check_rebalance_suggestion(
    *,
    bucket_name: str | None,
    maximum_status: str | None,
    target_status: str | None,
    previously_triggered: bool,
) -> AlertCheckResult:
    """Reuses the Allocation Engine's own maximum_status/target_status for
    the asset's bucket (never recomputed here) — suggests a rebalance
    review is worth considering when the bucket's configured maximum is
    breached or it is overweight against its configured target. This is a
    suggestion only: no sell, no buy, no transaction (see
    FINANCIAL_RULES.md, "Rebalancing Engine Rules").

    Accepts plain strings so either the raw domain `MaximumStatus`/
    `TargetStatus` enum values or the already-serialized API schema
    output can be passed in interchangeably."""
    if bucket_name is None or maximum_status is None or target_status is None:
        return AlertCheckResult(AlertType.REBALANCE_SUGGESTED, False, False, False, "no bucket allocation available")
    condition_met = maximum_status == MaximumStatus.MAXIMUM_BREACHED.value or target_status == TargetStatus.OVERWEIGHT.value
    is_new_trigger, should_clear = _edge(condition_met, previously_triggered)
    reason = (
        f"bucket '{bucket_name}' is {maximum_status}/{target_status} — a rebalance review may be worth considering"
        if condition_met
        else f"bucket '{bucket_name}' is within its configured target/maximum"
    )
    return AlertCheckResult(AlertType.REBALANCE_SUGGESTED, condition_met, is_new_trigger, should_clear, reason)


def check_income_maturity(
    *,
    maturity_date: date | None,
    reference_date: date,
    lookahead_days: int,
    previously_triggered: bool,
) -> AlertCheckResult:
    """Prepared, standalone check for a recurring income/payment maturity
    date (Phase 8 approval: "prepare a rule model that can represent an
    income/payment maturity date and trigger when due/approaching").

    Not yet wired to a persisted AlertRule: the current `alert_rules`
    schema has no maturity-date/recurrence columns at all (not even an
    `_enabled` flag), so this check is exercised directly with explicit
    inputs rather than through the DB-backed alert evaluation flow. See
    the Phase 8 report for the minimal schema addition this would need
    (matches the already-deferred `scheduled_income` table in
    DATABASE.md).
    """
    if maturity_date is None:
        return AlertCheckResult(AlertType.INCOME_MATURITY, False, False, False, "not configured")
    days_until_due = (maturity_date - reference_date).days
    condition_met = days_until_due <= lookahead_days
    is_new_trigger, should_clear = _edge(condition_met, previously_triggered)
    if condition_met and days_until_due < 0:
        reason = f"income maturity was due {-days_until_due} day(s) ago ({maturity_date})"
    elif condition_met:
        reason = f"income maturity due in {days_until_due} day(s) ({maturity_date}), within {lookahead_days}-day lookahead"
    else:
        reason = f"income maturity ({maturity_date}) is {days_until_due} day(s) away — not yet within lookahead"
    return AlertCheckResult(AlertType.INCOME_MATURITY, condition_met, is_new_trigger, should_clear, reason)
