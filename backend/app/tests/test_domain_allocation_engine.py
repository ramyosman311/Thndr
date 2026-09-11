from decimal import Decimal
from uuid import uuid4

from app.domain.allocation_engine import (
    MaximumStatus,
    MinimumStatus,
    TargetStatus,
    evaluate_bucket_allocation,
)
from app.domain.portfolio_engine import AssetPosition


def make_position(bucket_id, quantity, price, is_emergency=False, asset_type="STOCK"):
    return AssetPosition(
        asset_id=uuid4(),
        symbol="X",
        asset_type=asset_type,
        is_emergency=is_emergency,
        strategy_bucket_id=bucket_id,
        quantity=Decimal(quantity),
        current_price=None if price is None else Decimal(price),
    )


def test_overweight_but_not_maximum_breach():
    bucket_id = uuid4()
    positions = [make_position(bucket_id, "12", "1")]  # actual value 12, 12% of 100
    result = evaluate_bucket_allocation(
        strategy_bucket_id=bucket_id,
        bucket_name="Test",
        positions=positions,
        total_value=Decimal("100"),
        risk_denominator_value=Decimal("100"),
        excluded_from_risk_allocation=False,
        target_percent=Decimal("10"),
        minimum_percent=None,
        maximum_percent=Decimal("15"),
        allow_new_buy=True,
    )
    assert result.risk_allocation_percent == Decimal("12")
    assert result.total_portfolio_percent == Decimal("12")
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
            total_value=Decimal("100"),
            risk_denominator_value=Decimal("100"),
            excluded_from_risk_allocation=False,
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
        total_value=Decimal("100"),
        risk_denominator_value=Decimal("100"),
        excluded_from_risk_allocation=False,
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
        total_value=Decimal("100"),
        risk_denominator_value=Decimal("100"),
        excluded_from_risk_allocation=False,
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
        total_value=Decimal("1000"),
        risk_denominator_value=Decimal("1000"),
        excluded_from_risk_allocation=False,
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
        total_value=Decimal("0"),
        risk_denominator_value=Decimal("0"),
        excluded_from_risk_allocation=False,
        target_percent=Decimal("10"),
        minimum_percent=None,
        maximum_percent=None,
        allow_new_buy=True,
    )
    assert result.risk_allocation_percent == Decimal("0")
    assert result.total_portfolio_percent == Decimal("0")


def test_minimum_breach_is_independent_of_target_status():
    bucket_id = uuid4()
    positions = [make_position(bucket_id, "20", "1")]  # actual = 2% of 1000
    result = evaluate_bucket_allocation(
        strategy_bucket_id=bucket_id,
        bucket_name="Test",
        positions=positions,
        total_value=Decimal("1000"),
        risk_denominator_value=Decimal("1000"),
        excluded_from_risk_allocation=False,
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
        total_value=Decimal("1000"),
        risk_denominator_value=Decimal("1000"),
        excluded_from_risk_allocation=False,
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
        total_value=Decimal("100"),
        risk_denominator_value=Decimal("100"),
        excluded_from_risk_allocation=False,
        target_percent=Decimal("10"),
        minimum_percent=None,
        maximum_percent=Decimal("15"),
        allow_new_buy=True,
    )
    assert result.maximum_status == MaximumStatus.MAXIMUM_BREACHED
    assert not hasattr(result, "sell")
    assert not hasattr(result, "recommended_sell_quantity")


def test_excluded_from_risk_allocation_gives_null_risk_percent_not_misleading_number():
    """The Phase 5 caveat this resolves: a bucket excluded from risk
    allocation (e.g. holding the emergency asset when emergency_excluded)
    must never show something like 1000% just because its value is large
    relative to a denominator that excludes it."""
    bucket_id = uuid4()
    # Value (100,000) is 10x the risk denominator (10,000) — this would be
    # 1000% if computed against risk_denominator_value.
    positions = [make_position(bucket_id, "1", "100000")]
    result = evaluate_bucket_allocation(
        strategy_bucket_id=bucket_id,
        bucket_name="Emergency Cash",
        positions=positions,
        total_value=Decimal("110000"),
        risk_denominator_value=Decimal("10000"),
        excluded_from_risk_allocation=True,
        target_percent=None,
        minimum_percent=None,
        maximum_percent=None,
        allow_new_buy=None,
    )
    assert result.risk_allocation_percent is None
    # total_portfolio_percent remains well-defined and accurate regardless.
    assert result.total_portfolio_percent == (Decimal("100000") / Decimal("110000") * 100)
    assert result.target_status == TargetStatus.NO_TARGET
    assert result.minimum_status == MinimumStatus.NO_MINIMUM
    assert result.maximum_status == MaximumStatus.NO_MAXIMUM
    assert result.excluded_from_risk_allocation is True


def test_excluded_bucket_with_a_configured_maximum_reports_not_applicable_rather_than_guessing():
    """If a rule were ever configured on a risk-excluded bucket (not the
    normal case, but not schema-forbidden), the engine must not invent a
    comparison against an undefined percentage."""
    bucket_id = uuid4()
    positions = [make_position(bucket_id, "1", "100000")]
    result = evaluate_bucket_allocation(
        strategy_bucket_id=bucket_id,
        bucket_name="Emergency Cash",
        positions=positions,
        total_value=Decimal("110000"),
        risk_denominator_value=Decimal("10000"),
        excluded_from_risk_allocation=True,
        target_percent=Decimal("10"),
        minimum_percent=None,
        maximum_percent=Decimal("20"),
        allow_new_buy=True,
    )
    assert result.risk_allocation_percent is None
    assert result.target_status == TargetStatus.NO_TARGET
    assert result.maximum_status == MaximumStatus.NO_MAXIMUM
    # Buying is not frozen by an unevaluable maximum.
    assert result.buy_allowed is True


# --- Phase 11: unpriced positions surfaced, never silently zeroed -----------


def test_bucket_with_a_fully_unpriced_position_reports_has_unpriced_positions():
    bucket_id = uuid4()
    positions = [make_position(bucket_id, "10", None)]
    result = evaluate_bucket_allocation(
        strategy_bucket_id=bucket_id,
        bucket_name="Test",
        positions=positions,
        total_value=Decimal("0"),
        risk_denominator_value=Decimal("0"),
        excluded_from_risk_allocation=False,
        target_percent=None,
        minimum_percent=None,
        maximum_percent=None,
        allow_new_buy=None,
    )
    assert result.has_unpriced_positions is True
    assert result.actual_value == Decimal("0")  # excluded from the sum, not counted as 0-priced


def test_bucket_with_all_positions_priced_reports_no_unpriced_positions():
    bucket_id = uuid4()
    positions = [make_position(bucket_id, "10", "5")]
    result = evaluate_bucket_allocation(
        strategy_bucket_id=bucket_id,
        bucket_name="Test",
        positions=positions,
        total_value=Decimal("50"),
        risk_denominator_value=Decimal("50"),
        excluded_from_risk_allocation=False,
        target_percent=None,
        minimum_percent=None,
        maximum_percent=None,
        allow_new_buy=None,
    )
    assert result.has_unpriced_positions is False
