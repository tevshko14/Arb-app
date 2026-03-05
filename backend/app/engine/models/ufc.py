"""UFC/MMA-specific Monte Carlo model.

Uses an Elo-based system combined with fighter stats to estimate
win probability in MMA bouts.

Key factors:
- Elo rating differential (base probability)
- Significant strike differential (volume + accuracy)
- Takedown differential (grappling advantage)
- Finish rate (KO/Sub likelihood affects probability distribution)
- Reach/height advantage (minor factor)

The Elo system provides the baseline; stats adjustments shift it.
"""

import logging
from dataclasses import dataclass

import numpy as np

logger = logging.getLogger(__name__)

# Elo constants
ELO_K_FACTOR = 32  # Standard K-factor
ELO_BASE = 1500  # Starting Elo for new fighters
ELO_SCALE = 400  # Standard Elo scale factor


@dataclass
class UFCFighterStats:
    """Stats needed for simulation."""

    name: str
    elo: float = ELO_BASE
    sig_strikes_landed_per_min: float = 4.0  # Significant strikes
    sig_strike_accuracy: float = 0.45  # 45% accuracy
    sig_strike_defense: float = 0.55  # 55% defense
    takedowns_per_15min: float = 1.5
    takedown_accuracy: float = 0.35
    takedown_defense: float = 0.60
    finish_rate: float = 0.50  # % of wins by KO/Sub
    avg_fight_time_mins: float = 12.0  # Average fight duration


@dataclass
class UFCMatchup:
    """A single UFC bout for simulation."""

    event_id: str
    fighter_a: UFCFighterStats  # Home/favorite
    fighter_b: UFCFighterStats
    n_rounds: int = 3  # 3 or 5 for title fights


def elo_win_probability(elo_a: float, elo_b: float) -> float:
    """Calculate expected win probability from Elo ratings.

    Standard logistic Elo formula:
    P(A wins) = 1 / (1 + 10^((Elo_B - Elo_A) / 400))
    """
    return 1.0 / (1.0 + 10.0 ** ((elo_b - elo_a) / ELO_SCALE))


def stat_adjustment(fighter_a: UFCFighterStats, fighter_b: UFCFighterStats) -> float:
    """Calculate a probability adjustment based on striking and grappling stats.

    Returns a value in [-0.10, +0.10] that shifts the Elo baseline.
    Positive = favors fighter A, negative = favors fighter B.
    """
    # Striking advantage: volume × accuracy vs opponent's defense
    a_striking = (
        fighter_a.sig_strikes_landed_per_min
        * fighter_a.sig_strike_accuracy
        * (1 - fighter_b.sig_strike_defense)
    )
    b_striking = (
        fighter_b.sig_strikes_landed_per_min
        * fighter_b.sig_strike_accuracy
        * (1 - fighter_a.sig_strike_defense)
    )
    strike_diff = (a_striking - b_striking) / max(a_striking + b_striking, 0.01)

    # Grappling advantage: takedown volume × accuracy vs defense
    a_grappling = (
        fighter_a.takedowns_per_15min
        * fighter_a.takedown_accuracy
        * (1 - fighter_b.takedown_defense)
    )
    b_grappling = (
        fighter_b.takedowns_per_15min
        * fighter_b.takedown_accuracy
        * (1 - fighter_a.takedown_defense)
    )
    grapple_diff = (a_grappling - b_grappling) / max(a_grappling + b_grappling, 0.01)

    # Weight striking slightly more (60/40) — MMA is primarily a striking sport
    raw_adjustment = 0.6 * strike_diff + 0.4 * grapple_diff

    # Cap at ±10% shift
    return max(-0.10, min(0.10, raw_adjustment * 0.15))


def calculate_win_probability(
    fighter_a: UFCFighterStats,
    fighter_b: UFCFighterStats,
) -> float:
    """Calculate fighter A's win probability combining Elo + stats.

    Returns probability in [0.05, 0.95] (clamped to avoid extreme certainty).
    """
    elo_prob = elo_win_probability(fighter_a.elo, fighter_b.elo)
    adjustment = stat_adjustment(fighter_a, fighter_b)
    combined = elo_prob + adjustment

    # Clamp to avoid overconfidence
    return max(0.05, min(0.95, combined))


def simulate_ufc_bout(
    matchup: UFCMatchup,
    n_sims: int = 10_000,
    seed: int | None = None,
) -> dict:
    """Run a full Monte Carlo simulation for a UFC bout.

    Returns probability estimates for each fighter winning.
    """
    from app.engine.monte_carlo import MonteCarloEngine

    win_prob_a = calculate_win_probability(matchup.fighter_a, matchup.fighter_b)

    logger.debug(
        "UFC sim %s: %s (Elo %.0f) vs %s (Elo %.0f) → P(A)=%.3f",
        matchup.event_id,
        matchup.fighter_a.name, matchup.fighter_a.elo,
        matchup.fighter_b.name, matchup.fighter_b.elo,
        win_prob_a,
    )

    engine = MonteCarloEngine(n_sims=n_sims, seed=seed)

    result = engine.simulate_binary(
        event_id=matchup.event_id,
        home_win_prob=win_prob_a,
        outcome_names=(matchup.fighter_a.name, matchup.fighter_b.name),
        use_antithetic=True,
        use_stratified=True,
    )

    return {
        "simulation": result,
        "elo_probability": elo_win_probability(matchup.fighter_a.elo, matchup.fighter_b.elo),
        "stat_adjustment": stat_adjustment(matchup.fighter_a, matchup.fighter_b),
        "combined_probability": win_prob_a,
    }
