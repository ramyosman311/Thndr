"""API request/response schemas for the Watchlist feature."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.schemas.alert import AlertRuleOut


class WatchlistAddRequest(BaseModel):
    asset_id: UUID
    notes: str | None = None


class WatchlistUpdateRequest(BaseModel):
    enabled: bool | None = None
    notes: str | None = None


class WatchlistOut(BaseModel):
    id: UUID
    asset_id: UUID
    asset_symbol: str
    enabled: bool
    notes: str | None
    added_at: datetime
    removed_at: datetime | None
    alert_rule: AlertRuleOut | None
