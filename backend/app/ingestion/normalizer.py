"""Normalize raw Odds-API responses into canonical data structures."""

import json
import logging
from datetime import datetime

from app.config import settings

logger = logging.getLogger(__name__)


def normalize_event(raw: dict) -> dict:
    """Convert a raw Odds-API event into our canonical event format.

    Returns a dict ready for upserting into the `events` table.
    """
    return {
        "id": raw["id"],
        "sport": raw["sport_key"],
        "league": raw.get("sport_title", raw["sport_key"]),
        "home_team": raw["home_team"],
        "away_team": raw["away_team"],
        "commence_time": raw["commence_time"],
        "status": "upcoming",
        "external_ids": json.dumps({"odds_api": raw["id"]}),
    }


def normalize_odds(raw_event: dict) -> list[dict]:
    """Extract all odds snapshots from a raw Odds-API event.

    Returns a list of dicts ready for inserting into `odds_snapshots`.
    Each bookmaker × market × outcome produces one row.
    """
    event_id = raw_event["id"]
    snapshots = []

    for bookmaker in raw_event.get("bookmakers", []):
        bk_key = bookmaker["key"]

        # Skip bookmakers we don't track
        if bk_key not in settings.target_bookmakers:
            continue

        for market in bookmaker.get("markets", []):
            market_key = market["key"]

            for outcome in market.get("outcomes", []):
                snapshots.append(
                    {
                        "event_id": event_id,
                        "bookmaker_key": bk_key,
                        "market": market_key,
                        "outcome_name": outcome["name"],
                        "price": outcome["price"],
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
        bk_key = bookmaker["key"]
        if bk_key not in seen and bk_key in settings.target_bookmakers:
            seen[bk_key] = {
                "key": bk_key,
                "name": bookmaker["title"],
                "region": "ca",
                "is_sharp": bk_key == "pinnacle",
            }
    return list(seen.values())
