"""P0-3C: cross-user ownership isolation.

Two real users (A and B) with real, populated portfolios, driven over HTTP
through the REAL app with REAL signed Supabase-style JWTs (see conftest.py):
"who is calling" always comes from a verified token, and every request goes
through the real router -> service -> repository -> database path. Nothing
here overrides the auth dependency or reaches around the ownership logic.

Both users deliberately hold/watch the SAME shared (global) asset, which is
exactly the situation the per-portfolio constraints exist for and the one most
likely to leak: a query scoped by asset alone would return the wrong user's
row.

Lettering follows the P0-3C test plan (A: authentication is covered in
test_auth.py and test_supabase_auth.py).
"""

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import func, select

from app.models import (
    AlertRule,
    AllocationTarget,
    Asset,
    Holding,
    Notification,
    PortfolioConfig,
    PortfolioSnapshot,
    StrategyBucket,
    Transaction,
    TransactionType,
    User,
    Watchlist,
)
from app.tests.conftest import make_asset, make_current_price


@dataclass
class Tenant:
    user: User
    config: PortfolioConfig
    bucket: StrategyBucket
    target: AllocationTarget
    holding: Holding
    transaction: Transaction
    watchlist: Watchlist
    rule: AlertRule


@dataclass
class World:
    shared_asset: Asset
    a: Tenant
    b: Tenant


async def _make_tenant(session, user: User, asset: Asset, *, name: str, quantity: str, cost: str) -> Tenant:
    config = PortfolioConfig(user_id=user.id, name=name, base_currency="EGP", emergency_excluded=False)
    session.add(config)
    await session.flush()

    bucket = StrategyBucket(portfolio_config_id=config.id, name=f"{name} Bucket")
    session.add(bucket)
    await session.flush()
    target = AllocationTarget(
        portfolio_config_id=config.id, strategy_bucket_id=bucket.id, target_percent=Decimal("100"), priority=1
    )
    holding = Holding(
        portfolio_config_id=config.id, asset_id=asset.id, quantity=Decimal(quantity), average_cost=Decimal(cost)
    )
    transaction = Transaction(
        portfolio_config_id=config.id,
        asset_id=asset.id,
        transaction_type=TransactionType.BUY,
        quantity=Decimal(quantity),
        price=Decimal(cost),
        transaction_date=datetime(2026, 1, 1, tzinfo=timezone.utc),
        notes=f"{name} buy",
    )
    watch = Watchlist(portfolio_config_id=config.id, asset_id=asset.id, notes=f"{name} watch")
    session.add_all([target, holding, transaction, watch])
    await session.flush()
    rule = AlertRule(
        portfolio_config_id=config.id,
        watchlist_id=watch.id,
        price_target_enabled=True,
        price_target=Decimal("100"),
    )
    session.add(rule)
    await session.flush()
    return Tenant(user, config, bucket, target, holding, transaction, watch, rule)


@pytest_asyncio.fixture
async def world(db_session, user_a, user_b) -> World:
    asset = make_asset("SHARED1", name="Shared Stock")
    db_session.add(asset)
    await db_session.flush()
    await make_current_price(db_session, asset, Decimal("100"))
    a = await _make_tenant(db_session, user_a, asset, name="Alpha", quantity="10", cost="50")
    b = await _make_tenant(db_session, user_b, asset, name="Beta", quantity="40", cost="60")
    # The one global asset sits in A's bucket (assets carry a single bucket id).
    asset.strategy_bucket_id = a.bucket.id
    await db_session.commit()
    return World(asset, a, b)


# ============================================================================
# B. Portfolio ownership
# ============================================================================


async def test_user_a_can_access_own_portfolio(client_for, world):
    async with client_for(world.a.user) as ac:
        response = await ac.get("/api/portfolio/config")

    assert response.status_code == 200
    assert response.json()["id"] == str(world.a.config.id)
    assert response.json()["name"] == "Alpha"


async def test_user_a_never_receives_user_b_portfolio(client_for, world):
    async with client_for(world.a.user) as ac:
        config = (await ac.get("/api/portfolio/config")).json()
        summary = (await ac.get("/api/portfolio/summary")).json()
    async with client_for(world.b.user) as bc:
        b_config = (await bc.get("/api/portfolio/config")).json()

    assert config["id"] != b_config["id"]
    assert b_config["name"] == "Beta"
    # A's totals are A's 10 shares x 100, never B's 40 x 100 nor the sum.
    assert Decimal(summary["total_value"]) == Decimal("1000.00")


async def test_user_without_a_portfolio_gets_404_not_someone_elses(client_for, world, db_session):
    """The core "no first-portfolio fallback" guarantee: a user with no portfolio
    sees "not configured" even though other users' portfolios exist."""
    from app.tests.conftest import make_user

    newcomer = await make_user(db_session)
    await db_session.commit()

    async with client_for(newcomer) as ac:
        for path in (
            "/api/portfolio/config",
            "/api/portfolio/summary",
            "/api/portfolio/allocation",
            "/api/portfolio/rebalancing",
            "/api/portfolio/recommendations",
            "/api/portfolio/strategy/validation",
            "/api/portfolio/analytics/history?range=ALL",
            "/api/strategy/buckets",
            "/api/strategy/targets",
        ):
            response = await ac.get(path)
            assert response.status_code == 404, path


