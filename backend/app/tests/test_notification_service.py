"""Phase 19: Notification Center service tests — reuses the existing,
unmodified `alert_service.evaluate_alerts` (Phase 8) and
`recommendation_service.get_portfolio_recommendations` (Phase 18) as its
two sources, verifying only the NEW persistence/dedup/read-state layer
this phase adds on top of them.
"""

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import func, select

from app.models import (
    AllocationTarget,
    AssetType,
    Holding,
    Notification,
    PortfolioConfig,
    StrategyBucket,
    Transaction,
)
from app.services import notification_service, watchlist_service
from app.services import alert_service
from app.services.notification_service import (
    NotificationNotFoundError,
    list_notifications,
    mark_all_notifications_read,
    mark_notification_read,
)
from app.tests.conftest import make_asset, make_current_price, make_portfolio_config


async def _setup_recommendation_portfolio(session):
    """Same shape as test_recommendation_service.py's fixture: an
    emergency SAVINGS asset (excluded), a real non-emergency CASH asset
    (free cash, no target -- NO_TARGET), and one underweight Growth
    (STOCK) bucket with a target."""
    config = make_portfolio_config(emergency_excluded=True)
    session.add(config)
    await session.flush()

    emergency_bucket = StrategyBucket(portfolio_config_id=config.id, name="Emergency Reserve")
    session.add(emergency_bucket)
    await session.flush()
    emergency_asset = make_asset("NOTEMERG", asset_type=AssetType.SAVINGS, strategy_bucket_id=emergency_bucket.id)
    session.add(emergency_asset)
    await session.flush()
    config.emergency_asset_id = emergency_asset.id
    session.add(Holding(asset_id=emergency_asset.id, quantity=Decimal("1")))
    await make_current_price(session, emergency_asset, Decimal("100000"))

    cash_bucket = StrategyBucket(portfolio_config_id=config.id, name="Free Cash")
    session.add(cash_bucket)
    await session.flush()
    cash_asset = make_asset("NOTCASH", asset_type=AssetType.CASH, strategy_bucket_id=cash_bucket.id)
    session.add(cash_asset)
    await session.commit()

    # A second, unrelated STOCK bucket with real value and no target of
    # its own, purely so the portfolio's total investable value is
    # larger than Growth's own actual value -- without this, Growth
    # (with nothing else to compare against) would be its own 100% of
    # the investable base and therefore OVERWEIGHT, not underweight, for
    # any target below 100%.
    other_bucket = StrategyBucket(portfolio_config_id=config.id, name="Other Stocks")
    session.add(other_bucket)
    await session.flush()
    other_asset = make_asset("NOTOTHER", strategy_bucket_id=other_bucket.id)
    session.add(other_asset)
    await session.flush()
    session.add(Holding(asset_id=other_asset.id, quantity=Decimal("30")))  # 3000
    await make_current_price(session, other_asset, Decimal("100"))

    growth_bucket = StrategyBucket(portfolio_config_id=config.id, name="Growth")
    session.add(growth_bucket)
    await session.flush()
    growth_asset = make_asset("NOTGROWTH", strategy_bucket_id=growth_bucket.id)
    session.add(growth_asset)
    await session.flush()
    session.add(Holding(asset_id=growth_asset.id, quantity=Decimal("10")))  # 1000
    await make_current_price(session, growth_asset, Decimal("100"))
    # investable = 1000 (growth) + 3000 (other) + 0 (free cash) = 4000;
    # target 50% = 2000, actual 1000 -> underweight, gap 1000. With zero
    # available_cash (no CASH holding), this is NO_CAPACITY ->
    # RESTRICTED_ACTION -- never a false BUY (see Test D/E below).
    growth_target = AllocationTarget(
        portfolio_config_id=config.id, strategy_bucket_id=growth_bucket.id, target_percent=Decimal("50"), priority=1
    )
    session.add(growth_target)
    await session.commit()

    return config, cash_asset, growth_asset


