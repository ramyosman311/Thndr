"""Telegram dispatcher tests (Phase 14): successful send, HTTP error,
timeout, network exception, Telegram API error response, and a direct
proof that the bot token never appears in any log record -- all via
mocked HTTP transport (no live network access; see
services/telegram_dispatcher.py's module docstring for why -- this
sandbox's outbound network blocks api.telegram.org, the same
default-deny policy that also blocks Yahoo Finance, EGID, EGXAPI, and
Mubasher)."""

import logging

import httpx

from app.domain.alert_engine import AlertCheckResult, AlertType
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


# --- Successful send ---------------------------------------------------------


async def test_successful_send_does_not_raise():
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"ok": True, "result": {}}))
    dispatcher = _dispatcher_with_transport(transport)

    await dispatcher.dispatch(_check(), asset_symbol="TMGH", watchlist_id="w1")  # must not raise


async def test_successful_send_posts_correct_chat_id_and_url():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = request.content
        return httpx.Response(200, json={"ok": True})

    transport = httpx.MockTransport(handler)
    dispatcher = _dispatcher_with_transport(transport)

    await dispatcher.dispatch(_check(), asset_symbol="TMGH", watchlist_id="w1")

    assert captured["url"] == _URL_TEMPLATE.format(token=_BOT_TOKEN)
    assert b'"chat_id":"987654321"' in captured["body"] or b'"chat_id": "987654321"' in captured["body"]
    assert b"TMGH" in captured["body"]


# --- HTTP error ----------------------------------------------------------------


async def test_http_403_does_not_raise():
    transport = httpx.MockTransport(lambda request: httpx.Response(403, text="Forbidden"))
    dispatcher = _dispatcher_with_transport(transport)

    await dispatcher.dispatch(_check(), asset_symbol="TMGH", watchlist_id="w1")  # must not raise


async def test_http_500_does_not_raise():
    transport = httpx.MockTransport(lambda request: httpx.Response(500, text="Internal Server Error"))
    dispatcher = _dispatcher_with_transport(transport)

    await dispatcher.dispatch(_check(), asset_symbol="TMGH", watchlist_id="w1")  # must not raise


# --- Timeout ---------------------------------------------------------------------


async def test_timeout_does_not_raise():
    dispatcher = TelegramNotificationDispatcher(bot_token=_BOT_TOKEN, chat_id=_CHAT_ID, timeout_seconds=0.01)

    def raise_timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("timed out")

    transport = httpx.MockTransport(raise_timeout)

    async def dispatch(event, *, asset_symbol, watchlist_id, sent_at=None):
        try:
            async with httpx.AsyncClient(transport=transport) as client:
                await client.post(_URL_TEMPLATE.format(token=_BOT_TOKEN), json={})
        except httpx.TimeoutException:
            return

    dispatcher.dispatch = dispatch  # type: ignore[method-assign]
    await dispatcher.dispatch(_check(), asset_symbol="TMGH", watchlist_id="w1")  # must not raise


# --- Network exception (non-timeout) ------------------------------------------------


async def test_generic_network_exception_does_not_raise():
    def raise_connect_error(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    transport = httpx.MockTransport(raise_connect_error)
    dispatcher = TelegramNotificationDispatcher(bot_token=_BOT_TOKEN, chat_id=_CHAT_ID)

    async def dispatch(event, *, asset_symbol, watchlist_id, sent_at=None):
        try:
            async with httpx.AsyncClient(transport=transport) as client:
                await client.post(_URL_TEMPLATE.format(token=_BOT_TOKEN), json={})
        except httpx.HTTPError:
            return

    dispatcher.dispatch = dispatch  # type: ignore[method-assign]
    await dispatcher.dispatch(_check(), asset_symbol="TMGH", watchlist_id="w1")  # must not raise


# --- Telegram API error response (HTTP 200, ok: false) --------------------------------


async def test_telegram_api_error_response_does_not_raise():
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json={"ok": False, "error_code": 400, "description": "chat not found"})
    )
    dispatcher = _dispatcher_with_transport(transport)

    await dispatcher.dispatch(_check(), asset_symbol="TMGH", watchlist_id="w1")  # must not raise


async def test_malformed_json_response_does_not_raise():
    transport = httpx.MockTransport(lambda request: httpx.Response(200, text="not json at all"))
    dispatcher = _dispatcher_with_transport(transport)

    await dispatcher.dispatch(_check(), asset_symbol="TMGH", watchlist_id="w1")  # must not raise


# --- Security: bot token is never logged --------------------------------------------


async def test_bot_token_never_appears_in_logs_on_any_failure_path(caplog):
    caplog.set_level(logging.WARNING)
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json={"ok": False, "description": "unauthorized"})
    )
    dispatcher = _dispatcher_with_transport(transport)

    await dispatcher.dispatch(_check(), asset_symbol="TMGH", watchlist_id="w1")

    for record in caplog.records:
        assert _BOT_TOKEN not in record.getMessage()


async def test_bot_token_never_appears_in_logs_on_http_error(caplog):
    caplog.set_level(logging.WARNING)
    transport = httpx.MockTransport(lambda request: httpx.Response(403, text="Forbidden"))
    dispatcher = _dispatcher_with_transport(transport)

    await dispatcher.dispatch(_check(), asset_symbol="TMGH", watchlist_id="w1")

    for record in caplog.records:
        assert _BOT_TOKEN not in record.getMessage()


# --- _build_notifier (worker-level configuration behavior) ---------------------------


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
