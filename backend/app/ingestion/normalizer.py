"""Normalize raw Odds-API responses into canonical data structures."""

import json
import logging

from app.config import settings

logger = logging.getLogger(__name__)


class NormalizationError(Exception):
    """Raised when a raw event is missing required fields."""


def normalize_event(raw: dict) -> dict:
    """Convert a raw Odds-API event into our canonical event format.

    Returns a dict ready for upserting into the `events` table.
    Raises NormalizationError if required fields are missing.
    """
    event_id = raw.get("id")
    sport_key = raw.get("sport_key")
    home_team = raw.get("home_team")
    away_team = raw.get("away_team")
    commence_time = raw.get("commence_time")

    if not all([event_id, sport_key, home_team, away_team, commence_time]):
        missing = [
            k for k, v in {
                "id": event_id, "sport_key": sport_key, "home_team": home_team,
                "away_team": away_team, "commence_time": commence_time,
            }.items() if not v
        ]
        raise NormalizationError(f"Missing required fields: {missing}")

    return {
        "id": event_id,
        "sport": sport_key,
        "league": raw.get("sport_title", sport_key),
        "home_team": home_team,
        "away_team": away_team,
        "commence_time": commence_time,
        "status": "upcoming",
        "external_ids": json.dumps({"odds_api": event_id}),
    }


def normalize_odds(raw_event: dict) -> list[dict]:
    """Extract all odds snapshots from a raw Odds-API event.

    Returns a list of dicts ready for inserting into `odds_snapshots`.
    Each bookmaker x market x outcome produces one row.
    Skips malformed entries with a warning rather than failing the batch.
    """
    event_id = raw_event.get("id")
    if not event_id:
        logger.warning("Skipping event with no ID")
        return []

    snapshots = []

    for bookmaker in raw_event.get("bookmakers", []):
        bk_key = bookmaker.get("key")
        if not bk_key or bk_key not in settings.target_bookmakers:
            continue

        for market in bookmaker.get("markets", []):
            market_key = market.get("key")
            if not market_key:
                continue

            for outcome in market.get("outcomes", []):
                name = outcome.get("name")
                price = outcome.get("price")
                if not name or price is None:
                    logger.warning(
                        "Skipping malformed outcome in event %s: %s", event_id, outcome
                    )
                    continue

                snapshots.append(
                    {
                        "event_id": event_id,
                        "bookmaker_key": bk_key,
                        "market": market_key,
                        "outcome_name": name,
                        "price": price,
                        "point": outcome.get("point"),
                    }
                )

    return snapshots


def extract_bookmakers(raw_event: dict) -> list[dict]:
    """Extract unique bookmaker records from a raw event for upsert.

    Returns dicts for the `bookmakers` table.
    """
    seen = {}
    for bookmaker in raw_event.get("bookmakers", []):
        bk_key = bookmaker.get("key")
        bk_title = bookmaker.get("title", bk_key)
        if bk_key and bk_key not in seen and bk_key in settings.target_bookmakers:
            seen[bk_key] = {
                "key": bk_key,
                "name": bk_title,
                "region": "ca",
                "is_sharp": bk_key == "pinnacle",
            }
    return list(seen.values())
