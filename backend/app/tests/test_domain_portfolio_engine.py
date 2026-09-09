from decimal import Decimal
from uuid import uuid4

from app.domain.portfolio_engine import AssetPosition, calculate_portfolio_totals


def make_position(*, is_emergency=False, bucket_id=None, quantity="0", price="0"):
    return AssetPosition(
        asset_id=uuid4(),
        symbol="TEST",
        is_emergency=is_emergency,
        strategy_bucket_id=bucket_id,
        quantity=Decimal(quantity),
        current_price=Decimal(price),
    )


def test_emergency_excluded_uses_investable_value_as_denominator():
    positions = [
        make_position(is_emergency=True, quantity="1", price="100000"),
        make_position(is_emergency=False, quantity="1", price="10000"),
    ]
    totals = calculate_portfolio_totals(positions, emergency_excluded=True)

    assert totals.emergency_value == Decimal("100000")
    assert totals.investable_value == Decimal("10000")
    assert totals.total_value == Decimal("110000")
    assert totals.denominator_value == Decimal("10000")
    assert totals.denominator_basis == "investable"
    assert totals.denominator_is_zero is False


def test_emergency_included_uses_total_value_as_denominator():
    positions = [
        make_position(is_emergency=True, quantity="1", price="100000"),
        make_position(is_emergency=False, quantity="1", price="10000"),
    ]
    totals = calculate_portfolio_totals(positions, emergency_excluded=False)

    assert totals.denominator_value == Decimal("110000")
    assert totals.denominator_basis == "total"


def test_zero_investable_portfolio_when_emergency_excluded_is_well_defined():
    positions = [make_position(is_emergency=True, quantity="1", price="50000")]
    totals = calculate_portfolio_totals(positions, emergency_excluded=True)

    assert totals.investable_value == Decimal("0")
    assert totals.denominator_value == Decimal("0")
    assert totals.denominator_is_zero is True


def test_asset_without_holding_contributes_known_zero_value():
    position = make_position(quantity="0", price="0")
    assert position.value == Decimal("0")


def test_no_positions_produces_well_defined_zero_state():
    totals = calculate_portfolio_totals([], emergency_excluded=True)
    assert totals.total_value == Decimal("0")
    assert totals.denominator_is_zero is True


def test_total_value_is_always_emergency_plus_investable_regardless_of_exclusion():
    positions = [
        make_position(is_emergency=True, quantity="2", price="1000"),
        make_position(is_emergency=False, quantity="3", price="500"),
    ]
    excluded = calculate_portfolio_totals(positions, emergency_excluded=True)
    included = calculate_portfolio_totals(positions, emergency_excluded=False)

    assert excluded.total_value == included.total_value == Decimal("3500")
