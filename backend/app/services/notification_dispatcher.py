"""Minimal notification abstraction, decoupled from alert evaluation.

The alert engine's job ends at "this condition is newly triggered." A
separate dispatcher's job is "deliver that fact somewhere" (Telegram, a
future in-app inbox, etc.) — the two are never coupled (Phase 8 approval,
"Telegram").

No Telegram integration exists yet in this codebase (no credentials in
`core/config.py`, no worker implementation) and none is added here —
implementing real delivery is out of this phase's scope. This module
defines only the interface a future Telegram worker would implement, plus
a no-op default so the alert evaluation service has something concrete to
call without depending on any delivery mechanism.
"""

from typing import Protocol

from app.domain.alert_engine import AlertCheckResult


class NotificationDispatcher(Protocol):
    """Implemented by a future delivery mechanism (e.g. a Telegram worker).
    Must never be called from `domain/` — only from the service layer,
    after a new trigger has already been decided."""

    async def dispatch(self, event: AlertCheckResult, *, asset_symbol: str, watchlist_id: str) -> None: ...


class NullNotificationDispatcher:
    """Default dispatcher: does nothing. Used until a real delivery
    mechanism (Telegram or otherwise) is implemented in a later phase."""

    async def dispatch(self, event: AlertCheckResult, *, asset_symbol: str, watchlist_id: str) -> None:
        return None
