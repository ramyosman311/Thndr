import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.asset import Asset


class AssetPriceConfig(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """How one asset's price is obtained (Phase 11).

    A row here is entirely optional per asset — an asset with no config
    row simply has no automated pricing and no configured provider;
    manual pricing (via `asset_prices.is_manual=True` rows) always
    remains possible regardless of whether this row exists (see
    services/price_service.py). Provider names (`primary_provider`,
    `secondary_provider`) are plain configuration strings (e.g. "yahoo",
    "manual") — the Price Orchestrator resolves them via a registry, and
    nothing in the domain/service layer ever branches on an asset's
    symbol to decide how it's priced (see FINANCIAL_RULES.md, "Provider
    Configuration Is Data, Not Code").

    `stale_threshold_minutes` is an asset-level override of the
    asset-type default staleness window (see
    domain/stale_policy.py) — NULL means "use the asset_type default."

    `lock_manual`: when true, no automated observation may ever supersede
    the latest manual price, regardless of timestamp (see
    FINANCIAL_RULES.md, "Manual vs. Automated Price Precedence").
    """

    __tablename__ = "asset_price_configs"
    __table_args__ = (UniqueConstraint("asset_id", name="uq_asset_price_configs_asset_id"),)

    asset_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("assets.id", ondelete="CASCADE"), nullable=False
    )
    primary_provider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    primary_provider_symbol: Mapped[str | None] = mapped_column(String(64), nullable=True)
    secondary_provider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    secondary_provider_symbol: Mapped[str | None] = mapped_column(String(64), nullable=True)
    automated_fetching_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    manual_override_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    stale_threshold_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    lock_manual: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    asset: Mapped["Asset"] = relationship(back_populates="price_config")
