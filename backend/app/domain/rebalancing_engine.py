"""Pure Smart Rebalancing Engine (Phase 17): combines already-computed
allocation status (`domain/allocation_engine.py`) with the already-
computed cash-distribution logic (`domain/inflow_allocator.py`) into a
single set of per-category recommendations.

No I/O, and — critically — no new financial math beyond what those two
modules already established:

- Target/Maximum classification (`TargetStatus`/`MaximumStatus`,
  `MAXIMUM_BREACHED` in particular) is read directly from an already-
  evaluated `allocation_engine.BucketAllocation` — never re-derived here,
  so a maximum breach can never disagree between the Distribution screen
  and this engine (see FINANCIAL_RULES.md, "Portfolio Aggregation
  Consistency").
- BUY capacity/distribution across competing categories (target gap,
  maximum-capped capacity, `allow_new_buy`, emergency exclusion,
  priority-ordered greedy allocation so the same cash is never handed to
  two categories) is `domain/inflow_allocator.calculate_inflow_allocation`
  — the exact same function the Smart Inflow Allocator (Phase 7) uses,
  just fed the portfolio's own idle `available_cash` (Phase 16) instead
  of newly-deposited cash. See that module's docstring for why this is
  a deliberate reuse, not a coincidence: "if I have X cash right now,
  where should it go" is exactly this phase's BUY question too.

The one genuinely NEW calculation this phase adds is the REDUCE amount
for a category already in maximum breach (section 9 of the approved
spec): `required_reduction = actual_value - maximum_value`. A breached
category is never also considered for a BUY (see `calculate_rebalancing`
below) — "maximum has priority over target" (FINANCIAL_RULES.md).

This module never sells, never buys, never mutates anything — see
FINANCIAL_RULES.md, "Rebalancing Engine Rules": recommend, never
execute.
"""

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from uuid import UUID

from app.domain.allocation_engine import MaximumStatus, TargetStatus
from app.domain.inflow_allocator import (
    InflowCandidate,
    InflowStatus,
    calculate_inflow_allocation,
    capacity_and_status,
)


class RebalancingAction(str, Enum):
    """The actionable verb for one category — deliberately a NEW, small
    enum distinct from `TargetStatus`/`MaximumStatus`/`InflowStatus`
    (none of which alone says "what to actually consider doing"), per
    the approved spec's explicit instruction not to duplicate an
    existing enum where one already fits the underlying STATE (see
    `status` on `RebalancingRecommendation`, which reuses
    `TargetStatus`/`MaximumStatus` verbatim instead of re-encoding them
    here)."""

    BUY = "BUY"
    REDUCE = "REDUCE"
    HOLD = "HOLD"
    NO_CAPACITY = "NO_CAPACITY"
    NO_TARGET = "NO_TARGET"


@dataclass(frozen=True)
class RebalancingCandidate:
    """One strategy bucket's already-evaluated allocation state (from
    `allocation_engine.evaluate_bucket_allocation`) plus the priority
    ordering `inflow_allocator` needs — the two inputs this engine reuses
    rather than recomputing."""

    strategy_bucket_id: UUID
    bucket_name: str
    actual_value: Decimal
    risk_allocation_percent: Decimal | None
    target_percent: Decimal | None
    maximum_percent: Decimal | None
    allow_new_buy: bool | None
    priority: int
    is_emergency_excluded: bool
    target_status: TargetStatus
    maximum_status: MaximumStatus


