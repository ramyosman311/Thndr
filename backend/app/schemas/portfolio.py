"""API response schemas for the Portfolio Engine.

Decimal fields serialize as JSON strings (via DecimalStr), not floats, so
exact monetary/percentage values survive the API boundary without binary
floating-point rounding (see FINANCIAL_RULES.md, "Precision").
"""

from datetime import datetime
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
    # The asset's OWN currency (never the portfolio's base_currency) --
    # a manual price submission (POST /api/assets/{id}/price/manual)
    # must be denominated in this currency, not in whatever currency
    # `current_price` below happens to be displayed in.
    asset_currency: str
    # Phase 11: null when the Price Service has no usable price for this
    # asset (PRICE_UNAVAILABLE) -- never a fabricated 0. `price_status`/
    # `price_recorded_at`/`price_is_stale` let the UI distinguish a live
    # price from a stale last-known one without guessing from nullness
    # alone (see FINANCIAL_RULES.md, "Frontend Price States"). This
    # value is in the portfolio's base_currency (see PortfolioSummaryOut),
    # already converted where needed -- it is NOT necessarily in
    # `asset_currency`.
    current_price: DecimalStr | None
    price_status: str
    price_recorded_at: datetime | None
    price_is_stale: bool
    # market_value/unrealized_pnl are null exactly when current_price is
    # null -- see domain/pnl_engine.py. cost_basis never depends on price
    # so it stays populated whenever a holding exists.
    market_value: DecimalStr | None
    cost_basis: DecimalStr | None
    unrealized_pnl: DecimalStr | None
    unrealized_pnl_percent: DecimalStr | None


class PortfolioSummaryOut(BaseModel):
    base_currency: str
    total_value: DecimalStr
    emergency_value: DecimalStr
    investable_value: DecimalStr
    denominator_basis: str
    denominator_value: DecimalStr
    emergency_excluded: bool
    # Phase 11: False when at least one held asset had no usable price,
    # meaning the totals above EXCLUDE that asset's value rather than
    # counting it as 0 -- see domain/portfolio_engine.py,
    # "Incomplete Valuation Is Not Zero Valuation".
    is_complete: bool
    unpriced_asset_ids: list[UUID]
    holdings_pnl: list[HoldingPnLOut]
    total_unrealized_pnl: DecimalStr
    total_unrealized_pnl_percent: DecimalStr | None


class BucketAllocationOut(BaseModel):
    strategy_bucket_id: UUID
    bucket_name: str
    actual_value: DecimalStr
    # bucket value / TOTAL portfolio value — always defined, for every bucket.
    total_portfolio_percent: DecimalStr
    # bucket value / the risk/investable denominator — null (never a
    # misleading number) for the bucket excluded from risk allocation.
    risk_allocation_percent: DecimalStr | None
    target_percent: DecimalStr | None
    minimum_percent: DecimalStr | None
    maximum_percent: DecimalStr | None
    allow_new_buy: bool | None
    target_status: str
    minimum_status: str
    maximum_status: str
    buy_allowed: bool
    excluded_from_risk_allocation: bool
    # Phase 11: True when this bucket's `actual_value` excludes at least
    # one held-but-unpriced position -- the bucket total is understated
    # relative to a fully priced state, never silently treated as
    # complete.
    has_unpriced_positions: bool


class PortfolioAllocationOut(BaseModel):
    total_portfolio_value: DecimalStr
    risk_denominator_basis: str
    risk_denominator_value: DecimalStr
    emergency_excluded: bool
    is_complete: bool
    unpriced_asset_ids: list[UUID]
    buckets: list[BucketAllocationOut]
