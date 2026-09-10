"""API request/response schemas for the Transaction + Holding write path.

See app/domain/transaction_engine.py for the BUY/SELL semantics this
mirrors.
"""

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, field_validator, model_validator

from app.schemas.portfolio import DecimalStr


class TransactionCreateRequest(BaseModel):
    asset_id: UUID
    # Phase 10: BUY/SELL. Phase 15 adds DEPOSIT/WITHDRAWAL (external cash
    # flow against a CASH/SAVINGS-type asset -- see services/
    # transaction_service.py for the asset_type restriction). DIVIDEND and
    # TRANSFER still have no defined holding-update semantics (TRANSFER's
    # meaning -- external transfer vs. internal move -- was deliberately
    # left unresolved, see DECISIONS.md, "Phase 15 Known Limitations") and
    # this endpoint keeps rejecting them explicitly rather than silently
    # doing nothing useful with them.
    transaction_type: Literal["BUY", "SELL", "DEPOSIT", "WITHDRAWAL"]
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

    @model_validator(mode="after")
    def cash_flow_must_use_unit_price_and_no_fees(self) -> "TransactionCreateRequest":
        """DEPOSIT/WITHDRAWAL: quantity IS the cash amount (see
        domain/transaction_engine.py's DEPOSIT/WITHDRAWAL section), so
        price must be exactly 1 and fees must be 0 -- rejected explicitly
        here rather than silently ignored, since a non-1 price or a
        nonzero fee would otherwise make quantity*price ambiguous as
        "the amount". Fee handling for a cash-flow event is deliberately
        out of scope for this phase (see DECISIONS.md, "Phase 15 Known
        Limitations") rather than guessed."""
        if self.transaction_type in ("DEPOSIT", "WITHDRAWAL"):
            if self.price != 1:
                raise ValueError("price must be exactly 1 for DEPOSIT/WITHDRAWAL")
            if self.fees != 0:
                raise ValueError("fees must be 0 for DEPOSIT/WITHDRAWAL")
        return self


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
