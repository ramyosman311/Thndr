"""Phase 16 (P0): financial core correctness — Portfolio Value vs
Investable Value vs Available Cash, the missing-price fallback, and the
existing (never auto-linked) BUY/SELL-vs-cash accounting model.

See FINANCIAL_RULES.md, "Portfolio Value vs Investable Value vs
Available Cash" and "Missing-Price Fallback" for the policy these tests
enforce, and DECISIONS.md, "Phase 16 — Financial Core & Cash Logic" for
why BUY/SELL are asserted to NOT move `available_cash` (an explicit,
disclosed scope boundary, not an oversight — see Test D below).
"""

from datetime import datetime, timezone
from decimal import Decimal

from app.models import AssetType, Holding
from app.services import transaction_service
from app.services.portfolio_service import get_portfolio_summary
from app.tests.conftest import make_asset, make_current_price, make_portfolio_config


def _now():
    return datetime.now(timezone.utc)


async def _configure_portfolio(session, **kwargs):
    config = make_portfolio_config(**kwargs)
    session.add(config)
    await session.commit()
    return config


# --- Test A: holding shares without cash ------------------------------------


async def test_a_holding_shares_without_cash_reports_zero_investable_cash(db_session):
    await _configure_portfolio(db_session, emergency_excluded=False)
    stock = make_asset("TMGHTEST", asset_type=AssetType.STOCK)
    db_session.add(stock)
    await db_session.commit()
    db_session.add(Holding(asset_id=stock.id, quantity=Decimal("20"), average_cost=Decimal("50")))
    await make_current_price(db_session, stock, Decimal("55"))
    await db_session.commit()

    summary = await get_portfolio_summary(db_session)

    assert summary.total_value == Decimal("1100.00")  # 20 * 55
    assert summary.invested_market_value == Decimal("1100.00")
    # The whole point of Phase 16: holding shares does NOT create
    # spendable cash, no matter how large the position's market value.
    assert summary.available_cash == Decimal("0.00")
    assert summary.total_value > summary.available_cash


# --- Test B: cash deposit ----------------------------------------------------


async def test_b_cash_deposit_increases_available_cash_and_portfolio_value_1_to_1(db_session):
    await _configure_portfolio(db_session, emergency_excluded=False)
    cash = make_asset("FREECASHB", asset_type=AssetType.CASH)
    db_session.add(cash)
    await db_session.commit()

    await transaction_service.create_transaction(
        db_session,
        asset_id=cash.id,
        transaction_type="DEPOSIT",
        quantity=Decimal("1000"),
        price=Decimal("1"),
        fees=Decimal("0"),
        transaction_date=_now(),
        notes=None,
    )

    summary = await get_portfolio_summary(db_session)

    assert summary.available_cash == Decimal("1000.00")
    assert summary.total_value == Decimal("1000.00")
    assert summary.invested_market_value == Decimal("0.00")


# --- Test C: cash deposit with an existing position -------------------------


async def test_c_cash_deposit_with_existing_position_never_inflates_available_cash(db_session):
    await _configure_portfolio(db_session, emergency_excluded=False)
    stock = make_asset("TMGHTESTC", asset_type=AssetType.STOCK)
    cash = make_asset("FREECASHC", asset_type=AssetType.CASH)
    db_session.add_all([stock, cash])
    await db_session.commit()
    db_session.add(Holding(asset_id=stock.id, quantity=Decimal("20"), average_cost=Decimal("50")))
    await make_current_price(db_session, stock, Decimal("55"))  # 20 * 55 = 1100
    await db_session.commit()

    await transaction_service.create_transaction(
        db_session,
        asset_id=cash.id,
        transaction_type="DEPOSIT",
        quantity=Decimal("500"),
        price=Decimal("1"),
        fees=Decimal("0"),
        transaction_date=_now(),
        notes=None,
    )

    summary = await get_portfolio_summary(db_session)

    assert summary.total_value == Decimal("1600.00")  # 1100 + 500
    assert summary.available_cash == Decimal("500.00")  # NEVER 1600.00
    assert summary.invested_market_value == Decimal("1100.00")


# --- Test D: sell proceeds ----------------------------------------------------


