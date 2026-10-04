import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, Index, TIMESTAMP, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.alert_rule import AlertRule
    from app.models.asset import Asset
    from app.models.portfolio_config import PortfolioConfig


class Watchlist(UUIDPrimaryKeyMixin, Base):
    """A watched asset. Entries are disabled (enabled=False, removed_at set)
    rather than physically deleted, to preserve watchlist history (see
    DATABASE.md).

    One row per asset: re-adding a previously removed asset re-enables its
    existing row instead of creating a duplicate.

    `portfolio_config_id` (P0-3A/P0-3C): the owning portfolio -- one row per
    asset PER PORTFOLIO (`uq_watchlist_portfolio_asset`), with the partial
    `uq_watchlist_asset_id_unowned` preserving the original one-row-per-
    asset guarantee for legacy unowned rows (see DECISIONS.md, "P0-3C").
    """

    __tablename__ = "watchlist"
    __table_args__ = (
        UniqueConstraint("portfolio_config_id", "asset_id", name="uq_watchlist_portfolio_asset"),
        Index(
            "uq_watchlist_asset_id_unowned",
            "asset_id",
            unique=True,
            postgresql_where=text("portfolio_config_id IS NULL"),
        ),
    )

    portfolio_config_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("portfolio_configs.id", ondelete="CASCADE"), nullable=True
    )
    asset_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("assets.id", ondelete="RESTRICT"), nullable=False
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    added_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )
    removed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)

    asset: Mapped["Asset"] = relationship(back_populates="watchlist_entry")
    alert_rule: Mapped["AlertRule | None"] = relationship(
        back_populates="watchlist", uselist=False, cascade="all, delete-orphan"
    )
    portfolio_config: Mapped["PortfolioConfig | None"] = relationship()
