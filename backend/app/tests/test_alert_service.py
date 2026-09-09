import uuid
from decimal import Decimal

from sqlalchemy import func, select

from app.domain.alert_engine import AlertCheckResult
from app.models import (
    AllocationTarget,
    Asset,
    AssetType,
    Holding,
    PortfolioConfig,
    PortfolioSnapshot,
    StrategyBucket,
    Transaction,
)
from app.services import alert_service, watchlist_service
from app.services.alert_service import (
    AlertRuleNotFoundError,
    DuplicateAlertRuleError,
    InvalidAlertRuleConfigurationError,
)
from app.services.watchlist_service import WatchlistEntryNotFoundError
from app.tests.conftest import make_asset


class RecordingNotifier:
    def __init__(self):
        self.dispatched: list[tuple[AlertCheckResult, str, str]] = []

    async def dispatch(self, event, *, asset_symbol, watchlist_id):
        self.dispatched.append((event, asset_symbol, watchlist_id))


async def _setup_watched_bucket(
    session,
    *,
    asset_value=Decimal("2000"),
    other_value=Decimal("8000"),
    current_price=Decimal("100"),
    bucket_maximum_percent=None,
    bucket_target_percent=None,
    emergency=False,
    symbol="ALERTME",
):
    """A minimal, real portfolio: one watched asset in its own bucket
    (with a real, computable risk_allocation_percent) plus a second,
    unrelated bucket so the watched bucket's percentage is meaningfully
    less than 100%."""
    config = PortfolioConfig(name="Alert Test Portfolio", base_currency="EGP", emergency_excluded=emergency)
    session.add(config)
    await session.flush()

    bucket = StrategyBucket(portfolio_config_id=config.id, name="Watched Bucket")
    session.add(bucket)
    await session.flush()

    asset = make_asset(symbol, strategy_bucket_id=bucket.id)
    session.add(asset)
    await session.flush()
    quantity = (asset_value / current_price) if current_price != 0 else Decimal("0")
    session.add(Holding(asset_id=asset.id, quantity=quantity, current_price=current_price))

    if emergency:
        config.emergency_asset_id = asset.id

    if bucket_maximum_percent is not None or bucket_target_percent is not None:
        session.add(
            AllocationTarget(
                portfolio_config_id=config.id,
                strategy_bucket_id=bucket.id,
                target_percent=bucket_target_percent,
                maximum_percent=bucket_maximum_percent,
                priority=1,
            )
        )

    other_bucket = StrategyBucket(portfolio_config_id=config.id, name="Other")
    session.add(other_bucket)
    await session.flush()
    other_asset = make_asset("OTHERASSET", strategy_bucket_id=other_bucket.id)
    session.add(other_asset)
    await session.flush()
    session.add(Holding(asset_id=other_asset.id, quantity=other_value, current_price=Decimal("1")))

    await session.commit()
    return config, bucket, asset


async def _watch_with_rule(session, asset, **rule_fields):
    entry = await watchlist_service.add_to_watchlist(session, asset.id)
    rule = await alert_service.create_alert_rule(session, entry.id, **rule_fields)
    return entry, rule


# --- Alert rule CRUD ---------------------------------------------------------


async def test_create_alert_rule_defaults_when_nothing_enabled(db_session):
    _, _, asset = await _setup_watched_bucket(db_session)
    entry = await watchlist_service.add_to_watchlist(db_session, asset.id)
    rule = await alert_service.create_alert_rule(db_session, entry.id)
    assert rule.enabled is True
    assert rule.allocation_alert_enabled is False
    assert rule.price_target_enabled is False
    assert rule.dip_buy_enabled is False
    assert rule.last_triggered_at is None


async def test_create_alert_rule_rejects_missing_watchlist(db_session):
    try:
        await alert_service.create_alert_rule(db_session, uuid.uuid4())
        assert False, "expected WatchlistEntryNotFoundError"
    except WatchlistEntryNotFoundError:
        pass


