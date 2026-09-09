"""Pure comparison between two historical portfolio-value totals.

This is a VALUE CHANGE utility, not an investment-return or P&L
calculation: it says nothing about deposits, withdrawals, or trades that
happened between the two points in time. Computing an actual return
requires cash-flow/transaction data, which this module deliberately does
not use (see FINANCIAL_RULES.md, "Snapshot != Transaction").
"""

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class ValueChange:
    before: Decimal
    after: Decimal
    absolute_change: Decimal
    percent_change: Decimal | None  # None when `before` is zero (mathematically undefined)


def compare_values(before: Decimal, after: Decimal) -> ValueChange:
    absolute_change = after - before
    percent_change = None if before == 0 else (absolute_change / before) * Decimal("100")
    return ValueChange(before=before, after=after, absolute_change=absolute_change, percent_change=percent_change)


def compare_snapshot_totals(
    before_items: dict[str, Decimal], after_items: dict[str, Decimal]
) -> dict[str, ValueChange]:
    """Per-symbol value change between two snapshots' item values, plus a
    "TOTAL" entry. A symbol present in only one snapshot is compared
    against an explicit 0 on the missing side (not fabricated data — a
    snapshot simply may not have valued that asset at that point)."""
    all_symbols = set(before_items) | set(after_items)
    changes = {
        symbol: compare_values(before_items.get(symbol, Decimal("0")), after_items.get(symbol, Decimal("0")))
        for symbol in all_symbols
    }
    total_before = sum(before_items.values(), Decimal("0"))
    total_after = sum(after_items.values(), Decimal("0"))
    changes["TOTAL"] = compare_values(total_before, total_after)
    return changes
