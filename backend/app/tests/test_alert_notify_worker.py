"""Phase 20: end-to-end Telegram delivery worker tests against a real
database session — confirms `app/workers/alert_notify.py` actually wires
the Phase 19 Notification Center to a (mocked) Telegram send and applies
every required gate, without ever recomputing an alert/recommendation.

Uses the same `_NoCloseSession` pattern as test_snapshot_eod_worker.py /
test_price_refresh_worker.py so the worker's own `async with
async_session_factory()` reuses the fixture-managed `db_session` instead
of opening an unrelated connection.
"""

from datetime import datetime, timezone
from decimal import Decimal

from app.core.config import Settings
from app.models import AllocationTarget, StrategyBucket
from app.models.enums import NotificationCategory
from app.repositories.notification_repository import list_pending_telegram_notifications
from app.services import alert_service, watchlist_service
from app.services.notification_dispatcher import NullNotificationDispatcher
from app.tests.conftest import make_asset, make_current_price, make_portfolio_config
from app.workers import alert_notify


class _NoCloseSession:
    def __init__(self, session):
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, *exc_info):
        return False


class RecordingCenterNotifier:
    """Records every persisted Notification handed to it; `should_succeed`
    controls whether delivery is reported as accepted by Telegram."""

    def __init__(self, should_succeed: bool = True):
        self.should_succeed = should_succeed
        self.dispatched: list = []

    async def dispatch_notification(self, notification) -> bool:
        self.dispatched.append(notification)
        return self.should_succeed


def _enable_telegram_globally(monkeypatch, *, enabled=True, bot_token="test-token", chat_id="test-chat"):
    fake_settings = Settings(
        TELEGRAM_ENABLED=enabled,
        TELEGRAM_BOT_TOKEN=bot_token if enabled else "",
        TELEGRAM_CHAT_ID=chat_id if enabled else "",
    )
    monkeypatch.setattr(alert_notify, "get_settings", lambda: fake_settings)


async def _setup_breached_portfolio(session, *, portfolio_telegram_enabled=True):
    """A category already over its configured maximum -- a real,
    unmodified Phase 17/18/19 chain produces a RECOMMENDATION_ALERT/
    CRITICAL notification for it."""
    config = make_portfolio_config(emergency_excluded=False, telegram_enabled=portfolio_telegram_enabled)
    session.add(config)
    await session.flush()

    bucket = StrategyBucket(portfolio_config_id=config.id, name="Overweight Stocks")
    session.add(bucket)
    await session.flush()
    asset = make_asset("WRKROVER", strategy_bucket_id=bucket.id)
    session.add(asset)
    await session.flush()
    from app.models import Holding

    session.add(Holding(asset_id=asset.id, quantity=Decimal("100")))  # 10000
    await make_current_price(session, asset, Decimal("100"))
    target = AllocationTarget(
        portfolio_config_id=config.id, strategy_bucket_id=bucket.id, maximum_percent=Decimal("15"), priority=1
    )
    session.add(target)
    await session.commit()
    return config


async def _setup_watched_price_asset(session, *, current_price=Decimal("150"), rule_telegram_enabled=True, portfolio_telegram_enabled=True):
    config = make_portfolio_config(telegram_enabled=portfolio_telegram_enabled)
    session.add(config)
    await session.flush()
    asset = make_asset("WRKRPRICE")
    session.add(asset)
    await session.flush()
    from app.models import Holding

    session.add(Holding(asset_id=asset.id, quantity=Decimal("1")))
    await make_current_price(session, asset, current_price)
    await session.commit()

    entry = await watchlist_service.add_to_watchlist(session, asset.id)
    rule = await alert_service.create_alert_rule(
        session,
        entry.id,
        price_target_enabled=True,
        price_target=Decimal("150"),
        telegram_enabled=rule_telegram_enabled,
    )
    return config, asset, entry, rule


async def _run_worker(db_session, monkeypatch, notifier):
    monkeypatch.setattr(alert_notify, "async_session_factory", lambda: _NoCloseSession(db_session))
    monkeypatch.setattr(alert_notify, "_build_notifier", lambda: notifier)
    await alert_notify.run_alert_notify()


# --- A/B: pending notification is delivered and marked sent -----------------


async def test_a_b_pending_recommendation_notification_is_delivered_and_marked_sent(db_session, monkeypatch):
    await _setup_breached_portfolio(db_session)
    _enable_telegram_globally(monkeypatch)

    notifier = RecordingCenterNotifier(should_succeed=True)
    await _run_worker(db_session, monkeypatch, notifier)

    assert len(notifier.dispatched) == 1
    pending_after = await list_pending_telegram_notifications(db_session)
    assert pending_after == []  # the one notification is no longer pending


# --- C: failed delivery leaves telegram_sent_at NULL, remains pending -------


