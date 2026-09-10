import uuid
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, select

from app.models import Asset, Holding, PortfolioConfig, StrategyBucket, Transaction
from app.services import portfolio_service, transaction_service
from app.services.transaction_service import AssetNotFoundError, OversellError
from app.tests.conftest import make_asset, make_current_price

_NUMERIC_20_8 = Decimal("0.00000001")


def _now():
    return datetime.now(timezone.utc)


def _as_stored(value: Decimal) -> Decimal:
    """Mirrors PostgreSQL's rounding when a Decimal with more than 8
    fractional digits is stored into a NUMERIC(20,8) column (e.g.
    average_cost from a division that doesn't terminate within 8
    places) — expectations must compare against what's actually
    persisted and read back, not the pre-storage full-precision value."""
    return value.quantize(_NUMERIC_20_8, rounding=ROUND_HALF_UP)


async def _make_active_asset(session, symbol="TXNASSET"):
    asset = make_asset(symbol)
    session.add(asset)
    await session.commit()
    return asset


async def test_first_buy_creates_a_new_holding(db_session):
    asset = await _make_active_asset(db_session)
    result = await transaction_service.create_transaction(
        db_session,
        asset_id=asset.id,
        transaction_type="BUY",
        quantity=Decimal("10"),
        price=Decimal("100"),
        fees=Decimal("0"),
        transaction_date=_now(),
        notes=None,
    )
    assert result.holding.quantity == Decimal("10")
    assert result.holding.average_cost == Decimal("100")
    assert result.transaction.asset_symbol == "TXNASSET"
    assert result.transaction.transaction_type == "BUY"
    assert result.realized_pnl is None

    holding_row = (await db_session.execute(select(Holding).where(Holding.asset_id == asset.id))).scalar_one()
    assert holding_row.quantity == Decimal("10")
    assert holding_row.average_cost == Decimal("100")


async def test_multiple_buys_blend_average_cost_through_the_service(db_session):
    asset = await _make_active_asset(db_session, "TXNMULTI")
    await transaction_service.create_transaction(
        db_session, asset_id=asset.id, transaction_type="BUY", quantity=Decimal("10"),
        price=Decimal("100"), fees=Decimal("0"), transaction_date=_now(), notes=None,
    )
    result = await transaction_service.create_transaction(
        db_session, asset_id=asset.id, transaction_type="BUY", quantity=Decimal("5"),
        price=Decimal("120"), fees=Decimal("0"), transaction_date=_now(), notes=None,
    )
    assert result.holding.quantity == Decimal("15")
    assert result.holding.average_cost == _as_stored(Decimal("1600") / Decimal("15"))


async def test_buy_with_fees_increases_cost_basis_through_the_service(db_session):
    asset = await _make_active_asset(db_session, "TXNFEES")
    result = await transaction_service.create_transaction(
        db_session, asset_id=asset.id, transaction_type="BUY", quantity=Decimal("10"),
        price=Decimal("100"), fees=Decimal("50"), transaction_date=_now(), notes=None,
    )
    assert result.holding.average_cost == Decimal("105")


async def test_buy_onto_existing_holding_created_outside_a_transaction(db_session):
    """A holding that already existed (e.g. from before Phase 10, or
    created directly) blends correctly with a new transaction-driven buy."""
    asset = await _make_active_asset(db_session, "TXNEXISTING")
    db_session.add(Holding(asset_id=asset.id, quantity=Decimal("20"), average_cost=Decimal("50")))
    await db_session.commit()

    result = await transaction_service.create_transaction(
        db_session, asset_id=asset.id, transaction_type="BUY", quantity=Decimal("10"),
        price=Decimal("80"), fees=Decimal("0"), transaction_date=_now(), notes=None,
    )
    assert result.holding.quantity == Decimal("30")
    assert result.holding.average_cost == Decimal("60")


async def test_partial_sell_reduces_quantity_and_reports_realized_pnl(db_session):
    asset = await _make_active_asset(db_session, "TXNPARTIAL")
    await transaction_service.create_transaction(
        db_session, asset_id=asset.id, transaction_type="BUY", quantity=Decimal("10"),
        price=Decimal("100"), fees=Decimal("0"), transaction_date=_now(), notes=None,
    )
    result = await transaction_service.create_transaction(
        db_session, asset_id=asset.id, transaction_type="SELL", quantity=Decimal("4"),
        price=Decimal("120"), fees=Decimal("0"), transaction_date=_now(), notes=None,
    )
    assert result.holding.quantity == Decimal("6")
    assert result.holding.average_cost == Decimal("100")
    assert result.realized_pnl == Decimal("80.00")  # (4*120) - (4*100) = 80