async def test_create_alert_rule_rejects_duplicate_for_same_watchlist_entry(db_session):
    _, _, asset = await _setup_watched_bucket(db_session)
    entry = await watchlist_service.add_to_watchlist(db_session, asset.id)
    await alert_service.create_alert_rule(db_session, entry.id)
    try:
        await alert_service.create_alert_rule(db_session, entry.id)
        assert False, "expected DuplicateAlertRuleError"
    except DuplicateAlertRuleError:
        pass


async def test_create_alert_rule_rejects_enabled_check_missing_its_threshold(db_session):
    _, _, asset = await _setup_watched_bucket(db_session)
    entry = await watchlist_service.add_to_watchlist(db_session, asset.id)
    try:
        await alert_service.create_alert_rule(db_session, entry.id, price_target_enabled=True)
        assert False, "expected InvalidAlertRuleConfigurationError"
    except InvalidAlertRuleConfigurationError:
        pass


async def test_update_alert_rule_can_change_threshold_dynamically(db_session):
    _, _, asset = await _setup_watched_bucket(db_session)
    entry, rule = await _watch_with_rule(
        db_session, asset, price_target_enabled=True, price_target=Decimal("150")
    )
    updated = await alert_service.update_alert_rule(db_session, rule.id, {"price_target": Decimal("200")})
    assert updated.price_target == Decimal("200")


async def test_update_alert_rule_rejects_invalid_resulting_configuration(db_session):
    _, _, asset = await _setup_watched_bucket(db_session)
    entry, rule = await _watch_with_rule(db_session, asset)
    try:
        await alert_service.update_alert_rule(db_session, rule.id, {"dip_buy_enabled": True})
        assert False, "expected InvalidAlertRuleConfigurationError"
    except InvalidAlertRuleConfigurationError:
        pass


async def test_update_alert_rule_rejects_missing_rule(db_session):
    try:
        await alert_service.update_alert_rule(db_session, uuid.uuid4(), {"enabled": False})
        assert False, "expected AlertRuleNotFoundError"
    except AlertRuleNotFoundError:
        pass


async def test_delete_alert_rule_removes_it(db_session):
    _, _, asset = await _setup_watched_bucket(db_session)
    entry, rule = await _watch_with_rule(db_session, asset)
    await alert_service.delete_alert_rule(db_session, rule.id)
    try:
        await alert_service.get_alert_rule(db_session, rule.id)
        assert False, "expected AlertRuleNotFoundError"
    except AlertRuleNotFoundError:
        pass


async def test_delete_alert_rule_rejects_missing_rule(db_session):
    try:
        await alert_service.delete_alert_rule(db_session, uuid.uuid4())
        assert False, "expected AlertRuleNotFoundError"
    except AlertRuleNotFoundError:
        pass


async def test_get_alert_rule_for_watchlist_404_equivalent_when_none_configured(db_session):
    _, _, asset = await _setup_watched_bucket(db_session)
    entry = await watchlist_service.add_to_watchlist(db_session, asset.id)
    try:
        await alert_service.get_alert_rule_for_watchlist(db_session, entry.id)
        assert False, "expected AlertRuleNotFoundError"
    except AlertRuleNotFoundError:
        pass


# --- Allocation breach evaluation (reuses the Allocation Engine) -----------


async def test_evaluate_allocation_breach_triggers_at_configured_watch_threshold(db_session):
    # asset_value 2000 / total 10000 = 20% risk allocation.
    _, bucket, asset = await _setup_watched_bucket(db_session, asset_value=Decimal("2000"), other_value=Decimal("8000"))
    entry, rule = await _watch_with_rule(
        db_session, asset, allocation_alert_enabled=True, allocation_max_percent=Decimal("15")
    )

    evaluation = await alert_service.evaluate_alerts(db_session)
    breach = next(r for r in evaluation.results if r.alert_type == "ALLOCATION_BREACH")
    assert breach.condition_met is True
    assert breach.is_new_trigger is True
    assert breach.current_value == Decimal("20")


async def test_evaluate_allocation_breach_does_not_trigger_below_threshold(db_session):
    _, bucket, asset = await _setup_watched_bucket(db_session, asset_value=Decimal("1000"), other_value=Decimal("9000"))
    entry, rule = await _watch_with_rule(
        db_session, asset, allocation_alert_enabled=True, allocation_max_percent=Decimal("50")
    )

    evaluation = await alert_service.evaluate_alerts(db_session)
    breach = next(r for r in evaluation.results if r.alert_type == "ALLOCATION_BREACH")
    assert breach.condition_met is False
    assert breach.is_new_trigger is False


