"""Bet Buddy — FastAPI entrypoint."""

import asyncio
import logging
from contextlib import asynccontextmanager
from enum import Enum

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import text

from app.config import settings
from app.ingestion.odds_api_client import OddsAPIClient
from app.ingestion.pipeline import IngestPipeline
from app.ingestion.scheduler import AdaptiveScheduler
from app.entity_resolution.resolver import EntityResolver
from app.utils.database import async_session
from app.utils.health import check_database, check_redis, get_ingestion_status
from app.utils.redis_cache import odds_cache
from app.utils.validation import validate_event_id, validate_bookmaker_key

logging.basicConfig(
    level=getattr(logging, settings.log_level),
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger(__name__)

# --- Globals initialized at startup ---
scheduler: AdaptiveScheduler | None = None
scheduler_task: asyncio.Task | None = None


# ──────────────── Pydantic Response Models ────────────────

class SportFilter(str, Enum):
    MLB = "baseball_mlb"
    MMA = "mma_mixed_martial_arts"


class StatusFilter(str, Enum):
    UPCOMING = "upcoming"
    LIVE = "live"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class EventResponse(BaseModel):
    id: str
    sport: str
    league: str
    home_team: str
    away_team: str
    commence_time: str | None
    status: str


class OddsResponse(BaseModel):
    bookmaker: str
    bookmaker_name: str
    is_sharp: bool
    market: str
    outcome: str
    price: float
    point: float | None
    updated_at: str | None


class OddsHistoryResponse(BaseModel):
    bookmaker: str
    market: str
    outcome: str
    price: float
    point: float | None
    captured_at: str | None


class HealthResponse(BaseModel):
    status: str
    database: dict
    redis: dict
    scheduler_tier: str


class QuotaResponse(BaseModel):
    requests_remaining: int | None
    warning: bool = False
    message: str | None = None


# ──────────────── Lifespan ────────────────


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

# CORS — restrict to known origins (add your frontend domain in production)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allowed_origins,
    allow_credentials=True,
    allow_methods=["GET"],
    allow_headers=["*"],
)


# ──────────────── Health & Status ────────────────


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """System health check — database, Redis, and scheduler status."""
    db = await check_database()
    redis_status = await check_redis()
    tier = scheduler.current_tier if scheduler else "disabled"

    all_healthy = db["status"] == "healthy" and redis_status["status"] == "healthy"

    return HealthResponse(
        status="healthy" if all_healthy else "degraded",
        database=db,
        redis=redis_status,
        scheduler_tier=tier,
    )


@app.get("/health/ingestion")
async def ingestion_health() -> dict:
    """Recent ingestion poll history with latency and error tracking."""
    return await get_ingestion_status()


# ──────────────── Events ────────────────