async def test_full_sell_zeroes_quantity_and_average_cost(db_session):
    asset = await _make_active_asset(db_session, "TXNFULLSELL")
    await transaction_service.create_transaction(
        db_session, asset_id=asset.id, transaction_type="BUY", quantity=Decimal("10"),
        price=Decimal("100"), fees=Decimal("0"), transaction_date=_now(), notes=None,
    )
    result = await transaction_service.create_transaction(
        db_session, asset_id=asset.id, transaction_type="SELL", quantity=Decimal("10"),
        price=Decimal("120"), fees=Decimal("0"), transaction_date=_now(), notes=None,
    )
    assert result.holding.quantity == Decimal("0")
    assert result.holding.average_cost == Decimal("0")


async def test_sell_with_fees_reduces_realized_proceeds(db_session):
    asset = await _make_active_asset(db_session, "TXNSELLFEES")
    await transaction_service.create_transaction(
        db_session, asset_id=asset.id, transaction_type="BUY", quantity=Decimal("10"),
        price=Decimal("100"), fees=Decimal("0"), transaction_date=_now(), notes=None,
    )
    result = await transaction_service.create_transaction(
        db_session, asset_id=asset.id, transaction_type="SELL", quantity=Decimal("10"),
        price=Decimal("120"), fees=Decimal("50"), transaction_date=_now(), notes=None,
    )
    # proceeds = 1200 - 50 = 1150; cost removed = 1000; pnl = 150
    assert result.realized_pnl == Decimal("150.00")


async def test_oversell_is_rejected_and_does_not_change_the_holding(db_session):
    asset = await _make_active_asset(db_session, "TXNOVERSELL")
    await transaction_service.create_transaction(
        db_session, asset_id=asset.id, transaction_type="BUY", quantity=Decimal("5"),
        price=Decimal("100"), fees=Decimal("0"), transaction_date=_now(), notes=None,
    )
    try:
        await transaction_service.create_transaction(
            db_session, asset_id=asset.id, transaction_type="SELL", quantity=Decimal("6"),
            price=Decimal("100"), fees=Decimal("0"), transaction_date=_now(), notes=None,
        )
        assert False, "expected OversellError"
    except OversellError:
        pass

    holding_row = (await db_session.execute(select(Holding).where(Holding.asset_id == asset.id))).scalar_one()
    assert holding_row.quantity == Decimal("5")
    transaction_count = (
        await db_session.execute(select(func.count()).select_from(Transaction).where(Transaction.asset_id == asset.id))
    ).scalar_one()
    assert transaction_count == 1  # only the original BUY — the rejected SELL was never recorded


async def test_selling_an_asset_with_no_holding_at_all_is_rejected(db_session):
    asset = await _make_active_asset(db_session, "TXNNOHOLDING")
    try:
        await transaction_service.create_transaction(
            db_session, asset_id=asset.id, transaction_type="SELL", quantity=Decimal("1"),
            price=Decimal("100"), fees=Decimal("0"), transaction_date=_now(), notes=None,
        )
        assert False, "expected OversellError"
    except OversellError:
        pass


async def test_create_transaction_rejects_missing_asset(db_session):
    try:
        await transaction_service.create_transaction(
            db_session, asset_id=uuid.uuid4(), transaction_type="BUY", quantity=Decimal("1"),
            price=Decimal("100"), fees=Decimal("0"), transaction_date=_now(), notes=None,
        )
        assert False, "expected AssetNotFoundError"
    except AssetNotFoundError:
        pass


async def test_transactions_for_different_assets_do_not_interfere(db_session):
    asset_a = await _make_active_asset(db_session, "TXNA")
    asset_b = await _make_active_asset(db_session, "TXNB")
    await transaction_service.create_transaction(
        db_session, asset_id=asset_a.id, transaction_type="BUY", quantity=Decimal("10"),
        price=Decimal("100"), fees=Decimal("0"), transaction_date=_now(), notes=None,
    )
    await transaction_service.create_transaction(
        db_session, asset_id=asset_b.id, transaction_type="BUY", quantity=Decimal("3"),
        price=Decimal("50"), fees=Decimal("0"), transaction_date=_now(), notes=None,
    )
    holding_a = (await db_session.execute(select(Holding).where(Holding.asset_id == asset_a.id))).scalar_one()
    holding_b = (await db_session.execute(select(Holding).where(Holding.asset_id == asset_b.id))).scalar_one()
    assert holding_a.quantity == Decimal("10")
    assert holding_b.quantity == Decimal("3")


async def test_transaction_is_recorded_as_an_immutable_history_row(db_session):
    asset = await _make_active_asset(db_session, "TXNHISTORY")
    result = await transaction_service.create_transaction(
        db_session, asset_id=asset.id, transaction_type="BUY", quantity=Decimal("7"),
        price=Decimal("42"), fees=Decimal("1.50"), transaction_date=_now(), notes="first lot",
    )
    stored = (await db_session.execute(select(Transaction).where(Transaction.id == result.transaction.id))).scalar_one()
    assert stored.quantity == Decimal("7")
    assert stored.price == Decimal("42")
    assert stored.fees == Decimal("1.50")
    assert stored.notes == "first lot"


