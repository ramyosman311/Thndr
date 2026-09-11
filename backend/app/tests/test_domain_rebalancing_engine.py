"""Phase 17: Smart Rebalancing Engine — pure domain tests, mirroring the
scenario letters (A-K) from the approved spec. Test L (no mutation) is
an integration-level test — see test_rebalancing_service.py.

Candidates are built by feeding a single synthetic position through the
REAL, unchanged `allocation_engine.evaluate_bucket_allocation` (never by
hand-setting a TargetStatus/MaximumStatus) so these tests exercise the
exact same status classification the real service uses.
"""

from decimal import Decimal
from uuid import uuid4

from app.domain.allocation_engine import MaximumStatus, TargetStatus, evaluate_bucket_allocation
from app.domain.portfolio_engine import AssetPosition
from app.domain.rebalancing_engine import RebalancingAction, RebalancingCandidate, calculate_rebalancing

INVESTABLE = Decimal("10000")


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


def test_a_underweight_with_available_cash_produces_buy():
    growth = make_candidate("Growth", "4000", target="55", priority=1)  # target 5500, gap 1500
    result = calculate_rebalancing(candidates=[growth], available_cash=Decimal("1000"), investable_portfolio_value=INVESTABLE)
    rec = result.recommendations[0]
    assert rec.action == RebalancingAction.BUY
    assert rec.recommended_value == Decimal("1000")
    assert result.total_recommended_buy == Decimal("1000")


def test_b_underweight_with_zero_cash_produces_no_capacity():
    growth = make_candidate("Growth", "4000", target="55", priority=1)
    result = calculate_rebalancing(candidates=[growth], available_cash=Decimal("0"), investable_portfolio_value=INVESTABLE)
    rec = result.recommendations[0]
    assert rec.action == RebalancingAction.NO_CAPACITY
    assert rec.recommended_value is None
    assert result.total_recommended_buy == Decimal("0")


def test_c_maximum_breach_produces_correct_reduction():
    stocks = make_candidate("Individual Stocks", "2000", maximum="15")  # max value 1500
    result = calculate_rebalancing(candidates=[stocks], available_cash=Decimal("0"), investable_portfolio_value=INVESTABLE)
    rec = result.recommendations[0]
    assert rec.action == RebalancingAction.REDUCE
    assert rec.status == MaximumStatus.MAXIMUM_BREACHED.value
    assert rec.recommended_value == Decimal("500")  # 2000 - 1500


def test_maximum_takes_priority_over_a_higher_target():
    """Section 3: current=18%, target=20%, maximum=15% -> REDUCE, never BUY."""
    bucket = make_candidate("Aggressive", "1800", target="20", maximum="15")
    result = calculate_rebalancing(candidates=[bucket], available_cash=Decimal("5000"), investable_portfolio_value=INVESTABLE)
    rec = result.recommendations[0]
    assert rec.action == RebalancingAction.REDUCE
    assert rec.recommended_value == Decimal("300")  # 1800 - 1500


def test_d_target_below_maximum_produces_buy_capacity_subject_to_cash():
    bucket = make_candidate("Balanced", "1000", target="30", maximum="50")  # target 3000, gap 2000; max 5000
    result = calculate_rebalancing(candidates=[bucket], available_cash=Decimal("1500"), investable_portfolio_value=INVESTABLE)
    rec = result.recommendations[0]
    assert rec.action == RebalancingAction.BUY
    assert rec.recommended_value == Decimal("1500")  # capped by available cash, not the full 2000 gap


def test_e_between_target_and_maximum_holds_without_forcing_a_sell():
    bucket = make_candidate("Balanced", "3500", target="30", maximum="50")  # target 3000 -> overweight, max 5000 -> within
    result = calculate_rebalancing(candidates=[bucket], available_cash=Decimal("1000"), investable_portfolio_value=INVESTABLE)
    rec = result.recommendations[0]
    assert rec.action == RebalancingAction.HOLD
    assert rec.recommended_value is None
    assert rec.status == TargetStatus.OVERWEIGHT.value