async def test_unowned_legacy_portfolio_is_invisible_to_everyone(client_for, world, db_session):
    """A portfolio with no owner (pre-ownership data) is reachable by nobody --
    it is never adopted by whoever happens to call first."""
    from app.tests.conftest import make_user

    db_session.add(PortfolioConfig(user_id=None, name="Legacy Unowned", base_currency="EGP"))
    newcomer = await make_user(db_session)
    await db_session.commit()

    async with client_for(newcomer) as ac:
        assert (await ac.get("/api/portfolio/config")).status_code == 404
    async with client_for(world.a.user) as ac:
        assert (await ac.get("/api/portfolio/config")).json()["name"] == "Alpha"


async def test_user_a_cannot_reach_user_b_strategy_rows_by_id(client_for, world):
    async with client_for(world.a.user) as ac:
        buckets = (await ac.get("/api/strategy/buckets")).json()
        assert [b["id"] for b in buckets] == [str(world.a.bucket.id)]
        targets = (await ac.get("/api/strategy/targets")).json()
        assert [t["id"] for t in targets] == [str(world.a.target.id)]

        for method, path, body in (
            ("patch", f"/api/strategy/buckets/{world.b.bucket.id}", {"name": "hijack"}),
            ("post", f"/api/strategy/buckets/{world.b.bucket.id}/deactivate", None),
            ("post", f"/api/strategy/buckets/{world.b.bucket.id}/activate", None),
            ("patch", f"/api/strategy/targets/{world.b.target.id}", {"target_percent": "1"}),
        ):
            response = await getattr(ac, method)(path, **({"json": body} if body else {}))
            assert response.status_code == 404, (method, path)


async def test_user_a_cannot_create_a_target_for_user_b_bucket(client_for, world):
    async with client_for(world.a.user) as ac:
        response = await ac.post(
            "/api/strategy/targets", json={"strategy_bucket_id": str(world.b.bucket.id), "target_percent": "10"}
        )

    assert response.status_code == 400
    assert str(world.b.config.id) not in response.text


async def test_strategy_writes_never_modify_the_other_users_rows(client_for, world, db_session):
    async with client_for(world.a.user) as ac:
        await ac.patch(f"/api/strategy/buckets/{world.b.bucket.id}", json={"name": "hijack"})
        await ac.patch(f"/api/strategy/targets/{world.b.target.id}", json={"target_percent": "1"})

    await db_session.refresh(world.b.bucket)
    await db_session.refresh(world.b.target)
    assert world.b.bucket.name == "Beta Bucket"
    assert world.b.target.target_percent == Decimal("100.00")


async def test_portfolio_config_update_and_create_only_touch_the_callers_portfolio(client_for, world, db_session):
    async with client_for(world.a.user) as ac:
        # A already has a portfolio: a second POST is rejected (still single-portfolio per user)
        again = await ac.post("/api/portfolio/config", json={"name": "Second", "base_currency": "EGP"})
        assert again.status_code == 409
        patched = await ac.patch("/api/portfolio/config", json={"name": "Alpha Renamed"})
        assert patched.status_code == 200

    await db_session.refresh(world.b.config)
    assert world.b.config.name == "Beta"


async def test_a_new_portfolio_is_created_owned_by_the_caller(client_for, db_session):
    from app.tests.conftest import make_user

    newcomer = await make_user(db_session)
    await db_session.commit()

    async with client_for(newcomer) as ac:
        response = await ac.post("/api/portfolio/config", json={"name": "Mine", "base_currency": "EGP"})
    assert response.status_code == 201

    row = (await db_session.execute(select(PortfolioConfig).where(PortfolioConfig.name == "Mine"))).scalar_one()
    assert row.user_id == newcomer.id


async def test_a_client_supplied_user_id_in_the_body_is_ignored_on_portfolio_create(client_for, db_session, user_b):
    from app.tests.conftest import make_user

    newcomer = await make_user(db_session)
    await db_session.commit()

    async with client_for(newcomer) as ac:
        response = await ac.post(
            "/api/portfolio/config",
            json={"name": "Spoof", "base_currency": "EGP", "user_id": str(user_b.id)},
        )
    assert response.status_code == 201

    row = (await db_session.execute(select(PortfolioConfig).where(PortfolioConfig.name == "Spoof"))).scalar_one()
    assert row.user_id == newcomer.id


