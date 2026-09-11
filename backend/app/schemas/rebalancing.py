"""API response schemas for the Smart Rebalancing Engine (Phase 17).

See app/domain/rebalancing_engine.py for the semantics this mirrors.
Recommendation/calculation only — see FINANCIAL_RULES.md, "Rebalancing
Engine Rules": this schema is never accepted as a request body anywhere,
since nothing in this phase executes a trade.
"""

from uuid import UUID

from pydantic import BaseModel

from app.schemas.portfolio import DecimalStr


class RebalancingRecommendationOut(BaseModel):
    strategy_bucket_id: UUID
    bucket_name: str
    actual_value: DecimalStr
    current_percent: DecimalStr | None
    target_percent: DecimalStr | None
    maximum_percent: DecimalStr | None
    difference_percent: DecimalStr | None
    target_value: DecimalStr | None
    difference_value: DecimalStr | None
    action: str
    recommended_value: DecimalStr | None
    priority: int
    allow_new_buy: bool | None
    status: str
    reason: str


class RebalancingOut(BaseModel):
    available_cash: DecimalStr
    total_recommended_buy: DecimalStr
    total_recommended_reduce: DecimalStr
    # Phase 11/16: propagated from the same totals computation every
    # other portfolio-valuation endpoint exposes it from — false when at
    # least one held position's value could not be determined, meaning
    # every value/percent above may be understated rather than complete.
    is_complete: bool
    recommendations: list[RebalancingRecommendationOut]
