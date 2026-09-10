"""Financial integrity proof (Phase 12, spec sections 29 and 32):
administrative operations must NEVER alter historical transaction
prices/quantities/timestamps, holding quantities/average cost, realized
P&L, historical price observations, or historical snapshots.

Each test performs a real administrative write end-to-end, then asserts
the specific historical fact it could plausibly have corrupted is
byte-for-byte unchanged.
"""

from datetime import datetime, timezone
from decimal import Decimal

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.database import get_db_session
from app.main import app
from app.models import Holding, PortfolioSnapshot, PortfolioSnapshotItem, Transaction, TransactionType
from app.repositories import price_repository
from app.tests.conftest import make_asset, make_current_price, make_portfolio_config


@pytest_asyncio.fixture
async def client(db_session):
    async def _override_get_db_session():
        yield db_session

    app.dependency_overrides[get_db_session] = _override_get_db_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.pop(get_db_session, None)


async def test_asset_update_never_changes_transaction_history(db_session, client):
    asset = make_asset("INTEGRITY1", currency="EGP")
    db_session.add(asset)
    await db_session.flush()
    txn = Transaction(
        asset_id=asset.id, transaction_type=TransactionType.BUY, quantity=Decimal("10"),
        price=Decimal("123.45"), fees=Decimal("1.50"),
        transaction_date=datetime(2026, 1, 1, tzinfo=timezone.utc), notes="original",
    )
    db_session.add(txn)
    await db_session.commit()
    txn_id = txn.id

    response = await client.patch(f"/api/assets/{asset.id}", json={"name": "Renamed Asset", "market": "EGX"})
    assert response.status_code == 200

    reloaded = (await db_session.execute(select(Transaction).where(Transaction.id == txn_id))).scalar_one()
    assert reloaded.quantity == Decimal("10.00000000")
    assert reloaded.price == Decimal("123.45000000")
    assert reloaded.fees == Decimal("1.50")
    assert reloaded.transaction_date == datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert reloaded.notes == "original"


async def test_asset_update_never_changes_holding_accounting(db_session, client):
    asset = make_asset("INTEGRITY2")
    db_session.add(asset)
    await db_session.flush()
    holding = Holding(asset_id=asset.id, quantity=Decimal("42"), average_cost=Decimal("17.5"))
    db_session.add(holding)
    await db_session.commit()
    holding_id = holding.id

    response = await client.patch(f"/api/assets/{asset.id}", json={"name": "Renamed Again"})
    assert response.status_code == 200

    reloaded = (await db_session.execute(select(Holding).where(Holding.id == holding_id))).scalar_one()
    assert reloaded.quantity == Decimal("42.00000000")
    assert reloaded.average_cost == Decimal("17.50000000")


