import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Index, Numeric, String, TIMESTAMP
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import CreatedAtMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.asset import Asset


class AssetPrice(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """An immutable, timestamped price observation for one asset (Phase 11).

    This is the single historical record of "what price did we observe,
    from where, and when" — never mutated once written (see
    FINANCIAL_RULES.md, "Price Observations Are Immutable"). It is
    distinct from `holdings.current_price` (a legacy, no-longer-written
    column — see FINANCIAL_RULES.md, "One Authoritative Pricing Path"),
    from `transactions.price` (an executed trade price), and from
    `holdings.average_cost` (an accounting cost basis) — see
    FINANCIAL_RULES.md, "Core Domain Separation".

    `is_manual=True` marks a user-entered override; the manual-vs-
    automated precedence rule (domain/manual_precedence.py) decides
    whether a later automated row may be treated as more current than a
    manual one — it never deletes or edits the manual row itself.

    `ON DELETE CASCADE`: unlike `transactions` (a legal/audit record that
    must survive independently), a price observation with no asset behind
    it is meaningless — deleting an otherwise-deletable asset removes its
    price history along with it.
    """

    __tablename__ = "asset_prices"
    __table_args__ = (
        CheckConstraint("price >= 0", name="ck_asset_prices_price_non_negative"),
        Index("ix_asset_prices_asset_id_recorded_at", "asset_id", "recorded_at"),
    )

    asset_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("assets.id", ondelete="CASCADE"), nullable=False
    )
    price: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    currency: Mapped[str] = mapped_column(String(8), nullable=False)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    source: Mapped[str | None] = mapped_column(String(255), nullable=True)
    provider_symbol: Mapped[str | None] = mapped_column(String(64), nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    is_manual: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    price_metadata: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    asset: Mapped["Asset"] = relationship(back_populates="prices")
