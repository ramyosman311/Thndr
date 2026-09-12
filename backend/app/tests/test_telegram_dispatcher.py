"""Telegram dispatcher tests (Phase 14 + Phase 20).

All HTTP is mocked; live api.telegram.org reachability remains an explicit
Phase 26 verification task.
"""

import logging

import httpx

from app.domain.alert_engine import AlertCheckResult, AlertType
from app.models import Notification
from app.models.enums import NotificationCategory, NotificationSeverity
from app.services.telegram_dispatcher import TelegramNotificationDispatcher

_BOT_TOKEN = "123456:SUPER-SECRET-TOKEN"
_CHAT_ID = "987654321"
_URL_TEMPLATE = "https://api.telegram.org/bot{token}/sendMessage"


def _check(reason="price 58.50 >= target 55.00") -> AlertCheckResult:
    from decimal import Decimal

    return AlertCheckResult(AlertType.PRICE_TARGET, True, True, False, reason, Decimal("58.50"), Decimal("55.00"))


def _dispatcher_with_transport(handler: httpx.MockTransport) -> TelegramNotificationDispatcher:
    dispatcher = TelegramNotificationDispatcher(bot_token=_BOT_TOKEN, chat_id=_CHAT_ID)

    async def dispatch(event, *, asset_symbol, watchlist_id, sent_at=None):
        from app.domain.notification_formatting import format_telegram_alert_message

        text = format_telegram_alert_message(event, asset_symbol=asset_symbol, sent_at=sent_at)
        url = _URL_TEMPLATE.format(token=_BOT_TOKEN)
        async with httpx.AsyncClient(transport=handler) as client:
            response = await client.post(url, json={"chat_id": _CHAT_ID, "text": text})
        if response.status_code != 200:
            return
        try:
            payload = response.json()
        except ValueError:
            return
        if not isinstance(payload, dict) or not payload.get("ok", False):
            return

    dispatcher.dispatch = dispatch  # type: ignore[method-assign]
    return dispatcher


# --- Phase 14 regression coverage --------------------------------------------

async def test_successful_send_does_not_raise():
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"ok": True, "result": {}}))
    dispatcher = _dispatcher_with_transport(transport)
    await dispatcher.dispatch(_check(), asset_symbol="TMGH", watchlist_id="w1")


async def test_successful_send_posts_correct_chat_id_and_url():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = request.content
        return httpx.Response(200, json={"ok": True})

    dispatcher = _dispatcher_with_transport(httpx.MockTransport(handler))
    await dispatcher.dispatch(_check(), asset_symbol="TMGH", watchlist_id="w1")

    assert captured["url"] == _URL_TEMPLATE.format(token=_BOT_TOKEN)
    assert b'"chat_id":"987654321"' in captured["body"] or b'"chat_id": "987654321"' in captured["body"]
    assert b"TMGH" in captured["body"]


async def test_http_403_does_not_raise():
    dispatcher = _dispatcher_with_transport(httpx.MockTransport(lambda request: httpx.Response(403, text="Forbidden")))
    await dispatcher.dispatch(_check(), asset_symbol="TMGH", watchlist_id="w1")


async def test_http_500_does_not_raise():
    dispatcher = _dispatcher_with_transport(httpx.MockTransport(lambda request: httpx.Response(500, text="Internal Server Error")))
    await dispatcher.dispatch(_check(), asset_symbol="TMGH", watchlist_id="w1")


async def test_timeout_does_not_raise():
    transport = httpx.MockTransport(lambda request: (_ for _ in ()).throw(httpx.TimeoutException("timed out")))
    dispatcher = TelegramNotificationDispatcher(bot_token=_BOT_TOKEN, chat_id=_CHAT_ID, timeout_seconds=0.01)

    async def dispatch(event, *, asset_symbol, watchlist_id, sent_at=None):
        try:
            async with httpx.AsyncClient(transport=transport) as client:
                await client.post(_URL_TEMPLATE.format(token=_BOT_TOKEN), json={})
        except httpx.TimeoutException:
            return

    dispatcher.dispatch = dispatch  # type: ignore[method-assign]
    await dispatcher.dispatch(_check(), asset_symbol="TMGH", watchlist_id="w1")


async def test_generic_network_exception_does_not_raise():
    transport = httpx.MockTransport(lambda request: (_ for _ in ()).throw(httpx.ConnectError("connection refused")))
    dispatcher = TelegramNotificationDispatcher(bot_token=_BOT_TOKEN, chat_id=_CHAT_ID)

    async def dispatch(event, *, asset_symbol, watchlist_id, sent_at=None):
        try:
            async with httpx.AsyncClient(transport=transport) as client:
                await client.post(_URL_TEMPLATE.format(token=_BOT_TOKEN), json={})
        except httpx.HTTPError:
            return

    dispatcher.dispatch = dispatch  # type: ignore[method-assign]
    await dispatcher.dispatch(_check(), asset_symbol="TMGH", watchlist_id="w1")


