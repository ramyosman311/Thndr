"""API request/response schemas for the Smart Inflow Allocator.

See app/domain/inflow_allocator.py for the semantics this mirrors.
"""

from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.schemas.portfolio import DecimalStr


class InflowAllocateRequest(BaseModel):
    amount: DecimalStr = Field(..., description="New cash amount to allocate. Must be greater than 0.")

    @field_validator("amount")
    @classmethod
    def amount_must_be_positive(cls, value: Decimal) -> Decimal:
        if value <= 0:
            raise ValueError("amount must be greater than 0")
        return value


class InflowRecommendationOut(BaseModel):
    strategy_bucket_id: UUID
    bucket_name: str
    current_value: DecimalStr
    current_percent: DecimalStr | None
    target_percent: DecimalStr | None
    maximum_percent: DecimalStr | None
    allow_new_buy: bool | None
    priority: int
    target_gap: DecimalStr | None
    maximum_capacity: DecimalStr | None
    eligible: bool
    allocated_amount: DecimalStr
    status: str
    projected_value: DecimalStr | None
    projected_percent: DecimalStr | None


class InflowAllocationOut(BaseModel):
    requested_cash: DecimalStr
    allocated_cash: DecimalStr
    unallocated_cash: DecimalStr
    strategy_status: str
    strategy_is_valid: bool
    # Phase 11: False when at least one held position's value could not
    # be determined -- the investable/risk denominator this allocation
    # is based on excludes that position's value rather than treating
    # it as 0.
    is_complete: bool
    recommendations: list[InflowRecommendationOut]
