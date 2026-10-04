import uuid
from decimal import Decimal

from sqlalchemy import func, select

from app.models import Holding, Transaction
from app.tests.conftest import make_asset, make_current_price


async def _watched_asset_with_rule(client, db_session, portfolio, symbol, **rule_fields):
    asset = make_asset(symbol)
    db_session.add(asset)
    await db_session.commit()
    db_session.add(Holding(portfolio_config_id=portfolio.id, asset_id=asset.id, quantity=Decimal("1")))
    await make_current_price(db_session, asset, Decimal("150"))
    await db_session.commit()

    add_response = await client.post("/api/watchlist", json={"asset_id": str(asset.id)})
    watchlist_id = add_response.json()["id"]
    rule_response = await client.post(f"/api/watchlist/{watchlist_id}/alerts", json=rule_fields)
    return watchlist_id, rule_response.json()["id"]


async def test_patch_alert_rule_updates_threshold(db_session, client, owner, portfolio):
    _, rule_id = await _watched_asset_with_rule(
        client, db_session, portfolio, "APIALERTPATCH", price_target_enabled=True, price_target="150.00"
    )
    response = await client.patch(f"/api/alerts/{rule_id}", json={"price_target": "200.00"})
    assert response.status_code == 200
    assert Decimal(response.json()["price_target"]) == Decimal("200.00")


async def test_patch_alert_rule_rejects_invalid_resulting_configuration(db_session, client, owner, portfolio):
    _, rule_id = await _watched_asset_with_rule(client, db_session, portfolio, "APIALERTPATCHINVALID")
    response = await client.patch(f"/api/alerts/{rule_id}", json={"dip_buy_enabled": True})
    assert response.status_code == 400


async def test_patch_alert_rule_rejects_missing_rule(client, owner, portfolio):
    response = await client.patch(f"/api/alerts/{uuid.uuid4()}", json={"enabled": False})
    assert response.status_code == 404


async def test_delete_alert_rule_returns_204(db_session, client, owner, portfolio):
    _, rule_id = await _watched_asset_with_rule(client, db_session, portfolio, "APIALERTDEL")
    response = await client.delete(f"/api/alerts/{rule_id}")
    assert response.status_code == 204


async def test_delete_alert_rule_rejects_missing_rule(client, owner, portfolio):
    response = await client.delete(f"/api/alerts/{uuid.uuid4()}")
    assert response.status_code == 404


async def test_evaluate_alerts_returns_results_for_configured_rules(db_session, client, owner, portfolio):
    await _watched_asset_with_rule(
        client, db_session, portfolio, "APIALERTEVAL", price_target_enabled=True, price_target="150.00"
    )
    response = await client.post("/api/alerts/evaluate")
    assert response.status_code == 200
    body = response.json()
    assert "results" in body
    price_entries = [r for r in body["results"] if r["alert_type"] == "PRICE_TARGET"]
    assert len(price_entries) == 1
    assert price_entries[0]["condition_met"] is True
    assert price_entries[0]["is_new_trigger"] is True


async def test_evaluate_alerts_endpoint_is_read_only_for_financial_positions(db_session, client, owner, portfolio):
    await _watched_asset_with_rule(
        client, db_session, portfolio, "APIALERTREADONLY", dip_buy_enabled=True, dip_buy_price="200.00"
    )

    async def counts():
        result = {}
        for model in (Holding, Transaction):
            r = await db_session.execute(select(func.count()).select_from(model))
            result[model.__name__] = r.scalar_one()
        return result

    before = await counts()
    await client.post("/api/alerts/evaluate")
    await client.post("/api/alerts/evaluate")
    after = await counts()
    assert before == after
    assert after["Transaction"] == 0
