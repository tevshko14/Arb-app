"""Ensemble scoring — combines multiple probability sources into one.

The ensemble weights multiple model outputs:
1. Sharp line (Pinnacle implied probability) — the market's best estimate
2. Sport-specific MC model (Poisson/Elo) — our independent estimate
3. Bayesian fallback — regresses toward 50% when sample sizes are small

Early in the system's life, we weight heavily toward the sharp line.
As our sport-specific model proves calibrated (via Brier score), we shift
weight toward it — this is where real alpha comes from.

Weight formula:
    P_ensemble = w_sharp * P_sharp + w_model * P_model + w_prior * P_prior

Where w_sharp + w_model + w_prior = 1.0
"""

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class EnsembleWeights:
    """Weights for each probability source in the ensemble."""

    sharp: float = 0.55  # Pinnacle implied (vig-removed)
    model: float = 0.35  # Our sport-specific MC model
    prior: float = 0.10  # Bayesian prior (shrinkage toward 50%)

    def __post_init__(self):
        total = self.sharp + self.model + self.prior
        if abs(total - 1.0) > 0.001:
            # Normalize
            self.sharp /= total
            self.model /= total
            self.prior /= total


# Default weights — conservative, trusts the sharp market
DEFAULT_WEIGHTS = EnsembleWeights(sharp=0.55, model=0.35, prior=0.10)

# After model calibration proves Brier < 0.15
CALIBRATED_WEIGHTS = EnsembleWeights(sharp=0.35, model=0.55, prior=0.10)

# Bayesian fallback only (no model, no sharp data)
FALLBACK_WEIGHTS = EnsembleWeights(sharp=0.0, model=0.0, prior=1.0)


@dataclass
class EnsembleResult:
    """Output of ensemble scoring for one event."""

    event_id: str
    outcome_probs: dict[str, float]  # Final blended probabilities
    sharp_probs: dict[str, float]  # What the sharp market says
    model_probs: dict[str, float]  # What our model says
    prior_probs: dict[str, float]  # Bayesian prior
    weights: EnsembleWeights
    disagreement: float  # How much sharp and model disagree (0-1)


def bayesian_prior(n_outcomes: int = 2) -> dict[str, float]:
    """Uninformative prior — uniform across outcomes.

    With small sample sizes or no model data, we regress toward
    equal probability. This prevents overconfident bets on thin data.
    """
    p = 1.0 / n_outcomes
    return {f"outcome_{i}": p for i in range(n_outcomes)}


def blend_probabilities(
    sharp_probs: dict[str, float],
    model_probs: dict[str, float],
    weights: EnsembleWeights | None = None,
    prior_probs: dict[str, float] | None = None,
) -> dict[str, float]:
    """Blend probability estimates from multiple sources.

    All input dicts must have the same keys. Output sums to 1.0.
    """
    if weights is None:
        weights = DEFAULT_WEIGHTS

    outcomes = set(sharp_probs.keys()) | set(model_probs.keys())

    if prior_probs is None:
        prior_probs = {o: 1.0 / len(outcomes) for o in outcomes}

    blended = {}
    for outcome in outcomes:
        p_sharp = sharp_probs.get(outcome, 0.5)
        p_model = model_probs.get(outcome, 0.5)
        p_prior = prior_probs.get(outcome, 1.0 / len(outcomes))

        blended[outcome] = (
            weights.sharp * p_sharp
            + weights.model * p_model
            + weights.prior * p_prior
        )

    # Normalize to sum to 1.0
    total = sum(blended.values())
    if total > 0:
        blended = {o: p / total for o, p in blended.items()}

    return blended


def calculate_disagreement(
    sharp_probs: dict[str, float],
    model_probs: dict[str, float],
) -> float:
    """Measure how much the sharp market and our model disagree.

    Returns a value in [0, 1]:
    - 0 = perfect agreement
    - 1 = maximum disagreement (one says 100%, other says 0%)

    Uses mean absolute difference across outcomes.
    High disagreement = either our model found alpha, or it's wrong.
    Track via Brier score to determine which.
    """
    outcomes = set(sharp_probs.keys()) & set(model_probs.keys())
    if not outcomes:
        return 0.0

    diffs = [abs(sharp_probs[o] - model_probs[o]) for o in outcomes]
    return sum(diffs) / len(diffs)


def score_event(
    event_id: str,
    sharp_probs: dict[str, float],
    model_probs: dict[str, float],
    weights: EnsembleWeights | None = None,
) -> EnsembleResult:
    """Full ensemble scoring for one event.

    Combines sharp line, model output, and Bayesian prior into
    a single probability estimate per outcome.
    """
    if weights is None:
        weights = DEFAULT_WEIGHTS

    outcomes = set(sharp_probs.keys()) | set(model_probs.keys())
    prior = {o: 1.0 / len(outcomes) for o in outcomes}

    blended = blend_probabilities(sharp_probs, model_probs, weights, prior)
    disagreement = calculate_disagreement(sharp_probs, model_probs)

    if disagreement > 0.10:
        logger.info(
            "Event %s: model disagrees with sharp by %.1f%% — potential alpha or miscalibration",
            event_id,
            disagreement * 100,
        )

    return EnsembleResult(
        event_id=event_id,
        outcome_probs=blended,
        sharp_probs=sharp_probs,
        model_probs=model_probs,
        prior_probs=prior,
        weights=weights,
        disagreement=disagreement,
    )
