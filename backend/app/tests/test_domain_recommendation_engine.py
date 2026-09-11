"""Phase 18: Smart Recommendations Engine — pure domain tests, mirroring
scenario letters A-I from the approved spec. Test J (no mutation +
deterministic repeated request against the real HTTP endpoint) is an
integration-level test — see test_recommendation_service.py.

Recommendations are built by feeding REAL `domain.rebalancing_engine.
calculate_rebalancing` output (via the same `make_candidate` pattern as
test_domain_rebalancing_engine.py) into `build_recommendations`, never by
hand-constructing a RebalancingRecommendation — these tests must exercise
the exact same Phase 17 numbers Phase 18 is required to reuse verbatim.
"""

from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

from app.domain.allocation_engine import evaluate_bucket_allocation
from app.domain.portfolio_engine import AssetPosition
from app.domain.rebalancing_engine import RebalancingCandidate, calculate_rebalancing
from app.domain.recommendation_engine import (
    RecommendationSeverity,
    RecommendationType,
    SuggestedAction,
    build_recommendations,
)

INVESTABLE = Decimal("10000")
EVALUATED_AT = datetime(2026, 1, 1, tzinfo=timezone.utc)


def make_candidate(
    name,
    current_value,
    *,
    investable=INVESTABLE,
    target=None,
    maximum=None,
    allow_new_buy=True,
    priority=0,
    is_emerg=False,
):
    bucket_id = uuid4()
    position = AssetPosition(
        asset_id=uuid4(),
        symbol=name,
        asset_type="STOCK",
        is_emergency=is_emerg,
        strategy_bucket_id=bucket_id,
        quantity=Decimal("1"),
        current_price=Decimal(current_value),
    )
    allocation = evaluate_bucket_allocation(
        strategy_bucket_id=bucket_id,
        bucket_name=name,
        positions=[position],
        total_value=investable,
        risk_denominator_value=investable,
        excluded_from_risk_allocation=is_emerg,
        target_percent=None if target is None else Decimal(target),
        minimum_percent=None,
        maximum_percent=None if maximum is None else Decimal(maximum),
        allow_new_buy=allow_new_buy,
    )
    return RebalancingCandidate(
        strategy_bucket_id=allocation.strategy_bucket_id,
        bucket_name=allocation.bucket_name,
        actual_value=allocation.actual_value,
        risk_allocation_percent=allocation.risk_allocation_percent,
        target_percent=allocation.target_percent,
        maximum_percent=allocation.maximum_percent,
        allow_new_buy=allocation.allow_new_buy,
        priority=priority,
        is_emergency_excluded=is_emerg,
        target_status=allocation.target_status,
        maximum_status=allocation.maximum_status,
    )


def test_a_maximum_breach_generates_breach_resolution_critical_reduce():
    stocks = make_candidate("Individual Stocks", "2200", maximum="15")  # max value 1500 -> reduce 700
    rebalancing = calculate_rebalancing(candidates=[stocks], available_cash=Decimal("0"), investable_portfolio_value=INVESTABLE)
    recs = build_recommendations(rebalancing, evaluated_at=EVALUATED_AT)

    assert len(recs) == 1
    rec = recs[0]
    assert rec.type == RecommendationType.BREACH_RESOLUTION
    assert rec.severity == RecommendationSeverity.CRITICAL
    assert rec.suggested_action == SuggestedAction.REDUCE
    assert rec.target_category == "Individual Stocks"
    # Must come directly from the Phase 17 recommended_value -- never
    # recomputed here.
    reduce_rec = next(r for r in rebalancing.recommendations if r.bucket_name == "Individual Stocks")
    assert rec.amount == reduce_rec.recommended_value == Decimal("700")


def test_b_available_cash_and_underweight_generates_cash_deployment_using_phase17_amount():
    growth = make_candidate("Growth", "4000", target="55", priority=1)  # gap 1500
    rebalancing = calculate_rebalancing(candidates=[growth], available_cash=Decimal("1000"), investable_portfolio_value=INVESTABLE)
    recs = build_recommendations(rebalancing, evaluated_at=EVALUATED_AT)

    assert len(recs) == 1
    rec = recs[0]
    assert rec.type == RecommendationType.CASH_DEPLOYMENT
    assert rec.suggested_action == SuggestedAction.BUY
    buy_rec = next(r for r in rebalancing.recommendations if r.bucket_name == "Growth")
    assert rec.amount == buy_rec.recommended_value == Decimal("1000")


def test_c_zero_cash_and_underweight_generates_restricted_action_never_a_false_buy():
    growth = make_candidate("Growth", "4000", target="55", priority=1)
    rebalancing = calculate_rebalancing(candidates=[growth], available_cash=Decimal("0"), investable_portfolio_value=INVESTABLE)
    recs = build_recommendations(rebalancing, evaluated_at=EVALUATED_AT)

    assert len(recs) == 1
    rec = recs[0]
    assert rec.type == RecommendationType.RESTRICTED_ACTION
    assert rec.severity == RecommendationSeverity.WARNING
    assert rec.suggested_action != SuggestedAction.BUY
    assert rec.suggested_action == SuggestedAction.HOLD
    assert rec.amount is None


