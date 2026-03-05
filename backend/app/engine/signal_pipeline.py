"""Signal pipeline — orchestrates the full analysis for one event.

Flow:
1. Fetch latest odds from database
2. Extract sharp (Pinnacle) implied probabilities
3. Run sport-specific Monte Carlo simulation
4. Blend via ensemble scorer
5. Calculate edge against each soft bookmaker
6. Size bets via Kelly Criterion
7. Record prediction for calibration tracking

This is the "main loop" of The Brain.
"""

import logging
from dataclasses import dataclass

from app.engine.edge import (
    EdgeSignal,
    EventOdds,
    find_edges,
    implied_probability,
    remove_vig,
)
from app.engine.ensemble import EnsembleWeights, score_event
from app.engine.kelly import KellyRecommendation, recommend_bet, size_portfolio
from app.engine.calibration import CalibrationTracker, Prediction

logger = logging.getLogger(__name__)


@dataclass
class SignalOutput:
    """Complete output for one event — the "Daily Golden Play" data."""

    event_id: str
    sport: str
    home_team: str
    away_team: str
    ensemble_probs: dict[str, float]
    sharp_probs: dict[str, float]
    model_probs: dict[str, float]
    disagreement: float
    signals: list[EdgeSignal]
    kelly_recommendations: list[KellyRecommendation]


class SignalPipeline:
    """Runs the full analysis pipeline for events."""

    def __init__(
        self,
        bankroll: float = 1000.0,
        kelly_multiplier: float = 0.5,
        min_edge: float = 0.02,
        weights: EnsembleWeights | None = None,
        calibration_tracker: CalibrationTracker | None = None,
    ):
        self.bankroll = bankroll
        self.kelly_multiplier = kelly_multiplier
        self.min_edge = min_edge
        self.weights = weights
        self.tracker = calibration_tracker or CalibrationTracker()

    def analyze_event(
        self,
        event: EventOdds,
        model_probs: dict[str, float],
    ) -> SignalOutput:
        """Run the full pipeline for a single event.

        Args:
            event: All odds across bookmakers (from database/cache).
            model_probs: Our sport-specific model's probability estimates.

        Returns:
            SignalOutput with edge signals and Kelly recommendations.
        """
        # Step 1: Extract sharp probabilities (Pinnacle, vig-removed)
        sharp_raw = {}
        if event.sharp_book in event.odds:
            for outcome, odds in event.odds[event.sharp_book].items():
                sharp_raw[outcome] = implied_probability(odds)
        sharp_probs = remove_vig(sharp_raw) if sharp_raw else model_probs

        # Step 2: Ensemble blend
        ensemble_result = score_event(
            event_id=event.event_id,
            sharp_probs=sharp_probs,
            model_probs=model_probs,
            weights=self.weights,
        )

        # Step 3: Find edges
        signals = find_edges(
            event=event,
            model_probs=ensemble_result.outcome_probs,
            min_edge=self.min_edge,
        )

        # Step 4: Kelly sizing for each signal
        recommendations = []
        for signal in signals:
            rec = recommend_bet(
                event_id=signal.event_id,
                outcome=signal.outcome,
                bookmaker=signal.bookmaker,
                model_prob=signal.model_prob,
                decimal_odds=signal.decimal_odds,
                bankroll=self.bankroll,
                kelly_multiplier=self.kelly_multiplier,
            )
            if rec:
                signal.kelly_fraction = rec.adjusted_kelly_fraction
                signal.recommended_stake = rec.recommended_stake
                recommendations.append(rec)

        # Step 5: Portfolio sizing (cap total exposure)
        recommendations = size_portfolio(recommendations)

        # Step 6: Record predictions for calibration
        for outcome, prob in ensemble_result.outcome_probs.items():
            self.tracker.record_prediction(
                Prediction(
                    event_id=event.event_id,
                    sport=event.sport,
                    outcome=outcome,
                    predicted_prob=model_probs.get(outcome, 0.5),
                    sharp_prob=sharp_probs.get(outcome, 0.5),
                    ensemble_prob=prob,
                )
            )

        if signals:
            logger.info(
                "Event %s (%s vs %s): %d signals, best edge %.1f%%, total stake $%.2f",
                event.event_id,
                event.home_team,
                event.away_team,
                len(signals),
                signals[0].edge * 100 if signals else 0,
                sum(r.recommended_stake for r in recommendations),
            )

        return SignalOutput(
            event_id=event.event_id,
            sport=event.sport,
            home_team=event.home_team,
            away_team=event.away_team,
            ensemble_probs=ensemble_result.outcome_probs,
            sharp_probs=sharp_probs,
            model_probs=model_probs,
            disagreement=ensemble_result.disagreement,
            signals=signals,
            kelly_recommendations=recommendations,
        )

    def update_bankroll(self, new_bankroll: float):
        """Update the bankroll for Kelly calculations."""
        self.bankroll = new_bankroll
        logger.info("Bankroll updated to $%.2f", new_bankroll)

    def get_calibration_report(self):
        """Get the current calibration report."""
        return self.tracker.generate_report()
