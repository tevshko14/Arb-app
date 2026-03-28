"""Health and observability utilities."""

import logging
import time

from sqlalchemy import text

from app.utils.database import async_session
from app.utils.redis_cache import odds_cache

logger = logging.getLogger(__name__)


async def check_database() -> dict:
    """Check database connectivity and measure latency."""
    try:
        start = time.monotonic()
        async with async_session() as session:
            result = await session.execute(text("SELECT 1"))
            result.scalar()
        latency_ms = int((time.monotonic() - start) * 1000)
        return {"status": "healthy", "latency_ms": latency_ms}
    except Exception as e:
        logger.error("Database health check failed: %s", e)
        return {"status": "unhealthy", "error": str(e)[:200]}


async def check_redis() -> dict:
    """Check Redis connectivity and measure latency."""
    try:
        start = time.monotonic()
        healthy = await odds_cache.health_check()
        latency_ms = int((time.monotonic() - start) * 1000)
        return {
            "status": "healthy" if healthy else "unhealthy",
            "latency_ms": latency_ms,
        }
    except Exception as e:
        logger.error("Redis health check failed: %s", e)
        return {"status": "unhealthy", "error": str(e)[:200]}


async def get_ingestion_status() -> dict:
    """Get the latest ingestion health records with freshness check."""
    try:
        async with async_session() as session:
            result = await session.execute(
                text("""
                    SELECT sport, events_found, snapshots_written,
                           errors, latency_ms, polled_at,
                           EXTRACT(EPOCH FROM (now() - polled_at)) AS age_seconds
                    FROM bb_ingestion_health
                    ORDER BY polled_at DESC
                    LIMIT 10
                """)
            )
            rows = result.fetchall()

        polls = []
        stale = False
        for r in rows:
            age = r.age_seconds if hasattr(r, "age_seconds") else None
            if age is not None and age > 600:  # >10 min since last poll
                stale = True
            polls.append({
                "sport": r.sport,
                "events_found": r.events_found,
                "snapshots_written": r.snapshots_written,
                "errors": r.errors,
                "latency_ms": r.latency_ms,
                "polled_at": r.polled_at.isoformat() if r.polled_at else None,
                "age_seconds": int(age) if age is not None else None,
            })

        return {
            "fresh": not stale,
            "recent_polls": polls,
        }
    except Exception as e:
        return {"error": str(e)[:200]}
