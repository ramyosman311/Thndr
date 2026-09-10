"""DEPOSIT/WITHDRAWAL cash-flow semantics (Phase 15).

Covers: CASH/SAVINGS-only restriction, the pinned-at-1 average cost
convention, insufficient-cash rejection, the atomic post-transaction
snapshot side effect, and financial-integrity proofs that a cash flow
never mutates anything outside its own transaction/holding/snapshot rows.
"""

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select

from app.models import AssetType, Holding, PortfolioSnapshot, StrategyBucket
from app.services import transaction_service
from app.services.transaction_service import (
    InsufficientCashError,
    InvalidCashFlowAmountError,
    InvalidCashFlowAssetError,
    PortfolioNotConfiguredError,
)
from app.tests.conftest import make_asset, make_portfolio_config


def _now():
    return datetime.now(timezone.utc)


async def _make_cash_asset(session, symbol="CASHFLOW", asset_type=AssetType.CASH):
    asset = make_asset(symbol, asset_type=asset_type)
    session.add(asset)
    await session.commit()
    return asset


async def _configure_portfolio(session):
    config = make_portfolio_config()
    session.add(config)
    await session.commit()
    return config


# --- Restriction to CASH/SAVINGS assets -------------------------------------


async def test_deposit_is_rejected_for_a_stock_asset(db_session):
    await _configure_portfolio(db_session)
    asset = make_asset("STOCKDEPOSIT", asset_type=AssetType.STOCK)
    db_session.add(asset)
    await db_session.commit()

    try:
        await transaction_service.create_transaction(
            db_session, asset_id=asset.id, transaction_type="DEPOSIT", quantity=Decimal("100"),
            price=Decimal("1"), fees=Decimal("0"), transaction_date=_now(), notes=None,
        )
        assert False, "expected InvalidCashFlowAssetError"
    except InvalidCashFlowAssetError:
        pass


async def test_deposit_is_allowed_for_a_savings_asset(db_session):
    await _configure_portfolio(db_session)
    asset = await _make_cash_asset(db_session, "SAVINGSDEPOSIT", AssetType.SAVINGS)
    result = await transaction_service.create_transaction(
        db_session, asset_id=asset.id, transaction_type="DEPOSIT", quantity=Decimal("100"),
        price=Decimal("1"), fees=Decimal("0"), transaction_date=_now(), notes=None,
    )
    assert result.holding.quantity == Decimal("100")


# --- Pinned-at-1 average cost / no artificial P&L ---------------------------


async def test_deposit_pins_average_cost_at_one_and_reports_no_realized_pnl(db_session):
    await _configure_portfolio(db_session)
    asset = await _make_cash_asset(db_session)
    result = await transaction_service.create_transaction(
        db_session, asset_id=asset.id, transaction_type="DEPOSIT", quantity=Decimal("5000"),
        price=Decimal("1"), fees=Decimal("0"), transaction_date=_now(), notes=None,
    )
    assert result.holding.quantity == Decimal("5000")
    assert result.holding.average_cost == Decimal("1")
    assert result.realized_pnl is None


async def test_second_deposit_onto_existing_cash_holding_accumulates(db_session):
    await _configure_portfolio(db_session)
    asset = await _make_cash_asset(db_session)
    await transaction_service.create_transaction(
        db_session, asset_id=asset.id, transaction_type="DEPOSIT", quantity=Decimal("1000"),
        price=Decimal("1"), fees=Decimal("0"), transaction_date=_now(), notes=None,
    )
    result = await transaction_service.create_transaction(
        db_session, asset_id=asset.id, transaction_type="DEPOSIT", quantity=Decimal("500"),
        price=Decimal("1"), fees=Decimal("0"), transaction_date=_now(), notes=None,
    )
    assert result.holding.quantity == Decimal("1500")
    assert result.holding.average_cost == Decimal("1")


async def test_withdrawal_decreases_cash_balance_and_reports_no_realized_pnl(db_session):
    await _configure_portfolio(db_session)
    asset = await _make_cash_asset(db_session)
    await transaction_service.create_transaction(
        db_session, asset_id=asset.id, transaction_type="DEPOSIT", quantity=Decimal("1000"),
        price=Decimal("1"), fees=Decimal("0"), transaction_date=_now(), notes=None,
    )
    result = await transaction_service.create_transaction(
        db_session, asset_id=asset.id, transaction_type="WITHDRAWAL", quantity=Decimal("300"),
        price=Decimal("1"), fees=Decimal("0"), transaction_date=_now(), notes=None,
    )
    assert result.holding.quantity == Decimal("700")
    assert result.holding.average_cost == Decimal("1")
    assert result.realized_pnl is None


async def test_withdrawal_exceeding_balance_is_rejected_and_does_not_change_holding(db_session):
    await _configure_portfolio(db_session)
    asset = await _make_cash_asset(db_session)
    await transaction_service.create_transaction(
        db_session, asset_id=asset.id, transaction_type="DEPOSIT", quantity=Decimal("100"),
        price=Decimal("1"), fees=Decimal("0"), transaction_date=_now(), notes=None,
    )
    try:
        await transaction_service.create_transaction(
            db_session, asset_id=asset.id, transaction_type="WITHDRAWAL", quantity=Decimal("500"),
            price=Decimal("1"), fees=Decimal("0"), transaction_date=_now(), notes=None,
        )
        assert False, "expected InsufficientCashError"
    except InsufficientCashError:
        pass

    holding_row = (await db_session.execute(select(Holding).where(Holding.asset_id == asset.id))).scalar_one()
    assert holding_row.quantity == Decimal("100")


