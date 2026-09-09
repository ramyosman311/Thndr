import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.allocation_target import AllocationTarget
    from app.models.asset import Asset
    from app.models.portfolio_config import PortfolioConfig


class StrategyBucket(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A configurable allocation category (e.g. "Individual Stocks", "Gold",
    "Cash") that assets belong to and allocation rules target.

    Buckets are never hardcoded symbol groupings — they are user-defined rows
    scoped to a portfolio_config, so today's categories are not assumed to be
    permanent (see FINANCIAL_RULES.md).
    """

    __tablename__ = "strategy_buckets"
    __table_args__ = (
        UniqueConstraint("portfolio_config_id", "name", name="uq_strategy_bucket_portfolio_name"),
    )

    portfolio_config_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("portfolio_configs.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    portfolio_config: Mapped["PortfolioConfig"] = relationship(back_populates="strategy_buckets")
    assets: Mapped[list["Asset"]] = relationship(back_populates="strategy_bucket")
    allocation_targets: Mapped[list["AllocationTarget"]] = relationship(back_populates="strategy_bucket")
