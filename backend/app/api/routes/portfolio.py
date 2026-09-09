from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.schemas.portfolio import PortfolioAllocationOut, PortfolioSummaryOut
from app.services.portfolio_service import (
    PortfolioNotConfiguredError,
    get_portfolio_allocation,
    get_portfolio_summary,
)

router = APIRouter(prefix="/portfolio", tags=["portfolio"])


@router.get("/summary", response_model=PortfolioSummaryOut)
async def portfolio_summary(session: AsyncSession = Depends(get_db_session)) -> PortfolioSummaryOut:
    try:
        return await get_portfolio_summary(session)
    except PortfolioNotConfiguredError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/allocation", response_model=PortfolioAllocationOut)
async def portfolio_allocation(session: AsyncSession = Depends(get_db_session)) -> PortfolioAllocationOut:
    try:
        return await get_portfolio_allocation(session)
    except PortfolioNotConfiguredError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
