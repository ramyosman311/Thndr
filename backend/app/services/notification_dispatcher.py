"""Notification delivery abstractions.

Phase 8 introduced `NotificationDispatcher` for raw alert checks. Phase 20
adds a separate `NotificationCenterDispatcher` for persisted Phase 19
notifications so Telegram delivery can cover both alert-derived and
recommendation-derived notifications without coupling the Notification
Center back to the alert engine.
"""

from typing import Protocol

from app.domain.alert_engine import AlertCheckResult
from app.models.notification import Notification


class NotificationDispatcher(Protocol):
    """Delivery interface for newly-triggered alert checks (Phase 8/14)."""

    async def dispatch(self, event: AlertCheckResult, *, asset_symbol: str, watchlist_id: str) -> None: ...


class NotificationCenterDispatcher(Protocol):
    """Delivery interface for persisted Phase 19 Notification rows."""

    async def dispatch_notification(self, notification: Notification) -> None: ...


class NullNotificationDispatcher:
    """Default no-op dispatcher used by on-demand alert evaluation."""

    async def dispatch(self, event: AlertCheckResult, *, asset_symbol: str, watchlist_id: str) -> None:
        return None

    async def dispatch_notification(self, notification: Notification) -> None:
        return None