async def test_c_failed_delivery_leaves_notification_pending(db_session, monkeypatch):
    await _setup_breached_portfolio(db_session)
    _enable_telegram_globally(monkeypatch)

    notifier = RecordingCenterNotifier(should_succeed=False)
    await _run_worker(db_session, monkeypatch, notifier)

    assert len(notifier.dispatched) == 1
    pending_after = await list_pending_telegram_notifications(db_session)
    assert len(pending_after) == 1
    assert pending_after[0].telegram_sent_at is None


# --- D: resolved but undelivered notification is still eligible -------------


async def test_d_resolved_notification_still_eligible_for_delivery(db_session, monkeypatch):
    """A maximum breach that has since been genuinely fixed (so Phase 19's
    own resolution logic sets resolved_at) but was never Telegram-
    delivered must still be sent -- Telegram delivery answers 'was the
    user informed', not 'is the condition still true'."""
    from app.services.notification_service import sync_notifications

    await _setup_breached_portfolio(db_session)
    await sync_notifications(db_session)  # Phase 19's own sync -- independent of this worker

    pending_before = await list_pending_telegram_notifications(db_session)
    assert len(pending_before) == 1
    notification_id = pending_before[0].id

    # Genuinely fix the breach by diluting the same bucket's allocation
    # with a large, unrelated second position -- the breached bucket's
    # actual value is unchanged, but it now falls under its existing 15%
    # maximum, so the NEXT sync resolves this exact notification via
    # Phase 19's own edge-triggered logic, rather than a test manually
    # poking resolved_at.
    from app.models import Holding
    from app.repositories.portfolio_repository import get_portfolio_config

    config = await get_portfolio_config(db_session)
    other_bucket = StrategyBucket(portfolio_config_id=config.id, name="Diluting Bucket")
    db_session.add(other_bucket)
    await db_session.flush()
    other_asset = make_asset("WRKRDILUTE", strategy_bucket_id=other_bucket.id)
    db_session.add(other_asset)
    await db_session.flush()
    db_session.add(Holding(asset_id=other_asset.id, quantity=Decimal("900")))
    await make_current_price(db_session, other_asset, Decimal("100"))
    await db_session.commit()

    await sync_notifications(db_session)

    resolved = await list_pending_telegram_notifications(db_session)
    assert len(resolved) == 1
    assert resolved[0].id == notification_id
    assert resolved[0].resolved_at is not None
    assert resolved[0].telegram_sent_at is None

    _enable_telegram_globally(monkeypatch)
    notifier = RecordingCenterNotifier(should_succeed=True)
    await _run_worker(db_session, monkeypatch, notifier)

    assert len(notifier.dispatched) == 1
    assert notifier.dispatched[0].id == notification_id


# --- E: already-delivered notification is never sent again ------------------


async def test_e_already_delivered_notification_is_never_resent(db_session, monkeypatch):
    await _setup_breached_portfolio(db_session)
    _enable_telegram_globally(monkeypatch)

    first_notifier = RecordingCenterNotifier(should_succeed=True)
    await _run_worker(db_session, monkeypatch, first_notifier)
    assert len(first_notifier.dispatched) == 1

    second_notifier = RecordingCenterNotifier(should_succeed=True)
    await _run_worker(db_session, monkeypatch, second_notifier)
    assert len(second_notifier.dispatched) == 0


# --- F: global Telegram disabled --------------------------------------------


async def test_f_global_telegram_disabled_skips_delivery_entirely(db_session, monkeypatch):
    from app.services.notification_service import sync_notifications

    await _setup_breached_portfolio(db_session)
    await sync_notifications(db_session)  # Phase 19's own sync -- independent of this worker
    _enable_telegram_globally(monkeypatch, enabled=False)

    notifier = RecordingCenterNotifier(should_succeed=True)
    await _run_worker(db_session, monkeypatch, notifier)

    assert len(notifier.dispatched) == 0
    pending_after = await list_pending_telegram_notifications(db_session)
    assert len(pending_after) == 1
    assert pending_after[0].telegram_sent_at is None


# --- G: missing credentials ---------------------------------------------------


async def test_g_missing_credentials_skips_delivery(db_session, monkeypatch):
    await _setup_breached_portfolio(db_session)
    fake_settings = Settings(TELEGRAM_ENABLED=True, TELEGRAM_BOT_TOKEN="", TELEGRAM_CHAT_ID="")
    monkeypatch.setattr(alert_notify, "get_settings", lambda: fake_settings)

    notifier = RecordingCenterNotifier(should_succeed=True)
    await _run_worker(db_session, monkeypatch, notifier)

    assert len(notifier.dispatched) == 0


# --- H: portfolio Telegram disabled -------------------------------------------


