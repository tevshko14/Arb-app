"""Tests for the adaptive polling scheduler logic."""

from datetime import datetime, timezone, timedelta

from app.ingestion.scheduler import determine_tier, PollTier
from app.config import settings


class TestDetermineTier:
    def test_no_events_returns_idle(self):
        tier, interval = determine_tier(None)
        assert tier == PollTier.IDLE
        assert interval == settings.poll_idle_interval

    def test_far_event_returns_idle(self):
        future = datetime.now(timezone.utc) + timedelta(hours=12)
        tier, interval = determine_tier(future)
        assert tier == PollTier.IDLE

    def test_medium_event_returns_warm(self):
        future = datetime.now(timezone.utc) + timedelta(hours=4)
        tier, interval = determine_tier(future)
        assert tier == PollTier.WARM
        assert interval == settings.poll_warm_interval

    def test_close_event_returns_hot(self):
        future = datetime.now(timezone.utc) + timedelta(minutes=30)
        tier, interval = determine_tier(future)
        assert tier == PollTier.HOT
        assert interval == settings.poll_hot_interval

    def test_boundary_warm(self):
        # Exactly at warm threshold
        future = datetime.now(timezone.utc) + timedelta(
            hours=settings.poll_warm_threshold_hours - 0.01
        )
        tier, _ = determine_tier(future)
        assert tier == PollTier.WARM

    def test_boundary_hot(self):
        # Exactly at hot threshold
        future = datetime.now(timezone.utc) + timedelta(
            hours=settings.poll_hot_threshold_hours - 0.01
        )
        tier, _ = determine_tier(future)
        assert tier == PollTier.HOT

    def test_past_event_returns_hot(self):
        # Event already started — should be HOT (most urgent)
        past = datetime.now(timezone.utc) - timedelta(minutes=5)
        tier, _ = determine_tier(past)
        assert tier == PollTier.HOT
