from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.models import (
    AlertRule,
    AllocationTarget,
    Asset,
    AssetType,
    Holding,
    PortfolioConfig,
    PortfolioSnapshot,
    PortfolioSnapshotItem,
    StrategyBucket,
    Transaction,
    TransactionType,
    Watchlist,
)

EXPECTED_TABLES = {
    "assets",
    "holdings",
    "transactions",
    "portfolio_configs",
    "strategy_buckets",
    "allocation_targets",
    "watchlist",
    "alert_rules",
    "portfolio_snapshots",
    "portfolio_snapshot_items",
}


def make_asset(symbol: str = "TEST", asset_type: AssetType = AssetType.STOCK, **kwargs) -> Asset:
    return Asset(
        symbol=symbol,
        name=kwargs.pop("name", f"{symbol} Inc."),
        asset_type=asset_type,
        currency=kwargs.pop("currency", "EGP"),
        **kwargs,
    )


def make_portfolio_config(**kwargs) -> PortfolioConfig:
    return PortfolioConfig(
        name=kwargs.pop("name", "Main Portfolio"),
        base_currency=kwargs.pop("base_currency", "EGP"),
        **kwargs,
    )


async def test_migration_created_all_core_tables(db_session):
    result = await db_session.execute(
        text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
    )
    tables = {row[0] for row in result.fetchall()}
    assert EXPECTED_TABLES.issubset(tables)


async def test_foreign_key_rejects_nonexistent_asset(db_session):
    import uuid

    txn = Transaction(
        asset_id=uuid.uuid4(),
        transaction_type=TransactionType.BUY,
        quantity=Decimal("10"),
        price=Decimal("5"),
        transaction_date=datetime.now(timezone.utc),
    )
    db_session.add(txn)
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


async def test_asset_symbol_unique_constraint(db_session):
    db_session.add(make_asset(symbol="DUPTEST"))
    await db_session.commit()

    db_session.add(make_asset(symbol="DUPTEST"))
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


async def test_watchlist_duplicate_asset_rejected(db_session):
    asset = make_asset(symbol="WATCHDUP")
    db_session.add(asset)
    await db_session.flush()

    db_session.add(Watchlist(asset_id=asset.id))
    await db_session.commit()

    db_session.add(Watchlist(asset_id=asset.id))
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


async def test_holding_decimal_precision_round_trips_exactly(db_session):
    asset = make_asset(symbol="DECPREC")
    db_session.add(asset)
    await db_session.flush()

    precise_quantity = Decimal("123.45678901")
    precise_price = Decimal("0.00000001")
    holding = Holding(
        asset_id=asset.id,
        quantity=precise_quantity,
        average_cost=precise_price,
        current_price=precise_price,
    )
    db_session.add(holding)
    await db_session.commit()

    await db_session.refresh(holding)
    assert holding.quantity == precise_quantity
    assert holding.average_cost == precise_price
    assert isinstance(holding.quantity, Decimal)


async def test_holding_negative_quantity_rejected_by_check_constraint(db_session):
    asset = make_asset(symbol="NEGQTY")
    db_session.add(asset)
    await db_session.flush()

    db_session.add(Holding(asset_id=asset.id, quantity=Decimal("-1")))
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


async def test_snapshot_to_snapshot_items_relationship(db_session):
    config = make_portfolio_config()
    db_session.add(config)
    await db_session.flush()

    asset_a = make_asset(symbol="SNAPA")
    asset_b = make_asset(symbol="SNAPB")
    db_session.add_all([asset_a, asset_b])
    await db_session.flush()

    snapshot = PortfolioSnapshot(
        portfolio_config_id=config.id,
        snapshot_at=datetime.now(timezone.utc),
        label="test snapshot",
    )
    db_session.add(snapshot)
    await db_session.flush()

    db_session.add_all(
        [
            PortfolioSnapshotItem(snapshot_id=snapshot.id, asset_id=asset_a.id, value=Decimal("1000.50")),
            PortfolioSnapshotItem(snapshot_id=snapshot.id, asset_id=asset_b.id, value=Decimal("500.25")),
        ]
    )
    await db_session.commit()

    result = await db_session.execute(
        select(PortfolioSnapshot)
        .where(PortfolioSnapshot.id == snapshot.id)
    )
    loaded = result.scalar_one()
    await db_session.refresh(loaded, attribute_names=["items"])
    assert len(loaded.items) == 2
    assert {item.value for item in loaded.items} == {Decimal("1000.50"), Decimal("500.25")}