@dataclass(frozen=True)
class RebalancingRecommendation:
    strategy_bucket_id: UUID
    bucket_name: str
    actual_value: Decimal
    current_percent: Decimal | None
    target_percent: Decimal | None
    maximum_percent: Decimal | None
    # target_percent - current_percent, in percentage points — positive
    # means underweight, negative means overweight. None whenever either
    # side is undefined (no target, or excluded from risk allocation).
    difference_percent: Decimal | None
    target_value: Decimal | None
    # target_value - actual_value: positive = room to buy toward target,
    # negative = already past it. None when target_value is None.
    difference_value: Decimal | None
    action: RebalancingAction
    # The BUY or REDUCE amount actually being recommended (never both at
    # once) — None for HOLD/NO_CAPACITY/NO_TARGET. Always <= actual_value
    # for a REDUCE (the reduction formula guarantees this by
    # construction) and always <= available_cash in total across every
    # BUY recommendation combined (guaranteed by
    # `calculate_inflow_allocation`'s own invariant).
    recommended_value: Decimal | None
    priority: int
    allow_new_buy: bool | None
    # The underlying category state (section 2 of the approved spec),
    # reusing TargetStatus/MaximumStatus values verbatim rather than
    # inventing a third vocabulary: "UNDERWEIGHT" | "ON_TARGET" |
    # "OVERWEIGHT" | "NO_TARGET" (from TargetStatus) or
    # "MAXIMUM_BREACHED" (from MaximumStatus, reported instead of the
    # target status whenever it applies, since maximum has priority).
    status: str
    reason: str


@dataclass(frozen=True)
class RebalancingResult:
    available_cash: Decimal
    total_recommended_buy: Decimal
    total_recommended_reduce: Decimal
    recommendations: tuple[RebalancingRecommendation, ...]


def _percent_of(value: Decimal, denominator: Decimal) -> Decimal:
    if denominator <= 0:
        return Decimal("0")
    return (value / denominator) * Decimal("100")


def _reduction_recommendation(
    candidate: RebalancingCandidate, investable_portfolio_value: Decimal
) -> RebalancingRecommendation:
    """A category already over its maximum — REDUCE, never BUY,
    regardless of its target (maximum has priority over target; see
    FINANCIAL_RULES.md, "Target Allocation vs. Maximum Allocation")."""
    # MAXIMUM_BREACHED is only ever reported by allocation_engine when
    # both risk_allocation_percent and maximum_percent are real values
    # (never for an emergency-excluded bucket, whose risk_allocation_
    # percent is always None) -- see _maximum_status in
    # domain/allocation_engine.py.
    assert candidate.risk_allocation_percent is not None
    assert candidate.maximum_percent is not None

    maximum_value = (candidate.maximum_percent / Decimal("100")) * investable_portfolio_value
    required_reduction = max(candidate.actual_value - maximum_value, Decimal("0"))

    target_value = (
        (candidate.target_percent / Decimal("100")) * investable_portfolio_value
        if candidate.target_percent is not None
        else None
    )
    difference_value = None if target_value is None else target_value - candidate.actual_value
    difference_percent = (
        None if candidate.target_percent is None else candidate.target_percent - candidate.risk_allocation_percent
    )

    reason = (
        f"{candidate.bucket_name} is at {candidate.risk_allocation_percent:.2f}% of the investable portfolio, "
        f"above its configured maximum of {candidate.maximum_percent:.2f}%. "
        f"Reduce by approximately {required_reduction:.2f} to return within the maximum."
    )

    return RebalancingRecommendation(
        strategy_bucket_id=candidate.strategy_bucket_id,
        bucket_name=candidate.bucket_name,
        actual_value=candidate.actual_value,
        current_percent=candidate.risk_allocation_percent,
        target_percent=candidate.target_percent,
        maximum_percent=candidate.maximum_percent,
        difference_percent=difference_percent,
        target_value=target_value,
        difference_value=difference_value,
        action=RebalancingAction.REDUCE,
        recommended_value=required_reduction,
        priority=candidate.priority,
        allow_new_buy=candidate.allow_new_buy,
        status=MaximumStatus.MAXIMUM_BREACHED.value,
        reason=reason,
    )


