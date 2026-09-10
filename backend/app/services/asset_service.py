"""Asset listing (Phase 9, read-only) and Asset administration (Phase
12: create/edit/activate/deactivate/delete).

Financial integrity (Phase 12, FINANCIAL_RULES.md "Asset Edit Safety" /
"Asset Deletion Policy"): editing or deleting an asset here NEVER
rewrites a transaction, holding, price observation, or snapshot. A
currency change is rejected outright once the asset has any transaction
or price observation on record; a hard delete is rejected outright once
the asset has ANY historical data at all (holdings, transactions,
watchlist entries, snapshot items, or price observations) -- deactivate
is the only path once history exists.
"""

from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories import asset_repository
from app.repositories.portfolio_repository import get_active_assets
from app.schemas.asset import AssetCreateRequest, AssetOut, AssetUpdateRequest


class AssetNotFoundError(Exception):
    """Raised when the referenced asset_id does not exist."""


class DuplicateAssetSymbolError(Exception):
    """Raised when creating/renaming an asset to a symbol already in use."""


class InvalidStrategyBucketError(Exception):
    """Raised when strategy_bucket_id does not reference an existing bucket."""


class CurrencyChangeNotAllowedError(Exception):
    """Raised when changing currency on an asset that has transaction or
    price history -- see FINANCIAL_RULES.md, "Asset Edit Safety"."""


class AssetHasHistoricalDataError(Exception):
    """Raised when attempting to hard-delete an asset with any financial
    history -- see FINANCIAL_RULES.md, "Asset Deletion Policy"."""


def _to_asset_out(asset) -> AssetOut:
    return AssetOut(
        id=asset.id,
        symbol=asset.symbol,
        name=asset.name,
        asset_type=asset.asset_type.value,
        market=asset.market,
        currency=asset.currency,
        strategy_bucket_id=asset.strategy_bucket_id,
        is_active=asset.is_active,
    )


async def list_active_assets(session: AsyncSession) -> list[AssetOut]:
    """Reuses the exact repository query the Portfolio Engine already
    uses (Phase 9 contract) -- never a separate/duplicated query."""
    assets = await get_active_assets(session)
    return [_to_asset_out(asset) for asset in assets]


async def list_assets(session: AsyncSession, *, include_inactive: bool = False) -> list[AssetOut]:
    """The admin listing (Phase 12) -- unlike `list_active_assets`, this
    can include inactive assets so they remain visible/reactivatable."""
    assets = await asset_repository.list_assets(session, include_inactive=include_inactive)
    return [_to_asset_out(asset) for asset in assets]


async def get_asset(session: AsyncSession, asset_id: UUID) -> AssetOut:
    asset = await asset_repository.get_asset_by_id(session, asset_id)
    if asset is None:
        raise AssetNotFoundError(f"Asset {asset_id} does not exist.")
    return _to_asset_out(asset)


async def _validate_strategy_bucket(session: AsyncSession, strategy_bucket_id: UUID | None) -> None:
    if strategy_bucket_id is None:
        return
    if not await asset_repository.strategy_bucket_exists(session, strategy_bucket_id):
        raise InvalidStrategyBucketError(f"Strategy bucket {strategy_bucket_id} does not exist.")


async def create_asset(session: AsyncSession, request: AssetCreateRequest) -> AssetOut:
    from app.models import Asset

    if await asset_repository.get_asset_by_symbol(session, request.symbol) is not None:
        raise DuplicateAssetSymbolError(f"Asset symbol {request.symbol!r} is already in use.")
    await _validate_strategy_bucket(session, request.strategy_bucket_id)

    asset = Asset(
        symbol=request.symbol,
        name=request.name,
        asset_type=request.asset_type,
        market=request.market,
        currency=request.currency,
        strategy_bucket_id=request.strategy_bucket_id,
    )
    session.add(asset)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise DuplicateAssetSymbolError(f"Asset symbol {request.symbol!r} is already in use.") from exc
    return _to_asset_out(asset)


async def update_asset(session: AsyncSession, asset_id: UUID, request: AssetUpdateRequest) -> AssetOut:
    asset = await asset_repository.get_asset_by_id(session, asset_id)
    if asset is None:
        raise AssetNotFoundError(f"Asset {asset_id} does not exist.")

    if request.currency is not None and request.currency != asset.currency:
        if await asset_repository.asset_has_transaction_or_price_history(session, asset_id):
            raise CurrencyChangeNotAllowedError(
                f"Asset {asset_id} has transaction or price history recorded in "
                f"{asset.currency!r} -- changing its currency now would silently "
                "reinterpret that history. Create a new asset instead if the "
                "instrument is genuinely priced in a different currency."
            )
        asset.currency = request.currency

    if request.name is not None:
        asset.name = request.name
    if request.asset_type is not None:
        asset.asset_type = request.asset_type
    if request.market is not None:
        asset.market = request.market
    if request.clear_strategy_bucket:
        asset.strategy_bucket_id = None
    elif request.strategy_bucket_id is not None:
        await _validate_strategy_bucket(session, request.strategy_bucket_id)
        asset.strategy_bucket_id = request.strategy_bucket_id

    await session.commit()
    return _to_asset_out(asset)


async def activate_asset(session: AsyncSession, asset_id: UUID) -> AssetOut:
    asset = await asset_repository.get_asset_by_id(session, asset_id)
    if asset is None:
        raise AssetNotFoundError(f"Asset {asset_id} does not exist.")
    asset.is_active = True
    await session.commit()
    return _to_asset_out(asset)


async def deactivate_asset(session: AsyncSession, asset_id: UUID) -> AssetOut:
    """Deactivation is always safe and always available, regardless of
    historical data -- it never deletes anything (see FINANCIAL_RULES.md,
    "Asset Deletion Policy")."""
    asset = await asset_repository.get_asset_by_id(session, asset_id)
    if asset is None:
        raise AssetNotFoundError(f"Asset {asset_id} does not exist.")
    asset.is_active = False
    await session.commit()
    return _to_asset_out(asset)


async def delete_asset(session: AsyncSession, asset_id: UUID) -> None:
    """Hard delete, permitted ONLY when the asset has zero historical
    data of any kind. Otherwise raises `AssetHasHistoricalDataError` --
    the caller should deactivate instead. See FINANCIAL_RULES.md, "Asset
    Deletion Policy"."""
    asset = await asset_repository.get_asset_by_id(session, asset_id)
    if asset is None:
        raise AssetNotFoundError(f"Asset {asset_id} does not exist.")
    if await asset_repository.asset_has_historical_data(session, asset_id):
        raise AssetHasHistoricalDataError(
            f"Asset {asset_id} has holdings, transactions, watchlist entries, "
            "snapshot items, or price observations on record and cannot be "
            "permanently deleted -- deactivate it instead."
        )
    await session.delete(asset)
    await session.commit()
