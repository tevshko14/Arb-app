"""Tests for the InfoFi Scanner — line movement detection."""

import pytest
from datetime import datetime, timedelta, timezone

from app.engine.line_movement import (
    LineMovementTracker,
    MarketSnapshot,
    MovementType,
    AlertPriority,
)


def _make_snapshot(event_id, odds, minutes_ago=0, sport="baseball_mlb"):
    """Helper to create a MarketSnapshot."""
    return MarketSnapshot(
        event_id=event_id,
        sport=sport,
        captured_at=datetime.now(timezone.utc) - timedelta(minutes=minutes_ago),
        odds=odds,
    )


class TestSteamMoveDetection:
    def test_large_move_detected_as_steam(self):
        tracker = LineMovementTracker(steam_threshold=0.03)

        # Snapshot 1: normal odds
        snap1 = _make_snapshot("evt_1", {
            "pinnacle": {"Yankees": 1.90, "Red Sox": 2.00},
            "bet365": {"Yankees": 1.95, "Red Sox": 1.95},
        }, minutes_ago=5)

        # Snapshot 2: big move at bet365
        snap2 = _make_snapshot("evt_1", {
            "pinnacle": {"Yankees": 1.90, "Red Sox": 2.00},
            "bet365": {"Yankees": 1.60, "Red Sox": 2.40},  # ~10% implied prob change
        })

        tracker.add_snapshot(snap1)
        tracker.add_snapshot(snap2)
        movements = tracker.detect_movements("evt_1")

        steam_moves = [m for m in movements if m.movement_type == MovementType.STEAM]
        assert len(steam_moves) > 0
        assert steam_moves[0].priority == AlertPriority.HIGH

    def test_small_move_ignored(self):
        tracker = LineMovementTracker(steam_threshold=0.03)

        snap1 = _make_snapshot("evt_1", {
            "bet365": {"Yankees": 1.90, "Red Sox": 2.00},
        }, minutes_ago=5)

        # Tiny move (< 0.5% change)
        snap2 = _make_snapshot("evt_1", {
            "bet365": {"Yankees": 1.89, "Red Sox": 2.01},
        })

        tracker.add_snapshot(snap1)
        tracker.add_snapshot(snap2)
        movements = tracker.detect_movements("evt_1")
        assert len(movements) == 0


class TestConvergenceDetection:
    def test_soft_book_moving_toward_sharp(self):
        tracker = LineMovementTracker(steam_threshold=0.05)  # Higher steam threshold

        snap1 = _make_snapshot("evt_1", {
            "pinnacle": {"A": 1.80, "B": 2.10},
            "bet365": {"A": 2.00, "B": 1.90},  # Far from sharp
        }, minutes_ago=5)

        # Move toward sharp but below steam threshold (~4% implied change)
        snap2 = _make_snapshot("evt_1", {
            "pinnacle": {"A": 1.80, "B": 2.10},
            "bet365": {"A": 1.85, "B": 2.05},  # Closer to sharp
        })

        tracker.add_snapshot(snap1)
        tracker.add_snapshot(snap2)
        movements = tracker.detect_movements("evt_1")

        convergence = [m for m in movements if m.movement_type == MovementType.CONVERGENCE]
        assert len(convergence) > 0