def test_d_healthy_portfolio_within_tolerance_generates_portfolio_healthy():
    on_target = make_candidate("Balanced", "3000", target="30")  # exactly on target
    rebalancing = calculate_rebalancing(candidates=[on_target], available_cash=Decimal("0"), investable_portfolio_value=INVESTABLE)
    recs = build_recommendations(rebalancing, evaluated_at=EVALUATED_AT)

    assert len(recs) == 1
    rec = recs[0]
    assert rec.type == RecommendationType.PORTFOLIO_HEALTHY
    assert rec.severity == RecommendationSeverity.SUCCESS
    assert rec.suggested_action == SuggestedAction.NO_ACTION
    assert rec.target_category is None


def test_e_allow_new_buy_false_generates_restricted_action_hold():
    gold = make_candidate("Gold", "0", target="5", allow_new_buy=False)
    rebalancing = calculate_rebalancing(candidates=[gold], available_cash=Decimal("1000"), investable_portfolio_value=INVESTABLE)
    recs = build_recommendations(rebalancing, evaluated_at=EVALUATED_AT)

    assert len(recs) == 1
    rec = recs[0]
    assert rec.type == RecommendationType.RESTRICTED_ACTION
    assert rec.suggested_action == SuggestedAction.HOLD
    assert rec.target_category == "Gold"


def test_f_no_target_is_not_treated_as_zero_percent_and_generates_no_target_driven_recommendation():
    free_cash = make_candidate("Free Cash", "1000", maximum="15")  # target=None, well under max
    breached = make_candidate("Individual Stocks", "2200", maximum="15")
    rebalancing = calculate_rebalancing(
        candidates=[free_cash, breached], available_cash=Decimal("0"), investable_portfolio_value=INVESTABLE
    )
    recs = build_recommendations(rebalancing, evaluated_at=EVALUATED_AT)

    # Only the genuinely breached category produces a recommendation --
    # the NO_TARGET category is silently skipped, not treated as an
    # implicit 0% target.
    assert len(recs) == 1
    assert recs[0].target_category == "Individual Stocks"
    assert all(r.target_category != "Free Cash" for r in recs)


def test_g_free_cash_never_gets_a_fabricated_asset_level_field():
    free_cash = make_candidate("Free Cash", "200", target="5", priority=1)
    rebalancing = calculate_rebalancing(candidates=[free_cash], available_cash=Decimal("1000"), investable_portfolio_value=INVESTABLE)
    recs = build_recommendations(rebalancing, evaluated_at=EVALUATED_AT)

    assert len(recs) == 1
    assert recs[0].type == RecommendationType.CASH_DEPLOYMENT
    # Category-scoped only -- no asset-level field exists anywhere on
    # this dataclass to fabricate an instrument into.
    assert not hasattr(recs[0], "asset_id")


def test_h_emergency_cash_remains_protected_never_recommended_against():
    emergency = make_candidate("Emergency Reserve", "5000", is_emerg=True)
    growth = make_candidate("Growth", "1000", target="50", priority=1)
    rebalancing = calculate_rebalancing(
        candidates=[emergency, growth], available_cash=Decimal("2000"), investable_portfolio_value=INVESTABLE
    )
    recs = build_recommendations(rebalancing, evaluated_at=EVALUATED_AT)

    assert all(r.target_category != "Emergency Reserve" for r in recs)
    assert any(r.target_category == "Growth" for r in recs)


def test_i_multiple_categories_preserve_phase17_cash_constraints_and_priority():
    a = make_candidate("A", "200", target="10", priority=1)  # gap 800
    b = make_candidate("B", "300", target="10", priority=2)  # gap 700
    breached = make_candidate("Breached", "2200", maximum="15")
    rebalancing = calculate_rebalancing(
        candidates=[a, b, breached], available_cash=Decimal("1000"), investable_portfolio_value=INVESTABLE
    )
    recs = build_recommendations(rebalancing, evaluated_at=EVALUATED_AT)

    # No contradictory instructions, no double-allocation: total BUY
    # amount across recommendations must match Phase 17's own total.
    total_buy = sum((r.amount for r in recs if r.suggested_action == SuggestedAction.BUY), Decimal("0"))
    assert total_buy == rebalancing.total_recommended_buy == Decimal("1000")

    # Deterministic priority: the maximum breach (tier 0) is first,
    # regardless of the buyable categories' own configured priority.
    assert recs[0].type == RecommendationType.BREACH_RESOLUTION
    assert recs[0].target_category == "Breached"
    # Among the two CASH_DEPLOYMENT items, the higher-priority (lower
    # number) category A is listed before B.
    buy_recs = [r for r in recs if r.type == RecommendationType.CASH_DEPLOYMENT]
    assert [r.target_category for r in buy_recs] == ["A", "B"]


def test_deterministic_id_and_content_are_stable_across_different_evaluated_at():
    growth = make_candidate("Growth", "4000", target="55", priority=1)
    rebalancing = calculate_rebalancing(candidates=[growth], available_cash=Decimal("1000"), investable_portfolio_value=INVESTABLE)

    recs_1 = build_recommendations(rebalancing, evaluated_at=EVALUATED_AT)
    recs_2 = build_recommendations(rebalancing, evaluated_at=datetime(2030, 6, 15, tzinfo=timezone.utc))

    assert [r.id for r in recs_1] == [r.id for r in recs_2]
    assert [r.type for r in recs_1] == [r.type for r in recs_2]
    assert [r.amount for r in recs_1] == [r.amount for r in recs_2]
    assert [r.message for r in recs_1] == [r.message for r in recs_2]
    assert recs_1[0].evaluated_at != recs_2[0].evaluated_at
