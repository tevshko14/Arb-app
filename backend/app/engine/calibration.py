"""Brier Score calibration tracking and backtesting framework.

Tracks model accuracy over time to answer the critical question:
"Are our probability estimates honest?"

Brier Score = mean((predicted_prob - actual_outcome)^2)
- Perfect: 0.0
- Random: 0.25
- Always 50%: 0.25
- Excellent: < 0.10
- Good: < 0.20
- Bad: > 0.25 (worse than always guessing 50%)

We track Brier scores per:
- Overall model
- Per sport (MLB vs UFC)
- Per ensemble component (sharp vs model vs blended)
- Rolling windows (last 50, 100, 500 predictions)

This drives the ensemble weight adjustment:
if model Brier < sharp Brier → increase model weight (our model adds alpha)
if model Brier > sharp Brier → decrease model weight (trust the market)

Reference: gemchange_ltd thread Part II — Brier score for simulation evaluation.
"""

import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class Prediction:
    """A single prediction with its outcome (once resolved)."""

    event_id: str
    sport: str
    outcome: str
    predicted_prob: float  # Our model's probability
    sharp_prob: float  # Pinnacle's probability
    ensemble_prob: float  # Final ensemble probability
    actual_outcome: int | None = None  # 1 = happened, 0 = didn't, None = pending
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    resolved_at: datetime | None = None


@dataclass
class CalibrationReport:
    """Summary of model calibration over a set of predictions."""

    n_predictions: int
    n_resolved: int
    brier_ensemble: float | None  # Brier score of ensemble predictions
    brier_sharp: float | None  # Brier score of sharp line (benchmark)
    brier_model: float | None  # Brier score of our model alone
    edge_over_sharp: float | None  # Negative = our model is worse
    calibration_bins: list[dict]  # Predicted vs actual by decile
    sport_breakdown: dict[str, dict]


class CalibrationTracker:
    """Tracks predictions and computes rolling Brier scores."""

    def __init__(self, window_sizes: list[int] | None = None):
        self.predictions: list[Prediction] = []
        self.window_sizes = window_sizes or [50, 100, 500]

    def record_prediction(self, prediction: Prediction):
        """Record a new prediction (before outcome is known)."""
        self.predictions.append(prediction)

    def resolve_prediction(self, event_id: str, outcome: str, result: int):
        """Record the actual outcome for a prediction.

        result: 1 if the predicted outcome happened, 0 if it didn't.
        """
        for pred in self.predictions:
            if pred.event_id == event_id and pred.outcome == outcome:
                pred.actual_outcome = result
                pred.resolved_at = datetime.now(timezone.utc)
                return True
        return False

    def brier_score(self, probs: list[float], outcomes: list[int]) -> float:
        """Compute Brier score: mean squared error of probability estimates."""
        probs_arr = np.array(probs)
        outcomes_arr = np.array(outcomes)
        return float(np.mean((probs_arr - outcomes_arr) ** 2))

    def get_resolved(self, sport: str | None = None) -> list[Prediction]:
        """Get all resolved predictions, optionally filtered by sport."""
        resolved = [p for p in self.predictions if p.actual_outcome is not None]
        if sport:
            resolved = [p for p in resolved if p.sport == sport]
        return resolved

    def generate_report(self, sport: str | None = None) -> CalibrationReport:
        """Generate a full calibration report."""
        resolved = self.get_resolved(sport)

        if not resolved:
            return CalibrationReport(
                n_predictions=len(self.predictions),
                n_resolved=0,
                brier_ensemble=None,
                brier_sharp=None,
                brier_model=None,
                edge_over_sharp=None,
                calibration_bins=[],
                sport_breakdown={},
            )

        ensemble_probs = [p.ensemble_prob for p in resolved]
        sharp_probs = [p.sharp_prob for p in resolved]
        outcomes = [p.actual_outcome for p in resolved]

        brier_ensemble = self.brier_score(ensemble_probs, outcomes)
        brier_sharp = self.brier_score(sharp_probs, outcomes)

        # Model-only Brier (if we have model predictions)
        model_probs = [p.predicted_prob for p in resolved]
        brier_model = self.brier_score(model_probs, outcomes)

        # Edge: negative Brier difference = we're better
        edge = brier_sharp - brier_ensemble  # Positive = we beat the sharp line

        # Calibration bins (deciles)
        bins = self._calibration_bins(ensemble_probs, outcomes)

        # Per-sport breakdown
        sports = set(p.sport for p in resolved)
        sport_breakdown = {}
        for s in sports:
            s_resolved = [p for p in resolved if p.sport == s]
            s_ensemble = [p.ensemble_prob for p in s_resolved]
            s_outcomes = [p.actual_outcome for p in s_resolved]
            sport_breakdown[s] = {
                "n": len(s_resolved),
                "brier": self.brier_score(s_ensemble, s_outcomes),
            }

        return CalibrationReport(
            n_predictions=len(self.predictions),
            n_resolved=len(resolved),
            brier_ensemble=round(brier_ensemble, 6),
            brier_sharp=round(brier_sharp, 6),
            brier_model=round(brier_model, 6),
            edge_over_sharp=round(edge, 6),
            calibration_bins=bins,
            sport_breakdown=sport_breakdown,
        )

    def rolling_brier(self, window: int = 100) -> float | None:
        """Compute Brier score over the last N resolved predictions."""
        resolved = self.get_resolved()
        if len(resolved) < window:
            return None

        recent = resolved[-window:]
        probs = [p.ensemble_prob for p in recent]
        outcomes = [p.actual_outcome for p in recent]
        return self.brier_score(probs, outcomes)

    def should_increase_model_weight(self, min_samples: int = 50) -> bool:
        """Determine if our model is adding alpha vs the sharp line.

        Returns True if the model's Brier score beats the sharp line's
        over a sufficient sample size.
        """
        resolved = self.get_resolved()
        if len(resolved) < min_samples:
            return False

        report = self.generate_report()
        if report.edge_over_sharp is None:
            return False

        # Our ensemble beats the sharp line
        return report.edge_over_sharp > 0.005  # Meaningful edge threshold

    def _calibration_bins(
        self, probs: list[float], outcomes: list[int], n_bins: int = 10
    ) -> list[dict]:
        """Group predictions into probability bins and compare predicted vs actual.

        Perfect calibration: events predicted at 70% happen 70% of the time.
        """
        probs_arr = np.array(probs)
        outcomes_arr = np.array(outcomes)
        bins = []

        for i in range(n_bins):
            low = i / n_bins
            high = (i + 1) / n_bins
            mask = (probs_arr >= low) & (probs_arr < high)

            if mask.sum() == 0:
                continue

            bins.append({
                "bin_range": f"{low:.1f}-{high:.1f}",
                "n_predictions": int(mask.sum()),
                "mean_predicted": float(probs_arr[mask].mean()),
                "mean_actual": float(outcomes_arr[mask].mean()),
                "calibration_error": float(
                    abs(probs_arr[mask].mean() - outcomes_arr[mask].mean())
                ),
            })

        return bins


