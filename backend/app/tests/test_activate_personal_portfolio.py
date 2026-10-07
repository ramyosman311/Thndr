"""P0-3D: the production ownership-activation tool, against a real PostgreSQL."""

import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import text

from app.models import (
    AllocationTarget,
    Holding,
    PortfolioConfig,
    StrategyBucket,
    Transaction,
    TransactionType,
    Watchlist,
)
from app.ops import activate_personal_portfolio as ops
from app.tests.conftest import make_asset

EMAIL = "Ramy@Example.com"


@pytest_asyncio.fixture
async def conn(db_session):
    connection = await db_session.connection()
    await connection.execute(text("CREATE SCHEMA IF NOT EXISTS auth"))
    await connection.execute(text("CREATE TABLE IF NOT EXISTS auth.users (id uuid PRIMARY KEY, email text)"))
    await connection.execute(text("DELETE FROM auth.users"))
    return connection


async def add_auth_user(conn, email=EMAIL) -> uuid.UUID:
    uid = uuid.uuid4()
    await conn.execute(text("INSERT INTO auth.users (id, email) VALUES (:i, :e)"), {"i": uid, "e": email})
    return uid


async def seed_unowned_portfolio(session) -> PortfolioConfig:
    """A pre-ownership production-shaped portfolio: everything unowned (NULL)."""
    config = PortfolioConfig(name="MIZAN", base_currency="EGP")
    session.add(config)
    asset = make_asset(f"A{uuid.uuid4().hex[:6]}")
    session.add(asset)
    await session.flush()
    bucket = StrategyBucket(portfolio_config_id=config.id, name="Growth")
    session.add(bucket)
    await session.flush()
    session.add(AllocationTarget(portfolio_config_id=config.id, strategy_bucket_id=bucket.id, target_percent=Decimal("40")))
    session.add(Holding(asset_id=asset.id, quantity=Decimal("10"), average_cost=Decimal("12.5")))
    session.add(
        Transaction(
            asset_id=asset.id,
            transaction_type=TransactionType.BUY,
            quantity=Decimal("10"),
            price=Decimal("12.5"),
            fees=Decimal("0"),
            transaction_date=datetime.now(timezone.utc),
        )
    )
    session.add(Watchlist(asset_id=asset.id))
    await session.flush()
    return config


async def test_dry_run_changes_nothing_but_passes_checks(db_session, conn):
    config = await seed_unowned_portfolio(db_session)
    uid = await add_auth_user(conn)

    report = await ops.run(conn, EMAIL)

    assert report.user_id == uid and report.portfolio_id == config.id
    assert report.committed_changes["portfolio_configs.user_id set"] == 1
    assert report.committed_changes["holdings.portfolio_config_id set"] == 1


async def test_activation_sets_ownership_only_and_makes_data_visible(db_session, conn):
    config = await seed_unowned_portfolio(db_session)
    uid = await add_auth_user(conn)
    before = await ops._fingerprint(conn)

    await ops.run(conn, "ramy@example.com")  # case-insensitive e-mail match

    owner = (await conn.execute(text("SELECT user_id FROM portfolio_configs WHERE id=:p"), {"p": config.id})).scalar_one()
    assert owner == uid
    assert (await conn.execute(text("SELECT count(*) FROM users WHERE id=:u"), {"u": uid})).scalar_one() == 1
    for table in ops.OWNED_CHILD_TABLES:
        n = (await conn.execute(text(f"SELECT count(*) FROM {table} WHERE portfolio_config_id=:p"), {"p": config.id})).scalar_one()
        total = (await conn.execute(text(f"SELECT count(*) FROM {table}"))).scalar_one()
        assert n == total
    # financial content untouched (the tool itself asserts this; re-check independently)
    assert await ops._fingerprint(conn) == before
    assert (await conn.execute(text("SELECT quantity FROM holdings"))).scalar_one() == Decimal("10")


async def test_idempotent_second_run(db_session, conn):
    await seed_unowned_portfolio(db_session)
    await add_auth_user(conn)
    await ops.run(conn, EMAIL)
    report = await ops.run(conn, EMAIL)
    assert report.committed_changes["portfolio_configs.user_id set"] == 0
    assert report.committed_changes["holdings.portfolio_config_id set"] == 0


async def test_stops_when_no_portfolio(db_session, conn):
    await add_auth_user(conn)
    with pytest.raises(ops.ActivationError) as exc:
        await ops.run(conn, EMAIL)
    assert exc.value.code == ops.EXIT_NO_PORTFOLIO


async def test_stops_and_writes_nothing_with_two_portfolios(db_session, conn):
    await seed_unowned_portfolio(db_session)
    db_session.add(PortfolioConfig(name="Second", base_currency="EGP"))
    await db_session.flush()
    await add_auth_user(conn)
    with pytest.raises(ops.ActivationError) as exc:
        await ops.run(conn, EMAIL)
    assert exc.value.code == ops.EXIT_MANY_PORTFOLIOS
    assert (await conn.execute(text("SELECT count(*) FROM portfolio_configs WHERE user_id IS NOT NULL"))).scalar_one() == 0
    assert (await conn.execute(text("SELECT count(*) FROM holdings WHERE portfolio_config_id IS NOT NULL"))).scalar_one() == 0


async def test_stops_when_auth_user_missing_or_ambiguous(db_session, conn):
    await seed_unowned_portfolio(db_session)
    with pytest.raises(ops.ActivationError) as exc:
        await ops.run(conn, EMAIL)
    assert exc.value.code == ops.EXIT_USER

    await add_auth_user(conn, "dup@example.com")
    await add_auth_user(conn, "DUP@example.com")
    with pytest.raises(ops.ActivationError) as exc2:
        await ops.run(conn, "dup@example.com")
    assert exc2.value.code == ops.EXIT_USER


async def test_never_reassigns_a_portfolio_owned_by_someone_else(db_session, conn, user_b):
    config = await seed_unowned_portfolio(db_session)
    config.user_id = user_b.id
    await db_session.flush()
    await add_auth_user(conn)
    with pytest.raises(ops.ActivationError) as exc:
        await ops.run(conn, EMAIL)
    assert exc.value.code == ops.EXIT_OWNED_BY_OTHER
    assert (await conn.execute(text("SELECT user_id FROM portfolio_configs"))).scalar_one() == user_b.id


async def test_fingerprint_drift_aborts(db_session, conn, monkeypatch):
    await seed_unowned_portfolio(db_session)
    await add_auth_user(conn)
    real = ops._fingerprint
    calls = {"n": 0}

    async def drifting(c):
        calls["n"] += 1
        result = await real(c)
        if calls["n"] == 2:
            result["holdings"] = (result["holdings"][0], "tampered")
        return result

    monkeypatch.setattr(ops, "_fingerprint", drifting)
    with pytest.raises(ops.ActivationError) as exc:
        await ops.run(conn, EMAIL)
    assert exc.value.code == ops.EXIT_UNSAFE


async def test_activated_user_sees_portfolio_through_the_api(db_session, conn, client_for):
    """End to end: after activation the P0-3C-scoped API serves the real portfolio."""
    from app.models import User

    config = await seed_unowned_portfolio(db_session)
    uid = await add_auth_user(conn)
    await ops.run(conn, EMAIL)
    user = User(id=uid)
    async with client_for(user) as client:
        response = await client.get("/api/portfolio/summary")
    assert response.status_code == 200, response.text
    assert config.id  # the portfolio the API resolved is the activated one