async def test_base_currency_gate_is_per_portfolio(client_for, world, db_session):
    """B's transaction history must not block A from changing base currency,
    and vice versa -- the gate asks "does THIS portfolio have transactions"."""
    from app.tests.conftest import make_user

    newcomer = await make_user(db_session)
    db_session.add(PortfolioConfig(user_id=newcomer.id, name="Fresh", base_currency="EGP"))
    await db_session.commit()

    async with client_for(newcomer) as ac:
        ok = await ac.patch("/api/portfolio/config", json={"base_currency": "USD"})
    async with client_for(world.a.user) as ac:
        blocked = await ac.patch("/api/portfolio/config", json={"base_currency": "USD"})

    assert ok.status_code == 200  # newcomer has no transactions, despite A and B having some
    assert blocked.status_code == 409  # A has its own


# ============================================================================
# C. Holdings
# ============================================================================


async def test_user_a_reads_own_holding_and_never_user_bs(client_for, world):
    async with client_for(world.a.user) as ac:
        a_summary = (await ac.get("/api/portfolio/summary")).json()
    async with client_for(world.b.user) as bc:
        b_summary = (await bc.get("/api/portfolio/summary")).json()

    a_holding = next(h for h in a_summary["holdings_pnl"] if h["symbol"] == "SHARED1")
    b_holding = next(h for h in b_summary["holdings_pnl"] if h["symbol"] == "SHARED1")
    # the same global asset, two different positions -- each sees only its own
    assert Decimal(a_holding["quantity"]) == Decimal("10")
    assert Decimal(b_holding["quantity"]) == Decimal("40")
    assert Decimal(a_holding["average_cost"]) == Decimal("50")
    assert Decimal(b_holding["average_cost"]) == Decimal("60")


async def test_user_a_trading_never_modifies_user_b_holding(client_for, world, db_session):
    async with client_for(world.a.user) as ac:
        buy = await ac.post(
            "/api/transactions",
            json={
                "asset_id": str(world.shared_asset.id),
                "transaction_type": "BUY",
                "quantity": "5",
                "price": "70",
                "transaction_date": "2026-02-01T00:00:00Z",
            },
        )
    assert buy.status_code == 201

    await db_session.refresh(world.a.holding)
    await db_session.refresh(world.b.holding)
    assert world.a.holding.quantity == Decimal("15")
    assert world.b.holding.quantity == Decimal("40")
    assert world.b.holding.average_cost == Decimal("60")


async def test_user_a_cannot_sell_a_position_only_user_b_holds(client_for, world, db_session):
    """A holds nothing in a second asset that B holds: A's SELL is an oversell,
    and B's holding is untouched."""
    other = make_asset("ONLYB")
    db_session.add(other)
    await db_session.flush()
    b_only = Holding(
        portfolio_config_id=world.b.config.id, asset_id=other.id, quantity=Decimal("25"), average_cost=Decimal("10")
    )
    db_session.add(b_only)
    await db_session.commit()

    async with client_for(world.a.user) as ac:
        response = await ac.post(
            "/api/transactions",
            json={
                "asset_id": str(other.id),
                "transaction_type": "SELL",
                "quantity": "1",
                "price": "10",
                "transaction_date": "2026-02-01T00:00:00Z",
            },
        )

    assert response.status_code == 409
    await db_session.refresh(b_only)
    assert b_only.quantity == Decimal("25")


async def test_there_is_no_holding_endpoint_to_modify_or_delete_another_users_holding(client_for, world):
    """Holdings are only ever changed as a side effect of the caller's own
    transactions; no route addresses a holding by id."""
    async with client_for(world.a.user) as ac:
        for method in ("get", "patch", "put", "delete"):
            response = await getattr(ac, method)(f"/api/holdings/{world.b.holding.id}")
            assert response.status_code in (404, 405)


async def test_a_client_supplied_portfolio_id_never_places_a_holding_in_another_portfolio(
    client_for, world, db_session
):
    async with client_for(world.a.user) as ac:
        response = await ac.post(
            "/api/transactions",
            json={
                "asset_id": str(world.shared_asset.id),
                "transaction_type": "BUY",
                "quantity": "1",
                "price": "10",
                "transaction_date": "2026-02-01T00:00:00Z",
                "portfolio_config_id": str(world.b.config.id),
                "user_id": str(world.b.user.id),
            },
        )
    assert response.status_code == 201

    await db_session.refresh(world.b.holding)
    assert world.b.holding.quantity == Decimal("40")  # B's position is untouched
    created = (
        await db_session.execute(select(Transaction).where(Transaction.price == Decimal("10")))
    ).scalar_one()
    assert created.portfolio_config_id == world.a.config.id


# ============================================================================
# D. Transactions
# ============================================================================


async def test_user_a_lists_only_own_transactions(client_for, world):
    async with client_for(world.a.user) as ac:
        a_list = (await ac.get("/api/transactions")).json()
    async with client_for(world.b.user) as bc:
        b_list = (await bc.get("/api/transactions")).json()

    assert [t["notes"] for t in a_list] == ["Alpha buy"]
    assert [t["notes"] for t in b_list] == ["Beta buy"]


async def test_transactions_are_immutable_and_cannot_be_modified_or_deleted_by_anyone(client_for, world, db_session):
    async with client_for(world.a.user) as ac:
        for method in ("patch", "put", "delete"):
            response = await getattr(ac, method)(f"/api/transactions/{world.b.transaction.id}")
            assert response.status_code in (404, 405)

    await db_session.refresh(world.b.transaction)
    assert world.b.transaction.notes == "Beta buy"


