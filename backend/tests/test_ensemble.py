"""Tests for the ensemble scoring engine."""

import pytest

from app.engine.ensemble import (
    EnsembleWeights,
    blend_probabilities,
    calculate_disagreement,
    score_event,
    DEFAULT_WEIGHTS,
)


class TestEnsembleWeights:
    def test_default_weights_sum_to_one(self):
        w = DEFAULT_WEIGHTS
        assert w.sharp + w.model + w.prior == pytest.approx(1.0)

    def test_auto_normalization(self):
        w = EnsembleWeights(sharp=2.0, model=2.0, prior=1.0)
        assert w.sharp + w.model + w.prior == pytest.approx(1.0)
        assert w.sharp == pytest.approx(0.4)


class TestBlendProbabilities:
    def test_equal_inputs_give_equal_outputs(self):
        sharp = {"home": 0.60, "away": 0.40}
        model = {"home": 0.60, "away": 0.40}
        blended = blend_probabilities(sharp, model)
        assert blended["home"] == pytest.approx(0.58, abs=0.05)  # Prior pulls toward 0.5

    def test_sums_to_one(self):
        sharp = {"home": 0.70, "away": 0.30}
        model = {"home": 0.55, "away": 0.45}
        blended = blend_probabilities(sharp, model)
        assert sum(blended.values()) == pytest.approx(1.0)

    def test_model_weight_shifts_result(self):
        sharp = {"home": 0.60, "away": 0.40}
        model = {"home": 0.80, "away": 0.20}

        # Heavy sharp weight
        w_sharp = EnsembleWeights(sharp=0.9, model=0.05, prior=0.05)
        blended_sharp = blend_probabilities(sharp, model, w_sharp)

        # Heavy model weight
        w_model = EnsembleWeights(sharp=0.05, model=0.9, prior=0.05)
        blended_model = blend_probabilities(sharp, model, w_model)

        # Sharp-weighted should be closer to 0.60
        assert blended_sharp["home"] < blended_model["home"]

    def test_prior_pulls_toward_50(self):
        sharp = {"home": 0.90, "away": 0.10}
        model = {"home": 0.90, "away": 0.10}
        w = EnsembleWeights(sharp=0.0, model=0.0, prior=1.0)
        blended = blend_probabilities(sharp, model, w)
        assert blended["home"] == pytest.approx(0.50)


class TestDisagreement:
    def test_perfect_agreement(self):
        d = calculate_disagreement(
            {"home": 0.60, "away": 0.40},
            {"home": 0.60, "away": 0.40},
        )
        assert d == 0.0

    def test_total_disagreement(self):
        d = calculate_disagreement(
            {"home": 1.0, "away": 0.0},
            {"home": 0.0, "away": 1.0},
        )
        assert d == pytest.approx(1.0)

    def test_moderate_disagreement(self):
        d = calculate_disagreement(
            {"home": 0.60, "away": 0.40},
            {"home": 0.70, "away": 0.30},
        )
        assert d == pytest.approx(0.10)

    def test_empty_returns_zero(self):
        assert calculate_disagreement({}, {}) == 0.0


class TestScoreEvent:
    def test_returns_all_fields(self):
        result = score_event(
            event_id="test123",
            sharp_probs={"A": 0.55, "B": 0.45},
            model_probs={"A": 0.60, "B": 0.40},
        )
        assert result.event_id == "test123"
        assert "A" in result.outcome_probs
        assert "B" in result.outcome_probs
        assert sum(result.outcome_probs.values()) == pytest.approx(1.0)
        assert result.disagreement >= 0

    def test_high_disagreement_detected(self):
        result = score_event(
            event_id="test",
            sharp_probs={"A": 0.50, "B": 0.50},
            model_probs={"A": 0.80, "B": 0.20},
        )
        assert result.disagreement > 0.10
