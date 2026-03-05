"""Input validation utilities for API endpoints."""

import re

from fastapi import HTTPException

# Event IDs from The-Odds-API are 32-char hex strings
EVENT_ID_PATTERN = re.compile(r"^[a-f0-9]{32}$")
BOOKMAKER_KEY_PATTERN = re.compile(r"^[a-z0-9_]{1,64}$")


def validate_event_id(event_id: str) -> str:
    """Validate event ID is a 32-char hex string."""
    if not EVENT_ID_PATTERN.match(event_id):
        raise HTTPException(status_code=400, detail="Invalid event ID format")
    return event_id


def validate_bookmaker_key(key: str) -> str:
    """Validate bookmaker key is alphanumeric + underscore, 1-64 chars."""
    if not BOOKMAKER_KEY_PATTERN.match(key):
        raise HTTPException(status_code=400, detail="Invalid bookmaker key format")
    return key
