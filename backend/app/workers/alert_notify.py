"""Background alert evaluation + Telegram delivery entrypoint (Phase 14).

Run out-of-band from the FastAPI process -- by an external scheduler
(cron, a platform's scheduled-job feature, a long-running worker loop
started by the process manager), never as an in-app asyncio loop inside
the API server. Follows the exact same execution model already
established by `app/workers/price_refresh.py` (Phase 11) -- this project
has no in-repo scheduling infrastructure (no APScheduler, no Celery beat,
no cron), and none is introduced here; the minimum required mechanism is
this standalone script plus an operator-provided external trigger,
identical to price_refresh.py's own disclosed limitation (see
DEPLOYMENT.md, "Workers").

This is the ONLY code path that constructs a live-HTTP-capable
`TelegramNotificationDispatcher`. The user-facing `POST /api/alerts/
evaluate` route (Phase 8, unchanged) always calls `evaluate_alerts()`
with no notifier argument, which defaults to `NullNotificationDispatcher`
-- so an on-demand "check now" request from the Watchlist screen can
never depend on a live Telegram call. Only this worker, run
periodically and out-of-band, ever delivers a real notification -- and
even then, only for rules/portfolios that opted in (see
services/alert_service.py's AND-gate).

Usage:
    python -m app.workers.alert_notify

Exit code is always 0 if the run completed (a Telegram delivery failure
never raises out of `evaluate_alerts`/`TelegramNotificationDispatcher` --
see services/telegram_dispatcher.py -- so it can never surface here as
a worker crash); a non-zero exit means the run itself could not complete
(e.g. no database connection).
"""

import asyncio
import logging

from app.core.config import get_settings
from app.core.database import async_session_factory
from app.services.alert_service import evaluate_alerts
from app.services.notification_dispatcher import NotificationDispatcher, NullNotificationDispatcher
from app.services.telegram_dispatcher import TelegramNotificationDispatcher

logger = logging.getLogger(__name__)


def _build_notifier() -> NotificationDispatcher:
    """Only constructs a live-capable dispatcher when TELEGRAM_ENABLED
    and both credentials are actually set -- otherwise the safe
    NullNotificationDispatcher default, same as everywhere else in this
    codebase when Telegram isn't configured."""
    settings = get_settings()
    if settings.telegram_enabled and settings.telegram_bot_token and settings.telegram_chat_id:
        return TelegramNotificationDispatcher(
            bot_token=settings.telegram_bot_token, chat_id=settings.telegram_chat_id
        )
    return NullNotificationDispatcher()


async def run_alert_notify() -> None:
    notifier = _build_notifier()
    async with async_session_factory() as session:
        evaluation = await evaluate_alerts(session, notifier=notifier)

    new_triggers = sum(1 for entry in evaluation.results if entry.is_new_trigger)
    cleared = sum(1 for entry in evaluation.results if entry.should_clear)
    logger.info(
        "Alert notify run complete: %d check(s) evaluated, %d new trigger(s), %d cleared.",
        len(evaluation.results),
        new_triggers,
        cleared,
    )


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_alert_notify())


if __name__ == "__main__":
    main()
