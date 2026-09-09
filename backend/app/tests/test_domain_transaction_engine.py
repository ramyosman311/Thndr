from decimal import Decimal

import pytest

from app.domain.transaction_engine import OversellError, apply_buy, apply_sell


# --- BUY ---------------------------------------------------------------


def test_first_buy_on_empty_position():
    result = apply_buy(
        current_quantity=Decimal("0"),
        current_average_cost=Decimal("0"),
        purchase_quantity=Decimal("10"),
        purchase_price=Decimal("100"),
        fees=Decimal("0"),
    )
    assert result.quantity == Decimal("10")
    assert result.average_cost == Decimal("100")


def test_multiple_buys_blend_average_cost():
    first = apply_buy(
        current_quantity=Decimal("0"),
        current_average_cost=Decimal("0"),
        purchase_quantity=Decimal("10"),
        purchase_price=Decimal("100"),
        fees=Decimal("0"),
    )
    second = apply_buy(
        current_quantity=first.quantity,
        current_average_cost=first.average_cost,
        purchase_quantity=Decimal("5"),
        purchase_price=Decimal("120"),
        fees=Decimal("0"),
    )
    # (10*100 + 5*120) / 15 = 1600/15
    assert second.quantity == Decimal("15")
    assert second.average_cost == Decimal("1600") / Decimal("15")


def test_buy_with_fees_increases_cost_basis():
    result = apply_buy(
        current_quantity=Decimal("0"),
        current_average_cost=Decimal("0"),
        purchase_quantity=Decimal("10"),
        purchase_price=Decimal("100"),
        fees=Decimal("50"),
    )
    # cost basis = 1000 + 50 = 1050, average cost = 105
    assert result.average_cost == Decimal("105")


def test_buy_onto_existing_holding_before_any_new_transaction():
    """An asset that already had a holding (e.g. seeded or from an
    earlier phase) blends correctly with a brand-new purchase."""
    result = apply_buy(
        current_quantity=Decimal("20"),
        current_average_cost=Decimal("50"),
        purchase_quantity=Decimal("10"),
        purchase_price=Decimal("80"),
        fees=Decimal("0"),
    )
    # (20*50 + 10*80) / 30 = (1000+800)/30 = 1800/30 = 60
    assert result.quantity == Decimal("30")
    assert result.average_cost == Decimal("60")


def test_buy_rejects_zero_quantity():
    with pytest.raises(ValueError):
        apply_buy(
            current_quantity=Decimal("0"),
            current_average_cost=Decimal("0"),
            purchase_quantity=Decimal("0"),
            purchase_price=Decimal("100"),
            fees=Decimal("0"),
        )


def test_buy_rejects_negative_quantity():
    with pytest.raises(ValueError):
        apply_buy(
            current_quantity=Decimal("0"),
            current_average_cost=Decimal("0"),
            purchase_quantity=Decimal("-5"),
            purchase_price=Decimal("100"),
            fees=Decimal("0"),
        )


def test_buy_rejects_negative_price():
    with pytest.raises(ValueError):
        apply_buy(
            current_quantity=Decimal("0"),
            current_average_cost=Decimal("0"),
            purchase_quantity=Decimal("10"),
            purchase_price=Decimal("-1"),
            fees=Decimal("0"),
        )


def test_buy_rejects_negative_fees():
    with pytest.raises(ValueError):
        apply_buy(
            current_quantity=Decimal("0"),
            current_average_cost=Decimal("0"),
            purchase_quantity=Decimal("10"),
            purchase_price=Decimal("100"),
            fees=Decimal("-1"),
        )


def test_buy_zero_price_is_allowed():
    """A zero price (e.g. a bonus/gift share) is not negative, so it's
    accepted — only negative prices are rejected."""
    result = apply_buy(
        current_quantity=Decimal("0"),
        current_average_cost=Decimal("0"),
        purchase_quantity=Decimal("10"),
        purchase_price=Decimal("0"),
        fees=Decimal("0"),
    )
    assert result.average_cost == Decimal("0")


# --- SELL ----------------------------------------------------------------


def test_partial_sell_reduces_quantity_and_preserves_average_cost():
    result = apply_sell(
        current_quantity=Decimal("10"),
        current_average_cost=Decimal("100"),
        sell_quantity=Decimal("4"),
        sell_price=Decimal("120"),
        fees=Decimal("0"),
    )
    assert result.quantity == Decimal("6")
    # Average cost of the remainder is unchanged under average-cost accounting.
    assert result.average_cost == Decimal("100")


def test_full_sell_zeroes_quantity_and_cost_basis():
    result = apply_sell(
        current_quantity=Decimal("10"),
        current_average_cost=Decimal("100"),
        sell_quantity=Decimal("10"),
        sell_price=Decimal("120"),
        fees=Decimal("0"),
    )
    assert result.quantity == Decimal("0")
    assert result.average_cost == Decimal("0")
    # No negative residual anywhere.
    assert result.quantity >= 0
    assert result.average_cost >= 0


