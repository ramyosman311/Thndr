import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.allocation_target import AllocationTarget
    from app.models.asset import Asset
    from app.models.snapshot import PortfolioSnapshot
    from app.models.strategy_bucket import StrategyBucket
    from app.models.user import User


class PortfolioConfig(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Portfolio-level settings, including which asset (if any) is the
    designated emergency/savings asset.

    The emergency asset is never hardcoded by symbol — it is selected here,
    by foreign key, and `emergency_excluded` independently controls whether
    its value is excluded from risk/investment/rebalancing/inflow
    calculations (see FINANCIAL_RULES.md, "Emergency Cash").

    `user_id` (P0-3A/P0-3C): the owner (a Supabase Auth user). Nullable only
    because rows that predate ownership have no verified owner and cannot be
    safely assigned one by code -- see DECISIONS.md, "P0-3A/B" for the
    verified-backfill procedure a later phase must run before this can
    become NOT NULL. Every application read of a portfolio is scoped by it
    (`get_portfolio_config_for_user`); there is no unscoped "first row"
    lookup, and an unowned portfolio is unreachable through the API.
    """

    __tablename__ = "portfolio_configs"

    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    base_currency: Mapped[str] = mapped_column(String(8), nullable=False)
    emergency_asset_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("assets.id", ondelete="SET NULL"), nullable=True
    )
    emergency_excluded: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    telegram_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    user: Mapped["User | None"] = relationship()
    emergency_asset: Mapped["Asset | None"] = relationship(foreign_keys=[emergency_asset_id])
    strategy_buckets: Mapped[list["StrategyBucket"]] = relationship(back_populates="portfolio_config")
    allocation_targets: Mapped[list["AllocationTarget"]] = relationship(back_populates="portfolio_config")
    snapshots: Mapped[list["PortfolioSnapshot"]] = relationship(back_populates="portfolio_config")
