"""API response schema for the Strategy Engine's validation endpoint.

See app/domain/strategy_validation.py for the semantics this mirrors.
"""

from uuid import UUID

from pydantic import BaseModel

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
