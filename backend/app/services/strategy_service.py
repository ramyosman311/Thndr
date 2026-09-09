"""Orchestrates the Strategy Engine: loads active configuration via the
repository layer, runs pure domain validation, and assembles the
API-ready schema.

Read-only — never writes to allocation_targets, strategy_buckets, or
portfolio_configs. Reuses the same repository queries as the Portfolio
Engine (Phase 5) rather than duplicating them in a separate
strategy_repository module, since the data needed — portfolio config,
active buckets, active allocation targets, active assets (to resolve the
emergency bucket) — is identical.
"""

from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.strategy_validation import AllocationRuleInput, validate_strategy
from app.repositories.portfolio_repository import (
    get_active_allocation_targets,
    get_active_assets,
    get_active_strategy_buckets,
    get_portfolio_config,
)
from app.schemas.strategy import AllocationRuleOut, RuleFieldErrorOut, StrategyValidationOut
from app.services.portfolio_shared import find_emergency_bucket_id

_PRESENTATION_QUANT = Decimal("0.01")


class PortfolioNotConfiguredError(Exception):
    """Raised when no portfolio_configs row exists yet."""


def _round(value: Decimal) -> Decimal:
    return value.quantize(_PRESENTATION_QUANT, rounding=ROUND_HALF_UP)


def _rule_to_out(rule: AllocationRuleInput) -> AllocationRuleOut:
    return AllocationRuleOut(
        strategy_bucket_id=rule.strategy_bucket_id,
        bucket_name=rule.bucket_name,
        target_percent=rule.target_percent,
        minimum_percent=rule.minimum_percent,
        maximum_percent=rule.maximum_percent,
        allow_new_buy=rule.allow_new_buy,
        priority=rule.priority,
    )


async def get_strategy_validation(session: AsyncSession) -> StrategyValidationOut:
    config = await get_portfolio_config(session)
    if config is None:
        raise PortfolioNotConfiguredError("No portfolio configuration exists yet.")

    buckets = await get_active_strategy_buckets(session, config.id)
    targets = await get_active_allocation_targets(session, config.id)
    assets = await get_active_assets(session)

    target_by_bucket_id = {target.strategy_bucket_id: target for target in targets}
    emergency_bucket_id = find_emergency_bucket_id(assets, config.emergency_asset_id)

    rules: list[AllocationRuleInput] = []
    for bucket in buckets:
        target = target_by_bucket_id.get(bucket.id)
        if target is None:
            # A bucket with no allocation rule at all has nothing to
            # validate (e.g. "Emergency Cash" in the seeded configuration,
            # which intentionally has no allocation_targets row).
            continue
        is_emergency_excluded = config.emergency_excluded and bucket.id == emergency_bucket_id
        rules.append(
            AllocationRuleInput(
                strategy_bucket_id=bucket.id,
                bucket_name=bucket.name,
                target_percent=target.target_percent,
                minimum_percent=target.minimum_percent,
                maximum_percent=target.maximum_percent,
                allow_new_buy=target.allow_new_buy,
                priority=target.priority,
                is_emergency_excluded=is_emergency_excluded,
            )
        )

    result = validate_strategy(rules)

    return StrategyValidationOut(
        status=result.status.value,
        is_valid=result.is_valid,
        total_target_percent=_round(result.total_target_percent),
        expected_target_percent=_round(result.expected_target_percent),
        explanation=result.explanation,
        target_rows=[_rule_to_out(r) for r in result.target_rows],
        maximum_only_rows=[_rule_to_out(r) for r in result.maximum_only_rows],
        excluded_emergency_rows=[_rule_to_out(r) for r in result.excluded_emergency_rows],
        field_errors=[
            RuleFieldErrorOut(
                strategy_bucket_id=e.strategy_bucket_id, bucket_name=e.bucket_name, message=e.message
            )
            for e in result.field_errors
        ],
        priority_order=[_rule_to_out(r) for r in result.priority_order],
    )
