"""Small helpers shared by the Portfolio, Strategy, and Smart Inflow
services, so the emergency-bucket lookup and position-building logic
exist in exactly one place (see Phase 7 approval, "Reuse Existing
Engines" — refactored here rather than left duplicated across
portfolio_service.py and strategy_service.py, and rather than adding a
third copy for the inflow service).
"""

from decimal import Decimal
from uuid import UUID

from app.domain.portfolio_engine import AssetPosition
from app.models import Asset


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


def build_positions(assets: list[Asset], emergency_asset_id: UUID | None) -> list[AssetPosition]:
    positions = []
    for asset in assets:
        holding = asset.holding
        quantity = holding.quantity if holding is not None else Decimal("0")
        current_price = holding.current_price if holding is not None else Decimal("0")
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
