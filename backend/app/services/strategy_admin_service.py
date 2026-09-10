"""Strategy Bucket + Allocation Target administration (Phase 12).
Distinct from services/strategy_service.py, which is deliberately
read-only (it only validates and reports -- see its own module
docstring).

Ownership boundary (see FINANCIAL_RULES.md, "Strategy Validation
Ownership"): this module enforces only PER-ROW constraints (percent
ranges, minimum <= maximum, duplicate bucket/target names) -- exactly
what the database's own CHECK/UNIQUE constraints already require. It
NEVER validates or blocks on the AGGREGATE question of whether the
whole strategy's target percentages sum to 100%; that remains
exclusively `services/strategy_service.get_strategy_validation`'s
responsibility, called separately and reported as a diagnostic status,
never silently fixed or used to reject a save here.
"""

from decimal import Decimal
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories import strategy_admin_repository
from app.repositories.portfolio_repository import get_portfolio_config
from app.schemas.strategy import (
    AllocationTargetCreateRequest,
    AllocationTargetOut,
    AllocationTargetUpdateRequest,
    StrategyBucketCreateRequest,
    StrategyBucketOut,
    StrategyBucketUpdateRequest,
)


class PortfolioNotConfiguredError(Exception):
    """Raised when no portfolio_configs row exists yet."""


class StrategyBucketNotFoundError(Exception):
    """Raised when the referenced strategy_bucket_id does not exist."""


class DuplicateStrategyBucketNameError(Exception):
    """Raised when a bucket name is already used within this portfolio."""


class AllocationTargetNotFoundError(Exception):
    """Raised when the referenced allocation_target_id does not exist."""


class InvalidAllocationTargetError(Exception):
    """Raised for a per-row inconsistency (bucket doesn't belong to this
    portfolio, or minimum_percent would exceed maximum_percent after
    this update)."""


class DuplicateAllocationTargetError(Exception):
    """Raised when the bucket already has an allocation_targets row."""


def _bucket_to_out(bucket) -> StrategyBucketOut:
    return StrategyBucketOut(
        id=bucket.id,
        portfolio_config_id=bucket.portfolio_config_id,
        name=bucket.name,
        description=bucket.description,
        is_active=bucket.is_active,
    )


def _target_to_out(target) -> AllocationTargetOut:
    return AllocationTargetOut(
        id=target.id,
        portfolio_config_id=target.portfolio_config_id,
        strategy_bucket_id=target.strategy_bucket_id,
        target_percent=target.target_percent,
        minimum_percent=target.minimum_percent,
        maximum_percent=target.maximum_percent,
        allow_new_buy=target.allow_new_buy,
        priority=target.priority,
        is_active=target.is_active,
    )


async def _require_portfolio_config(session: AsyncSession):
    config = await get_portfolio_config(session)
    if config is None:
        raise PortfolioNotConfiguredError("No portfolio configuration exists yet.")
    return config


# --- Strategy Buckets ----------------------------------------------------


async def list_buckets(session: AsyncSession, *, include_inactive: bool = False) -> list[StrategyBucketOut]:
    config = await _require_portfolio_config(session)
    buckets = await strategy_admin_repository.list_strategy_buckets(
        session, config.id, include_inactive=include_inactive
    )
    return [_bucket_to_out(b) for b in buckets]


async def create_bucket(session: AsyncSession, request: StrategyBucketCreateRequest) -> StrategyBucketOut:
    from app.models import StrategyBucket

    config = await _require_portfolio_config(session)
    bucket = StrategyBucket(
        portfolio_config_id=config.id, name=request.name, description=request.description
    )
    session.add(bucket)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise DuplicateStrategyBucketNameError(
            f"A strategy bucket named {request.name!r} already exists for this portfolio."
        ) from exc
    return _bucket_to_out(bucket)


async def update_bucket(
    session: AsyncSession, bucket_id: UUID, request: StrategyBucketUpdateRequest
) -> StrategyBucketOut:
    bucket = await strategy_admin_repository.get_strategy_bucket_by_id(session, bucket_id)
    if bucket is None:
        raise StrategyBucketNotFoundError(f"Strategy bucket {bucket_id} does not exist.")
    if request.name is not None:
        bucket.name = request.name
    if request.description is not None:
        bucket.description = request.description
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise DuplicateStrategyBucketNameError(
            f"A strategy bucket named {request.name!r} already exists for this portfolio."
        ) from exc
    return _bucket_to_out(bucket)


