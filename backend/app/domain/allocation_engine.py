"""Pure allocation calculations: actual weight per strategy bucket, and its
status against configured target/minimum/maximum/allow_new_buy.

No I/O. Buckets and allocation rules are passed in as plain values from
the database — this module never references a specific bucket name or
asset symbol, so it works unchanged for any set of assets/buckets a user
configures (see FINANCIAL_RULES.md, "Database Is the Source of Truth").

target_percent, minimum_percent, maximum_percent, and allow_new_buy are
kept fully independent per FINANCIAL_RULES.md ("Target Allocation vs.
Maximum Allocation vs. Allow New Buy") — none is derived from another.
"""

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from uuid import UUID

from app.domain.portfolio_engine import AssetPosition

# Tolerance for deciding an actual percentage is "on target" rather than
# strictly under/over. This is a computational comparison detail of this
# module, not a business allocation rule — target/minimum/maximum values
# themselves always come from the database.
ON_TARGET_TOLERANCE_PERCENT = Decimal("0.5")


class TargetStatus(str, Enum):
    NO_TARGET = "NO_TARGET"
    UNDERWEIGHT = "UNDERWEIGHT"
    ON_TARGET = "ON_TARGET"
    OVERWEIGHT = "OVERWEIGHT"


class MinimumStatus(str, Enum):
    NO_MINIMUM = "NO_MINIMUM"
    ABOVE_MINIMUM = "ABOVE_MINIMUM"
    MINIMUM_BREACHED = "MINIMUM_BREACHED"


class MaximumStatus(str, Enum):
    NO_MAXIMUM = "NO_MAXIMUM"
    WITHIN_MAXIMUM = "WITHIN_MAXIMUM"
    MAXIMUM_BREACHED = "MAXIMUM_BREACHED"


@dataclass(frozen=True)
class BucketAllocation:
    strategy_bucket_id: UUID
    bucket_name: str
    actual_value: Decimal
    actual_percent: Decimal
    target_percent: Decimal | None
    minimum_percent: Decimal | None
    maximum_percent: Decimal | None
    allow_new_buy: bool | None  # None: no allocation rule configured for this bucket
    target_status: TargetStatus
    minimum_status: MinimumStatus
    maximum_status: MaximumStatus
    buy_allowed: bool


def calculate_bucket_value(positions: list[AssetPosition], strategy_bucket_id: UUID) -> Decimal:
    return sum(
        (p.value for p in positions if p.strategy_bucket_id == strategy_bucket_id),
        Decimal("0"),
    )


def calculate_actual_percent(actual_value: Decimal, denominator_value: Decimal) -> Decimal:
    """Returns 0 (never raises) when denominator_value is 0 — a well-defined
    empty allocation state rather than a division-by-zero crash."""
    if denominator_value == 0:
        return Decimal("0")
    return (actual_value / denominator_value) * Decimal("100")


def _target_status(actual_percent: Decimal, target_percent: Decimal | None) -> TargetStatus:
    if target_percent is None:
        return TargetStatus.NO_TARGET
    diff = actual_percent - target_percent
    if abs(diff) <= ON_TARGET_TOLERANCE_PERCENT:
        return TargetStatus.ON_TARGET
    return TargetStatus.OVERWEIGHT if diff > 0 else TargetStatus.UNDERWEIGHT


def _minimum_status(actual_percent: Decimal, minimum_percent: Decimal | None) -> MinimumStatus:
    if minimum_percent is None:
        return MinimumStatus.NO_MINIMUM
    return MinimumStatus.MINIMUM_BREACHED if actual_percent < minimum_percent else MinimumStatus.ABOVE_MINIMUM


def _maximum_status(actual_percent: Decimal, maximum_percent: Decimal | None) -> MaximumStatus:
    if maximum_percent is None:
        return MaximumStatus.NO_MAXIMUM
    return MaximumStatus.MAXIMUM_BREACHED if actual_percent >= maximum_percent else MaximumStatus.WITHIN_MAXIMUM


def evaluate_bucket_allocation(
    *,
    strategy_bucket_id: UUID,
    bucket_name: str,
    positions: list[AssetPosition],
    denominator_value: Decimal,
    target_percent: Decimal | None,
    minimum_percent: Decimal | None,
    maximum_percent: Decimal | None,
    allow_new_buy: bool | None,
) -> BucketAllocation:
    """Evaluate one bucket. This function only ever REPORTS a status — it
    never sells, never buys, and never modifies anything (see
    FINANCIAL_RULES.md, "Rebalancing Engine Rules": recommend, never
    execute — the same principle applies here, one phase earlier)."""
    actual_value = calculate_bucket_value(positions, strategy_bucket_id)
    actual_percent = calculate_actual_percent(actual_value, denominator_value)
    target_status = _target_status(actual_percent, target_percent)
    minimum_status = _minimum_status(actual_percent, minimum_percent)
    maximum_status = _maximum_status(actual_percent, maximum_percent)

    # Buying is reported as currently allowed only if the configured rule
    # permits it AND the maximum has not been breached — reaching the
    # maximum freezes new buying regardless of the allow_new_buy flag, but
    # never triggers a sell (see FINANCIAL_RULES.md, section on Individual
    # Stocks: "the future engine must be able to freeze new buys when the
    # maximum is reached/exceeded; it must NOT automatically sell").
    maximum_breached = maximum_status == MaximumStatus.MAXIMUM_BREACHED
    buy_allowed = (allow_new_buy is not False) and not maximum_breached

    return BucketAllocation(
        strategy_bucket_id=strategy_bucket_id,
        bucket_name=bucket_name,
        actual_value=actual_value,
        actual_percent=actual_percent,
        target_percent=target_percent,
        minimum_percent=minimum_percent,
        maximum_percent=maximum_percent,
        allow_new_buy=allow_new_buy,
        target_status=target_status,
        minimum_status=minimum_status,
        maximum_status=maximum_status,
        buy_allowed=buy_allowed,
    )
