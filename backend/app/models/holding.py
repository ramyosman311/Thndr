import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, ForeignKey, Index, Numeric, TIMESTAMP, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.asset import Asset
    from app.models.portfolio_config import PortfolioConfig


class Holding(UUIDPrimaryKeyMixin, Base):
    """Current position for an asset: quantity held and cost/price info.

    Distinct from portfolio_snapshots (historical point-in-time values) and
    from transactions (the events that produced this position) — see
    FINANCIAL_RULES.md ("Snapshot != Transaction").

    Numeric precision: quantity/average_cost/current_price use
    NUMERIC(20, 8) to represent fractional share/fund units and low-priced
    assets exactly, without binary floating-point rounding error.

    `portfolio_config_id` (P0-3A/P0-3C): the owning portfolio. Nullable only
    because rows that predate ownership have no verified owner (see
    DECISIONS.md, "P0-3A/B"); application code never creates or reads an
    unowned holding -- every read/write is scoped to the caller's
    portfolio (see DECISIONS.md, "P0-3C"). One holding per asset PER
    PORTFOLIO: `uq_holdings_portfolio_asset`. The partial
    `uq_holdings_asset_id_unowned` keeps the original one-holding-per-asset
    guarantee for legacy unowned rows, which the composite constraint alone
    would not cover (Postgres treats NULL as distinct in a unique constraint).
    """

    __tablename__ = "holdings"
    __table_args__ = (
        UniqueConstraint("portfolio_config_id", "asset_id", name="uq_holdings_portfolio_asset"),
        Index(
            "uq_holdings_asset_id_unowned",
            "asset_id",
            unique=True,
            postgresql_where=text("portfolio_config_id IS NULL"),
        ),
        CheckConstraint("quantity >= 0", name="ck_holdings_quantity_non_negative"),
        CheckConstraint("average_cost >= 0", name="ck_holdings_average_cost_non_negative"),
        CheckConstraint("current_price >= 0", name="ck_holdings_current_price_non_negative"),
    )

    portfolio_config_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("portfolio_configs.id", ondelete="CASCADE"), nullable=True
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
    portfolio_config: Mapped["PortfolioConfig | None"] = relationship()