def test_sell_with_fees_reduces_realized_proceeds():
    result = apply_sell(
        current_quantity=Decimal("10"),
        current_average_cost=Decimal("100"),
        sell_quantity=Decimal("10"),
        sell_price=Decimal("120"),
        fees=Decimal("50"),
    )
    # proceeds = 10*120 - 50 = 1150; cost removed = 10*100 = 1000
    # realized_pnl = 1150 - 1000 = 150
    assert result.realized_pnl == Decimal("150")


def test_sell_realized_pnl_positive_when_price_above_cost():
    result = apply_sell(
        current_quantity=Decimal("10"),
        current_average_cost=Decimal("50"),
        sell_quantity=Decimal("5"),
        sell_price=Decimal("80"),
        fees=Decimal("0"),
    )
    # proceeds = 5*80 = 400; cost removed = 5*50 = 250; pnl = 150
    assert result.realized_pnl == Decimal("150")


def test_sell_realized_pnl_negative_when_price_below_cost():
    result = apply_sell(
        current_quantity=Decimal("10"),
        current_average_cost=Decimal("100"),
        sell_quantity=Decimal("5"),
        sell_price=Decimal("80"),
        fees=Decimal("0"),
    )
    # proceeds = 400; cost removed = 500; pnl = -100
    assert result.realized_pnl == Decimal("-100")


def test_oversell_is_rejected():
    with pytest.raises(OversellError):
        apply_sell(
            current_quantity=Decimal("5"),
            current_average_cost=Decimal("100"),
            sell_quantity=Decimal("6"),
            sell_price=Decimal("120"),
            fees=Decimal("0"),
        )


def test_oversell_error_message_reports_available_quantity():
    with pytest.raises(OversellError, match="only 5"):
        apply_sell(
            current_quantity=Decimal("5"),
            current_average_cost=Decimal("100"),
            sell_quantity=Decimal("10"),
            sell_price=Decimal("120"),
            fees=Decimal("0"),
        )


def test_sell_rejects_zero_quantity():
    with pytest.raises(ValueError):
        apply_sell(
            current_quantity=Decimal("10"),
            current_average_cost=Decimal("100"),
            sell_quantity=Decimal("0"),
            sell_price=Decimal("120"),
            fees=Decimal("0"),
        )


def test_sell_rejects_negative_quantity():
    with pytest.raises(ValueError):
        apply_sell(
            current_quantity=Decimal("10"),
            current_average_cost=Decimal("100"),
            sell_quantity=Decimal("-1"),
            sell_price=Decimal("120"),
            fees=Decimal("0"),
        )


def test_sell_rejects_negative_price():
    with pytest.raises(ValueError):
        apply_sell(
            current_quantity=Decimal("10"),
            current_average_cost=Decimal("100"),
            sell_quantity=Decimal("1"),
            sell_price=Decimal("-1"),
            fees=Decimal("0"),
        )


def test_sell_rejects_negative_fees():
    with pytest.raises(ValueError):
        apply_sell(
            current_quantity=Decimal("10"),
            current_average_cost=Decimal("100"),
            sell_quantity=Decimal("1"),
            sell_price=Decimal("100"),
            fees=Decimal("-1"),
        )


def test_selling_from_zero_quantity_is_always_an_oversell():
    with pytest.raises(OversellError):
        apply_sell(
            current_quantity=Decimal("0"),
            current_average_cost=Decimal("0"),
            sell_quantity=Decimal("1"),
            sell_price=Decimal("100"),
            fees=Decimal("0"),
        )


# --- Decimal precision -----------------------------------------------------


def test_buy_uses_decimal_throughout_no_float_drift():
    result = apply_buy(
        current_quantity=Decimal("3.33333333"),
        current_average_cost=Decimal("33.33"),
        purchase_quantity=Decimal("6.66666667"),
        purchase_price=Decimal("11.11"),
        fees=Decimal("0.01"),
    )
    assert isinstance(result.quantity, Decimal)
    assert isinstance(result.average_cost, Decimal)
    expected_cost_basis = (Decimal("3.33333333") * Decimal("33.33")) + (
        Decimal("6.66666667") * Decimal("11.11")
    ) + Decimal("0.01")
    expected_quantity = Decimal("3.33333333") + Decimal("6.66666667")
    assert result.quantity == expected_quantity
    assert result.average_cost == expected_cost_basis / expected_quantity


def test_sell_partial_average_cost_invariant_holds_exactly_with_fractional_quantities():
    result = apply_sell(
        current_quantity=Decimal("7.5"),
        current_average_cost=Decimal("13.333333"),
        sell_quantity=Decimal("2.5"),
        sell_price=Decimal("20"),
        fees=Decimal("0"),
    )
    assert result.quantity == Decimal("5")
    assert result.average_cost == Decimal("13.333333")
