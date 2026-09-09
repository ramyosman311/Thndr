import uuid

from sqlalchemy import select

from app.models import Asset
from app.services import watchlist_service
from app.services.watchlist_service import (
    AssetInactiveError,
    AssetNotFoundError,
    DuplicateWatchlistEntryError,
    WatchlistEntryNotFoundError,
)
from app.tests.conftest import make_asset


async def _make_active_asset(session, symbol="WATCHME"):
    asset = make_asset(symbol)
    session.add(asset)
    await session.commit()
    return asset


async def test_add_to_watchlist_creates_an_entry(db_session):
    asset = await _make_active_asset(db_session)
    entry = await watchlist_service.add_to_watchlist(db_session, asset.id, notes="worth watching")
    assert entry.asset_id == asset.id
    assert entry.asset_symbol == "WATCHME"
    assert entry.enabled is True
    assert entry.notes == "worth watching"
    assert entry.removed_at is None
    assert entry.alert_rule is None


async def test_add_to_watchlist_rejects_missing_asset(db_session):
    try:
        await watchlist_service.add_to_watchlist(db_session, uuid.uuid4())
        assert False, "expected AssetNotFoundError"
    except AssetNotFoundError:
        pass


async def test_add_to_watchlist_rejects_inactive_asset(db_session):
    asset = make_asset("INACTIVE1", is_active=False)
    db_session.add(asset)
    await db_session.commit()
    try:
        await watchlist_service.add_to_watchlist(db_session, asset.id)
        assert False, "expected AssetInactiveError"
    except AssetInactiveError:
        pass


async def test_add_to_watchlist_rejects_duplicate_for_same_asset(db_session):
    asset = await _make_active_asset(db_session)
    await watchlist_service.add_to_watchlist(db_session, asset.id)
    try:
        await watchlist_service.add_to_watchlist(db_session, asset.id)
        assert False, "expected DuplicateWatchlistEntryError"
    except DuplicateWatchlistEntryError:
        pass


async def test_re_adding_a_removed_entry_re_enables_it_instead_of_duplicating(db_session):
    asset = await _make_active_asset(db_session)
    first = await watchlist_service.add_to_watchlist(db_session, asset.id)
    await watchlist_service.remove_from_watchlist(db_session, first.id)

    re_added = await watchlist_service.add_to_watchlist(db_session, asset.id, notes="back on watch")
    assert re_added.id == first.id
    assert re_added.enabled is True
    assert re_added.removed_at is None
    assert re_added.notes == "back on watch"

    all_entries = await watchlist_service.list_watchlist(db_session)
    assert len([e for e in all_entries if e.asset_id == asset.id]) == 1


async def test_remove_from_watchlist_is_logical_not_physical(db_session):
    asset = await _make_active_asset(db_session)
    entry = await watchlist_service.add_to_watchlist(db_session, asset.id)
    removed = await watchlist_service.remove_from_watchlist(db_session, entry.id)
    assert removed.enabled is False
    assert removed.removed_at is not None

    # Still visible via list_watchlist (not enabled_only) — a logical
    # delete keeps the row for history, per DATABASE.md.
    all_entries = await watchlist_service.list_watchlist(db_session, enabled_only=False)
    assert any(e.id == entry.id for e in all_entries)

    enabled_only = await watchlist_service.list_watchlist(db_session, enabled_only=True)
    assert not any(e.id == entry.id for e in enabled_only)


async def test_remove_from_watchlist_rejects_missing_entry(db_session):
    try:
        await watchlist_service.remove_from_watchlist(db_session, uuid.uuid4())
        assert False, "expected WatchlistEntryNotFoundError"
    except WatchlistEntryNotFoundError:
        pass


async def test_update_watchlist_entry_can_disable_and_re_enable(db_session):
    asset = await _make_active_asset(db_session)
    entry = await watchlist_service.add_to_watchlist(db_session, asset.id)

    disabled = await watchlist_service.update_watchlist_entry(db_session, entry.id, enabled=False)
    assert disabled.enabled is False

    re_enabled = await watchlist_service.update_watchlist_entry(db_session, entry.id, enabled=True)
    assert re_enabled.enabled is True


async def test_update_watchlist_entry_rejects_missing_entry(db_session):
    try:
        await watchlist_service.update_watchlist_entry(db_session, uuid.uuid4(), enabled=False)
        assert False, "expected WatchlistEntryNotFoundError"
    except WatchlistEntryNotFoundError:
        pass


async def test_list_evaluation_candidates_excludes_disabled_entries(db_session):
    asset = await _make_active_asset(db_session, "CAND1")
    entry = await watchlist_service.add_to_watchlist(db_session, asset.id)
    await watchlist_service.update_watchlist_entry(db_session, entry.id, enabled=False)

    candidates = await watchlist_service.list_evaluation_candidates(db_session)
    assert not any(c.id == entry.id for c in candidates)


async def test_list_evaluation_candidates_excludes_assets_deactivated_after_being_watched(db_session):
    asset = await _make_active_asset(db_session, "CAND2")
    entry = await watchlist_service.add_to_watchlist(db_session, asset.id)

    result = await db_session.execute(select(Asset).where(Asset.id == asset.id))
    asset_row = result.scalar_one()
    asset_row.is_active = False
    await db_session.commit()

    candidates = await watchlist_service.list_evaluation_candidates(db_session)
    assert not any(c.id == entry.id for c in candidates)