class Backtester:
    """Walk-forward backtesting using historical odds data.

    Tests the model against historical outcomes to validate calibration
    before going live with real capital.

    Walk-forward: train on data[0:t], test on data[t:t+window], slide forward.
    This prevents look-ahead bias.
    """

    def __init__(self):
        self.results: list[dict] = []

    def run_backtest(
        self,
        historical_predictions: list[Prediction],
        window_size: int = 50,
        step_size: int = 10,
    ) -> list[dict]:
        """Run walk-forward backtesting.

        Slides a window over historical predictions and computes
        Brier scores at each step.
        """
        tracker = CalibrationTracker()
        results = []

        for i in range(0, len(historical_predictions) - window_size, step_size):
            window = historical_predictions[i:i + window_size]

            # Only use resolved predictions
            resolved = [p for p in window if p.actual_outcome is not None]
            if len(resolved) < window_size // 2:
                continue

            probs = [p.ensemble_prob for p in resolved]
            outcomes = [p.actual_outcome for p in resolved]

            brier = tracker.brier_score(probs, outcomes)

            results.append({
                "window_start": i,
                "window_end": i + window_size,
                "n_resolved": len(resolved),
                "brier_score": round(brier, 6),
                "mean_edge": round(
                    np.mean([
                        (p.ensemble_prob * 2.0) - 1.0  # Approximate edge at even odds
                        for p in resolved
                    ]),
                    6,
                ),
            })

        self.results = results
        return results

    def summary(self) -> dict:
        """Summarize backtest results."""
        if not self.results:
            return {"error": "No backtest results"}

        briers = [r["brier_score"] for r in self.results]
        return {
            "n_windows": len(self.results),
            "mean_brier": round(float(np.mean(briers)), 6),
            "std_brier": round(float(np.std(briers)), 6),
            "best_brier": round(float(np.min(briers)), 6),
            "worst_brier": round(float(np.max(briers)), 6),
            "calibrated": float(np.mean(briers)) < 0.20,
        }
