"""API response schema for the read-only Assets listing endpoint.

Phase 9 addition: the frontend's Watchlist "add asset" picker needs a way
to look up an asset's id by symbol — no calculation, purely a listing of
existing `assets` rows.
"""

from uuid import UUID

from pydantic import BaseModel


class AssetOut(BaseModel):
    id: UUID
    symbol: str
    name: str
    asset_type: str
    currency: str
    is_active: bool
