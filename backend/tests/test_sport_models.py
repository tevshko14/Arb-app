"""Tests for sport-specific models (MLB Poisson, UFC Elo)."""

import pytest

from app.engine.models.mlb import (
    MLBTeamStats,
    MLBMatchup,
    calculate_expected_runs,
    make_poisson_scorer,
    simulate_mlb_game,
    LEAGUE_AVG_RUNS,
)
from app.engine.models.ufc import (
    UFCFighterStats,
    UFCMatchup,
    elo_win_probability,
    stat_adjustment,
    calculate_win_probability,
    simulate_ufc_bout,
)


class TestMLBExpectedRuns:
    def test_average_team_vs_average_team(self):
        runs = calculate_expected_runs(
            team_offense=LEAGUE_AVG_RUNS,
            opponent_defense=LEAGUE_AVG_RUNS,
        )
        assert runs == pytest.approx(LEAGUE_AVG_RUNS, abs=0.5)

    def test_good_offense_vs_bad_defense(self):
        runs = calculate_expected_runs(
            team_offense=5.5,  # Good offense
            opponent_defense=5.0,  # Bad defense (allows many runs)
        )
        assert runs > LEAGUE_AVG_RUNS

    def test_bad_offense_vs_good_defense(self):
        runs = calculate_expected_runs(
            team_offense=3.5,
            opponent_defense=3.5,
        )
        assert runs < LEAGUE_AVG_RUNS

    def test_home_field_advantage(self):
        home_runs = calculate_expected_runs(
            LEAGUE_AVG_RUNS, LEAGUE_AVG_RUNS, is_home=True,
        )
        away_runs = calculate_expected_runs(
            LEAGUE_AVG_RUNS, LEAGUE_AVG_RUNS, is_home=False,
        )
        assert home_runs > away_runs

    def test_starter_era_effect(self):
        # Good pitcher (low ERA) reduces opponent's runs
        vs_ace = calculate_expected_runs(
            LEAGUE_AVG_RUNS, LEAGUE_AVG_RUNS, starter_era=2.5,
        )
        vs_bad = calculate_expected_runs(
            LEAGUE_AVG_RUNS, LEAGUE_AVG_RUNS, starter_era=6.0,
        )
        assert vs_ace < vs_bad

    def test_floor_at_half_run(self):
        runs = calculate_expected_runs(0.5, 0.5, starter_era=1.0)
        assert runs >= 0.5


class TestMLBSimulation:
    def test_simulate_game(self):
        matchup = MLBMatchup(
            event_id="mlb_test",
            home=MLBTeamStats(name="Yankees", runs_per_game=5.0, runs_allowed_per_game=3.8),
            away=MLBTeamStats(name="Red Sox", runs_per_game=4.2, runs_allowed_per_game=4.5),
        )
        result = simulate_mlb_game(matchup, n_sims=10_000, seed=42)
        sim = result["simulation"]

        # Yankees (better offense + worse opponent defense) should be favored
        assert sim.outcome_probs["Yankees"] > sim.outcome_probs["Red Sox"]
        assert sum(v for k, v in sim.outcome_probs.items() if k != "Draw") > 0.85

    def test_expected_runs_in_output(self):
        matchup = MLBMatchup(
            event_id="test",
            home=MLBTeamStats(name="A"),
            away=MLBTeamStats(name="B"),
        )
        result = simulate_mlb_game(matchup, n_sims=1000, seed=42)
        assert "home_expected_runs" in result
        assert "total_expected_runs" in result
        assert result["total_expected_runs"] > 0


class TestPoissonScorer:
    def test_scorer_returns_correct_shape(self):
        import numpy as np
        scorer = make_poisson_scorer(4.5)
        rng = np.random.default_rng(42)
        scores = scorer(rng, 1000)
        assert len(scores) == 1000
        assert scores.mean() == pytest.approx(4.5, abs=0.3)


class TestUFCElo:
    def test_equal_elo_gives_50_50(self):
        p = elo_win_probability(1500, 1500)
        assert p == pytest.approx(0.50)

    def test_higher_elo_favored(self):
        p = elo_win_probability(1700, 1500)
        assert p > 0.50

    def test_lower_elo_unfavored(self):
        p = elo_win_probability(1300, 1500)
        assert p < 0.50

    def test_large_elo_gap(self):
        p = elo_win_probability(2000, 1500)
        assert p > 0.90

    def test_symmetry(self):
        p_a = elo_win_probability(1600, 1400)
        p_b = elo_win_probability(1400, 1600)
        assert p_a + p_b == pytest.approx(1.0)


class TestUFCStatAdjustment:
    def test_equal_fighters_no_adjustment(self):
        a = UFCFighterStats(name="A")
        b = UFCFighterStats(name="B")
        adj = stat_adjustment(a, b)
        assert adj == pytest.approx(0.0, abs=0.01)

    def test_better_striker_positive_adjustment(self):
        a = UFCFighterStats(name="A", sig_strikes_landed_per_min=7.0, sig_strike_accuracy=0.55)
        b = UFCFighterStats(name="B", sig_strikes_landed_per_min=3.0, sig_strike_accuracy=0.35)
        adj = stat_adjustment(a, b)
        assert adj > 0

    def test_adjustment_capped(self):
        a = UFCFighterStats(
            name="A", sig_strikes_landed_per_min=10.0, sig_strike_accuracy=0.70,
            takedowns_per_15min=5.0, takedown_accuracy=0.80,
        )
        b = UFCFighterStats(
            name="B", sig_strikes_landed_per_min=1.0, sig_strike_accuracy=0.20,
            takedowns_per_15min=0.5, takedown_accuracy=0.10,
        )
        adj = stat_adjustment(a, b)
        assert -0.10 <= adj <= 0.10


class TestUFCSimulation:
    def test_simulate_bout(self):
        matchup = UFCMatchup(
            event_id="ufc_test",
            fighter_a=UFCFighterStats(name="Makhachev", elo=1800),
            fighter_b=UFCFighterStats(name="Challenger", elo=1500),
        )
        result = simulate_ufc_bout(matchup, n_sims=10_000, seed=42)
        sim = result["simulation"]

        # Higher Elo fighter should be heavily favored
        assert sim.outcome_probs["Makhachev"] > 0.60

    def test_combined_probability_clamped(self):
        prob = calculate_win_probability(
            UFCFighterStats(name="A", elo=2500),  # Extreme Elo
            UFCFighterStats(name="B", elo=1000),
        )
        assert 0.05 <= prob <= 0.95
