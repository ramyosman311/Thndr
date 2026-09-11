"""Snapshot lifecycle service tests (Phase 15): EOD idempotency, post-
transaction financial computation, and the cumulative realized-P/L replay.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select

from app.models import AssetType, Holding, PortfolioSnapshot, StrategyBucket
from app.repositories.snapshot_repository import get_eod_snapshot_for_utc_date
from app.services import snapshot_service, transaction_service
from app.tests.conftest import make_asset, make_current_price, make_portfolio_config


def _now():
    return datetime.now(timezone.utc)


async def _configure_portfolio(session):
    config = make_portfolio_config()
    session.add(config)
    await session.commit()
    return config


# --- EOD idempotency ---------------------------------------------------------


async def test_eod_snapshot_is_created_when_none_exists_for_today(db_session):
    config = await _configure_portfolio(db_session)
    snapshot = await snapshot_service.create_eod_snapshot_if_missing(db_session, config=config)
    assert snapshot is not None
    assert snapshot.trigger_source == "EOD"
    assert snapshot.snapshot_at.date() == datetime.now(timezone.utc).date()


async def test_eod_snapshot_second_call_same_day_is_a_no_op(db_session):
    config = await _configure_portfolio(db_session)
    first = await snapshot_service.create_eod_snapshot_if_missing(db_session, config=config)
    second = await snapshot_service.create_eod_snapshot_if_missing(db_session, config=config)
    assert first is not None
    assert second is None

    count = (
        await db_session.execute(
            select(PortfolioSnapshot).where(
                PortfolioSnapshot.portfolio_config_id == config.id, PortfolioSnapshot.trigger_source == "EOD"
            )
        )
    ).scalars().all()
    assert len(count) == 1


# --- Post-transaction snapshot financial computation ------------------------


async def test_post_transaction_snapshot_reflects_multiple_assets(db_session):
    await _configure_portfolio(db_session)
    stock = make_asset("SNAPSTOCK", asset_type=AssetType.STOCK)
    cash = make_asset("SNAPCASH", asset_type=AssetType.CASH)
    db_session.add_all([stock, cash])
    await db_session.commit()

    # An existing STOCK holding with a usable price, priced independently
    # of the deposit that will trigger the snapshot. The cash asset also
    # needs its own usable price (Phase 15 does not special-case pricing
    # for CASH/SAVINGS assets -- see DECISIONS.md, "Phase 15 Known
    # Limitations": a real deployment sets this once via the existing
    # Phase 11 manual-price endpoint, same as any other asset).
    db_session.add(Holding(asset_id=stock.id, quantity=Decimal("10"), average_cost=Decimal("50")))
    await make_current_price(db_session, stock, Decimal("60"))
    await make_current_price(db_session, cash, Decimal("1"))
    await db_session.commit()

    result = await transaction_service.create_transaction(
        db_session, asset_id=cash.id, transaction_type="DEPOSIT", quantity=Decimal("1000"),
        price=Decimal("1"), fees=Decimal("0"), transaction_date=_now(), notes=None,
    )

    snapshot = (
        await db_session.execute(
            select(PortfolioSnapshot).where(PortfolioSnapshot.source_transaction_id == result.transaction.id)
        )
    ).scalar_one()
    # total_cost_basis = (10 * 50) [stock] + (1000 * 1) [cash] = 1500
    assert snapshot.total_cost_basis == Decimal("1500.00")
    # invested_capital only counts the recorded cash flow, never the
    # stock's cost basis (cash flow is not profit -- and buying a stock
    # is not an external flow either).
    assert snapshot.invested_capital == Decimal("1000.00")
    values = {item.asset_id: item.value for item in snapshot.items}
    assert values[stock.id] == Decimal("600.00")  # 10 * 60
    assert values[cash.id] == Decimal("1000.00")


async def test_post_transaction_snapshot_uses_average_cost_fallback_for_a_held_but_unpriced_asset(db_session):
    """Phase 16: a held asset with no live/stale price observation but a
    genuine (same-currency) average cost is now valued via the average-
    cost fallback rather than excluded — see
    services/portfolio_shared.resolve_valuation_price, which every
    valuation consumer (Portfolio Summary AND the snapshot lifecycle
    here) shares, so both agree on the same number for the same holding
    (FINANCIAL_RULES.md, "Portfolio Aggregation Consistency"). Cost
    basis (which never depended on price) is unaffected either way."""
    await _configure_portfolio(db_session)
    fallback_priced = make_asset("SNAPFALLBACK", asset_type=AssetType.FUND)
    genuinely_unpriced = make_asset("SNAPNOFALLBACK", asset_type=AssetType.FUND)
    cash = make_asset("SNAPUNPRICEDCASH", asset_type=AssetType.CASH)
    db_session.add_all([fallback_priced, genuinely_unpriced, cash])
    await db_session.commit()
    db_session.add(Holding(asset_id=fallback_priced.id, quantity=Decimal("5"), average_cost=Decimal("20")))
    # No average_cost given -- defaults to 0, so there is genuinely no
    # safe fallback price for this one either (see "if neither is
    # available" in FINANCIAL_RULES.md, "Missing-Price Fallback").
    db_session.add(Holding(asset_id=genuinely_unpriced.id, quantity=Decimal("3")))
    await make_current_price(db_session, cash, Decimal("1"))
    await db_session.commit()

    result = await transaction_service.create_transaction(
        db_session, asset_id=cash.id, transaction_type="DEPOSIT", quantity=Decimal("200"),
        price=Decimal("1"), fees=Decimal("0"), transaction_date=_now(), notes=None,
    )

    snapshot = (
        await db_session.execute(
            select(PortfolioSnapshot).where(PortfolioSnapshot.source_transaction_id == result.transaction.id)
        )
    ).scalar_one()
    # (5*20) + (3*0, no holding cost recorded) + (200*1)
    assert snapshot.total_cost_basis == Decimal("300.00")
    item_by_asset_id = {item.asset_id: item.value for item in snapshot.items}
    assert item_by_asset_id[fallback_priced.id] == Decimal("100.00")  # 5 * average_cost fallback of 20
    assert item_by_asset_id[cash.id] == Decimal("200.00")
    assert genuinely_unpriced.id not in item_by_asset_id  # still never fabricated a value from nothing


# --- Cumulative realized P/L replay ------------------------------------------


async def test_realized_pnl_cumulative_reflects_prior_sells_not_just_the_triggering_deposit(db_session):
    await _configure_portfolio(db_session)
    stock = make_asset("SNAPREALIZED", asset_type=AssetType.STOCK)
    cash = make_asset("SNAPREALIZEDCASH", asset_type=AssetType.CASH)
    db_session.add_all([stock, cash])
    await db_session.commit()

    await transaction_service.create_transaction(
        db_session, asset_id=stock.id, transaction_type="BUY", quantity=Decimal("10"),
        price=Decimal("100"), fees=Decimal("0"), transaction_date=datetime(2026, 1, 1, tzinfo=timezone.utc), notes=None,
    )
    await transaction_service.create_transaction(
        db_session, asset_id=stock.id, transaction_type="SELL", quantity=Decimal("4"),
        price=Decimal("120"), fees=Decimal("0"), transaction_date=datetime(2026, 1, 5, tzinfo=timezone.utc), notes=None,
    )
    # realized_pnl from that sell = (4*120) - (4*100) = 80

    result = await transaction_service.create_transaction(
        db_session, asset_id=cash.id, transaction_type="DEPOSIT", quantity=Decimal("500"),
        price=Decimal("1"), fees=Decimal("0"), transaction_date=datetime(2026, 1, 10, tzinfo=timezone.utc), notes=None,
    )

    snapshot = (
        await db_session.execute(
            select(PortfolioSnapshot).where(PortfolioSnapshot.source_transaction_id == result.transaction.id)
        )
    ).scalar_one()
    assert snapshot.realized_pnl_cumulative == Decimal("80")


async def test_realized_pnl_cumulative_never_double_counts_across_two_deposits(db_session):
    await _configure_portfolio(db_session)
    stock = make_asset("SNAPNODUP", asset_type=AssetType.STOCK)
    cash = make_asset("SNAPNODUPCASH", asset_type=AssetType.CASH)
    db_session.add_all([stock, cash])
    await db_session.commit()

    await transaction_service.create_transaction(
        db_session, asset_id=stock.id, transaction_type="BUY", quantity=Decimal("10"),
        price=Decimal("10"), fees=Decimal("0"), transaction_date=datetime(2026, 2, 1, tzinfo=timezone.utc), notes=None,
    )
    await transaction_service.create_transaction(
        db_session, asset_id=stock.id, transaction_type="SELL", quantity=Decimal("10"),
        price=Decimal("15"), fees=Decimal("0"), transaction_date=datetime(2026, 2, 2, tzinfo=timezone.utc), notes=None,
    )
    # realized_pnl = (10*15)-(10*10) = 50, from ONE sell event only

    first = await transaction_service.create_transaction(
        db_session, asset_id=cash.id, transaction_type="DEPOSIT", quantity=Decimal("100"),
        price=Decimal("1"), fees=Decimal("0"), transaction_date=datetime(2026, 2, 3, tzinfo=timezone.utc), notes=None,
    )
    second = await transaction_service.create_transaction(
        db_session, asset_id=cash.id, transaction_type="DEPOSIT", quantity=Decimal("50"),
        price=Decimal("1"), fees=Decimal("0"), transaction_date=datetime(2026, 2, 4, tzinfo=timezone.utc), notes=None,
    )

    snapshots = (
        await db_session.execute(
            select(PortfolioSnapshot).where(
                PortfolioSnapshot.source_transaction_id.in_([first.transaction.id, second.transaction.id])
            )
        )
    ).scalars().all()
    assert all(s.realized_pnl_cumulative == Decimal("50") for s in snapshots)


# --- Timezone: EOD boundary is UTC calendar day, not local/server time ------


async def test_eod_lookup_treats_two_utc_hours_of_the_same_day_as_one_day(db_session):
    """23:00 and 01:00 UTC on the SAME calendar date must be found as the
    same EOD day -- proves the boundary is a UTC calendar date, not a
    24-hour rolling window or a local-server-time boundary (see
    DECISIONS.md, "Phase 15 EOD Convention")."""
    config = await _configure_portfolio(db_session)
    same_day_morning = datetime(2026, 6, 15, 1, 0, tzinfo=timezone.utc)
    same_day_night = datetime(2026, 6, 15, 23, 0, tzinfo=timezone.utc)

    db_session.add(
        PortfolioSnapshot(portfolio_config_id=config.id, snapshot_at=same_day_morning, trigger_source="EOD")
    )
    await db_session.commit()

    found = await get_eod_snapshot_for_utc_date(db_session, config.id, same_day_night.date())
    assert found is not None


async def test_eod_lookup_treats_adjacent_utc_days_as_different(db_session):
    config = await _configure_portfolio(db_session)
    end_of_day_1 = datetime(2026, 6, 15, 23, 59, tzinfo=timezone.utc)

    db_session.add(PortfolioSnapshot(portfolio_config_id=config.id, snapshot_at=end_of_day_1, trigger_source="EOD"))
    await db_session.commit()

    next_day = (end_of_day_1 + timedelta(minutes=2)).date()
    found = await get_eod_snapshot_for_utc_date(db_session, config.id, next_day)
    assert found is None


# --- Financial integrity: EOD snapshot creation is purely observational ----


async def test_eod_snapshot_creation_does_not_touch_strategy_buckets_or_holdings(db_session):
    config = await _configure_portfolio(db_session)
    bucket = StrategyBucket(portfolio_config_id=config.id, name="EOD Untouched Bucket")
    db_session.add(bucket)
    stock = make_asset("EODINTEGRITY", asset_type=AssetType.STOCK)
    db_session.add(stock)
    await db_session.commit()
    db_session.add(Holding(asset_id=stock.id, quantity=Decimal("3"), average_cost=Decimal("10")))
    await db_session.commit()
    bucket_updated_at_before = bucket.updated_at

    await snapshot_service.create_eod_snapshot_if_missing(db_session, config=config)

    await db_session.refresh(bucket)
    holding_row = (await db_session.execute(select(Holding).where(Holding.asset_id == stock.id))).scalar_one()
    assert bucket.updated_at == bucket_updated_at_before
    assert holding_row.quantity == Decimal("3")
    assert holding_row.average_cost == Decimal("10")
