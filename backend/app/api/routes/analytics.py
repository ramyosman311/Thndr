from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.schemas.analytics import PortfolioAnalyticsHistoryOut
from app.services.portfolio_analytics_service import (
    InvalidRangeError,
    PortfolioNotConfiguredError,
    get_portfolio_analytics_history,
)

router = APIRouter(prefix="/portfolio/analytics", tags=["analytics"])


@router.get("/history", response_model=PortfolioAnalyticsHistoryOut)
async def get_analytics_history(
    range: str = Query("1M", pattern="^(1W|1M|3M|YTD|ALL)$"),
    session: AsyncSession = Depends(get_db_session),
) -> PortfolioAnalyticsHistoryOut:
    """Read-only wealth history derived from persisted portfolio snapshots
    only (Phase 15) -- never computed from today's live holdings, never
    interpolated. See services/portfolio_analytics_service.py."""
    try:
        return await get_portfolio_analytics_history(session, range_key=range)
    except PortfolioNotConfiguredError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except InvalidRangeError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
