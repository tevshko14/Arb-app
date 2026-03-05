"""Signal pipeline — orchestrates the full analysis for one event.

Flow:
1. Fetch latest odds from database
2. Extract sharp (Pinnacle) implied probabilities
3. Run sport-specific Monte Carlo simulation
4. Blend via ensemble scorer
5. Calculate edge against each soft bookmaker
6. Size bets via Kelly Criterion (dynamic multiplier from Risk Manager)
7. Apply humanization (stake noise, timing, bookmaker rotation)
8. Record prediction for calibration tracking
9. Track CLV for signal quality measurement

This is the "main loop" of The Brain.
"""

import logging
from dataclasses import dataclass, field

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
from app.engine.risk_manager import RiskManager, BetRecord
from app.engine.clv_tracker import CLVTracker
from app.engine.humanizer import Humanizer, HumanizedBet, HumanizerConfig
from app.engine.line_movement import LineMovementTracker, MarketSnapshot

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
    humanized_bets: list[HumanizedBet] = field(default_factory=list)
    risk_level: str = "normal"
    stale_lines_found: int = 0


class SignalPipeline:
    """Runs the full analysis pipeline for events."""

    def __init__(
        self,
        bankroll: float = 1000.0,
        kelly_multiplier: float = 0.5,
        min_edge: float = 0.02,
        weights: EnsembleWeights | None = None,
        calibration_tracker: CalibrationTracker | None = None,
        risk_manager: RiskManager | None = None,
        clv_tracker: CLVTracker | None = None,
        humanizer: Humanizer | None = None,
        line_tracker: LineMovementTracker | None = None,
    ):
        self.bankroll = bankroll
        self.kelly_multiplier = kelly_multiplier
        self.min_edge = min_edge
        self.weights = weights
        self.tracker = calibration_tracker or CalibrationTracker()
        self.risk_manager = risk_manager or RiskManager(initial_bankroll=bankroll)
        self.clv_tracker = clv_tracker or CLVTracker()
        self.humanizer = humanizer or Humanizer()
        self.line_tracker = line_tracker or LineMovementTracker()

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
            SignalOutput with edge signals, Kelly recommendations,
            humanized bets, and risk state.
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

        # Step 3b: Check for stale lines (InfoFi scanner)
        stale_lines = self.line_tracker.find_stale_lines(event.event_id)

        # Step 4: Dynamic Kelly sizing (risk-adjusted)
        rm = self.risk_manager
        kelly_mult = rm.kelly_multiplier
        max_stake = rm.max_stake_fraction
        max_portfolio = rm.max_portfolio_exposure

        recommendations = []
        for signal in signals:
            # Check risk manager approval
            proposed_stake = signal.model_prob * 0.05 * rm.current_bankroll  # Rough estimate
            allowed, reason = rm.can_place_bet(proposed_stake, signal.bookmaker)
            if not allowed:
                logger.info("Bet blocked by risk manager: %s — %s", signal.outcome, reason)
                continue

            rec = recommend_bet(
                event_id=signal.event_id,
                outcome=signal.outcome,
                bookmaker=signal.bookmaker,
                model_prob=signal.model_prob,
                decimal_odds=signal.decimal_odds,
                bankroll=rm.current_bankroll,
                kelly_multiplier=kelly_mult,
            )
            if rec:
                signal.kelly_fraction = rec.adjusted_kelly_fraction
                signal.recommended_stake = rec.recommended_stake
                recommendations.append(rec)

        # Step 5: Portfolio sizing (dynamic cap from risk manager)
        recommendations = size_portfolio(recommendations, max_total_exposure=max_portfolio)

        # Step 6: Humanize bets
        humanized = []
        for rec in recommendations:
            h = self.humanizer.humanize_bet(
                event_id=rec.event_id,
                outcome=rec.outcome,
                bookmaker=rec.bookmaker,
                stake=rec.recommended_stake,
            )
            humanized.append(h)

        # Step 7: Record predictions for calibration
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

        # Step 8: Record signals for CLV tracking
        for signal in signals:
            sharp_odds = event.odds.get(event.sharp_book, {}).get(signal.outcome)
            self.clv_tracker.record_signal(
                event_id=signal.event_id,
                sport=signal.sport,
                bookmaker=signal.bookmaker,
                outcome=signal.outcome,
                signal_odds=signal.decimal_odds,
                signal_model_prob=signal.model_prob,
                signal_edge=signal.edge,
                sharp_odds=sharp_odds,
            )

        if signals:
            logger.info(
                "Event %s (%s vs %s): %d signals, best edge %.1f%%, "
                "total stake $%.2f, risk: %s, stale lines: %d",
                event.event_id,
                event.home_team,
                event.away_team,
                len(signals),
                signals[0].edge * 100 if signals else 0,
                sum(r.recommended_stake for r in recommendations),
                rm.risk_level.value,
                len(stale_lines),
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
            humanized_bets=humanized,
            risk_level=rm.risk_level.value,
            stale_lines_found=len(stale_lines),
        )

    def update_bankroll(self, new_bankroll: float):
        """Update the bankroll for Kelly calculations."""
        self.bankroll = new_bankroll
        self.risk_manager.update_bankroll(new_bankroll)
        logger.info("Bankroll updated to $%.2f", new_bankroll)

    def get_calibration_report(self):
        """Get the current calibration report."""
        return self.tracker.generate_report()

    def get_risk_state(self):
        """Get the current risk state snapshot."""
        return self.risk_manager.get_state()

    def get_clv_report(self):
        """Get the CLV tracking report."""
        return self.clv_tracker.generate_report()
