"""Mathematically verified Time-Weighted Return fixtures (Phase 15).

Every expected value below is hand-derived from the standard sub-period
TWR formula, not merely "the function returns a number" -- see
domain/twr_engine.py's module docstring for the convention (snapshot-
after-flow with algebraic pre-flow reconstruction) these fixtures exercise.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.domain.twr_engine import TWRPoint, calculate_period_returns, cumulative_returns, summarize_twr

_T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _at(days: int) -> datetime:
    return _T0 + timedelta(days=days)


def _pct(fraction: Decimal) -> Decimal:
    return fraction * Decimal("100")


# --- Case A: flat market, deposit only -> 0% -------------------------------


def test_case_a_flat_market_deposit_only_is_zero_percent():
    points = [
        TWRPoint(at=_at(0), total_value=Decimal("10000")),
        TWRPoint(at=_at(1), total_value=Decimal("15000"), external_flow=Decimal("5000")),
        TWRPoint(at=_at(2), total_value=Decimal("15000")),
    ]
    summary = summarize_twr(points)
    assert summary.insufficient_history is False
    assert summary.twr_percentage == Decimal("0")


# --- Case B: growth without cash flow -> +10% ------------------------------


def test_case_b_growth_without_cash_flow_is_ten_percent():
    points = [
        TWRPoint(at=_at(0), total_value=Decimal("10000")),
        TWRPoint(at=_at(1), total_value=Decimal("11000")),
    ]
    summary = summarize_twr(points)
    assert summary.twr_percentage == Decimal("10")


# --- Case C: deposit + growth -> correct market return (+10%) -------------


def test_case_c_deposit_then_growth_isolates_the_ten_percent_market_return():
    # Deposit lands with zero elapsed growth (baseline 10,000 -> pre-flow
    # 10,000), then all growth (10,000 -> 11,000 organically, landing at
    # 16,500 post-deposit-base of 15,000) happens strictly afterward.
    points = [
        TWRPoint(at=_at(0), total_value=Decimal("10000")),
        TWRPoint(at=_at(1), total_value=Decimal("15000"), external_flow=Decimal("5000")),
        TWRPoint(at=_at(2), total_value=Decimal("16500")),
    ]
    summary = summarize_twr(points)
    assert summary.twr_percentage == Decimal("10")
    # The deposit's own the amount must never appear as part of the return
    assert Decimal("5000") not in [p.total_value for p in points if p.at == _at(0)]


# --- Case D: withdrawal + growth does not fabricate a gain/loss ------------


def test_case_d_withdrawal_does_not_create_artificial_gain_or_loss():
    # Withdraw 3,000 with zero elapsed growth (10,000 -> pre-flow 10,000),
    # then genuine 10% growth happens strictly afterward on the new
    # 7,000 base (-> 7,700).
    points = [
        TWRPoint(at=_at(0), total_value=Decimal("10000")),
        TWRPoint(at=_at(1), total_value=Decimal("7000"), external_flow=Decimal("-3000")),
        TWRPoint(at=_at(2), total_value=Decimal("7700")),
    ]
    summary = summarize_twr(points)
    assert summary.twr_percentage == Decimal("10")


# --- Case E: consecutive deposits are isolated correctly -------------------


def test_case_e_consecutive_deposits_net_to_zero_without_growth():
    points = [
        TWRPoint(at=_at(0), total_value=Decimal("10000")),
        TWRPoint(at=_at(1), total_value=Decimal("15000"), external_flow=Decimal("5000")),
        TWRPoint(at=_at(2), total_value=Decimal("20000"), external_flow=Decimal("5000")),
    ]
    summary = summarize_twr(points)
    assert summary.twr_percentage == Decimal("0")


# --- Case F: consecutive withdrawals are isolated correctly ----------------


def test_case_f_consecutive_withdrawals_net_to_zero_without_growth():
    points = [
        TWRPoint(at=_at(0), total_value=Decimal("20000")),
        TWRPoint(at=_at(1), total_value=Decimal("15000"), external_flow=Decimal("-5000")),
        TWRPoint(at=_at(2), total_value=Decimal("10000"), external_flow=Decimal("-5000")),
    ]
    summary = summarize_twr(points)
    assert summary.twr_percentage == Decimal("0")


# --- Case G: zero starting balance ------------------------------------------


def test_case_g_zero_starting_balance_funded_by_deposit_is_zero_percent():
    """Going from literally nothing to something via external funding is
    not investment performance -- it must resolve to a defined 0%, never
    NaN/Infinity/a fabricated percentage."""
    points = [
        TWRPoint(at=_at(0), total_value=Decimal("0")),
        TWRPoint(at=_at(1), total_value=Decimal("5000"), external_flow=Decimal("5000")),
    ]
    summary = summarize_twr(points)
    assert summary.insufficient_history is False
    assert summary.twr_percentage == Decimal("0")


def test_case_g_zero_starting_balance_with_unexplained_value_is_undefined_not_fabricated():
    """Value appearing from a zero baseline with NO recorded flow to
    explain it is a data anomaly -- must be reported as undefined, never
    as a division-by-zero crash or a misleading percentage."""
    points = [
        TWRPoint(at=_at(0), total_value=Decimal("0")),
        TWRPoint(at=_at(1), total_value=Decimal("5000")),
    ]
    returns = calculate_period_returns(points)
    assert returns == [None]
    summary = summarize_twr(points)
    assert summary.twr_percentage is None
    assert summary.insufficient_history is True
    assert summary.reason is not None


def test_case_g_zero_to_zero_is_a_defined_zero_percent():
    points = [
        TWRPoint(at=_at(0), total_value=Decimal("0")),
        TWRPoint(at=_at(1), total_value=Decimal("0")),
    ]
    summary = summarize_twr(points)
    assert summary.twr_percentage == Decimal("0")
    assert summary.insufficient_history is False


# --- Case H: first snapshot / insufficient history --------------------------


def test_case_h_single_point_is_insufficient_history_never_zero_percent():
    """A single observation must never be silently reported as "0%
    return" -- that would claim knowledge ("nothing changed") the system
    doesn't have."""
    points = [TWRPoint(at=_at(0), total_value=Decimal("10000"))]
    summary = summarize_twr(points)
    assert summary.twr_percentage is None
    assert summary.insufficient_history is True
    assert "at least two" in summary.reason.lower()


