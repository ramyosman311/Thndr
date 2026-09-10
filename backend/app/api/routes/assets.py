from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.schemas.asset import AssetCreateRequest, AssetOut, AssetUpdateRequest
from app.services import asset_service
from app.services.asset_service import (
    AssetHasHistoricalDataError,
    AssetNotFoundError,
    CurrencyChangeNotAllowedError,
    DuplicateAssetSymbolError,
    InvalidStrategyBucketError,
)

router = APIRouter(prefix="/assets", tags=["assets"])


@router.get("", response_model=list[AssetOut])
async def list_assets(
    include_inactive: bool = False, session: AsyncSession = Depends(get_db_session)
) -> list[AssetOut]:
    """Active-only by default (Phase 9 contract: the Watchlist/Transaction
    asset pickers rely on this) — pass `include_inactive=true` for the
    Phase 12 admin listing, which must also show deactivated assets so
    they remain visible/reactivatable."""
    return await asset_service.list_assets(session, include_inactive=include_inactive)


@router.post("", response_model=AssetOut, status_code=status.HTTP_201_CREATED)
async def create_asset(
    request: AssetCreateRequest, session: AsyncSession = Depends(get_db_session)
) -> AssetOut:
    try:
        return await asset_service.create_asset(session, request)
    except DuplicateAssetSymbolError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except InvalidStrategyBucketError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/{asset_id}", response_model=AssetOut)
async def get_asset(asset_id: UUID, session: AsyncSession = Depends(get_db_session)) -> AssetOut:
    try:
        return await asset_service.get_asset(session, asset_id)
    except AssetNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.patch("/{asset_id}", response_model=AssetOut)
async def update_asset(
    asset_id: UUID, request: AssetUpdateRequest, session: AsyncSession = Depends(get_db_session)
) -> AssetOut:
    try:
        return await asset_service.update_asset(session, asset_id, request)
    except AssetNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except InvalidStrategyBucketError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except CurrencyChangeNotAllowedError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/{asset_id}/activate", response_model=AssetOut)
async def activate_asset(asset_id: UUID, session: AsyncSession = Depends(get_db_session)) -> AssetOut:
    try:
        return await asset_service.activate_asset(session, asset_id)
    except AssetNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/{asset_id}/deactivate", response_model=AssetOut)
async def deactivate_asset(asset_id: UUID, session: AsyncSession = Depends(get_db_session)) -> AssetOut:
    try:
        return await asset_service.deactivate_asset(session, asset_id)
    except AssetNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.delete("/{asset_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_asset(asset_id: UUID, session: AsyncSession = Depends(get_db_session)) -> None:
    """Hard delete — only succeeds when the asset has zero historical
    data (see FINANCIAL_RULES.md, "Asset Deletion Policy"). Otherwise
    `409`; deactivate via `POST /{asset_id}/deactivate` instead."""
    try:
        await asset_service.delete_asset(session, asset_id)
    except AssetNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except AssetHasHistoricalDataError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
