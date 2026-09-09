from datetime import date, timedelta
from decimal import Decimal

from app.domain.alert_engine import (
    AlertType,
    check_allocation_breach,
    check_dip_buy,
    check_income_maturity,
    check_price_target,
    check_rebalance_suggestion,
)
from app.domain.allocation_engine import MaximumStatus, TargetStatus


# --- Allocation breach --------------------------------------------------


def test_allocation_breach_not_configured_never_triggers():
    result = check_allocation_breach(
        allocation_max_percent=None, risk_allocation_percent=Decimal("50"), previously_triggered=False
    )
    assert result.condition_met is False
    assert result.is_new_trigger is False
    assert result.should_clear is False


def test_allocation_breach_undefined_risk_percent_never_triggers():
    """A bucket excluded from risk allocation (e.g. the emergency bucket)
    reports risk_allocation_percent=None — never fabricated into 0 or a
    misleading number."""
    result = check_allocation_breach(
        allocation_max_percent=Decimal("20"), risk_allocation_percent=None, previously_triggered=False
    )
    assert result.condition_met is False
    assert result.is_new_trigger is False


def test_allocation_breach_below_threshold_does_not_trigger():
    result = check_allocation_breach(
        allocation_max_percent=Decimal("20"), risk_allocation_percent=Decimal("15"), previously_triggered=False
    )
    assert result.condition_met is False
    assert result.is_new_trigger is False


def test_allocation_breach_at_threshold_is_a_new_trigger():
    result = check_allocation_breach(
        allocation_max_percent=Decimal("20"), risk_allocation_percent=Decimal("20"), previously_triggered=False
    )
    assert result.condition_met is True
    assert result.is_new_trigger is True
    assert result.should_clear is False


def test_allocation_breach_above_threshold_continuation_is_not_a_new_trigger():
    result = check_allocation_breach(
        allocation_max_percent=Decimal("20"), risk_allocation_percent=Decimal("25"), previously_triggered=True
    )
    assert result.condition_met is True
    assert result.is_new_trigger is False
    assert result.should_clear is False


def test_allocation_breach_clears_when_it_drops_back_below_threshold():
    result = check_allocation_breach(
        allocation_max_percent=Decimal("20"), risk_allocation_percent=Decimal("10"), previously_triggered=True
    )
    assert result.condition_met is False
    assert result.is_new_trigger is False
    assert result.should_clear is True


# --- Price target --------------------------------------------------------


def test_price_target_not_configured_never_triggers():
    result = check_price_target(price_target=None, current_price=Decimal("100"), previously_triggered=False)
    assert result.condition_met is False


def test_price_target_unknown_current_price_never_triggers():
    result = check_price_target(price_target=Decimal("100"), current_price=None, previously_triggered=False)
    assert result.condition_met is False
    assert result.is_new_trigger is False


def test_price_target_not_reached_does_not_trigger():
    result = check_price_target(price_target=Decimal("100"), current_price=Decimal("90"), previously_triggered=False)
    assert result.condition_met is False


def test_price_target_reached_is_a_new_trigger():
    result = check_price_target(price_target=Decimal("100"), current_price=Decimal("100"), previously_triggered=False)
    assert result.condition_met is True
    assert result.is_new_trigger is True


def test_price_target_reached_continuation_is_not_a_new_trigger():
    result = check_price_target(price_target=Decimal("100"), current_price=Decimal("110"), previously_triggered=True)
    assert result.condition_met is True
    assert result.is_new_trigger is False


def test_price_target_clears_when_price_falls_back_below():
    result = check_price_target(price_target=Decimal("100"), current_price=Decimal("95"), previously_triggered=True)
    assert result.condition_met is False
    assert result.should_clear is True


# --- Dip buy ---------------------------------------------------------------


def test_dip_buy_not_configured_never_triggers():
    result = check_dip_buy(dip_buy_price=None, current_price=Decimal("50"), previously_triggered=False)
    assert result.condition_met is False


def test_dip_buy_unknown_current_price_never_triggers():
    result = check_dip_buy(dip_buy_price=Decimal("50"), current_price=None, previously_triggered=False)
    assert result.condition_met is False


def test_dip_buy_not_reached_does_not_trigger():
    result = check_dip_buy(dip_buy_price=Decimal("50"), current_price=Decimal("60"), previously_triggered=False)
    assert result.condition_met is False


def test_dip_buy_reached_is_a_new_trigger():
    result = check_dip_buy(dip_buy_price=Decimal("50"), current_price=Decimal("50"), previously_triggered=False)
    assert result.condition_met is True
    assert result.is_new_trigger is True


def test_dip_buy_below_dip_level_continuation_is_not_a_new_trigger():
    result = check_dip_buy(dip_buy_price=Decimal("50"), current_price=Decimal("40"), previously_triggered=True)
    assert result.condition_met is True
    assert result.is_new_trigger is False