async def _setup_breached_portfolio(session):
    config = make_portfolio_config(emergency_excluded=False)
    session.add(config)
    await session.flush()

    bucket = StrategyBucket(portfolio_config_id=config.id, name="Overweight Stocks")
    session.add(bucket)
    await session.flush()
    asset = make_asset("NOTOVER", strategy_bucket_id=bucket.id)
    session.add(asset)
    await session.flush()
    session.add(Holding(asset_id=asset.id, quantity=Decimal("100")))  # 10000
    await make_current_price(session, asset, Decimal("100"))
    target = AllocationTarget(
        portfolio_config_id=config.id, strategy_bucket_id=bucket.id, maximum_percent=Decimal("15"), priority=1
    )
    session.add(target)
    await session.commit()
    return config, bucket, asset


async def _setup_watched_price_asset(session, *, current_price=Decimal("150")):
    config = make_portfolio_config()
    session.add(config)
    await session.flush()
    asset = make_asset("NOTPRICE")
    session.add(asset)
    await session.flush()
    session.add(Holding(asset_id=asset.id, quantity=Decimal("1")))
    await make_current_price(session, asset, current_price)
    await session.commit()

    entry = await watchlist_service.add_to_watchlist(session, asset.id)
    rule = await alert_service.create_alert_rule(
        session, entry.id, price_target_enabled=True, price_target=Decimal("150")
    )
    return config, asset, entry, rule


async def _financial_counts(session):
    result = {}
    for model in (Holding, Transaction, AllocationTarget, StrategyBucket, PortfolioConfig):
        r = await session.execute(select(func.count()).select_from(model))
        result[model.__name__] = r.scalar_one()
    return result


# --- A: Maximum breach alert -------------------------------------------------


async def test_a_maximum_breach_generates_recommendation_alert_critical(db_session):
    await _setup_breached_portfolio(db_session)

    result = await list_notifications(db_session)
    breach = next(n for n in result.notifications if n.target_category == "Overweight Stocks")
    assert breach.category == "RECOMMENDATION_ALERT"
    assert breach.severity == "CRITICAL"
    assert breach.action == "REVIEW_RECOMMENDATIONS"
    assert breach.read is False


# --- B: Recommendation alert (restricted action, non-breach) ----------------


async def test_b_restricted_action_recommendation_generates_warning_notification(db_session):
    await _setup_recommendation_portfolio(db_session)

    result = await list_notifications(db_session)
    growth_notif = next(n for n in result.notifications if n.target_category == "Growth")
    assert growth_notif.category == "RECOMMENDATION_ALERT"
    assert growth_notif.severity == "WARNING"  # underweight + zero available cash -> RESTRICTED_ACTION


# --- C: Price alert -----------------------------------------------------------


async def test_c_price_target_reached_generates_price_alert(db_session):
    _, asset, _, _ = await _setup_watched_price_asset(db_session, current_price=Decimal("150"))

    result = await list_notifications(db_session)
    price_notif = next(n for n in result.notifications if n.target_asset == "NOTPRICE")
    assert price_notif.category == "PRICE_ALERT"
    assert price_notif.action == "OPEN_ASSET"
    assert "NOTPRICE" in price_notif.message


# --- D: Zero cash never produces a false BUY --------------------------------


async def test_d_zero_cash_underweight_never_produces_a_buy_notification(db_session):
    await _setup_recommendation_portfolio(db_session)

    result = await list_notifications(db_session)
    growth_notif = next(n for n in result.notifications if n.target_category == "Growth")
    # Zero available cash -> RESTRICTED_ACTION (WARNING), never the INFO-
    # severity CASH_DEPLOYMENT a fundable BUY would produce -- and
    # CASH_DEPLOYMENT/INFO recommendations are never notification-worthy
    # here in the first place (see domain/notification_engine.py).
    assert growth_notif.severity == "WARNING"
    assert growth_notif.category == "RECOMMENDATION_ALERT"
    assert not any(n.severity == "INFO" and n.category == "RECOMMENDATION_ALERT" for n in result.notifications)


# --- E: Allow New Buy false ---------------------------------------------------


