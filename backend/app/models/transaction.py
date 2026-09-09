import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, Enum, ForeignKey, Index, Numeric, TIMESTAMP, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.enums import TransactionType
from app.models.mixins import CreatedAtMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.asset import Asset


class Transaction(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """An immutable record of a buy/sell/dividend/cash event.

    Kept strictly separate from portfolio_snapshots: transactions record
    what happened (with quantity and price); snapshots record a point-in-
    time value observation and never imply quantities or prices (see
    FINANCIAL_RULES.md, "Snapshot != Transaction").

    Numeric precision: quantity/price use NUMERIC(20, 8) to support
    fractional units and low-priced assets exactly. fees uses
    NUMERIC(18, 2) as a plain currency amount.
    """

    __tablename__ = "transactions"
    __table_args__ = (
        CheckConstraint("quantity >= 0", name="ck_transactions_quantity_non_negative"),
        CheckConstraint("price >= 0", name="ck_transactions_price_non_negative"),
        CheckConstraint("fees >= 0", name="ck_transactions_fees_non_negative"),
        Index("ix_transactions_asset_id_transaction_date", "asset_id", "transaction_date"),
    )

    asset_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("assets.id", ondelete="RESTRICT"), nullable=False
    )
    transaction_type: Mapped[TransactionType] = mapped_column(
        Enum(TransactionType, name="transaction_type", native_enum=True), nullable=False
    )
    quantity: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    fees: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=Decimal("0"))
    transaction_date: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    asset: Mapped["Asset"] = relationship(back_populates="transactions")
