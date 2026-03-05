"""Tests for the Kelly Criterion bet sizing engine."""

import pytest

from app.engine.kelly import (
    KellyRecommendation,
    full_kelly,
    fractional_kelly,
    recommend_bet,
    size_portfolio,
    MAX_STAKE_FRACTION,
    MIN_EDGE_TO_BET,
)


class TestFullKelly:
    def test_positive_ev(self):
        # 55% win prob at even odds (2.0)
        # f = (0.55 * 1 - 0.45) / 1 = 0.10
        f = full_kelly(0.55, 2.0)
        assert f == pytest.approx(0.10)

    def test_large_edge(self):
        # 70% win prob at 2.0 odds → f = (0.7 * 1 - 0.3) / 1 = 0.40
        f = full_kelly(0.70, 2.0)
        assert f == pytest.approx(0.40)

    def test_negative_ev_returns_zero(self):
        # 40% at 2.0 → negative EV
        f = full_kelly(0.40, 2.0)
        assert f == 0.0

    def test_break_even_returns_zero(self):
        f = full_kelly(0.50, 2.0)
        assert f == 0.0

    def test_high_odds_underdog(self):
        # 15% at 8.0 odds → f = (0.15 * 7 - 0.85) / 7 = 0.0286
        f = full_kelly(0.15, 8.0)
        assert f == pytest.approx(0.0286, abs=0.001)

    def test_invalid_odds(self):
        assert full_kelly(0.50, 0.5) == 0.0
        assert full_kelly(0.50, 1.0) == 0.0


class TestFractionalKelly:
    def test_half_kelly(self):
        f_full = full_kelly(0.55, 2.0)
        f_half = fractional_kelly(0.55, 2.0, multiplier=0.5)
        assert f_half == pytest.approx(f_full * 0.5)

    def test_quarter_kelly(self):
        f_full = full_kelly(0.55, 2.0)
        f_quarter = fractional_kelly(0.55, 2.0, multiplier=0.25)
        assert f_quarter == pytest.approx(f_full * 0.25)

    def test_full_kelly_multiplier(self):
        f_full = full_kelly(0.55, 2.0)
        f_one = fractional_kelly(0.55, 2.0, multiplier=1.0)
        assert f_one == pytest.approx(f_full)


class TestRecommendBet:
    def test_returns_recommendation(self):
        rec = recommend_bet(
            event_id="test123",
            outcome="Yankees",
            bookmaker="bet365",
            model_prob=0.60,
            decimal_odds=2.0,
            bankroll=1000.0,
            kelly_multiplier=0.5,
        )
        assert rec is not None
        assert rec.edge > 0
        assert rec.recommended_stake > 0
        assert rec.kelly_multiplier == 0.5

    def test_negative_ev_returns_none(self):
        rec = recommend_bet(
            event_id="test",
            outcome="Team",
            bookmaker="book",
            model_prob=0.40,
            decimal_odds=2.0,
            bankroll=1000.0,
        )
        assert rec is None

    def test_below_min_edge_returns_none(self):
        # Edge just barely positive but below MIN_EDGE_TO_BET
        rec = recommend_bet(
            event_id="test",
            outcome="Team",
            bookmaker="book",
            model_prob=0.505,
            decimal_odds=2.0,
            bankroll=1000.0,
        )
        assert rec is None

    def test_stake_capped_at_max(self):
        # Very large edge should be capped
        rec = recommend_bet(
            event_id="test",
            outcome="Team",
            bookmaker="book",
            model_prob=0.90,
            decimal_odds=3.0,
            bankroll=10000.0,
            kelly_multiplier=1.0,  # Full Kelly for extreme case
        )
        assert rec is not None
        assert rec.capped is True
        assert rec.adjusted_kelly_fraction <= MAX_STAKE_FRACTION

    def test_stake_matches_bankroll_fraction(self):
        rec = recommend_bet(
            event_id="test",
            outcome="Team",
            bookmaker="book",
            model_prob=0.60,
            decimal_odds=2.0,
            bankroll=2000.0,
            kelly_multiplier=0.5,
        )
        assert rec is not None
        expected_stake = rec.adjusted_kelly_fraction * 2000.0
        assert rec.recommended_stake == pytest.approx(expected_stake, abs=0.01)


class TestSizePortfolio:
    def test_under_limit_unchanged(self):
        recs = [
            KellyRecommendation(
                event_id="a", outcome="X", bookmaker="b",
                decimal_odds=2.0, model_prob=0.55, edge=0.10,
                full_kelly_fraction=0.10, adjusted_kelly_fraction=0.05,
                recommended_stake=50.0, bankroll=1000.0,
                kelly_multiplier=0.5, capped=False,
            ),
        ]
        result = size_portfolio(recs, max_total_exposure=0.20)
        assert result[0].adjusted_kelly_fraction == 0.05

    def test_over_limit_scaled_down(self):
        recs = [
            KellyRecommendation(
                event_id=f"ev{i}", outcome="X", bookmaker="b",
                decimal_odds=2.0, model_prob=0.60, edge=0.10,
                full_kelly_fraction=0.10, adjusted_kelly_fraction=0.08,
                recommended_stake=80.0, bankroll=1000.0,
                kelly_multiplier=0.5, capped=False,
            )
            for i in range(5)  # 5 × 8% = 40% > 20% limit
        ]
        result = size_portfolio(recs, max_total_exposure=0.20)
        total = sum(r.adjusted_kelly_fraction for r in result)
        assert total == pytest.approx(0.20, abs=0.01)

    def test_empty_portfolio(self):
        assert size_portfolio([]) == []
