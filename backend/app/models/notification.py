import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Enum, ForeignKey, Index, String, Text, TIMESTAMP, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.enums import NotificationAction, NotificationCategory, NotificationSeverity
from app.models.mixins import CreatedAtMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.portfolio_config import PortfolioConfig


class Notification(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """Phase 19/20: persisted user-facing notification and delivery state.

    Phase 19 owns notification creation, resolution, and read/unread state.
    Phase 20 adds only the non-financial Telegram delivery timestamp so an
    external worker can deliver each notification at most once after a
    successful send while safely retrying failed sends.

    `portfolio_config_id` (P0-3A/P0-3C): the owning portfolio; nullable only
    for rows that predate ownership. `source_id` is unique among a
    portfolio's ACTIVE notifications, not globally -- two users can
    legitimately have the same condition active at once. The partial
    `uq_notifications_source_id_active_unowned` keeps the original
    guarantee for legacy unowned rows (see DECISIONS.md, "P0-3C").
    """

    __tablename__ = "notifications"
    __table_args__ = (
        Index(
            "uq_notifications_portfolio_source_id_active",
            "portfolio_config_id",
            "source_id",
            unique=True,
            postgresql_where=text("resolved_at IS NULL"),
        ),
        Index(
            "uq_notifications_source_id_active_unowned",
            "source_id",
            unique=True,
            postgresql_where=text("resolved_at IS NULL AND portfolio_config_id IS NULL"),
        ),
    )

    portfolio_config_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("portfolio_configs.id", ondelete="CASCADE"), nullable=True, index=True
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
    # could drift from this timestamp -- the API layer derives `read: bool`
    # from `read_at is not None`.
    read_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    # NULL = the underlying condition is still active. Set when the source
    # condition clears so the same source_id can produce a fresh row later.
    resolved_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    # Phase 20: NULL means Telegram delivery has not successfully completed.
    # Failed sends deliberately leave this NULL so the worker can retry.
    telegram_sent_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)

    portfolio_config: Mapped["PortfolioConfig | None"] = relationship()