async def test_a_new_transaction_is_attributed_to_the_caller_only(client_for, world, db_session):
    async with client_for(world.b.user) as bc:
        response = await bc.post(
            "/api/transactions",
            json={
                "asset_id": str(world.shared_asset.id),
                "transaction_type": "BUY",
                "quantity": "2",
                "price": "99",
                "transaction_date": "2026-03-01T00:00:00Z",
                "notes": "b second buy",
            },
        )
    assert response.status_code == 201

    created = (await db_session.execute(select(Transaction).where(Transaction.notes == "b second buy"))).scalar_one()
    assert created.portfolio_config_id == world.b.config.id
    async with client_for(world.a.user) as ac:
        assert "b second buy" not in (await ac.get("/api/transactions")).text


async def test_transaction_without_a_portfolio_is_rejected_not_attributed_elsewhere(client_for, world, db_session):
    from app.tests.conftest import make_user

    newcomer = await make_user(db_session)
    await db_session.commit()

    async with client_for(newcomer) as ac:
        response = await ac.post(
            "/api/transactions",
            json={
                "asset_id": str(world.shared_asset.id),
                "transaction_type": "BUY",
                "quantity": "1",
                "price": "1",
                "transaction_date": "2026-03-01T00:00:00Z",
            },
        )
        listing = await ac.get("/api/transactions")

    assert response.status_code == 404
    assert listing.json() == []  # not A's or B's history


async def test_cash_flow_snapshot_is_built_from_the_callers_portfolio_only(client_for, world, db_session):
    cash = make_asset("CASHX", asset_type=__import__("app.models", fromlist=["AssetType"]).AssetType.CASH)
    db_session.add(cash)
    await db_session.flush()
    await make_current_price(db_session, cash, Decimal("1"))
    await db_session.commit()

    async with client_for(world.a.user) as ac:
        response = await ac.post(
            "/api/transactions",
            json={
                "asset_id": str(cash.id),
                "transaction_type": "DEPOSIT",
                "quantity": "500",
                "price": "1",
                "fees": "0",
                "transaction_date": "2026-04-01T00:00:00Z",
            },
        )
    assert response.status_code == 201

    snapshots = (await db_session.execute(select(PortfolioSnapshot))).scalars().all()
    assert len(snapshots) == 1
    assert snapshots[0].portfolio_config_id == world.a.config.id
    # invested capital counts only A's own deposits
    assert snapshots[0].invested_capital == Decimal("500.00")


# ============================================================================
# E. Watchlist
# ============================================================================


async def test_user_a_sees_only_own_watchlist(client_for, world):
    async with client_for(world.a.user) as ac:
        a_list = (await ac.get("/api/watchlist")).json()
    async with client_for(world.b.user) as bc:
        b_list = (await bc.get("/api/watchlist")).json()

    assert [e["id"] for e in a_list] == [str(world.a.watchlist.id)]
    assert [e["id"] for e in b_list] == [str(world.b.watchlist.id)]
    assert a_list[0]["notes"] == "Alpha watch"


async def test_user_a_cannot_mutate_user_b_watchlist_entry(client_for, world, db_session):
    async with client_for(world.a.user) as ac:
        patch = await ac.patch(f"/api/watchlist/{world.b.watchlist.id}", json={"enabled": False, "notes": "hijack"})
        delete = await ac.delete(f"/api/watchlist/{world.b.watchlist.id}")

    assert patch.status_code == 404
    assert delete.status_code == 404
    await db_session.refresh(world.b.watchlist)
    assert world.b.watchlist.enabled is True
    assert world.b.watchlist.notes == "Beta watch"
    assert world.b.watchlist.removed_at is None


async def test_both_users_can_watch_the_same_global_asset_independently(client_for, world, db_session):
    from app.tests.conftest import make_user

    asset = make_asset("COWATCH")
    newcomer = await make_user(db_session)
    db_session.add_all([asset, PortfolioConfig(user_id=newcomer.id, name="Third", base_currency="EGP")])
    await db_session.commit()

    async with client_for(world.a.user) as ac:
        a_add = await ac.post("/api/watchlist", json={"asset_id": str(asset.id)})
    async with client_for(newcomer) as nc:
        c_add = await nc.post("/api/watchlist", json={"asset_id": str(asset.id)})
        c_dup = await nc.post("/api/watchlist", json={"asset_id": str(asset.id)})

    assert a_add.status_code == 201 and c_add.status_code == 201
    assert a_add.json()["id"] != c_add.json()["id"]
    assert c_dup.status_code == 409  # still unique per portfolio

    async with client_for(newcomer) as nc:
        await nc.delete(f"/api/watchlist/{c_add.json()['id']}")
    async with client_for(world.a.user) as ac:
        a_entry = next(e for e in (await ac.get("/api/watchlist")).json() if e["asset_id"] == str(asset.id))
    assert a_entry["enabled"] is True  # unaffected by the other user's removal


