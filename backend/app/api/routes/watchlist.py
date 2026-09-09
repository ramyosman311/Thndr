from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.schemas.alert import AlertRuleCreateRequest, AlertRuleOut
from app.schemas.watchlist import WatchlistAddRequest, WatchlistOut, WatchlistUpdateRequest
from app.services import alert_service, watchlist_service
from app.services.alert_service import AlertRuleNotFoundError, DuplicateAlertRuleError, InvalidAlertRuleConfigurationError
from app.services.watchlist_service import (
    AssetInactiveError,
    AssetNotFoundError,
    DuplicateWatchlistEntryError,
    WatchlistEntryNotFoundError,
)

router = APIRouter(prefix="/watchlist", tags=["watchlist"])


@router.get("", response_model=list[WatchlistOut])
async def list_watchlist(
    enabled_only: bool = False, session: AsyncSession = Depends(get_db_session)
) -> list[WatchlistOut]:
    return await watchlist_service.list_watchlist(session, enabled_only=enabled_only)


@router.post("", response_model=WatchlistOut, status_code=status.HTTP_201_CREATED)
async def add_watchlist_entry(
    request: WatchlistAddRequest, session: AsyncSession = Depends(get_db_session)
) -> WatchlistOut:
    try:
        return await watchlist_service.add_to_watchlist(session, request.asset_id, notes=request.notes)
    except AssetNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except (AssetInactiveError, DuplicateWatchlistEntryError) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.patch("/{watchlist_id}", response_model=WatchlistOut)
async def update_watchlist_entry(
    watchlist_id: UUID, request: WatchlistUpdateRequest, session: AsyncSession = Depends(get_db_session)
) -> WatchlistOut:
    try:
        return await watchlist_service.update_watchlist_entry(
            session, watchlist_id, enabled=request.enabled, notes=request.notes
        )
    except WatchlistEntryNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.delete("/{watchlist_id}", response_model=WatchlistOut)
async def remove_watchlist_entry(watchlist_id: UUID, session: AsyncSession = Depends(get_db_session)) -> WatchlistOut:
    """Logical removal only (sets `removed_at`), never a physical delete —
    see DATABASE.md, "watchlist"."""
    try:
        return await watchlist_service.remove_from_watchlist(session, watchlist_id)
    except WatchlistEntryNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/{watchlist_id}/alerts", response_model=AlertRuleOut)
async def get_watchlist_alert_rule(watchlist_id: UUID, session: AsyncSession = Depends(get_db_session)) -> AlertRuleOut:
    try:
        return await alert_service.get_alert_rule_for_watchlist(session, watchlist_id)
    except AlertRuleNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/{watchlist_id}/alerts", response_model=AlertRuleOut, status_code=status.HTTP_201_CREATED)
async def create_watchlist_alert_rule(
    watchlist_id: UUID, request: AlertRuleCreateRequest, session: AsyncSession = Depends(get_db_session)
) -> AlertRuleOut:
    try:
        return await alert_service.create_alert_rule(session, watchlist_id, **request.model_dump())
    except WatchlistEntryNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except DuplicateAlertRuleError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except InvalidAlertRuleConfigurationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
