"""Tests for API input validation logic."""

import pytest
from fastapi import HTTPException

from app.utils.validation import validate_event_id, validate_bookmaker_key, EVENT_ID_PATTERN


class TestEventIdValidation:
    def test_valid_hex_32(self):
        valid_id = "abc123def456abc123def456abc12345"
        assert validate_event_id(valid_id) == valid_id

    def test_rejects_short_id(self):
        with pytest.raises(HTTPException) as exc_info:
            validate_event_id("abc123")
        assert exc_info.value.status_code == 400

    def test_rejects_non_hex(self):
        with pytest.raises(HTTPException):
            validate_event_id("ZZZZ23def456abc123def456abc12345")

    def test_rejects_empty(self):
        with pytest.raises(HTTPException):
            validate_event_id("")

    def test_rejects_sql_injection_attempt(self):
        with pytest.raises(HTTPException):
            validate_event_id("'; DROP TABLE events; --")

    def test_rejects_path_traversal(self):
        with pytest.raises(HTTPException):
            validate_event_id("../../etc/passwd")


class TestBookmakerKeyValidation:
    def test_valid_key(self):
        assert validate_bookmaker_key("pinnacle") == "pinnacle"
        assert validate_bookmaker_key("bet365") == "bet365"
        assert validate_bookmaker_key("sports_interaction") == "sports_interaction"

    def test_rejects_special_chars(self):
        with pytest.raises(HTTPException):
            validate_bookmaker_key("book;DROP TABLE")

    def test_rejects_empty(self):
        with pytest.raises(HTTPException):
            validate_bookmaker_key("")

    def test_rejects_too_long(self):
        with pytest.raises(HTTPException):
            validate_bookmaker_key("a" * 65)


class TestEventIdPattern:
    def test_pattern_matches_real_odds_api_ids(self):
        # Real Odds-API event IDs are 32-char hex
        real_ids = [
            "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4",
            "00000000000000000000000000000000",
            "ffffffffffffffffffffffffffffffff",
        ]
        for eid in real_ids:
            assert EVENT_ID_PATTERN.match(eid), f"Should match: {eid}"

    def test_pattern_rejects_invalid(self):
        invalid = ["short", "has spaces in it here now!!!!!", "UPPERCASE_HEX_1234"]
        for eid in invalid:
            assert not EVENT_ID_PATTERN.match(eid), f"Should reject: {eid}"