async def test_evaluate_allocation_breach_excludes_emergency_bucket_never_fabricates_a_percent(db_session):
    _, bucket, asset = await _setup_watched_bucket(
        db_session, asset_value=Decimal("100000"), other_value=Decimal("1000"), emergency=True
    )
    entry, rule = await _watch_with_rule(
        db_session, asset, allocation_alert_enabled=True, allocation_max_percent=Decimal("10")
    )

    evaluation = await alert_service.evaluate_alerts(db_session)
    breach = next(r for r in evaluation.results if r.alert_type == "ALLOCATION_BREACH")
    assert breach.condition_met is False
    assert breach.current_value is None
    assert "excluded" in breach.reason


async def test_evaluate_rebalance_suggestion_is_independent_of_the_alert_watch_threshold(db_session):
    """The bucket's own configured maximum_percent (allocation_targets)
    drives the rebalance suggestion, never the personal
    allocation_max_percent watch threshold on the alert rule — these are
    two independent numbers (Phase 8 approval, "reuse the Allocation
    Engine")."""
    # risk% = 2000/10000 = 20%, which breaches the bucket's own configured
    # maximum of 15%, even though the alert's own watch threshold (90%) is
    # nowhere close to being reached.
    _, bucket, asset = await _setup_watched_bucket(
        db_session, asset_value=Decimal("2000"), other_value=Decimal("8000"), bucket_maximum_percent=Decimal("15")
    )
    entry, rule = await _watch_with_rule(
        db_session, asset, allocation_alert_enabled=True, allocation_max_percent=Decimal("90")
    )

    evaluation = await alert_service.evaluate_alerts(db_session)
    breach = next(r for r in evaluation.results if r.alert_type == "ALLOCATION_BREACH")
    rebalance = next(r for r in evaluation.results if r.alert_type == "REBALANCE_SUGGESTED")
    assert breach.condition_met is False
    assert rebalance.condition_met is True
    assert rebalance.is_new_trigger is True


async def test_evaluate_rebalance_suggestion_is_a_suggestion_never_a_trade(db_session):
    _, bucket, asset = await _setup_watched_bucket(
        db_session, asset_value=Decimal("2000"), other_value=Decimal("8000"), bucket_maximum_percent=Decimal("15")
    )
    entry, rule = await _watch_with_rule(
        db_session, asset, allocation_alert_enabled=True, allocation_max_percent=Decimal("90")
    )

    async def counts():
        result = {}
        for model in (Holding, Transaction):
            r = await db_session.execute(select(func.count()).select_from(model))
            result[model.__name__] = r.scalar_one()
        return result

    before = await counts()
    await alert_service.evaluate_alerts(db_session)
    after = await counts()
    assert before == after
    assert after["Transaction"] == 0


# --- Price target / dip buy --------------------------------------------------


async def test_evaluate_price_target_reached(db_session):
    _, _, asset = await _setup_watched_bucket(db_session, current_price=Decimal("150"))
    entry, rule = await _watch_with_rule(db_session, asset, price_target_enabled=True, price_target=Decimal("150"))

    evaluation = await alert_service.evaluate_alerts(db_session)
    price = next(r for r in evaluation.results if r.alert_type == "PRICE_TARGET")
    assert price.condition_met is True
    assert price.is_new_trigger is True
    assert price.current_value == Decimal("150")


async def test_evaluate_price_target_not_reached(db_session):
    _, _, asset = await _setup_watched_bucket(db_session, current_price=Decimal("100"))
    entry, rule = await _watch_with_rule(db_session, asset, price_target_enabled=True, price_target=Decimal("150"))

    evaluation = await alert_service.evaluate_alerts(db_session)
    price = next(r for r in evaluation.results if r.alert_type == "PRICE_TARGET")
    assert price.condition_met is False


