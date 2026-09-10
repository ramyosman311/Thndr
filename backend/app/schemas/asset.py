"""API request/response schemas for Asset administration (Phase 12) and
the read-only Assets listing endpoint (Phase 9).

Phase 9: the frontend's Watchlist "add asset" picker needs a way to look
up an asset's id by symbol — no calculation, purely a listing of
existing `assets` rows. Phase 12 adds create/edit/activate/deactivate/
delete around the same `assets` table -- no new columns were needed.
"""

from uuid import UUID

from pydantic import BaseModel, field_validator

from app.models.enums import AssetType


class AssetOut(BaseModel):
    id: UUID
    symbol: str
    name: str
    asset_type: str
    market: str | None
    currency: str
    strategy_bucket_id: UUID | None
    is_active: bool


class AssetCreateRequest(BaseModel):
    symbol: str
    name: str
    asset_type: AssetType
    market: str | None = None
    currency: str
    strategy_bucket_id: UUID | None = None

    @field_validator("symbol")
    @classmethod
    def symbol_must_not_be_blank(cls, value: str) -> str:
        value = value.strip().upper()
        if not value:
            raise ValueError("symbol must not be blank")
        return value

    @field_validator("name")
    @classmethod
    def name_must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("name must not be blank")
        return value

    @field_validator("currency")
    @classmethod
    def currency_must_be_a_plausible_code(cls, value: str) -> str:
        value = value.strip().upper()
        if not (2 <= len(value) <= 8) or not value.isalpha():
            raise ValueError("currency must be a 2-8 letter code, e.g. EGP, USD")
        return value


class AssetUpdateRequest(BaseModel):
    """All fields optional -- only the ones provided are changed. `currency`
    is accepted here but the service layer rejects the change outright
    once the asset has any transaction or price observation on record
    (see FINANCIAL_RULES.md, "Asset Edit Safety")."""

    name: str | None = None
    asset_type: AssetType | None = None
    market: str | None = None
    currency: str | None = None
    strategy_bucket_id: UUID | None = None
    clear_strategy_bucket: bool = False

    @field_validator("name")
    @classmethod
    def name_must_not_be_blank(cls, value: str | None) -> str | None:
        if value is None:
            return value
        value = value.strip()
        if not value:
            raise ValueError("name must not be blank")
        return value

    @field_validator("currency")
    @classmethod
    def currency_must_be_a_plausible_code(cls, value: str | None) -> str | None:
        if value is None:
            return value
        value = value.strip().upper()
        if not (2 <= len(value) <= 8) or not value.isalpha():
            raise ValueError("currency must be a 2-8 letter code, e.g. EGP, USD")
        return value
