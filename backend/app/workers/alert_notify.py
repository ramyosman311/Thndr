"""Out-of-band Telegram delivery worker for the Phase 19 Notification Center.

Run with `python -m app.workers.alert_notify` from an external scheduler.
The FastAPI process never starts this worker and user-facing notification
requests never make live Telegram calls.

Phase 20 deliberately reuses the existing Phase 19 Notification Center as
its source of truth: the worker syncs notifications without a live notifier,
then delivers persisted notification events that have not yet been
successfully sent. This prevents a second alert/recommendation engine and
gives Telegram the same notification content the user sees in-app.

Delivery is best-effort and at-least-once: a successful Telegram response is
persisted in `notifications.telegram_sent_at`; failures remain pending for a
later run. A network timeout after Telegram accepted a message can therefore
produce a retry, which is the unavoidable boundary of an HTTP send without a
provider-side idempotency key.
"""

import asyncio
import logging
from datetime import datetime, timezone
from uuid import UUID

from app.core.config import get_settings
from app.core.database import async_session_factory
from app.core.logging_config import configure_logging
from app.models.enums import NotificationCategory
from app.repositories.notification_repository import list_pending_telegram_notifications
from app.repositories.portfolio_repository import get_portfolio_config
from app.repositories.watchlist_repository import get_alert_rule_by_id
from app.services.notification_dispatcher import NotificationCenterDispatcher, NullNotificationDispatcher
from app.services.notification_service import sync_notifications
from app.services.telegram_dispatcher import TelegramNotificationDispatcher

logger = logging.getLogger(__name__)


def _build_notifier() -> NotificationCenterDispatcher:
    """Construct a live-capable dispatcher only when deployment credentials exist."""
    settings = get_settings()
    if settings.telegram_enabled and settings.telegram_bot_token and settings.telegram_chat_id:
        return TelegramNotificationDispatcher(
            bot_token=settings.telegram_bot_token, chat_id=settings.telegram_chat_id
        )
    return NullNotificationDispatcher()


async def _notification_is_telegram_enabled(session, notification) -> bool:
    """Apply Phase 14 opt-in semantics without inventing a new user setting.

    Every Notification Center delivery requires the portfolio-level Telegram
    switch. Alert-derived notifications additionally retain the original
    per-alert-rule opt-in. Recommendation-derived notifications have no alert
    rule by design, so the portfolio switch is their most granular existing
    Telegram control.
    """
    config = await get_portfolio_config(session)
    if config is None or not config.telegram_enabled:
        return False

    if notification.category not in {
        NotificationCategory.PRICE_ALERT,
        NotificationCategory.ALLOCATION_ALERT,
    }:
        return True

    if not notification.source_id.startswith("ALERT:"):
        logger.warning("Skipping malformed alert notification source %s", notification.source_id)
        return False

    parts = notification.source_id.split(":", 2)
    if len(parts) != 3:
        logger.warning("Skipping malformed alert notification source %s", notification.source_id)
        return False

    try:
        alert_rule_id = UUID(parts[1])
    except ValueError:
        logger.warning("Skipping malformed alert rule id in source %s", notification.source_id)
        return False

    rule = await get_alert_rule_by_id(session, alert_rule_id)
    return bool(rule and rule.enabled and rule.telegram_enabled)


async def run_alert_notify() -> None:
    settings = get_settings()
    if not (settings.telegram_enabled and settings.telegram_bot_token and settings.telegram_chat_id):
        logger.info("Telegram delivery skipped: global Telegram configuration is disabled or incomplete.")
        return

    notifier = _build_notifier()
    if isinstance(notifier, NullNotificationDispatcher):
        return

    async with async_session_factory() as session:
        config = await get_portfolio_config(session)
        if config is None or not config.telegram_enabled:
            logger.info("Telegram delivery skipped: portfolio Telegram switch is disabled.")
            return

        # Phase 19 remains the only source of notification truth. No live
        # notifier is passed here, so this sync cannot make Telegram calls.
        await sync_notifications(session)
        pending = await list_pending_telegram_notifications(session)

        sent = 0
        skipped = 0
        for notification in pending:
            if not await _notification_is_telegram_enabled(session, notification):
                skipped += 1
                continue

            delivered = await notifier.dispatch_notification(notification)
            if delivered:
                # Mark only after Telegram returned {"ok": true}.
                notification.telegram_sent_at = datetime.now(timezone.utc)
                await session.commit()
                sent += 1

    logger.info(
        "Telegram Notification Center run complete: %d pending, %d sent, %d skipped.",
        len(pending),
        sent,
        skipped,
    )


def main() -> None:
    configure_logging()
    asyncio.run(run_alert_notify())


if __name__ == "__main__":
    main()
