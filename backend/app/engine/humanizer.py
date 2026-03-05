"""Humanizer — makes bet patterns look natural to avoid sportsbook restrictions.

Sportsbooks actively detect and limit sharp bettors. Common triggers:
1. Consistently betting on +EV lines within minutes of opening
2. Always betting round numbers ($100, $500)
3. Concentration at one bookmaker
4. Betting only when lines are stale/off-market
5. Pattern of always winning / beating the closing line

The humanizer adds realistic noise to bet parameters:
- Stake amounts get randomized (±5-15%)
- Bet timing gets staggered (random delays)
- Stakes are rounded to natural-looking amounts
- Bookmaker rotation is tracked and enforced
- Frequency limits prevent too many bets in a short period

This is DEFENSIVE, not deceptive — it prevents legitimate bettors from
being flagged by automated detection systems that assume all profitable
bettors are "sharps" to be limited.
"""

import logging
import math
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

# Natural-looking stake amounts that humans actually bet
NATURAL_AMOUNTS = [
    5, 10, 15, 20, 25, 30, 35, 40, 45, 50,
    60, 70, 75, 80, 90, 100,
    125, 150, 175, 200, 250, 300,
    400, 500, 750, 1000,
]


@dataclass
class HumanizedBet:
    """A bet recommendation after humanization."""

    event_id: str
    outcome: str
    bookmaker: str
    original_stake: float
    humanized_stake: float
    delay_seconds: int  # Suggested delay before placing
    reason: str  # Why this particular humanization was applied
    suppressed: bool = False  # True if bet should be skipped entirely
    suppression_reason: str = ""


@dataclass
class BookmakerActivity:
    """Tracks recent activity at one bookmaker for rotation enforcement."""

    bookmaker: str
    bets_today: int = 0
    bets_this_week: int = 0
    last_bet_at: datetime | None = None
    consecutive_wins: int = 0
    total_staked_today: float = 0.0


@dataclass
class HumanizerConfig:
    """Configuration for humanization parameters."""

    # Stake randomization
    stake_noise_min: float = 0.05  # ±5% minimum noise
    stake_noise_max: float = 0.15  # ±15% maximum noise
    round_to_natural: bool = True  # Round to natural-looking amounts

    # Timing
    min_delay_seconds: int = 30  # Minimum delay before placing
    max_delay_seconds: int = 300  # Maximum delay (5 min)
    peak_delay_seconds: int = 120  # Most common delay (~2 min)

    # Frequency limits
    max_bets_per_day_per_book: int = 3  # Max bets at one bookmaker per day
    max_bets_per_week_per_book: int = 10  # Max bets at one bookmaker per week
    min_time_between_bets: int = 600  # 10 min minimum between bets at same book

    # Win streak protection
    max_consecutive_wins: int = 5  # Cool off after N consecutive wins at a book

    # Seed for reproducible testing (None = truly random)
    seed: int | None = None


