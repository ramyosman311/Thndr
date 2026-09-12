"""Pure Telegram message formatting for alert checks and Phase 19 notifications.

No I/O and no financial calculation. Transport classes only receive the
already-computed presentation content from this module.
"""

from datetime import datetime, timezone

from app.domain.alert_engine import AlertCheckResult, AlertType
from app.models.notification import Notification

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
    notification: Notification, *, sent_at: datetime | None = None
) -> str:
    """Renders one persisted Notification Center item for Telegram.

    Title/message are already Phase 19 user-facing content. No condition,
    severity, allocation, price, or recommendation value is recomputed here.
    """
    sent_at = sent_at or datetime.now(timezone.utc)
    timestamp = sent_at.strftime("%Y-%m-%d %H:%M UTC")
    severity = notification.severity.value
    target = notification.target_category or notification.target_asset
    target_line = f"\n{target}" if target else ""

    return (
        "🔔 MIZAN Notification\n"
        "\n"
        f"{notification.title}{target_line}\n"
        f"{notification.message}\n"
        f"Severity: {severity}\n"
        "\n"
        f"Time: {timestamp}"
    )
