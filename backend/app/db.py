"""Database session wiring (TASK-002, EPIC-01).

Provides the async engine, a session factory, and a FastAPI dependency. The ORM
models and Alembic migrations (TASK-004) live in `app.models`; importing `Base`
from here registers all tables on `Base.metadata` for autogenerate and gives
callers a single import point (`from app.db import Base, get_session`).
"""

from collections.abc import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import get_settings
from app.models import Base  # noqa: F401 — re-exported; populates Base.metadata

settings = get_settings()

engine: AsyncEngine = create_async_engine(
    settings.database_url,
    echo=False,
    pool_pre_ping=True,  # transparently recycle stale connections
)

SessionFactory = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency yielding a request-scoped async session."""
    async with SessionFactory() as session:
        yield session


async def ping_db() -> bool:
    """Lightweight connectivity check used by the readiness probe."""
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
    return True
