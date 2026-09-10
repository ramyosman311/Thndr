from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, Index, Numeric, String, TIMESTAMP
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.mixins import CreatedAtMixin, UUIDPrimaryKeyMixin


class FxRate(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """An immutable, timestamped currency-pair observation (Phase 11).

    `rate` means: 1 unit of `base_currency` = `rate` units of
    `quote_currency` (standard BASE/QUOTE quoting). Valuing an asset
    priced in `base_currency` into a portfolio whose `base_currency`
    equals this row's `quote_currency` is `asset_value * rate` — see
    FINANCIAL_RULES.md, "FX Conversion".

    Not tied to any asset, holding, or portfolio — currency pairs are a
    global, shared observation domain, exactly like asset prices are
    shared at the Asset level rather than duplicated per portfolio (see
    FINANCIAL_RULES.md, "Generic Multi-Portfolio Architecture").

    No uniqueness constraint on (base_currency, quote_currency,
    recorded_at): multiple providers may report a rate for the same
    instant, and this table is an append-only observation log, not a
    single current-rate cache.
    """

    __tablename__ = "fx_rates"
    __table_args__ = (
        CheckConstraint("rate > 0", name="ck_fx_rates_rate_positive"),
        Index("ix_fx_rates_pair_recorded_at", "base_currency", "quote_currency", "recorded_at"),
    )

    base_currency: Mapped[str] = mapped_column(String(8), nullable=False)
    quote_currency: Mapped[str] = mapped_column(String(8), nullable=False)
    rate: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    rate_metadata: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
