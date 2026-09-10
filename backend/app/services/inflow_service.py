"""Orchestrates the Smart Inflow Allocator: loads current portfolio state
via the repository layer, reuses the Strategy Engine's validation (rather
than duplicating the target-sum logic), runs the pure domain allocator,
and assembles the API-ready schema.

Read-only — never writes to holdings, transactions, allocation_targets,
strategy_buckets, or portfolio_configs (Phase 7 approval, "No Transaction
Side Effects"). This is a recommendation engine only: it never sells,
never executes a trade, and never modifies anything.

Rounding: domain calculations stay at full Decimal precision throughout.
Presentation rounding happens only here, and uses cumulative rounding
(not independent per-bucket rounding) for allocated amounts specifically,
so that sum(rounded allocated_amounts) always equals the rounded
allocated_cash exactly — independent rounding of each amount could drift
the total by a cent. See _round_allocated_amounts below.
"""

from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.allocation_engine import calculate_bucket_value
from app.domain.inflow_allocator import InflowCandidate, InflowRecommendation, calculate_inflow_allocation
from app.domain.portfolio_engine import calculate_portfolio_totals
from app.domain.strategy_validation import AllocationRuleInput, validate_strategy
from app.repositories.portfolio_repository import (
    get_active_allocation_targets,
    get_active_assets,
    get_active_strategy_buckets,
    get_portfolio_config,
)
from app.schemas.inflow import InflowAllocationOut, InflowRecommendationOut
from app.services import price_service
from app.services.portfolio_shared import build_positions, find_emergency_bucket_id

_PRESENTATION_QUANT = Decimal("0.01")


class PortfolioNotConfiguredError(Exception):
    """Raised when no portfolio_configs row exists yet."""


def _round(value: Decimal) -> Decimal:
    return value.quantize(_PRESENTATION_QUANT, rounding=ROUND_HALF_UP)


def _round_or_none(value: Decimal | None) -> Decimal | None:
    return None if value is None else _round(value)


def _round_allocated_amounts(recommendations: tuple[InflowRecommendation, ...]) -> dict:
    """Cumulative rounding over allocated amounts, in the same
    deterministic (priority, bucket_name) order the domain allocator used
    to hand out cash, so the rounded amounts sum to exactly the rounded
    allocated total — never more, never less, regardless of how rounding
    falls on any individual bucket."""
    allocated = sorted(
        (r for r in recommendations if r.allocated_amount > 0),
        key=lambda r: (r.priority, r.bucket_name),
    )
    rounded_by_bucket: dict = {}
    cumulative_exact = Decimal("0")
    cumulative_rounded = Decimal("0")
    for r in allocated:
        cumulative_exact += r.allocated_amount
        new_cumulative_rounded = _round(cumulative_exact)
        rounded_by_bucket[r.strategy_bucket_id] = new_cumulative_rounded - cumulative_rounded
        cumulative_rounded = new_cumulative_rounded
    return rounded_by_bucket


async def get_inflow_allocation(session: AsyncSession, amount: Decimal) -> InflowAllocationOut:
    if amount <= 0:
        raise ValueError("amount must be greater than 0")

    config = await get_portfolio_config(session)
    if config is None:
        raise PortfolioNotConfiguredError("No portfolio configuration exists yet.")

    assets = await get_active_assets(session)
    prices = await price_service.get_prices_for_assets_in_base_currency(session, assets, config.base_currency)
    positions = build_positions(assets, config.emergency_asset_id, prices)
    totals = calculate_portfolio_totals(positions, emergency_excluded=config.emergency_excluded)

    buckets = await get_active_strategy_buckets(session, config.id)
    targets = await get_active_allocation_targets(session, config.id)
    target_by_bucket_id = {target.strategy_bucket_id: target for target in targets}
    emergency_bucket_id = find_emergency_bucket_id(assets, config.emergency_asset_id)

    # Reuse the Strategy Engine's validation rather than duplicating the
    # target-sum logic (Phase 7 approval, "Reuse Existing Engines"). The
    # allocator still calculates allocations for eligible configured
    # targets even when the overall strategy is incomplete/overallocated
    # — it never invents a destination for a missing target.
    strategy_rules = []
    for bucket in buckets:
        target = target_by_bucket_id.get(bucket.id)
        if target is None:
            continue
        is_emergency_excluded = config.emergency_excluded and bucket.id == emergency_bucket_id
        strategy_rules.append(
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
    strategy_result = validate_strategy(strategy_rules)

    candidates = []
    for bucket in buckets:
        target = target_by_bucket_id.get(bucket.id)
        is_emergency_excluded = config.emergency_excluded and bucket.id == emergency_bucket_id
        current_value = calculate_bucket_value(positions, bucket.id)
        candidates.append(
            InflowCandidate(
                strategy_bucket_id=bucket.id,
                bucket_name=bucket.name,
                current_value=current_value,
                target_percent=target.target_percent if target else None,
                maximum_percent=target.maximum_percent if target else None,
                allow_new_buy=target.allow_new_buy if target else None,
                priority=target.priority if target else 0,
                is_emergency_excluded=is_emergency_excluded,
            )
        )

    # Investable/risk value BEFORE the new cash arrives — never inflated
    # by the incoming amount before target gaps are computed (Phase 7
    # approval, "Critical Question: New Cash and Denominator").
    result = calculate_inflow_allocation(
        new_cash_amount=amount,
        investable_portfolio_value=totals.denominator_value,
        candidates=candidates,
    )

    rounded_allocated = _round_allocated_amounts(result.recommendations)
    requested_rounded = _round(result.requested_cash)
    allocated_rounded = _round(result.allocated_cash)
    # Derived, not independently rounded, so the visible invariant
    # requested == allocated + unallocated holds exactly at presentation
    # too (Phase 7 approval, "Rounding").
    unallocated_rounded = requested_rounded - allocated_rounded

    recommendation_outs = [
        InflowRecommendationOut(
            strategy_bucket_id=r.strategy_bucket_id,
            bucket_name=r.bucket_name,
            current_value=_round(r.current_value),
            current_percent=_round_or_none(r.current_percent),
            target_percent=r.target_percent,
            maximum_percent=r.maximum_percent,
            allow_new_buy=r.allow_new_buy,
            priority=r.priority,
            target_gap=_round_or_none(r.target_gap),
            maximum_capacity=_round_or_none(r.maximum_capacity),
            eligible=r.eligible,
            allocated_amount=rounded_allocated.get(r.strategy_bucket_id, Decimal("0")),
            status=r.status.value,
            projected_value=_round_or_none(r.projected_value),
            projected_percent=_round_or_none(r.projected_percent),
        )
        for r in result.recommendations
    ]

    return InflowAllocationOut(
        requested_cash=requested_rounded,
        allocated_cash=allocated_rounded,
        unallocated_cash=unallocated_rounded,
        strategy_status=strategy_result.status.value,
        strategy_is_valid=strategy_result.is_valid,
        is_complete=totals.is_complete,
        recommendations=recommendation_outs,
    )
