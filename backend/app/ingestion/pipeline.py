"""Ingestion pipeline — orchestrates a full poll-and-store cycle."""

import logging
import time
from datetime import datetime, timezone

from sqlalchemy import text

from app.config import settings
from app.ingestion.odds_api_client import OddsAPIClient
from app.ingestion.normalizer import (
    NormalizationError,
    normalize_event,
    normalize_odds,
    extract_bookmakers,
)
from app.entity_resolution.resolver import EntityResolver
from app.utils.database import async_session
from app.utils.redis_cache import odds_cache

logger = logging.getLogger(__name__)


class IngestPipeline:
    """Full ingestion cycle: fetch → normalize → resolve → store → cache."""

    def __init__(self, client: OddsAPIClient, resolver: EntityResolver):
        self.client = client
        self.resolver = resolver

    async def run_cycle(self) -> datetime | None:
        """Run one full poll cycle across all supported sports.

        Returns the earliest upcoming commence_time (for scheduler tier calc),
        or None if no upcoming events.
        """
        earliest_commence: datetime | None = None

        for sport in settings.supported_sports:
            next_t = await self._poll_sport(sport)
            if next_t is not None:
                if earliest_commence is None or next_t < earliest_commence:
                    earliest_commence = next_t

        return earliest_commence

    async def _poll_sport(self, sport: str) -> datetime | None:
        """Poll one sport, store results, return next commence time."""
        start = time.monotonic()
        errors = []
        events_count = 0
        snapshots_count = 0
        next_commence: datetime | None = None

        try:
            raw_events = await self.client.get_events(sport)
            events_count = len(raw_events)

            async with async_session() as session:
                for raw in raw_events:
                    # Track earliest upcoming event
                    raw_time = raw.get("commence_time")
                    if raw_time:
                        try:
                            commence = datetime.fromisoformat(
                                raw_time.replace("Z", "+00:00")
                            )
                            if commence > datetime.now(timezone.utc):
                                if next_commence is None or commence < next_commence:
                                    next_commence = commence
                        except (ValueError, AttributeError):
                            logger.warning("Unparseable commence_time: %s", raw_time)

                    # Normalize event
                    try:
                        event = normalize_event(raw)
                    except NormalizationError as e:
                        logger.warning("Skipping malformed event: %s", e)
                        continue
                    event["home_team"] = self.resolver.resolve(
                        event["home_team"], sport, "team"
                    )
                    event["away_team"] = self.resolver.resolve(
                        event["away_team"], sport, "team"
                    )

                    # Upsert event
                    await session.execute(
                        text("""
                            INSERT INTO events (id, sport, league, home_team, away_team,
                                                commence_time, status, external_ids)
                            VALUES (:id, :sport, :league, :home_team, :away_team,
                                    :commence_time, :status, :external_ids)
                            ON CONFLICT (id) DO UPDATE SET
                                commence_time = EXCLUDED.commence_time,
                                updated_at = now()
                        """),
                        event,
                    )

                    # Upsert bookmakers
                    for bk in extract_bookmakers(raw):
                        await session.execute(
                            text("""
                                INSERT INTO bookmakers (key, name, region, is_sharp)
                                VALUES (:key, :name, :region, :is_sharp)
                                ON CONFLICT (key) DO NOTHING
                            """),
                            bk,
                        )

                    # Normalize and store odds
                    snapshots = normalize_odds(raw)
                    for snap in snapshots:
                        snap["outcome_name"] = self.resolver.resolve(
                            snap["outcome_name"], sport, "team"
                        )

                        # Insert snapshot (historical)
                        await session.execute(
                            text("""
                                INSERT INTO odds_snapshots
                                    (event_id, bookmaker_key, market,
                                     outcome_name, price, point)
                                VALUES
                                    (:event_id, :bookmaker_key, :market,
                                     :outcome_name, :price, :point)
                            """),
                            snap,
                        )

                        # Upsert latest odds
                        await session.execute(
                            text("""
                                INSERT INTO odds_latest
                                    (event_id, bookmaker_key, market,
                                     outcome_name, price, point)
                                VALUES
                                    (:event_id, :bookmaker_key, :market,
                                     :outcome_name, :price, :point)
                                ON CONFLICT
                                    (event_id, bookmaker_key, market, outcome_name)
                                DO UPDATE SET
                                    price = EXCLUDED.price,
                                    point = EXCLUDED.point,
                                    updated_at = now()
                            """),
                            snap,
                        )

                        # Update Redis cache
                        await odds_cache.set_odds(
                            snap["event_id"],
                            snap["bookmaker_key"],
                            snap["market"],
                            snap["outcome_name"],
                            snap["price"],
                            snap.get("point"),
                        )

                        snapshots_count += 1

                await session.commit()

            # Cache next commence for this sport
            if next_commence:
                await odds_cache.set_next_commence(
                    sport, next_commence.isoformat()
                )

        except Exception as e:
            errors.append(str(e)[:256])
            logger.exception("Error polling %s", sport)

        # Write health record
        latency_ms = int((time.monotonic() - start) * 1000)
        await self._write_health(
            sport, events_count, snapshots_count, errors, latency_ms
        )

        return next_commence

    async def _write_health(
        self,
        sport: str,
        events_found: int,
        snapshots_written: int,
        errors: list[str],
        latency_ms: int,
    ):
        """Log a health heartbeat for this poll cycle."""
        try:
            async with async_session() as session:
                await session.execute(
                    text("""
                        INSERT INTO ingestion_health
                            (sport, events_found, snapshots_written, errors, latency_ms)
                        VALUES
                            (:sport, :events_found, :snapshots_written, :errors, :latency_ms)
                    """),
                    {
                        "sport": sport,
                        "events_found": events_found,
                        "snapshots_written": snapshots_written,
                        "errors": "; ".join(errors) if errors else None,
                        "latency_ms": latency_ms,
                    },
                )
                await session.commit()
        except Exception:
            logger.exception("Failed to write health record")