@app.get("/events", response_model=list[EventResponse])
async def list_events(
    sport: SportFilter | None = Query(None, description="Filter by sport key"),
    status: StatusFilter = Query(StatusFilter.UPCOMING, description="Event status filter"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> list[EventResponse]:
    """List events with optional sport/status filters and pagination."""
    async with async_session() as session:
        query = """
            SELECT id, sport, league, home_team, away_team, commence_time, status
            FROM events WHERE status = :status
        """
        params: dict = {"status": status.value, "limit": limit, "offset": offset}

        if sport:
            query += " AND sport = :sport"
            params["sport"] = sport.value

        query += " ORDER BY commence_time ASC LIMIT :limit OFFSET :offset"

        result = await session.execute(text(query), params)
        rows = result.fetchall()

    return [
        EventResponse(
            id=r.id,
            sport=r.sport,
            league=r.league,
            home_team=r.home_team,
            away_team=r.away_team,
            commence_time=r.commence_time.isoformat() if r.commence_time else None,
            status=r.status,
        )
        for r in rows
    ]


# ──────────────── Odds ────────────────


@app.get("/odds/{event_id}", response_model=list[OddsResponse])
async def get_odds(event_id: str) -> list[OddsResponse]:
    """Get latest odds across all bookmakers for an event."""
    validate_event_id(event_id)

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
                LIMIT 500
            """),
            {"event_id": event_id},
        )
        rows = result.fetchall()

    return [
        OddsResponse(
            bookmaker=r.bookmaker_key,
            bookmaker_name=r.bookmaker_name,
            is_sharp=r.is_sharp,
            market=r.market,
            outcome=r.outcome_name,
            price=r.price,
            point=r.point,
            updated_at=r.updated_at.isoformat() if r.updated_at else None,
        )
        for r in rows
    ]


@app.get("/odds/{event_id}/history", response_model=list[OddsHistoryResponse])
async def get_odds_history(
    event_id: str,
    bookmaker: str | None = Query(None),
    limit: int = Query(100, ge=1, le=1000),
) -> list[OddsHistoryResponse]:
    """Get historical odds snapshots for line movement analysis."""
    validate_event_id(event_id)
    if bookmaker:
        validate_bookmaker_key(bookmaker)

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
        OddsHistoryResponse(
            bookmaker=r.bookmaker_key,
            market=r.market,
            outcome=r.outcome_name,
            price=r.price,
            point=r.point,
            captured_at=r.captured_at.isoformat() if r.captured_at else None,
        )
        for r in rows
    ]


# ──────────────── API Quota ────────────────


@app.get("/quota", response_model=QuotaResponse)
async def api_quota() -> QuotaResponse:
    """Check remaining Odds API request quota."""
    if scheduler and scheduler.pipeline:
        remaining = scheduler.pipeline.client.requests_remaining
        return QuotaResponse(
            requests_remaining=remaining,
            warning=remaining is not None and remaining < 50,
        )
    return QuotaResponse(
        requests_remaining=None,
        message="Scheduler not active",
    )


# ──────────────── Signals (Phase 2 — The Brain) ────────────────


class SignalResponse(BaseModel):
    event_id: str
    sport: str
    home_team: str
    away_team: str
    bookmaker: str
    outcome: str
    decimal_odds: float
    model_prob: float
    sharp_prob: float
    edge_pct: float
    kelly_fraction_pct: float
    recommended_stake: float
    confidence: float


class CalibrationResponse(BaseModel):
    n_predictions: int
    n_resolved: int
    brier_ensemble: float | None
    brier_sharp: float | None
    brier_model: float | None
    edge_over_sharp: float | None
    calibration_bins: list[dict]


@app.get("/signals", response_model=list[SignalResponse])
async def get_signals(
    sport: SportFilter | None = Query(None, description="Filter by sport"),
    min_edge: float = Query(0.02, ge=0.0, le=0.5, description="Minimum edge (0.02 = 2%)"),
    limit: int = Query(20, ge=1, le=100),
) -> list[SignalResponse]:
    """Get current +EV signals — the Daily Golden Plays.

    Returns edges found where soft bookmaker odds deviate from our
    ensemble model probability, sized by Half Kelly.
    """
    from app.engine.edge import EventOdds, implied_probability, remove_vig, find_edges
    from app.engine.ensemble import score_event
    from app.engine.kelly import recommend_bet

    # Fetch upcoming events with odds
    async with async_session() as session:
        query = """
            SELECT DISTINCT e.id, e.sport, e.home_team, e.away_team
            FROM events e
            JOIN odds_latest ol ON ol.event_id = e.id
            WHERE e.status = 'upcoming'
        """
        params: dict = {"limit": limit * 5}
        if sport:
            query += " AND e.sport = :sport"
            params["sport"] = sport.value
        query += " LIMIT :limit"

        result = await session.execute(text(query), params)
        events = result.fetchall()

    all_signals: list[SignalResponse] = []

    for ev in events:
        # Fetch odds for this event
        async with async_session() as session:
            result = await session.execute(
                text("""
                    SELECT ol.bookmaker_key, ol.outcome_name, ol.price
                    FROM odds_latest ol
                    WHERE ol.event_id = :event_id AND ol.market = 'h2h'
                """),
                {"event_id": ev.id},
            )
            odds_rows = result.fetchall()

        if not odds_rows:
            continue

        # Build EventOdds structure
        odds_dict: dict[str, dict[str, float]] = {}
        for row in odds_rows:
            odds_dict.setdefault(row.bookmaker_key, {})[row.outcome_name] = row.price

        event_odds = EventOdds(
            event_id=ev.id,
            sport=ev.sport,
            home_team=ev.home_team,
            away_team=ev.away_team,
            odds=odds_dict,
        )

        # Sharp-line model: use Pinnacle as "truth"
        sharp_raw = {}
        if "pinnacle" in odds_dict:
            for outcome, price in odds_dict["pinnacle"].items():
                sharp_raw[outcome] = implied_probability(price)
        sharp_probs = remove_vig(sharp_raw) if sharp_raw else {}

        if not sharp_probs:
            continue

        # For now, use sharp probs as model probs (Phase 2 MC models
        # will feed in here once we have stat feeds)
        ensemble = score_event(ev.id, sharp_probs, sharp_probs)

        edges = find_edges(event_odds, ensemble.outcome_probs, min_edge=min_edge)

        for signal in edges:
            rec = recommend_bet(
                event_id=signal.event_id,
                outcome=signal.outcome,
                bookmaker=signal.bookmaker,
                model_prob=signal.model_prob,
                decimal_odds=signal.decimal_odds,
                bankroll=1000.0,  # Default; configurable via settings later
                kelly_multiplier=0.5,
            )
            all_signals.append(
                SignalResponse(
                    event_id=signal.event_id,
                    sport=ev.sport,
                    home_team=ev.home_team,
                    away_team=ev.away_team,
                    bookmaker=signal.bookmaker,
                    outcome=signal.outcome,
                    decimal_odds=signal.decimal_odds,
                    model_prob=round(signal.model_prob, 4),
                    sharp_prob=round(signal.sharp_prob, 4),
                    edge_pct=round(signal.edge * 100, 2),
                    kelly_fraction_pct=round(
                        rec.adjusted_kelly_fraction * 100 if rec else 0, 2
                    ),
                    recommended_stake=rec.recommended_stake if rec else 0,
                    confidence=signal.confidence,
                )
            )

    # Sort by edge, return top N
    all_signals.sort(key=lambda s: s.edge_pct, reverse=True)
    return all_signals[:limit]


@app.get("/calibration", response_model=CalibrationResponse)
async def get_calibration() -> CalibrationResponse:
    """Get model calibration metrics (Brier scores).

    Shows how well our model's probability estimates match actual outcomes.
    Lower Brier score = better calibration.
    """
    # In production, this would read from the persistent calibration tracker.
    # For now, return empty state until predictions accumulate.
    return CalibrationResponse(
        n_predictions=0,
        n_resolved=0,
        brier_ensemble=None,
        brier_sharp=None,
        brier_model=None,
        edge_over_sharp=None,
        calibration_bins=[],
    )
