"""Pure Smart Inflow Allocator: recommends where NEW CASH should go among
eligible strategy buckets.

SMART INFLOW ALLOCATOR != REBALANCING ENGINE: this module only answers
"if I receive X EGP of new cash, where should it go?" — never "how
should existing holdings be sold to reach target?" It never sells, never
executes a trade, and never modifies holdings, targets, or configuration
(see FINANCIAL_RULES.md, "Smart Inflow Allocator Rules").

No I/O. Buckets/rules are passed in as plain values from the database —
this module never references a specific bucket name or asset symbol, so
it works unchanged for any set of assets/buckets a user configures.

Denominator treatment (Phase 7 approval, "Critical Question: New Cash and
Denominator"): target gaps and maximum capacities are computed against
the CURRENT investable portfolio value, as it was BEFORE the new cash
arrived. The incoming cash is never added to that denominator before
deciding where it goes — doing so would let the incoming cash inflate
(shrink) its own target gap. Post-inflow "projected" percentages are a
separate, clearly labeled calculation using a distinct denominator (the
current investable value plus whatever ends up actually allocated).

A maximum-only bucket (target_percent is None, e.g. "Individual Stocks"
with only a maximum) is treated purely as a constraint, never a
destination — no target is ever invented for it, even if it is well
under its maximum (see FINANCIAL_RULES.md).
"""

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from uuid import UUID


class InflowStatus(str, Enum):
    ELIGIBLE = "ELIGIBLE"
    TARGET_GAP = "TARGET_GAP"
    MAXIMUM_LIMIT = "MAXIMUM_LIMIT"
    BUY_DISABLED = "BUY_DISABLED"
    EMERGENCY_EXCLUDED = "EMERGENCY_EXCLUDED"
    NO_TARGET = "NO_TARGET"
    AT_TARGET = "AT_TARGET"
    OVER_TARGET = "OVER_TARGET"
    NO_CAPACITY = "NO_CAPACITY"


@dataclass(frozen=True)
class InflowCandidate:
    """One active strategy bucket's inflow-eligibility inputs. Callers
    must already have filtered to active rules and resolved
    is_emergency_excluded from portfolio_configs (never a bucket name).

    `allow_new_buy=None` means no allocation_targets rule exists for this
    bucket at all (as opposed to a rule that explicitly sets it False) —
    treated the same as a bucket with no target: NO_TARGET, since a
    bucket with no rule has no target_percent either.
    """

    strategy_bucket_id: UUID
    bucket_name: str
    current_value: Decimal
    target_percent: Decimal | None
    maximum_percent: Decimal | None
    allow_new_buy: bool | None
    priority: int
    is_emergency_excluded: bool = False


@dataclass(frozen=True)
class InflowRecommendation:
    strategy_bucket_id: UUID
    bucket_name: str
    current_value: Decimal
    current_percent: Decimal | None
    target_percent: Decimal | None
    maximum_percent: Decimal | None
    allow_new_buy: bool | None
    priority: int
    target_gap: Decimal | None
    maximum_capacity: Decimal | None
    eligible: bool
    allocated_amount: Decimal
    status: InflowStatus
    projected_value: Decimal | None
    projected_percent: Decimal | None


@dataclass(frozen=True)
class InflowAllocationResult:
    requested_cash: Decimal
    allocated_cash: Decimal
    unallocated_cash: Decimal
    recommendations: tuple[InflowRecommendation, ...]


def _percent_of(value: Decimal, denominator: Decimal) -> Decimal:
    if denominator <= 0:
        return Decimal("0")
    return (value / denominator) * Decimal("100")


def capacity_and_status(
    candidate: InflowCandidate, investable_portfolio_value: Decimal
) -> tuple[Decimal, InflowStatus]:
    """How much this bucket could theoretically absorb right now, and why
    (or why not) — before the greedy cash-distribution pass runs.

    Public (not `_`-prefixed) so a second caller can classify a bucket's
    eligibility/status independent of any actual cash amount to
    distribute — specifically `domain/rebalancing_engine.py`, which
    needs this exact classification even when there is currently zero
    available cash (a case `calculate_inflow_allocation` itself refuses
    via its `new_cash_amount > 0` guard, see below). Reused, not
    duplicated: this is the one place the gap/capacity formula is
    computed either way."""
    if candidate.is_emergency_excluded:
        return Decimal("0"), InflowStatus.EMERGENCY_EXCLUDED
    if investable_portfolio_value <= 0:
        return Decimal("0"), InflowStatus.NO_CAPACITY
    if candidate.target_percent is None:
        # Maximum-only buckets (no target_percent) are a constraint, not
        # a destination — never invent a target to fill them.
        return Decimal("0"), InflowStatus.NO_TARGET
    if candidate.allow_new_buy is False:
        return Decimal("0"), InflowStatus.BUY_DISABLED

    target_value = (candidate.target_percent / Decimal("100")) * investable_portfolio_value
    gap = target_value - candidate.current_value
    if gap == 0:
        return Decimal("0"), InflowStatus.AT_TARGET
    if gap < 0:
        return Decimal("0"), InflowStatus.OVER_TARGET

    if candidate.maximum_percent is not None:
        maximum_value = (candidate.maximum_percent / Decimal("100")) * investable_portfolio_value
        remaining_capacity = maximum_value - candidate.current_value
        if remaining_capacity <= 0:
            return Decimal("0"), InflowStatus.MAXIMUM_LIMIT
        if remaining_capacity < gap:
            return remaining_capacity, InflowStatus.MAXIMUM_LIMIT

    return gap, InflowStatus.TARGET_GAP


