"""Kelly Criterion bet sizing engine.

Calculates the mathematically optimal bet size to maximize long-term
bankroll growth while controlling for risk of ruin.

Full Kelly: f* = (p * b - q) / b
Where:
    p = model probability of winning
    q = 1 - p (probability of losing)
    b = decimal odds - 1 (net payout per unit staked)

We use Half Kelly (0.5x) by default — standard for professional bettors.
This reduces variance by ~50% while sacrificing only ~25% of growth rate.

Fractional Kelly is the industry standard because:
1. Model probabilities have estimation error
2. Full Kelly has brutal drawdowns (~40% drawdown is common)
3. Half Kelly achieves 75% of full Kelly growth with much smoother equity curve

Reference: Kelly (1956), Thorp (2006), gemchange_ltd thread Part VIII
"""

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Bet sizing constraints
MIN_EDGE_TO_BET = 0.02  # Don't bet with < 2% edge
MAX_STAKE_FRACTION = 0.05  # Never risk more than 5% of bankroll on one bet
MIN_STAKE_FRACTION = 0.005  # Minimum 0.5% of bankroll to bother


@dataclass
class KellyRecommendation:
    """Output of the Kelly Criterion calculator."""

    event_id: str
    outcome: str
    bookmaker: str
    decimal_odds: float
    model_prob: float
    edge: float
    full_kelly_fraction: float  # Optimal fraction of bankroll
    adjusted_kelly_fraction: float  # After applying Kelly multiplier
    recommended_stake: float  # Actual dollar amount
    bankroll: float
    kelly_multiplier: float  # 0.5 for half Kelly
    capped: bool  # True if stake was capped at MAX_STAKE_FRACTION


def full_kelly(prob: float, decimal_odds: float) -> float:
    """Calculate the full Kelly fraction.

    f* = (p * b - q) / b

    Where b = decimal_odds - 1 (net payout).
    Returns 0 if the bet has negative expected value.
    """
    b = decimal_odds - 1.0
    q = 1.0 - prob

    if b <= 0:
        return 0.0

    f = (prob * b - q) / b

    # Negative Kelly = negative EV, don't bet
    return max(0.0, f)


def fractional_kelly(
    prob: float,
    decimal_odds: float,
    multiplier: float = 0.5,
) -> float:
    """Calculate fractional Kelly stake as a fraction of bankroll.

    multiplier=0.5 → Half Kelly (default, recommended)
    multiplier=0.25 → Quarter Kelly (very conservative)
    multiplier=1.0 → Full Kelly (aggressive, not recommended)
    """
    f = full_kelly(prob, decimal_odds)
    return f * multiplier


def recommend_bet(
    event_id: str,
    outcome: str,
    bookmaker: str,
    model_prob: float,
    decimal_odds: float,
    bankroll: float,
    kelly_multiplier: float = 0.5,
) -> KellyRecommendation | None:
    """Generate a Kelly-based bet recommendation.

    Returns None if the edge is below minimum threshold or Kelly fraction is 0.
    """
    edge = (model_prob * decimal_odds) - 1.0

    if edge < MIN_EDGE_TO_BET:
        return None

    f_full = full_kelly(model_prob, decimal_odds)
    f_adjusted = f_full * kelly_multiplier

    if f_adjusted < MIN_STAKE_FRACTION:
        return None

    # Cap at maximum stake fraction
    capped = f_adjusted > MAX_STAKE_FRACTION
    f_final = min(f_adjusted, MAX_STAKE_FRACTION)

    stake = f_final * bankroll

    logger.info(
        "Kelly recommendation: %s @ %s — %.1f%% edge, %.2f%% of bankroll ($%.2f)%s",
        outcome,
        bookmaker,
        edge * 100,
        f_final * 100,
        stake,
        " [CAPPED]" if capped else "",
    )

    return KellyRecommendation(
        event_id=event_id,
        outcome=outcome,
        bookmaker=bookmaker,
        decimal_odds=decimal_odds,
        model_prob=model_prob,
        edge=edge,
        full_kelly_fraction=f_full,
        adjusted_kelly_fraction=f_final,
        recommended_stake=round(stake, 2),
        bankroll=bankroll,
        kelly_multiplier=kelly_multiplier,
        capped=capped,
    )


def size_portfolio(
    recommendations: list[KellyRecommendation],
    max_total_exposure: float = 0.20,
) -> list[KellyRecommendation]:
    """Adjust a batch of Kelly recommendations so total exposure doesn't exceed limit.

    If the sum of all recommended stakes exceeds max_total_exposure * bankroll,
    scale them down proportionally.

    This prevents over-betting when many +EV signals fire simultaneously.
    """
    if not recommendations:
        return []

    bankroll = recommendations[0].bankroll
    total_fraction = sum(r.adjusted_kelly_fraction for r in recommendations)

    if total_fraction <= max_total_exposure:
        return recommendations

    # Scale down proportionally
    scale_factor = max_total_exposure / total_fraction
    logger.warning(
        "Portfolio exposure %.1f%% exceeds limit %.1f%% — scaling by %.2fx",
        total_fraction * 100,
        max_total_exposure * 100,
        scale_factor,
    )

    scaled = []
    for r in recommendations:
        new_fraction = r.adjusted_kelly_fraction * scale_factor
        scaled.append(
            KellyRecommendation(
                event_id=r.event_id,
                outcome=r.outcome,
                bookmaker=r.bookmaker,
                decimal_odds=r.decimal_odds,
                model_prob=r.model_prob,
                edge=r.edge,
                full_kelly_fraction=r.full_kelly_fraction,
                adjusted_kelly_fraction=new_fraction,
                recommended_stake=round(new_fraction * bankroll, 2),
                bankroll=bankroll,
                kelly_multiplier=r.kelly_multiplier,
                capped=r.capped,
            )
        )

    return scaled
