from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.schemas.strategy import StrategyValidationOut
from app.services.strategy_service import PortfolioNotConfiguredError, get_strategy_validation

router = APIRouter(prefix="/portfolio/strategy", tags=["strategy"])


@router.get("/validation", response_model=StrategyValidationOut)
async def strategy_validation(session: AsyncSession = Depends(get_db_session)) -> StrategyValidationOut:
    """Read-only. Always returns 200 with a validation status/explanation
    when a portfolio is configured — an incomplete or overallocated
    strategy is a normal, successful response, not a server error. Only a
    missing portfolio_configs row raises 404."""
    try:
        return await get_strategy_validation(session)
    except PortfolioNotConfiguredError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
