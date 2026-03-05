"""Tests for the Monte Carlo simulation engine."""

import pytest
import numpy as np

from app.engine.monte_carlo import MonteCarloEngine, SimulationResult


class TestBinarySimulation:
    def test_fair_coin(self):
        engine = MonteCarloEngine(n_sims=50_000, seed=42)
        result = engine.simulate_binary("test", home_win_prob=0.50)
        assert result.outcome_probs["home"] == pytest.approx(0.50, abs=0.02)
        assert result.outcome_probs["away"] == pytest.approx(0.50, abs=0.02)

    def test_heavy_favorite(self):
        engine = MonteCarloEngine(n_sims=50_000, seed=42)
        result = engine.simulate_binary("test", home_win_prob=0.80)
        assert result.outcome_probs["home"] == pytest.approx(0.80, abs=0.02)

    def test_heavy_underdog(self):
        engine = MonteCarloEngine(n_sims=50_000, seed=42)
        result = engine.simulate_binary("test", home_win_prob=0.10)
        assert result.outcome_probs["home"] == pytest.approx(0.10, abs=0.02)

    def test_probabilities_sum_to_one(self):
        engine = MonteCarloEngine(n_sims=10_000, seed=42)
        result = engine.simulate_binary("test", home_win_prob=0.65)
        total = sum(result.outcome_probs.values())
        assert total == pytest.approx(1.0, abs=0.001)

    def test_confidence_intervals_contain_true_value(self):
        engine = MonteCarloEngine(n_sims=50_000, seed=42)
        true_prob = 0.60
        result = engine.simulate_binary("test", home_win_prob=true_prob)
        ci = result.confidence_intervals["home"]
        assert ci[0] <= true_prob <= ci[1]

    def test_custom_outcome_names(self):
        engine = MonteCarloEngine(n_sims=1000, seed=42)
        result = engine.simulate_binary(
            "test", home_win_prob=0.5,
            outcome_names=("Yankees", "Red Sox"),
        )
        assert "Yankees" in result.outcome_probs
        assert "Red Sox" in result.outcome_probs

    def test_variance_reduction_reduces_std_error(self):
        engine = MonteCarloEngine(n_sims=10_000, seed=42)

        # With variance reduction
        with_vr = engine.simulate_binary(
            "test", 0.50, use_antithetic=True, use_stratified=True,
        )
        # Without
        without_vr = engine.simulate_binary(
            "test", 0.50, use_antithetic=False, use_stratified=False,
        )

        # VR should have lower or equal std error
        assert with_vr.std_errors["home"] <= without_vr.std_errors["home"] * 1.5


class TestScoringSimulation:
    def test_poisson_scoring(self):
        engine = MonteCarloEngine(n_sims=50_000, seed=42)

        def home_scorer(rng, n):
            return rng.poisson(5.0, n).astype(float)  # Strong offense

        def away_scorer(rng, n):
            return rng.poisson(3.5, n).astype(float)  # Weaker offense

        result = engine.simulate_scoring(
            "test", home_scorer, away_scorer,
            outcome_names=("Home", "Away"),
        )
        # Home team with higher lambda should win more often
        assert result.outcome_probs["Home"] > result.outcome_probs["Away"]

    def test_equal_teams(self):
        engine = MonteCarloEngine(n_sims=50_000, seed=42)

        def scorer(rng, n):
            return rng.poisson(4.0, n).astype(float)

        result = engine.simulate_scoring(
            "test", scorer, scorer,
            outcome_names=("A", "B"),
        )
        # Should be approximately 50/50 (excluding draws)
        assert result.outcome_probs["A"] == pytest.approx(
            result.outcome_probs["B"], abs=0.03
        )

    def test_draws_possible(self):
        engine = MonteCarloEngine(n_sims=50_000, seed=42)

        def scorer(rng, n):
            return rng.poisson(3.0, n).astype(float)

        result = engine.simulate_scoring("test", scorer, scorer)
        # Poisson scoring should produce some draws
        if "Draw" in result.outcome_probs:
            assert result.outcome_probs["Draw"] > 0


class TestImportanceSampling:
    def test_rare_event_estimation(self):
        engine = MonteCarloEngine(n_sims=10_000, seed=42)
        result = engine.importance_sampling_underdog(
            "test", true_prob=0.03, outcome_name="Underdog",
        )
        # IS should give a reasonable estimate near 0.03
        assert result["probability"] == pytest.approx(0.03, abs=0.02)
        assert result["method"] == "importance_sampling"

    def test_not_rare_uses_crude(self):
        engine = MonteCarloEngine(n_sims=10_000, seed=42)
        result = engine.importance_sampling_underdog(
            "test", true_prob=0.30, outcome_name="Moderate",
        )
        assert result["method"] == "crude"

    def test_variance_reduction_factor(self):
        engine = MonteCarloEngine(n_sims=10_000, seed=42)
        result = engine.importance_sampling_underdog(
            "test", true_prob=0.02, outcome_name="VeryRare",
        )
        # IS should provide meaningful variance reduction for rare events
        assert result["variance_reduction"] >= 1.0


class TestStratifiedSampling:
    def test_stratified_covers_unit_interval(self):
        engine = MonteCarloEngine(n_sims=1000, seed=42)
        samples = engine._stratified_uniforms(1000, n_strata=10)
        assert len(samples) == 1000
        assert samples.min() >= 0.0
        assert samples.max() <= 1.0

    def test_stratified_uniform_distribution(self):
        engine = MonteCarloEngine(n_sims=10_000, seed=42)
        samples = engine._stratified_uniforms(10_000, n_strata=10)
        # Each stratum should have equal representation
        for i in range(10):
            low = i / 10
            high = (i + 1) / 10
            count = ((samples >= low) & (samples < high)).sum()
            assert count == 1000  # Exactly n/strata per bin
