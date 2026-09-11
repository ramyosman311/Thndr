"""Pure Smart Recommendations Engine (Phase 18): interprets and presents
the Smart Rebalancing Engine's (Phase 17) already-computed per-category
recommendations as prioritized, Arabic, user-facing guidance answering
"what should I do with my portfolio today, and why?"

No I/O, and — critically — no rebalancing mathematics of its own. Every
BUY/REDUCE amount, every target/maximum/allow_new_buy/priority value,
and every category state (`TargetStatus`/`MaximumStatus` value) below is
read directly from a `domain.rebalancing_engine.RebalancingRecommendation`
— never recomputed (see FINANCIAL_RULES.md, "Rebalancing Is The Single
Source Of Truth"). This module's only job is classification into a
user-facing type/severity plus natural-language Arabic copy built from
those already-computed numbers.

Decision table (RebalancingAction -> RecommendationType), applied in the
order below so an emergency-protected category is never miscategorized
merely because it also happens to have no target configured:

- REDUCE                                          -> BREACH_RESOLUTION (always; a breached
                                                      category is never also considered
                                                      for a BUY -- see rebalancing_engine.py)
- is_emergency_excluded                           -> skipped (Emergency Cash must never
                                                      appear as something to act on; see
                                                      FINANCIAL_RULES.md, "Emergency Cash")
- NO_TARGET                                       -> skipped (constraint-only category --
                                                      "no target-driven action is recommended"
                                                      per Phase 17 itself; Free Cash falls
                                                      here when it has no target)
- BUY                                             -> CASH_DEPLOYMENT
- HOLD with status == TargetStatus.ON_TARGET.value -> skipped (nothing to report -- this is
                                                      exactly what "healthy" means for this
                                                      one category)
- HOLD with allow_new_buy is False                -> RESTRICTED_ACTION (below target, but new
                                                      buys are disabled -- never a false BUY)
- HOLD with status == TargetStatus.OVERWEIGHT.value -> REBALANCING_OPPORTUNITY (drifted above
                                                      target but still within the existing
                                                      maximum -- the existing tolerance
                                                      semantics already say this, nothing new
                                                      is invented here)
- NO_CAPACITY (either cause: structurally eligible
  but cash exhausted/self-capped, or the portfolio
  has no investable value yet)                    -> RESTRICTED_ACTION (informational --
                                                      underweight, but no fundable capacity;
                                                      never a false BUY)

If, after this pass, no BREACH_RESOLUTION / RESTRICTED_ACTION /
CASH_DEPLOYMENT / REBALANCING_OPPORTUNITY item exists, the portfolio is
genuinely healthy (no maximum breaches, no actionable drift, no blocked
opportunity) and a single PORTFOLIO_HEALTHY recommendation is returned
instead of an empty list.

This module never sells, never buys, never mutates anything, and never
executes a trade -- read-only guidance only.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum

from app.domain.allocation_engine import TargetStatus
from app.domain.rebalancing_engine import RebalancingAction, RebalancingRecommendation, RebalancingResult


class RecommendationType(str, Enum):
    """A single, unified vocabulary for what kind of guidance this is --
    deliberately not a second enum overlapping RebalancingAction, since
    the two answer different questions (RebalancingAction: what
    category-level action was computed; RecommendationType: how should
    the user-facing UI group/prioritize it)."""

    BREACH_RESOLUTION = "BREACH_RESOLUTION"
    CASH_DEPLOYMENT = "CASH_DEPLOYMENT"
    REBALANCING_OPPORTUNITY = "REBALANCING_OPPORTUNITY"
    RESTRICTED_ACTION = "RESTRICTED_ACTION"
    PORTFOLIO_HEALTHY = "PORTFOLIO_HEALTHY"


class RecommendationSeverity(str, Enum):
    CRITICAL = "CRITICAL"
    WARNING = "WARNING"
    INFO = "INFO"
    SUCCESS = "SUCCESS"


class SuggestedAction(str, Enum):
    BUY = "BUY"
    REDUCE = "REDUCE"
    HOLD = "HOLD"
    NO_ACTION = "NO_ACTION"


@dataclass(frozen=True)
class PortfolioRecommendation:
    # Deterministic -- f"{type.value}:{bucket_id or 'portfolio'}" -- never
    # a random UUID and never derived from `evaluated_at`, so identical
    # portfolio/strategy state always yields the identical id (see
    # "verify deterministic output", Phase 18 Test J).
    id: str
    type: RecommendationType
    severity: RecommendationSeverity
    title: str
    message: str
    suggested_action: SuggestedAction
    target_category: str | None
    # Present only when directly sourced from a Phase 17 recommended_value
    # (a REDUCE or BUY amount) -- never independently computed here.
    amount: Decimal | None
    evaluated_at: datetime


# Tier rank drives the primary sort key -- the deterministic priority
# order mandated by the spec: maximum breaches/critical risk first,
# then restricted/blocked opportunities, then fundable cash deployment,
# then rebalancing opportunities, then the healthy/informational state.
_TYPE_TIER: dict[RecommendationType, int] = {
    RecommendationType.BREACH_RESOLUTION: 0,
    RecommendationType.RESTRICTED_ACTION: 1,
    RecommendationType.CASH_DEPLOYMENT: 2,
    RecommendationType.REBALANCING_OPPORTUNITY: 3,
    RecommendationType.PORTFOLIO_HEALTHY: 4,
}


def _recommendation_id(rec_type: RecommendationType, bucket_id: object | None) -> str:
    return f"{rec_type.value}:{bucket_id if bucket_id is not None else 'portfolio'}"


def _breach_resolution(r: RebalancingRecommendation, evaluated_at: datetime) -> PortfolioRecommendation:
    amount = r.recommended_value if r.recommended_value is not None else Decimal("0")
    return PortfolioRecommendation(
        id=_recommendation_id(RecommendationType.BREACH_RESOLUTION, r.strategy_bucket_id),
        type=RecommendationType.BREACH_RESOLUTION,
        severity=RecommendationSeverity.CRITICAL,
        title=f"{r.bucket_name}: تجاوز الحد الأقصى المسموح به",
        message=(f"{r.bucket_name} تجاوزت الحد الأقصى المسموح به. يوصى بتقليل الاستثمار بحوالي {amount:.2f}."),
        suggested_action=SuggestedAction.REDUCE,
        target_category=r.bucket_name,
        amount=r.recommended_value,
        evaluated_at=evaluated_at,
    )


def _cash_deployment(r: RebalancingRecommendation, evaluated_at: datetime) -> PortfolioRecommendation:
    amount = r.recommended_value if r.recommended_value is not None else Decimal("0")
    return PortfolioRecommendation(
        id=_recommendation_id(RecommendationType.CASH_DEPLOYMENT, r.strategy_bucket_id),
        type=RecommendationType.CASH_DEPLOYMENT,
        severity=RecommendationSeverity.INFO,
        title=f"{r.bucket_name}: فرصة لنشر السيولة المتاحة",
        message=(
            f"{r.bucket_name} أقل من نسبتها المستهدفة. "
            f"يمكن استخدام حوالي {amount:.2f} من النقد المتاح لتقريبها من الهدف."
        ),
        suggested_action=SuggestedAction.BUY,
        target_category=r.bucket_name,
        amount=r.recommended_value,
        evaluated_at=evaluated_at,
    )


def _rebalancing_opportunity(r: RebalancingRecommendation, evaluated_at: datetime) -> PortfolioRecommendation:
    return PortfolioRecommendation(
        id=_recommendation_id(RecommendationType.REBALANCING_OPPORTUNITY, r.strategy_bucket_id),
        type=RecommendationType.REBALANCING_OPPORTUNITY,
        severity=RecommendationSeverity.INFO,
        title=f"{r.bucket_name}: أعلى من الهدف ضمن الحد المسموح",
        message=(
            f"{r.bucket_name} أعلى من نسبتها المستهدفة حاليًا، لكنها لا تزال ضمن الحد الأقصى المسموح به، "
            f"لذا لا يلزم إجراء فوري."
        ),
        suggested_action=SuggestedAction.HOLD,
        target_category=r.bucket_name,
        amount=None,
        evaluated_at=evaluated_at,
    )


def _restricted_allow_new_buy_disabled(r: RebalancingRecommendation, evaluated_at: datetime) -> PortfolioRecommendation:
    return PortfolioRecommendation(
        id=_recommendation_id(RecommendationType.RESTRICTED_ACTION, r.strategy_bucket_id),
        type=RecommendationType.RESTRICTED_ACTION,
        severity=RecommendationSeverity.WARNING,
        title=f"{r.bucket_name}: الشراء الجديد موقوف",
        message=(
            f"{r.bucket_name} أقل من نسبتها المستهدفة، لكن الشراء الجديد موقوف حاليًا لهذه الفئة، "
            f"لذا لا يُقترح شراء الآن."
        ),
        suggested_action=SuggestedAction.HOLD,
        target_category=r.bucket_name,
        amount=None,
        evaluated_at=evaluated_at,
    )


def _restricted_no_capacity(r: RebalancingRecommendation, evaluated_at: datetime) -> PortfolioRecommendation:
    return PortfolioRecommendation(
        id=_recommendation_id(RecommendationType.RESTRICTED_ACTION, r.strategy_bucket_id),
        type=RecommendationType.RESTRICTED_ACTION,
        severity=RecommendationSeverity.WARNING,
        title=f"{r.bucket_name}: لا توجد سيولة كافية",
        message=(f"{r.bucket_name} أقل من نسبتها المستهدفة، لكن لا يوجد حاليًا نقد متاح كافٍ لتمويل الشراء."),
        suggested_action=SuggestedAction.HOLD,
        target_category=r.bucket_name,
        amount=None,
        evaluated_at=evaluated_at,
    )


def _portfolio_healthy(evaluated_at: datetime) -> PortfolioRecommendation:
    return PortfolioRecommendation(
        id=_recommendation_id(RecommendationType.PORTFOLIO_HEALTHY, None),
        type=RecommendationType.PORTFOLIO_HEALTHY,
        severity=RecommendationSeverity.SUCCESS,
        title="المحفظة ضمن الحدود المستهدفة",
        message=(
            "المحفظة ضمن نسب التخصيص المحددة. لا يوجد تجاوز للحد الأقصى في أي فئة. "
            "لا حاجة لإجراء إعادة توازن فوري."
        ),
        suggested_action=SuggestedAction.NO_ACTION,
        target_category=None,
        amount=None,
        evaluated_at=evaluated_at,
    )


def _one_recommendation(r: RebalancingRecommendation, evaluated_at: datetime) -> PortfolioRecommendation | None:
    if r.action == RebalancingAction.REDUCE:
        return _breach_resolution(r, evaluated_at)

    # Emergency protection and "no target configured" both mean "no
    # target-driven action is recommended" -- checked before every other
    # HOLD/NO_CAPACITY branch so neither is ever miscategorized as a
    # restricted opportunity (see module docstring).
    if r.is_emergency_excluded:
        return None
    if r.action == RebalancingAction.NO_TARGET:
        return None

    if r.action == RebalancingAction.BUY:
        return _cash_deployment(r, evaluated_at)

    if r.action == RebalancingAction.HOLD:
        if r.status == TargetStatus.ON_TARGET.value:
            return None
        if r.allow_new_buy is False:
            return _restricted_allow_new_buy_disabled(r, evaluated_at)
        if r.status == TargetStatus.OVERWEIGHT.value:
            return _rebalancing_opportunity(r, evaluated_at)
        # Any other HOLD (defensively -- not reached by the current
        # rebalancing_engine.py decision table) carries no actionable
        # signal worth surfacing.
        return None

    if r.action == RebalancingAction.NO_CAPACITY:
        return _restricted_no_capacity(r, evaluated_at)

    return None


def build_recommendations(
    rebalancing_result: RebalancingResult,
    *,
    evaluated_at: datetime,
) -> list[PortfolioRecommendation]:
    """Pure, deterministic mapping from Phase 17's raw output to
    prioritized, Arabic, user-facing recommendations. Never recomputes a
    BUY/REDUCE amount, a target/maximum percent, or a category status --
    every number/state here is read verbatim from `rebalancing_result`.
    """
    items = [
        rec
        for rec in (_one_recommendation(r, evaluated_at) for r in rebalancing_result.recommendations)
        if rec is not None
    ]

    if not items:
        return [_portfolio_healthy(evaluated_at)]

    priority_by_bucket_name = {r.bucket_name: r.priority for r in rebalancing_result.recommendations}
    items.sort(
        key=lambda item: (
            _TYPE_TIER[item.type],
            priority_by_bucket_name.get(item.target_category, 0),
            item.target_category or "",
        )
    )
    return items
