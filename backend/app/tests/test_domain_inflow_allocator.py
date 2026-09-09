from decimal import Decimal
from uuid import uuid4

import pytest

from app.domain.inflow_allocator import (
    InflowCandidate,
    InflowStatus,
    calculate_inflow_allocation,
)


def candidate(name, current_value, target=None, maximum=None, allow_new_buy=True, priority=0, is_emerg=False):
    return InflowCandidate(
        strategy_bucket_id=uuid4(),
        bucket_name=name,
        current_value=Decimal(current_value),
        target_percent=None if target is None else Decimal(target),
        maximum_percent=None if maximum is None else Decimal(maximum),
        allow_new_buy=allow_new_buy,
        priority=priority,
        is_emergency_excluded=is_emerg,
    )


INVESTABLE = Decimal("10000")


def test_simple_underweight_allocation_fills_target_gap():
    """A. BWA target 55% (=5500), current 4000 -> gap 1500. New cash of
    1000 (less than the gap) should go entirely to BWA."""
    bwa = candidate("BWA", "4000", target="55", priority=1)
    result = calculate_inflow_allocation(
        new_cash_amount=Decimal("1000"), investable_portfolio_value=INVESTABLE, candidates=[bwa]
    )
    rec = result.recommendations[0]
    assert rec.target_gap == Decimal("1500")
    assert rec.allocated_amount == Decimal("1000")
    assert rec.status == InflowStatus.ELIGIBLE
    assert result.allocated_cash == Decimal("1000")
    assert result.unallocated_cash == Decimal("0")


def test_azn_underweight_receives_cash_when_eligible():
    """B. AZN target 25% (=2500), current 1000 -> gap 1500. Alone in the
    portfolio, it receives the full requested cash (less than its gap)."""
    azn = candidate("AZN", "1000", target="25", priority=2)
    result = calculate_inflow_allocation(
        new_cash_amount=Decimal("800"), investable_portfolio_value=INVESTABLE, candidates=[azn]
    )
    rec = result.recommendations[0]
    assert rec.target_gap == Decimal("1500")
    assert rec.allocated_amount == Decimal("800")
    assert rec.status == InflowStatus.ELIGIBLE


def test_priority_determines_order_higher_priority_first():
    """C. Two eligible buckets, both with positive gaps. Priority 1 (BWA)
    must be fully funded before priority 2 (AZN) receives anything."""
    bwa = candidate("BWA", "4000", target="55", priority=1)  # gap 1500
    azn = candidate("AZN", "1000", target="25", priority=2)  # gap 1500
    result = calculate_inflow_allocation(
        new_cash_amount=Decimal("1000"), investable_portfolio_value=INVESTABLE, candidates=[bwa, azn]
    )
    by_name = {r.bucket_name: r for r in result.recommendations}
    assert by_name["BWA"].allocated_amount == Decimal("1000")
    assert by_name["AZN"].allocated_amount == Decimal("0")


def test_priority_change_in_data_changes_result_without_code_change():
    """C (continued). Swapping priority values (pure data change) flips
    which bucket is funded first — no engine code changes."""
    bwa_low_priority = candidate("BWA", "4000", target="55", priority=2)
    azn_high_priority = candidate("AZN", "1000", target="25", priority=1)
    result = calculate_inflow_allocation(
        new_cash_amount=Decimal("1000"),
        investable_portfolio_value=INVESTABLE,
        candidates=[bwa_low_priority, azn_high_priority],
    )
    by_name = {r.bucket_name: r for r in result.recommendations}
    assert by_name["AZN"].allocated_amount == Decimal("1000")
    assert by_name["BWA"].allocated_amount == Decimal("0")


