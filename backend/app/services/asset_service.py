"""Read-only Assets listing (Phase 9): reuses the same repository query
the Portfolio Engine already uses — never a separate/duplicated query.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.portfolio_repository import get_active_assets
from app.schemas.asset import AssetOut


async def list_active_assets(session: AsyncSession) -> list[AssetOut]:
    assets = await get_active_assets(session)
    return [
        AssetOut(
            id=asset.id,
            symbol=asset.symbol,
            name=asset.name,
            asset_type=asset.asset_type.value,
            currency=asset.currency,
            is_active=asset.is_active,
        )
        for asset in assets
    ]
