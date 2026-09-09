import uuid
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Integer, Numeric, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import CreatedAtMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.portfolio_config import PortfolioConfig
    from app.models.strategy_bucket import StrategyBucket


class AllocationTarget(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """The allocation rule for one strategy bucket within a portfolio.

    target_percent, minimum_percent, maximum_percent, and allow_new_buy are
    independent fields on purpose (see FINANCIAL_RULES.md,
    "Target Allocation vs. Maximum Allocation vs. Allow New Buy") — none may
    be derived from another, and none of these values are Python constants.

    The aggregate rule that active target_percent values must not exceed
    100% is a service/domain-layer concern (Phase 6), not a database
    constraint, since PostgreSQL cannot enforce an aggregate SUM check
    across rows with a column-level CHECK.

    Numeric precision: percent fields use NUMERIC(5, 2) (0.00-100.00),
    giving hundredths-of-a-percent precision without float rounding error.
    """

    __tablename__ = "allocation_targets"
    __table_args__ = (
        UniqueConstraint(
            "portfolio_config_id", "strategy_bucket_id", name="uq_allocation_target_portfolio_bucket"
        ),
        CheckConstraint(
            "target_percent IS NULL OR (target_percent >= 0 AND target_percent <= 100)",
            name="ck_allocation_target_percent_range",
        ),
        CheckConstraint(
            "minimum_percent IS NULL OR (minimum_percent >= 0 AND minimum_percent <= 100)",
            name="ck_allocation_target_minimum_range",
        ),
        CheckConstraint(
            "maximum_percent IS NULL OR (maximum_percent >= 0 AND maximum_percent <= 100)",
            name="ck_allocation_target_maximum_range",
        ),
        CheckConstraint(
            "minimum_percent IS NULL OR maximum_percent IS NULL OR minimum_percent <= maximum_percent",
            name="ck_allocation_target_min_le_max",
        ),
    )

    portfolio_config_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("portfolio_configs.id", ondelete="CASCADE"), nullable=False
    )
    strategy_bucket_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("strategy_buckets.id", ondelete="RESTRICT"), nullable=False
    )
    target_percent: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    minimum_percent: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    maximum_percent: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    allow_new_buy: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    portfolio_config: Mapped["PortfolioConfig"] = relationship(back_populates="allocation_targets")
    strategy_bucket: Mapped["StrategyBucket"] = relationship(back_populates="allocation_targets")
