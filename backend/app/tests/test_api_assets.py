
from app.tests.conftest import make_asset


async def test_list_assets_returns_active_assets(db_session, client, owner):
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


async def test_list_assets_excludes_inactive_assets(db_session, client, owner):
    asset = make_asset("APIASSETINACTIVE", is_active=False)
    db_session.add(asset)
    await db_session.commit()

    response = await client.get("/api/assets")
    body = response.json()
    assert not any(a["symbol"] == "APIASSETINACTIVE" for a in body)


async def test_list_assets_empty_when_none_exist(client, owner):
    response = await client.get("/api/assets")
    assert response.status_code == 200
    assert response.json() == []
