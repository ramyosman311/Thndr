from decimal import Decimal
from uuid import uuid4

from app.domain.allocation_engine import (
    MaximumStatus,
    MinimumStatus,
    TargetStatus,
    evaluate_bucket_allocation,
)
from app.domain.portfolio_engine import AssetPosition


def make_position(bucket_id, quantity, price, is_emergency=False):
    return AssetPosition(
        asset_id=uuid4(),
        symbol="X",
        is_emergency=is_emergency,
        strategy_bucket_id=bucket_id,
        quantity=Decimal(quantity),
        current_price=Decimal(price),
    )


def test_overweight_but_not_maximum_breach():
    bucket_id = uuid4()
    positions = [make_position(bucket_id, "12", "1")]  # actual value 12, 12% of 100
    result = evaluate_bucket_allocation(
        strategy_bucket_id=bucket_id,
        bucket_name="Test",
        positions=positions,
        denominator_value=Decimal("100"),
        target_percent=Decimal("10"),
        minimum_percent=None,
        maximum_percent=Decimal("15"),
        allow_new_buy=True,
    )
    assert result.actual_percent == Decimal("12")
    assert result.target_status == TargetStatus.OVERWEIGHT
    assert result.maximum_status == MaximumStatus.WITHIN_MAXIMUM
    assert result.buy_allowed is True


def test_maximum_breach_at_and_above_boundary():
    bucket_id = uuid4()

    for quantity in ("16", "15"):  # both >= 15% maximum
        positions = [make_position(bucket_id, quantity, "1")]
        result = evaluate_bucket_allocation(
            strategy_bucket_id=bucket_id,
            bucket_name="Test",
            positions=positions,
            denominator_value=Decimal("100"),
            target_percent=Decimal("10"),
            minimum_percent=None,
            maximum_percent=Decimal("15"),
            allow_new_buy=True,
        )
        assert result.maximum_status == MaximumStatus.MAXIMUM_BREACHED
        assert result.buy_allowed is False  # frozen even though allow_new_buy=True; never a sell signal


def test_individual_stocks_style_bucket_no_target_reports_maximum_only():
    bucket_id = uuid4()
    positions = [make_position(bucket_id, "15", "1")]
    result = evaluate_bucket_allocation(
        strategy_bucket_id=bucket_id,
        bucket_name="Individual Stocks",
        positions=positions,
        denominator_value=Decimal("100"),
        target_percent=None,
        minimum_percent=None,
        maximum_percent=Decimal("15"),
        allow_new_buy=True,
    )
    assert result.target_status == TargetStatus.NO_TARGET
    assert result.maximum_status == MaximumStatus.MAXIMUM_BREACHED
    assert result.buy_allowed is False


def test_allow_new_buy_flag_changes_result_without_code_change():
    bucket_id = uuid4()
    positions = [make_position(bucket_id, "5", "1")]  # 5%, well under any maximum
    kwargs = dict(
        strategy_bucket_id=bucket_id,
        bucket_name="Some Bucket",
        positions=positions,
        denominator_value=Decimal("100"),
        target_percent=None,
        minimum_percent=None,
        maximum_percent=None,
    )
    allowed = evaluate_bucket_allocation(**kwargs, allow_new_buy=True)
    disallowed = evaluate_bucket_allocation(**kwargs, allow_new_buy=False)

    assert allowed.buy_allowed is True
    assert disallowed.buy_allowed is False


def test_gold_style_zero_target_and_disallowed_buy_is_configuration_driven():
    bucket_id = uuid4()
    positions = [make_position(bucket_id, "10", "1")]  # existing gold still held/reported
    result = evaluate_bucket_allocation(
        strategy_bucket_id=bucket_id,
        bucket_name="Gold",
        positions=positions,
        denominator_value=Decimal("1000"),
        target_percent=Decimal("0"),
        minimum_percent=None,
        maximum_percent=None,
        allow_new_buy=False,
    )
    assert result.actual_value == Decimal("10")  # existing gold value still reported, never deleted
    assert result.allow_new_buy is False
    assert result.buy_allowed is False
    assert result.target_status == TargetStatus.OVERWEIGHT  # 1% actual vs 0% target


def test_zero_denominator_yields_zero_percent_not_a_crash():
    bucket_id = uuid4()
    positions = [make_position(bucket_id, "10", "1")]
    result = evaluate_bucket_allocation(
        strategy_bucket_id=bucket_id,
        bucket_name="Test",
        positions=positions,
        denominator_value=Decimal("0"),
        target_percent=Decimal("10"),
        minimum_percent=None,
        maximum_percent=None,
        allow_new_buy=True,
    )
    assert result.actual_percent == Decimal("0")


def test_minimum_breach_is_independent_of_target_status():
    bucket_id = uuid4()
    positions = [make_position(bucket_id, "20", "1")]  # actual = 2% of 1000
    result = evaluate_bucket_allocation(
        strategy_bucket_id=bucket_id,
        bucket_name="Test",
        positions=positions,
        denominator_value=Decimal("1000"),
        target_percent=Decimal("10"),
        minimum_percent=Decimal("5"),
        maximum_percent=None,
        allow_new_buy=True,
    )
    assert result.minimum_status == MinimumStatus.MINIMUM_BREACHED
    assert result.target_status == TargetStatus.UNDERWEIGHT


def test_on_target_within_tolerance():
    bucket_id = uuid4()
    positions = [make_position(bucket_id, "552", "1")]  # 55.2% vs target 55%, within 0.5 tolerance
    result = evaluate_bucket_allocation(
        strategy_bucket_id=bucket_id,
        bucket_name="Growth",
        positions=positions,
        denominator_value=Decimal("1000"),
        target_percent=Decimal("55"),
        minimum_percent=None,
        maximum_percent=None,
        allow_new_buy=True,
    )
    assert result.target_status == TargetStatus.ON_TARGET


def test_maximum_breach_never_triggers_a_sell_it_only_reports():
    """The result object has no field or method that could execute a sell —
    this is itself the guarantee that the engine only ever reports."""
    bucket_id = uuid4()
    positions = [make_position(bucket_id, "20", "1")]
    result = evaluate_bucket_allocation(
        strategy_bucket_id=bucket_id,
        bucket_name="Test",
        positions=positions,
        denominator_value=Decimal("100"),
        target_percent=Decimal("10"),
        minimum_percent=None,
        maximum_percent=Decimal("15"),
        allow_new_buy=True,
    )
    assert result.maximum_status == MaximumStatus.MAXIMUM_BREACHED
    assert not hasattr(result, "sell")
    assert not hasattr(result, "recommended_sell_quantity")
