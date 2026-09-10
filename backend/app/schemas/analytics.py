"""API response schemas for Phase 15 wealth analytics.

Deliberately exposes only frontend-relevant fields -- no snapshot/
transaction IDs, no trigger_source, no internal worker metadata (see
DECISIONS.md, "Phase 15 Analytics API").
"""

from pydantic import BaseModel

from app.schemas.portfolio import DecimalStr


class AnalyticsPointOut(BaseModel):
    date: str  # ISO calendar date (UTC), e.g. "2026-09-01"
    portfolio_value: DecimalStr
    invested_capital: DecimalStr
    total_pnl: DecimalStr
    # None exactly when TWR is undefined up to this point (see
    # domain/twr_engine.py) -- never a fabricated 0.0.
    twr_percentage: DecimalStr | None


class PortfolioAnalyticsHistoryOut(BaseModel):
    range: str
    base_currency: str
    data: list[AnalyticsPointOut]
    # True when `data` is empty because fewer than two eligible historical
    # observations exist for the requested range -- the frontend must
    # render an explicit "insufficient data" state, never an empty chart
    # presented as if it were a real flat/zero result.
    insufficient_history: bool
    message: str | None
