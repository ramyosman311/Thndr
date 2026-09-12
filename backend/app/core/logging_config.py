"""Shared logging setup for the FastAPI process and every out-of-band
worker (Phase 23) -- one place defining what a production log line looks
like, instead of each entrypoint picking its own bare `basicConfig`.

Never logs secrets: this module only sets format/level, and every
existing call site that logs a Telegram/database failure already omits
credentials (see services/telegram_dispatcher.py, "never logs the bot
token on any failure path" -- see its own tests). This module does not
change what call sites choose to log, only how the resulting line looks.
"""

import logging

from app.core.config import get_settings

_LOG_FORMAT = "%(asctime)s %(levelname)-8s [%(name)s] %(message)s"
_DATE_FORMAT = "%Y-%m-%dT%H:%M:%S%z"


def configure_logging() -> None:
    """Idempotent: safe to call from both the API process and a worker's
    `main()` without producing duplicate handlers."""
    settings = get_settings()
    level = logging.DEBUG if (settings.app_debug and not settings.is_production) else logging.INFO

    root = logging.getLogger()
    root.setLevel(level)
    if not any(isinstance(h, logging.StreamHandler) for h in root.handlers):
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT))
        root.addHandler(handler)
    else:
        for handler in root.handlers:
            handler.setFormatter(logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT))
