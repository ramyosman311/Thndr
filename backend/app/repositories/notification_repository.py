"""Data access for the Notification Center and Telegram delivery (Phase 19/20).

P0-3C: notifications are user-owned. Every query takes the caller's
`portfolio_config_id` and filters on it -- another portfolio's notification
(by id, by source_id, or in any list/count) is indistinguishable from one
that doesn't exist.
"""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Notification
from app.models.enums import NotificationCategory


async def get_active_notification_by_source_id(
    session: AsyncSession, source_id: str, portfolio_config_id: UUID
) -> Notification | None:
    """The at-most-one currently-unresolved row for this source_id in this portfolio."""
    result = await session.execute(
        select(Notification).where(
            Notification.portfolio_config_id == portfolio_config_id,
            Notification.source_id == source_id,
            Notification.resolved_at.is_(None),
        )
    )
    return result.scalar_one_or_none()


async def list_active_source_ids(
    session: AsyncSession, category: NotificationCategory, portfolio_config_id: UUID
) -> set[str]:
    result = await session.execute(
        select(Notification.source_id).where(
            Notification.portfolio_config_id == portfolio_config_id,
            Notification.category == category,
            Notification.resolved_at.is_(None),
        )
    )
    return set(result.scalars().all())


async def list_notifications(session: AsyncSession, portfolio_config_id: UUID) -> list[Notification]:
    result = await session.execute(
        select(Notification)
        .where(Notification.portfolio_config_id == portfolio_config_id)
        .order_by(Notification.created_at.desc())
    )
    return list(result.scalars().all())


async def get_notification_by_id(
    session: AsyncSession, notification_id: UUID, portfolio_config_id: UUID
) -> Notification | None:
    result = await session.execute(
        select(Notification).where(
            Notification.id == notification_id, Notification.portfolio_config_id == portfolio_config_id
        )
    )
    return result.scalar_one_or_none()


async def list_unread_notifications(session: AsyncSession, portfolio_config_id: UUID) -> list[Notification]:
    result = await session.execute(
        select(Notification).where(
            Notification.portfolio_config_id == portfolio_config_id, Notification.read_at.is_(None)
        )
    )
    return list(result.scalars().all())


async def list_pending_telegram_notifications(
    session: AsyncSession, portfolio_config_id: UUID
) -> list[Notification]:
    """Return notification events that have not been successfully sent.

    Resolution is intentionally NOT a delivery filter. `resolved_at` answers
    whether the underlying condition is still active; Telegram delivery
    answers whether the user was informed about the notification event. Once
    Phase 19 creates a notification, Phase 20 should deliver that event even
    if the condition clears before the next external worker run.
    """
    result = await session.execute(
        select(Notification)
        .where(
            Notification.portfolio_config_id == portfolio_config_id,
            Notification.telegram_sent_at.is_(None),
        )
        .order_by(Notification.created_at.asc(), Notification.id.asc())
    )
    return list(result.scalars().all())
