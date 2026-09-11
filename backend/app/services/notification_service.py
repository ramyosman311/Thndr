"""Orchestrates the Notification Center (Phase 19): evaluates the two
existing, unmodified sources of "something needs attention" —
`alert_service.evaluate_alerts` (Phase 8) and
`recommendation_service.get_portfolio_recommendations` (Phase 18) — and
persists/resolves `Notification` rows so the user gets a stable, de-
duplicated in-app inbox instead of ephemeral, recompute-every-time
results.

No new financial semantics or math: this module reads
`AlertCheckResult.is_new_trigger`/`should_clear` and each
recommendation's own `severity`/`type` — it never recomputes an
allocation percent, a price condition, or a BUY/REDUCE amount (see
FINANCIAL_RULES.md, "Notification Layer Rules").

Read-only w.r.t. financial state: the only writes here are to the new
`notifications` table (non-financial, user-facing metadata) plus
whatever `evaluate_alerts` itself already writes
(`alert_rules.last_triggered_at` — pre-existing, Phase 8-approved).
Marking a notification read changes only `notifications.read_at`.
"""

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.alert_engine import AlertType
from app.domain.notification_engine import (
    build_alert_notification_content,
    build_recommendation_notification_content,
)
from app.models import Notification
from app.models.enums import NotificationCategory
from app.repositories.notification_repository import (
    get_active_notification_by_source_id,
    get_notification_by_id,
    list_active_source_ids,
    list_notifications as repo_list_notifications,
    list_unread_notifications,
)
from app.schemas.notification import NotificationOut, NotificationsOut
from app.services.alert_service import evaluate_alerts
from app.services.rebalancing_service import RebalancingNotConfiguredError
from app.services.recommendation_service import get_portfolio_recommendations


class NotificationNotFoundError(Exception):
    """Raised when the referenced notification_id does not exist."""


def _to_out(notification: Notification) -> NotificationOut:
    return NotificationOut(
        id=notification.id,
        category=notification.category.value,
        severity=notification.severity.value,
        title=notification.title,
        message=notification.message,
        target_category=notification.target_category,
        target_asset=notification.target_asset,
        action=notification.action.value if notification.action else None,
        read=notification.read_at is not None,
        created_at=notification.created_at,
    )


async def _sync_alert_notifications(session: AsyncSession) -> None:
    """Reuses `alert_service.evaluate_alerts` (unchanged, including its
    Telegram-dispatch gating, which this call always bypasses by passing
    no notifier — in-app visibility is independent of the Telegram
    opt-in) and persists one Notification per newly-triggered check,
    resolving any that have just cleared. `is_new_trigger`/`should_clear`
    are ALREADY edge-detected by alert_engine.py — this function only
    mirrors that decision into the notifications table, never
    re-derives it."""
    evaluation = await evaluate_alerts(session)

    for entry in evaluation.results:
        content = build_alert_notification_content(
            _EntryAsCheckResult(entry),
            alert_rule_id=str(entry.alert_rule_id),
            asset_symbol=entry.asset_symbol,
            bucket_name=entry.bucket_name,
        )
        if content is None:
            continue

        if entry.is_new_trigger:
            existing = await get_active_notification_by_source_id(session, content.source_id)
            if existing is None:
                session.add(
                    Notification(
                        source_id=content.source_id,
                        category=content.category,
                        severity=content.severity,
                        title=content.title,
                        message=content.message,
                        target_category=content.target_category,
                        target_asset=content.target_asset,
                        action=content.action,
                    )
                )
        elif entry.should_clear:
            existing = await get_active_notification_by_source_id(session, content.source_id)
            if existing is not None:
                existing.resolved_at = datetime.now(timezone.utc)


class _EntryAsCheckResult:
    """Adapts one `AlertEvaluationEntryOut` (the already-serialized API
    schema) to the plain-attribute shape
    `domain.notification_engine.build_alert_notification_content`
    expects — the same "raw domain or serialized schema, either works"
    idiom `alert_engine.check_rebalance_suggestion` already established,
    applied here so this module never needs the raw `AlertCheckResult`
    objects `evaluate_alerts` doesn't return."""

    def __init__(self, entry) -> None:
        self.alert_type = AlertType(entry.alert_type)
        self.current_value = entry.current_value
        self.threshold_value = entry.threshold_value
        self.reason = entry.reason


async def _sync_recommendation_notifications(session: AsyncSession) -> None:
    """Reuses `recommendation_service.get_portfolio_recommendations`
    (Phase 18, unchanged) — never recomputes a recommendation. Since
    recommendations are pure/stateless (recomputed fresh every call,
    unlike alert_engine's own persisted `last_triggered_at` latch), "is
    this new" is derived here by diffing the current notify-worthy
    recommendation ids against which RECOMMENDATION_ALERT source_ids are
    currently active in the notifications table — the same edge-
    triggered idea, applied at the notification-persistence layer
    instead of duplicating a new stateful field onto the recommendation
    engine itself."""
    try:
        recommendations = await get_portfolio_recommendations(session)
    except RebalancingNotConfiguredError:
        return

    current_source_ids: set[str] = set()
    for rec in recommendations.recommendations:
        content = build_recommendation_notification_content(
            recommendation_id=rec.id,
            recommendation_type=rec.type,
            severity=rec.severity,
            title=rec.title,
            message=rec.message,
            target_category=rec.target_category,
        )
        if content is None:
            continue
        current_source_ids.add(content.source_id)

        existing = await get_active_notification_by_source_id(session, content.source_id)
        if existing is None:
            session.add(
                Notification(
                    source_id=content.source_id,
                    category=content.category,
                    severity=content.severity,
                    title=content.title,
                    message=content.message,
                    target_category=content.target_category,
                    target_asset=content.target_asset,
                    action=content.action,
                )
            )

    previously_active = await list_active_source_ids(session, NotificationCategory.RECOMMENDATION_ALERT)
    for stale_source_id in previously_active - current_source_ids:
        existing = await get_active_notification_by_source_id(session, stale_source_id)
        if existing is not None:
            existing.resolved_at = datetime.now(timezone.utc)


async def sync_notifications(session: AsyncSession) -> None:
    await _sync_alert_notifications(session)
    await _sync_recommendation_notifications(session)
    await session.commit()


async def list_notifications(session: AsyncSession) -> NotificationsOut:
    await sync_notifications(session)
    notifications = await repo_list_notifications(session)
    unread = await list_unread_notifications(session)
    return NotificationsOut(
        unread_count=len(unread),
        notifications=[_to_out(n) for n in notifications],
    )


async def mark_notification_read(session: AsyncSession, notification_id: UUID) -> NotificationOut:
    notification = await get_notification_by_id(session, notification_id)
    if notification is None:
        raise NotificationNotFoundError(f"Notification {notification_id} does not exist.")
    if notification.read_at is None:
        notification.read_at = datetime.now(timezone.utc)
        await session.commit()
    return _to_out(notification)


async def mark_all_notifications_read(session: AsyncSession) -> NotificationsOut:
    unread = await list_unread_notifications(session)
    now = datetime.now(timezone.utc)
    for notification in unread:
        notification.read_at = now
    await session.commit()
    notifications = await repo_list_notifications(session)
    return NotificationsOut(unread_count=0, notifications=[_to_out(n) for n in notifications])