def test_f_allow_new_buy_false_never_produces_a_buy():
    gold = make_candidate("Gold", "0", target="5", allow_new_buy=False)
    result = calculate_rebalancing(candidates=[gold], available_cash=Decimal("1000"), investable_portfolio_value=INVESTABLE)
    rec = result.recommendations[0]
    assert rec.action == RebalancingAction.HOLD
    assert rec.recommended_value is None
    assert result.total_recommended_buy == Decimal("0")


def test_g_no_target_is_never_treated_as_a_zero_percent_target():
    stocks = make_candidate("Individual Stocks", "1000", maximum="15")  # target=None, well under max 1500
    result = calculate_rebalancing(candidates=[stocks], available_cash=Decimal("1000"), investable_portfolio_value=INVESTABLE)
    rec = result.recommendations[0]
    assert rec.action == RebalancingAction.NO_TARGET
    assert rec.target_value is None
    assert rec.difference_value is None
    assert result.total_recommended_buy == Decimal("0")


def test_h_free_cash_category_gets_a_category_level_recommendation_not_a_fake_asset():
    free_cash = make_candidate("Free Cash", "200", target="5", priority=1)  # target 500, gap 300
    result = calculate_rebalancing(candidates=[free_cash], available_cash=Decimal("1000"), investable_portfolio_value=INVESTABLE)
    rec = result.recommendations[0]
    assert rec.action == RebalancingAction.BUY
    assert rec.recommended_value == Decimal("300")
    # The recommendation is category-scoped only -- no asset-level field
    # exists anywhere on this dataclass to fabricate an instrument into.
    assert not hasattr(rec, "asset_id")


def test_i_emergency_cash_is_never_consumed_by_ordinary_rebalancing():
    emergency = make_candidate("Emergency Reserve", "5000", is_emerg=True)
    growth = make_candidate("Growth", "1000", target="50", priority=1)  # gap 4000 at investable=10000
    result = calculate_rebalancing(
        candidates=[emergency, growth], available_cash=Decimal("2000"), investable_portfolio_value=INVESTABLE
    )
    by_name = {r.bucket_name: r for r in result.recommendations}
    assert by_name["Emergency Reserve"].action == RebalancingAction.HOLD
    assert by_name["Emergency Reserve"].recommended_value is None
    # All available cash went to Growth -- none of it was ever attributed
    # to funding via the emergency bucket.
    assert by_name["Growth"].recommended_value == Decimal("2000")
    assert result.total_recommended_buy == Decimal("2000")


def test_j_multiple_underweight_categories_never_exceed_available_cash():
    a = make_candidate("A", "200", target="10", priority=1)  # target 1000, gap 800
    b = make_candidate("B", "300", target="10", priority=2)  # target 1000, gap 700
    result = calculate_rebalancing(candidates=[a, b], available_cash=Decimal("1000"), investable_portfolio_value=INVESTABLE)
    by_name = {r.bucket_name: r for r in result.recommendations}
    total = sum((r.recommended_value or Decimal("0")) for r in result.recommendations)
    assert total <= Decimal("1000")
    assert total == Decimal("1000")
    # Priority 1 (A) is fully funded (800) before priority 2 (B) gets the
    # remaining 200 -- never both funded in full (that would be 1500).
    assert by_name["A"].recommended_value == Decimal("800")
    assert by_name["B"].recommended_value == Decimal("200")
    assert result.total_recommended_buy == Decimal("1000")


def test_k_reduce_never_exceeds_the_actual_held_value():
    # An extreme breach: maximum is 1%, actual holding is the entire
    # portfolio's investable value.
    bucket = make_candidate("Overconcentrated", "10000", maximum="1")
    result = calculate_rebalancing(candidates=[bucket], available_cash=Decimal("0"), investable_portfolio_value=INVESTABLE)
    rec = result.recommendations[0]
    assert rec.action == RebalancingAction.REDUCE
    assert rec.recommended_value is not None
    assert rec.recommended_value <= rec.actual_value


def test_zero_investable_value_reports_no_capacity_not_a_crash():
    bucket = make_candidate("Growth", "0", target="50", investable=Decimal("0"))
    result = calculate_rebalancing(candidates=[bucket], available_cash=Decimal("0"), investable_portfolio_value=Decimal("0"))
    rec = result.recommendations[0]
    assert rec.action == RebalancingAction.NO_CAPACITY