async def test_withdrawal_from_asset_with_no_holding_at_all_is_rejected(db_session):
    await _configure_portfolio(db_session)
    asset = await _make_cash_asset(db_session, "NOHOLDINGCASH")
    try:
        await transaction_service.create_transaction(
            db_session, asset_id=asset.id, transaction_type="WITHDRAWAL", quantity=Decimal("1"),
            price=Decimal("1"), fees=Decimal("0"), transaction_date=_now(), notes=None,
        )
        assert False, "expected InsufficientCashError"
    except InsufficientCashError:
        pass


# --- Fixed 1:1 unit convention -----------------------------------------------


async def test_deposit_with_non_unit_price_is_rejected(db_session):
    await _configure_portfolio(db_session)
    asset = await _make_cash_asset(db_session)
    try:
        await transaction_service.create_transaction(
            db_session, asset_id=asset.id, transaction_type="DEPOSIT", quantity=Decimal("100"),
            price=Decimal("1.5"), fees=Decimal("0"), transaction_date=_now(), notes=None,
        )
        assert False, "expected InvalidCashFlowAmountError"
    except InvalidCashFlowAmountError:
        pass


async def test_deposit_with_nonzero_fees_is_rejected(db_session):
    await _configure_portfolio(db_session)
    asset = await _make_cash_asset(db_session)
    try:
        await transaction_service.create_transaction(
            db_session, asset_id=asset.id, transaction_type="DEPOSIT", quantity=Decimal("100"),
            price=Decimal("1"), fees=Decimal("5"), transaction_date=_now(), notes=None,
        )
        assert False, "expected InvalidCashFlowAmountError"
    except InvalidCashFlowAmountError:
        pass


# --- Post-transaction snapshot side effect ----------------------------------


async def test_deposit_creates_exactly_one_transaction_scoped_snapshot(db_session):
    await _configure_portfolio(db_session)
    asset = await _make_cash_asset(db_session)
    result = await transaction_service.create_transaction(
        db_session, asset_id=asset.id, transaction_type="DEPOSIT", quantity=Decimal("2500"),
        price=Decimal("1"), fees=Decimal("0"), transaction_date=datetime(2026, 3, 1, tzinfo=timezone.utc),
        notes=None,
    )
    snapshots = (
        await db_session.execute(
            select(PortfolioSnapshot).where(PortfolioSnapshot.source_transaction_id == result.transaction.id)
        )
    ).scalars().all()
    assert len(snapshots) == 1
    snapshot = snapshots[0]
    assert snapshot.trigger_source == "TRANSACTION"
    assert snapshot.invested_capital == Decimal("2500.00")
    assert snapshot.snapshot_at == datetime(2026, 3, 1, tzinfo=timezone.utc)


async def test_withdrawal_reduces_invested_capital_on_its_snapshot(db_session):
    await _configure_portfolio(db_session)
    asset = await _make_cash_asset(db_session)
    await transaction_service.create_transaction(
        db_session, asset_id=asset.id, transaction_type="DEPOSIT", quantity=Decimal("1000"),
        price=Decimal("1"), fees=Decimal("0"), transaction_date=_now(), notes=None,
    )
    result = await transaction_service.create_transaction(
        db_session, asset_id=asset.id, transaction_type="WITHDRAWAL", quantity=Decimal("400"),
        price=Decimal("1"), fees=Decimal("0"), transaction_date=_now(), notes=None,
    )
    snapshot = (
        await db_session.execute(
            select(PortfolioSnapshot).where(PortfolioSnapshot.source_transaction_id == result.transaction.id)
        )
    ).scalar_one()
    assert snapshot.invested_capital == Decimal("600.00")


async def test_deposit_without_portfolio_configured_is_rejected(db_session):
    """No portfolio_configs row exists -- the deposit must be rejected
    rather than silently skipping its snapshot. The service only reaches
    this check after `flush()` (not `commit()`); the FastAPI route's own
    session context manager (see core/database.py's `get_db_session`)
    rolls back automatically on the exception in real use, so nothing is
    ever durably persisted -- not re-verified at the DB level here to
    avoid coupling this test to this test-harness's own savepoint
    mechanics (see conftest.py's `db_session` fixture)."""
    asset = await _make_cash_asset(db_session, "NOCONFIGCASH")
    try:
        await transaction_service.create_transaction(
            db_session, asset_id=asset.id, transaction_type="DEPOSIT", quantity=Decimal("100"),
            price=Decimal("1"), fees=Decimal("0"), transaction_date=_now(), notes=None,
        )
        assert False, "expected PortfolioNotConfiguredError"
    except PortfolioNotConfiguredError:
        pass


# --- Financial integrity: no side effects on unrelated tables ---------------


async def test_deposit_does_not_touch_strategy_buckets_or_other_assets(db_session):
    config = await _configure_portfolio(db_session)
    bucket = StrategyBucket(portfolio_config_id=config.id, name="Untouched Bucket")
    db_session.add(bucket)
    other_asset = make_asset("UNTOUCHEDASSET", strategy_bucket_id=None)
    db_session.add(other_asset)
    await db_session.commit()
    bucket_updated_at_before = bucket.updated_at

    cash_asset = await _make_cash_asset(db_session, "DEPOSITSIDEEFFECT")
    await transaction_service.create_transaction(
        db_session, asset_id=cash_asset.id, transaction_type="DEPOSIT", quantity=Decimal("100"),
        price=Decimal("1"), fees=Decimal("0"), transaction_date=_now(), notes=None,
    )

    await db_session.refresh(bucket)
    await db_session.refresh(other_asset)
    assert bucket.updated_at == bucket_updated_at_before
    other_holding = (
        await db_session.execute(select(Holding).where(Holding.asset_id == other_asset.id))
    ).scalar_one_or_none()
    assert other_holding is None