async def test_snapshot_item_duplicate_asset_rejected(db_session):
    config = make_portfolio_config()
    db_session.add(config)
    await db_session.flush()

    asset = make_asset(symbol="SNAPDUP")
    db_session.add(asset)
    await db_session.flush()

    snapshot = PortfolioSnapshot(portfolio_config_id=config.id, snapshot_at=datetime.now(timezone.utc))
    db_session.add(snapshot)
    await db_session.flush()

    db_session.add(PortfolioSnapshotItem(snapshot_id=snapshot.id, asset_id=asset.id, value=Decimal("1")))
    await db_session.commit()

    db_session.add(PortfolioSnapshotItem(snapshot_id=snapshot.id, asset_id=asset.id, value=Decimal("2")))
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


async def test_transaction_to_asset_relationship(db_session):
    asset = make_asset(symbol="TXNREL")
    db_session.add(asset)
    await db_session.flush()

    txn = Transaction(
        asset_id=asset.id,
        transaction_type=TransactionType.BUY,
        quantity=Decimal("10"),
        price=Decimal("25.5"),
        transaction_date=datetime.now(timezone.utc),
    )
    db_session.add(txn)
    await db_session.commit()

    result = await db_session.execute(select(Transaction).where(Transaction.id == txn.id))
    loaded = result.scalar_one()
    await db_session.refresh(loaded, attribute_names=["asset"])
    assert loaded.asset.symbol == "TXNREL"


