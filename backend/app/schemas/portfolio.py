"""API response schemas for the Portfolio Engine.

Decimal fields serialize as JSON strings (via DecimalStr), not floats, so
exact monetary/percentage values survive the API boundary without binary
floating-point rounding (see FINANCIAL_RULES.md, "Precision").
"""

from datetime import datetime
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, PlainSerializer, field_validator

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
    # Phase 16: `current_price` is null only in the true worst case --
    # no live price, no stale last-known price, AND no safe same-
    # currency average-cost fallback (see
    # services/portfolio_shared.resolve_valuation_price). Whenever a
    # price IS present, `price_status` says whether it should be
    # trusted as a confirmed live market price:
    #   "LIVE"         -- a genuinely current market price.
    #   "PENDING_SYNC" -- a stale last-known price OR the average-cost
    #                     fallback; a real number safe to display as
    #                     the holding's estimated value, but
    #                     `unrealized_pnl`/`unrealized_pnl_percent` are
    #                     always exactly 0 in this state -- a P/L
    #                     computed from a non-live price is never
    #                     presented as a real profit/loss (see
    #                     FINANCIAL_RULES.md, "PENDING_SYNC Never
    #                     Implies Profit"). This value is in the
    #                     portfolio's base_currency (see
    #                     PortfolioSummaryOut), already converted where
    #                     needed -- it is NOT necessarily in
    #                     `asset_currency`.
    current_price: DecimalStr | None
    price_status: str
    price_recorded_at: datetime | None
    price_is_stale: bool
    # market_value is null exactly when current_price is null -- see
    # domain/pnl_engine.py. cost_basis never depends on price so it
    # stays populated whenever a holding exists. unrealized_pnl is null
    # only alongside a null market_value; whenever a price (live or
    # PENDING_SYNC) is available it is a real Decimal, forced to exactly
    # 0 in the PENDING_SYNC case (see `price_status` above).
    market_value: DecimalStr | None
    cost_basis: DecimalStr | None
    unrealized_pnl: DecimalStr | None
    unrealized_pnl_percent: DecimalStr | None


class PortfolioSummaryOut(BaseModel):
    """Phase 16 note on the six value fields below -- each has a distinct,
    non-overlapping meaning (see FINANCIAL_RULES.md, "Portfolio Value vs
    Investable Value vs Available Cash"):

    - `total_value` ("Portfolio Value"): every held position's value,
      always -- equals `emergency_value + available_cash +
      invested_market_value` by construction.
    - `emergency_value` ("Reserved/Emergency Cash"): the value of
      whichever single asset is configured as the portfolio's emergency
      reserve (`portfolio_configs.emergency_asset_id`), if any.
    - `investable_value`: total_value minus emergency_value -- this is
      ONLY the denominator historically used for risk-allocation
      percentages (see domain/allocation_engine.py); it is NOT spendable
      cash and INCLUDES invested market value. Never label this
      "Investable Cash" in any UI -- that is `available_cash` below.
    - `available_cash` ("Available/Free Cash", i.e. what the product
      calls "Investable Cash"): the value of non-emergency CASH/SAVINGS
      holdings only -- the actual amount a user could deploy into a new
      purchase right now. Zero whenever no free cash is held, even if
      `total_value` and `investable_value` are both large.
    - `invested_market_value`: the value of every other (non-cash,
      non-emergency) holding -- `investable_value` minus
      `available_cash`.
    - `denominator_value`/`denominator_basis`: unchanged Phase 5/6
      concept, unrelated to cash -- which of `investable_value`/
      `total_value` is actually used as the allocation-percentage
      denominator, per `emergency_excluded`.
    """

    base_currency: str
    total_value: DecimalStr
    emergency_value: DecimalStr
    investable_value: DecimalStr
    available_cash: DecimalStr
    invested_market_value: DecimalStr
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


# --- Portfolio configuration administration (Phase 12) -----------------


class PortfolioConfigOut(BaseModel):
    id: UUID
    name: str
    base_currency: str
    emergency_asset_id: UUID | None
    emergency_excluded: bool
    telegram_enabled: bool


def _validate_currency_code(value: str) -> str:
    value = value.strip().upper()
    if not (2 <= len(value) <= 8) or not value.isalpha():
        raise ValueError("base_currency must be a 2-8 letter code, e.g. EGP, USD")
    return value


class PortfolioConfigCreateRequest(BaseModel):
    name: str
    base_currency: str
    emergency_asset_id: UUID | None = None
    emergency_excluded: bool = False

    @field_validator("name")
    @classmethod
    def name_must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("name must not be blank")
        return value

    @field_validator("base_currency")
    @classmethod
    def base_currency_must_be_a_plausible_code(cls, value: str) -> str:
        return _validate_currency_code(value)


class PortfolioConfigUpdateRequest(BaseModel):
    """All fields optional -- only the ones provided are changed.
    `base_currency` is accepted here but the service layer rejects the
    change outright once any transaction exists (see FINANCIAL_RULES.md,
    "Base Currency Change Policy"). `clear_emergency_asset` explicitly
    unsets `emergency_asset_id` (a plain `None` in JSON is
    indistinguishable from "field omitted" for an Optional field, so a
    dedicated flag is used instead — same pattern as
    AssetUpdateRequest.clear_strategy_bucket)."""

    name: str | None = None
    base_currency: str | None = None
    emergency_asset_id: UUID | None = None
    clear_emergency_asset: bool = False
    emergency_excluded: bool | None = None
    telegram_enabled: bool | None = None

    @field_validator("name")
    @classmethod
    def name_must_not_be_blank(cls, value: str | None) -> str | None:
        if value is None:
            return value
        value = value.strip()
        if not value:
            raise ValueError("name must not be blank")
        return value

    @field_validator("base_currency")
    @classmethod
    def base_currency_must_be_a_plausible_code(cls, value: str | None) -> str | None:
        if value is None:
            return value
        return _validate_currency_code(value)
