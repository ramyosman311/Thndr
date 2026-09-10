"""Portfolio configuration administration (Phase 12) -- create/read/
update the single `portfolio_configs` row. Distinct from
services/portfolio_service.py, which is deliberately read-only (never
writes to configuration -- see its own module docstring).

Base currency is financially critical (see FINANCIAL_RULES.md, "Base
Currency Change Policy"): once any transaction exists anywhere,
changing it is rejected outright rather than silently reinterpreting
every historical valuation.
"""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories import asset_repository
from app.repositories.portfolio_repository import any_transaction_exists, get_portfolio_config
from app.schemas.portfolio import (
    PortfolioConfigCreateRequest,
    PortfolioConfigOut,
    PortfolioConfigUpdateRequest,
)


class PortfolioConfigNotFoundError(Exception):
    """Raised when no portfolio_configs row exists yet."""


class PortfolioConfigAlreadyExistsError(Exception):
    """Raised on POST when a portfolio_configs row already exists -- the
    application remains single-portfolio for now (see ARCHITECTURE.md,
    "Domain Readiness Audit")."""


class InvalidEmergencyAssetError(Exception):
    """Raised when emergency_asset_id does not reference an existing asset."""


class BaseCurrencyChangeNotAllowedError(Exception):
    """Raised when attempting to change base_currency after any
    transaction has been recorded -- see FINANCIAL_RULES.md, "Base
    Currency Change Policy"."""


def _to_out(config) -> PortfolioConfigOut:
    return PortfolioConfigOut(
        id=config.id,
        name=config.name,
        base_currency=config.base_currency,
        emergency_asset_id=config.emergency_asset_id,
        emergency_excluded=config.emergency_excluded,
        telegram_enabled=config.telegram_enabled,
    )


async def get_config(session: AsyncSession) -> PortfolioConfigOut:
    config = await get_portfolio_config(session)
    if config is None:
        raise PortfolioConfigNotFoundError("No portfolio configuration exists yet.")
    return _to_out(config)


async def _validate_emergency_asset(session: AsyncSession, emergency_asset_id: UUID | None) -> None:
    if emergency_asset_id is None:
        return
    if await asset_repository.get_asset_by_id(session, emergency_asset_id) is None:
        raise InvalidEmergencyAssetError(f"Asset {emergency_asset_id} does not exist.")


async def create_config(session: AsyncSession, request: PortfolioConfigCreateRequest) -> PortfolioConfigOut:
    from app.models import PortfolioConfig

    if await get_portfolio_config(session) is not None:
        raise PortfolioConfigAlreadyExistsError(
            "A portfolio configuration already exists. The application is "
            "single-portfolio for now -- update the existing configuration "
            "instead of creating a second one."
        )
    await _validate_emergency_asset(session, request.emergency_asset_id)

    config = PortfolioConfig(
        name=request.name,
        base_currency=request.base_currency,
        emergency_asset_id=request.emergency_asset_id,
        emergency_excluded=request.emergency_excluded,
    )
    session.add(config)
    await session.commit()
    return _to_out(config)


async def update_config(session: AsyncSession, request: PortfolioConfigUpdateRequest) -> PortfolioConfigOut:
    config = await get_portfolio_config(session)
    if config is None:
        raise PortfolioConfigNotFoundError("No portfolio configuration exists yet.")

    if request.base_currency is not None and request.base_currency != config.base_currency:
        if await any_transaction_exists(session):
            raise BaseCurrencyChangeNotAllowedError(
                f"Cannot change base_currency from {config.base_currency!r} to "
                f"{request.base_currency!r}: transactions already exist, and every "
                "historical valuation was computed assuming the current base "
                "currency. Changing it now would silently reinterpret that "
                "history. Financial integrity is preserved by rejecting this "
                "change rather than allowing it."
            )
        config.base_currency = request.base_currency

    if request.name is not None:
        config.name = request.name
    if request.clear_emergency_asset:
        config.emergency_asset_id = None
    elif request.emergency_asset_id is not None:
        await _validate_emergency_asset(session, request.emergency_asset_id)
        config.emergency_asset_id = request.emergency_asset_id
    if request.emergency_excluded is not None:
        config.emergency_excluded = request.emergency_excluded
    if request.telegram_enabled is not None:
        config.telegram_enabled = request.telegram_enabled

    await session.commit()
    return _to_out(config)
