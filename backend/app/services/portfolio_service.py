"""Orchestrates the Portfolio Engine: loads state via the repository layer,
runs pure domain calculations, and assembles API-ready schemas.

This module is read-only — it never writes to holdings, transactions,
snapshots, or configuration (see Phase 5 approval, "No Side Effects").

Rounding: internal domain calculations stay at full Decimal precision.
Values are quantized to 2 decimal places only here, when building the
schema returned to the API boundary — never inside the domain layer, and
never via float conversion (see FINANCIAL_RULES.md, "Precision").
"""

from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.allocation_engine import evaluate_bucket_allocation
from app.domain.pnl_engine import calculate_holding_pnl
from app.domain.portfolio_engine import AssetPosition, calculate_portfolio_totals
from app.models import Asset
from app.repositories.portfolio_repository import (
    get_active_allocation_targets,
    get_active_assets,
    get_active_strategy_buckets,
    get_portfolio_config,
)
from app.schemas.portfolio import BucketAllocationOut, HoldingPnLOut, PortfolioAllocationOut, PortfolioSummaryOut

_PRESENTATION_QUANT = Decimal("0.01")


class PortfolioNotConfiguredError(Exception):
    """Raised when no portfolio_configs row exists yet."""


def _round(value: Decimal) -> Decimal:
    """Round to 2 decimal places for presentation only (matches the
    NUMERIC(18,2) / NUMERIC(5,2) precision used for stored money/percent
    columns). Never used inside the domain layer itself."""
    return value.quantize(_PRESENTATION_QUANT, rounding=ROUND_HALF_UP)


def _find_emergency_bucket_id(assets: list[Asset], emergency_asset_id):
    """Which strategy bucket (if any) holds the configured emergency asset —
    determined purely from configuration relationships (portfolio_configs
    -> assets -> strategy_buckets), never from a bucket/asset name."""
    if emergency_asset_id is None:
        return None
    for asset in assets:
        if asset.id == emergency_asset_id:
            return asset.strategy_bucket_id
    return None


def _build_positions(assets: list[Asset], emergency_asset_id) -> list[AssetPosition]:
    positions = []
    for asset in assets:
        holding = asset.holding
        quantity = holding.quantity if holding is not None else Decimal("0")
        current_price = holding.current_price if holding is not None else Decimal("0")
        positions.append(
            AssetPosition(
                asset_id=asset.id,
                symbol=asset.symbol,
                is_emergency=emergency_asset_id is not None and asset.id == emergency_asset_id,
                strategy_bucket_id=asset.strategy_bucket_id,
                quantity=quantity,
                current_price=current_price,
            )
        )
    return positions


async def get_portfolio_summary(session: AsyncSession) -> PortfolioSummaryOut:
    config = await get_portfolio_config(session)
    if config is None:
        raise PortfolioNotConfiguredError("No portfolio configuration exists yet.")

    assets = await get_active_assets(session)
    positions = _build_positions(assets, config.emergency_asset_id)
    totals = calculate_portfolio_totals(positions, emergency_excluded=config.emergency_excluded)

    holdings_pnl: list[HoldingPnLOut] = []
    for asset in assets:
        holding = asset.holding
        if holding is None or holding.quantity == 0:
            continue
        pnl = calculate_holding_pnl(
            quantity=holding.quantity,
            average_cost=holding.average_cost,
            current_price=holding.current_price,
        )
        holdings_pnl.append(
            HoldingPnLOut(
                asset_id=asset.id,
                symbol=asset.symbol,
                quantity=holding.quantity,
                average_cost=holding.average_cost,
                current_price=holding.current_price,
                market_value=_round(pnl.market_value),
                cost_basis=_round(pnl.cost_basis),
                unrealized_pnl=_round(pnl.unrealized_pnl),
                unrealized_pnl_percent=(
                    _round(pnl.unrealized_pnl_percent) if pnl.unrealized_pnl_percent is not None else None
                ),
            )
        )

    return PortfolioSummaryOut(
        base_currency=config.base_currency,
        total_value=_round(totals.total_value),
        emergency_value=_round(totals.emergency_value),
        investable_value=_round(totals.investable_value),
        denominator_basis=totals.denominator_basis,
        denominator_value=_round(totals.denominator_value),
        emergency_excluded=config.emergency_excluded,
        holdings_pnl=holdings_pnl,
    )


async def get_portfolio_allocation(session: AsyncSession) -> PortfolioAllocationOut:
    config = await get_portfolio_config(session)
    if config is None:
        raise PortfolioNotConfiguredError("No portfolio configuration exists yet.")

    assets = await get_active_assets(session)
    positions = _build_positions(assets, config.emergency_asset_id)
    totals = calculate_portfolio_totals(positions, emergency_excluded=config.emergency_excluded)

    buckets = await get_active_strategy_buckets(session, config.id)
    targets = await get_active_allocation_targets(session, config.id)
    target_by_bucket_id = {target.strategy_bucket_id: target for target in targets}
    emergency_bucket_id = _find_emergency_bucket_id(assets, config.emergency_asset_id)

    bucket_outs: list[BucketAllocationOut] = []
    for bucket in buckets:
        target = target_by_bucket_id.get(bucket.id)
        excluded_from_risk = config.emergency_excluded and bucket.id == emergency_bucket_id
        result = evaluate_bucket_allocation(
            strategy_bucket_id=bucket.id,
            bucket_name=bucket.name,
            positions=positions,
            total_value=totals.total_value,
            risk_denominator_value=totals.denominator_value,
            excluded_from_risk_allocation=excluded_from_risk,
            target_percent=target.target_percent if target else None,
            minimum_percent=target.minimum_percent if target else None,
            maximum_percent=target.maximum_percent if target else None,
            allow_new_buy=target.allow_new_buy if target else None,
        )
        bucket_outs.append(
            BucketAllocationOut(
                strategy_bucket_id=result.strategy_bucket_id,
                bucket_name=result.bucket_name,
                actual_value=_round(result.actual_value),
                total_portfolio_percent=_round(result.total_portfolio_percent),
                risk_allocation_percent=(
                    _round(result.risk_allocation_percent) if result.risk_allocation_percent is not None else None
                ),
                target_percent=result.target_percent,
                minimum_percent=result.minimum_percent,
                maximum_percent=result.maximum_percent,
                allow_new_buy=result.allow_new_buy,
                target_status=result.target_status.value,
                minimum_status=result.minimum_status.value,
                maximum_status=result.maximum_status.value,
                buy_allowed=result.buy_allowed,
                excluded_from_risk_allocation=result.excluded_from_risk_allocation,
            )
        )

    return PortfolioAllocationOut(
        total_portfolio_value=_round(totals.total_value),
        risk_denominator_basis=totals.denominator_basis,
        risk_denominator_value=_round(totals.denominator_value),
        emergency_excluded=config.emergency_excluded,
        buckets=bucket_outs,
    )