class TestStaleLineDetection:
    def test_finds_stale_lines(self):
        tracker = LineMovementTracker(stale_threshold=0.04)

        # Sharp says A is 60% likely, but bet365 still offers 50% odds
        snap = _make_snapshot("evt_1", {
            "pinnacle": {"A": 1.67, "B": 2.40},  # A ~60%
            "bet365": {"A": 2.00, "B": 1.90},  # A ~50% — stale!
        })
        tracker.add_snapshot(snap)

        stale = tracker.find_stale_lines("evt_1")
        assert len(stale) > 0
        assert stale[0].bookmaker == "bet365"
        assert stale[0].gap >= 0.04

    def test_no_stale_when_aligned(self):
        tracker = LineMovementTracker(stale_threshold=0.04)

        snap = _make_snapshot("evt_1", {
            "pinnacle": {"A": 1.90, "B": 2.00},
            "bet365": {"A": 1.91, "B": 1.99},  # Very close to sharp
        })
        tracker.add_snapshot(snap)

        stale = tracker.find_stale_lines("evt_1")
        assert len(stale) == 0

    def test_stale_sorted_by_gap(self):
        tracker = LineMovementTracker(stale_threshold=0.02)

        snap = _make_snapshot("evt_1", {
            "pinnacle": {"A": 1.50, "B": 2.80},  # A ~67%
            "bet365": {"A": 1.80, "B": 2.10},  # A ~56% — 11% gap
            "fanduel": {"A": 1.70, "B": 2.20},  # A ~59% — 8% gap
        })
        tracker.add_snapshot(snap)

        stale = tracker.find_stale_lines("evt_1")
        assert len(stale) >= 2
        # Most stale first
        assert stale[0].gap >= stale[1].gap


class TestMarketConsensus:
    def test_consensus_from_multiple_books(self):
        tracker = LineMovementTracker()

        snap = _make_snapshot("evt_1", {
            "pinnacle": {"A": 1.80, "B": 2.10},
            "bet365": {"A": 1.85, "B": 2.05},
            "fanduel": {"A": 1.90, "B": 2.00},
        })
        tracker.add_snapshot(snap)

        consensus = tracker.get_market_consensus("evt_1")
        assert consensus is not None
        assert "A" in consensus
        assert "B" in consensus
        # Should sum to ~1.0
        assert sum(consensus.values()) == pytest.approx(1.0, abs=0.01)

    def test_no_consensus_without_data(self):
        tracker = LineMovementTracker()
        assert tracker.get_market_consensus("nonexistent") is None


class TestAlertFiltering:
    def test_recent_alerts_by_hours(self):
        tracker = LineMovementTracker(steam_threshold=0.03)

        snap1 = _make_snapshot("evt_1", {
            "bet365": {"A": 1.90, "B": 2.00},
        }, minutes_ago=5)
        snap2 = _make_snapshot("evt_1", {
            "bet365": {"A": 1.50, "B": 2.60},
        })

        tracker.add_snapshot(snap1)
        tracker.add_snapshot(snap2)
        tracker.detect_movements("evt_1")

        alerts = tracker.get_recent_alerts(hours=1)
        assert len(alerts) > 0

    def test_filter_by_priority(self):
        tracker = LineMovementTracker(steam_threshold=0.03)

        snap1 = _make_snapshot("evt_1", {
            "pinnacle": {"A": 1.80, "B": 2.10},
            "bet365": {"A": 1.50, "B": 2.60},
        }, minutes_ago=5)
        snap2 = _make_snapshot("evt_1", {
            "pinnacle": {"A": 1.80, "B": 2.10},
            "bet365": {"A": 1.85, "B": 2.05},  # Convergence
        })

        tracker.add_snapshot(snap1)
        tracker.add_snapshot(snap2)
        tracker.detect_movements("evt_1")

        high = tracker.get_recent_alerts(priority=AlertPriority.HIGH)
        medium = tracker.get_recent_alerts(priority=AlertPriority.MEDIUM)
        # All high alerts should be steam moves
        for a in high:
            assert a.movement_type == MovementType.STEAM


class TestMovementVelocity:
    def test_velocity_with_insufficient_data(self):
        tracker = LineMovementTracker()
        snap = _make_snapshot("evt_1", {"bet365": {"A": 1.90}})
        tracker.add_snapshot(snap)
        assert tracker.movement_velocity("evt_1", "A", "bet365") is None

    def test_history_capped_at_100(self):
        tracker = LineMovementTracker()
        for i in range(110):
            snap = _make_snapshot("evt_1", {
                "bet365": {"A": 1.90 + i * 0.001},
            }, minutes_ago=110 - i)
            tracker.add_snapshot(snap)
        assert len(tracker.history["evt_1"]) == 100
