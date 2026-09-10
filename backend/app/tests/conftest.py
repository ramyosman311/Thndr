import os
import subprocess
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import psycopg2
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

from app.core.config import get_settings  # noqa: E402
from app.models import Asset, AssetType, PortfolioConfig  # noqa: E402


def make_asset(symbol: str, **kwargs) -> Asset:
    """Shared test factory for a minimal valid Asset row."""
    return Asset(
        symbol=symbol,
        name=kwargs.pop("name", symbol),
        asset_type=kwargs.pop("asset_type", AssetType.STOCK),
        currency=kwargs.pop("currency", "EGP"),
        **kwargs,
    )


async def make_current_price(session, asset, price: Decimal, *, currency: str | None = None) -> None:
    """Seeds a fresh, current (not stale) price observation for `asset`
    via the real Price Service write path (Phase 11) -- the equivalent
    of what used to be `Holding(current_price=...)` before valuation
    moved off that column (see FINANCIAL_RULES.md, "Single Source Of
    Truth For Current Price"). Flushes but does not commit."""
    from app.repositories import price_repository

    await price_repository.insert_price_observation(
        session,
        asset_id=asset.id,
        price=price,
        currency=currency or asset.currency,
        provider="yahoo",
        recorded_at=datetime.now(timezone.utc),
        is_manual=False,
    )


def make_portfolio_config(**kwargs) -> PortfolioConfig:
    """Shared test factory for a minimal valid PortfolioConfig row."""
    return PortfolioConfig(
        name=kwargs.pop("name", "Test Portfolio"),
        base_currency=kwargs.pop("base_currency", "EGP"),
        **kwargs,
    )


def _with_test_suffix(url: str) -> str:
    if url.rstrip("/").endswith("_test"):
        return url
    base, _, dbname = url.rpartition("/")
    if not dbname.endswith("_test"):
        dbname = f"{dbname}_test"
    return f"{base}/{dbname}"


@pytest.fixture(scope="session")
def test_database_url() -> str:
    return _with_test_suffix(get_settings().database_url)


@pytest.fixture(scope="session")
def test_database_url_sync() -> str:
    return _with_test_suffix(get_settings().database_url_sync)


@pytest.fixture(scope="session", autouse=True)
def migrated_test_database(test_database_url_sync: str):
    """Reset the real PostgreSQL test database to a clean schema, then apply
    the actual Alembic migration chain via the `alembic` CLI — exactly as an
    operator would run it against any real database.
    """
    plain_url = test_database_url_sync.replace("postgresql+psycopg2", "postgresql")
    conn = psycopg2.connect(plain_url)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute("DROP SCHEMA public CASCADE;")
            cur.execute("CREATE SCHEMA public;")
    finally:
        conn.close()

    env = os.environ.copy()
    env["DATABASE_URL_SYNC"] = test_database_url_sync
    env["DATABASE_URL"] = test_database_url_sync.replace("+psycopg2", "+asyncpg")

    result = subprocess.run(
        ["alembic", "upgrade", "head"],
        cwd=str(BACKEND_DIR),
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"alembic upgrade head failed against test database:\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    yield


@pytest_asyncio.fixture
async def db_session(test_database_url: str):
    """A per-test AsyncSession bound to a connection whose outer transaction
    is rolled back at teardown, so tests never leak data into each other.
    """
    engine = create_async_engine(test_database_url, poolclass=NullPool)
    async with engine.connect() as conn:
        trans = await conn.begin()
        session_factory = async_sessionmaker(
            bind=conn, expire_on_commit=False, join_transaction_mode="create_savepoint"
        )
        async with session_factory() as session:
            yield session
        await trans.rollback()
    await engine.dispose()
