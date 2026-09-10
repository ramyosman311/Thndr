"""Price Service (Phase 11) -- the ONLY price read path for every
request-time consumer (Portfolio, Allocation, P&L, Dashboard, Watchlist
alerts, the transaction response snapshot). It NEVER calls a
`PriceProvider`; it only reads whatever is already sitting in
`asset_prices` / `fx_rates` and classifies it. This is what makes
valuation non-blocking (see FINANCIAL_RULES.md, "Non-Blocking
Valuation") -- fetching *new* data from a provider is exclusively
services/price_orchestrator.py's job, run out-of-band by
app/workers/price_refresh.py.

Manual price submission also lives here (`record_manual_price`) even
though it's a write: it is a direct, synchronous user action (not a
provider fetch), so it doesn't belong in the Orchestrator, and it's the
Price Service's own storage it is writing into.
"""

from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.fx import convert
from app.domain.price_types import PriceResult, PriceStatus, unavailable_price_result
from app.domain.stale_policy import (
    FX_DEFAULT_STALE_THRESHOLD_MINUTES,
    classify_staleness,
    classify_staleness_by_threshold,
)
from app.models import Asset, AssetPrice, FxRate
from app.repositories import price_repository


class InvalidManualPriceError(Exception):
    """A manual price submission failed validation (non-positive price,
    or a currency that doesn't match the asset's own currency -- manual
    entry can never silently change what currency an asset is
    denominated in)."""


def _price_result_from_observation(
    observation: AssetPrice | None,
    *,
    asset: Asset,
    stale_threshold_minutes_override: int | None,
    reference_time: datetime,
) -> PriceResult:
    if observation is None:
        return unavailable_price_result("No price observation exists for this asset yet.")

    classification = classify_staleness(
        asset_type=asset.asset_type,
        recorded_at=observation.recorded_at,
        reference_time=reference_time,
        stale_threshold_minutes_override=stale_threshold_minutes_override,
    )
    return PriceResult(
        status=PriceStatus.LAST_KNOWN if classification.is_stale else PriceStatus.CURRENT,
        price=observation.price,
        currency=observation.currency,
        provider=observation.provider,
        provider_symbol=observation.provider_symbol,
        recorded_at=observation.recorded_at,
        age_seconds=classification.trading_adjusted_age_seconds,
        is_stale=classification.is_stale,
    )


async def get_asset_price(
    session: AsyncSession, asset: Asset, *, reference_time: datetime | None = None
) -> PriceResult:
    """The latest known price for one asset, in the asset's own native
    currency -- classified as CURRENT, LAST_KNOWN, or UNAVAILABLE. Never
    calls a provider; never fabricates a price when none exists."""
    reference_time = reference_time or datetime.now(timezone.utc)
    observation = await price_repository.get_latest_price(session, asset.id)
    config = await price_repository.get_price_config_by_asset_id(session, asset.id)
    return _price_result_from_observation(
        observation,
        asset=asset,
        stale_threshold_minutes_override=config.stale_threshold_minutes if config else None,
        reference_time=reference_time,
    )


async def get_prices_for_assets(
    session: AsyncSession, assets: list[Asset], *, reference_time: datetime | None = None
) -> dict[UUID, PriceResult]:
    """Batch equivalent of `get_asset_price` -- one pair of queries for
    N assets, so pricing a whole portfolio never costs N round trips
    (let alone N provider calls, which would never happen here anyway)."""
    reference_time = reference_time or datetime.now(timezone.utc)
    asset_ids = [asset.id for asset in assets]
    observations = await price_repository.get_latest_prices_for_assets(session, asset_ids)
    configs = await price_repository.get_price_configs_for_assets(session, asset_ids)
    results: dict[UUID, PriceResult] = {}
    for asset in assets:
        config = configs.get(asset.id)
        results[asset.id] = _price_result_from_observation(
            observations.get(asset.id),
            asset=asset,
            stale_threshold_minutes_override=config.stale_threshold_minutes if config else None,
            reference_time=reference_time,
        )
    return results


def _fx_rate_is_stale(fx_rate: FxRate, *, reference_time: datetime) -> bool:
    return classify_staleness_by_threshold(
        threshold_minutes=FX_DEFAULT_STALE_THRESHOLD_MINUTES,
        recorded_at=fx_rate.recorded_at,
        reference_time=reference_time,
    ).is_stale