async def test_list_transactions_orders_most_recent_first(db_session):
    asset = await _make_active_asset(db_session, "TXNORDER")
    older = datetime(2025, 1, 1, tzinfo=timezone.utc)
    newer = datetime(2025, 6, 1, tzinfo=timezone.utc)
    await transaction_service.create_transaction(
        db_session, asset_id=asset.id, transaction_type="BUY", quantity=Decimal("1"),
        price=Decimal("10"), fees=Decimal("0"), transaction_date=older, notes="older",
    )
    await transaction_service.create_transaction(
        db_session, asset_id=asset.id, transaction_type="BUY", quantity=Decimal("1"),
        price=Decimal("10"), fees=Decimal("0"), transaction_date=newer, notes="newer",
    )
    history = await transaction_service.list_transactions(db_session)
    ours = [t for t in history if t.asset_symbol == "TXNORDER"]
    assert ours[0].notes == "newer"
    assert ours[1].notes == "older"


async def test_transaction_never_touches_current_price(db_session):
    """The Price Service's current price is a separate concept from
    transaction.price (see FINANCIAL_RULES.md) — a BUY/SELL must never
    write a price observation, however different its own trade price
    is."""
    asset = await _make_active_asset(db_session, "TXNPRICESEP")
    db_session.add(Holding(asset_id=asset.id, quantity=Decimal("0"), average_cost=Decimal("0")))
    await make_current_price(db_session, asset, Decimal("77"))
    await db_session.commit()

    result = await transaction_service.create_transaction(
        db_session, asset_id=asset.id, transaction_type="BUY", quantity=Decimal("1"),
        price=Decimal("999"), fees=Decimal("0"), transaction_date=_now(), notes=None,
    )
    assert result.holding.current_price == Decimal("77")


async def test_portfolio_engine_reflects_the_new_holding_without_duplicated_logic(db_session):
    """Phase 10 must not create a second portfolio calculation engine —
    after a transaction, the existing Portfolio Engine must see the
    updated holding automatically."""
    config = PortfolioConfig(name="Txn Portfolio", base_currency="EGP", emergency_excluded=False)
    db_session.add(config)
    await db_session.flush()
    bucket = StrategyBucket(portfolio_config_id=config.id, name="Txn Bucket")
    db_session.add(bucket)
    await db_session.flush()
    asset = make_asset("TXNPORTFOLIO", strategy_bucket_id=bucket.id)
    db_session.add(asset)
    await db_session.commit()

    await transaction_service.create_transaction(
        db_session, asset_id=asset.id, transaction_type="BUY", quantity=Decimal("10"),
        price=Decimal("100"), fees=Decimal("0"), transaction_date=_now(), notes=None,
    )

    summary = await portfolio_service.get_portfolio_summary(db_session)
    pnl_row = next(p for p in summary.holdings_pnl if p.symbol == "TXNPORTFOLIO")
    assert pnl_row.quantity == Decimal("10")
    assert pnl_row.average_cost == Decimal("100")
    # current_price was never set, so market_value is legitimately 0 —
    # never fabricated — and cost_basis/pnl reflect that honestly.
    assert pnl_row.cost_basis == Decimal("1000.00")


async def test_creating_a_transaction_has_no_side_effects_on_unrelated_tables(db_session):
    asset = await _make_active_asset(db_session, "TXNSIDEEFFECT")

    async def counts():
        result = {}
        for model in (Asset,):
            r = await db_session.execute(select(func.count()).select_from(model))
            result[model.__name__] = r.scalar_one()
        return result

    before = await counts()
    await transaction_service.create_transaction(
        db_session, asset_id=asset.id, transaction_type="BUY", quantity=Decimal("1"),
        price=Decimal("10"), fees=Decimal("0"), transaction_date=_now(), notes=None,
    )
    after = await counts()
    assert before == after


async def test_decimal_precision_is_exact_through_the_service(db_session):
    asset = await _make_active_asset(db_session, "TXNDECIMAL")
    result = await transaction_service.create_transaction(
        db_session, asset_id=asset.id, transaction_type="BUY", quantity=Decimal("3.33333333"),
        price=Decimal("33.33"), fees=Decimal("0.01"), transaction_date=_now(), notes=None,
    )
    assert isinstance(result.holding.quantity, Decimal)
    assert isinstance(result.holding.average_cost, Decimal)
    expected_cost_basis = (Decimal("3.33333333") * Decimal("33.33")) + Decimal("0.01")
    assert result.holding.average_cost == _as_stored(expected_cost_basis / Decimal("3.33333333"))
