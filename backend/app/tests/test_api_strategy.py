from decimal import Decimal

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.core.database import get_db_session
from app.main import app
from app.models import AllocationTarget, PortfolioConfig, StrategyBucket
from app.seed.seed import run_seed


@pytest_asyncio.fixture
async def client(db_session):
    async def _override_get_db_session():
        yield db_session

    app.dependency_overrides[get_db_session] = _override_get_db_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.pop(get_db_session, None)


async def test_strategy_validation_endpoint_returns_expected_structure(db_session, client):
    config = PortfolioConfig(name="API Strategy Portfolio", base_currency="EGP", emergency_excluded=False)
    db_session.add(config)
    await db_session.flush()

    bucket = StrategyBucket(portfolio_config_id=config.id, name="Only Bucket")
    db_session.add(bucket)
    await db_session.flush()
    db_session.add(
        AllocationTarget(portfolio_config_id=config.id, strategy_bucket_id=bucket.id, target_percent=Decimal("100"))
    )
    await db_session.commit()

    response = await client.get("/api/portfolio/strategy/validation")
    assert response.status_code == 200
    body = response.json()

    assert body["status"] == "VALID"
    assert body["is_valid"] is True
    assert Decimal(body["total_target_percent"]) == Decimal("100.00")
    assert Decimal(body["expected_target_percent"]) == Decimal("100.00")
    assert isinstance(body["explanation"], str) and body["explanation"]
    assert len(body["target_rows"]) == 1
    assert body["target_rows"][0]["bucket_name"] == "Only Bucket"
    assert body["maximum_only_rows"] == []
    assert body["field_errors"] == []


async def test_strategy_validation_endpoint_reports_seeded_config_as_incomplete_not_500(db_session, client):
    """An incomplete configuration is a normal 200 response with a
    diagnostic status — never an HTTP 500."""
    await run_seed(db_session)

    response = await client.get("/api/portfolio/strategy/validation")
    assert response.status_code == 200
    body = response.json()

    assert body["status"] == "INCOMPLETE_TARGET_ALLOCATION"
    assert body["is_valid"] is False
    assert Decimal(body["total_target_percent"]) == Decimal("85.00")
    max_only_names = {r["bucket_name"] for r in body["maximum_only_rows"]}
    assert max_only_names == {"Individual Stocks"}


async def test_strategy_validation_returns_404_when_not_configured(client):
    response = await client.get("/api/portfolio/strategy/validation")
    assert response.status_code == 404


async def test_strategy_validation_api_does_not_mutate_database(db_session, client):
    await run_seed(db_session)

    async def counts():
        result = {}
        for model in (AllocationTarget, StrategyBucket, PortfolioConfig):
            r = await db_session.execute(select(func.count()).select_from(model))
            result[model.__name__] = r.scalar_one()
        return result

    before = await counts()
    await client.get("/api/portfolio/strategy/validation")
    await client.get("/api/portfolio/strategy/validation")
    after = await counts()

    assert before == after
