"""API request/response schemas for the Transaction + Holding write path.

See app/domain/transaction_engine.py for the BUY/SELL semantics this
mirrors.
"""

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, field_validator

from app.schemas.portfolio import DecimalStr


class TransactionCreateRequest(BaseModel):
    asset_id: UUID
    # Phase 10 implements BUY/SELL only; DIVIDEND/DEPOSIT/WITHDRAWAL/
    # TRANSFER exist on the model's enum for a future phase but have no
    # holding-update semantics defined yet, so this endpoint rejects them
    # explicitly rather than silently doing nothing useful with them.
    transaction_type: Literal["BUY", "SELL"]
    quantity: DecimalStr
    price: DecimalStr
    fees: DecimalStr = Decimal("0")
    transaction_date: datetime
    notes: str | None = None

    @field_validator("quantity")
    @classmethod
    def quantity_must_be_positive(cls, value: Decimal) -> Decimal:
        if value <= 0:
            raise ValueError("quantity must be greater than 0")
        return value

    @field_validator("price")
    @classmethod
    def price_must_not_be_negative(cls, value: Decimal) -> Decimal:
        if value < 0:
            raise ValueError("price must not be negative")
        return value

    @field_validator("fees")
    @classmethod
    def fees_must_not_be_negative(cls, value: Decimal) -> Decimal:
        if value < 0:
            raise ValueError("fees must not be negative")
        return value


class TransactionOut(BaseModel):
    id: UUID
    asset_id: UUID
    asset_symbol: str
    transaction_type: str
    quantity: DecimalStr
    price: DecimalStr
    fees: DecimalStr
    transaction_date: datetime
    notes: str | None
    created_at: datetime


class HoldingSnapshotOut(BaseModel):
    quantity: DecimalStr
    average_cost: DecimalStr
    # Phase 11: null when the Price Service has no usable price for this
    # asset -- never a fabricated 0 (see FINANCIAL_RULES.md, "Never
    # Fabricate A Price").
    current_price: DecimalStr | None
    price_status: str


class TransactionResultOut(BaseModel):
    transaction: TransactionOut
    holding: HoldingSnapshotOut
    # Only present for SELL — the immediate realized P/L of that specific
    # sale (sale proceeds net of fees, minus the proportional cost basis
    # removed). Never stored as a running ledger, never combined with
    # unrealized P/L. None for BUY.
    realized_pnl: DecimalStr | None
