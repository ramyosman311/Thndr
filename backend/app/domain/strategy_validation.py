"""Pure strategy configuration validation.

No I/O. Validates allocation_targets rows already loaded from the
database — this module never asserts a fake target for a maximum-only
bucket, never silently corrects an invalid configuration, and never
reads a bucket/asset name to special-case behavior (see
FINANCIAL_RULES.md, "Allocation Target Validation" and "Database Is the
Source of Truth").

CRITICAL RULE (see FINANCIAL_RULES.md, "Target Allocation vs. Maximum
Allocation vs. Allow New Buy"): only `target_percent` ever contributes to
the aggregate target sum. `minimum_percent`, `maximum_percent`, and
`allow_new_buy` never do — enforced structurally here (the aggregation
step only ever reads `target_percent` off each rule), not just by
convention. A bucket with `target_percent=None` and only a
`maximum_percent` configured (e.g. "Individual Stocks") contributes
nothing to the sum; its maximum is never treated as an implied target.

This engine only ever REPORTS a validation status. It never changes a
percentage, never invents a missing target, and never normalizes an
incomplete or overallocated configuration to 100% — see the Phase 6
approval, "No Auto-Correction".
"""

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from uuid import UUID

# The mathematical target every active, risk-participating bucket's
# target_percent values must sum to. This is a structural invariant of
# "percentages sum to 100", not a business-specific number like an
# asset's target — it is never read from the database because it can't
# be anything other than 100.
TARGET_ALLOCATION_TOTAL = Decimal("100")

# Tolerance for treating an aggregate sum as "exactly" 100% despite
# harmless Decimal noise (e.g. three rules at 33.33 + 33.33 + 33.34). A
# computational comparison detail of this module, not a business rule.
TARGET_SUM_TOLERANCE = Decimal("0.01")


class StrategyValidationStatus(str, Enum):
    VALID = "VALID"
    INCOMPLETE_TARGET_ALLOCATION = "INCOMPLETE_TARGET_ALLOCATION"
    OVERALLOCATED_TARGET_ALLOCATION = "OVERALLOCATED_TARGET_ALLOCATION"
    EMPTY_CONFIGURATION = "EMPTY_CONFIGURATION"
    INVALID_TARGET_VALUE = "INVALID_TARGET_VALUE"
    INVALID_MIN_MAX_CONFIGURATION = "INVALID_MIN_MAX_CONFIGURATION"


@dataclass(frozen=True)
class AllocationRuleInput:
    """One active allocation_targets row, joined with the one fact the
    engine needs from portfolio_configs: whether this bucket holds the
    configured emergency asset and is therefore excluded (never inferred
    from the bucket's name)."""

    strategy_bucket_id: UUID
    bucket_name: str
    target_percent: Decimal | None
    minimum_percent: Decimal | None
    maximum_percent: Decimal | None
    allow_new_buy: bool
    priority: int
    is_emergency_excluded: bool = False


@dataclass(frozen=True)
class RuleFieldError:
    strategy_bucket_id: UUID
    bucket_name: str
    message: str


@dataclass(frozen=True)
class StrategyValidationResult:
    status: StrategyValidationStatus
    is_valid: bool
    total_target_percent: Decimal
    expected_target_percent: Decimal
    explanation: str
    target_rows: tuple[AllocationRuleInput, ...]
    maximum_only_rows: tuple[AllocationRuleInput, ...]
    excluded_emergency_rows: tuple[AllocationRuleInput, ...]
    field_errors: tuple[RuleFieldError, ...]
    priority_order: tuple[AllocationRuleInput, ...]


def _validate_rule_fields(rule: AllocationRuleInput) -> list[RuleFieldError]:
    errors: list[RuleFieldError] = []
    for field_name, value in (
        ("target_percent", rule.target_percent),
        ("minimum_percent", rule.minimum_percent),
        ("maximum_percent", rule.maximum_percent),
    ):
        if value is not None and (value < 0 or value > 100):
            errors.append(
                RuleFieldError(
                    rule.strategy_bucket_id,
                    rule.bucket_name,
                    f"{field_name} must be between 0 and 100, got {value}",
                )
            )
    if (
        rule.minimum_percent is not None
        and rule.maximum_percent is not None
        and rule.minimum_percent > rule.maximum_percent
    ):
        errors.append(
            RuleFieldError(
                rule.strategy_bucket_id,
                rule.bucket_name,
                f"minimum_percent ({rule.minimum_percent}) must not exceed maximum_percent ({rule.maximum_percent})",
            )
        )
    return errors


def validate_strategy(rules: list[AllocationRuleInput]) -> StrategyValidationResult:
    """Validate the full set of active allocation rules for a portfolio.

    Callers pass only *active* rules (inactive rules must already be
    filtered out before calling this — this module has no notion of
    "active" itself, it only aggregates what it is given) and must mark
    `is_emergency_excluded=True` on the rule for whichever bucket holds
    the configured emergency asset, when `portfolio_configs.emergency_
    excluded` is true.
    """
    participating = [r for r in rules if not r.is_emergency_excluded]
    excluded_emergency_rows = tuple(r for r in rules if r.is_emergency_excluded)

    field_errors: list[RuleFieldError] = []
    for rule in participating:
        field_errors.extend(_validate_rule_fields(rule))

    target_rows = tuple(r for r in participating if r.target_percent is not None)
    maximum_only_rows = tuple(r for r in participating if r.target_percent is None)
    priority_order = tuple(sorted(participating, key=lambda r: r.priority))

    # Only target_percent is summed — minimum_percent, maximum_percent,
    # and allow_new_buy are never read here.
    total_target_percent = sum((r.target_percent for r in target_rows), Decimal("0"))

    if field_errors:
        # A structurally invalid rule takes priority over the aggregate
        # diagnosis — fix the rule itself first.
        has_min_max_error = any(
            "minimum_percent" in e.message and "maximum_percent" in e.message for e in field_errors
        )
        status = (
            StrategyValidationStatus.INVALID_MIN_MAX_CONFIGURATION
            if has_min_max_error
            else StrategyValidationStatus.INVALID_TARGET_VALUE
        )
        explanation = "; ".join(e.message for e in field_errors)
    elif not participating:
        status = StrategyValidationStatus.EMPTY_CONFIGURATION
        explanation = "No active, risk-participating allocation rules are configured."
    elif abs(total_target_percent - TARGET_ALLOCATION_TOTAL) <= TARGET_SUM_TOLERANCE:
        status = StrategyValidationStatus.VALID
        explanation = f"Configured target allocation totals {total_target_percent}%, matching the expected 100%."
    elif total_target_percent < TARGET_ALLOCATION_TOTAL:
        status = StrategyValidationStatus.INCOMPLETE_TARGET_ALLOCATION
        explanation = (
            f"Configured target allocation totals {total_target_percent}%, which is below the expected 100%. "
            "This reflects the database's configured strategy and is not automatically corrected."
        )
    else:
        status = StrategyValidationStatus.OVERALLOCATED_TARGET_ALLOCATION
        explanation = (
            f"Configured target allocation totals {total_target_percent}%, which exceeds the expected 100%."
        )

    return StrategyValidationResult(
        status=status,
        is_valid=status == StrategyValidationStatus.VALID,
        total_target_percent=total_target_percent,
        expected_target_percent=TARGET_ALLOCATION_TOTAL,
        explanation=explanation,
        target_rows=target_rows,
        maximum_only_rows=maximum_only_rows,
        excluded_emergency_rows=excluded_emergency_rows,
        field_errors=tuple(field_errors),
        priority_order=priority_order,
    )