def _apply_fx_conversion(
    native: PriceResult, fx_rate: FxRate | None, base_currency: str, *, reference_time: datetime
) -> PriceResult:
    """Shared by `get_asset_price_in_base_currency` and its batch
    equivalent so the conversion/staleness-combination rule is defined
    exactly once. NEVER treats a foreign-currency price as if it were
    already in `base_currency` -- if no valid FX rate is on record,
    returns CURRENCY_CONVERSION_UNAVAILABLE rather than assuming 1:1 or
    fabricating a rate (see FINANCIAL_RULES.md, "Base Currency & FX
    Conversion"). A stale FX rate is still used (like a stale asset
    price) but marks the combined result LAST_KNOWN rather than
    CURRENT -- never silently presented as live."""
    if fx_rate is None:
        return PriceResult(
            status=PriceStatus.CURRENCY_CONVERSION_UNAVAILABLE,
            price=None,
            currency=None,
            provider=native.provider,
            provider_symbol=native.provider_symbol,
            recorded_at=native.recorded_at,
            age_seconds=native.age_seconds,
            is_stale=native.is_stale,
            reason=f"No FX rate on record for {native.currency}->{base_currency}.",
        )

    fx_is_stale = _fx_rate_is_stale(fx_rate, reference_time=reference_time)
    converted_price = convert(native.price, fx_rate.rate)  # type: ignore[arg-type]
    is_stale = native.is_stale or fx_is_stale
    return PriceResult(
        status=PriceStatus.LAST_KNOWN if is_stale else PriceStatus.CURRENT,
        price=converted_price,
        currency=base_currency,
        provider=native.provider,
        provider_symbol=native.provider_symbol,
        recorded_at=native.recorded_at,
        age_seconds=native.age_seconds,
        is_stale=is_stale,
    )


async def get_asset_price_in_base_currency(
    session: AsyncSession,
    asset: Asset,
    base_currency: str,
    *,
    reference_time: datetime | None = None,
) -> PriceResult:
    """`get_asset_price`, converted into `base_currency` when the asset
    is denominated differently -- see `_apply_fx_conversion` for the
    conversion/staleness rule."""
    reference_time = reference_time or datetime.now(timezone.utc)
    native = await get_asset_price(session, asset, reference_time=reference_time)

    if not native.is_usable or native.currency == base_currency:
        return native

    fx_rate = await price_repository.get_latest_fx_rate(
        session, base_currency=native.currency, quote_currency=base_currency
    )
    return _apply_fx_conversion(native, fx_rate, base_currency, reference_time=reference_time)


async def get_prices_for_assets_in_base_currency(
    session: AsyncSession,
    assets: list[Asset],
    base_currency: str,
    *,
    reference_time: datetime | None = None,
) -> dict[UUID, PriceResult]:
    """Batch equivalent of `get_asset_price_in_base_currency` -- one
    native-price batch query plus one FX-rate query per distinct
    non-base currency actually present in `assets`, regardless of how
    many assets share that currency. This is what portfolio valuation
    (services/portfolio_shared.py) uses so a whole portfolio is priced
    in a fixed, small number of queries."""
    reference_time = reference_time or datetime.now(timezone.utc)
    native_results = await get_prices_for_assets(session, assets, reference_time=reference_time)

    needed_currencies = {asset.currency for asset in assets if asset.currency != base_currency}
    fx_rate_by_currency = {
        currency: await price_repository.get_latest_fx_rate(session, base_currency=currency, quote_currency=base_currency)
        for currency in needed_currencies
    }

    results: dict[UUID, PriceResult] = {}
    for asset in assets:
        native = native_results[asset.id]
        if not native.is_usable or native.currency == base_currency:
            results[asset.id] = native
            continue
        results[asset.id] = _apply_fx_conversion(
            native, fx_rate_by_currency.get(asset.currency), base_currency, reference_time=reference_time
        )
    return results


async def record_manual_price(
    session: AsyncSession,
    asset: Asset,
    *,
    price: Decimal,
    currency: str,
    recorded_at: datetime | None = None,
) -> AssetPrice:
    """Stores a new manual observation. This never checks manual-vs-
    automated precedence (domain/manual_precedence.py) -- that rule only
    ever gates an *automated* observation superseding an existing manual
    one; a human explicitly submitting a price right now is always
    accepted as the new latest manual observation. It also never alters
    any transaction, holding quantity, or average cost -- see
    FINANCIAL_RULES.md, "Manual Price Never Touches Transaction
    History"."""
    if price <= 0:
        raise InvalidManualPriceError(f"Manual price must be positive, got {price}.")
    if currency != asset.currency:
        raise InvalidManualPriceError(
            f"Manual price currency {currency!r} does not match asset currency {asset.currency!r}."
        )
    recorded_at = recorded_at or datetime.now(timezone.utc)
    observation = await price_repository.insert_price_observation(
        session,
        asset_id=asset.id,
        price=price,
        currency=currency,
        provider="manual",
        recorded_at=recorded_at,
        is_manual=True,
    )
    await session.commit()
    return observation
