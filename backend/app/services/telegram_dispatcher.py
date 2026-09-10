"""Telegram delivery adapter (Phase 14), implementing the existing
`NotificationDispatcher` Protocol (services/notification_dispatcher.py,
Phase 8) exactly -- no new interface, no new persistence mechanism.

IMPORTANT -- environment limitation, mock-driven only: this sandbox's
outbound HTTPS proxy denies every external host tested so far (Yahoo
Finance, EGID, EGXAPI, Mubasher -- see DECISIONS.md), and `api.telegram.
org` is expected to be blocked identically. This adapter's live network
reachability has not been verified from within this environment. Its
request construction and response handling are instead verified by unit
tests (tests/test_telegram_dispatcher.py) against Telegram's real,
documented Bot API `sendMessage` shape:

    POST https://api.telegram.org/bot{BOT_TOKEN}/sendMessage
    body: {"chat_id": <str>, "text": <str>}
    -> {"ok": true, "result": {...}}                    (success)
    -> {"ok": false, "error_code": <int>, "description": <str>}  (failure)

`dispatch()` NEVER raises. Unlike `PriceProvider.get_price` (which raises
a `ProviderError` subclass so the orchestrator's fallback chain can react
to it), `NotificationDispatcher.dispatch()` returns `None` with no error
contract at all -- notification delivery is explicitly a "best effort,
isolated from evaluation" concern (Phase 14 approval: "notification
delivery must be isolated from evaluation failures"). Every failure mode
here is caught and logged, never propagated, so a Telegram outage can
never break `alert_service.evaluate_alerts()`.

Security: the bot token is part of the request URL (Telegram's own API
design, not a choice made here). It is NEVER logged, NEVER included in
any exception message, and NEVER present in any value this module
returns -- every log line below references only `watchlist_id`, HTTP
status codes, and Telegram's own (non-secret) `description` field.
"""

import logging
from datetime import datetime

import httpx

from app.domain.alert_engine import AlertCheckResult
from app.domain.notification_formatting import format_telegram_alert_message

logger = logging.getLogger(__name__)

_SEND_MESSAGE_URL = "https://api.telegram.org/bot{token}/sendMessage"
_DEFAULT_TIMEOUT_SECONDS = 10.0


class TelegramNotificationDispatcher:
    """Sends one Telegram message per newly-triggered alert check.
    Constructed only when TELEGRAM_ENABLED/TELEGRAM_BOT_TOKEN/
    TELEGRAM_CHAT_ID are all configured (see app/workers/alert_notify.py)
    -- this class itself does not read Settings or decide whether it
    should exist; it only knows how to send, given credentials."""

    def __init__(self, *, bot_token: str, chat_id: str, timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS) -> None:
        self._bot_token = bot_token
        self._chat_id = chat_id
        self._timeout_seconds = timeout_seconds

    async def dispatch(
        self,
        event: AlertCheckResult,
        *,
        asset_symbol: str,
        watchlist_id: str,
        sent_at: datetime | None = None,
    ) -> None:
        text = format_telegram_alert_message(event, asset_symbol=asset_symbol, sent_at=sent_at)
        url = _SEND_MESSAGE_URL.format(token=self._bot_token)

        try:
            async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
                response = await client.post(url, json={"chat_id": self._chat_id, "text": text})
        except httpx.TimeoutException:
            logger.warning("Telegram notification timed out for watchlist %s.", watchlist_id)
            return
        except httpx.HTTPError:
            logger.warning("Telegram notification failed (network error) for watchlist %s.", watchlist_id)
            return

        if response.status_code != 200:
            logger.warning(
                "Telegram API returned HTTP %s for watchlist %s.", response.status_code, watchlist_id
            )
            return

        try:
            payload = response.json()
        except ValueError:
            logger.warning("Telegram API response was not valid JSON for watchlist %s.", watchlist_id)
            return

        if not isinstance(payload, dict) or not payload.get("ok", False):
            description = payload.get("description") if isinstance(payload, dict) else None
            logger.warning(
                "Telegram API reported failure for watchlist %s: %s", watchlist_id, description
            )
            return