async def test_manual_price_submission_never_touches_transactions_or_holdings(db_session, client):
    asset = make_asset("INTEGRITY3", currency="EGP")
    db_session.add(asset)
    await db_session.flush()
    db_session.add(Holding(asset_id=asset.id, quantity=Decimal("5"), average_cost=Decimal("100")))
    txn = Transaction(
        asset_id=asset.id, transaction_type=TransactionType.BUY, quantity=Decimal("5"), price=Decimal("100"),
        transaction_date=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    db_session.add(txn)
    await db_session.commit()

    response = await client.post(
        f"/api/assets/{asset.id}/price/manual", json={"price": "999.99", "currency": "EGP"}
    )
    assert response.status_code == 201

    holding = (await db_session.execute(select(Holding).where(Holding.asset_id == asset.id))).scalar_one()
    assert holding.quantity == Decimal("5.00000000")
    assert holding.average_cost == Decimal("100.00000000")

    reloaded_txn = (await db_session.execute(select(Transaction).where(Transaction.id == txn.id))).scalar_one()
    assert reloaded_txn.price == Decimal("100.00000000")
    assert reloaded_txn.quantity == Decimal("5.00000000")


async def test_price_config_upsert_never_writes_a_price_observation(db_session, client):
    asset = make_asset("INTEGRITY4")
    db_session.add(asset)
    await db_session.flush()
    await make_current_price(db_session, asset, Decimal("50"))
    await db_session.commit()

    before = await price_repository.list_price_history(db_session, asset.id)
    assert len(before) == 1

    response = await client.put(
        f"/api/assets/{asset.id}/price-config",
        json={"primary_provider": "yahoo", "primary_provider_symbol": "X", "automated_fetching_enabled": True},
    )
    assert response.status_code == 200

    after = await price_repository.list_price_history(db_session, asset.id)
    assert len(after) == 1
    assert after[0].id == before[0].id
    assert after[0].price == Decimal("50.00000000")


async def test_portfolio_config_update_never_touches_snapshots(db_session, client):
    config = make_portfolio_config(name="Snapshotted", base_currency="EGP")
    db_session.add(config)
    await db_session.flush()
    asset = make_asset("INTEGRITY5")
    db_session.add(asset)
    await db_session.flush()
    snapshot = PortfolioSnapshot(portfolio_config_id=config.id, snapshot_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    db_session.add(snapshot)
    await db_session.flush()
    item = PortfolioSnapshotItem(snapshot_id=snapshot.id, asset_id=asset.id, value=Decimal("777.00"))
    db_session.add(item)
    await db_session.commit()
    item_id = item.id

    response = await client.patch("/api/portfolio/config", json={"name": "Renamed Portfolio"})
    assert response.status_code == 200

    reloaded_item = (
        await db_session.execute(select(PortfolioSnapshotItem).where(PortfolioSnapshotItem.id == item_id))
    ).scalar_one()
    assert reloaded_item.value == Decimal("777.00")


async def test_strategy_target_update_never_alters_realized_pnl_from_a_prior_sell(db_session, client):
    """Realized P&L is never stored as a ledger (see FINANCIAL_RULES.md,
    "Realized P&L") -- this proves the transaction record it was
    computed from stays byte-for-byte unchanged after an unrelated
    strategy configuration write, which is the only way realized P&L
    could ever silently drift."""
    config = make_portfolio_config()
    db_session.add(config)
    await db_session.flush()
    asset = make_asset("INTEGRITY6")
    db_session.add(asset)
    await db_session.flush()
    sell = Transaction(
        asset_id=asset.id, transaction_type=TransactionType.SELL, quantity=Decimal("3"), price=Decimal("55"),
        fees=Decimal("2"), transaction_date=datetime(2026, 2, 1, tzinfo=timezone.utc),
    )
    db_session.add(sell)
    await db_session.commit()

    bucket_response = await client.post("/api/strategy/buckets", json={"name": "Unrelated Bucket"})
    assert bucket_response.status_code == 201
    target_response = await client.post(
        "/api/strategy/targets",
        json={"strategy_bucket_id": bucket_response.json()["id"], "target_percent": "25"},
    )
    assert target_response.status_code == 201

    reloaded = (await db_session.execute(select(Transaction).where(Transaction.id == sell.id))).scalar_one()
    assert reloaded.price == Decimal("55.00000000")
    assert reloaded.quantity == Decimal("3.00000000")
    assert reloaded.fees == Decimal("2.00")


async def test_asset_price_history_row_count_unaffected_by_unrelated_admin_writes(db_session, client):
    asset = make_asset("INTEGRITY7")
    db_session.add(asset)
    await db_session.flush()
    await make_current_price(db_session, asset, Decimal("10"))
    await db_session.commit()

    before_count = len(await price_repository.list_price_history(db_session, asset.id))

    await client.patch(f"/api/assets/{asset.id}", json={"market": "EGX"})
    await client.post(f"/api/assets/{asset.id}/deactivate")
    await client.post(f"/api/assets/{asset.id}/activate")

    after_count = len(await price_repository.list_price_history(db_session, asset.id))
    assert after_count == before_count == 1
