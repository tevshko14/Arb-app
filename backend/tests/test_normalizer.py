"""Tests for the odds normalizer — including edge cases and error handling."""

import pytest

from app.ingestion.normalizer import (
    NormalizationError,
    normalize_event,
    normalize_odds,
    extract_bookmakers,
)


SAMPLE_EVENT = {
    "id": "abc123def456abc123def456abc12345",
    "sport_key": "baseball_mlb",
    "sport_title": "MLB",
    "home_team": "New York Yankees",
    "away_team": "Boston Red Sox",
    "commence_time": "2026-04-15T23:05:00Z",
    "bookmakers": [
        {
            "key": "pinnacle",
            "title": "Pinnacle",
            "markets": [
                {
                    "key": "h2h",
                    "outcomes": [
                        {"name": "New York Yankees", "price": 1.85},
                        {"name": "Boston Red Sox", "price": 2.05},
                    ],
                },
                {
                    "key": "spreads",
                    "outcomes": [
                        {"name": "New York Yankees", "price": 1.91, "point": -1.5},
                        {"name": "Boston Red Sox", "price": 1.91, "point": 1.5},
                    ],
                },
            ],
        },
        {
            "key": "bet365",
            "title": "Bet365",
            "markets": [
                {
                    "key": "h2h",
                    "outcomes": [
                        {"name": "New York Yankees", "price": 1.83},
                        {"name": "Boston Red Sox", "price": 2.10},
                    ],
                },
            ],
        },
        {
            "key": "some_random_book",
            "title": "Random Book",
            "markets": [
                {
                    "key": "h2h",
                    "outcomes": [
                        {"name": "New York Yankees", "price": 1.80},
                    ],
                },
            ],
        },
    ],
}


class TestNormalizeEvent:
    def test_basic_fields(self):
        result = normalize_event(SAMPLE_EVENT)
        assert result["id"] == "abc123def456abc123def456abc12345"
        assert result["sport"] == "baseball_mlb"
        assert result["home_team"] == "New York Yankees"
        assert result["away_team"] == "Boston Red Sox"
        assert result["status"] == "upcoming"

    def test_commence_time_passthrough(self):
        result = normalize_event(SAMPLE_EVENT)
        assert result["commence_time"] == "2026-04-15T23:05:00Z"

    def test_missing_sport_title_falls_back(self):
        raw = dict(SAMPLE_EVENT)
        del raw["sport_title"]
        result = normalize_event(raw)
        assert result["league"] == "baseball_mlb"

    def test_missing_required_field_raises(self):
        for field in ["id", "sport_key", "home_team", "away_team", "commence_time"]:
            raw = dict(SAMPLE_EVENT)
            del raw[field]
            with pytest.raises(NormalizationError):
                normalize_event(raw)

    def test_empty_string_field_raises(self):
        raw = dict(SAMPLE_EVENT)
        raw["id"] = ""
        with pytest.raises(NormalizationError):
            normalize_event(raw)


class TestNormalizeOdds:
    def test_snapshot_count(self):
        snapshots = normalize_odds(SAMPLE_EVENT)
        assert len(snapshots) == 6

    def test_snapshot_structure(self):
        snapshots = normalize_odds(SAMPLE_EVENT)
        snap = snapshots[0]
        assert "event_id" in snap
        assert "bookmaker_key" in snap
        assert "market" in snap
        assert "outcome_name" in snap
        assert "price" in snap
        assert "point" in snap

    def test_filters_non_target_books(self):
        snapshots = normalize_odds(SAMPLE_EVENT)
        book_keys = {s["bookmaker_key"] for s in snapshots}
        assert "some_random_book" not in book_keys

    def test_spread_has_point(self):
        snapshots = normalize_odds(SAMPLE_EVENT)
        spreads = [s for s in snapshots if s["market"] == "spreads"]
        assert len(spreads) == 2
        assert spreads[0]["point"] == -1.5

    def test_empty_bookmakers_returns_empty(self):
        raw = dict(SAMPLE_EVENT)
        raw["bookmakers"] = []
        assert normalize_odds(raw) == []

    def test_no_bookmakers_key_returns_empty(self):
        assert normalize_odds({"id": "test123"}) == []

    def test_missing_event_id_returns_empty(self):
        assert normalize_odds({"bookmakers": []}) == []

    def test_malformed_outcome_skipped(self):
        raw = {
            "id": "abc123",
            "bookmakers": [
                {
                    "key": "pinnacle",
                    "title": "Pinnacle",
                    "markets": [
                        {
                            "key": "h2h",
                            "outcomes": [
                                {"name": "Team A", "price": 1.5},
                                {"name": None, "price": 2.0},
                                {"name": "Team B"},
                            ],
                        }
                    ],
                }
            ],
        }
        snapshots = normalize_odds(raw)
        assert len(snapshots) == 1
        assert snapshots[0]["outcome_name"] == "Team A"

    def test_missing_market_key_skipped(self):
        raw = {
            "id": "abc123",
            "bookmakers": [
                {
                    "key": "pinnacle",
                    "title": "Pinnacle",
                    "markets": [
                        {"outcomes": [{"name": "A", "price": 1.5}]},
                    ],
                }
            ],
        }
        assert normalize_odds(raw) == []


class TestExtractBookmakers:
    def test_extracts_target_books_only(self):
        bks = extract_bookmakers(SAMPLE_EVENT)
        keys = {b["key"] for b in bks}
        assert "pinnacle" in keys
        assert "bet365" in keys
        assert "some_random_book" not in keys

    def test_pinnacle_is_sharp(self):
        bks = extract_bookmakers(SAMPLE_EVENT)
        pinnacle = next(b for b in bks if b["key"] == "pinnacle")
        assert pinnacle["is_sharp"] is True

    def test_bet365_is_soft(self):
        bks = extract_bookmakers(SAMPLE_EVENT)
        b365 = next(b for b in bks if b["key"] == "bet365")
        assert b365["is_sharp"] is False

    def test_empty_bookmakers(self):
        assert extract_bookmakers({"bookmakers": []}) == []
        assert extract_bookmakers({}) == []

    def test_bookmaker_missing_key(self):
        raw = {"bookmakers": [{"title": "No Key Book", "markets": []}]}
        assert extract_bookmakers(raw) == []

    def test_deduplication(self):
        raw = {
            "bookmakers": [
                {"key": "pinnacle", "title": "Pinnacle", "markets": []},
                {"key": "pinnacle", "title": "Pinnacle Dupe", "markets": []},
            ]
        }
        bks = extract_bookmakers(raw)
        assert len(bks) == 1
