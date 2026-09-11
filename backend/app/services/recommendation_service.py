"""Orchestrates the Smart Recommendations engine (Phase 18): loads the
Smart Rebalancing Engine's (Phase 17) raw domain output via its own
loader -- never recomputing any rebalancing math here -- runs the pure
`domain/recommendation_engine.build_recommendations`, and assembles the
API-ready schema.

Read-only, same as rebalancing_service.py: never writes to holdings,
transactions, allocation_targets, strategy_buckets, portfolio_configs, or
cash. Recommendation only; no execution, ever.
"""

from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.recommendation_engine import build_recommendations
from app.schemas.recommendations import PortfolioRecommendationOut, RecommendationsOut
from app.services.rebalancing_service import RebalancingNotConfiguredError, load_rebalancing_result

_PRESENTATION_QUANT = Decimal("0.01")


def _round_or_none(value: Decimal | None) -> Decimal | None:
    return None if value is None else value.quantize(_PRESENTATION_QUANT, rounding=ROUND_HALF_UP)


async def get_portfolio_recommendations(
    session: AsyncSession, *, evaluated_at: datetime | None = None
) -> RecommendationsOut:
    """`RebalancingNotConfiguredError` (imported from rebalancing_service
    rather than redefined here) propagates unchanged -- a portfolio with
    no configuration yet has no recommendations to compute, same as it
    has no rebalancing to compute."""
    loaded = await load_rebalancing_result(session)
    evaluated_at = evaluated_at or datetime.now(timezone.utc)

    recommendations = build_recommendations(loaded.result, evaluated_at=evaluated_at)

    recommendation_outs = [
        PortfolioRecommendationOut(
            id=r.id,
            type=r.type.value,
            severity=r.severity.value,
            title=r.title,
            message=r.message,
            suggested_action=r.suggested_action.value,
            target_category=r.target_category,
            amount=_round_or_none(r.amount),
            evaluated_at=r.evaluated_at,
        )
        for r in recommendations
    ]

    return RecommendationsOut(
        is_complete=loaded.is_complete,
        recommendations=recommendation_outs,
    )


__all__ = ["RebalancingNotConfiguredError", "get_portfolio_recommendations"]
