import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.api.routes import health as health_route
from app.core.database import engine
from app.main import app
from app.services import health_service


@pytest_asyncio.fixture(autouse=True)
async def _dispose_global_engine_pool_after_each_test():
    """`app.core.database.engine` is a process-wide singleton pool, but
    pytest-asyncio gives each test function its own event loop -- without
    disposing the pool between tests, a connection acquired under one
    test's loop can be reused/cleaned up under the next test's (already
    closed) loop, raising "Event loop is closed" from asyncpg. Every other
    test file avoids this by using the `db_session` fixture's own
    NullPool-backed engine instead; this file is the one place that
    exercises the real app (and therefore the real global engine) over
    HTTP, so it needs this instead."""
    yield
    await engine.dispose()


@pytest.mark.asyncio
async def test_health_returns_ok_status():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["database"] in {"connected", "unavailable"}


# --- Phase 23: readiness --------------------------------------------------


@pytest.mark.asyncio
async def test_readiness_returns_200_when_database_reachable():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


@pytest.mark.asyncio
async def test_readiness_returns_503_when_database_unreachable(monkeypatch):
    async def fake_is_ready() -> bool:
        return False

    monkeypatch.setattr(health_route, "is_ready", fake_is_ready)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/health/ready")

    assert response.status_code == 503
    assert "detail" in response.json()


@pytest.mark.asyncio
async def test_readiness_never_flips_the_liveness_endpoint(monkeypatch):
    """Liveness (/health) and readiness (/health/ready) are deliberately
    distinct -- a database outage must not make the process report itself
    as not-alive, only as not-ready to serve requests."""
    async def fake_check_database_connection() -> bool:
        return False

    monkeypatch.setattr(health_service, "check_database_connection", fake_check_database_connection)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        health_response = await client.get("/api/health")
        readiness_response = await client.get("/api/health/ready")

    assert health_response.status_code == 200
    assert health_response.json() == {"status": "ok", "database": "unavailable"}
    assert readiness_response.status_code == 503
