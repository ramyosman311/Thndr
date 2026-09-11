"""Orchestrates the Smart Rebalancing Engine (Phase 17): loads current
portfolio state via the repository layer, runs the Allocation Engine
(Phase 5/6) to get each category's target/maximum status, runs the pure
`domain/rebalancing_engine.calculate_rebalancing` (which itself reuses
the Smart Inflow Allocator for BUY distribution), and assembles the
API-ready schema.

Read-only — this module never writes to holdings, transactions,
allocation_targets, strategy_buckets, portfolio_configs, or cash (see
FINANCIAL_RULES.md, "Rebalancing Engine Rules"). Recommendation only;
no execution, ever.

Rounding: domain calculations stay at full Decimal precision throughout;
presentation rounding happens only here, same convention as
portfolio_service.py/inflow_service.py.
"""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.allocation_engine import evaluate_bucket_allocation
from app.domain.portfolio_engine import calculate_portfolio_totals
from app.domain.rebalancing_engine import RebalancingCandidate, RebalancingResult, calculate_rebalancing
from app.repositories.portfolio_repository import (
    get_active_allocation_targets,
    get_active_assets,
    get_active_strategy_buckets,
    get_portfolio_config,
)
from app.schemas.rebalancing import RebalancingOut, RebalancingRecommendationOut
from app.services.portfolio_shared import find_emergency_bucket_id, load_priced_positions

_PRESENTATION_QUANT = Decimal("0.01")


class RebalancingNotConfiguredError(Exception):
    """Raised when no portfolio_configs row exists yet. Named distinctly
    from portfolio_service.py's/inflow_service.py's own identically-
    purposed exception (rather than reusing that same name, this
    codebase's established per-service convention) only because
    api/routes/portfolio.py needs to import and catch both in the same
    module."""


def _round(value: Decimal) -> Decimal:
    return value.quantize(_PRESENTATION_QUANT, rounding=ROUND_HALF_UP)


def _round_or_none(value: Decimal | None) -> Decimal | None:
    return None if value is None else _round(value)


@dataclass(frozen=True)
class LoadedRebalancingResult:
    """The raw, full-precision domain output plus the one piece of
    portfolio-level context (`is_complete`) a caller needs alongside it —
    returned as-is, before any presentation rounding."""

    result: RebalancingResult
    is_complete: bool


async def load_rebalancing_result(session: AsyncSession) -> LoadedRebalancingResult:
    """Fetches current portfolio/strategy/allocation state and runs the
    pure `domain/rebalancing_engine.calculate_rebalancing` — the single
    place this happens. Extracted out of `get_rebalancing_recommendations`
    (Phase 17) so Phase 18's Smart Recommendations engine can reuse the
    exact same DB-fetch/candidate-building/calculation path instead of
    duplicating it (see FINANCIAL_RULES.md, "Rebalancing Is The Single
    Source Of Truth" — recommendations must consume Phase 17's numbers,
    never recompute them)."""
    config = await get_portfolio_config(session)
    if config is None:
        raise RebalancingNotConfiguredError("No portfolio configuration exists yet.")

    assets = await get_active_assets(session)
    positions = await load_priced_positions(session, assets, config.emergency_asset_id, config.base_currency)
    totals = calculate_portfolio_totals(positions, emergency_excluded=config.emergency_excluded)

    buckets = await get_active_strategy_buckets(session, config.id)
    targets = await get_active_allocation_targets(session, config.id)
    target_by_bucket_id = {target.strategy_bucket_id: target for target in targets}
    emergency_bucket_id = find_emergency_bucket_id(assets, config.emergency_asset_id)

    candidates: list[RebalancingCandidate] = []
    for bucket in buckets:
        target = target_by_bucket_id.get(bucket.id)
        excluded_from_risk = config.emergency_excluded and bucket.id == emergency_bucket_id
        allocation = evaluate_bucket_allocation(
            strategy_bucket_id=bucket.id,
            bucket_name=bucket.name,
            positions=positions,
            total_value=totals.total_value,
            risk_denominator_value=totals.denominator_value,
            excluded_from_risk_allocation=excluded_from_risk,
            target_percent=target.target_percent if target else None,
            minimum_percent=target.minimum_percent if target else None,
            maximum_percent=target.maximum_percent if target else None,
            allow_new_buy=target.allow_new_buy if target else None,
        )
        candidates.append(
            RebalancingCandidate(
                strategy_bucket_id=allocation.strategy_bucket_id,
                bucket_name=allocation.bucket_name,
                actual_value=allocation.actual_value,
                risk_allocation_percent=allocation.risk_allocation_percent,
                target_percent=allocation.target_percent,
                maximum_percent=allocation.maximum_percent,
                allow_new_buy=allocation.allow_new_buy,
                priority=target.priority if target else 0,
                is_emergency_excluded=excluded_from_risk,
                target_status=allocation.target_status,
                maximum_status=allocation.maximum_status,
            )
        )

    # Investable Cash (Phase 16) is the ONLY source of ordinary BUY
    # funding here — never invested_market_value, never total_value (see
    # FINANCIAL_RULES.md, "Portfolio Value vs Investable Value vs
    # Available Cash"). Reserved/emergency cash is excluded from
    # `available_cash` by construction (a CASH/SAVINGS holding that IS
    # the configured emergency asset counts toward `emergency_value`
    # instead), so it can never be consumed here.
    result = calculate_rebalancing(
        candidates=candidates,
        available_cash=totals.available_cash,
        investable_portfolio_value=totals.denominator_value,
    )

    return LoadedRebalancingResult(result=result, is_complete=totals.is_complete)


async def get_rebalancing_recommendations(session: AsyncSession) -> RebalancingOut:
    loaded = await load_rebalancing_result(session)
    result = loaded.result

    recommendation_outs = [
        RebalancingRecommendationOut(
            strategy_bucket_id=r.strategy_bucket_id,
            bucket_name=r.bucket_name,
            actual_value=_round(r.actual_value),
            current_percent=_round_or_none(r.current_percent),
            target_percent=r.target_percent,
            maximum_percent=r.maximum_percent,
            difference_percent=_round_or_none(r.difference_percent),
            target_value=_round_or_none(r.target_value),
            difference_value=_round_or_none(r.difference_value),
            action=r.action.value,
            recommended_value=_round_or_none(r.recommended_value),
            priority=r.priority,
            allow_new_buy=r.allow_new_buy,
            status=r.status,
            reason=r.reason,
        )
        for r in result.recommendations
    ]

    return RebalancingOut(
        available_cash=_round(result.available_cash),
        total_recommended_buy=_round(result.total_recommended_buy),
        total_recommended_reduce=_round(result.total_recommended_reduce),
        is_complete=loaded.is_complete,
        recommendations=recommendation_outs,
    )