def _buy_side_recommendation(
    candidate: RebalancingCandidate,
    *,
    investable_portfolio_value: Decimal,
    inflow_status: InflowStatus,
    allocated_amount: Decimal,
) -> RebalancingRecommendation:
    """Every category NOT currently in maximum breach — action derived
    from the Smart Inflow Allocator's own status/allocation for this
    category (see module docstring)."""
    target_value = (
        (candidate.target_percent / Decimal("100")) * investable_portfolio_value
        if candidate.target_percent is not None
        else None
    )
    difference_value = None if target_value is None else target_value - candidate.actual_value
    difference_percent = (
        None
        if candidate.target_percent is None or candidate.risk_allocation_percent is None
        else candidate.target_percent - candidate.risk_allocation_percent
    )

    current_percent_display = (
        f"{candidate.risk_allocation_percent:.2f}%" if candidate.risk_allocation_percent is not None else "n/a"
    )

    if allocated_amount > 0:
        # Never true for an emergency-excluded candidate: capacity_and_
        # status/calculate_inflow_allocation both refuse it capacity
        # unconditionally (see EMERGENCY_EXCLUDED below), so this branch
        # and the emergency-protection branch can never both apply.
        action = RebalancingAction.BUY
        recommended_value: Decimal | None = allocated_amount
        gap_note = (
            f" (a partial fill of the {difference_value:.2f} gap toward target, limited by available cash)"
            if difference_value is not None and allocated_amount < difference_value
            else ""
        )
        reason = (
            f"{candidate.bucket_name} is below its {candidate.target_percent:.2f}% target "
            f"(currently {current_percent_display}). "
            f"Recommended purchase: {allocated_amount:.2f}{gap_note}."
        )
    elif candidate.is_emergency_excluded:
        # Checked before NO_TARGET/allow_new_buy so the emergency-
        # protection reason always wins for this category, regardless of
        # whether it also happens to have no target configured (see
        # FINANCIAL_RULES.md, "Emergency Cash").
        action = RebalancingAction.HOLD
        recommended_value = None
        reason = f"{candidate.bucket_name} is the configured emergency reserve — never used to fund rebalancing."
    elif candidate.target_percent is None:
        action = RebalancingAction.NO_TARGET
        recommended_value = None
        reason = (
            f"{candidate.bucket_name} has no configured target — it is a constraint-only category. "
            f"No target-driven action is recommended."
        )
    elif candidate.allow_new_buy is False:
        action = RebalancingAction.HOLD
        recommended_value = None
        reason = f"{candidate.bucket_name} is below its target, but new purchases are currently disabled for it."
    elif inflow_status in (InflowStatus.TARGET_GAP, InflowStatus.MAXIMUM_LIMIT):
        # Structurally eligible (a real gap exists, buying is permitted)
        # but nothing was actually funded — either available_cash was
        # exhausted by higher-priority categories, or this category is
        # already at its own maximum ceiling for new buying.
        action = RebalancingAction.NO_CAPACITY
        recommended_value = None
        reason = (
            f"{candidate.bucket_name} is below its {candidate.target_percent:.2f}% target, "
            f"but no available cash could be allocated to it right now."
        )
    elif inflow_status == InflowStatus.AT_TARGET:
        action = RebalancingAction.HOLD
        recommended_value = None
        reason = f"{candidate.bucket_name} is at its target — no action needed."
    elif inflow_status == InflowStatus.OVER_TARGET:
        action = RebalancingAction.HOLD
        recommended_value = None
        reason = (
            f"{candidate.bucket_name} is above its target but within the configured maximum — "
            f"no reduction is required."
        )
    else:
        # InflowStatus.NO_CAPACITY: the portfolio itself has no
        # investable value to compute a percentage against.
        action = RebalancingAction.NO_CAPACITY
        recommended_value = None
        reason = f"{candidate.bucket_name}: no investable portfolio value to allocate against yet."

    status = candidate.target_status.value if candidate.target_percent is not None else TargetStatus.NO_TARGET.value

    return RebalancingRecommendation(
        strategy_bucket_id=candidate.strategy_bucket_id,
        bucket_name=candidate.bucket_name,
        actual_value=candidate.actual_value,
        current_percent=candidate.risk_allocation_percent,
        target_percent=candidate.target_percent,
        maximum_percent=candidate.maximum_percent,
        difference_percent=difference_percent,
        target_value=target_value,
        difference_value=difference_value,
        action=action,
        recommended_value=recommended_value,
        priority=candidate.priority,
        allow_new_buy=candidate.allow_new_buy,
        status=status,
        reason=reason,
    )