async def test_h_portfolio_telegram_disabled_skips_delivery(db_session, monkeypatch):
    from app.services.notification_service import sync_notifications

    await _setup_breached_portfolio(db_session, portfolio_telegram_enabled=False)
    await sync_notifications(db_session)  # Phase 19's own sync -- independent of this worker
    _enable_telegram_globally(monkeypatch)

    notifier = RecordingCenterNotifier(should_succeed=True)
    await _run_worker(db_session, monkeypatch, notifier)

    assert len(notifier.dispatched) == 0
    pending_after = await list_pending_telegram_notifications(db_session)
    assert len(pending_after) == 1
    assert pending_after[0].telegram_sent_at is None


# --- I: alert-origin notification with rule-level Telegram disabled ----------


async def test_i_alert_origin_notification_respects_per_rule_telegram_opt_in(db_session, monkeypatch):
    await _setup_watched_price_asset(db_session, current_price=Decimal("150"), rule_telegram_enabled=False)
    _enable_telegram_globally(monkeypatch)

    notifier = RecordingCenterNotifier(should_succeed=True)
    await _run_worker(db_session, monkeypatch, notifier)

    pending = await list_pending_telegram_notifications(db_session)
    assert len(pending) == 1  # the PRICE_ALERT notification exists...
    assert pending[0].category == NotificationCategory.PRICE_ALERT
    assert len(notifier.dispatched) == 0  # ...but is never delivered: the rule opted out.
    assert pending[0].telegram_sent_at is None


async def test_i_alert_origin_notification_delivered_when_rule_telegram_enabled(db_session, monkeypatch):
    await _setup_watched_price_asset(db_session, current_price=Decimal("150"), rule_telegram_enabled=True)
    _enable_telegram_globally(monkeypatch)

    notifier = RecordingCenterNotifier(should_succeed=True)
    await _run_worker(db_session, monkeypatch, notifier)

    assert len(notifier.dispatched) == 1
    assert notifier.dispatched[0].category == NotificationCategory.PRICE_ALERT


# --- J: recommendation notification needs only the portfolio switch ---------


async def test_j_recommendation_notification_needs_only_portfolio_switch(db_session, monkeypatch):
    """No alert rule exists for a recommendation-origin notification --
    the portfolio-level switch alone (after global config) is sufficient,
    unlike the alert-origin case in test I."""
    await _setup_breached_portfolio(db_session, portfolio_telegram_enabled=True)
    _enable_telegram_globally(monkeypatch)

    notifier = RecordingCenterNotifier(should_succeed=True)
    await _run_worker(db_session, monkeypatch, notifier)

    assert len(notifier.dispatched) == 1
    assert notifier.dispatched[0].category == NotificationCategory.RECOMMENDATION_ALERT


# --- K: Phase 14 raw-alert-check dispatch path remains untouched -------------


async def test_k_worker_never_uses_the_legacy_raw_alert_dispatch_method(db_session, monkeypatch):
    """The Phase 20 worker must call only `dispatch_notification` on
    persisted Notification Center rows -- never the Phase 14
    `dispatch(AlertCheckResult, ...)` method, which remains reserved for
    `alert_service.evaluate_alerts`'s own on-demand call path."""
    await _setup_watched_price_asset(db_session, current_price=Decimal("150"), rule_telegram_enabled=True)
    _enable_telegram_globally(monkeypatch)

    class DispatchNotCalled(RecordingCenterNotifier):
        async def dispatch(self, *args, **kwargs):
            raise AssertionError("worker must not call the legacy dispatch() method")

    notifier = DispatchNotCalled(should_succeed=True)
    await _run_worker(db_session, monkeypatch, notifier)
    assert len(notifier.dispatched) == 1


# --- L: Notification Center stays functional with Telegram fully disabled ---


async def test_l_notification_center_sync_unaffected_by_telegram_being_disabled(db_session, monkeypatch):
    """sync_notifications/list_notifications (Phase 19) must keep working
    identically regardless of Telegram configuration -- in-app visibility
    never depends on it."""
    from app.services.notification_service import list_notifications

    await _setup_breached_portfolio(db_session, portfolio_telegram_enabled=False)

    result = await list_notifications(db_session)
    assert len(result.notifications) == 1
    assert result.notifications[0].category == "RECOMMENDATION_ALERT"

    # Running the (disabled) worker must not disturb in-app state either.
    _enable_telegram_globally(monkeypatch, enabled=False)
    notifier = RecordingCenterNotifier(should_succeed=True)
    await _run_worker(db_session, monkeypatch, notifier)

    result_after = await list_notifications(db_session)
    assert len(result_after.notifications) == 1
    assert result_after.notifications[0].read is False


# --- Read-only financial state, no dispatcher used means no side effect -----


async def test_worker_never_uses_null_dispatcher_when_fully_configured(db_session, monkeypatch):
    """Confirms _build_notifier is genuinely wired -- a fully-configured
    deployment must not silently fall back to the no-op dispatcher."""
    await _setup_breached_portfolio(db_session)
    _enable_telegram_globally(monkeypatch)

    real_notifier = alert_notify._build_notifier()
    assert not isinstance(real_notifier, NullNotificationDispatcher)
