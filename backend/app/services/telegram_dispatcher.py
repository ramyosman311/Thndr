"""Telegram delivery adapters for Phase 14 alerts and Phase 20 notifications.

Both delivery methods are best-effort and never raise into evaluation or
worker orchestration. The bot token is never logged or returned.
"""

import logging
from datetime import datetime, timezone

import httpx

from app.domain.alert_engine import AlertCheckResult
from app.domain.notification_formatting import (
    format_telegram_alert_message,
    format_telegram_notification_message,
)
from app.models.notification import Notification

logger = logging.getLogger(__name__)

_SEND_MESSAGE_URL = "https://api.telegram.org/bot{token}/sendMessage"
_DEFAULT_TIMEOUT_SECONDS = 10.0


class TelegramNotificationDispatcher:
    """Sends Phase 14 alert checks or Phase 19 persisted notifications."""

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
        await self._send(text, context=watchlist_id)

    async def dispatch_notification(self, notification: Notification) -> bool:
        """Send one persisted Notification and report whether Telegram accepted it."""
        sent_at = datetime.now(timezone.utc)
        text = format_telegram_notification_message(
            title=notification.title,
            message=notification.message,
            severity=notification.severity.value,
            target_category=notification.target_category,
            target_asset=notification.target_asset,
            sent_at=sent_at,
        )
        return await self._send(text, context=str(notification.id))

    async def _send(self, text: str, *, context: str) -> bool:
        url = _SEND_MESSAGE_URL.format(token=self._bot_token)
        try:
            async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
                response = await client.post(url, json={"chat_id": self._chat_id, "text": text})
        except httpx.TimeoutException:
            logger.warning("Telegram notification timed out for %s.", context)
            return False
        except httpx.HTTPError:
            logger.warning("Telegram notification failed (network error) for %s.", context)
            return False

        if response.status_code != 200:
            logger.warning("Telegram API returned HTTP %s for %s.", response.status_code, context)
            return False

        try:
            payload = response.json()
        except ValueError:
            logger.warning("Telegram API response was not valid JSON for %s.", context)
            return False

        if not isinstance(payload, dict) or not payload.get("ok", False):
            description = payload.get("description") if isinstance(payload, dict) else None
            logger.warning("Telegram API reported failure for %s: %s", context, description)
            return False

        return True
