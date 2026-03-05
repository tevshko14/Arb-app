"""Bet Buddy — FastAPI entrypoint."""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Query
from sqlalchemy import text

from app.config import settings
from app.ingestion.odds_api_client import OddsAPIClient
from app.ingestion.pipeline import IngestPipeline
from app.ingestion.scheduler import AdaptiveScheduler
from app.entity_resolution.resolver import EntityResolver
from app.utils.database import async_session
from app.utils.health import check_database, check_redis, get_ingestion_status
from app.utils.redis_cache import odds_cache

logging.basicConfig(
    level=getattr(logging, settings.log_level),
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger(__name__)

# --- Globals initialized at startup ---
scheduler: AdaptiveScheduler | None = None
scheduler_task: asyncio.Task | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown lifecycle."""
    global scheduler, scheduler_task

    # Connect Redis
    await odds_cache.connect()
    logger.info("Redis connected")

    # Initialize pipeline
    client = OddsAPIClient()
    resolver = EntityResolver()
    pipeline = IngestPipeline(client, resolver)
    scheduler = AdaptiveScheduler(pipeline)

    # Start polling in background
    if settings.odds_api_key:
        scheduler_task = asyncio.create_task(scheduler.start())
        logger.info("Ingestion scheduler started")
    else:
        logger.warning("ODDS_API_KEY not set — ingestion disabled")

    yield

    # Shutdown
    if scheduler:
        scheduler.stop()
    if scheduler_task:
        scheduler_task.cancel()
        try:
            await scheduler_task
        except asyncio.CancelledError:
            pass
    await client.close()
    await odds_cache.close()
    logger.info("Shutdown complete")


app = FastAPI(
    title="Bet Buddy",
    description="InfoFi platform — Positive EV signal engine for Canadian sports betting",
    version="0.1.0",
    lifespan=lifespan,
)


# ──────────────── Health & Status ────────────────


@app.get("/health")
async def health():
    """System health check."""
    db = await check_database()
    redis = await check_redis()
    tier = scheduler.current_tier if scheduler else "disabled"

    all_healthy = db["status"] == "healthy" and redis["status"] == "healthy"

    return {
        "status": "healthy" if all_healthy else "degraded",
        "database": db,
        "redis": redis,
        "scheduler_tier": tier,
    }


@app.get("/health/ingestion")
async def ingestion_health():
    """Recent ingestion poll history."""
    return await get_ingestion_status()


# ──────────────── Events ────────────────


@app.get("/events")
async def list_events(
    sport: str | None = Query(None, description="Filter by sport key"),
    status: str = Query("upcoming", description="Event status filter"),
    limit: int = Query(50, le=200),
):
    """List events with optional filters."""
    async with async_session() as session:
        query = "SELECT * FROM events WHERE status = :status"
        params: dict = {"status": status}

        if sport:
            query += " AND sport = :sport"
            params["sport"] = sport

        query += " ORDER BY commence_time ASC LIMIT :limit"
        params["limit"] = limit

        result = await session.execute(text(query), params)
        rows = result.fetchall()

    return [
        {
            "id": r.id,
            "sport": r.sport,
            "league": r.league,
            "home_team": r.home_team,
            "away_team": r.away_team,
            "commence_time": r.commence_time.isoformat() if r.commence_time else None,
            "status": r.status,
        }
        for r in rows
    ]


# ──────────────── Odds ────────────────


@app.get("/odds/{event_id}")
async def get_odds(event_id: str):
    """Get latest odds across all bookmakers for an event."""
    async with async_session() as session:
        result = await session.execute(
            text("""
                SELECT ol.bookmaker_key, ol.market, ol.outcome_name,
                       ol.price, ol.point, ol.updated_at,
                       b.name as bookmaker_name, b.is_sharp
                FROM odds_latest ol
                JOIN bookmakers b ON b.key = ol.bookmaker_key
                WHERE ol.event_id = :event_id
                ORDER BY ol.market, ol.outcome_name, ol.price DESC
            """),
            {"event_id": event_id},
        )
        rows = result.fetchall()

    return [
        {
            "bookmaker": r.bookmaker_key,
            "bookmaker_name": r.bookmaker_name,
            "is_sharp": r.is_sharp,
            "market": r.market,
            "outcome": r.outcome_name,
            "price": r.price,
            "point": r.point,
            "updated_at": r.updated_at.isoformat() if r.updated_at else None,
        }
        for r in rows
    ]


@app.get("/odds/{event_id}/history")
async def get_odds_history(
    event_id: str,
    bookmaker: str | None = Query(None),
    limit: int = Query(100, le=1000),
):
    """Get historical odds snapshots for line movement analysis."""
    async with async_session() as session:
        query = """
            SELECT bookmaker_key, market, outcome_name, price, point, captured_at
            FROM odds_snapshots
            WHERE event_id = :event_id
        """
        params: dict = {"event_id": event_id, "limit": limit}

        if bookmaker:
            query += " AND bookmaker_key = :bookmaker"
            params["bookmaker"] = bookmaker

        query += " ORDER BY captured_at DESC LIMIT :limit"

        result = await session.execute(text(query), params)
        rows = result.fetchall()

    return [
        {
            "bookmaker": r.bookmaker_key,
            "market": r.market,
            "outcome": r.outcome_name,
            "price": r.price,
            "point": r.point,
            "captured_at": r.captured_at.isoformat() if r.captured_at else None,
        }
        for r in rows
    ]


# ──────────────── API Quota ────────────────


@app.get("/quota")
async def api_quota():
    """Check remaining Odds API quota."""
    # Access the client through the pipeline
    if scheduler and scheduler.pipeline:
        remaining = scheduler.pipeline.client.requests_remaining
        return {
            "requests_remaining": remaining,
            "warning": remaining is not None and remaining < 50,
        }
    return {"requests_remaining": None, "message": "Scheduler not active"}