async def test_evaluate_dip_buy_reached(db_session):
    _, _, asset = await _setup_watched_bucket(db_session, current_price=Decimal("40"))
    entry, rule = await _watch_with_rule(db_session, asset, dip_buy_enabled=True, dip_buy_price=Decimal("50"))

    evaluation = await alert_service.evaluate_alerts(db_session)
    dip = next(r for r in evaluation.results if r.alert_type == "DIP_BUY")
    assert dip.condition_met is True
    assert dip.is_new_trigger is True


async def test_evaluate_dip_buy_not_reached(db_session):
    _, _, asset = await _setup_watched_bucket(db_session, current_price=Decimal("60"))
    entry, rule = await _watch_with_rule(db_session, asset, dip_buy_enabled=True, dip_buy_price=Decimal("50"))

    evaluation = await alert_service.evaluate_alerts(db_session)
    dip = next(r for r in evaluation.results if r.alert_type == "DIP_BUY")
    assert dip.condition_met is False


# --- Deduplication ------------------------------------------------------------


async def test_dedup_does_not_spam_while_condition_remains_true(db_session):
    _, _, asset = await _setup_watched_bucket(db_session, current_price=Decimal("150"))
    entry, rule = await _watch_with_rule(db_session, asset, price_target_enabled=True, price_target=Decimal("150"))

    first = await alert_service.evaluate_alerts(db_session)
    first_price = next(r for r in first.results if r.alert_type == "PRICE_TARGET")
    assert first_price.is_new_trigger is True

    second = await alert_service.evaluate_alerts(db_session)
    second_price = next(r for r in second.results if r.alert_type == "PRICE_TARGET")
    assert second_price.condition_met is True
    assert second_price.is_new_trigger is False


async def test_dedup_clears_and_can_re_trigger_after_condition_becomes_true_again(db_session):
    _, _, asset = await _setup_watched_bucket(db_session, current_price=Decimal("150"))
    entry, rule = await _watch_with_rule(db_session, asset, price_target_enabled=True, price_target=Decimal("150"))

    await alert_service.evaluate_alerts(db_session)  # new trigger, latch set

    holding = (await db_session.execute(select(Holding).where(Holding.asset_id == asset.id))).scalar_one()
    holding.current_price = Decimal("100")
    await db_session.commit()

    cleared = await alert_service.evaluate_alerts(db_session)
    cleared_price = next(r for r in cleared.results if r.alert_type == "PRICE_TARGET")
    assert cleared_price.condition_met is False
    assert cleared_price.should_clear is True

    holding.current_price = Decimal("150")
    await db_session.commit()

    retriggered = await alert_service.evaluate_alerts(db_session)
    retriggered_price = next(r for r in retriggered.results if r.alert_type == "PRICE_TARGET")
    assert retriggered_price.condition_met is True
    assert retriggered_price.is_new_trigger is True


async def test_dedup_persists_last_triggered_at_on_the_alert_rule_row(db_session):
    _, _, asset = await _setup_watched_bucket(db_session, current_price=Decimal("150"))
    entry, rule = await _watch_with_rule(db_session, asset, price_target_enabled=True, price_target=Decimal("150"))

    await alert_service.evaluate_alerts(db_session)
    refreshed = await alert_service.get_alert_rule(db_session, rule.id)
    assert refreshed.last_triggered_at is not None


# --- Exclusions ---------------------------------------------------------------


async def test_evaluate_skips_disabled_alert_rules(db_session):
    _, _, asset = await _setup_watched_bucket(db_session, current_price=Decimal("150"))
    entry, rule = await _watch_with_rule(db_session, asset, price_target_enabled=True, price_target=Decimal("150"))
    await alert_service.update_alert_rule(db_session, rule.id, {"enabled": False})

    evaluation = await alert_service.evaluate_alerts(db_session)
    assert not any(r.alert_rule_id == rule.id for r in evaluation.results)


async def test_evaluate_skips_disabled_watchlist_entries(db_session):
    _, _, asset = await _setup_watched_bucket(db_session, current_price=Decimal("150"))
    entry, rule = await _watch_with_rule(db_session, asset, price_target_enabled=True, price_target=Decimal("150"))
    await watchlist_service.update_watchlist_entry(db_session, entry.id, enabled=False)

    evaluation = await alert_service.evaluate_alerts(db_session)
    assert not any(r.alert_rule_id == rule.id for r in evaluation.results)