async def test_watchlist_without_a_portfolio_is_empty_and_cannot_be_added_to(client_for, world, db_session):
    from app.tests.conftest import make_user

    newcomer = await make_user(db_session)
    await db_session.commit()

    async with client_for(newcomer) as nc:
        listing = await nc.get("/api/watchlist")
        add = await nc.post("/api/watchlist", json={"asset_id": str(world.shared_asset.id)})

    assert listing.json() == []
    assert add.status_code == 404


# ============================================================================
# F. Alert rules
# ============================================================================


async def test_user_a_accesses_own_alert_rule(client_for, world):
    async with client_for(world.a.user) as ac:
        got = await ac.get(f"/api/watchlist/{world.a.watchlist.id}/alerts")
        patched = await ac.patch(f"/api/alerts/{world.a.rule.id}", json={"price_target": "123"})

    assert got.status_code == 200
    assert got.json()["id"] == str(world.a.rule.id)
    assert patched.status_code == 200
    assert Decimal(patched.json()["price_target"]) == Decimal("123")


async def test_user_a_cannot_access_user_b_alert_rule(client_for, world, db_session):
    async with client_for(world.a.user) as ac:
        got = await ac.get(f"/api/watchlist/{world.b.watchlist.id}/alerts")
        patched = await ac.patch(f"/api/alerts/{world.b.rule.id}", json={"price_target": "1"})
        deleted = await ac.delete(f"/api/alerts/{world.b.rule.id}")

    assert got.status_code == 404
    assert patched.status_code == 404
    assert deleted.status_code == 404
    await db_session.refresh(world.b.rule)
    assert world.b.rule.price_target == Decimal("100")
    still = (await db_session.execute(select(func.count()).select_from(AlertRule))).scalar_one()
    assert still == 2


async def test_user_a_cannot_attach_an_alert_to_user_b_watchlist(client_for, world, db_session):
    other = make_asset("BWATCHONLY")
    db_session.add(other)
    await db_session.flush()
    b_entry = Watchlist(portfolio_config_id=world.b.config.id, asset_id=other.id)
    db_session.add(b_entry)
    await db_session.commit()

    async with client_for(world.a.user) as ac:
        response = await ac.post(f"/api/watchlist/{b_entry.id}/alerts", json={"price_target_enabled": False})

    assert response.status_code == 404
    count = (
        await db_session.execute(select(func.count()).select_from(AlertRule).where(AlertRule.watchlist_id == b_entry.id))
    ).scalar_one()
    assert count == 0


async def test_user_a_cannot_attach_an_alert_to_user_b_portfolio(client_for, world, db_session):
    """The rule's portfolio is derived server-side from the (owned) watchlist
    entry; a client-supplied portfolio/user id in the body is ignored."""
    other = make_asset("AWATCH")
    db_session.add(other)
    await db_session.flush()
    a_entry = Watchlist(portfolio_config_id=world.a.config.id, asset_id=other.id)
    db_session.add(a_entry)
    await db_session.commit()

    async with client_for(world.a.user) as ac:
        response = await ac.post(
            f"/api/watchlist/{a_entry.id}/alerts",
            json={"portfolio_config_id": str(world.b.config.id), "user_id": str(world.b.user.id)},
        )
    assert response.status_code == 201

    rule = (await db_session.execute(select(AlertRule).where(AlertRule.watchlist_id == a_entry.id))).scalar_one()
    assert rule.portfolio_config_id == world.a.config.id


async def test_an_alert_rule_with_inconsistent_ownership_paths_is_unreachable_by_both(client_for, world, db_session):
    """Defense in depth: a rule whose own portfolio_config_id and whose
    watchlist's portfolio disagree is reachable by NEITHER owner."""
    other = make_asset("INCONSISTENT")
    db_session.add(other)
    await db_session.flush()
    b_entry = Watchlist(portfolio_config_id=world.b.config.id, asset_id=other.id)
    db_session.add(b_entry)
    await db_session.flush()
    rule = AlertRule(portfolio_config_id=world.a.config.id, watchlist_id=b_entry.id)  # mismatched on purpose
    db_session.add(rule)
    await db_session.commit()

    async with client_for(world.a.user) as ac:
        assert (await ac.patch(f"/api/alerts/{rule.id}", json={"enabled": False})).status_code == 404
    async with client_for(world.b.user) as bc:
        assert (await bc.patch(f"/api/alerts/{rule.id}", json={"enabled": False})).status_code == 404


async def test_alert_updates_cannot_change_ownership_columns(client_for, world, db_session):
    async with client_for(world.a.user) as ac:
        response = await ac.patch(
            f"/api/alerts/{world.a.rule.id}",
            json={"portfolio_config_id": str(world.b.config.id), "watchlist_id": str(world.b.watchlist.id)},
        )
    assert response.status_code == 200

    await db_session.refresh(world.a.rule)
    assert world.a.rule.portfolio_config_id == world.a.config.id
    assert world.a.rule.watchlist_id == world.a.watchlist.id


