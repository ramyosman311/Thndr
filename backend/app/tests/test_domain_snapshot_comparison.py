from decimal import Decimal

from app.domain.snapshot_comparison import ValueChange, compare_snapshot_totals, compare_values


def test_compare_values_absolute_and_percent_change():
    change = compare_values(Decimal("1000"), Decimal("1100"))
    assert change.absolute_change == Decimal("100")
    assert change.percent_change == Decimal("10")


def test_compare_values_zero_before_gives_none_percent_not_crash():
    change = compare_values(Decimal("0"), Decimal("500"))
    assert change.absolute_change == Decimal("500")
    assert change.percent_change is None


def test_compare_values_negative_change():
    change = compare_values(Decimal("1000"), Decimal("900"))
    assert change.absolute_change == Decimal("-100")
    assert change.percent_change == Decimal("-10")


def test_snapshot_comparison_matches_seeded_snapshot_1_and_2_bwa_change():
    # Real values from the Phase 4 seed: Snapshot 1 BWA=4983, Snapshot 2 BWA=5045.
    before = {"BWA": Decimal("4983"), "AZN": Decimal("1042")}
    after = {"BWA": Decimal("5045"), "AZN": Decimal("1042")}
    changes = compare_snapshot_totals(before, after)

    assert changes["BWA"].absolute_change == Decimal("62")
    assert changes["AZN"].absolute_change == Decimal("0")
    assert changes["TOTAL"].absolute_change == Decimal("62")


def test_snapshot_comparison_is_a_value_change_never_a_transaction_or_pnl():
    """ValueChange carries only before/after/absolute/percent — by
    construction it cannot be mistaken for a transaction record or a P/L
    figure, since neither concept has a field here at all."""
    before = {"BWA": Decimal("100")}
    after = {"BWA": Decimal("150")}
    changes = compare_snapshot_totals(before, after)

    field_names = {f for f in vars(ValueChange).get("__dataclass_fields__", {})}
    assert field_names == {"before", "after", "absolute_change", "percent_change"}
    assert not hasattr(changes["BWA"], "transaction_id")
    assert not hasattr(changes["BWA"], "transaction_type")
    assert not hasattr(changes["BWA"], "unrealized_pnl")
    assert not hasattr(changes["BWA"], "quantity")


def test_snapshot_comparison_handles_asset_present_in_only_one_snapshot():
    before = {"BWA": Decimal("100")}
    after = {"BWA": Decimal("100"), "NEWASSET": Decimal("50")}
    changes = compare_snapshot_totals(before, after)

    assert changes["NEWASSET"].before == Decimal("0")
    assert changes["NEWASSET"].after == Decimal("50")
    assert changes["TOTAL"].absolute_change == Decimal("50")
