from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.core.database import get_db_session
from app.models import User
from app.schemas.notification import NotificationOut, NotificationsOut
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
from app.services.notification_service import (
    NotificationNotFoundError,
    list_notifications,
    mark_all_notifications_read,
    mark_notification_read,
)
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
async def get_portfolio_config_route(
    session: AsyncSession = Depends(get_db_session), user: User = Depends(get_current_user)
) -> PortfolioConfigOut:
    try:
        return await portfolio_config_service.get_config(session, user.id)
    except PortfolioConfigNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/config", response_model=PortfolioConfigOut, status_code=status.HTTP_201_CREATED)
async def create_portfolio_config_route(
    request: PortfolioConfigCreateRequest,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
) -> PortfolioConfigOut:
    try:
        return await portfolio_config_service.create_config(session, user.id, request)
    except PortfolioConfigAlreadyExistsError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except InvalidEmergencyAssetError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.patch("/config", response_model=PortfolioConfigOut)
async def update_portfolio_config_route(
    request: PortfolioConfigUpdateRequest,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
) -> PortfolioConfigOut:
    try:
        return await portfolio_config_service.update_config(session, user.id, request)
    except PortfolioConfigNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except InvalidEmergencyAssetError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except BaseCurrencyChangeNotAllowedError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.get("/summary", response_model=PortfolioSummaryOut)
async def portfolio_summary(
    session: AsyncSession = Depends(get_db_session), user: User = Depends(get_current_user)
) -> PortfolioSummaryOut:
    try:
        return await get_portfolio_summary(session, user.id)
    except PortfolioNotConfiguredError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/allocation", response_model=PortfolioAllocationOut)
async def portfolio_allocation(
    session: AsyncSession = Depends(get_db_session), user: User = Depends(get_current_user)
) -> PortfolioAllocationOut:
    try:
        return await get_portfolio_allocation(session, user.id)
    except PortfolioNotConfiguredError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/rebalancing", response_model=RebalancingOut)
async def portfolio_rebalancing(
    session: AsyncSession = Depends(get_db_session), user: User = Depends(get_current_user)
) -> RebalancingOut:
    """Phase 17: recommendation/calculation only — reads current
    portfolio state, strategy, and cash, and returns deterministic BUY/
    REDUCE/HOLD recommendations. Never executes a trade, moves cash, or
    modifies strategy configuration (see FINANCIAL_RULES.md,
    "Rebalancing Engine Rules")."""
    try:
        return await get_rebalancing_recommendations(session, user.id)
    except RebalancingNotConfiguredError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/recommendations", response_model=RecommendationsOut)
async def portfolio_recommendations(
    session: AsyncSession = Depends(get_db_session), user: User = Depends(get_current_user)
) -> RecommendationsOut:
    """Phase 18: read-only, deterministic guidance synthesized from the
    Smart Rebalancing Engine's (Phase 17) own output — never recomputes a
    BUY/REDUCE amount or category status, and never executes a trade or
    mutates any financial state (see FINANCIAL_RULES.md, "Rebalancing
    Engine Rules", which applies equally to this endpoint)."""
    try:
        return await get_portfolio_recommendations(session, user.id)
    except RebalancingNotConfiguredError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/notifications", response_model=NotificationsOut)
async def portfolio_notifications(
    session: AsyncSession = Depends(get_db_session), user: User = Depends(get_current_user)
) -> NotificationsOut:
    """Phase 19: the in-app Notification Center. Evaluates the existing
    alert engine (Phase 8) and Smart Recommendations (Phase 18) — never
    recomputing either — and returns the persisted, deduplicated
    notification inbox. Never unconfigured-404s: with no portfolio
    configured yet there is simply nothing to notify, an empty list.
    Read-only w.r.t. financial state; only notification rows are
    written (see FINANCIAL_RULES.md, "Notification Layer Rules")."""
    return await list_notifications(session, user.id)


@router.patch("/notifications/{notification_id}/read", response_model=NotificationOut)
async def mark_notification_read_route(
    notification_id: UUID,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
) -> NotificationOut:
    """Mutates only `notifications.read_at` — never financial state."""
    try:
        return await mark_notification_read(session, user.id, notification_id)
    except NotificationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/notifications/read-all", response_model=NotificationsOut)
async def mark_all_notifications_read_route(
    session: AsyncSession = Depends(get_db_session), user: User = Depends(get_current_user)
) -> NotificationsOut:
    """Mutates only `notifications.read_at` for every currently-unread
    row — never financial state."""
    return await mark_all_notifications_read(session, user.id)
