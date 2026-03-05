"""MLB-specific Monte Carlo model.

Uses Poisson distribution for run scoring, which is the standard
statistical model for baseball (runs are approximately Poisson-distributed
with lambda = expected runs per game).

Adjustments applied:
- Home field advantage (~54% historical win rate)
- Starting pitcher quality (ERA-based adjustment)
- Bullpen strength
- Weather (optional future enhancement)

The model feeds into the generic MonteCarloEngine.simulate_scoring().
"""

import logging
from dataclasses import dataclass

import numpy as np

logger = logging.getLogger(__name__)

# MLB constants
LEAGUE_AVG_RUNS = 4.5  # ~2024-2025 MLB average runs per team per game
HOME_FIELD_ADVANTAGE = 0.025  # ~54% home win rate historically


@dataclass
class MLBTeamStats:
    """Stats needed for simulation. Can be populated from a stats API."""

    name: str
    runs_per_game: float = LEAGUE_AVG_RUNS  # Offensive output
    runs_allowed_per_game: float = LEAGUE_AVG_RUNS  # Pitching/defense
    starter_era: float | None = None  # Today's starting pitcher ERA
    bullpen_era: float | None = None


@dataclass
class MLBMatchup:
    """A single MLB game matchup for simulation."""

    event_id: str
    home: MLBTeamStats
    away: MLBTeamStats
    is_home_field: bool = True


def calculate_expected_runs(
    team_offense: float,
    opponent_defense: float,
    starter_era: float | None = None,
    is_home: bool = False,
) -> float:
    """Calculate expected runs for a team in a specific matchup.

    Uses the log5 / Pythagorean-style approach:
    Expected runs = (team_offense / league_avg) * (opponent_runs_allowed / league_avg) * league_avg

    This normalizes for the strength of both teams.
    """
    # Offensive factor: how much better/worse than average
    off_factor = team_offense / LEAGUE_AVG_RUNS

    # Defensive factor of opponent: how many runs they allow vs average
    def_factor = opponent_defense / LEAGUE_AVG_RUNS

    expected = off_factor * def_factor * LEAGUE_AVG_RUNS

    # Adjust for starting pitcher if available
    if starter_era is not None:
        # ERA below league average (~4.5) = fewer runs allowed
        pitcher_factor = starter_era / LEAGUE_AVG_RUNS
        # Blend pitcher factor (pitchers throw ~60% of innings)
        expected *= (0.4 + 0.6 * pitcher_factor)

    # Home field advantage
    if is_home:
        expected += HOME_FIELD_ADVANTAGE * LEAGUE_AVG_RUNS

    return max(0.5, expected)  # Floor at 0.5 runs


def make_poisson_scorer(expected_runs: float):
    """Create a scoring function for the Monte Carlo engine.

    Returns a callable(rng, n) -> array of n Poisson-distributed scores.
    """
    def scorer(rng: np.random.Generator, n: int) -> np.ndarray:
        return rng.poisson(expected_runs, n).astype(float)
    return scorer


def simulate_mlb_game(
    matchup: MLBMatchup,
    n_sims: int = 10_000,
    seed: int | None = None,
) -> dict:
    """Run a full Monte Carlo simulation for an MLB game.

    Returns probability estimates for home win, away win, and over/under.
    """
    from app.engine.monte_carlo import MonteCarloEngine

    # Calculate expected runs for each team
    home_expected = calculate_expected_runs(
        team_offense=matchup.home.runs_per_game,
        opponent_defense=matchup.away.runs_allowed_per_game,
        starter_era=matchup.away.starter_era,  # Away pitcher faces home batters
        is_home=matchup.is_home_field,
    )
    away_expected = calculate_expected_runs(
        team_offense=matchup.away.runs_per_game,
        opponent_defense=matchup.home.runs_allowed_per_game,
        starter_era=matchup.home.starter_era,  # Home pitcher faces away batters
        is_home=False,
    )

    logger.debug(
        "MLB sim %s: %s (%.2f exp runs) vs %s (%.2f exp runs)",
        matchup.event_id,
        matchup.home.name, home_expected,
        matchup.away.name, away_expected,
    )

    engine = MonteCarloEngine(n_sims=n_sims, seed=seed)

    result = engine.simulate_scoring(
        event_id=matchup.event_id,
        home_score_fn=make_poisson_scorer(home_expected),
        away_score_fn=make_poisson_scorer(away_expected),
        outcome_names=(matchup.home.name, matchup.away.name),
    )

    # Add expected runs to result for totals markets
    return {
        "simulation": result,
        "home_expected_runs": home_expected,
        "away_expected_runs": away_expected,
        "total_expected_runs": home_expected + away_expected,
    }
