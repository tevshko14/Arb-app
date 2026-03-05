"""Health and observability utilities."""

import logging
from datetime import datetime, timezone

from sqlalchemy import text

from app.utils.database import async_session
from app.utils.redis_cache import odds_cache

logger = logging.getLogger(__name__)


async def check_database() -> dict:
    """Check database connectivity and return status."""
    try:
        async with async_session() as session:
            result = await session.execute(text("SELECT 1"))
            result.scalar()
        return {"status": "healthy", "latency_ms": None}
    except Exception as e:
        logger.error("Database health check failed: %s", e)
        return {"status": "unhealthy", "error": str(e)[:200]}


async def check_redis() -> dict:
    """Check Redis connectivity."""
    try:
        healthy = await odds_cache.health_check()
        return {"status": "healthy" if healthy else "unhealthy"}
    except Exception as e:
        logger.error("Redis health check failed: %s", e)
        return {"status": "unhealthy", "error": str(e)[:200]}


async def get_ingestion_status() -> dict:
    """Get the latest ingestion health records."""
    try:
        async with async_session() as session:
            result = await session.execute(
                text("""
                    SELECT sport, events_found, snapshots_written,
                           errors, latency_ms, polled_at
                    FROM ingestion_health
                    ORDER BY polled_at DESC
                    LIMIT 10
                """)
            )
            rows = result.fetchall()

        return {
            "recent_polls": [
                {
                    "sport": r.sport,
                    "events_found": r.events_found,
                    "snapshots_written": r.snapshots_written,
                    "errors": r.errors,
                    "latency_ms": r.latency_ms,
                    "polled_at": r.polled_at.isoformat() if r.polled_at else None,
                }
                for r in rows
            ]
        }
    except Exception as e:
        return {"error": str(e)[:200]}
