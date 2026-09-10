from decimal import Decimal

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.core.database import get_db_session
from app.main import app
from app.models import Holding, PortfolioConfig, StrategyBucket, Transaction
from app.tests.conftest import make_asset, make_current_price


@pytest_asyncio.fixture
async def client(db_session):
    async def _override_get_db_session():
        yield db_session

    app.dependency_overrides[get_db_session] = _override_get_db_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.pop(get_db_session, None)


async def _setup_simple_portfolio(session, *, emergency_excluded=False):
    from app.models import AllocationTarget

    config = PortfolioConfig(name="API Inflow Portfolio", base_currency="EGP", emergency_excluded=emergency_excluded)
    session.add(config)
    await session.flush()

    bucket = StrategyBucket(portfolio_config_id=config.id, name="API Growth")
    session.add(bucket)
    await session.flush()
    asset = make_asset("APIINFLOW", strategy_bucket_id=bucket.id)
    session.add(asset)
    await session.flush()
    session.add(Holding(asset_id=asset.id, quantity=Decimal("10")))  # value 100
    await make_current_price(session, asset, Decimal("10"))
    session.add(
        AllocationTarget(portfolio_config_id=config.id, strategy_bucket_id=bucket.id, target_percent=Decimal("50"), priority=1)
    )

    # A second, unrelated funded asset so the investable denominator is
    # larger than the "API Growth" bucket alone — otherwise that bucket
    # would always sit at exactly 100% of investable value by
    # construction and could never be underweight relative to any target.
    other_bucket = StrategyBucket(portfolio_config_id=config.id, name="API Other")
    session.add(other_bucket)
    await session.flush()
    other_asset = make_asset("APIOTHER", strategy_bucket_id=other_bucket.id)
    session.add(other_asset)
    await session.flush()
    session.add(Holding(asset_id=other_asset.id, quantity=Decimal("90")))  # value 900
    await make_current_price(session, other_asset, Decimal("10"))

    await session.commit()
    return config, bucket, asset


async def test_cash_flow_allocate_returns_expected_structure(db_session, client):
    await _setup_simple_portfolio(db_session)

    response = await client.post("/api/cash-flow/allocate", json={"amount": "50.00"})
    assert response.status_code == 200
    body = response.json()

    assert Decimal(body["requested_cash"]) == Decimal("50.00")
    assert "allocated_cash" in body and "unallocated_cash" in body
    assert Decimal(body["allocated_cash"]) + Decimal(body["unallocated_cash"]) == Decimal(body["requested_cash"])
    assert "strategy_status" in body
    assert isinstance(body["recommendations"], list) and len(body["recommendations"]) == 2

    rec = next(r for r in body["recommendations"] if r["bucket_name"] == "API Growth")
    assert Decimal(rec["target_gap"]) == Decimal("400.00")
    assert Decimal(rec["allocated_amount"]) == Decimal("50.00")
    assert rec["status"] == "ELIGIBLE"


async def test_cash_flow_allocate_rejects_zero_amount(db_session, client):
    await _setup_simple_portfolio(db_session)
    response = await client.post("/api/cash-flow/allocate", json={"amount": "0"})
    assert response.status_code == 422


async def test_cash_flow_allocate_rejects_negative_amount(db_session, client):
    await _setup_simple_portfolio(db_session)
    response = await client.post("/api/cash-flow/allocate", json={"amount": "-100"})
    assert response.status_code == 422


async def test_cash_flow_allocate_returns_404_when_not_configured(client):
    response = await client.post("/api/cash-flow/allocate", json={"amount": "100"})
    assert response.status_code == 404


async def test_cash_flow_allocate_is_read_only(db_session, client):
    """The endpoint must never create a transaction or modify holdings."""
    config, bucket, asset = await _setup_simple_portfolio(db_session)

    async def counts():
        result = {}
        for model in (Holding, Transaction):
            r = await db_session.execute(select(func.count()).select_from(model))
            result[model.__name__] = r.scalar_one()
        return result

    before = await counts()
    await client.post("/api/cash-flow/allocate", json={"amount": "1000.00"})
    await client.post("/api/cash-flow/allocate", json={"amount": "5000.00"})
    after = await counts()

    assert before == after
    assert after["Transaction"] == 0
