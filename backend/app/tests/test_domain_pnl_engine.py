from decimal import Decimal

from app.domain.pnl_engine import HoldingPnL, calculate_holding_pnl, calculate_portfolio_pnl_totals


def test_exact_decimal_pnl_calculation():
    result = calculate_holding_pnl(
        quantity=Decimal("10"), average_cost=Decimal("50.25"), current_price=Decimal("60.75")
    )
    assert result.market_value == Decimal("607.50")
    assert result.cost_basis == Decimal("502.50")
    assert result.unrealized_pnl == Decimal("105.00")
    assert result.unrealized_pnl_percent == (Decimal("105.00") / Decimal("502.50")) * Decimal("100")


def test_missing_average_cost_returns_none_not_fabricated():
    result = calculate_holding_pnl(quantity=Decimal("10"), average_cost=None, current_price=Decimal("60"))
    assert result.cost_basis is None
    assert result.unrealized_pnl is None
    assert result.unrealized_pnl_percent is None
    assert result.market_value == Decimal("600")


def test_missing_current_price_returns_none_not_fabricated():
    result = calculate_holding_pnl(quantity=Decimal("10"), average_cost=Decimal("5"), current_price=None)
    assert result.market_value is None
    assert result.unrealized_pnl is None
    assert result.cost_basis == Decimal("50")


def test_missing_quantity_returns_none_not_fabricated():
    result = calculate_holding_pnl(quantity=None, average_cost=Decimal("5"), current_price=Decimal("10"))
    assert result.market_value is None
    assert result.cost_basis is None
    assert result.unrealized_pnl is None


def test_zero_cost_basis_does_not_crash_and_percent_is_none():
    result = calculate_holding_pnl(quantity=Decimal("10"), average_cost=Decimal("0"), current_price=Decimal("5"))
    assert result.cost_basis == Decimal("0")
    assert result.unrealized_pnl == Decimal("50")
    assert result.unrealized_pnl_percent is None


def test_zero_quantity_produces_zero_values_not_none():
    result = calculate_holding_pnl(quantity=Decimal("0"), average_cost=Decimal("10"), current_price=Decimal("20"))
    assert result.market_value == Decimal("0")
    assert result.cost_basis == Decimal("0")
    assert result.unrealized_pnl == Decimal("0")
    assert result.unrealized_pnl_percent is None


def test_negative_pnl_when_current_price_below_cost():
    result = calculate_holding_pnl(quantity=Decimal("10"), average_cost=Decimal("100"), current_price=Decimal("80"))
    assert result.unrealized_pnl == Decimal("-200")
    assert result.unrealized_pnl_percent == Decimal("-20")


# --- Portfolio-level P/L aggregation (Phase 9) ------------------------------


def test_portfolio_pnl_totals_sums_across_holdings():
    a = calculate_holding_pnl(quantity=Decimal("10"), average_cost=Decimal("50"), current_price=Decimal("60"))
    b = calculate_holding_pnl(quantity=Decimal("5"), average_cost=Decimal("100"), current_price=Decimal("90"))
    totals = calculate_portfolio_pnl_totals([a, b])
    assert totals.total_market_value == Decimal("600") + Decimal("450")
    assert totals.total_cost_basis == Decimal("500") + Decimal("500")
    assert totals.total_unrealized_pnl == Decimal("100") + Decimal("-50")
    assert totals.total_unrealized_pnl_percent == (Decimal("50") / Decimal("1000")) * Decimal("100")


def test_portfolio_pnl_totals_empty_list_is_zero_not_none():
    totals = calculate_portfolio_pnl_totals([])
    assert totals.total_market_value == Decimal("0")
    assert totals.total_cost_basis == Decimal("0")
    assert totals.total_unrealized_pnl == Decimal("0")
    assert totals.total_unrealized_pnl_percent is None


def test_portfolio_pnl_totals_zero_total_cost_basis_yields_none_percent():
    zero_cost = calculate_holding_pnl(quantity=Decimal("10"), average_cost=Decimal("0"), current_price=Decimal("5"))
    totals = calculate_portfolio_pnl_totals([zero_cost])
    assert totals.total_unrealized_pnl == Decimal("50")
    assert totals.total_unrealized_pnl_percent is None


def test_portfolio_pnl_totals_excludes_holdings_with_undefined_pnl_never_treats_as_zero():
    """A holding with a missing input (None market_value/cost_basis)
    must be excluded from the sums entirely, not silently counted as
    contributing 0 — see the function's docstring."""
    complete = calculate_holding_pnl(quantity=Decimal("10"), average_cost=Decimal("50"), current_price=Decimal("60"))
    incomplete = HoldingPnL(market_value=None, cost_basis=None, unrealized_pnl=None, unrealized_pnl_percent=None)
    totals = calculate_portfolio_pnl_totals([complete, incomplete])
    assert totals.total_market_value == Decimal("600")
    assert totals.total_cost_basis == Decimal("500")
    assert totals.total_unrealized_pnl == Decimal("100")
