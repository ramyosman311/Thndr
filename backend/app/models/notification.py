import uuid
from datetime import datetime

from sqlalchemy import Enum, Index, String, Text, TIMESTAMP, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.enums import NotificationAction, NotificationCategory, NotificationSeverity
from app.models.mixins import CreatedAtMixin, UUIDPrimaryKeyMixin


class Notification(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """Phase 19: one persisted, user-facing notification for the
    in-app Notification Center. Does not replace or duplicate any
    existing alert/recommendation computation -- see
    `services/notification_service.py`. `source_id` identifies the
    underlying condition instance (an alert-rule/alert-type pair, or a
    Phase 18 recommendation id) so a still-true condition is never
    re-notified while already active: a *partial* unique index enforces
    "at most one active (unresolved) row per source_id" at the database
    level, mirroring the same edge-triggered latch pattern
    `alert_rules.last_triggered_at` already uses, generalized to any
    notification source.
    """

    __tablename__ = "notifications"
    __table_args__ = (
        Index(
            "uq_notifications_source_id_active",
            "source_id",
            unique=True,
            postgresql_where=text("resolved_at IS NULL"),
        ),
    )

    source_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    category: Mapped[NotificationCategory] = mapped_column(
        Enum(NotificationCategory, name="notification_category", native_enum=True), nullable=False
    )
    severity: Mapped[NotificationSeverity] = mapped_column(
        Enum(NotificationSeverity, name="notification_severity", native_enum=True), nullable=False
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    target_category: Mapped[str | None] = mapped_column(String(255), nullable=True)
    target_asset: Mapped[str | None] = mapped_column(String(32), nullable=True)
    action: Mapped[NotificationAction | None] = mapped_column(
        Enum(NotificationAction, name="notification_action", native_enum=True), nullable=True
    )
    # NULL = unread. A separate boolean would be redundant state that
    # could drift from this timestamp -- the API layer derives
    # `read: bool` from `read_at is not None`.
    read_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    # NULL = the underlying condition is still active. Set when the
    # source condition clears (mirrors AlertCheckResult.should_clear /
    # a recommendation no longer appearing in current output), so the
    # SAME source_id can produce a fresh notification if it re-triggers
    # later -- never a permanent "never again" state.
    resolved_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