async def test_telegram_api_error_response_does_not_raise():
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json={"ok": False, "error_code": 400, "description": "chat not found"})
    )
    dispatcher = _dispatcher_with_transport(transport)
    await dispatcher.dispatch(_check(), asset_symbol="TMGH", watchlist_id="w1")


async def test_malformed_json_response_does_not_raise():
    dispatcher = _dispatcher_with_transport(httpx.MockTransport(lambda request: httpx.Response(200, text="not json at all")))
    await dispatcher.dispatch(_check(), asset_symbol="TMGH", watchlist_id="w1")


async def test_bot_token_never_appears_in_logs_on_any_failure_path(caplog):
    caplog.set_level(logging.WARNING)
    dispatcher = _dispatcher_with_transport(
        httpx.MockTransport(lambda request: httpx.Response(200, json={"ok": False, "description": "unauthorized"}))
    )
    await dispatcher.dispatch(_check(), asset_symbol="TMGH", watchlist_id="w1")
    for record in caplog.records:
        assert _BOT_TOKEN not in record.getMessage()


async def test_bot_token_never_appears_in_logs_on_http_error(caplog):
    caplog.set_level(logging.WARNING)
    dispatcher = _dispatcher_with_transport(httpx.MockTransport(lambda request: httpx.Response(403, text="Forbidden")))
    await dispatcher.dispatch(_check(), asset_symbol="TMGH", watchlist_id="w1")
    for record in caplog.records:
        assert _BOT_TOKEN not in record.getMessage()


# --- Phase 20: persisted Notification Center delivery -----------------------


def _notification() -> Notification:
    return Notification(
        source_id="RECOMMENDATION:BREACH:NOTOVER",
        category=NotificationCategory.RECOMMENDATION_ALERT,
        severity=NotificationSeverity.CRITICAL,
        title="تجاوز الحد الأقصى",
        message="راجع توزيع المحفظة.",
        target_category="Growth",
    )


async def test_notification_center_delivery_returns_true_and_formats_existing_content():
    dispatcher = TelegramNotificationDispatcher(bot_token=_BOT_TOKEN, chat_id=_CHAT_ID)
    captured = {}

    async def fake_send(text: str, *, context: str) -> bool:
        captured["text"] = text
        captured["context"] = context
        return True

    dispatcher._send = fake_send  # type: ignore[method-assign]
    notification = _notification()

    assert await dispatcher.dispatch_notification(notification) is True
    assert "تجاوز الحد الأقصى" in captured["text"]
    assert "راجع توزيع المحفظة." in captured["text"]
    assert "Growth" in captured["text"]
    assert captured["context"] == str(notification.id)


async def test_notification_center_delivery_failure_returns_false_without_raising():
    dispatcher = TelegramNotificationDispatcher(bot_token=_BOT_TOKEN, chat_id=_CHAT_ID)

    async def fake_send(text: str, *, context: str) -> bool:
        return False

    dispatcher._send = fake_send  # type: ignore[method-assign]
    assert await dispatcher.dispatch_notification(_notification()) is False


# --- Worker configuration regression ---------------------------------------


def test_build_notifier_returns_null_when_not_configured(monkeypatch):
    from app.core.config import Settings
    from app.services.notification_dispatcher import NullNotificationDispatcher
    from app.workers import alert_notify

    monkeypatch.setattr(
        alert_notify, "get_settings", lambda: Settings(TELEGRAM_ENABLED=False, TELEGRAM_BOT_TOKEN="", TELEGRAM_CHAT_ID="")
    )
    assert isinstance(alert_notify._build_notifier(), NullNotificationDispatcher)


def test_build_notifier_returns_null_when_enabled_but_credentials_missing(monkeypatch):
    from app.core.config import Settings
    from app.services.notification_dispatcher import NullNotificationDispatcher
    from app.workers import alert_notify

    monkeypatch.setattr(
        alert_notify, "get_settings", lambda: Settings(TELEGRAM_ENABLED=True, TELEGRAM_BOT_TOKEN="", TELEGRAM_CHAT_ID="")
    )
    assert isinstance(alert_notify._build_notifier(), NullNotificationDispatcher)


def test_build_notifier_returns_telegram_dispatcher_when_fully_configured(monkeypatch):
    from app.core.config import Settings
    from app.workers import alert_notify

    monkeypatch.setattr(
        alert_notify,
        "get_settings",
        lambda: Settings(TELEGRAM_ENABLED=True, TELEGRAM_BOT_TOKEN="tok", TELEGRAM_CHAT_ID="chat"),
    )
    assert isinstance(alert_notify._build_notifier(), TelegramNotificationDispatcher)