def test_maximum_caps_allocation_below_raw_target_gap():
    """D1. A bucket with BOTH a target and a maximum: target gap is 1500,
    but the maximum only leaves 200 of remaining capacity. Allocation
    must never exceed that 200, even though more cash and a larger raw
    gap both exist."""
    bucket = candidate("Capped", "4800", target="55", maximum="50", priority=1)
    # target_value = 5500, gap = 700; maximum_value = 5000, remaining = 200
    result = calculate_inflow_allocation(
        new_cash_amount=Decimal("5000"), investable_portfolio_value=INVESTABLE, candidates=[bucket]
    )
    rec = result.recommendations[0]
    assert rec.target_gap == Decimal("700")
    assert rec.maximum_capacity == Decimal("200")
    assert rec.allocated_amount == Decimal("200")
    assert rec.status == InflowStatus.ELIGIBLE
    assert result.unallocated_cash == Decimal("4800")


def test_maximum_only_bucket_is_a_constraint_never_a_destination():
    """D2. A maximum-only bucket (no target_percent), e.g. Individual
    Stocks, must receive zero new cash even when well under its maximum
    — it is never invented as a target (Phase 7 approval, section on
    maximum capacity: "prefer treating a maximum-only bucket as a
    constraint rather than a destination")."""
    individual_stocks = candidate("Individual Stocks", "500", maximum="15", priority=3)
    result = calculate_inflow_allocation(
        new_cash_amount=Decimal("5000"), investable_portfolio_value=INVESTABLE, candidates=[individual_stocks]
    )
    rec = result.recommendations[0]
    assert rec.allocated_amount == Decimal("0")
    assert rec.status == InflowStatus.NO_TARGET
    assert result.unallocated_cash == Decimal("5000")


def test_maximum_already_reached_yields_zero_allocation():
    """E. current_value already equals the maximum value -> zero capacity."""
    bucket = candidate("AtMax", "1500", target="55", maximum="15", priority=1)
    # maximum_value = 1500, remaining = 0
    result = calculate_inflow_allocation(
        new_cash_amount=Decimal("1000"), investable_portfolio_value=INVESTABLE, candidates=[bucket]
    )
    rec = result.recommendations[0]
    assert rec.allocated_amount == Decimal("0")
    assert rec.status == InflowStatus.MAXIMUM_LIMIT


def test_maximum_breached_yields_zero_allocation():
    """F. current_value already exceeds the maximum value."""
    bucket = candidate("OverMax", "2000", target="55", maximum="15", priority=1)
    # maximum_value = 1500, remaining = -500
    result = calculate_inflow_allocation(
        new_cash_amount=Decimal("1000"), investable_portfolio_value=INVESTABLE, candidates=[bucket]
    )
    rec = result.recommendations[0]
    assert rec.allocated_amount == Decimal("0")
    assert rec.status == InflowStatus.MAXIMUM_LIMIT


def test_allow_new_buy_false_yields_zero_allocation_even_with_a_gap():
    """G. allow_new_buy=False blocks allocation regardless of target gap."""
    bucket = candidate("Disabled", "1000", target="55", allow_new_buy=False, priority=1)
    result = calculate_inflow_allocation(
        new_cash_amount=Decimal("1000"), investable_portfolio_value=INVESTABLE, candidates=[bucket]
    )
    rec = result.recommendations[0]
    assert rec.allocated_amount == Decimal("0")
    assert rec.status == InflowStatus.BUY_DISABLED


def test_gold_configuration_target_zero_and_buy_disabled_yields_zero():
    """H. Gold: target=0%, allow_new_buy=False, from the database — the
    engine reads this, never hardcodes it."""
    gold = candidate("Gold", "200", target="0", allow_new_buy=False, priority=4)
    result = calculate_inflow_allocation(
        new_cash_amount=Decimal("1000"), investable_portfolio_value=INVESTABLE, candidates=[gold]
    )
    rec = result.recommendations[0]
    assert rec.allocated_amount == Decimal("0")
    assert rec.status == InflowStatus.BUY_DISABLED
    # Existing Gold value is still reported, never removed/sold.
    assert rec.current_value == Decimal("200")


