"""API request/response schemas for the Phase 11 price endpoints.

See app/domain/price_types.py for the PriceResult concept this mirrors,
and services/price_service.py for the read/write logic behind these
routes.
"""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, field_validator

from app.schemas.portfolio import DecimalStr


class PriceOut(BaseModel):
    """One asset's current price, as classified by the Price Service --
    never a live provider result (see FINANCIAL_RULES.md, "Non-Blocking
    Valuation"). `status` is one of CURRENT_PRICE_AVAILABLE,
    LAST_KNOWN_PRICE, or PRICE_UNAVAILABLE; `price`/`currency` are null
    exactly when `status` is PRICE_UNAVAILABLE."""

    asset_id: UUID
    status: str
    price: DecimalStr | None
    currency: str | None
    provider: str | None
    provider_symbol: str | None
    recorded_at: datetime | None
    age_seconds: float | None
    is_stale: bool
    reason: str | None


class PriceObservationOut(BaseModel):
    """One immutable row from `asset_prices` -- the full history, oldest
    fields never mutated (see DATABASE.md, "asset_prices")."""

    id: UUID
    price: DecimalStr
    currency: str
    provider: str
    source: str | None
    provider_symbol: str | None
    recorded_at: datetime
    is_manual: bool


class ManualPriceCreateRequest(BaseModel):
    price: DecimalStr
    currency: str

    @field_validator("price")
    @classmethod
    def price_must_be_positive(cls, value: Decimal) -> Decimal:
        if value <= 0:
            raise ValueError("price must be greater than 0")
        return value


class AssetPriceConfigOut(BaseModel):
    """Phase 12 administration view of `asset_price_configs`. `configured`
    is False (with every other field null/default) when the asset has no
    config row yet -- a normal, expected state (see FINANCIAL_RULES.md,
    "Unconfigured Providers Are Not Errors"), not an error condition."""

    asset_id: UUID
    configured: bool
    primary_provider: str | None
    primary_provider_symbol: str | None
    secondary_provider: str | None
    secondary_provider_symbol: str | None
    automated_fetching_enabled: bool
    manual_override_enabled: bool
    stale_threshold_minutes: int | None
    lock_manual: bool


class AssetPriceConfigUpsertRequest(BaseModel):
    """A full replacement of the asset's price configuration (PUT
    semantics) -- validated against the real provider registry, never
    against a hardcoded or asset-specific list (see FINANCIAL_RULES.md,
    "Provider Configuration Is Data, Not Code")."""

    primary_provider: str | None = None
    primary_provider_symbol: str | None = None
    secondary_provider: str | None = None
    secondary_provider_symbol: str | None = None
    automated_fetching_enabled: bool = False
    manual_override_enabled: bool = True
    stale_threshold_minutes: int | None = None
    lock_manual: bool = False

    @field_validator("stale_threshold_minutes")
    @classmethod
    def stale_threshold_must_be_positive(cls, value: int | None) -> int | None:
        if value is not None and value <= 0:
            raise ValueError("stale_threshold_minutes must be a positive number of minutes, or null")
        return value
