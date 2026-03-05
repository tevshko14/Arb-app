"""Edge (Alpha) calculation engine.

Identifies Positive Expected Value (+EV) opportunities by comparing
model probabilities against bookmaker-implied probabilities.

Edge = (Model_Probability × Decimal_Odds) - 1

An edge > 0 means the bet has positive expected value.
"""

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class EdgeSignal:
    """A single +EV signal for one outcome at one bookmaker."""

    event_id: str
    sport: str
    home_team: str
    away_team: str
    bookmaker: str
    market: str
    outcome: str
    decimal_odds: float
    implied_prob: float  # What the bookmaker's odds imply
    model_prob: float  # What our model says
    sharp_prob: float  # What Pinnacle (sharp) says
    edge: float  # (model_prob * decimal_odds) - 1
    edge_vs_sharp: float  # How far the soft book deviates from sharp
    confidence: float  # 0-1, how confident the model is
    kelly_fraction: float = 0.0  # Filled in by Kelly engine
    recommended_stake: float = 0.0


@dataclass
class EventOdds:
    """All odds for a single event across bookmakers."""

    event_id: str
    sport: str
    home_team: str
    away_team: str
    # {bookmaker_key: {outcome_name: decimal_odds}}
    odds: dict[str, dict[str, float]] = field(default_factory=dict)
    sharp_book: str = "pinnacle"


def implied_probability(decimal_odds: float) -> float:
    """Convert decimal odds to implied probability.

    Decimal odds of 2.00 = 50% implied probability.
    Includes the bookmaker's vig/margin.
    """
    if decimal_odds <= 1.0:
        return 1.0
    return 1.0 / decimal_odds


def remove_vig(probs: dict[str, float]) -> dict[str, float]:
    """Remove the bookmaker's overround (vig) from implied probabilities.

    The sum of raw implied probs > 1.0 (the excess is the vig).
    We normalize to sum to 1.0 to get 'fair' probabilities.

    Example: odds of 1.90 / 1.90 imply 52.6% + 52.6% = 105.2%
    After removing vig: 50% / 50%.
    """
    total = sum(probs.values())
    if total == 0:
        return probs
    return {outcome: p / total for outcome, p in probs.items()}


def calculate_edge(model_prob: float, decimal_odds: float) -> float:
    """Calculate the edge (expected value) of a bet.

    Edge = (model_probability × decimal_odds) - 1

    Positive edge = profitable bet over time.
    Negative edge = losing bet over time.
    """
    return (model_prob * decimal_odds) - 1.0


def find_edges(
    event: EventOdds,
    model_probs: dict[str, float],
    min_edge: float = 0.02,
    min_confidence: float = 0.5,
    confidence: float = 0.8,
) -> list[EdgeSignal]:
    """Find all +EV opportunities for an event.

    Compares model probabilities against each soft bookmaker's odds.
    Only returns signals where edge >= min_edge.

    Args:
        event: All odds for the event across bookmakers.
        model_probs: Our model's probability for each outcome (should sum to ~1.0).
        min_edge: Minimum edge to report (default 2%).
        min_confidence: Minimum model confidence to report.
        confidence: Model confidence score.

    Returns:
        List of EdgeSignal objects, sorted by edge descending.
    """
    signals: list[EdgeSignal] = []

    # Get sharp (Pinnacle) implied probs for comparison
    sharp_raw_probs = {}
    if event.sharp_book in event.odds:
        for outcome, odds in event.odds[event.sharp_book].items():
            sharp_raw_probs[outcome] = implied_probability(odds)
    sharp_probs = remove_vig(sharp_raw_probs) if sharp_raw_probs else {}

    for bookmaker, outcomes in event.odds.items():
        # Skip the sharp book itself — we're looking for soft book edges
        if bookmaker == event.sharp_book:
            continue

        for outcome, decimal_odds in outcomes.items():
            model_prob = model_probs.get(outcome, 0.0)
            if model_prob <= 0:
                continue

            edge = calculate_edge(model_prob, decimal_odds)
            implied = implied_probability(decimal_odds)
            sharp_prob = sharp_probs.get(outcome, implied)
            edge_vs_sharp = (sharp_prob * decimal_odds) - 1.0

            if edge >= min_edge and confidence >= min_confidence:
                signals.append(
                    EdgeSignal(
                        event_id=event.event_id,
                        sport=event.sport,
                        home_team=event.home_team,
                        away_team=event.away_team,
                        bookmaker=bookmaker,
                        market="h2h",
                        outcome=outcome,
                        decimal_odds=decimal_odds,
                        implied_prob=implied,
                        model_prob=model_prob,
                        sharp_prob=sharp_prob,
                        edge=edge,
                        edge_vs_sharp=edge_vs_sharp,
                        confidence=confidence,
                    )
                )

    signals.sort(key=lambda s: s.edge, reverse=True)

    if signals:
        logger.info(
            "Found %d +EV signals for %s vs %s (best edge: %.1f%%)",
            len(signals),
            event.home_team,
            event.away_team,
            signals[0].edge * 100,
        )

    return signals