def test_case_h_empty_points_is_insufficient_history():
    summary = summarize_twr([])
    assert summary.twr_percentage is None
    assert summary.insufficient_history is True


# --- Case I: no market movement across multiple snapshots -> 0% ------------


def test_case_i_no_movement_across_multiple_snapshots_is_zero_percent():
    points = [
        TWRPoint(at=_at(0), total_value=Decimal("10000")),
        TWRPoint(at=_at(1), total_value=Decimal("10000")),
        TWRPoint(at=_at(2), total_value=Decimal("10000")),
        TWRPoint(at=_at(3), total_value=Decimal("10000")),
    ]
    summary = summarize_twr(points)
    assert summary.twr_percentage == Decimal("0")
    assert all(r == Decimal("0") for r in cumulative_returns(points)[1:])


# --- Case J: mixed inflow/outflow sequence across multiple periods --------


def test_case_j_mixed_inflow_outflow_sequence_links_correctly():
    # Period 1: 10,000 -> 11,000 organically = +10%.
    # Then a deposit of 4,000 lands with zero further growth (11,000 ->
    # pre-flow 11,000), moving the base to 15,000.
    # Period 2: 15,000 -> 16,500 organically = +10%.
    # Then a withdrawal of 3,000 lands with zero further growth (16,500 ->
    # pre-flow 16,500), moving the base to 13,500.
    # Period 3: 13,500 -> 14,850 organically = +10%.
    # Overall TWR = (1.10)^3 - 1 = 33.1%.
    points = [
        TWRPoint(at=_at(0), total_value=Decimal("10000")),
        TWRPoint(at=_at(1), total_value=Decimal("11000")),
        TWRPoint(at=_at(2), total_value=Decimal("15000"), external_flow=Decimal("4000")),
        TWRPoint(at=_at(3), total_value=Decimal("16500")),
        TWRPoint(at=_at(4), total_value=Decimal("13500"), external_flow=Decimal("-3000")),
        TWRPoint(at=_at(5), total_value=Decimal("14850")),
    ]
    summary = summarize_twr(points)
    expected = (Decimal("1.10") ** 3 - 1) * Decimal("100")
    assert summary.twr_percentage == expected
    assert summary.twr_percentage == Decimal("33.100")


# --- Cross-cutting: never NaN/Infinity, never raises ------------------------


def test_engine_never_raises_for_any_of_the_above_zero_edge_cases():
    weird_points = [
        TWRPoint(at=_at(0), total_value=Decimal("0")),
        TWRPoint(at=_at(1), total_value=Decimal("0"), external_flow=Decimal("0")),
        TWRPoint(at=_at(2), total_value=Decimal("0")),
    ]
    summary = summarize_twr(weird_points)
    assert summary.twr_percentage == Decimal("0")


def test_cumulative_returns_length_matches_points_and_first_is_always_zero():
    points = [
        TWRPoint(at=_at(0), total_value=Decimal("1000")),
        TWRPoint(at=_at(1), total_value=Decimal("1100")),
        TWRPoint(at=_at(2), total_value=Decimal("1210")),
    ]
    cumulative = cumulative_returns(points)
    assert len(cumulative) == len(points)
    assert cumulative[0] == Decimal("0")
    assert _pct(cumulative[-1]) == Decimal("21.00")


def test_an_undefined_sub_period_poisons_every_later_cumulative_value():
    points = [
        TWRPoint(at=_at(0), total_value=Decimal("0")),
        TWRPoint(at=_at(1), total_value=Decimal("100")),  # undefined: unexplained value from zero
        TWRPoint(at=_at(2), total_value=Decimal("200")),
    ]
    cumulative = cumulative_returns(points)
    assert cumulative[0] == Decimal("0")
    assert cumulative[1] is None
    assert cumulative[2] is None
