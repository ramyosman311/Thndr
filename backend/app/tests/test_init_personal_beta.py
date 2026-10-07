"""P0-3D: fresh Personal Beta initialization tool, against a real PostgreSQL."""

import uuid
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import text

from app.models import Holding
from app.ops import init_personal_beta as ops
from app.tests.conftest import make_asset

EMAIL = "Ramyosman@msn.com"


@pytest_asyncio.fixture
async def session(db_session):
    await db_session.execute(text("CREATE SCHEMA IF NOT EXISTS auth"))
    await db_session.execute(text("CREATE TABLE IF NOT EXISTS auth.users (id uuid PRIMARY KEY, email text)"))
    await db_session.execute(text("DELETE FROM auth.users"))
    return db_session


async def add_auth_user(session, email=EMAIL) -> uuid.UUID:
    uid = uuid.uuid4()
    await session.execute(text("INSERT INTO auth.users (id, email) VALUES (:i, :e)"), {"i": uid, "e": email})
    return uid


async def count(session, table):
    return (await session.execute(text(f"SELECT count(*) FROM {table}"))).scalar_one()


async def test_creates_one_empty_owned_portfolio_and_no_financial_data(session):
    uid = await add_auth_user(session)

    report = await ops.run(session, "ramyosman@msn.com")  # case-insensitive

    assert report.user_id == uid
    owner = (await session.execute(text("SELECT user_id FROM portfolio_configs"))).scalar_one()
    assert owner == uid
    assert await count(session, "portfolio_configs") == 1
    assert await count(session, "users") == 1
    assert await count(session, "assets") == 7
    assert await count(session, "strategy_buckets") == 6
    assert await count(session, "allocation_targets") == 5
    for table in ops.FINANCIAL_TABLES:
        assert await count(session, table) == 0, table


async def test_strategy_values_and_emergency_configuration(session):
    await add_auth_user(session)
    await ops.run(session, EMAIL)
    rows = (
        await session.execute(
            text(
                "SELECT b.name, t.target_percent, t.maximum_percent, t.allow_new_buy FROM allocation_targets t "
                "JOIN strategy_buckets b ON b.id = t.strategy_bucket_id"
            )
        )
    ).all()
    by = {r[0]: r[1:] for r in rows}
    assert by["Growth / Investment Funds"][0] == Decimal("55")
    assert by["Defensive / Fixed Income"][0] == Decimal("25")
    assert by["Free Cash"][0] == Decimal("0")
    assert by["Individual Stocks"][0] is None and by["Individual Stocks"][1] == Decimal("20")
    assert by["Gold"][0] == Decimal("0") and by["Gold"][2] is False
    assert "Emergency Cash" not in by
    total = sum((r[1] or Decimal(0)) for r in rows)
    assert total == Decimal("80")
    cfg = (await session.execute(text("SELECT emergency_excluded, emergency_asset_id FROM portfolio_configs"))).one()
    assert cfg[0] is True and cfg[1] is not None


async def test_stops_when_auth_user_missing_or_ambiguous(session):
    with pytest.raises(ops.InitError) as exc:
        await ops.run(session, EMAIL)
    assert exc.value.code == ops.EXIT_USER
    await add_auth_user(session, "dup@x.com")
    await add_auth_user(session, "DUP@x.com")
    with pytest.raises(ops.InitError) as exc2:
        await ops.run(session, "dup@x.com")
    assert exc2.value.code == ops.EXIT_USER


async def test_refuses_when_a_portfolio_already_exists(session, user_a, portfolio):
    await add_auth_user(session)
    with pytest.raises(ops.InitError) as exc:
        await ops.run(session, EMAIL)
    assert exc.value.code == ops.EXIT_NOT_CLEAN
    assert await count(session, "portfolio_configs") == 1  # untouched, not reassigned


async def test_refuses_when_financial_rows_exist(session):
    await add_auth_user(session)
    asset = make_asset("ZZZ")
    session.add(asset)
    await session.flush()
    session.add(Holding(asset_id=asset.id, quantity=Decimal("1")))
    await session.flush()
    with pytest.raises(ops.InitError) as exc:
        await ops.run(session, EMAIL)
    assert exc.value.code == ops.EXIT_NOT_CLEAN
    assert await count(session, "portfolio_configs") == 0


async def test_initialized_user_reaches_empty_portfolio_through_the_api(session, client_for):
    from app.models import User

    uid = await add_auth_user(session)
    await ops.run(session, EMAIL)
    async with client_for(User(id=uid)) as client:
        response = await client.get("/api/portfolio/config")
    assert response.status_code == 200, response.text
    assert response.json()["emergency_excluded"] is True
