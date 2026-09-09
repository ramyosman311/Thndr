import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, ForeignKey, Index, Numeric, String, TIMESTAMP, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import CreatedAtMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.asset import Asset
    from app.models.portfolio_config import PortfolioConfig


class PortfolioSnapshot(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """A point-in-time record of portfolio composition value.

    Snapshots represent historical VALUE only — never quantities, purchase
    prices, or a substitute for transaction history (see FINANCIAL_RULES.md,
    "Snapshot != Transaction"). Quantities must never be inferred from a
    snapshot's recorded values.
    """

    __tablename__ = "portfolio_snapshots"
    __table_args__ = (
        Index("ix_portfolio_snapshots_config_snapshot_at", "portfolio_config_id", "snapshot_at"),
    )

    portfolio_config_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("portfolio_configs.id", ondelete="CASCADE"), nullable=False
    )
    snapshot_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    label: Mapped[str | None] = mapped_column(String(255), nullable=True)

    portfolio_config: Mapped["PortfolioConfig"] = relationship(back_populates="snapshots")
    items: Mapped[list["PortfolioSnapshotItem"]] = relationship(
        back_populates="snapshot", cascade="all, delete-orphan"
    )


class PortfolioSnapshotItem(UUIDPrimaryKeyMixin, Base):
    """One asset's recorded value within a snapshot.

    Assets are referenced dynamically by foreign key rather than as fixed
    columns (never `snapshot.cloudz`, `snapshot.bwa`, ...) so new assets
    never require a schema change (see DATABASE.md).

    Numeric precision: value uses NUMERIC(18, 2) — a plain currency amount
    in the portfolio's base currency, 2 decimal places.
    """

    __tablename__ = "portfolio_snapshot_items"
    __table_args__ = (
        UniqueConstraint("snapshot_id", "asset_id", name="uq_snapshot_item_snapshot_asset"),
        CheckConstraint("value >= 0", name="ck_snapshot_item_value_non_negative"),
    )

    snapshot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("portfolio_snapshots.id", ondelete="CASCADE"), nullable=False
    )
    asset_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("assets.id", ondelete="RESTRICT"), nullable=False
    )
    value: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)

    snapshot: Mapped["PortfolioSnapshot"] = relationship(back_populates="items")
    asset: Mapped["Asset"] = relationship(back_populates="snapshot_items")
