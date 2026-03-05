"""Database connection management — lazy initialization."""

import logging
from functools import lru_cache

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from app.config import settings

logger = logging.getLogger(__name__)


def _build_async_url(url: str) -> str:
    """Convert a standard postgresql:// URL to asyncpg."""
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+asyncpg://", 1)
    return url


@lru_cache(maxsize=1)
def get_engine():
    return create_async_engine(
        _build_async_url(settings.database_url),
        echo=settings.env == "development",
        pool_size=5,
        max_overflow=10,
    )


def get_async_session_factory():
    return async_sessionmaker(get_engine(), class_=AsyncSession, expire_on_commit=False)


def async_session():
    """Return a new async session context manager."""
    return get_async_session_factory()()


async def get_session() -> AsyncSession:
    """Dependency for FastAPI route injection."""
    async with get_async_session_factory()() as session:
        yield session
