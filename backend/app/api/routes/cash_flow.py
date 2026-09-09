from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.schemas.inflow import InflowAllocateRequest, InflowAllocationOut
from app.services.inflow_service import PortfolioNotConfiguredError, get_inflow_allocation

router = APIRouter(prefix="/cash-flow", tags=["cash-flow"])


@router.post("/allocate", response_model=InflowAllocationOut)
async def allocate_cash_flow(
    request: InflowAllocateRequest, session: AsyncSession = Depends(get_db_session)
) -> InflowAllocationOut:
    """Calculates a recommended allocation of new cash. Read-only: this
    never creates a transaction, never modifies holdings, and never
    executes a trade — it only calculates and returns a recommendation."""
    try:
        return await get_inflow_allocation(session, request.amount)
    except PortfolioNotConfiguredError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
