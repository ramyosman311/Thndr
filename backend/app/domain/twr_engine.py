"""Time-Weighted Return (TWR) -- pure domain calculation (Phase 15).

No I/O, no database session -- everything here is a plain function/
dataclass over Decimal values, independently testable (see
ARCHITECTURE.md, "Backend Layering").

THE CORE PRINCIPLE: external cash flows (deposits/withdrawals) must never
be counted as investment return (see FINANCIAL_RULES.md, "Cash Flow Is
Not Profit"). This module implements that via the approved "snapshot-
after-flow with algebraic pre-flow reconstruction" convention (see
DECISIONS.md, "Phase 15 TWR Convention"):

Each `TWRPoint` is one historical portfolio-value observation, optionally
carrying the signed external flow that landed at that exact instant
(positive for a deposit, negative for a withdrawal, zero for an EOD point
with no flow). For a point with a flow, the value observed IS the
post-flow value -- the pre-flow value is reconstructed algebraically as
`pre_flow_value = point.total_value - point.external_flow`, which is
exact (not an assumption) precisely because the flow is defined to be the
ONLY thing that changed between "just before" and "just after" the same
instant.

The return for the sub-period ending at a point is then measured against
this reconstructed pre-flow value, never the raw post-flow value -- so a
deposit contributes exactly 0% to that sub-period's return by
construction, and the deposit amount becomes the new baseline for
whatever comes next. This is standard sub-period TWR; no cash-flow-timing
assumption beyond "the caller supplies flows at the exact instant they
were recorded" is required (see repositories/snapshot_repository.py's
deterministic ordering, which is exactly this input in practice).

Callers are responsible for supplying `points` already in the exact
chronological order to treat as authoritative -- this module NEVER
re-sorts (sorting by `at` alone cannot correctly break a tie two points
share; the caller's own deterministic tiebreak, e.g.
(snapshot_at, created_at, id), already resolved that -- see
repositories/snapshot_repository.py).
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass(frozen=True)
class TWRPoint:
    at: datetime
    total_value: Decimal
    # Signed external flow landing at this exact point: positive for a
    # deposit, negative for a withdrawal, zero (default) for a point with
    # no flow (e.g. an EOD observation). Ignored for points[0] -- there is
    # no prior period for the very first point to measure.
    external_flow: Decimal = Decimal("0")


def calculate_period_returns(points: list[TWRPoint]) -> list[Decimal | None]:
    """One return FRACTION (not a percentage) per sub-period, aligned to
    `points[1:]` -- `len(points) - 1` entries total.

    `None` marks an undefined sub-period: the baseline (the prior point's
    value) was exactly zero, and the reconstructed pre-flow value at the
    end of this sub-period was NOT also zero with no recorded flow to
    explain the difference -- i.e. portfolio value appears to have
    materialized from nothing. This is never coerced to 0% (which would
    misleadingly claim "no return" when the truth is "undefined") and
    never raised as an exception (a single bad boundary should not crash
    the whole series) -- see `cumulative_returns` for how this propagates.

    Case: baseline == 0 and the reconstructed pre-flow value is ALSO 0 --
    this is well-defined (0% -- nothing to grow from nothing) and returns
    Decimal("0"), not None.
    """
    returns: list[Decimal | None] = []
    if not points:
        return returns
    baseline = points[0].total_value
    for point in points[1:]:
        pre_flow_value = point.total_value - point.external_flow
        if baseline == 0:
            returns.append(Decimal("0") if pre_flow_value == 0 else None)
        else:
            returns.append((pre_flow_value - baseline) / baseline)
        baseline = point.total_value
    return returns


def cumulative_returns(points: list[TWRPoint]) -> list[Decimal | None]:
    """Linked (geometrically chained) cumulative return FRACTION as of
    each point, aligned 1:1 with `points` -- `points[0]` is always
    Decimal("0") (the baseline has no return relative to itself yet).

    Once an undefined sub-period occurs (see `calculate_period_returns`),
    every following entry is also `None` -- an undefined leg poisons every
    later cumulative value that would otherwise chain through it. This is
    never silently treated as if the undefined leg contributed 0%, which
    would understate/fabricate a result from a genuinely unknown gap.
    """
    if not points:
        return []
    result: list[Decimal | None] = [Decimal("0")]
    running = Decimal("1")
    poisoned = False
    for period_return in calculate_period_returns(points):
        if period_return is None:
            poisoned = True
        if poisoned:
            result.append(None)
        else:
            running *= Decimal("1") + period_return
            result.append(running - Decimal("1"))
    return result


@dataclass(frozen=True)
class TWRSummary:
    # A percentage (already *100, e.g. Decimal("4.82") means 4.82%) --
    # matches this codebase's existing percentage convention (see
    # domain/pnl_engine.py). None exactly when insufficient_history is
    # True, or when the whole chain resolves to undefined (see
    # `cumulative_returns`) -- never a fabricated 0% standing in for "we
    # don't know".
    twr_percentage: Decimal | None
    insufficient_history: bool
    reason: str | None


def summarize_twr(points: list[TWRPoint]) -> TWRSummary:
    """The single headline TWR percentage across the entire given range
    (first point to last). Never raises, never returns NaN/Infinity --
    see module docstring and `calculate_period_returns` for how an
    undefined boundary is represented instead."""
    if len(points) < 2:
        return TWRSummary(
            twr_percentage=None,
            insufficient_history=True,
            reason="At least two historical observations are required to compute a return.",
        )
    final = cumulative_returns(points)[-1]
    if final is None:
        return TWRSummary(
            twr_percentage=None,
            insufficient_history=True,
            reason=(
                "A sub-period started from a zero portfolio value that cannot be "
                "reconciled with a later non-zero value without a recorded external "
                "flow -- return is undefined for this range."
            ),
        )
    return TWRSummary(twr_percentage=final * Decimal("100"), insufficient_history=False, reason=None)