async def test_d_sell_proceeds_correct_quantity_cost_basis_and_realized_pnl(db_session):
    """Verifies the sell math itself (existing, correct, Phase 10
    behavior) AND makes explicit an intentional architecture boundary:
    this system has no automatic link between BUY/SELL and a cash
    balance -- `available_cash` is only ever moved by an explicit
    DEPOSIT/WITHDRAWAL against a CASH/SAVINGS asset (see
    domain/transaction_engine.py's module docstring and
    FINANCIAL_RULES.md, "Cash Flow Is Not Profit"). A SELL's proceeds
    therefore correctly do NOT appear as `available_cash` until the user
    separately records a DEPOSIT for them -- this is a disclosed scope
    boundary, not a bug (see DECISIONS.md, "Phase 16 — Financial Core &
    Cash Logic")."""
    await _configure_portfolio(db_session, emergency_excluded=False)
    stock = make_asset("SELLTESTD", asset_type=AssetType.STOCK)
    db_session.add(stock)
    await db_session.commit()
    db_session.add(Holding(asset_id=stock.id, quantity=Decimal("50"), average_cost=Decimal("50")))
    await make_current_price(db_session, stock, Decimal("60"))
    await db_session.commit()

    before = await get_portfolio_summary(db_session)
    assert before.available_cash == Decimal("0.00")

    result = await transaction_service.create_transaction(
        db_session,
        asset_id=stock.id,
        transaction_type="SELL",
        quantity=Decimal("30"),
        price=Decimal("60"),
        fees=Decimal("0"),
        transaction_date=_now(),
        notes=None,
    )

    assert result.holding.quantity == Decimal("20.00000000")
    assert result.holding.average_cost == Decimal("50.00000000")  # unchanged by a sell
    # realized_pnl = (30 * 60) - (30 * 50) = 1800 - 1500 = 300
    assert result.realized_pnl == Decimal("300.00")

    after = await get_portfolio_summary(db_session)
    assert after.invested_market_value == Decimal("1200.00")  # 20 remaining * 60
    # The sale proceeds are not auto-credited anywhere -- confirms the
    # documented boundary above rather than silently fabricating cash.
    assert after.available_cash == Decimal("0.00")


# --- Test E: missing market price WITH a historical price -------------------


async def test_e_missing_current_price_falls_back_to_historical_price(db_session):
    await _configure_portfolio(db_session, emergency_excluded=False)
    asset = make_asset("STALETESTE", asset_type=AssetType.STOCK)
    db_session.add(asset)
    await db_session.commit()
    db_session.add(Holding(asset_id=asset.id, quantity=Decimal("10"), average_cost=Decimal("40")))
    # A stale (aged-past-threshold) observation is still a real,
    # previously-recorded price -- `make_current_price` records "now";
    # we back-date it so `classify_staleness` marks it LAST_KNOWN.
    await make_current_price(db_session, asset, Decimal("45"))
    await db_session.commit()

    from sqlalchemy import update

    from app.models import AssetPrice

    await db_session.execute(
        update(AssetPrice)
        .where(AssetPrice.asset_id == asset.id)
        .values(recorded_at=datetime(2000, 1, 1, tzinfo=timezone.utc))
    )
    await db_session.commit()

    summary = await get_portfolio_summary(db_session)
    holding_pnl = next(h for h in summary.holdings_pnl if h.symbol == "STALETESTE")

    assert holding_pnl.price_status == "PENDING_SYNC"
    assert holding_pnl.current_price == Decimal("45.00000000")  # the historical price, used as-is
    assert holding_pnl.market_value == Decimal("450.00")  # 10 * 45, a real (if stale) estimate
    assert holding_pnl.unrealized_pnl == Decimal("0.00")  # never presented as a confirmed profit
    assert summary.is_complete is True
    assert summary.unpriced_asset_ids == []


# --- Test F: missing market price WITHOUT a historical price ----------------


