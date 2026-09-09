from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.schemas.asset import AssetOut
from app.services.asset_service import list_active_assets

router = APIRouter(prefix="/assets", tags=["assets"])


@router.get("", response_model=list[AssetOut])
async def list_assets(session: AsyncSession = Depends(get_db_session)) -> list[AssetOut]:
    """Read-only listing of active assets (Phase 9): lets the frontend's
    Watchlist "add asset" picker resolve a symbol to an asset id, without
    duplicating the Portfolio Engine's own asset query."""
    return await list_active_assets(session)
