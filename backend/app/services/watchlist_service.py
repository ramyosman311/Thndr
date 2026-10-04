"""Orchestrates Watchlist CRUD: validates input, enforces the
add/re-enable/duplicate rules, and delegates persistence to the
repository layer.

P0-3C: the watchlist is user-owned. Every function takes the verified
`user_id`, resolves that user's portfolio server-side, and only ever reads
or writes entries belonging to it -- a watchlist id (or asset id) from
another portfolio behaves exactly like one that doesn't exist. Assets are
shared reference data and are looked up globally.

Unlike the Phase 5-7 read-only engines, this is ordinary CRUD — it is
expected to write to `watchlist` (never to holdings/transactions/
snapshots/allocation_targets/portfolio_configs). Like the rest of the
service layer, it returns API-ready schemas, not ORM models.
"""

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import PortfolioConfig, Watchlist
from app.repositories.portfolio_repository import get_portfolio_config_for_user
from app.repositories.watchlist_repository import (
    get_asset_by_id,
    get_watchlist_entry_by_asset_id,
    get_watchlist_entry_by_id,
    list_active_watchlist_entries_with_active_assets,
    list_watchlist_entries,
)
from app.schemas.watchlist import WatchlistOut
from app.services.watchlist_shared import to_watchlist_out


class AssetNotFoundError(Exception):
    """Raised when the referenced asset_id does not exist."""


class AssetInactiveError(Exception):
    """Raised when attempting to watch an inactive asset."""


class DuplicateWatchlistEntryError(Exception):
    """Raised when the asset is already actively watched."""


class WatchlistEntryNotFoundError(Exception):
    """Raised when the referenced watchlist_id does not exist (in the
    caller's portfolio)."""


class PortfolioNotConfiguredError(Exception):
    """Raised when the caller has no portfolio yet -- a watchlist entry
    belongs to a portfolio, so none can be created before one exists."""


async def require_portfolio(session: AsyncSession, user_id: UUID) -> PortfolioConfig:
    config = await get_portfolio_config_for_user(session, user_id)
    if config is None:
        raise PortfolioNotConfiguredError("No portfolio configuration exists yet.")
    return config


async def _portfolio_or_entry_not_found(session: AsyncSession, user_id: UUID, watchlist_id: UUID) -> PortfolioConfig:
    """For operations addressed by watchlist id: a caller with no portfolio
    has no entries at all, so the id is simply "not found" -- the same
    answer as an id that belongs to someone else."""
    config = await get_portfolio_config_for_user(session, user_id)
    if config is None:
        raise WatchlistEntryNotFoundError(f"Watchlist entry {watchlist_id} does not exist.")
    return config


async def add_to_watchlist(
    session: AsyncSession, user_id: UUID, asset_id: UUID, notes: str | None = None
) -> WatchlistOut:
    config = await require_portfolio(session, user_id)
    asset = await get_asset_by_id(session, asset_id)
    if asset is None:
        raise AssetNotFoundError(f"Asset {asset_id} does not exist.")
    if not asset.is_active:
        raise AssetInactiveError(f"Asset {asset_id} is inactive and cannot be watched.")

    existing = await get_watchlist_entry_by_asset_id(session, asset_id, config.id)
    if existing is not None:
        if existing.enabled:
            raise DuplicateWatchlistEntryError(f"Asset {asset_id} is already on the watchlist.")
        # Re-adding a previously removed entry re-enables the existing
        # row instead of creating a duplicate (see DATABASE.md).
        existing.enabled = True
        existing.removed_at = None
        if notes is not None:
            existing.notes = notes
        await session.commit()
        entry = await get_watchlist_entry_by_id(session, existing.id, config.id)
        return to_watchlist_out(entry)

    entry = Watchlist(portfolio_config_id=config.id, asset_id=asset_id, notes=notes)
    session.add(entry)
    await session.commit()
    entry = await get_watchlist_entry_by_id(session, entry.id, config.id)
    return to_watchlist_out(entry)


async def remove_from_watchlist(session: AsyncSession, user_id: UUID, watchlist_id: UUID) -> WatchlistOut:
    """Logical removal only: sets enabled=False and removed_at — never a
    physical delete (see DATABASE.md, "watchlist")."""
    config = await _portfolio_or_entry_not_found(session, user_id, watchlist_id)
    entry = await get_watchlist_entry_by_id(session, watchlist_id, config.id)
    if entry is None:
        raise WatchlistEntryNotFoundError(f"Watchlist entry {watchlist_id} does not exist.")
    entry.enabled = False
    entry.removed_at = datetime.now(timezone.utc)
    await session.commit()
    return to_watchlist_out(entry)


async def update_watchlist_entry(
    session: AsyncSession, user_id: UUID, watchlist_id: UUID, *, enabled: bool | None = None, notes: str | None = None
) -> WatchlistOut:
    config = await _portfolio_or_entry_not_found(session, user_id, watchlist_id)
    entry = await get_watchlist_entry_by_id(session, watchlist_id, config.id)
    if entry is None:
        raise WatchlistEntryNotFoundError(f"Watchlist entry {watchlist_id} does not exist.")
    if enabled is not None:
        entry.enabled = enabled
    if notes is not None:
        entry.notes = notes
    await session.commit()
    return to_watchlist_out(entry)


async def get_watchlist_entry(session: AsyncSession, user_id: UUID, watchlist_id: UUID) -> WatchlistOut:
    config = await _portfolio_or_entry_not_found(session, user_id, watchlist_id)
    entry = await get_watchlist_entry_by_id(session, watchlist_id, config.id)
    if entry is None:
        raise WatchlistEntryNotFoundError(f"Watchlist entry {watchlist_id} does not exist.")
    return to_watchlist_out(entry)


async def list_watchlist(
    session: AsyncSession, user_id: UUID, *, enabled_only: bool = False
) -> list[WatchlistOut]:
    """The caller's own watchlist. With no portfolio there is nothing to
    show -- an empty list, never another user's entries."""
    config = await get_portfolio_config_for_user(session, user_id)
    if config is None:
        return []
    entries = await list_watchlist_entries(session, config.id, enabled_only=enabled_only)
    return [to_watchlist_out(entry) for entry in entries]


async def list_evaluation_candidates(session: AsyncSession, portfolio_config_id: UUID) -> list[Watchlist]:
    """Enabled watchlist entries, in THIS portfolio, with an active
    underlying asset — the only entries alert evaluation should ever
    consider. Returns ORM models (not schemas): this is an internal handoff
    to alert_service, never returned directly from an API route."""
    return await list_active_watchlist_entries_with_active_assets(session, portfolio_config_id)
