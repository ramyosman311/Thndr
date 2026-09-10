"""Confirms app/workers/snapshot_eod.py actually wires
services/snapshot_service.py to a real database session and commits --
i.e. that the worker file is not a dead/unused entrypoint."""

from sqlalchemy import select

from app.models import PortfolioSnapshot
from app.tests.conftest import make_portfolio_config
from app.workers import snapshot_eod


class _NoCloseSession:
    """db_session is a fixture-managed session -- prevent the worker's
    `async with` from closing it out from under the test fixture's own
    teardown (see test_price_refresh_worker.py's identical pattern)."""

    def __init__(self, session):
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, *exc_info):
        return False


async def test_run_snapshot_eod_creates_a_real_snapshot(db_session, monkeypatch):
    config = make_portfolio_config()
    db_session.add(config)
    await db_session.commit()

    monkeypatch.setattr(snapshot_eod, "async_session_factory", lambda: _NoCloseSession(db_session))

    await snapshot_eod.run_snapshot_eod()

    snapshots = (
        await db_session.execute(
            select(PortfolioSnapshot).where(
                PortfolioSnapshot.portfolio_config_id == config.id, PortfolioSnapshot.trigger_source == "EOD"
            )
        )
    ).scalars().all()
    assert len(snapshots) == 1


async def test_run_snapshot_eod_is_a_no_op_on_second_call_same_day(db_session, monkeypatch):
    config = make_portfolio_config()
    db_session.add(config)
    await db_session.commit()

    monkeypatch.setattr(snapshot_eod, "async_session_factory", lambda: _NoCloseSession(db_session))

    await snapshot_eod.run_snapshot_eod()
    await snapshot_eod.run_snapshot_eod()

    snapshots = (
        await db_session.execute(
            select(PortfolioSnapshot).where(
                PortfolioSnapshot.portfolio_config_id == config.id, PortfolioSnapshot.trigger_source == "EOD"
            )
        )
    ).scalars().all()
    assert len(snapshots) == 1


async def test_run_snapshot_eod_raises_when_no_portfolio_configured(db_session, monkeypatch):
    monkeypatch.setattr(snapshot_eod, "async_session_factory", lambda: _NoCloseSession(db_session))

    try:
        await snapshot_eod.run_snapshot_eod()
        assert False, "expected PortfolioNotConfiguredError"
    except snapshot_eod.PortfolioNotConfiguredError:
        pass