async def _set_bucket_active(session: AsyncSession, bucket_id: UUID, *, is_active: bool) -> StrategyBucketOut:
    bucket = await strategy_admin_repository.get_strategy_bucket_by_id(session, bucket_id)
    if bucket is None:
        raise StrategyBucketNotFoundError(f"Strategy bucket {bucket_id} does not exist.")
    bucket.is_active = is_active
    await session.commit()
    return _bucket_to_out(bucket)


async def activate_bucket(session: AsyncSession, bucket_id: UUID) -> StrategyBucketOut:
    return await _set_bucket_active(session, bucket_id, is_active=True)


async def deactivate_bucket(session: AsyncSession, bucket_id: UUID) -> StrategyBucketOut:
    """Deactivation never deletes the bucket, its historical allocation
    targets, or any asset's existing `strategy_bucket_id` assignment --
    it only stops the bucket from being offered/considered as active
    going forward (existing engines already filter on `is_active`)."""
    return await _set_bucket_active(session, bucket_id, is_active=False)


# --- Allocation Targets ----------------------------------------------------


async def list_targets(session: AsyncSession, *, include_inactive: bool = False) -> list[AllocationTargetOut]:
    config = await _require_portfolio_config(session)
    targets = await strategy_admin_repository.list_allocation_targets(
        session, config.id, include_inactive=include_inactive
    )
    return [_target_to_out(t) for t in targets]


async def create_target(session: AsyncSession, request: AllocationTargetCreateRequest) -> AllocationTargetOut:
    from app.models import AllocationTarget

    config = await _require_portfolio_config(session)
    bucket = await strategy_admin_repository.get_strategy_bucket_by_id(session, request.strategy_bucket_id)
    if bucket is None or bucket.portfolio_config_id != config.id:
        raise InvalidAllocationTargetError(
            f"Strategy bucket {request.strategy_bucket_id} does not exist for this portfolio."
        )

    target = AllocationTarget(
        portfolio_config_id=config.id,
        strategy_bucket_id=request.strategy_bucket_id,
        target_percent=request.target_percent,
        minimum_percent=request.minimum_percent,
        maximum_percent=request.maximum_percent,
        allow_new_buy=request.allow_new_buy,
        priority=request.priority,
    )
    session.add(target)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise DuplicateAllocationTargetError(
            f"An allocation target for bucket {request.strategy_bucket_id} already exists."
        ) from exc
    return _target_to_out(target)


async def update_target(
    session: AsyncSession, target_id: UUID, request: AllocationTargetUpdateRequest
) -> AllocationTargetOut:
    target = await strategy_admin_repository.get_allocation_target_by_id(session, target_id)
    if target is None:
        raise AllocationTargetNotFoundError(f"Allocation target {target_id} does not exist.")

    new_target_percent: Decimal | None = target.target_percent
    if request.clear_target_percent:
        new_target_percent = None
    elif request.target_percent is not None:
        new_target_percent = request.target_percent

    new_minimum: Decimal | None = target.minimum_percent
    if request.clear_minimum_percent:
        new_minimum = None
    elif request.minimum_percent is not None:
        new_minimum = request.minimum_percent

    new_maximum: Decimal | None = target.maximum_percent
    if request.clear_maximum_percent:
        new_maximum = None
    elif request.maximum_percent is not None:
        new_maximum = request.maximum_percent

    if new_minimum is not None and new_maximum is not None and new_minimum > new_maximum:
        raise InvalidAllocationTargetError("minimum_percent must not exceed maximum_percent.")

    target.target_percent = new_target_percent
    target.minimum_percent = new_minimum
    target.maximum_percent = new_maximum
    if request.allow_new_buy is not None:
        target.allow_new_buy = request.allow_new_buy
    if request.priority is not None:
        target.priority = request.priority
    if request.is_active is not None:
        target.is_active = request.is_active

    await session.commit()
    return _target_to_out(target)
