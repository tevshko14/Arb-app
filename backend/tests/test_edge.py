"""Tests for the Edge/Alpha calculation engine."""

import pytest

from app.engine.edge import (
    EdgeSignal,
    EventOdds,
    calculate_edge,
    find_edges,
    implied_probability,
    remove_vig,
)


class TestImpliedProbability:
    def test_even_odds(self):
        assert implied_probability(2.0) == pytest.approx(0.50)

    def test_heavy_favorite(self):
        assert implied_probability(1.25) == pytest.approx(0.80)

    def test_heavy_underdog(self):
        assert implied_probability(5.0) == pytest.approx(0.20)

    def test_odds_of_one(self):
        assert implied_probability(1.0) == pytest.approx(1.0)

    def test_invalid_odds_below_one(self):
        assert implied_probability(0.5) == 1.0


class TestRemoveVig:
    def test_balanced_vig(self):
        # 1.90 / 1.90 implies 52.6% each = 105.2% total
        raw = {"home": 1 / 1.90, "away": 1 / 1.90}
        fair = remove_vig(raw)
        assert fair["home"] == pytest.approx(0.50, abs=0.01)
        assert fair["away"] == pytest.approx(0.50, abs=0.01)
        assert sum(fair.values()) == pytest.approx(1.0)

    def test_lopsided_vig(self):
        raw = {"home": implied_probability(1.50), "away": implied_probability(2.80)}
        fair = remove_vig(raw)
        assert sum(fair.values()) == pytest.approx(1.0)
        assert fair["home"] > fair["away"]

    def test_empty(self):
        assert remove_vig({}) == {}


class TestCalculateEdge:
    def test_positive_edge(self):
        # Model says 55%, odds are 2.0 (50% implied)
        edge = calculate_edge(0.55, 2.0)
        assert edge == pytest.approx(0.10)  # 10% edge

    def test_zero_edge(self):
        edge = calculate_edge(0.50, 2.0)
        assert edge == pytest.approx(0.0)

    def test_negative_edge(self):
        edge = calculate_edge(0.40, 2.0)
        assert edge == pytest.approx(-0.20)

    def test_heavy_favorite_edge(self):
        # Model says 80%, odds 1.30 (76.9% implied)
        edge = calculate_edge(0.80, 1.30)
        assert edge == pytest.approx(0.04, abs=0.01)


class TestFindEdges:
    def setup_method(self):
        self.event = EventOdds(
            event_id="test123",
            sport="baseball_mlb",
            home_team="Yankees",
            away_team="Red Sox",
            odds={
                "pinnacle": {"Yankees": 1.85, "Red Sox": 2.05},
                "bet365": {"Yankees": 1.95, "Red Sox": 1.95},
                "draftkings": {"Yankees": 1.80, "Red Sox": 2.10},
            },
        )

    def test_finds_positive_edge(self):
        # Model agrees with Pinnacle: Yankees ~54%
        model_probs = {"Yankees": 0.54, "Red Sox": 0.46}
        signals = find_edges(self.event, model_probs, min_edge=0.02)
        # bet365 offers Yankees at 1.95 vs model 54% → edge = 0.54*1.95-1 = 0.053
        assert len(signals) >= 1
        assert all(s.edge >= 0.02 for s in signals)

    def test_sorted_by_edge(self):
        model_probs = {"Yankees": 0.54, "Red Sox": 0.46}
        signals = find_edges(self.event, model_probs, min_edge=0.0)
        if len(signals) > 1:
            assert signals[0].edge >= signals[1].edge

    def test_skips_sharp_book(self):
        model_probs = {"Yankees": 0.54, "Red Sox": 0.46}
        signals = find_edges(self.event, model_probs, min_edge=0.0)
        assert all(s.bookmaker != "pinnacle" for s in signals)

    def test_no_edge_returns_empty(self):
        # Model says 45% Yankees but odds only 1.80 → negative EV
        model_probs = {"Yankees": 0.45, "Red Sox": 0.55}
        signals = find_edges(self.event, model_probs, min_edge=0.05)
        yankee_signals = [s for s in signals if s.outcome == "Yankees"]
        # Yankees at 1.80 * 0.45 = 0.81 → -19% edge, should not appear
        assert all(s.edge >= 0.05 for s in yankee_signals)

    def test_edge_signal_has_all_fields(self):
        model_probs = {"Yankees": 0.55, "Red Sox": 0.45}
        signals = find_edges(self.event, model_probs, min_edge=0.0)
        if signals:
            s = signals[0]
            assert s.event_id == "test123"
            assert s.sport == "baseball_mlb"
            assert s.decimal_odds > 1.0
            assert 0 < s.model_prob < 1
            assert 0 < s.implied_prob < 1
