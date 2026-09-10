"""API routes for the Phase 11 price infrastructure.

Every route here is a request-time read (or an explicit, user-initiated
write) served entirely from `asset_prices` via services/price_service.py
-- NONE of them call a live PriceProvider except `POST .../price/refresh`,
which is a deliberate, single-asset, user-initiated exception to the
non-blocking rule (see its own docstring below). Background/batch
refresh is a separate, unauthenticated-by-design internal process
(app/workers/price_refresh.py) never exposed here (see FINANCIAL_RULES.md,
"Non-Blocking Valuation" and "Do Not Expose Provider Controls
Insecurely").
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.repositories import price_repository
from app.schemas.price import (
    AssetPriceConfigOut,
    AssetPriceConfigUpsertRequest,
    ManualPriceCreateRequest,
    PriceObservationOut,
    PriceOut,
)
from app.services import price_config_service, price_orchestrator, price_service
from app.services.price_config_service import (
    AssetNotFoundError as PriceConfigAssetNotFoundError,
    InvalidPriceConfigError,
    InvalidProviderError,
)
from app.services.price_service import InvalidManualPriceError

router = APIRouter(prefix="/assets", tags=["prices"])


def _to_price_out(asset_id: UUID, result) -> PriceOut:
    return PriceOut(
        asset_id=asset_id,
        status=result.status.value,
        price=result.price,
        currency=result.currency,
        provider=result.provider,
        provider_symbol=result.provider_symbol,
        recorded_at=result.recorded_at,
        age_seconds=result.age_seconds,
        is_stale=result.is_stale,
        reason=result.reason,
    )


async def _get_asset_or_404(session: AsyncSession, asset_id: UUID):
    asset = await price_repository.get_asset_by_id(session, asset_id)
    if asset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Asset {asset_id} does not exist.")
    return asset


@router.get("/{asset_id}/price", response_model=PriceOut)
async def get_asset_price(asset_id: UUID, session: AsyncSession = Depends(get_db_session)) -> PriceOut:
    """The asset's current price as classified by the Price Service --
    a pure DB read, never a live provider call."""
    asset = await _get_asset_or_404(session, asset_id)
    result = await price_service.get_asset_price(session, asset)
    return _to_price_out(asset_id, result)


@router.get("/{asset_id}/prices", response_model=list[PriceObservationOut])
async def list_asset_prices(
    asset_id: UUID, limit: int = 100, session: AsyncSession = Depends(get_db_session)
) -> list[PriceObservationOut]:
    """Full price history for the asset, most recent first."""
    await _get_asset_or_404(session, asset_id)
    observations = await price_repository.list_price_history(session, asset_id, limit=limit)
    return [
        PriceObservationOut(
            id=o.id,
            price=o.price,
            currency=o.currency,
            provider=o.provider,
            source=o.source,
            provider_symbol=o.provider_symbol,
            recorded_at=o.recorded_at,
            is_manual=o.is_manual,
        )
        for o in observations
    ]


@router.post("/{asset_id}/price/manual", response_model=PriceOut, status_code=status.HTTP_201_CREATED)
async def create_manual_price(
    asset_id: UUID, request: ManualPriceCreateRequest, session: AsyncSession = Depends(get_db_session)
) -> PriceOut:
    """Records a user-submitted manual price observation. Never touches
    any transaction, holding quantity, or average cost (see
    FINANCIAL_RULES.md, "Manual Price Never Touches Transaction
    History")."""
    asset = await _get_asset_or_404(session, asset_id)
    try:
        await price_service.record_manual_price(session, asset, price=request.price, currency=request.currency)
    except InvalidManualPriceError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    result = await price_service.get_asset_price(session, asset)
    return _to_price_out(asset_id, result)


@router.post("/{asset_id}/price/refresh", response_model=PriceOut)
async def refresh_asset_price(asset_id: UUID, session: AsyncSession = Depends(get_db_session)) -> PriceOut:
    """Synchronously fetches this one asset's price from its configured
    provider right now. This is the ONE deliberate, user-initiated
    exception to the non-blocking valuation rule anywhere in this system
    -- every other read in the app (Portfolio, Allocation, P&L,
    Dashboard, Alerts) is served purely from `asset_prices` and never
    calls this. Requires `automated_fetching_enabled` with a configured
    provider; otherwise there is nothing to refresh and this returns
    409, leaving the asset's last known price untouched."""
    asset = await _get_asset_or_404(session, asset_id)
    config = await price_repository.get_price_config_by_asset_id(session, asset_id)
    if config is None or not config.automated_fetching_enabled:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Asset {asset_id} has no automated price provider configured.",
        )
    await price_orchestrator.refresh_one_asset(session, config)
    await session.commit()
    result = await price_service.get_asset_price(session, asset)
    return _to_price_out(asset_id, result)


@router.get("/{asset_id}/price-config", response_model=AssetPriceConfigOut)
async def get_asset_price_config(
    asset_id: UUID, session: AsyncSession = Depends(get_db_session)
) -> AssetPriceConfigOut:
    """Phase 12 administration read. `configured: false` (with every
    other field null/default) is a normal response for an asset that
    has no config row yet -- never a 404."""
    try:
        return await price_config_service.get_price_config(session, asset_id)
    except PriceConfigAssetNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.put("/{asset_id}/price-config", response_model=AssetPriceConfigOut)
async def put_asset_price_config(
    asset_id: UUID, request: AssetPriceConfigUpsertRequest, session: AsyncSession = Depends(get_db_session)
) -> AssetPriceConfigOut:
    """Full-replacement upsert (Phase 12) -- creates the config row if
    none exists yet. Provider names are validated against the real
    provider registry, never accepted merely because a string was
    entered (see FINANCIAL_RULES.md, "Provider Configuration Is Data,
    Not Code")."""
    try:
        return await price_config_service.upsert_price_config(session, asset_id, request)
    except PriceConfigAssetNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except (InvalidProviderError, InvalidPriceConfigError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