async def test_allocation_target_minimum_le_maximum_check_constraint(db_session):
    config = make_portfolio_config()
    db_session.add(config)
    await db_session.flush()

    bucket = StrategyBucket(portfolio_config_id=config.id, name="Test Bucket")
    db_session.add(bucket)
    await db_session.flush()

    db_session.add(
        AllocationTarget(
            portfolio_config_id=config.id,
            strategy_bucket_id=bucket.id,
            minimum_percent=Decimal("50"),
            maximum_percent=Decimal("10"),
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


async def test_allocation_target_percent_out_of_range_rejected(db_session):
    config = make_portfolio_config()
    db_session.add(config)
    await db_session.flush()

    bucket = StrategyBucket(portfolio_config_id=config.id, name="Out Of Range Bucket")
    db_session.add(bucket)
    await db_session.flush()

    db_session.add(
        AllocationTarget(
            portfolio_config_id=config.id,
            strategy_bucket_id=bucket.id,
            target_percent=Decimal("150"),
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


async def test_allocation_target_independent_fields_persist(db_session):
    """target != maximum != allow_new_buy: verify each is stored and read
    back independently, per FINANCIAL_RULES.md."""
    config = make_portfolio_config()
    db_session.add(config)
    await db_session.flush()

    bucket = StrategyBucket(portfolio_config_id=config.id, name="Individual Stocks")
    db_session.add(bucket)
    await db_session.flush()

    target = AllocationTarget(
        portfolio_config_id=config.id,
        strategy_bucket_id=bucket.id,
        target_percent=None,
        maximum_percent=Decimal("15.00"),
        allow_new_buy=True,
        priority=1,
    )
    db_session.add(target)
    await db_session.commit()
    await db_session.refresh(target)

    assert target.target_percent is None
    assert target.maximum_percent == Decimal("15.00")
    assert target.allow_new_buy is True

    gold_bucket = StrategyBucket(portfolio_config_id=config.id, name="Gold")
    db_session.add(gold_bucket)
    await db_session.flush()
    gold_target = AllocationTarget(
        portfolio_config_id=config.id,
        strategy_bucket_id=gold_bucket.id,
        target_percent=Decimal("0"),
        allow_new_buy=False,
    )
    db_session.add(gold_target)
    await db_session.commit()
    await db_session.refresh(gold_target)

    assert gold_target.target_percent == Decimal("0")
    assert gold_target.allow_new_buy is False


async def test_emergency_asset_configuration(db_session):
    emergency_asset = make_asset(symbol="EMERGENCY", asset_type=AssetType.SAVINGS)
    db_session.add(emergency_asset)
    await db_session.flush()

    config = make_portfolio_config(
        emergency_asset_id=emergency_asset.id,
        emergency_excluded=True,
    )
    db_session.add(config)
    await db_session.commit()

    result = await db_session.execute(select(PortfolioConfig).where(PortfolioConfig.id == config.id))
    loaded = result.scalar_one()
    await db_session.refresh(loaded, attribute_names=["emergency_asset"])
    assert loaded.emergency_asset.symbol == "EMERGENCY"
    assert loaded.emergency_excluded is True


async def test_asset_belongs_to_configurable_strategy_bucket(db_session):
    config = make_portfolio_config()
    db_session.add(config)
    await db_session.flush()

    bucket = StrategyBucket(portfolio_config_id=config.id, name="Custom Future Category")
    db_session.add(bucket)
    await db_session.flush()

    asset = make_asset(symbol="BUCKETED", strategy_bucket_id=bucket.id)
    db_session.add(asset)
    await db_session.commit()

    result = await db_session.execute(select(Asset).where(Asset.id == asset.id))
    loaded = result.scalar_one()
    await db_session.refresh(loaded, attribute_names=["strategy_bucket"])
    assert loaded.strategy_bucket.name == "Custom Future Category"


async def test_deleting_asset_with_transaction_history_is_blocked(db_session):
    asset = make_asset(symbol="PROTECTED")
    db_session.add(asset)
    await db_session.flush()

    txn = Transaction(
        asset_id=asset.id,
        transaction_type=TransactionType.BUY,
        quantity=Decimal("5"),
        price=Decimal("100"),
        transaction_date=datetime.now(timezone.utc),
    )
    db_session.add(txn)
    await db_session.commit()
    asset_id, txn_id = asset.id, txn.id

    await db_session.delete(asset)
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()

    result = await db_session.execute(select(Transaction).where(Transaction.id == txn_id))
    assert result.scalar_one().asset_id == asset_id


async def test_deleting_asset_with_snapshot_history_is_blocked(db_session):
    config = make_portfolio_config()
    db_session.add(config)
    await db_session.flush()

    asset = make_asset(symbol="SNAPPROTECT")
    db_session.add(asset)
    await db_session.flush()

    snapshot = PortfolioSnapshot(portfolio_config_id=config.id, snapshot_at=datetime.now(timezone.utc))
    db_session.add(snapshot)
    await db_session.flush()
    db_session.add(PortfolioSnapshotItem(snapshot_id=snapshot.id, asset_id=asset.id, value=Decimal("1")))
    await db_session.commit()
    asset_id = asset.id

    await db_session.delete(asset)
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()

    result = await db_session.execute(
        select(PortfolioSnapshotItem).where(PortfolioSnapshotItem.asset_id == asset_id)
    )
    assert result.scalar_one() is not None


async def test_alert_rule_one_per_watchlist_entry(db_session):
    asset = make_asset(symbol="ALERTASSET")
    db_session.add(asset)
    await db_session.flush()

    watch = Watchlist(asset_id=asset.id)
    db_session.add(watch)
    await db_session.flush()

    db_session.add(AlertRule(watchlist_id=watch.id, price_target_enabled=True, price_target=Decimal("42.5")))
    await db_session.commit()

    db_session.add(AlertRule(watchlist_id=watch.id))
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


# --- Phase 15: snapshot idempotency + trigger_source constraints -----------


async def test_two_eod_snapshots_same_utc_day_violates_unique_index(db_session):
    config = make_portfolio_config()
    db_session.add(config)
    await db_session.flush()

    db_session.add(
        PortfolioSnapshot(
            portfolio_config_id=config.id,
            snapshot_at=datetime(2026, 4, 1, 8, 0, tzinfo=timezone.utc),
            trigger_source="EOD",
        )
    )
    await db_session.commit()

    db_session.add(
        PortfolioSnapshot(
            portfolio_config_id=config.id,
            snapshot_at=datetime(2026, 4, 1, 20, 0, tzinfo=timezone.utc),
            trigger_source="EOD",
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


async def test_eod_snapshots_on_different_utc_days_are_both_allowed(db_session):
    config = make_portfolio_config()
    db_session.add(config)
    await db_session.flush()

    db_session.add(
        PortfolioSnapshot(
            portfolio_config_id=config.id,
            snapshot_at=datetime(2026, 4, 1, 8, 0, tzinfo=timezone.utc),
            trigger_source="EOD",
        )
    )
    db_session.add(
        PortfolioSnapshot(
            portfolio_config_id=config.id,
            snapshot_at=datetime(2026, 4, 2, 8, 0, tzinfo=timezone.utc),
            trigger_source="EOD",
        )
    )
    await db_session.commit()  # must not raise

    count = (
        await db_session.execute(
            select(PortfolioSnapshot).where(PortfolioSnapshot.portfolio_config_id == config.id)
        )
    ).scalars().all()
    assert len(count) == 2


async def test_two_snapshots_for_the_same_source_transaction_violates_unique_index(db_session):
    config = make_portfolio_config()
    db_session.add(config)
    await db_session.flush()
    asset = make_asset(symbol="SNAPSOURCETXN", asset_type=AssetType.CASH)
    db_session.add(asset)
    await db_session.flush()
    txn = Transaction(
        asset_id=asset.id, transaction_type=TransactionType.DEPOSIT, quantity=Decimal("1"),
        price=Decimal("1"), transaction_date=datetime.now(timezone.utc),
    )
    db_session.add(txn)
    await db_session.flush()

    db_session.add(
        PortfolioSnapshot(
            portfolio_config_id=config.id, snapshot_at=datetime.now(timezone.utc),
            trigger_source="TRANSACTION", source_transaction_id=txn.id,
        )
    )
    await db_session.commit()

    db_session.add(
        PortfolioSnapshot(
            portfolio_config_id=config.id, snapshot_at=datetime.now(timezone.utc),
            trigger_source="TRANSACTION", source_transaction_id=txn.id,
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


async def test_trigger_source_rejects_an_arbitrary_value(db_session):
    config = make_portfolio_config()
    db_session.add(config)
    await db_session.flush()

    db_session.add(
        PortfolioSnapshot(
            portfolio_config_id=config.id, snapshot_at=datetime.now(timezone.utc), trigger_source="BOGUS"
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


async def test_pre_phase_15_style_snapshot_with_null_trigger_source_is_still_valid(db_session):
    """The five original dev-seed snapshots (trigger_source NULL) must
    remain a legal row shape after the Phase 15 migration -- nothing
    about the new columns/constraints requires backfilling them."""
    config = make_portfolio_config()
    db_session.add(config)
    await db_session.flush()

    db_session.add(PortfolioSnapshot(portfolio_config_id=config.id, snapshot_at=datetime.now(timezone.utc)))
    await db_session.commit()  # must not raise

    snapshot = (
        await db_session.execute(select(PortfolioSnapshot).where(PortfolioSnapshot.portfolio_config_id == config.id))
    ).scalar_one()
    assert snapshot.trigger_source is None
    assert snapshot.total_cost_basis is None
    assert snapshot.invested_capital is None
    assert snapshot.realized_pnl_cumulative is None
