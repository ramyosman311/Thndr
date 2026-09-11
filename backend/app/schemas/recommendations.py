"""API response schemas for the Smart Recommendations engine (Phase 18).

See app/domain/recommendation_engine.py for the semantics this mirrors.
Read-only -- never accepted as a request body anywhere, since nothing in
this phase executes a trade (see FINANCIAL_RULES.md, "Rebalancing Engine
Rules", which applies equally here).
"""

from datetime import datetime

from pydantic import BaseModel

from app.schemas.portfolio import DecimalStr


class PortfolioRecommendationOut(BaseModel):
    id: str
    type: str
    severity: str
    title: str
    message: str
    suggested_action: str
    target_category: str | None
    amount: DecimalStr | None
    evaluated_at: datetime


class RecommendationsOut(BaseModel):
    # Phase 11/16/17 precedent: propagated from the same totals
    # computation every other portfolio-valuation-derived endpoint
    # exposes it from -- false when at least one held position's value
    # could not be determined, meaning the recommendations below were
    # computed against an incomplete valuation.
    is_complete: bool
    recommendations: list[PortfolioRecommendationOut]