async def test_alert_evaluation_only_evaluates_the_callers_rules(client_for, world, db_session):
    async with client_for(world.a.user) as ac:
        response = await ac.post("/api/alerts/evaluate")

    assert response.status_code == 200
    evaluated = {r["alert_rule_id"] for r in response.json()["results"]}
    assert evaluated == {str(world.a.rule.id)}
    await db_session.refresh(world.b.rule)
    assert world.b.rule.last_triggered_at is None  # B's rule was never evaluated
    await db_session.refresh(world.a.rule)
    assert world.a.rule.last_triggered_at is not None


# ============================================================================
# G. Notifications
# ============================================================================


async def _notification_ids(client) -> list[str]:
    return [n["id"] for n in (await client.get("/api/portfolio/notifications")).json()["notifications"]]


async def test_user_a_accesses_own_notifications(client_for, world):
    async with client_for(world.a.user) as ac:
        body = (await ac.get("/api/portfolio/notifications")).json()

    assert body["unread_count"] >= 1
    assert any(n["category"] == "PRICE_ALERT" for n in body["notifications"])


async def test_each_user_only_ever_sees_their_own_notification_rows(client_for, world, db_session):
    async with client_for(world.a.user) as ac:
        a_ids = set(await _notification_ids(ac))
    async with client_for(world.b.user) as bc:
        b_ids = set(await _notification_ids(bc))

    assert a_ids and b_ids and a_ids.isdisjoint(b_ids)
    owners = {
        str(row.id): row.portfolio_config_id for row in (await db_session.execute(select(Notification))).scalars()
    }
    assert {owners[i] for i in a_ids} == {world.a.config.id}
    assert {owners[i] for i in b_ids} == {world.b.config.id}


async def test_user_a_cannot_read_or_mutate_user_b_notification(client_for, world, db_session):
    async with client_for(world.b.user) as bc:
        b_id = (await _notification_ids(bc))[0]

    async with client_for(world.a.user) as ac:
        response = await ac.patch(f"/api/portfolio/notifications/{b_id}/read")
    assert response.status_code == 404
    assert "PRICE" not in response.text and "SHARED1" not in response.text  # no content leaked

    row = (await db_session.execute(select(Notification).where(Notification.id == uuid.UUID(b_id)))).scalar_one()
    assert row.read_at is None


async def test_read_all_only_marks_the_callers_notifications(client_for, world, db_session):
    async with client_for(world.a.user) as ac:
        await ac.get("/api/portfolio/notifications")
    async with client_for(world.b.user) as bc:
        await bc.get("/api/portfolio/notifications")

    async with client_for(world.a.user) as ac:
        result = (await ac.post("/api/portfolio/notifications/read-all")).json()
    assert result["unread_count"] == 0

    b_rows = (
        await db_session.execute(select(Notification).where(Notification.portfolio_config_id == world.b.config.id))
    ).scalars().all()
    assert b_rows and all(row.read_at is None for row in b_rows)


async def test_user_can_mark_their_own_notification_read(client_for, world):
    async with client_for(world.a.user) as ac:
        notification_id = (await _notification_ids(ac))[0]
        response = await ac.patch(f"/api/portfolio/notifications/{notification_id}/read")

    assert response.status_code == 200
    assert response.json()["read"] is True


# ============================================================================
# H. Global market / reference data stays global
# ============================================================================


async def test_authenticated_users_both_read_the_same_global_market_data(client_for, world):
    async with client_for(world.a.user) as ac:
        a_assets = (await ac.get("/api/assets")).json()
        a_price = (await ac.get(f"/api/assets/{world.shared_asset.id}/price")).json()
    async with client_for(world.b.user) as bc:
        b_assets = (await bc.get("/api/assets")).json()
        b_price = (await bc.get(f"/api/assets/{world.shared_asset.id}/price")).json()

    assert {a["symbol"] for a in a_assets} == {a["symbol"] for a in b_assets} == {"SHARED1"}
    assert a_price["price"] == b_price["price"]
    assert Decimal(a_price["price"]) == Decimal("100")


async def test_global_tables_carry_no_ownership_and_are_unchanged_by_user_activity(client_for, world, db_session):
    before = (await db_session.execute(select(func.count()).select_from(Asset))).scalar_one()
    async with client_for(world.a.user) as ac:
        await ac.get("/api/portfolio/summary")
        await ac.post("/api/watchlist", json={"asset_id": str(world.shared_asset.id)})
    after = (await db_session.execute(select(func.count()).select_from(Asset))).scalar_one()

    assert before == after == 1
    assert not {"user_id", "portfolio_config_id"} & {c.name for c in Asset.__table__.columns}