def calculate_inflow_allocation(
    *,
    new_cash_amount: Decimal,
    investable_portfolio_value: Decimal,
    candidates: list[InflowCandidate],
) -> InflowAllocationResult:
    """Deterministically distribute `new_cash_amount` across `candidates`.

    Never sells, never mutates its inputs, never forces full allocation:
    unallocated_cash is returned explicitly rather than fabricated into a
    destination. `requested_cash == allocated_cash + unallocated_cash`
    always holds exactly (Decimal arithmetic only).
    """
    if new_cash_amount <= 0:
        raise ValueError("new_cash_amount must be greater than 0")

    evaluated = []
    for candidate in candidates:
        capacity, status = capacity_and_status(candidate, investable_portfolio_value)

        # Diagnostic fields are computed independently of eligibility so a
        # future UI can explain *why* a disabled/excluded bucket still has
        # (or doesn't have) a gap — but never used to move money if the
        # bucket is disqualified.
        is_excluded_from_math = candidate.is_emergency_excluded
        current_percent = None if is_excluded_from_math else _percent_of(candidate.current_value, investable_portfolio_value)
        target_gap = None
        maximum_capacity = None
        if not is_excluded_from_math and candidate.target_percent is not None and investable_portfolio_value > 0:
            target_value = (candidate.target_percent / Decimal("100")) * investable_portfolio_value
            target_gap = target_value - candidate.current_value
        if not is_excluded_from_math and candidate.maximum_percent is not None and investable_portfolio_value > 0:
            maximum_value = (candidate.maximum_percent / Decimal("100")) * investable_portfolio_value
            maximum_capacity = maximum_value - candidate.current_value

        evaluated.append((candidate, capacity, status, current_percent, target_gap, maximum_capacity))

    # Deterministic order: configured priority ascending (lower number =
    # higher priority, matching allocation_targets.priority), then
    # bucket_name as a stable, data-driven tiebreaker — never a hardcoded
    # asset/bucket name comparison.
    ordered = sorted(
        (item for item in evaluated if item[1] > 0),
        key=lambda item: (item[0].priority, item[0].bucket_name),
    )

    remaining_cash = new_cash_amount
    allocated_by_bucket: dict[UUID, Decimal] = {}
    for candidate, capacity, *_ in ordered:
        if remaining_cash <= 0:
            break
        amount = min(capacity, remaining_cash)
        if amount > 0:
            allocated_by_bucket[candidate.strategy_bucket_id] = amount
            remaining_cash -= amount

    allocated_cash = new_cash_amount - remaining_cash
    projected_investable_total = investable_portfolio_value + allocated_cash

    recommendations = []
    for candidate, capacity, status, current_percent, target_gap, maximum_capacity in evaluated:
        allocated_amount = allocated_by_bucket.get(candidate.strategy_bucket_id, Decimal("0"))
        final_status = InflowStatus.ELIGIBLE if allocated_amount > 0 else status
        is_excluded_from_math = candidate.is_emergency_excluded
        projected_value = candidate.current_value + allocated_amount
        projected_percent = (
            None if is_excluded_from_math else _percent_of(projected_value, projected_investable_total)
        )
        recommendations.append(
            InflowRecommendation(
                strategy_bucket_id=candidate.strategy_bucket_id,
                bucket_name=candidate.bucket_name,
                current_value=candidate.current_value,
                current_percent=current_percent,
                target_percent=candidate.target_percent,
                maximum_percent=candidate.maximum_percent,
                allow_new_buy=candidate.allow_new_buy,
                priority=candidate.priority,
                target_gap=target_gap,
                maximum_capacity=maximum_capacity,
                eligible=capacity > 0,
                allocated_amount=allocated_amount,
                status=final_status,
                projected_value=projected_value,
                projected_percent=projected_percent,
            )
        )

    return InflowAllocationResult(
        requested_cash=new_cash_amount,
        allocated_cash=allocated_cash,
        unallocated_cash=remaining_cash,
        recommendations=tuple(recommendations),
    )
