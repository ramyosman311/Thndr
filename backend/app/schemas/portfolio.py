"""API response schemas for the Portfolio Engine.

Decimal fields serialize as JSON strings (via DecimalStr), not floats, so
exact monetary/percentage values survive the API boundary without binary
floating-point rounding (see FINANCIAL_RULES.md, "Precision").
"""

from decimal import Decimal
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, PlainSerializer

DecimalStr = Annotated[Decimal, PlainSerializer(lambda v: str(v), return_type=str)]


class HoldingPnLOut(BaseModel):
    asset_id: UUID
    symbol: str
    quantity: DecimalStr
    average_cost: DecimalStr
    current_price: DecimalStr
    market_value: DecimalStr
    cost_basis: DecimalStr
    unrealized_pnl: DecimalStr
    unrealized_pnl_percent: DecimalStr | None


class PortfolioSummaryOut(BaseModel):
    base_currency: str
    total_value: DecimalStr
    emergency_value: DecimalStr
    investable_value: DecimalStr
    denominator_basis: str
    denominator_value: DecimalStr
    emergency_excluded: bool
    holdings_pnl: list[HoldingPnLOut]


class BucketAllocationOut(BaseModel):
    strategy_bucket_id: UUID
    bucket_name: str
    actual_value: DecimalStr
    actual_percent: DecimalStr
    target_percent: DecimalStr | None
    minimum_percent: DecimalStr | None
    maximum_percent: DecimalStr | None
    allow_new_buy: bool | None
    target_status: str
    minimum_status: str
    maximum_status: str
    buy_allowed: bool


class PortfolioAllocationOut(BaseModel):
    denominator_basis: str
    denominator_value: DecimalStr
    emergency_excluded: bool
    buckets: list[BucketAllocationOut]
