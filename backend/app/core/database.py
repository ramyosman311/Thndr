from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import get_settings


class Base(DeclarativeBase):
    """Shared declarative base for all ORM models (added starting Phase 3)."""


def create_engine() -> AsyncEngine:
    settings = get_settings()
    return create_async_engine(
        settings.database_url,
        echo=settings.app_debug and not settings.is_production,
        pool_pre_ping=True,
        # Recycle connections before a managed Postgres provider's own
        # idle-connection timeout (e.g. a pooler in front of Supabase)
        # can silently drop them out from under a long-lived process.
        pool_recycle=1800,
    )


engine: AsyncEngine = create_engine()

async_session_factory = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency yielding a request-scoped async session."""
    async with async_session_factory() as session:
        yield session


async def check_database_connection() -> bool:
    """Attempt a lightweight round-trip to the database. Returns False on any failure."""
    from sqlalchemy import text

    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