def calculate_rebalancing(
    *,
    candidates: list[RebalancingCandidate],
    available_cash: Decimal,
    investable_portfolio_value: Decimal,
) -> RebalancingResult:
    """Deterministic, side-effect-free rebalancing recommendations.

    Maximum-breached categories are resolved first and entirely
    separately from the cash competition below (section 10 of the
    approved spec: "maximum breaches should be resolved first") — a
    breached category can never also receive a BUY in the same pass,
    and its own cash need (a REDUCE, not a BUY) never competes for
    `available_cash` at all.

    Every other category competes for the SAME `available_cash` via
    `calculate_inflow_allocation` — the exact priority-ordered, greedy,
    never-double-spent distribution the Smart Inflow Allocator already
    uses, so `sum(recommended BUY amounts) <= available_cash` holds by
    that function's own existing guarantee, never re-verified or
    re-implemented here.
    """
    breached = [c for c in candidates if c.maximum_status == MaximumStatus.MAXIMUM_BREACHED]
    buyable = [c for c in candidates if c.maximum_status != MaximumStatus.MAXIMUM_BREACHED]

    reduce_recommendations = [_reduction_recommendation(c, investable_portfolio_value) for c in breached]

    inflow_candidates = [
        InflowCandidate(
            strategy_bucket_id=c.strategy_bucket_id,
            bucket_name=c.bucket_name,
            current_value=c.actual_value,
            target_percent=c.target_percent,
            maximum_percent=c.maximum_percent,
            allow_new_buy=c.allow_new_buy,
            priority=c.priority,
            is_emergency_excluded=c.is_emergency_excluded,
        )
        for c in buyable
    ]

    if available_cash > 0:
        inflow_result = calculate_inflow_allocation(
            new_cash_amount=available_cash,
            investable_portfolio_value=investable_portfolio_value,
            candidates=inflow_candidates,
        )
        status_and_amount_by_bucket = {
            r.strategy_bucket_id: (r.status, r.allocated_amount) for r in inflow_result.recommendations
        }
    else:
        # calculate_inflow_allocation refuses new_cash_amount <= 0 (a
        # deliberate, existing, unchanged guard — see
        # test_domain_inflow_allocator.py) -- zero cash is a perfectly
        # meaningful rebalancing input (Test B/I), so classify each
        # category's structural status directly via the same
        # capacity_and_status this function itself uses internally,
        # without running the (moot, nothing-to-distribute) allocation
        # pass.
        status_and_amount_by_bucket = {
            c.strategy_bucket_id: (capacity_and_status(ic, investable_portfolio_value)[1], Decimal("0"))
            for c, ic in zip(buyable, inflow_candidates)
        }

    buy_recommendations = []
    for c in buyable:
        inflow_status, allocated_amount = status_and_amount_by_bucket[c.strategy_bucket_id]
        buy_recommendations.append(
            _buy_side_recommendation(
                c,
                investable_portfolio_value=investable_portfolio_value,
                inflow_status=inflow_status,
                allocated_amount=allocated_amount,
            )
        )

    all_recommendations = tuple(reduce_recommendations + buy_recommendations)
    total_recommended_buy = sum((r.recommended_value for r in buy_recommendations if r.recommended_value), Decimal("0"))
    total_recommended_reduce = sum((r.recommended_value for r in reduce_recommendations if r.recommended_value), Decimal("0"))

    return RebalancingResult(
        available_cash=available_cash,
        total_recommended_buy=total_recommended_buy,
        total_recommended_reduce=total_recommended_reduce,
        recommendations=all_recommendations,
    )