class Humanizer:
    """Applies human-like noise to bet parameters to avoid detection."""

    def __init__(self, config: HumanizerConfig | None = None):
        self.config = config or HumanizerConfig()
        self.rng = random.Random(self.config.seed)
        self.bookmaker_activity: dict[str, BookmakerActivity] = {}
        self._last_bet_time: datetime | None = None

    def humanize_bet(
        self,
        event_id: str,
        outcome: str,
        bookmaker: str,
        stake: float,
    ) -> HumanizedBet:
        """Apply humanization to a bet recommendation.

        Returns a HumanizedBet with adjusted stake, suggested delay,
        and potentially a suppression flag.
        """
        activity = self._get_activity(bookmaker)

        # Check suppression rules first
        suppressed, reason = self._check_suppression(bookmaker, activity)
        if suppressed:
            logger.info(
                "Bet suppressed: %s %s @ %s — %s",
                event_id, outcome, bookmaker, reason,
            )
            return HumanizedBet(
                event_id=event_id,
                outcome=outcome,
                bookmaker=bookmaker,
                original_stake=stake,
                humanized_stake=0.0,
                delay_seconds=0,
                reason="suppressed",
                suppressed=True,
                suppression_reason=reason,
            )

        # Randomize stake
        humanized_stake = self._randomize_stake(stake)

        # Calculate delay
        delay = self._calculate_delay()

        return HumanizedBet(
            event_id=event_id,
            outcome=outcome,
            bookmaker=bookmaker,
            original_stake=stake,
            humanized_stake=humanized_stake,
            delay_seconds=delay,
            reason=f"stake {stake:.2f}→{humanized_stake:.2f}, delay {delay}s",
        )

    def record_bet_placed(self, bookmaker: str, won: bool | None = None):
        """Record that a bet was actually placed at this bookmaker."""
        activity = self._get_activity(bookmaker)
        activity.bets_today += 1
        activity.bets_this_week += 1
        activity.last_bet_at = datetime.now(timezone.utc)
        self._last_bet_time = datetime.now(timezone.utc)

        if won is True:
            activity.consecutive_wins += 1
        elif won is False:
            activity.consecutive_wins = 0

    def record_bet_result(self, bookmaker: str, won: bool):
        """Record win/loss for consecutive win tracking."""
        activity = self._get_activity(bookmaker)
        if won:
            activity.consecutive_wins += 1
        else:
            activity.consecutive_wins = 0

    def reset_daily_counts(self):
        """Reset daily bet counters (call at midnight)."""
        for activity in self.bookmaker_activity.values():
            activity.bets_today = 0
            activity.total_staked_today = 0.0

    def reset_weekly_counts(self):
        """Reset weekly bet counters (call on Monday)."""
        for activity in self.bookmaker_activity.values():
            activity.bets_this_week = 0

    def _get_activity(self, bookmaker: str) -> BookmakerActivity:
        """Get or create activity tracker for a bookmaker."""
        if bookmaker not in self.bookmaker_activity:
            self.bookmaker_activity[bookmaker] = BookmakerActivity(bookmaker=bookmaker)
        return self.bookmaker_activity[bookmaker]

    def _check_suppression(
        self, bookmaker: str, activity: BookmakerActivity
    ) -> tuple[bool, str]:
        """Check if this bet should be suppressed entirely."""
        cfg = self.config

        # Daily limit
        if activity.bets_today >= cfg.max_bets_per_day_per_book:
            return True, f"Daily limit ({cfg.max_bets_per_day_per_book}) reached at {bookmaker}"

        # Weekly limit
        if activity.bets_this_week >= cfg.max_bets_per_week_per_book:
            return True, f"Weekly limit ({cfg.max_bets_per_week_per_book}) reached at {bookmaker}"

        # Too soon since last bet at this book
        if activity.last_bet_at:
            elapsed = (datetime.now(timezone.utc) - activity.last_bet_at).total_seconds()
            if elapsed < cfg.min_time_between_bets:
                return True, f"Too soon since last bet at {bookmaker} ({elapsed:.0f}s < {cfg.min_time_between_bets}s)"

        # Win streak cooloff
        if activity.consecutive_wins >= cfg.max_consecutive_wins:
            return True, f"Win streak cooloff at {bookmaker} ({activity.consecutive_wins} consecutive wins)"

        return False, ""

    def _randomize_stake(self, stake: float) -> float:
        """Add realistic noise to the stake amount."""
        cfg = self.config

        # Random noise between min and max
        noise_pct = self.rng.uniform(cfg.stake_noise_min, cfg.stake_noise_max)
        direction = self.rng.choice([-1, 1])
        noisy_stake = stake * (1 + direction * noise_pct)

        # Round to natural amount
        if cfg.round_to_natural:
            noisy_stake = self._round_to_natural(noisy_stake)

        # Ensure minimum $5 bet
        return max(5.0, noisy_stake)

    def _round_to_natural(self, amount: float) -> float:
        """Round to the nearest natural-looking bet amount."""
        if amount <= 0:
            return 5.0

        # Find the closest natural amount
        closest = min(NATURAL_AMOUNTS, key=lambda x: abs(x - amount))

        # If the amount is significantly larger than our table, round to nearest 50 or 100
        if amount > NATURAL_AMOUNTS[-1]:
            if amount > 500:
                return round(amount / 100) * 100
            return round(amount / 50) * 50

        return float(closest)

    def _calculate_delay(self) -> int:
        """Calculate a human-like delay before placing the bet.

        Uses a log-normal distribution to simulate natural human timing:
        most bets placed after ~2 minutes, with a long tail.
        """
        cfg = self.config

        # Log-normal distribution centered around peak_delay
        mu = math.log(cfg.peak_delay_seconds)
        sigma = 0.5
        delay = self.rng.lognormvariate(mu, sigma)

        # Clamp to bounds
        delay = max(cfg.min_delay_seconds, min(cfg.max_delay_seconds, delay))

        return int(delay)

    def suggest_bookmaker_rotation(
        self, available_bookmakers: list[str]
    ) -> list[str]:
        """Rank bookmakers by how safe they are to bet at right now.

        Prefers bookmakers where we have:
        - Fewer recent bets
        - No active win streaks
        - Longer time since last bet
        """
        def score(book: str) -> float:
            activity = self.bookmaker_activity.get(book)
            if activity is None:
                return 100.0  # Never used = most preferred

            s = 0.0
            # Fewer daily bets = better
            s += (self.config.max_bets_per_day_per_book - activity.bets_today) * 10
            # Lower win streak = better
            s -= activity.consecutive_wins * 5
            # More time since last bet = better
            if activity.last_bet_at:
                hours_since = (datetime.now(timezone.utc) - activity.last_bet_at).total_seconds() / 3600
                s += min(hours_since * 2, 20)
            return s

        return sorted(available_bookmakers, key=score, reverse=True)
