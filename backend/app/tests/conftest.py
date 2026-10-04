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

import uuid  # noqa: E402
from datetime import timedelta  # noqa: E402

import jwt  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import rsa  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

from app.core import auth as auth_module  # noqa: E402
from app.core.config import Settings, get_settings  # noqa: E402
from app.core.database import get_db_session  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Asset, AssetType, PortfolioConfig, User  # noqa: E402


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


# --- P0-3C ownership/auth test support ------------------------------------
#
# Tests exercise the REAL verification chain: tokens are signed RS256 with a
# locally generated key and verified by `require_supabase_user` against a
# faked JWKS client (this sandbox cannot reach a live Supabase project -- see
# test_supabase_auth.py), so "who the caller is" always comes from a verified
# JWT, never from a test-only auth override.

TEST_SUPABASE_URL = "https://test-project.supabase.co"
TEST_INTERNAL_TOKEN = "test-internal-proxy-token"
_TEST_PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_TEST_PUBLIC_KEY = _TEST_PRIVATE_KEY.public_key()


class _FakeSigningKey:
    def __init__(self, key):
        self.key = key


class _FakeJWKClient:
    def get_signing_key_from_jwt(self, token: str) -> _FakeSigningKey:
        return _FakeSigningKey(_TEST_PUBLIC_KEY)


def make_jwt(user_id: uuid.UUID, *, expires_in: timedelta = timedelta(hours=1), private_key=None) -> str:
    return jwt.encode(
        {
            "sub": str(user_id),
            "iss": f"{TEST_SUPABASE_URL}/auth/v1",
            "aud": "authenticated",
            "exp": datetime.now(timezone.utc) + expires_in,
        },
        private_key or _TEST_PRIVATE_KEY,
        algorithm="RS256",
    )


def auth_headers(user_id: uuid.UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {make_jwt(user_id)}"}


@pytest.fixture
def supabase_auth(monkeypatch):
    """Points the auth module at the fake Supabase project + JWKS."""
    monkeypatch.setattr(
        auth_module,
        "get_settings",
        lambda: Settings(
            SUPABASE_URL=TEST_SUPABASE_URL, SUPABASE_JWT_AUDIENCE="authenticated", API_AUTH_TOKEN=TEST_INTERNAL_TOKEN
        ),
    )
    monkeypatch.setattr(auth_module, "_jwks_client", lambda jwks_url: _FakeJWKClient())


async def make_user(session) -> User:
    """A persisted local user (the row `get_current_user` would create for
    a verified Supabase uuid). Flushes; does not commit."""
    user = User(id=uuid.uuid4())
    session.add(user)
    await session.flush()
    return user


async def owned_config(session, user: User) -> PortfolioConfig:
    """The user's own portfolio, as the application itself would resolve it."""
    from app.repositories.portfolio_repository import get_portfolio_config_for_user

    config = await get_portfolio_config_for_user(session, user.id)
    assert config is not None
    return config


@pytest_asyncio.fixture
async def user_a(db_session) -> User:
    return await make_user(db_session)


@pytest_asyncio.fixture
async def user_b(db_session) -> User:
    return await make_user(db_session)


@pytest_asyncio.fixture
async def owner(user_a) -> User:
    """The default owner for tests that only need "a user" (single-tenant
    scenarios under the P0-3C ownership contract)."""
    return user_a


@pytest.fixture
def client_for(db_session, supabase_auth):
    """Factory: an httpx client for `app`, wired to the exact same test-
    database session/transaction as `db_session` (so ORM writes in a test
    are immediately visible to the HTTP call and everything rolls back
    together), authenticated as the given user via a real signed JWT."""
    created: list[AsyncClient] = []

    async def _override_get_db_session():
        yield db_session

    app.dependency_overrides[get_db_session] = _override_get_db_session

    def _make(user: User | None) -> AsyncClient:
        headers = auth_headers(user.id) if user is not None else {}
        ac = AsyncClient(transport=ASGITransport(app=app), base_url="http://test", headers=headers)
        created.append(ac)
        return ac

    yield _make
    app.dependency_overrides.pop(get_db_session, None)


@pytest_asyncio.fixture
async def portfolio(db_session, owner) -> PortfolioConfig:
    """A minimal portfolio owned by `owner`, for tests whose subject (e.g. the
    watchlist) merely needs the caller to HAVE a portfolio."""
    config = make_portfolio_config(user_id=owner.id)
    db_session.add(config)
    await db_session.flush()
    return config


@pytest_asyncio.fixture
async def client(client_for, owner):
    """The default authenticated client: the `owner` user."""
    async with client_for(owner) as ac:
        yield ac


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
