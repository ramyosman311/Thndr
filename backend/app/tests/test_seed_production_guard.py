"""Phase 23: app/seed/__main__.py must refuse to run against a production
environment by default -- not because the seed itself is destructive (it
isn't, see seed.py's idempotency guarantees), but because it would inject
fake demo assets/config into what could be a real user's real portfolio.
"""

from app.core.config import Settings
from app.seed import __main__ as seed_main


async def test_seed_refuses_to_run_in_production_by_default(monkeypatch, capsys):
    monkeypatch.setattr(seed_main, "get_settings", lambda: Settings(APP_ENV="production"))
    monkeypatch.delenv("ALLOW_SEED_IN_PRODUCTION", raising=False)

    exited = False
    try:
        await seed_main.main()
    except SystemExit as exc:
        exited = True
        assert exc.code == 1

    assert exited, "seed main() must sys.exit(1) rather than proceed in production"
    assert "production" in capsys.readouterr().err.lower()


async def test_seed_runs_in_production_when_explicitly_allowed(monkeypatch):
    monkeypatch.setattr(seed_main, "get_settings", lambda: Settings(APP_ENV="production"))
    monkeypatch.setenv("ALLOW_SEED_IN_PRODUCTION", "1")

    called = False

    async def fake_run_seed(session) -> None:
        nonlocal called
        called = True

    monkeypatch.setattr(seed_main, "run_seed", fake_run_seed)

    await seed_main.main()

    assert called is True


async def test_seed_runs_normally_outside_production(monkeypatch):
    monkeypatch.setattr(seed_main, "get_settings", lambda: Settings(APP_ENV="development"))
    monkeypatch.delenv("ALLOW_SEED_IN_PRODUCTION", raising=False)

    called = False

    async def fake_run_seed(session) -> None:
        nonlocal called
        called = True

    monkeypatch.setattr(seed_main, "run_seed", fake_run_seed)

    await seed_main.main()

    assert called is True
