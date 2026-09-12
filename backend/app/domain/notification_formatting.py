"""Pure Telegram message formatting for alert checks and persisted notifications.

No I/O, ORM dependency, or financial calculation. Transport classes provide
already-computed presentation fields to these functions.
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
    """Renders one Telegram message for a raw alert check (Phase 14)."""
    sent_at = sent_at or datetime.now(timezone.utc)
    label = _ALERT_TYPE_LABELS.get(check.alert_type, check.alert_type.value)
    timestamp = sent_at.strftime("%Y-%m-%d %H:%M UTC")

    return (
        "🔔 MIZAN Alert\n"
        "\n"
        f"{asset_symbol}\n"
        f"Alert: {label} — {check.reason}\n"
        "\n"
        f"Time: {timestamp}"
    )


def format_telegram_notification_message(
    *,
    title: str,
    message: str,
    severity: str,
    target_category: str | None,
    target_asset: str | None,
    sent_at: datetime | None = None,
) -> str:
    """Renders existing Phase 19 Notification content without recomputing it."""
    sent_at = sent_at or datetime.now(timezone.utc)
    timestamp = sent_at.strftime("%Y-%m-%d %H:%M UTC")
    target = target_category or target_asset
    target_line = f"\n{target}" if target else ""

    return (
        "🔔 MIZAN Notification\n"
        "\n"
        f"{title}{target_line}\n"
        f"{message}\n"
        f"Severity: {severity}\n"
        "\n"
        f"Time: {timestamp}"
    )