async def test_evaluate_works_with_no_portfolio_configured_for_non_allocation_checks(db_session):
    """Price/dip checks must not depend on a configured portfolio at
    all — only allocation-related checks need it, and those degrade to
    'no bucket allocation available' rather than raising."""
    asset = make_asset("NOPORTFOLIO")
    db_session.add(asset)
    await db_session.commit()
    db_session.add(Holding(asset_id=asset.id, quantity=Decimal("1"), current_price=Decimal("150")))
    await db_session.commit()

    entry = await watchlist_service.add_to_watchlist(db_session, asset.id)
    await alert_service.create_alert_rule(
        db_session,
        entry.id,
        price_target_enabled=True,
        price_target=Decimal("150"),
        allocation_alert_enabled=True,
        allocation_max_percent=Decimal("10"),
    )

    evaluation = await alert_service.evaluate_alerts(db_session)
    price = next(r for r in evaluation.results if r.alert_type == "PRICE_TARGET")
    breach = next(r for r in evaluation.results if r.alert_type == "ALLOCATION_BREACH")
    assert price.condition_met is True
    assert breach.condition_met is False


# --- Side effects / read-only contract ---------------------------------------


async def test_evaluate_alerts_has_no_side_effects_on_financial_positions(db_session):
    _, bucket, asset = await _setup_watched_bucket(
        db_session, asset_value=Decimal("2000"), other_value=Decimal("8000"), bucket_maximum_percent=Decimal("15")
    )
    entry, rule = await _watch_with_rule(
        db_session,
        asset,
        allocation_alert_enabled=True,
        allocation_max_percent=Decimal("15"),
        price_target_enabled=True,
        price_target=Decimal("100"),
        dip_buy_enabled=True,
        dip_buy_price=Decimal("50"),
    )

    async def counts():
        result = {}
        for model in (Asset, Holding, AllocationTarget, StrategyBucket, PortfolioConfig, Transaction, PortfolioSnapshot):
            r = await db_session.execute(select(func.count()).select_from(model))
            result[model.__name__] = r.scalar_one()
        return result

    before = await counts()
    await alert_service.evaluate_alerts(db_session)
    await alert_service.evaluate_alerts(db_session)
    after = await counts()

    assert before == after


async def test_evaluate_alerts_only_writes_last_triggered_at_not_other_alert_rule_fields(db_session):
    _, _, asset = await _setup_watched_bucket(db_session, current_price=Decimal("150"))
    entry, rule = await _watch_with_rule(db_session, asset, price_target_enabled=True, price_target=Decimal("150"))

    await alert_service.evaluate_alerts(db_session)
    refreshed = await alert_service.get_alert_rule(db_session, rule.id)
    assert refreshed.price_target == Decimal("150")
    assert refreshed.price_target_enabled is True
    assert refreshed.enabled is True


async def test_evaluate_dispatches_notification_only_for_new_triggers(db_session):
    _, _, asset = await _setup_watched_bucket(db_session, current_price=Decimal("150"))
    entry, rule = await _watch_with_rule(db_session, asset, price_target_enabled=True, price_target=Decimal("150"))

    notifier = RecordingNotifier()
    await alert_service.evaluate_alerts(db_session, notifier=notifier)
    assert len(notifier.dispatched) == 1

    notifier2 = RecordingNotifier()
    await alert_service.evaluate_alerts(db_session, notifier=notifier2)
    assert len(notifier2.dispatched) == 0


# --- Decimal-only ---------------------------------------------------------


async def test_evaluate_alerts_values_are_decimal_not_float(db_session):
    _, bucket, asset = await _setup_watched_bucket(
        db_session, asset_value=Decimal("2000"), other_value=Decimal("8000")
    )
    entry, rule = await _watch_with_rule(
        db_session, asset, allocation_alert_enabled=True, allocation_max_percent=Decimal("15")
    )

    evaluation = await alert_service.evaluate_alerts(db_session)
    breach = next(r for r in evaluation.results if r.alert_type == "ALLOCATION_BREACH")
    assert isinstance(breach.current_value, Decimal)
    assert isinstance(breach.threshold_value, Decimal)
