"""Strategy Bucket + Allocation Target administration tests (Phase 12):
create/update/activate/deactivate buckets; create/update targets with
per-row range/min-max validation. Never blocks on aggregate strategy
validity (see FINANCIAL_RULES.md, "Strategy Validation Ownership")."""

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.core.database import get_db_session
from app.main import app
from app.tests.conftest import make_portfolio_config


@pytest_asyncio.fixture
async def client(db_session):
    async def _override_get_db_session():
        yield db_session

    app.dependency_overrides[get_db_session] = _override_get_db_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.pop(get_db_session, None)


async def _configured_portfolio(session):
    config = make_portfolio_config()
    session.add(config)
    await session.commit()
    return config


async def test_list_buckets_404_when_no_portfolio_configured(client):
    response = await client.get("/api/strategy/buckets")
    assert response.status_code == 404


async def test_create_bucket_succeeds(db_session, client):
    await _configured_portfolio(db_session)
    response = await client.post("/api/strategy/buckets", json={"name": "Growth", "description": "Growth assets"})
    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Growth"
    assert body["is_active"] is True


async def test_create_bucket_rejects_duplicate_name(db_session, client):
    await _configured_portfolio(db_session)
    await client.post("/api/strategy/buckets", json={"name": "Defensive"})
    response = await client.post("/api/strategy/buckets", json={"name": "Defensive"})
    assert response.status_code == 409


async def test_create_bucket_rejects_blank_name(db_session, client):
    await _configured_portfolio(db_session)
    response = await client.post("/api/strategy/buckets", json={"name": "   "})
    assert response.status_code == 422


async def test_update_bucket_edits_description(db_session, client):
    await _configured_portfolio(db_session)
    created = await client.post("/api/strategy/buckets", json={"name": "Cash"})
    bucket_id = created.json()["id"]

    response = await client.patch(f"/api/strategy/buckets/{bucket_id}", json={"description": "Liquid reserves"})
    assert response.status_code == 200
    assert response.json()["description"] == "Liquid reserves"


async def test_update_bucket_404_for_missing_bucket(client):
    response = await client.patch(
        "/api/strategy/buckets/00000000-0000-0000-0000-000000000000", json={"name": "X"}
    )
    assert response.status_code == 404


async def test_deactivate_and_reactivate_bucket(db_session, client):
    await _configured_portfolio(db_session)
    created = await client.post("/api/strategy/buckets", json={"name": "Gold"})
    bucket_id = created.json()["id"]

    deactivated = await client.post(f"/api/strategy/buckets/{bucket_id}/deactivate")
    assert deactivated.status_code == 200
    assert deactivated.json()["is_active"] is False

    default_listing = await client.get("/api/strategy/buckets")
    assert not any(b["id"] == bucket_id for b in default_listing.json())

    full_listing = await client.get("/api/strategy/buckets?include_inactive=true")
    assert any(b["id"] == bucket_id for b in full_listing.json())

    reactivated = await client.post(f"/api/strategy/buckets/{bucket_id}/activate")
    assert reactivated.status_code == 200
    assert reactivated.json()["is_active"] is True


async def test_create_target_succeeds(db_session, client):
    await _configured_portfolio(db_session)
    bucket = await client.post("/api/strategy/buckets", json={"name": "Growth"})
    bucket_id = bucket.json()["id"]

    response = await client.post(
        "/api/strategy/targets",
        json={
            "strategy_bucket_id": bucket_id,
            "target_percent": "55.00",
            "maximum_percent": "70.00",
            "allow_new_buy": True,
            "priority": 1,
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["target_percent"] == "55.00"
    assert body["is_active"] is True


async def test_create_target_rejects_unknown_bucket(db_session, client):
    await _configured_portfolio(db_session)
    response = await client.post(
        "/api/strategy/targets",
        json={"strategy_bucket_id": "00000000-0000-0000-0000-000000000000", "target_percent": "10"},
    )
    assert response.status_code == 400


async def test_create_target_rejects_out_of_range_percent(db_session, client):
    await _configured_portfolio(db_session)
    bucket = await client.post("/api/strategy/buckets", json={"name": "Overflow"})
    response = await client.post(
        "/api/strategy/targets",
        json={"strategy_bucket_id": bucket.json()["id"], "target_percent": "150"},
    )
    assert response.status_code == 422


async def test_create_target_rejects_minimum_above_maximum(db_session, client):
    await _configured_portfolio(db_session)
    bucket = await client.post("/api/strategy/buckets", json={"name": "Inverted"})
    response = await client.post(
        "/api/strategy/targets",
        json={"strategy_bucket_id": bucket.json()["id"], "minimum_percent": "50", "maximum_percent": "10"},
    )
    assert response.status_code == 422


async def test_create_target_rejects_duplicate_for_same_bucket(db_session, client):
    await _configured_portfolio(db_session)
    bucket = await client.post("/api/strategy/buckets", json={"name": "OnlyOne"})
    bucket_id = bucket.json()["id"]
    await client.post("/api/strategy/targets", json={"strategy_bucket_id": bucket_id, "target_percent": "10"})

    response = await client.post(
        "/api/strategy/targets", json={"strategy_bucket_id": bucket_id, "target_percent": "20"}
    )
    assert response.status_code == 409


async def test_update_target_changes_priority_and_allow_new_buy(db_session, client):
    await _configured_portfolio(db_session)
    bucket = await client.post("/api/strategy/buckets", json={"name": "Adjustable"})
    created = await client.post(
        "/api/strategy/targets", json={"strategy_bucket_id": bucket.json()["id"], "target_percent": "30"}
    )
    target_id = created.json()["id"]

    response = await client.patch(
        f"/api/strategy/targets/{target_id}", json={"priority": 5, "allow_new_buy": False}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["priority"] == 5
    assert body["allow_new_buy"] is False


async def test_update_target_rejects_minimum_exceeding_existing_maximum(db_session, client):
    await _configured_portfolio(db_session)
    bucket = await client.post("/api/strategy/buckets", json={"name": "Bounded"})
    created = await client.post(
        "/api/strategy/targets",
        json={"strategy_bucket_id": bucket.json()["id"], "maximum_percent": "20"},
    )
    target_id = created.json()["id"]

    response = await client.patch(f"/api/strategy/targets/{target_id}", json={"minimum_percent": "50"})
    assert response.status_code == 400


async def test_update_target_can_clear_target_percent(db_session, client):
    await _configured_portfolio(db_session)
    bucket = await client.post("/api/strategy/buckets", json={"name": "Clearable"})
    created = await client.post(
        "/api/strategy/targets", json={"strategy_bucket_id": bucket.json()["id"], "target_percent": "40"}
    )
    target_id = created.json()["id"]

    response = await client.patch(f"/api/strategy/targets/{target_id}", json={"clear_target_percent": True})
    assert response.status_code == 200
    assert response.json()["target_percent"] is None


async def test_creating_incomplete_strategy_is_not_rejected(db_session, client):
    """A single target below 100% must be accepted -- aggregate
    completeness is `GET /api/portfolio/strategy/validation`'s concern,
    never a write-time block (Phase 6 semantics preserved)."""
    await _configured_portfolio(db_session)
    bucket = await client.post("/api/strategy/buckets", json={"name": "PartialOnly"})
    response = await client.post(
        "/api/strategy/targets", json={"strategy_bucket_id": bucket.json()["id"], "target_percent": "10"}
    )
    assert response.status_code == 201

    validation = await client.get("/api/portfolio/strategy/validation")
    assert validation.status_code == 200
    assert validation.json()["status"] == "INCOMPLETE_TARGET_ALLOCATION"
