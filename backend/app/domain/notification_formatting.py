"""Pure Telegram alert-message formatting (Phase 14).

No I/O, no HTTP, no domain calculation of its own -- exactly the same
"pure function, no side effects" contract as `domain/alert_engine.py`,
kept in a separate module so transport concerns (services/
telegram_dispatcher.py) never need to know how a message is worded, and
so a future localization pass only ever touches this one file.

Uses ONLY fields that genuinely exist on `AlertCheckResult` today:
`alert_type` and `reason` (already a complete, human-readable sentence
produced by the pure domain check functions -- e.g. "price 58.50 >=
target 55.00"), plus `asset_symbol` (already passed to
`NotificationDispatcher.dispatch`) and the notification's own send
timestamp.

Deliberately NOT included: a "Change" / "Change %" line. No such data
exists anywhere in this pipeline -- `AlertCheckResult` carries only
`current_value`/`threshold_value` (unitless Decimals whose meaning is a
percent for ALLOCATION_BREACH/REBALANCE_SUGGESTED but a native-currency
price for PRICE_TARGET/DIP_BUY, and `reason` already states them in
context), and no prior/previous-close price is computed or stored
anywhere in the Price Service or alert engine. Fabricating one here
would violate the "do not invent market data, do not introduce a new
financial calculation layer just for notifications" rule this phase was
built under -- see DECISIONS.md, "Telegram Delivery Decision" for the
full rationale. `reason` already IS the "human-readable alert condition"
the message needs.
"""

from datetime import datetime, timezone

from app.domain.alert_engine import AlertCheckResult, AlertType

_ALERT_TYPE_LABELS: dict[AlertType, str] = {
    AlertType.ALLOCATION_BREACH: "Allocation Breach",
    AlertType.PRICE_TARGET: "Price Target",
    AlertType.DIP_BUY: "Dip Buy",
    AlertType.REBALANCE_SUGGESTED: "Rebalance Suggested",
    AlertType.INCOME_MATURITY: "Income Maturity",
}


def format_telegram_alert_message(
    check: AlertCheckResult, *, asset_symbol: str, sent_at: datetime | None = None
) -> str:
    """Renders one Telegram message for a single newly-triggered check.
    `sent_at` defaults to now (UTC) -- the notification's own send time,
    not a market-data timestamp, so it is never fabricated market data."""
    sent_at = sent_at or datetime.now(timezone.utc)
    label = _ALERT_TYPE_LABELS.get(check.alert_type, check.alert_type.value)
    timestamp = sent_at.strftime("%Y-%m-%d %H:%M UTC")

    return (
        "🔔 THNDR Alert\n"
        "\n"
        f"{asset_symbol}\n"
        f"Alert: {label} — {check.reason}\n"
        "\n"
        f"Time: {timestamp}"
    )
