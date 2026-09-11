from decimal import Decimal
from uuid import uuid4

from app.domain.portfolio_engine import AssetPosition, calculate_portfolio_totals


def make_position(*, is_emergency=False, bucket_id=None, quantity="0", price="0", asset_id=None, asset_type="STOCK"):
    return AssetPosition(
        asset_id=asset_id or uuid4(),
        symbol="TEST",
        asset_type=asset_type,
        is_emergency=is_emergency,
        strategy_bucket_id=bucket_id,
        quantity=Decimal(quantity),
        current_price=None if price is None else Decimal(price),
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


# --- Phase 11: unpriced positions never fabricate a zero value --------------


def test_held_asset_with_no_price_has_no_value():
    position = make_position(quantity="10", price=None)
    assert position.value is None


def test_zero_quantity_position_always_values_at_zero_even_without_a_price():
    """No holding to price -- this is never an 'incomplete' valuation,
    just a genuinely empty position."""
    position = make_position(quantity="0", price=None)
    assert position.value == Decimal("0")


def test_unpriced_position_is_excluded_from_totals_not_counted_as_zero():
    priced_id = uuid4()
    unpriced_id = uuid4()
    positions = [
        make_position(asset_id=priced_id, is_emergency=False, quantity="10", price="100"),  # 1000
        make_position(asset_id=unpriced_id, is_emergency=False, quantity="5", price=None),
    ]
    totals = calculate_portfolio_totals(positions, emergency_excluded=False)

    assert totals.investable_value == Decimal("1000")  # unpriced position excluded, not counted as 0
    assert totals.total_value == Decimal("1000")
    assert totals.unpriced_asset_ids == frozenset({unpriced_id})
    assert totals.is_complete is False


def test_fully_priced_portfolio_reports_complete_valuation():
    positions = [make_position(quantity="1", price="100")]
    totals = calculate_portfolio_totals(positions, emergency_excluded=False)
    assert totals.unpriced_asset_ids == frozenset()
    assert totals.is_complete is True


def test_total_value_is_always_emergency_plus_investable_regardless_of_exclusion():
    positions = [
        make_position(is_emergency=True, quantity="2", price="1000"),
        make_position(is_emergency=False, quantity="3", price="500"),
    ]
    excluded = calculate_portfolio_totals(positions, emergency_excluded=True)
    included = calculate_portfolio_totals(positions, emergency_excluded=False)

    assert excluded.total_value == included.total_value == Decimal("3500")
