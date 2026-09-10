"""Pure Telegram message formatting tests (Phase 14). No I/O -- confirms
only real AlertCheckResult fields are used, never fabricated market data
(no "Change"/"Change %" line, since no such field exists anywhere in the
alert engine's output -- see notification_formatting.py's own docstring
for why)."""

from datetime import datetime, timezone
from decimal import Decimal

from app.domain.alert_engine import AlertCheckResult, AlertType
from app.domain.notification_formatting import format_telegram_alert_message

_SENT_AT = datetime(2026, 9, 10, 12, 30, tzinfo=timezone.utc)


def test_price_target_message_includes_symbol_label_and_reason():
    check = AlertCheckResult(
        AlertType.PRICE_TARGET, True, True, False, "price 58.50 >= target 55.00", Decimal("58.50"), Decimal("55.00")
    )
    message = format_telegram_alert_message(check, asset_symbol="TMGH", sent_at=_SENT_AT)

    assert "🔔 MIZAN Alert" in message
    assert "TMGH" in message
    assert "Price Target" in message
    assert "price 58.50 >= target 55.00" in message
    assert "2026-09-10 12:30 UTC" in message


def test_dip_buy_message_uses_dip_buy_label():
    check = AlertCheckResult(
        AlertType.DIP_BUY, True, True, False, "price 40.00 <= dip level 45.00", Decimal("40.00"), Decimal("45.00")
    )
    message = format_telegram_alert_message(check, asset_symbol="ETEL", sent_at=_SENT_AT)

    assert "Dip Buy" in message
    assert "price 40.00 <= dip level 45.00" in message


def test_allocation_breach_message_uses_allocation_breach_label():
    check = AlertCheckResult(
        AlertType.ALLOCATION_BREACH,
        True,
        True,
        False,
        "allocation 42% >= watch threshold 40%",
        Decimal("42"),
        Decimal("40"),
    )
    message = format_telegram_alert_message(check, asset_symbol="EFID", sent_at=_SENT_AT)

    assert "Allocation Breach" in message
    assert "allocation 42% >= watch threshold 40%" in message


def test_rebalance_suggested_message_has_no_values_only_reason():
    check = AlertCheckResult(
        AlertType.REBALANCE_SUGGESTED,
        True,
        True,
        False,
        "bucket 'Growth' is MAXIMUM_BREACHED/OVERWEIGHT — a rebalance review may be worth considering",
    )
    message = format_telegram_alert_message(check, asset_symbol="TMGH", sent_at=_SENT_AT)

    assert "Rebalance Suggested" in message
    assert "rebalance review may be worth considering" in message


def test_message_never_contains_a_change_or_change_percentage_line():
    """No such field exists on AlertCheckResult -- must never be
    fabricated regardless of alert type."""
    check = AlertCheckResult(
        AlertType.PRICE_TARGET, True, True, False, "price 58.50 >= target 55.00", Decimal("58.50"), Decimal("55.00")
    )
    message = format_telegram_alert_message(check, asset_symbol="TMGH", sent_at=_SENT_AT)

    assert "change" not in message.lower()


def test_defaults_sent_at_to_now_when_not_provided():
    check = AlertCheckResult(AlertType.PRICE_TARGET, True, True, False, "price 1 >= target 1", Decimal("1"), Decimal("1"))
    message = format_telegram_alert_message(check, asset_symbol="TMGH")

    assert "UTC" in message