async def test_an_assets_strategy_bucket_is_masked_unless_it_is_the_callers_own(client_for, world):
    async with client_for(world.a.user) as ac:
        a_view = (await ac.get(f"/api/assets/{world.shared_asset.id}")).json()
    async with client_for(world.b.user) as bc:
        b_view = (await bc.get(f"/api/assets/{world.shared_asset.id}")).json()
        b_listing = (await bc.get("/api/assets")).json()

    assert a_view["strategy_bucket_id"] == str(world.a.bucket.id)
    assert b_view["strategy_bucket_id"] is None  # A's bucket id is never shown to B
    assert str(world.a.bucket.id) not in str(b_listing)


async def test_user_b_cannot_assign_an_asset_to_user_a_bucket_or_take_it_over(client_for, world, db_session):
    async with client_for(world.b.user) as bc:
        into_a = await bc.patch(
            f"/api/assets/{world.shared_asset.id}", json={"strategy_bucket_id": str(world.a.bucket.id)}
        )
        steal = await bc.patch(
            f"/api/assets/{world.shared_asset.id}", json={"strategy_bucket_id": str(world.b.bucket.id)}
        )
        clear = await bc.patch(f"/api/assets/{world.shared_asset.id}", json={"clear_strategy_bucket": True})

    assert into_a.status_code in (400, 409)
    assert steal.status_code == 409
    assert clear.status_code == 409
    await db_session.refresh(world.shared_asset)
    assert world.shared_asset.strategy_bucket_id == world.a.bucket.id  # A's assignment intact


async def test_a_user_can_assign_an_unassigned_asset_to_their_own_bucket(client_for, world, db_session):
    free = make_asset("FREEASSET")
    db_session.add(free)
    await db_session.commit()

    async with client_for(world.b.user) as bc:
        ok = await bc.patch(f"/api/assets/{free.id}", json={"strategy_bucket_id": str(world.b.bucket.id)})
        created = await bc.post(
            "/api/assets",
            json={
                "symbol": "BNEW",
                "name": "B New",
                "asset_type": "STOCK",
                "currency": "EGP",
                "strategy_bucket_id": str(world.b.bucket.id),
            },
        )

    assert ok.status_code == 200 and ok.json()["strategy_bucket_id"] == str(world.b.bucket.id)
    assert created.status_code == 201
    async with client_for(world.a.user) as ac:
        creation_by_a = await ac.post(
            "/api/assets",
            json={
                "symbol": "ANEW",
                "name": "A New",
                "asset_type": "STOCK",
                "currency": "EGP",
                "strategy_bucket_id": str(world.b.bucket.id),
            },
        )
    assert creation_by_a.status_code == 400  # cannot create into another user's bucket


# ============================================================================
# I. Background / service paths never fall back to a global / first portfolio
# ============================================================================


class _NoCloseSession:
    def __init__(self, session):
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, *exc_info):
        return False


async def test_eod_worker_snapshots_each_owned_portfolio_from_its_own_data(world, db_session, monkeypatch):
    from app.workers import snapshot_eod

    # an unowned legacy portfolio that must be skipped, not adopted
    legacy = PortfolioConfig(user_id=None, name="Legacy", base_currency="EGP")
    db_session.add(legacy)
    await db_session.commit()
    monkeypatch.setattr(snapshot_eod, "async_session_factory", lambda: _NoCloseSession(db_session))

    await snapshot_eod.run_snapshot_eod()

    snaps = {
        s.portfolio_config_id: s
        for s in (
            await db_session.execute(select(PortfolioSnapshot).where(PortfolioSnapshot.trigger_source == "EOD"))
        ).scalars()
    }
    assert set(snaps) == {world.a.config.id, world.b.config.id}  # nobody else, notably not the legacy one
    assert legacy.id not in snaps
    # each snapshot is valued from that portfolio's OWN holding: 10 x 100 and 40 x 100
    assert snaps[world.a.config.id].total_cost_basis == Decimal("500.00")
    assert snaps[world.b.config.id].total_cost_basis == Decimal("2400.00")


async def test_eod_worker_refuses_to_run_when_no_portfolio_is_owned(db_session, monkeypatch):
    from app.workers import snapshot_eod

    db_session.add(PortfolioConfig(user_id=None, name="Only Legacy", base_currency="EGP"))
    await db_session.commit()
    monkeypatch.setattr(snapshot_eod, "async_session_factory", lambda: _NoCloseSession(db_session))

    with pytest.raises(snapshot_eod.PortfolioNotConfiguredError):
        await snapshot_eod.run_snapshot_eod()

    assert (await db_session.execute(select(func.count()).select_from(PortfolioSnapshot))).scalar_one() == 0


async def test_eod_worker_one_failing_portfolio_does_not_block_the_others(world, db_session, monkeypatch):
    from app.workers import snapshot_eod

    monkeypatch.setattr(snapshot_eod, "async_session_factory", lambda: _NoCloseSession(db_session))
    real = snapshot_eod.create_eod_snapshot_if_missing
    # ids captured up front: the failing portfolio's rollback expires every
    # loaded object in the (shared, test) session
    a_id, b_id = world.a.config.id, world.b.config.id

    async def flaky(session, *, config):
        if config.id == a_id:
            raise RuntimeError("boom")
        return await real(session, config=config)

    monkeypatch.setattr(snapshot_eod, "create_eod_snapshot_if_missing", flaky)

    with pytest.raises(RuntimeError):
        await snapshot_eod.run_snapshot_eod()  # non-zero exit so a scheduler notices

    done = {
        s.portfolio_config_id
        for s in (await db_session.execute(select(PortfolioSnapshot).where(PortfolioSnapshot.trigger_source == "EOD")))
        .scalars()
    }
    assert done == {b_id}


