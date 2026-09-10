"""API schemas for the Strategy Engine's validation endpoint (Phase 6)
and Strategy Bucket / Allocation Target administration (Phase 12).

See app/domain/strategy_validation.py for the validation semantics
these mirror. Administration writes here never duplicate that domain
validation -- see FINANCIAL_RULES.md, "Strategy Validation Ownership":
an individual bucket/target row's own field-level constraints (percent
ranges, minimum <= maximum) are enforced on write, but the AGGREGATE
question of whether the whole strategy sums to 100% remains exclusively
`GET /api/portfolio/strategy/validation`'s to answer -- writing one
target never blocks on, or silently fixes, that aggregate state.
"""

from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, field_validator, model_validator

from app.schemas.portfolio import DecimalStr


class AllocationRuleOut(BaseModel):
    strategy_bucket_id: UUID
    bucket_name: str
    target_percent: DecimalStr | None
    minimum_percent: DecimalStr | None
    maximum_percent: DecimalStr | None
    allow_new_buy: bool
    priority: int


class RuleFieldErrorOut(BaseModel):
    strategy_bucket_id: UUID
    bucket_name: str
    message: str


class StrategyValidationOut(BaseModel):
    status: str
    is_valid: bool
    total_target_percent: DecimalStr
    expected_target_percent: DecimalStr
    explanation: str
    target_rows: list[AllocationRuleOut]
    maximum_only_rows: list[AllocationRuleOut]
    excluded_emergency_rows: list[AllocationRuleOut]
    field_errors: list[RuleFieldErrorOut]
    priority_order: list[AllocationRuleOut]


# --- Strategy Bucket administration (Phase 12) --------------------------


class StrategyBucketOut(BaseModel):
    id: UUID
    portfolio_config_id: UUID
    name: str
    description: str | None
    is_active: bool


class StrategyBucketCreateRequest(BaseModel):
    name: str
    description: str | None = None

    @field_validator("name")
    @classmethod
    def name_must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("name must not be blank")
        return value


class StrategyBucketUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None

    @field_validator("name")
    @classmethod
    def name_must_not_be_blank(cls, value: str | None) -> str | None:
        if value is None:
            return value
        value = value.strip()
        if not value:
            raise ValueError("name must not be blank")
        return value


# --- Allocation Target administration (Phase 12) ------------------------


def _validate_percent_range(value: Decimal | None, field_name: str) -> Decimal | None:
    if value is not None and not (Decimal("0") <= value <= Decimal("100")):
        raise ValueError(f"{field_name} must be between 0 and 100")
    return value


class AllocationTargetOut(BaseModel):
    id: UUID
    portfolio_config_id: UUID
    strategy_bucket_id: UUID
    target_percent: DecimalStr | None
    minimum_percent: DecimalStr | None
    maximum_percent: DecimalStr | None
    allow_new_buy: bool
    priority: int
    is_active: bool


class AllocationTargetCreateRequest(BaseModel):
    strategy_bucket_id: UUID
    target_percent: DecimalStr | None = None
    minimum_percent: DecimalStr | None = None
    maximum_percent: DecimalStr | None = None
    allow_new_buy: bool = True
    priority: int = 0

    @field_validator("target_percent")
    @classmethod
    def target_percent_range(cls, value: Decimal | None) -> Decimal | None:
        return _validate_percent_range(value, "target_percent")

    @field_validator("minimum_percent")
    @classmethod
    def minimum_percent_range(cls, value: Decimal | None) -> Decimal | None:
        return _validate_percent_range(value, "minimum_percent")

    @field_validator("maximum_percent")
    @classmethod
    def maximum_percent_range(cls, value: Decimal | None) -> Decimal | None:
        return _validate_percent_range(value, "maximum_percent")

    @model_validator(mode="after")
    def minimum_must_not_exceed_maximum(self) -> "AllocationTargetCreateRequest":
        if self.minimum_percent is not None and self.maximum_percent is not None:
            if self.minimum_percent > self.maximum_percent:
                raise ValueError("minimum_percent must not exceed maximum_percent")
        return self


class AllocationTargetUpdateRequest(BaseModel):
    """All fields optional -- only the ones provided are changed. Field-
    level range/min-max validation runs only across the values actually
    provided together in this request; the service layer re-checks the
    resulting row against the full min<=max rule using whatever wasn't
    changed (the DB CHECK constraint is the final backstop either way)."""

    target_percent: DecimalStr | None = None
    clear_target_percent: bool = False
    minimum_percent: DecimalStr | None = None
    clear_minimum_percent: bool = False
    maximum_percent: DecimalStr | None = None
    clear_maximum_percent: bool = False
    allow_new_buy: bool | None = None
    priority: int | None = None
    is_active: bool | None = None

    @field_validator("target_percent")
    @classmethod
    def target_percent_range(cls, value: Decimal | None) -> Decimal | None:
        return _validate_percent_range(value, "target_percent")

    @field_validator("minimum_percent")
    @classmethod
    def minimum_percent_range(cls, value: Decimal | None) -> Decimal | None:
        return _validate_percent_range(value, "minimum_percent")

    @field_validator("maximum_percent")
    @classmethod
    def maximum_percent_range(cls, value: Decimal | None) -> Decimal | None:
        return _validate_percent_range(value, "maximum_percent")
