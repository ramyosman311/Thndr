"""Data access for the Notification Center and Telegram delivery (Phase 19/20)."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Notification
from app.models.enums import NotificationCategory


async def get_active_notification_by_source_id(session: AsyncSession, source_id: str) -> Notification | None:
    """The at-most-one currently-unresolved row for this source_id."""
    result = await session.execute(
        select(Notification).where(Notification.source_id == source_id, Notification.resolved_at.is_(None))
    )
    return result.scalar_one_or_none()


async def list_active_source_ids(session: AsyncSession, category: NotificationCategory) -> set[str]:
    result = await session.execute(
        select(Notification.source_id).where(
            Notification.category == category, Notification.resolved_at.is_(None)
        )
    )
    return set(result.scalars().all())


async def list_notifications(session: AsyncSession) -> list[Notification]:
    result = await session.execute(select(Notification).order_by(Notification.created_at.desc()))
    return list(result.scalars().all())


async def get_notification_by_id(session: AsyncSession, notification_id: UUID) -> Notification | None:
    result = await session.execute(select(Notification).where(Notification.id == notification_id))
    return result.scalar_one_or_none()


async def list_unread_notifications(session: AsyncSession) -> list[Notification]:
    result = await session.execute(select(Notification).where(Notification.read_at.is_(None)))
    return list(result.scalars().all())


async def list_pending_telegram_notifications(session: AsyncSession) -> list[Notification]:
    """Return notification events that have not been successfully sent.

    Resolution is intentionally NOT a delivery filter. `resolved_at` answers
    whether the underlying condition is still active; Telegram delivery
    answers whether the user was informed about the notification event. Once
    Phase 19 creates a notification, Phase 20 should deliver that event even
    if the condition clears before the next external worker run.
    """
    result = await session.execute(
        select(Notification)
        .where(Notification.telegram_sent_at.is_(None))
        .order_by(Notification.created_at.asc(), Notification.id.asc())
    )
    return list(result.scalars().all())
