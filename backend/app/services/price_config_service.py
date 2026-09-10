"""Asset price CONFIGURATION administration (Phase 12) -- distinct from
services/price_service.py (request-time reads) and
services/price_orchestrator.py (the background fetch path). This module
only ever reads/writes `asset_price_configs` rows; it never reads
`asset_prices` and never calls a provider.

Validation lives here, not in the frontend (see FINANCIAL_RULES.md,
"Do Not Duplicate Business Logic"): a provider name is checked against
the real registry, never assumed valid because a string was entered.
"""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.providers.registry import is_registered_provider_name
from app.repositories import price_repository
from app.schemas.price import AssetPriceConfigOut, AssetPriceConfigUpsertRequest


class AssetNotFoundError(Exception):
    """Raised when the referenced asset_id does not exist."""


class InvalidProviderError(Exception):
    """Raised when a provider name is not registered in
    app/providers/registry.py."""


class InvalidPriceConfigError(Exception):
    """Raised for any other internally-inconsistent configuration (e.g.
    automated fetching enabled with no primary provider)."""


def _validate_provider(provider: str | None, provider_symbol: str | None, *, role: str) -> None:
    if provider is None:
        return
    if not is_registered_provider_name(provider):
        raise InvalidProviderError(
            f"{role} provider {provider!r} is not a registered provider. "
            "Configure a provider that actually has an implemented adapter, "
            "or leave it unset for manual-only pricing."
        )
    if not provider_symbol or not provider_symbol.strip():
        raise InvalidPriceConfigError(f"{role}_provider_symbol is required when {role}_provider is set.")


def _to_out(asset_id: UUID, config) -> AssetPriceConfigOut:
    if config is None:
        return AssetPriceConfigOut(
            asset_id=asset_id,
            configured=False,
            primary_provider=None,
            primary_provider_symbol=None,
            secondary_provider=None,
            secondary_provider_symbol=None,
            automated_fetching_enabled=False,
            manual_override_enabled=True,
            stale_threshold_minutes=None,
            lock_manual=False,
        )
    return AssetPriceConfigOut(
        asset_id=asset_id,
        configured=True,
        primary_provider=config.primary_provider,
        primary_provider_symbol=config.primary_provider_symbol,
        secondary_provider=config.secondary_provider,
        secondary_provider_symbol=config.secondary_provider_symbol,
        automated_fetching_enabled=config.automated_fetching_enabled,
        manual_override_enabled=config.manual_override_enabled,
        stale_threshold_minutes=config.stale_threshold_minutes,
        lock_manual=config.lock_manual,
    )


async def get_price_config(session: AsyncSession, asset_id: UUID) -> AssetPriceConfigOut:
    asset = await price_repository.get_asset_by_id(session, asset_id)
    if asset is None:
        raise AssetNotFoundError(f"Asset {asset_id} does not exist.")
    config = await price_repository.get_price_config_by_asset_id(session, asset_id)
    return _to_out(asset_id, config)


async def upsert_price_config(
    session: AsyncSession, asset_id: UUID, request: AssetPriceConfigUpsertRequest
) -> AssetPriceConfigOut:
    asset = await price_repository.get_asset_by_id(session, asset_id)
    if asset is None:
        raise AssetNotFoundError(f"Asset {asset_id} does not exist.")

    _validate_provider(request.primary_provider, request.primary_provider_symbol, role="primary")
    _validate_provider(request.secondary_provider, request.secondary_provider_symbol, role="secondary")
    if request.automated_fetching_enabled and request.primary_provider is None:
        raise InvalidPriceConfigError(
            "automated_fetching_enabled requires a primary_provider to be configured."
        )

    config = await price_repository.get_price_config_by_asset_id(session, asset_id)
    if config is None:
        from app.models import AssetPriceConfig

        config = AssetPriceConfig(asset_id=asset_id)
        session.add(config)

    config.primary_provider = request.primary_provider
    config.primary_provider_symbol = request.primary_provider_symbol
    config.secondary_provider = request.secondary_provider
    config.secondary_provider_symbol = request.secondary_provider_symbol
    config.automated_fetching_enabled = request.automated_fetching_enabled
    config.manual_override_enabled = request.manual_override_enabled
    config.stale_threshold_minutes = request.stale_threshold_minutes
    config.lock_manual = request.lock_manual

    await session.commit()
    return _to_out(asset_id, config)