async def test_e_allow_new_buy_false_never_produces_a_buy_notification(db_session):
    config = make_portfolio_config(emergency_excluded=False)
    db_session.add(config)
    await db_session.flush()
    bucket = StrategyBucket(portfolio_config_id=config.id, name="Gold")
    db_session.add(bucket)
    await db_session.flush()
    asset = make_asset("NOTGOLD", strategy_bucket_id=bucket.id)
    db_session.add(asset)
    await db_session.flush()
    session_asset_holding = Holding(asset_id=asset.id, quantity=Decimal("0"))
    db_session.add(session_asset_holding)
    await make_current_price(db_session, asset, Decimal("100"))
    target = AllocationTarget(
        portfolio_config_id=config.id,
        strategy_bucket_id=bucket.id,
        target_percent=Decimal("5"),
        allow_new_buy=False,
        priority=1,
    )
    db_session.add(target)
    await db_session.commit()

    result = await list_notifications(db_session)
    gold_notifs = [n for n in result.notifications if n.target_category == "Gold"]
    assert len(gold_notifs) == 1
    assert gold_notifs[0].category == "RECOMMENDATION_ALERT"
    assert gold_notifs[0].severity == "WARNING"


# --- F: Emergency Cash protected ----------------------------------------------


async def test_f_emergency_cash_never_generates_a_notification(db_session):
    await _setup_recommendation_portfolio(db_session)

    result = await list_notifications(db_session)
    assert all(n.target_category != "Emergency Reserve" for n in result.notifications)


# --- G: No Target preserved ---------------------------------------------------


async def test_g_no_target_never_generates_a_target_driven_notification(db_session):
    await _setup_recommendation_portfolio(db_session)

    result = await list_notifications(db_session)
    assert all(n.target_category != "Free Cash" for n in result.notifications)


# --- H: Duplicate protection ---------------------------------------------------


async def test_h_repeated_evaluation_never_creates_duplicate_notifications(db_session):
    await _setup_breached_portfolio(db_session)

    first = await list_notifications(db_session)
    second = await list_notifications(db_session)
    third = await list_notifications(db_session)

    assert len(first.notifications) == len(second.notifications) == len(third.notifications)
    assert {n.id for n in first.notifications} == {n.id for n in second.notifications} == {
        n.id for n in third.notifications
    }

    count = (await db_session.execute(select(func.count()).select_from(Notification))).scalar_one()
    assert count == len(first.notifications)


async def test_h_price_alert_dedup_across_repeated_evaluation(db_session):
    await _setup_watched_price_asset(db_session, current_price=Decimal("150"))

    await list_notifications(db_session)
    await list_notifications(db_session)

    count = (
        await db_session.execute(
            select(func.count()).select_from(Notification).where(Notification.target_asset == "NOTPRICE")
        )
    ).scalar_one()
    assert count == 1


# --- I: Read-only financial state ----------------------------------------------


async def test_i_notification_sync_never_mutates_financial_state(db_session):
    await _setup_breached_portfolio(db_session)
    await _setup_watched_price_asset(db_session, current_price=Decimal("150"))

    before = await _financial_counts(db_session)
    await list_notifications(db_session)
    await list_notifications(db_session)
    after = await _financial_counts(db_session)

    assert before == after


# --- J: Notification read state ------------------------------------------------


async def test_j_marking_one_notification_read_changes_only_that_row(db_session):
    await _setup_breached_portfolio(db_session)

    result = await list_notifications(db_session)
    target = result.notifications[0]
    assert target.read is False

    before = await _financial_counts(db_session)
    updated = await mark_notification_read(db_session, target.id)
    after = await _financial_counts(db_session)

    assert updated.read is True
    assert before == after

    refreshed = await list_notifications(db_session)
    refreshed_target = next(n for n in refreshed.notifications if n.id == target.id)
    assert refreshed_target.read is True
    # Untouched notifications remain unread.
    for other in refreshed.notifications:
        if other.id != target.id:
            assert other.read is False


async def test_j_mark_notification_read_rejects_missing_id(db_session):
    import uuid

    try:
        await mark_notification_read(db_session, uuid.uuid4())
        assert False, "expected NotificationNotFoundError"
    except NotificationNotFoundError:
        pass


async def test_j_mark_all_read_clears_unread_count(db_session):
    await _setup_breached_portfolio(db_session)
    await _setup_watched_price_asset(db_session, current_price=Decimal("150"))

    before_result = await list_notifications(db_session)
    assert before_result.unread_count > 0

    result = await mark_all_notifications_read(db_session)
    assert result.unread_count == 0
    assert all(n.read is True for n in result.notifications)