async def test_f_missing_current_price_without_history_falls_back_to_average_cost(db_session):
    await _configure_portfolio(db_session, emergency_excluded=False)
    asset = make_asset("NOHISTTESTF", asset_type=AssetType.STOCK)
    db_session.add(asset)
    await db_session.commit()
    db_session.add(Holding(asset_id=asset.id, quantity=Decimal("10"), average_cost=Decimal("40")))
    await db_session.commit()  # no price observation ever recorded

    summary = await get_portfolio_summary(db_session)
    holding_pnl = next(h for h in summary.holdings_pnl if h.symbol == "NOHISTTESTF")

    assert holding_pnl.price_status == "PENDING_SYNC"
    assert holding_pnl.current_price == Decimal("40")  # the average-cost fallback
    assert holding_pnl.market_value == Decimal("400.00")  # 10 * 40 == cost_basis, by construction
    assert holding_pnl.cost_basis == Decimal("400.00")
    assert holding_pnl.unrealized_pnl == Decimal("0.00")
    assert summary.is_complete is True
    assert summary.unpriced_asset_ids == []
    # No NaN/undefined anywhere in the aggregates this holding feeds.
    assert summary.total_value == Decimal("400.00")
    assert summary.invested_market_value == Decimal("400.00")


# --- Test G: multiple buys and a partial sell --------------------------------


async def test_g_multiple_buys_then_partial_sell_preserves_correct_average_cost(db_session):
    await _configure_portfolio(db_session, emergency_excluded=False)
    asset = make_asset("MULTIBUYTESTG", asset_type=AssetType.STOCK)
    db_session.add(asset)
    await db_session.commit()

    await transaction_service.create_transaction(
        db_session, asset_id=asset.id, transaction_type="BUY", quantity=Decimal("10"),
        price=Decimal("100"), fees=Decimal("0"), transaction_date=_now(), notes=None,
    )
    result = await transaction_service.create_transaction(
        db_session, asset_id=asset.id, transaction_type="BUY", quantity=Decimal("10"),
        price=Decimal("120"), fees=Decimal("0"), transaction_date=_now(), notes=None,
    )
    # cost_basis = 1000 + 1200 = 2200; quantity = 20; average_cost = 110
    assert result.holding.quantity == Decimal("20.00000000")
    assert result.holding.average_cost == Decimal("110.00000000")

    result = await transaction_service.create_transaction(
        db_session, asset_id=asset.id, transaction_type="SELL", quantity=Decimal("5"),
        price=Decimal("150"), fees=Decimal("0"), transaction_date=_now(), notes=None,
    )
    # Selling at a different average cost must not change the average
    # cost of what remains (see domain/transaction_engine.py).
    assert result.holding.quantity == Decimal("15.00000000")
    assert result.holding.average_cost == Decimal("110.00000000")
    # realized_pnl = (5 * 150) - (5 * 110) = 750 - 550 = 200
    assert result.realized_pnl == Decimal("200.00")


# --- Test H: full sell (position closed) ------------------------------------


async def test_h_full_sell_closes_the_position_cleanly(db_session):
    await _configure_portfolio(db_session, emergency_excluded=False)
    asset = make_asset("FULLSELLTESTH", asset_type=AssetType.STOCK)
    db_session.add(asset)
    await db_session.commit()
    db_session.add(Holding(asset_id=asset.id, quantity=Decimal("10"), average_cost=Decimal("50")))
    await make_current_price(db_session, asset, Decimal("70"))
    await db_session.commit()

    result = await transaction_service.create_transaction(
        db_session, asset_id=asset.id, transaction_type="SELL", quantity=Decimal("10"),
        price=Decimal("70"), fees=Decimal("0"), transaction_date=_now(), notes=None,
    )

    assert result.holding.quantity == Decimal("0E-8")
    assert result.holding.average_cost == Decimal("0.00000000")
    # realized_pnl = (10 * 70) - (10 * 50) = 700 - 500 = 200, still
    # returned even though the position is now fully closed.
    assert result.realized_pnl == Decimal("200.00")

    summary = await get_portfolio_summary(db_session)
    # A zero-quantity holding contributes nothing and is not even listed
    # (see services/portfolio_service.py: `if holding is None or
    # holding.quantity == 0: continue`).
    assert all(h.symbol != "FULLSELLTESTH" for h in summary.holdings_pnl)
    assert summary.total_value == Decimal("0.00")
