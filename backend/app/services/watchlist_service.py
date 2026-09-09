"""Orchestrates Watchlist CRUD: validates input, enforces the
add/re-enable/duplicate rules, and delegates persistence to the
repository layer.

Unlike the Phase 5-7 read-only engines, this is ordinary CRUD — it is
expected to write to `watchlist` (never to holdings/transactions/
snapshots/allocation_targets/portfolio_configs). Like the rest of the
service layer, it returns API-ready schemas, not ORM models.
"""

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Watchlist
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
    """Raised when the referenced watchlist_id does not exist."""


async def add_to_watchlist(session: AsyncSession, asset_id: UUID, notes: str | None = None) -> WatchlistOut:
    asset = await get_asset_by_id(session, asset_id)
    if asset is None:
        raise AssetNotFoundError(f"Asset {asset_id} does not exist.")
    if not asset.is_active:
        raise AssetInactiveError(f"Asset {asset_id} is inactive and cannot be watched.")

    existing = await get_watchlist_entry_by_asset_id(session, asset_id)
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
        entry = await get_watchlist_entry_by_id(session, existing.id)
        return to_watchlist_out(entry)

    entry = Watchlist(asset_id=asset_id, notes=notes)
    session.add(entry)
    await session.commit()
    entry = await get_watchlist_entry_by_id(session, entry.id)
    return to_watchlist_out(entry)


async def remove_from_watchlist(session: AsyncSession, watchlist_id: UUID) -> WatchlistOut:
    """Logical removal only: sets enabled=False and removed_at — never a
    physical delete (see DATABASE.md, "watchlist")."""
    entry = await get_watchlist_entry_by_id(session, watchlist_id)
    if entry is None:
        raise WatchlistEntryNotFoundError(f"Watchlist entry {watchlist_id} does not exist.")
    entry.enabled = False
    entry.removed_at = datetime.now(timezone.utc)
    await session.commit()
    return to_watchlist_out(entry)


async def update_watchlist_entry(
    session: AsyncSession, watchlist_id: UUID, *, enabled: bool | None = None, notes: str | None = None
) -> WatchlistOut:
    entry = await get_watchlist_entry_by_id(session, watchlist_id)
    if entry is None:
        raise WatchlistEntryNotFoundError(f"Watchlist entry {watchlist_id} does not exist.")
    if enabled is not None:
        entry.enabled = enabled
    if notes is not None:
        entry.notes = notes
    await session.commit()
    return to_watchlist_out(entry)


async def get_watchlist_entry(session: AsyncSession, watchlist_id: UUID) -> WatchlistOut:
    entry = await get_watchlist_entry_by_id(session, watchlist_id)
    if entry is None:
        raise WatchlistEntryNotFoundError(f"Watchlist entry {watchlist_id} does not exist.")
    return to_watchlist_out(entry)


async def list_watchlist(session: AsyncSession, *, enabled_only: bool = False) -> list[WatchlistOut]:
    entries = await list_watchlist_entries(session, enabled_only=enabled_only)
    return [to_watchlist_out(entry) for entry in entries]


async def list_evaluation_candidates(session: AsyncSession) -> list[Watchlist]:
    """Enabled watchlist entries with an active underlying asset — the
    only entries alert evaluation should ever consider. Returns ORM
    models (not schemas): this is an internal handoff to alert_service,
    never returned directly from an API route."""
    return await list_active_watchlist_entries_with_active_assets(session)
