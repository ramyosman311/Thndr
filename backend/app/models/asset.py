import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Enum, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.enums import AssetType
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.asset_price import AssetPrice
    from app.models.asset_price_config import AssetPriceConfig
    from app.models.holding import Holding
    from app.models.snapshot import PortfolioSnapshotItem
    from app.models.strategy_bucket import StrategyBucket
    from app.models.transaction import Transaction
    from app.models.watchlist import Watchlist


class Asset(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A trackable instrument (stock, fund, gold, cash, ...).

    Assets are pure data rows. No symbol is ever referenced by name in
    business logic — the set of assets, and which strategy bucket each
    belongs to, is entirely configurable via this table (see
    FINANCIAL_RULES.md, "Database Is the Source of Truth").
    """

    __tablename__ = "assets"
    __table_args__ = (UniqueConstraint("symbol", name="uq_assets_symbol"),)

    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    asset_type: Mapped[AssetType] = mapped_column(
        Enum(AssetType, name="asset_type", native_enum=True), nullable=False
    )
    market: Mapped[str | None] = mapped_column(String(64), nullable=True)
    currency: Mapped[str] = mapped_column(String(8), nullable=False)
    strategy_bucket_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("strategy_buckets.id", ondelete="SET NULL"),
        nullable=True,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # No delete cascade on any of these: an asset that still has a holding,
    # transactions, a watchlist entry, or snapshot history must not be
    # deletable at all (DB-level ON DELETE RESTRICT below enforces this).
    # Cascading the ORM-side delete would silently remove the child rows
    # first and defeat that protection.
    strategy_bucket: Mapped["StrategyBucket | None"] = relationship(back_populates="assets")
    holding: Mapped["Holding | None"] = relationship(back_populates="asset", uselist=False)
    transactions: Mapped[list["Transaction"]] = relationship(back_populates="asset")
    watchlist_entry: Mapped["Watchlist | None"] = relationship(back_populates="asset", uselist=False)
    snapshot_items: Mapped[list["PortfolioSnapshotItem"]] = relationship(back_populates="asset")
    # Price config/history cascade with the asset (Phase 11) — unlike the
    # relationships above, these are pure pricing metadata/observations,
    # not financial/audit records, so deleting an asset that's otherwise
    # deletable removes its price config and history with it.
    price_config: Mapped["AssetPriceConfig | None"] = relationship(
        back_populates="asset", uselist=False, cascade="all, delete-orphan"
    )
    prices: Mapped[list["AssetPrice"]] = relationship(back_populates="asset", cascade="all, delete-orphan")
