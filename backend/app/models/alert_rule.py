import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Numeric, TIMESTAMP, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.watchlist import Watchlist


class AlertRule(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Alert configuration for one watchlist entry.

    Numeric precision: allocation_max_percent uses NUMERIC(5, 2)
    (0.00-100.00); price_target/dip_buy_price use NUMERIC(20, 8), matching
    the precision used for asset prices elsewhere.
    """

    __tablename__ = "alert_rules"
    __table_args__ = (
        UniqueConstraint("watchlist_id", name="uq_alert_rules_watchlist_id"),
        CheckConstraint(
            "allocation_max_percent IS NULL OR (allocation_max_percent >= 0 AND allocation_max_percent <= 100)",
            name="ck_alert_rules_allocation_max_percent_range",
        ),
        CheckConstraint(
            "price_target IS NULL OR price_target >= 0", name="ck_alert_rules_price_target_non_negative"
        ),
        CheckConstraint(
            "dip_buy_price IS NULL OR dip_buy_price >= 0", name="ck_alert_rules_dip_buy_price_non_negative"
        ),
    )

    watchlist_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("watchlist.id", ondelete="CASCADE"), nullable=False
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    allocation_alert_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    allocation_max_percent: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    price_target_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    price_target: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    dip_buy_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    dip_buy_price: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    telegram_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    last_triggered_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)

    watchlist: Mapped["Watchlist"] = relationship(back_populates="alert_rule")
