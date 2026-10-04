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

P0-3C: assets are shared market/reference data, but `assets.strategy_bucket_id`
points into ONE portfolio's strategy buckets. So that a user can neither read
nor overwrite another user's bucket assignment, the bucket id is masked to
null in responses unless it is one of the caller's own buckets, a bucket may
only be assigned if it belongs to the caller's portfolio, and an asset that
sits in another owned portfolio's bucket cannot be re-pointed from here. A
true per-portfolio asset-to-bucket association is a follow-up (see
DECISIONS.md, "P0-3C"). Who may mutate the shared asset rows themselves
(create/edit/activate/delete) is a separate authorization decision that is
not made here.
"""

from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories import asset_repository
from app.repositories.portfolio_repository import get_portfolio_config_for_user
from app.schemas.asset import AssetCreateRequest, AssetOut, AssetUpdateRequest


class AssetNotFoundError(Exception):
    """Raised when the referenced asset_id does not exist."""


class DuplicateAssetSymbolError(Exception):
    """Raised when creating/renaming an asset to a symbol already in use."""


class InvalidStrategyBucketError(Exception):
    """Raised when strategy_bucket_id does not reference an existing bucket."""


class StrategyBucketAssignmentLockedError(Exception):
    """Raised when changing the strategy bucket of an asset that is
    currently assigned into another user's portfolio (P0-3C). Deliberately
    says nothing about whose or which."""


class CurrencyChangeNotAllowedError(Exception):
    """Raised when changing currency on an asset that has transaction or
    price history -- see FINANCIAL_RULES.md, "Asset Edit Safety"."""


class AssetHasHistoricalDataError(Exception):
    """Raised when attempting to hard-delete an asset with any financial
    history -- see FINANCIAL_RULES.md, "Asset Deletion Policy"."""


async def _caller_bucket_ids(session: AsyncSession, user_id: UUID) -> tuple[UUID | None, set[UUID]]:
    """The caller's portfolio id (None if they have none) and the ids of
    that portfolio's strategy buckets."""
    config = await get_portfolio_config_for_user(session, user_id)
    if config is None:
        return None, set()
    return config.id, await asset_repository.list_strategy_bucket_ids_for_portfolio(session, config.id)


def _to_asset_out(asset, visible_bucket_ids: set[UUID]) -> AssetOut:
    bucket_id = asset.strategy_bucket_id if asset.strategy_bucket_id in visible_bucket_ids else None
    return AssetOut(
        id=asset.id,
        symbol=asset.symbol,
        name=asset.name,
        asset_type=asset.asset_type.value,
        market=asset.market,
        currency=asset.currency,
        strategy_bucket_id=bucket_id,
        is_active=asset.is_active,
    )


async def list_assets(
    session: AsyncSession, user_id: UUID, *, include_inactive: bool = False
) -> list[AssetOut]:
    """The admin listing (Phase 12) -- active-only by default, but can
    include inactive assets so they remain visible/reactivatable."""
    assets = await asset_repository.list_assets(session, include_inactive=include_inactive)
    _, visible = await _caller_bucket_ids(session, user_id)
    return [_to_asset_out(asset, visible) for asset in assets]


async def get_asset(session: AsyncSession, user_id: UUID, asset_id: UUID) -> AssetOut:
    asset = await asset_repository.get_asset_by_id(session, asset_id)
    if asset is None:
        raise AssetNotFoundError(f"Asset {asset_id} does not exist.")
    _, visible = await _caller_bucket_ids(session, user_id)
    return _to_asset_out(asset, visible)


async def _validate_strategy_bucket(
    session: AsyncSession, portfolio_config_id: UUID | None, strategy_bucket_id: UUID | None
) -> None:
    """A bucket may only be assigned if it is one of the CALLER's own -- the
    client-supplied id is never trusted as proof of ownership."""
    if strategy_bucket_id is None:
        return
    if portfolio_config_id is None or not await asset_repository.strategy_bucket_belongs_to_portfolio(
        session, strategy_bucket_id, portfolio_config_id
    ):
        raise InvalidStrategyBucketError(f"Strategy bucket {strategy_bucket_id} does not exist.")


async def create_asset(session: AsyncSession, user_id: UUID, request: AssetCreateRequest) -> AssetOut:
    from app.models import Asset

    if await asset_repository.get_asset_by_symbol(session, request.symbol) is not None:
        raise DuplicateAssetSymbolError(f"Asset symbol {request.symbol!r} is already in use.")
    portfolio_config_id, visible = await _caller_bucket_ids(session, user_id)
    await _validate_strategy_bucket(session, portfolio_config_id, request.strategy_bucket_id)

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
    return _to_asset_out(asset, visible)


async def update_asset(
    session: AsyncSession, user_id: UUID, asset_id: UUID, request: AssetUpdateRequest
) -> AssetOut:
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
    portfolio_config_id, visible = await _caller_bucket_ids(session, user_id)
    if request.clear_strategy_bucket or request.strategy_bucket_id is not None:
        current_bucket_id = asset.strategy_bucket_id
        if (
            current_bucket_id is not None
            and current_bucket_id not in visible
            and portfolio_config_id is not None
            and await asset_repository.bucket_belongs_to_another_owned_portfolio(
                session, current_bucket_id, portfolio_config_id
            )
        ):
            raise StrategyBucketAssignmentLockedError("This asset's strategy bucket cannot be changed.")
        if request.clear_strategy_bucket:
            asset.strategy_bucket_id = None
        else:
            await _validate_strategy_bucket(session, portfolio_config_id, request.strategy_bucket_id)
            asset.strategy_bucket_id = request.strategy_bucket_id

    await session.commit()
    return _to_asset_out(asset, visible)


async def activate_asset(session: AsyncSession, user_id: UUID, asset_id: UUID) -> AssetOut:
    asset = await asset_repository.get_asset_by_id(session, asset_id)
    if asset is None:
        raise AssetNotFoundError(f"Asset {asset_id} does not exist.")
    asset.is_active = True
    await session.commit()
    _, visible = await _caller_bucket_ids(session, user_id)
    return _to_asset_out(asset, visible)


async def deactivate_asset(session: AsyncSession, user_id: UUID, asset_id: UUID) -> AssetOut:
    """Deactivation is always safe and always available, regardless of
    historical data -- it never deletes anything (see FINANCIAL_RULES.md,
    "Asset Deletion Policy")."""
    asset = await asset_repository.get_asset_by_id(session, asset_id)
    if asset is None:
        raise AssetNotFoundError(f"Asset {asset_id} does not exist.")
    asset.is_active = False
    await session.commit()
    _, visible = await _caller_bucket_ids(session, user_id)
    return _to_asset_out(asset, visible)


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
