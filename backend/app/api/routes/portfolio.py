from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.schemas.portfolio import (
    PortfolioAllocationOut,
    PortfolioConfigCreateRequest,
    PortfolioConfigOut,
    PortfolioConfigUpdateRequest,
    PortfolioSummaryOut,
)
from app.schemas.rebalancing import RebalancingOut
from app.schemas.recommendations import RecommendationsOut
from app.services import portfolio_config_service
from app.services.portfolio_config_service import (
    BaseCurrencyChangeNotAllowedError,
    InvalidEmergencyAssetError,
    PortfolioConfigAlreadyExistsError,
    PortfolioConfigNotFoundError,
)
from app.services.portfolio_service import (
    PortfolioNotConfiguredError,
    get_portfolio_allocation,
    get_portfolio_summary,
)
from app.services.rebalancing_service import RebalancingNotConfiguredError, get_rebalancing_recommendations
from app.services.recommendation_service import get_portfolio_recommendations

router = APIRouter(prefix="/portfolio", tags=["portfolio"])


@router.get("/config", response_model=PortfolioConfigOut)
async def get_portfolio_config_route(session: AsyncSession = Depends(get_db_session)) -> PortfolioConfigOut:
    try:
        return await portfolio_config_service.get_config(session)
    except PortfolioConfigNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/config", response_model=PortfolioConfigOut, status_code=status.HTTP_201_CREATED)
async def create_portfolio_config_route(
    request: PortfolioConfigCreateRequest, session: AsyncSession = Depends(get_db_session)
) -> PortfolioConfigOut:
    try:
        return await portfolio_config_service.create_config(session, request)
    except PortfolioConfigAlreadyExistsError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except InvalidEmergencyAssetError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.patch("/config", response_model=PortfolioConfigOut)
async def update_portfolio_config_route(
    request: PortfolioConfigUpdateRequest, session: AsyncSession = Depends(get_db_session)
) -> PortfolioConfigOut:
    try:
        return await portfolio_config_service.update_config(session, request)
    except PortfolioConfigNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except InvalidEmergencyAssetError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except BaseCurrencyChangeNotAllowedError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


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


@router.get("/rebalancing", response_model=RebalancingOut)
async def portfolio_rebalancing(session: AsyncSession = Depends(get_db_session)) -> RebalancingOut:
    """Phase 17: recommendation/calculation only — reads current
    portfolio state, strategy, and cash, and returns deterministic BUY/
    REDUCE/HOLD recommendations. Never executes a trade, moves cash, or
    modifies strategy configuration (see FINANCIAL_RULES.md,
    "Rebalancing Engine Rules")."""
    try:
        return await get_rebalancing_recommendations(session)
    except RebalancingNotConfiguredError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/recommendations", response_model=RecommendationsOut)
async def portfolio_recommendations(session: AsyncSession = Depends(get_db_session)) -> RecommendationsOut:
    """Phase 18: read-only, deterministic guidance synthesized from the
    Smart Rebalancing Engine's (Phase 17) own output — never recomputes a
    BUY/REDUCE amount or category status, and never executes a trade or
    mutates any financial state (see FINANCIAL_RULES.md, "Rebalancing
    Engine Rules", which applies equally to this endpoint)."""
    try:
        return await get_portfolio_recommendations(session)
    except RebalancingNotConfiguredError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