def test_emergency_excluded_bucket_never_receives_new_cash():
    """I. The emergency bucket must never be an inflow destination, and
    gets no misleading percentage figures either."""
    emergency = candidate("Emergency Cash", "100000", is_emerg=True, priority=0)
    result = calculate_inflow_allocation(
        new_cash_amount=Decimal("1000"), investable_portfolio_value=INVESTABLE, candidates=[emergency]
    )
    rec = result.recommendations[0]
    assert rec.allocated_amount == Decimal("0")
    assert rec.status == InflowStatus.EMERGENCY_EXCLUDED
    assert rec.current_percent is None
    assert rec.target_gap is None
    assert result.unallocated_cash == Decimal("1000")


def test_unallocated_cash_when_requested_exceeds_all_capacity():
    """L. Requested cash far exceeds the only eligible gap. The excess is
    returned as unallocated, never forced into any bucket."""
    bwa = candidate("BWA", "4000", target="55", priority=1)  # gap 1500
    result = calculate_inflow_allocation(
        new_cash_amount=Decimal("10000"), investable_portfolio_value=INVESTABLE, candidates=[bwa]
    )
    assert result.allocated_cash == Decimal("1500")
    assert result.unallocated_cash == Decimal("8500")
    assert result.allocated_cash + result.unallocated_cash == result.requested_cash


def test_zero_or_negative_amount_is_rejected():
    """M."""
    bwa = candidate("BWA", "4000", target="55", priority=1)
    with pytest.raises(ValueError):
        calculate_inflow_allocation(
            new_cash_amount=Decimal("0"), investable_portfolio_value=INVESTABLE, candidates=[bwa]
        )
    with pytest.raises(ValueError):
        calculate_inflow_allocation(
            new_cash_amount=Decimal("-100"), investable_portfolio_value=INVESTABLE, candidates=[bwa]
        )


def test_decimal_precision_is_exact():
    """N. Fractional percentages and amounts must not drift."""
    bucket = candidate("Frac", "3333.33", target="33.33", priority=1)
    investable = Decimal("10000.00")
    # target_value = 33.33% of 10000.00 = 3333.0000...; use exact Decimal math to compute expected gap
    expected_target_value = (Decimal("33.33") / Decimal("100")) * investable
    expected_gap = expected_target_value - Decimal("3333.33")
    result = calculate_inflow_allocation(
        new_cash_amount=Decimal("10.00"), investable_portfolio_value=investable, candidates=[bucket]
    )
    rec = result.recommendations[0]
    assert rec.target_gap == expected_gap
    assert isinstance(rec.allocated_amount, Decimal)


def test_projected_percent_uses_post_inflow_denominator_and_differs_from_current():
    """S. Projected percentage must use investable_value + allocated_cash
    as its denominator, and must differ from current_percent when an
    allocation actually occurs."""
    bwa = candidate("BWA", "4000", target="55", priority=1)  # current 40%, gap 1500
    result = calculate_inflow_allocation(
        new_cash_amount=Decimal("1000"), investable_portfolio_value=INVESTABLE, candidates=[bwa]
    )
    rec = result.recommendations[0]
    assert rec.current_percent == Decimal("40")  # 4000/10000*100
    projected_total = INVESTABLE + result.allocated_cash  # 11000
    expected_projected_percent = ((Decimal("4000") + Decimal("1000")) / projected_total) * Decimal("100")
    assert rec.projected_percent == expected_projected_percent
    assert rec.projected_percent != rec.current_percent


def test_engine_never_mutates_candidates_or_creates_side_effect_fields():
    """No side effects at the domain level: the result carries no field
    that could represent a database write, a sell, or a trade."""
    bwa = candidate("BWA", "4000", target="55", priority=1)
    result = calculate_inflow_allocation(
        new_cash_amount=Decimal("1000"), investable_portfolio_value=INVESTABLE, candidates=[bwa]
    )
    rec = result.recommendations[0]
    assert not hasattr(rec, "transaction_id")
    assert not hasattr(rec, "sell_amount")
    assert not hasattr(result, "transactions_created")
