import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.core.database import get_db_session
from app.main import app
from app.tests.conftest import make_asset


@pytest_asyncio.fixture
async def client(db_session):
    async def _override_get_db_session():
        yield db_session

    app.dependency_overrides[get_db_session] = _override_get_db_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.pop(get_db_session, None)


async def test_list_assets_returns_active_assets(db_session, client):
    asset = make_asset("APIASSETLIST")
    db_session.add(asset)
    await db_session.commit()

    response = await client.get("/api/assets")
    assert response.status_code == 200
    body = response.json()
    symbols = {a["symbol"] for a in body}
    assert "APIASSETLIST" in symbols
    row = next(a for a in body if a["symbol"] == "APIASSETLIST")
    assert row["id"] == str(asset.id)
    assert row["is_active"] is True


async def test_list_assets_excludes_inactive_assets(db_session, client):
    asset = make_asset("APIASSETINACTIVE", is_active=False)
    db_session.add(asset)
    await db_session.commit()

    response = await client.get("/api/assets")
    body = response.json()
    assert not any(a["symbol"] == "APIASSETINACTIVE" for a in body)


async def test_list_assets_empty_when_none_exist(client):
    response = await client.get("/api/assets")
    assert response.status_code == 200
    assert response.json() == []
