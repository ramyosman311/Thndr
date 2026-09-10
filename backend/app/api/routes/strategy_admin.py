"""Strategy Bucket + Allocation Target administration (Phase 12).

Deliberately a separate router/prefix from `/portfolio/strategy/validation`
(read-only, Phase 6) -- see FINANCIAL_RULES.md, "Strategy Validation
Ownership": these routes write per-row configuration; they never
recompute or gate on the aggregate validation status that endpoint
reports.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.schemas.strategy import (
    AllocationTargetCreateRequest,
    AllocationTargetOut,
    AllocationTargetUpdateRequest,
    StrategyBucketCreateRequest,
    StrategyBucketOut,
    StrategyBucketUpdateRequest,
)
from app.services import strategy_admin_service
from app.services.strategy_admin_service import (
    AllocationTargetNotFoundError,
    DuplicateAllocationTargetError,
    DuplicateStrategyBucketNameError,
    InvalidAllocationTargetError,
    PortfolioNotConfiguredError,
    StrategyBucketNotFoundError,
)

router = APIRouter(prefix="/strategy", tags=["strategy-admin"])


@router.get("/buckets", response_model=list[StrategyBucketOut])
async def list_buckets(
    include_inactive: bool = False, session: AsyncSession = Depends(get_db_session)
) -> list[StrategyBucketOut]:
    try:
        return await strategy_admin_service.list_buckets(session, include_inactive=include_inactive)
    except PortfolioNotConfiguredError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/buckets", response_model=StrategyBucketOut, status_code=status.HTTP_201_CREATED)
async def create_bucket(
    request: StrategyBucketCreateRequest, session: AsyncSession = Depends(get_db_session)
) -> StrategyBucketOut:
    try:
        return await strategy_admin_service.create_bucket(session, request)
    except PortfolioNotConfiguredError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except DuplicateStrategyBucketNameError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.patch("/buckets/{bucket_id}", response_model=StrategyBucketOut)
async def update_bucket(
    bucket_id: UUID, request: StrategyBucketUpdateRequest, session: AsyncSession = Depends(get_db_session)
) -> StrategyBucketOut:
    try:
        return await strategy_admin_service.update_bucket(session, bucket_id, request)
    except StrategyBucketNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except DuplicateStrategyBucketNameError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/buckets/{bucket_id}/activate", response_model=StrategyBucketOut)
async def activate_bucket(bucket_id: UUID, session: AsyncSession = Depends(get_db_session)) -> StrategyBucketOut:
    try:
        return await strategy_admin_service.activate_bucket(session, bucket_id)
    except StrategyBucketNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/buckets/{bucket_id}/deactivate", response_model=StrategyBucketOut)
async def deactivate_bucket(bucket_id: UUID, session: AsyncSession = Depends(get_db_session)) -> StrategyBucketOut:
    try:
        return await strategy_admin_service.deactivate_bucket(session, bucket_id)
    except StrategyBucketNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/targets", response_model=list[AllocationTargetOut])
async def list_targets(
    include_inactive: bool = False, session: AsyncSession = Depends(get_db_session)
) -> list[AllocationTargetOut]:
    try:
        return await strategy_admin_service.list_targets(session, include_inactive=include_inactive)
    except PortfolioNotConfiguredError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/targets", response_model=AllocationTargetOut, status_code=status.HTTP_201_CREATED)
async def create_target(
    request: AllocationTargetCreateRequest, session: AsyncSession = Depends(get_db_session)
) -> AllocationTargetOut:
    try:
        return await strategy_admin_service.create_target(session, request)
    except PortfolioNotConfiguredError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except InvalidAllocationTargetError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except DuplicateAllocationTargetError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.patch("/targets/{target_id}", response_model=AllocationTargetOut)
async def update_target(
    target_id: UUID, request: AllocationTargetUpdateRequest, session: AsyncSession = Depends(get_db_session)
) -> AllocationTargetOut:
    try:
        return await strategy_admin_service.update_target(session, target_id, request)
    except AllocationTargetNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except InvalidAllocationTargetError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
