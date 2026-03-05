"""Tests for the Humanizer — bet pattern randomization."""

import pytest
from datetime import datetime, timedelta, timezone

from app.engine.humanizer import (
    Humanizer,
    HumanizerConfig,
    NATURAL_AMOUNTS,
)


class TestStakeRandomization:
    def test_stake_gets_noise(self):
        h = Humanizer(HumanizerConfig(seed=42))
        bet = h.humanize_bet("evt_1", "Team A", "bet365", 100.0)
        # Should not be exactly 100 (noise applied)
        assert bet.humanized_stake != 100.0
        assert not bet.suppressed

    def test_stake_within_noise_range(self):
        h = Humanizer(HumanizerConfig(seed=42, stake_noise_min=0.05, stake_noise_max=0.15))
        results = set()
        for i in range(50):
            h_inner = Humanizer(HumanizerConfig(seed=i))
            bet = h_inner.humanize_bet("evt_1", "A", "bet365", 100.0)
            results.add(bet.humanized_stake)
        # All should be natural amounts within reasonable range
        for stake in results:
            assert 60 <= stake <= 150  # ±50% range accounts for rounding to natural

    def test_rounds_to_natural_amount(self):
        h = Humanizer(HumanizerConfig(seed=42, round_to_natural=True))
        bet = h.humanize_bet("evt_1", "A", "bet365", 73.0)
        assert bet.humanized_stake in NATURAL_AMOUNTS or bet.humanized_stake % 50 == 0

    def test_minimum_stake_is_5(self):
        h = Humanizer(HumanizerConfig(seed=42))
        bet = h.humanize_bet("evt_1", "A", "bet365", 1.0)
        assert bet.humanized_stake >= 5.0

    def test_large_stakes_round_to_100s(self):
        h = Humanizer(HumanizerConfig(seed=42))
        bet = h.humanize_bet("evt_1", "A", "bet365", 1500.0)
        # Large amounts should round to nearest $50 or $100
        assert bet.humanized_stake % 50 == 0 or bet.humanized_stake in NATURAL_AMOUNTS


class TestTimingDelay:
    def test_delay_within_bounds(self):
        cfg = HumanizerConfig(seed=42, min_delay_seconds=30, max_delay_seconds=300)
        h = Humanizer(cfg)
        bet = h.humanize_bet("evt_1", "A", "bet365", 100.0)
        assert 30 <= bet.delay_seconds <= 300

    def test_delays_vary(self):
        delays = set()
        for i in range(20):
            h = Humanizer(HumanizerConfig(seed=i))
            bet = h.humanize_bet("evt_1", "A", "bet365", 100.0)
            delays.add(bet.delay_seconds)
        assert len(delays) > 1  # Different seeds produce different delays


class TestFrequencyLimits:
    def test_daily_limit_suppresses_bets(self):
        h = Humanizer(HumanizerConfig(seed=42, max_bets_per_day_per_book=2))
        # Place 2 bets
        h.record_bet_placed("bet365")
        h.record_bet_placed("bet365")
        # Third should be suppressed
        bet = h.humanize_bet("evt_3", "A", "bet365", 100.0)
        assert bet.suppressed
        assert "Daily limit" in bet.suppression_reason

    def test_weekly_limit_suppresses_bets(self):
        h = Humanizer(HumanizerConfig(
            seed=42, max_bets_per_week_per_book=3,
            max_bets_per_day_per_book=10,  # High daily limit so weekly triggers first
            min_time_between_bets=0,
        ))
        for i in range(3):
            h.record_bet_placed("bet365")
        bet = h.humanize_bet("evt_4", "A", "bet365", 100.0)
        assert bet.suppressed
        assert "Weekly limit" in bet.suppression_reason

    def test_different_bookmakers_independent(self):
        h = Humanizer(HumanizerConfig(seed=42, max_bets_per_day_per_book=1))
        h.record_bet_placed("bet365")
        # Different bookmaker should still be allowed
        bet = h.humanize_bet("evt_2", "A", "fanduel", 100.0)
        assert not bet.suppressed


class TestWinStreakProtection:
    def test_consecutive_wins_trigger_cooloff(self):
        h = Humanizer(HumanizerConfig(
            seed=42, max_consecutive_wins=3,
            max_bets_per_day_per_book=10,  # High so daily limit doesn't fire first
            min_time_between_bets=0,
        ))
        for _ in range(3):
            h.record_bet_placed("bet365", won=True)
        bet = h.humanize_bet("evt_4", "A", "bet365", 100.0)
        assert bet.suppressed
        assert "Win streak" in bet.suppression_reason

    def test_loss_resets_streak(self):
        h = Humanizer(HumanizerConfig(
            seed=42, max_consecutive_wins=3,
            max_bets_per_day_per_book=10,
            min_time_between_bets=0,
        ))
        h.record_bet_placed("bet365", won=True)
        h.record_bet_placed("bet365", won=True)
        h.record_bet_result("bet365", won=False)  # Resets streak
        h.record_bet_placed("bet365", won=True)
        bet = h.humanize_bet("evt_5", "A", "bet365", 100.0)
        assert not bet.suppressed


class TestBookmakerRotation:
    def test_unused_bookmakers_preferred(self):
        h = Humanizer(HumanizerConfig(seed=42))
        h.record_bet_placed("bet365")
        h.record_bet_placed("bet365")
        ranking = h.suggest_bookmaker_rotation(["bet365", "fanduel", "draftkings"])
        # Unused bookmakers should rank higher
        assert ranking[0] != "bet365"

    def test_all_unused_rank_equally(self):
        h = Humanizer(HumanizerConfig(seed=42))
        ranking = h.suggest_bookmaker_rotation(["a", "b", "c"])
        assert len(ranking) == 3


class TestDailyReset:
    def test_reset_daily_counts(self):
        h = Humanizer(HumanizerConfig(
            seed=42, max_bets_per_day_per_book=1,
            min_time_between_bets=0,  # Disable time check for this test
        ))
        h.record_bet_placed("bet365")
        # Should be suppressed
        bet = h.humanize_bet("evt_2", "A", "bet365", 100.0)
        assert bet.suppressed
        # Reset
        h.reset_daily_counts()
        bet = h.humanize_bet("evt_3", "A", "bet365", 100.0)
        assert not bet.suppressed
