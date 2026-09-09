import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, ForeignKey, Numeric, TIMESTAMP, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.asset import Asset


class Holding(UUIDPrimaryKeyMixin, Base):
    """Current position for an asset: quantity held and cost/price info.

    Distinct from portfolio_snapshots (historical point-in-time values) and
    from transactions (the events that produced this position) — see
    FINANCIAL_RULES.md ("Snapshot != Transaction").

    Numeric precision: quantity/average_cost/current_price use
    NUMERIC(20, 8) to represent fractional share/fund units and low-priced
    assets exactly, without binary floating-point rounding error.
    """

    __tablename__ = "holdings"
    __table_args__ = (
        UniqueConstraint("asset_id", name="uq_holdings_asset_id"),
        CheckConstraint("quantity >= 0", name="ck_holdings_quantity_non_negative"),
        CheckConstraint("average_cost >= 0", name="ck_holdings_average_cost_non_negative"),
        CheckConstraint("current_price >= 0", name="ck_holdings_current_price_non_negative"),
    )

    asset_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("assets.id", ondelete="RESTRICT"), nullable=False
    )
    quantity: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False, default=Decimal("0"))
    average_cost: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False, default=Decimal("0"))
    current_price: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False, default=Decimal("0"))
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    asset: Mapped["Asset"] = relationship(back_populates="holding")