def test_dip_buy_clears_when_price_recovers_above_dip_level():
    result = check_dip_buy(dip_buy_price=Decimal("50"), current_price=Decimal("55"), previously_triggered=True)
    assert result.condition_met is False
    assert result.should_clear is True


# --- Rebalance suggestion ---------------------------------------------------


def test_rebalance_suggestion_no_bucket_data_never_triggers():
    result = check_rebalance_suggestion(
        bucket_name=None, maximum_status=None, target_status=None, previously_triggered=False
    )
    assert result.condition_met is False


def test_rebalance_suggestion_within_bounds_does_not_trigger():
    result = check_rebalance_suggestion(
        bucket_name="Growth",
        maximum_status=MaximumStatus.WITHIN_MAXIMUM.value,
        target_status=TargetStatus.ON_TARGET.value,
        previously_triggered=False,
    )
    assert result.condition_met is False


def test_rebalance_suggestion_triggers_on_maximum_breach():
    result = check_rebalance_suggestion(
        bucket_name="Individual Stocks",
        maximum_status=MaximumStatus.MAXIMUM_BREACHED.value,
        target_status=TargetStatus.NO_TARGET.value,
        previously_triggered=False,
    )
    assert result.condition_met is True
    assert result.is_new_trigger is True
    assert result.alert_type == AlertType.REBALANCE_SUGGESTED


def test_rebalance_suggestion_triggers_on_overweight_target():
    result = check_rebalance_suggestion(
        bucket_name="Growth",
        maximum_status=MaximumStatus.NO_MAXIMUM.value,
        target_status=TargetStatus.OVERWEIGHT.value,
        previously_triggered=False,
    )
    assert result.condition_met is True
    assert result.is_new_trigger is True


def test_rebalance_suggestion_is_a_suggestion_only_no_trade_fields():
    """A suggestion is NOT an automatic trade: the result must carry no
    field that could represent a sell/buy/transaction."""
    result = check_rebalance_suggestion(
        bucket_name="Individual Stocks",
        maximum_status=MaximumStatus.MAXIMUM_BREACHED.value,
        target_status=TargetStatus.NO_TARGET.value,
        previously_triggered=False,
    )
    assert not hasattr(result, "transaction_id")
    assert not hasattr(result, "sell_amount")
    assert not hasattr(result, "buy_amount")


def test_rebalance_suggestion_clears_when_back_within_bounds():
    result = check_rebalance_suggestion(
        bucket_name="Growth",
        maximum_status=MaximumStatus.WITHIN_MAXIMUM.value,
        target_status=TargetStatus.ON_TARGET.value,
        previously_triggered=True,
    )
    assert result.condition_met is False
    assert result.should_clear is True


# --- Income maturity (prepared, standalone) --------------------------------


def test_income_maturity_not_configured_never_triggers():
    result = check_income_maturity(
        maturity_date=None, reference_date=date(2026, 1, 1), lookahead_days=7, previously_triggered=False
    )
    assert result.condition_met is False


def test_income_maturity_not_yet_due_does_not_trigger():
    result = check_income_maturity(
        maturity_date=date(2026, 2, 1), reference_date=date(2026, 1, 1), lookahead_days=7, previously_triggered=False
    )
    assert result.condition_met is False


def test_income_maturity_approaching_within_lookahead_is_a_new_trigger():
    result = check_income_maturity(
        maturity_date=date(2026, 1, 5), reference_date=date(2026, 1, 1), lookahead_days=7, previously_triggered=False
    )
    assert result.condition_met is True
    assert result.is_new_trigger is True


def test_income_maturity_reached_exactly_on_due_date_triggers():
    result = check_income_maturity(
        maturity_date=date(2026, 1, 1), reference_date=date(2026, 1, 1), lookahead_days=7, previously_triggered=False
    )
    assert result.condition_met is True


def test_income_maturity_overdue_still_triggers_and_reports_days_ago():
    result = check_income_maturity(
        maturity_date=date(2025, 12, 20), reference_date=date(2026, 1, 1), lookahead_days=7, previously_triggered=True
    )
    assert result.condition_met is True
    assert result.is_new_trigger is False
    assert "ago" in result.reason


def test_income_maturity_clears_when_pushed_out_beyond_lookahead():
    """A maturity date moved further out (e.g. edited) re-arms the alert
    for a later trigger, rather than leaving it permanently triggered."""
    result = check_income_maturity(
        maturity_date=date(2026, 3, 1), reference_date=date(2026, 1, 1), lookahead_days=7, previously_triggered=True
    )
    assert result.condition_met is False
    assert result.should_clear is True


# --- Decimal-only comparisons ------------------------------------------------


def test_all_numeric_comparisons_use_decimal_not_float():
    result = check_price_target(
        price_target=Decimal("123.45"), current_price=Decimal("123.45"), previously_triggered=False
    )
    assert isinstance(result.current_value, Decimal)
    assert isinstance(result.threshold_value, Decimal)
    assert not isinstance(result.current_value, float)
