from decimal import Decimal
from uuid import uuid4

from app.domain.strategy_validation import (
    AllocationRuleInput,
    StrategyValidationStatus,
    validate_strategy,
)


def rule(target, *, maximum=None, minimum=None, allow_new_buy=True, priority=0, is_emerg=False, name="Bucket"):
    return AllocationRuleInput(
        strategy_bucket_id=uuid4(),
        bucket_name=name,
        target_percent=target,
        minimum_percent=minimum,
        maximum_percent=maximum,
        allow_new_buy=allow_new_buy,
        priority=priority,
        is_emergency_excluded=is_emerg,
    )


def test_targets_totaling_exactly_100_percent_is_valid():
    rules = [rule(Decimal("60"), name="A"), rule(Decimal("40"), name="B")]
    result = validate_strategy(rules)
    assert result.status == StrategyValidationStatus.VALID
    assert result.is_valid is True
    assert result.total_target_percent == Decimal("100")


def test_current_seeded_configuration_totals_85_percent_and_is_incomplete():
    """The exact seeded strategy: BWA=55, AZN=25, Free Cash=5, Gold=0,
    Individual Stocks maximum=15 (no target). Must report 85%,
    INCOMPLETE_TARGET_ALLOCATION — never silently treated as 100%, and
    the 15% maximum must never be added to the sum."""
    rules = [
        rule(Decimal("55"), name="Growth / Investment Funds", priority=1),
        rule(Decimal("25"), name="Defensive / Fixed Income", priority=2),
        rule(None, maximum=Decimal("15"), name="Individual Stocks", priority=3),
        rule(Decimal("0"), allow_new_buy=False, name="Gold", priority=4),
        rule(Decimal("5"), name="Free Cash", priority=5),
    ]
    result = validate_strategy(rules)

    assert result.total_target_percent == Decimal("85")
    assert result.status == StrategyValidationStatus.INCOMPLETE_TARGET_ALLOCATION
    assert result.is_valid is False
    assert {r.bucket_name for r in result.maximum_only_rows} == {"Individual Stocks"}
    assert {r.bucket_name for r in result.target_rows} == {
        "Growth / Investment Funds",
        "Defensive / Fixed Income",
        "Gold",
        "Free Cash",
    }


def test_targets_totaling_105_percent_is_overallocated():
    rules = [rule(Decimal("60"), name="A"), rule(Decimal("45"), name="B")]
    result = validate_strategy(rules)
    assert result.status == StrategyValidationStatus.OVERALLOCATED_TARGET_ALLOCATION
    assert result.total_target_percent == Decimal("105")
    assert result.is_valid is False


def test_maximum_only_row_does_not_contribute_to_target_total():
    rules = [rule(Decimal("100"), name="A"), rule(None, maximum=Decimal("15"), name="MaxOnly")]
    result = validate_strategy(rules)
    assert result.total_target_percent == Decimal("100")
    assert result.status == StrategyValidationStatus.VALID


def test_null_target_does_not_contribute():
    rules = [rule(Decimal("100"), name="A"), rule(None, name="NoTarget")]
    result = validate_strategy(rules)
    assert result.total_target_percent == Decimal("100")


def test_zero_target_contributes_zero_not_ignored():
    rules = [rule(Decimal("100"), name="A"), rule(Decimal("0"), name="ZeroTarget")]
    result = validate_strategy(rules)
    assert result.total_target_percent == Decimal("100")
    # The zero-target bucket is still a target row (it has a real
    # target_percent value of 0, distinct from a maximum-only rule).
    assert any(r.bucket_name == "ZeroTarget" for r in result.target_rows)
    assert not any(r.bucket_name == "ZeroTarget" for r in result.maximum_only_rows)


def test_no_rules_at_all_is_empty_configuration():
    result = validate_strategy([])
    assert result.status == StrategyValidationStatus.EMPTY_CONFIGURATION
    assert result.is_valid is False
    assert result.total_target_percent == Decimal("0")


def test_emergency_excluded_rule_does_not_participate_in_validation():
    rules = [
        rule(Decimal("100"), name="A"),
        rule(Decimal("9999"), name="Emergency Cash", is_emerg=True),  # would break everything if counted
    ]
    result = validate_strategy(rules)
    assert result.status == StrategyValidationStatus.VALID
    assert result.total_target_percent == Decimal("100")
    assert {r.bucket_name for r in result.excluded_emergency_rows} == {"Emergency Cash"}


def test_minimum_greater_than_maximum_is_invalid():
    rules = [rule(Decimal("50"), minimum=Decimal("60"), maximum=Decimal("40"), name="Bad")]
    result = validate_strategy(rules)
    assert result.status == StrategyValidationStatus.INVALID_MIN_MAX_CONFIGURATION
    assert result.is_valid is False
    assert len(result.field_errors) == 1
    assert result.field_errors[0].bucket_name == "Bad"


def test_target_percent_out_of_range_is_invalid():
    rules = [rule(Decimal("150"), name="TooHigh")]
    result = validate_strategy(rules)
    assert result.status == StrategyValidationStatus.INVALID_TARGET_VALUE
    assert result.is_valid is False


def test_negative_percent_is_invalid():
    rules = [rule(Decimal("-5"), name="Negative")]
    result = validate_strategy(rules)
    assert result.status == StrategyValidationStatus.INVALID_TARGET_VALUE


def test_decimal_precision_is_exact_not_float_rounded():
    rules = [rule(Decimal("33.33"), name="A"), rule(Decimal("33.33"), name="B"), rule(Decimal("33.34"), name="C")]
    result = validate_strategy(rules)
    assert result.total_target_percent == Decimal("100.00")
    assert result.status == StrategyValidationStatus.VALID


def test_changing_maximum_never_changes_target_sum():
    base = [rule(Decimal("60"), name="A"), rule(None, maximum=Decimal("15"), name="B")]
    changed = [rule(Decimal("60"), name="A"), rule(None, maximum=Decimal("40"), name="B")]
    assert validate_strategy(base).total_target_percent == validate_strategy(changed).total_target_percent


def test_changing_allow_new_buy_never_changes_target_sum():
    base = [rule(Decimal("60"), name="A", allow_new_buy=True), rule(Decimal("40"), name="B", allow_new_buy=True)]
    changed = [rule(Decimal("60"), name="A", allow_new_buy=False), rule(Decimal("40"), name="B", allow_new_buy=False)]
    assert validate_strategy(base).total_target_percent == validate_strategy(changed).total_target_percent
    assert validate_strategy(base).status == validate_strategy(changed).status


def test_priority_order_is_preserved_and_sorted():
    rules = [
        rule(Decimal("10"), name="Third", priority=3),
        rule(Decimal("10"), name="First", priority=1),
        rule(Decimal("10"), name="Second", priority=2),
    ]
    result = validate_strategy(rules)
    assert [r.bucket_name for r in result.priority_order] == ["First", "Second", "Third"]


def test_engine_never_mutates_input_rules_or_invents_a_value():
    """No auto-correction: the result carries the same target_percent
    values it was given — nothing is adjusted to force a VALID status."""
    rules = [rule(Decimal("55"), name="A"), rule(None, maximum=Decimal("15"), name="B")]
    result = validate_strategy(rules)
    assert result.status != StrategyValidationStatus.VALID
    # The maximum-only bucket's target_percent is still None — never
    # rewritten to 15 or any other value to "fix" the total.
    max_only = next(r for r in result.maximum_only_rows if r.bucket_name == "B")
    assert max_only.target_percent is None