async def test_telegram_worker_only_acts_on_opted_in_owned_portfolios(world, db_session, monkeypatch):
    """Notification delivery is iterated per owned portfolio and selected/
    marked strictly within it: B has not opted in, so B's notifications are
    never sent and never marked sent, while A's are."""
    from app.services.notification_service import sync_notifications
    from app.tests.test_alert_notify_worker import RecordingCenterNotifier, _enable_telegram_globally, _run_worker

    world.a.config.telegram_enabled = True
    world.a.rule.telegram_enabled = True
    world.b.config.telegram_enabled = False
    world.b.rule.telegram_enabled = True
    await db_session.commit()
    await sync_notifications(db_session, world.a.user.id)
    await sync_notifications(db_session, world.b.user.id)

    _enable_telegram_globally(monkeypatch)
    notifier = RecordingCenterNotifier(should_succeed=True)
    await _run_worker(db_session, monkeypatch, notifier)

    rows = (await db_session.execute(select(Notification))).scalars().all()
    a_rows = [r for r in rows if r.portfolio_config_id == world.a.config.id]
    b_rows = [r for r in rows if r.portfolio_config_id == world.b.config.id]
    assert a_rows and b_rows
    assert all(r.telegram_sent_at is not None for r in a_rows)
    assert all(r.telegram_sent_at is None for r in b_rows)
    assert len(notifier.dispatched) == len(a_rows)


async def test_telegram_worker_delivers_each_opted_in_portfolio_its_own_notifications(world, db_session, monkeypatch):
    """Both portfolios opted in, handled by one worker session: each
    portfolio's notifications are delivered and marked sent within that
    portfolio, with no cross-talk and nothing delivered twice."""
    from app.services.notification_service import sync_notifications
    from app.tests.test_alert_notify_worker import RecordingCenterNotifier, _enable_telegram_globally, _run_worker

    for tenant in (world.a, world.b):
        tenant.config.telegram_enabled = True
        tenant.rule.telegram_enabled = True
    await db_session.commit()
    await sync_notifications(db_session, world.a.user.id)
    await sync_notifications(db_session, world.b.user.id)

    _enable_telegram_globally(monkeypatch)
    notifier = RecordingCenterNotifier(should_succeed=True)
    await _run_worker(db_session, monkeypatch, notifier)

    rows = (await db_session.execute(select(Notification))).scalars().all()
    assert {r.portfolio_config_id for r in rows} == {world.a.config.id, world.b.config.id}
    assert all(r.telegram_sent_at is not None for r in rows)
    assert len(notifier.dispatched) == len(rows)


async def test_services_resolve_only_by_user_never_by_a_global_first_row(world, db_session):
    """Directly at the service layer: with several portfolios present, each
    user resolves their own, and an unknown user resolves nothing."""
    from app.repositories.portfolio_repository import get_portfolio_config_for_user, list_owned_portfolio_configs

    a_cfg = await get_portfolio_config_for_user(db_session, world.a.user.id)
    b_cfg = await get_portfolio_config_for_user(db_session, world.b.user.id)
    nobody = await get_portfolio_config_for_user(db_session, uuid.uuid4())

    assert a_cfg.id == world.a.config.id
    assert b_cfg.id == world.b.config.id
    assert nobody is None
    owned = {c.id for c in await list_owned_portfolio_configs(db_session)}
    assert owned == {world.a.config.id, world.b.config.id}


async def test_get_active_assets_only_loads_the_requested_portfolios_holding(world, db_session):
    """Called back-to-back on ONE session (as a worker iterating portfolios
    does): each call must reflect only the requested portfolio's holding, not
    whatever was loaded into the shared `Asset` objects by the previous call."""
    from app.repositories.portfolio_repository import get_active_assets

    a_assets = await get_active_assets(db_session, world.a.config.id)
    a_holding = next(a for a in a_assets if a.symbol == "SHARED1").holding
    assert a_holding.portfolio_config_id == world.a.config.id
    assert a_holding.quantity == Decimal("10")

    b_assets = await get_active_assets(db_session, world.b.config.id)
    b_holding = next(a for a in b_assets if a.symbol == "SHARED1").holding
    assert b_holding.portfolio_config_id == world.b.config.id
    assert b_holding.quantity == Decimal("40")

    other_assets = await get_active_assets(db_session, uuid.uuid4())
    assert next(a for a in other_assets if a.symbol == "SHARED1").holding is None

    again = await get_active_assets(db_session, world.a.config.id)
    assert next(a for a in again if a.symbol == "SHARED1").holding.quantity == Decimal("10")
