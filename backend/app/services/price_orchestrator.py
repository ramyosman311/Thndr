"""Price Orchestrator (Phase 11) -- the ONLY component that ever calls
a live `PriceProvider`. Used exclusively by the background refresh
worker (app/workers/price_refresh.py); never imported by any
request-time read path (see FINANCIAL_RULES.md, "Non-Blocking
Valuation", and services/price_service.py's module docstring, which is
the only thing request-time code should ever import).

Per-asset flow, generic for every asset (no symbol-specific branching):

    AssetPriceConfig -> primary provider
        -> on failure: secondary provider
        -> on failure: nothing is stored; the failure is recorded and
           the batch moves on to the next asset (see
           FINANCIAL_RULES.md, "One Provider Failure Never Stops The
           Batch")

This module never itself produces a "LAST_KNOWN_PRICE" or
"PRICE_UNAVAILABLE" classification -- those fall naturally out of
whatever is (or isn't) already in `asset_prices` once
services/price_service.py reads it back at request time.
"""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.manual_precedence import may_automated_observation_supersede_manual
from app.models import AssetPriceConfig
from app.providers.base import ProviderError, ProviderQuote
from app.providers.registry import get_provider
from app.repositories import price_repository


@dataclass(frozen=True)
class RefreshOutcome:
    asset_id: UUID
    provider_name: str | None
    succeeded: bool
    stored: bool
    reason: str | None = None


async def _fetch_quote(provider_name: str, provider_symbol: str) -> tuple[ProviderQuote | None, str | None]:
    provider = get_provider(provider_name)
    if provider is None:
        return None, f"Provider {provider_name!r} is not registered/implemented."
    try:
        return await provider.get_price(provider_symbol), None
    except ProviderError as exc:
        return None, str(exc)


async def refresh_one_asset(session: AsyncSession, config: AssetPriceConfig) -> RefreshOutcome:
    """Refreshes one asset through the generic primary -> secondary
    fallback chain. Never invents a price when both providers fail --
    it simply stores nothing for this run, leaving whatever is already
    in `asset_prices` (however old) as what Price Service will report."""
    asset_id = config.asset_id
    attempts: list[tuple[str, str]] = []
    if config.primary_provider and config.primary_provider_symbol:
        attempts.append((config.primary_provider, config.primary_provider_symbol))
    if config.secondary_provider and config.secondary_provider_symbol:
        attempts.append((config.secondary_provider, config.secondary_provider_symbol))

    if not attempts:
        return RefreshOutcome(
            asset_id=asset_id,
            provider_name=None,
            succeeded=False,
            stored=False,
            reason="No provider configured for automated fetching.",
        )

    last_failure_reason: str | None = None
    for provider_name, provider_symbol in attempts:
        quote, error = await _fetch_quote(provider_name, provider_symbol)
        if quote is None:
            last_failure_reason = error
            continue

        manual = await price_repository.get_latest_manual_price(session, asset_id)
        may_supersede = may_automated_observation_supersede_manual(
            lock_manual=config.lock_manual,
            manual_recorded_at=manual.recorded_at if manual else None,
            automated_timestamp=quote.timestamp,
        )
        if not may_supersede:
            return RefreshOutcome(
                asset_id=asset_id,
                provider_name=provider_name,
                succeeded=True,
                stored=False,
                reason="A manual price takes precedence; the fetched observation was not stored.",
            )

        await price_repository.insert_price_observation(
            session,
            asset_id=asset_id,
            price=quote.price,
            currency=quote.currency,
            provider=provider_name,
            recorded_at=quote.timestamp,
            is_manual=False,
            provider_symbol=quote.provider_symbol,
        )
        return RefreshOutcome(asset_id=asset_id, provider_name=provider_name, succeeded=True, stored=True)

    return RefreshOutcome(
        asset_id=asset_id, provider_name=None, succeeded=False, stored=False, reason=last_failure_reason
    )


async def refresh_all_automated_assets(session: AsyncSession) -> list[RefreshOutcome]:
    """The batch entrypoint app/workers/price_refresh.py calls. One
    asset's provider failure never stops the rest of the batch -- every
    asset is refreshed independently and its outcome recorded."""
    configs = await price_repository.list_automated_price_configs(session)
    outcomes = [await refresh_one_asset(session, config) for config in configs]
    return outcomes
