"""Data access for the Phase 11 price infrastructure. All SQLAlchemy
queries against `asset_price_configs`, `asset_prices`, and `fx_rates`
live here (see ARCHITECTURE.md, "Backend Layering") -- neither
services/price_service.py nor services/price_orchestrator.py issues a
query of its own.
"""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Asset, AssetPrice, AssetPriceConfig, FxRate


async def get_asset_by_id(session: AsyncSession, asset_id: UUID) -> Asset | None:
    result = await session.execute(select(Asset).where(Asset.id == asset_id))
    return result.scalar_one_or_none()


async def get_price_config_by_asset_id(session: AsyncSession, asset_id: UUID) -> AssetPriceConfig | None:
    result = await session.execute(select(AssetPriceConfig).where(AssetPriceConfig.asset_id == asset_id))
    return result.scalar_one_or_none()


async def get_price_configs_for_assets(session: AsyncSession, asset_ids: list[UUID]) -> dict[UUID, AssetPriceConfig]:
    """Batch equivalent of `get_price_config_by_asset_id` -- used
    alongside `get_latest_prices_for_assets` so batch valuation reads
    stay to a fixed, small number of queries regardless of portfolio
    size."""
    if not asset_ids:
        return {}
    result = await session.execute(select(AssetPriceConfig).where(AssetPriceConfig.asset_id.in_(asset_ids)))
    return {config.asset_id: config for config in result.scalars().all()}


async def list_automated_price_configs(session: AsyncSession) -> list[AssetPriceConfig]:
    """Every asset configured for automated fetching, with its asset
    eagerly loaded -- the candidate set for one background refresh run
    (services/price_orchestrator.py). Assets with no config row, or with
    `automated_fetching_enabled=False`, are never included -- provider
    selection is configuration-driven, not inferred."""
    result = await session.execute(
        select(AssetPriceConfig)
        .where(AssetPriceConfig.automated_fetching_enabled.is_(True))
        .options(selectinload(AssetPriceConfig.asset))
    )
    return list(result.scalars().all())


async def get_latest_price(session: AsyncSession, asset_id: UUID) -> AssetPrice | None:
    """The single most recent observation for an asset, manual or
    automated -- the one row request-time reads
    (services/price_service.py) ever look at."""
    result = await session.execute(
        select(AssetPrice)
        .where(AssetPrice.asset_id == asset_id)
        .order_by(AssetPrice.recorded_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def get_latest_prices_for_assets(session: AsyncSession, asset_ids: list[UUID]) -> dict[UUID, AssetPrice]:
    """Batch equivalent of `get_latest_price`, one query for many
    assets -- used by portfolio valuation so pricing N holdings never
    costs N queries."""
    if not asset_ids:
        return {}
    result = await session.execute(
        select(AssetPrice).where(AssetPrice.asset_id.in_(asset_ids)).order_by(AssetPrice.recorded_at.desc())
    )
    latest_by_asset: dict[UUID, AssetPrice] = {}
    for price in result.scalars().all():
        if price.asset_id not in latest_by_asset:
            latest_by_asset[price.asset_id] = price
    return latest_by_asset


async def get_latest_manual_price(session: AsyncSession, asset_id: UUID) -> AssetPrice | None:
    """The most recent manual observation only -- used to enforce
    manual-vs-automated precedence (domain/manual_precedence.py) before
    an automated observation is stored."""
    result = await session.execute(
        select(AssetPrice)
        .where(AssetPrice.asset_id == asset_id, AssetPrice.is_manual.is_(True))
        .order_by(AssetPrice.recorded_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def list_price_history(session: AsyncSession, asset_id: UUID, *, limit: int = 100) -> list[AssetPrice]:
    result = await session.execute(
        select(AssetPrice)
        .where(AssetPrice.asset_id == asset_id)
        .order_by(AssetPrice.recorded_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def insert_price_observation(
    session: AsyncSession,
    *,
    asset_id: UUID,
    price: Decimal,
    currency: str,
    provider: str,
    recorded_at: datetime,
    is_manual: bool,
    source: str | None = None,
    provider_symbol: str | None = None,
    price_metadata: dict | None = None,
) -> AssetPrice:
    """Appends a new immutable observation. Never updates or deletes an
    existing row -- see FINANCIAL_RULES.md, "Price Observations Are
    Immutable"."""
    observation = AssetPrice(
        asset_id=asset_id,
        price=price,
        currency=currency,
        provider=provider,
        source=source,
        provider_symbol=provider_symbol,
        recorded_at=recorded_at,
        is_manual=is_manual,
        price_metadata=price_metadata,
    )
    session.add(observation)
    await session.flush()
    return observation


async def get_latest_fx_rate(session: AsyncSession, base_currency: str, quote_currency: str) -> FxRate | None:
    result = await session.execute(
        select(FxRate)
        .where(FxRate.base_currency == base_currency, FxRate.quote_currency == quote_currency)
        .order_by(FxRate.recorded_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def insert_fx_rate(
    session: AsyncSession,
    *,
    base_currency: str,
    quote_currency: str,
    rate: Decimal,
    provider: str,
    recorded_at: datetime,
    rate_metadata: dict | None = None,
) -> FxRate:
    fx_rate = FxRate(
        base_currency=base_currency,
        quote_currency=quote_currency,
        rate=rate,
        provider=provider,
        recorded_at=recorded_at,
        rate_metadata=rate_metadata,
    )
    session.add(fx_rate)
    await session.flush()
    return fx_rate
