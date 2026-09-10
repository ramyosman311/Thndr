"""Small helpers shared by the Portfolio, Strategy, and Smart Inflow
services, so the emergency-bucket lookup and position-building logic
exist in exactly one place (see Phase 7 approval, "Reuse Existing
Engines" — refactored here rather than left duplicated across
portfolio_service.py and strategy_service.py, and rather than adding a
third copy for the inflow service).

Phase 11: this is also the one place `holdings.current_price` would
have been read — it no longer is. Every position's price now comes from
services/price_service.py (the single price read path for the whole
system), already converted into the portfolio's base currency, so
`domain/portfolio_engine.py`'s pure math never has to know about
currencies or providers at all (see FINANCIAL_RULES.md, "Single Source
Of Truth For Current Price").
"""

from decimal import Decimal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.portfolio_engine import AssetPosition
from app.domain.price_types import PriceResult
from app.models import Asset
from app.services import price_service


def find_emergency_bucket_id(assets: list[Asset], emergency_asset_id: UUID | None) -> UUID | None:
    """Which strategy bucket (if any) holds the configured emergency asset
    — determined purely from configuration relationships (portfolio_configs
    -> assets -> strategy_buckets), never from a bucket/asset name."""
    if emergency_asset_id is None:
        return None
    for asset in assets:
        if asset.id == emergency_asset_id:
            return asset.strategy_bucket_id
    return None


def build_positions(
    assets: list[Asset], emergency_asset_id: UUID | None, prices: dict[UUID, PriceResult]
) -> list[AssetPosition]:
    """Pure: assembles positions from already-resolved price results
    (each already converted into the portfolio's base currency by the
    caller — see `load_priced_positions` below). A missing/unusable
    entry in `prices` becomes `current_price=None`, never a fabricated
    zero (see domain/portfolio_engine.py, "Never Fabricate A Price")."""
    positions = []
    for asset in assets:
        holding = asset.holding
        quantity = holding.quantity if holding is not None else Decimal("0")
        price_result = prices.get(asset.id)
        current_price = price_result.price if price_result is not None and price_result.is_usable else None
        positions.append(
            AssetPosition(
                asset_id=asset.id,
                symbol=asset.symbol,
                is_emergency=emergency_asset_id is not None and asset.id == emergency_asset_id,
                strategy_bucket_id=asset.strategy_bucket_id,
                quantity=quantity,
                current_price=current_price,
            )
        )
    return positions


async def load_priced_positions(
    session: AsyncSession, assets: list[Asset], emergency_asset_id: UUID | None, base_currency: str
) -> list[AssetPosition]:
    """Fetches every asset's latest price (via the Price Service --
    never a live provider call, see FINANCIAL_RULES.md, "Non-Blocking
    Valuation") in one batch, converts into `base_currency`, and builds
    positions. This is the one call site every consumer of portfolio
    valuation (Dashboard, Allocation, Smart Inflow) should use, so they
    can never drift onto different pricing logic."""
    prices = await price_service.get_prices_for_assets_in_base_currency(session, assets, base_currency)
    return build_positions(assets, emergency_asset_id, prices)
