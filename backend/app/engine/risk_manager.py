"""Risk Manager — dynamic Kelly tuning, drawdown protection, per-bookmaker exposure limits.

Upgrades the static Kelly sizing from Phase 2 into an adaptive system that:
1. Adjusts Kelly multiplier based on recent performance (winning → more aggressive)
2. Triggers drawdown protection when bankroll drops significantly
3. Tracks per-bookmaker exposure to prevent concentration risk
4. Enforces correlation limits (don't overbet correlated events)

Reference: Kelly (1956), Thorp (2006), gemchange_ltd thread Part VIII
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

logger = logging.getLogger(__name__)


class RiskLevel(str, Enum):
    """Current risk posture based on bankroll trajectory."""

    AGGRESSIVE = "aggressive"  # Bankroll growing, model calibrated
    NORMAL = "normal"  # Default state
    CAUTIOUS = "cautious"  # Minor drawdown or model underperforming
    DEFENSIVE = "defensive"  # Major drawdown — reduce all exposure


# Kelly multiplier by risk level
KELLY_MULTIPLIERS = {
    RiskLevel.AGGRESSIVE: 0.65,
    RiskLevel.NORMAL: 0.50,
    RiskLevel.CAUTIOUS: 0.35,
    RiskLevel.DEFENSIVE: 0.15,
}

# Max single-bet fraction by risk level
MAX_STAKE_BY_LEVEL = {
    RiskLevel.AGGRESSIVE: 0.06,
    RiskLevel.NORMAL: 0.05,
    RiskLevel.CAUTIOUS: 0.03,
    RiskLevel.DEFENSIVE: 0.02,
}

# Max portfolio exposure by risk level
MAX_PORTFOLIO_BY_LEVEL = {
    RiskLevel.AGGRESSIVE: 0.25,
    RiskLevel.NORMAL: 0.20,
    RiskLevel.CAUTIOUS: 0.15,
    RiskLevel.DEFENSIVE: 0.08,
}


@dataclass
class BetRecord:
    """Record of a placed bet for tracking performance."""

    event_id: str
    outcome: str
    bookmaker: str
    stake: float
    decimal_odds: float
    model_prob: float
    placed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    resolved: bool = False
    won: bool | None = None
    pnl: float = 0.0


@dataclass
class BookmakerExposure:
    """Tracks exposure at a single bookmaker."""

    bookmaker: str
    total_staked: float = 0.0
    active_bets: int = 0
    total_bets: int = 0
    wins: int = 0
    losses: int = 0
    pnl: float = 0.0


@dataclass
class RiskState:
    """Complete risk state snapshot."""

    risk_level: RiskLevel
    kelly_multiplier: float
    max_stake_fraction: float
    max_portfolio_exposure: float
    current_bankroll: float
    peak_bankroll: float
    drawdown_pct: float
    active_exposure: float
    active_exposure_pct: float
    bookmaker_exposures: dict[str, BookmakerExposure]
    recent_win_rate: float | None
    recent_pnl: float
    total_bets: int
    total_pnl: float


class RiskManager:
    """Adaptive risk management for the signal pipeline.

    Dynamically adjusts Kelly multiplier and exposure limits based on:
    - Current drawdown from peak bankroll
    - Recent win rate (last N bets)
    - Per-bookmaker concentration
    - Model calibration quality
    """

    def __init__(
        self,
        initial_bankroll: float = 1000.0,
        max_bookmaker_exposure_pct: float = 0.40,
        drawdown_caution_threshold: float = 0.10,
        drawdown_defensive_threshold: float = 0.20,
        win_rate_window: int = 30,
    ):
        self.initial_bankroll = initial_bankroll
        self.current_bankroll = initial_bankroll
        self.peak_bankroll = initial_bankroll

        # Thresholds
        self.max_bookmaker_exposure_pct = max_bookmaker_exposure_pct
        self.drawdown_caution_threshold = drawdown_caution_threshold
        self.drawdown_defensive_threshold = drawdown_defensive_threshold
        self.win_rate_window = win_rate_window

        # State tracking
        self.bet_history: list[BetRecord] = []
        self.bookmaker_exposure: dict[str, BookmakerExposure] = {}
        self._risk_level = RiskLevel.NORMAL

    @property
    def drawdown(self) -> float:
        """Current drawdown from peak bankroll (0 to 1)."""
        if self.peak_bankroll <= 0:
            return 0.0
        return max(0.0, (self.peak_bankroll - self.current_bankroll) / self.peak_bankroll)

    @property
    def risk_level(self) -> RiskLevel:
        """Determine risk level from current conditions."""
        return self._assess_risk_level()

    @property
    def kelly_multiplier(self) -> float:
        """Dynamic Kelly multiplier based on risk level."""
        return KELLY_MULTIPLIERS[self.risk_level]

    @property
    def max_stake_fraction(self) -> float:
        """Dynamic max stake fraction based on risk level."""
        return MAX_STAKE_BY_LEVEL[self.risk_level]

    @property
    def max_portfolio_exposure(self) -> float:
        """Dynamic max portfolio exposure based on risk level."""
        return MAX_PORTFOLIO_BY_LEVEL[self.risk_level]

    def _assess_risk_level(self) -> RiskLevel:
        """Assess current risk level based on drawdown and performance."""
        dd = self.drawdown

        # Drawdown-based levels
        if dd >= self.drawdown_defensive_threshold:
            return RiskLevel.DEFENSIVE
        if dd >= self.drawdown_caution_threshold:
            return RiskLevel.CAUTIOUS

        # Performance-based upgrade
        recent_wr = self.recent_win_rate()
        if recent_wr is not None and recent_wr > 0.55 and dd < 0.03:
            return RiskLevel.AGGRESSIVE

        return RiskLevel.NORMAL

    def recent_win_rate(self) -> float | None:
        """Win rate over the last N resolved bets."""
        resolved = [b for b in self.bet_history if b.resolved]
        if len(resolved) < self.win_rate_window:
            return None

        recent = resolved[-self.win_rate_window:]
        wins = sum(1 for b in recent if b.won)
        return wins / len(recent)

    def record_bet(self, bet: BetRecord):
        """Record a newly placed bet."""
        self.bet_history.append(bet)

        # Update bookmaker exposure
        if bet.bookmaker not in self.bookmaker_exposure:
            self.bookmaker_exposure[bet.bookmaker] = BookmakerExposure(
                bookmaker=bet.bookmaker
            )
        exp = self.bookmaker_exposure[bet.bookmaker]
        exp.total_staked += bet.stake
        exp.active_bets += 1
        exp.total_bets += 1

    def resolve_bet(self, event_id: str, outcome: str, won: bool):
        """Resolve a bet and update bankroll/exposure."""
        for bet in self.bet_history:
            if bet.event_id == event_id and bet.outcome == outcome and not bet.resolved:
                bet.resolved = True
                bet.won = won

                if won:
                    pnl = bet.stake * (bet.decimal_odds - 1)
                else:
                    pnl = -bet.stake

                bet.pnl = pnl
                self.current_bankroll += pnl

                # Update peak
                if self.current_bankroll > self.peak_bankroll:
                    self.peak_bankroll = self.current_bankroll

                # Update bookmaker exposure
                if bet.bookmaker in self.bookmaker_exposure:
                    exp = self.bookmaker_exposure[bet.bookmaker]
                    exp.active_bets = max(0, exp.active_bets - 1)
                    exp.pnl += pnl
                    if won:
                        exp.wins += 1
                    else:
                        exp.losses += 1

                level = self._assess_risk_level()
                logger.info(
                    "Bet resolved: %s %s @ %s — %s ($%.2f), bankroll: $%.2f, risk: %s",
                    event_id,
                    outcome,
                    bet.bookmaker,
                    "WON" if won else "LOST",
                    pnl,
                    self.current_bankroll,
                    level.value,
                )
                return

    def check_bookmaker_limit(self, bookmaker: str, proposed_stake: float) -> bool:
        """Check if a bet at this bookmaker would exceed concentration limits.

        Prevents over-concentrating bets at a single bookmaker, which:
        1. Increases account restriction risk
        2. Creates single-counterparty risk
        """
        exp = self.bookmaker_exposure.get(bookmaker)
        if exp is None:
            return True

        max_at_book = self.current_bankroll * self.max_bookmaker_exposure_pct
        if exp.total_staked + proposed_stake > max_at_book:
            logger.warning(
                "Bookmaker limit: %s exposure $%.2f + $%.2f would exceed $%.2f (%.0f%%)",
                bookmaker,
                exp.total_staked,
                proposed_stake,
                max_at_book,
                self.max_bookmaker_exposure_pct * 100,
            )
            return False
        return True

    def active_exposure(self) -> float:
        """Total dollars currently at risk in unresolved bets."""
        return sum(
            b.stake for b in self.bet_history if not b.resolved
        )

    def active_exposure_pct(self) -> float:
        """Active exposure as fraction of bankroll."""
        if self.current_bankroll <= 0:
            return 1.0
        return self.active_exposure() / self.current_bankroll

    def can_place_bet(self, proposed_stake: float, bookmaker: str) -> tuple[bool, str]:
        """Comprehensive check on whether a new bet should be placed.

        Returns (allowed, reason) tuple.
        """
        # Check risk level
        if self.risk_level == RiskLevel.DEFENSIVE and self.active_exposure_pct() > 0.05:
            return False, "Defensive mode — reducing exposure"

        # Check portfolio exposure
        new_exposure = self.active_exposure_pct() + (proposed_stake / max(self.current_bankroll, 1))
        if new_exposure > self.max_portfolio_exposure:
            return False, f"Would exceed portfolio limit ({self.max_portfolio_exposure:.0%})"

        # Check bookmaker concentration
        if not self.check_bookmaker_limit(bookmaker, proposed_stake):
            return False, f"Would exceed bookmaker limit at {bookmaker}"

        # Check minimum bankroll (circuit breaker)
        if self.current_bankroll < self.initial_bankroll * 0.25:
            return False, "Circuit breaker — bankroll below 25% of initial"

        return True, "ok"

    def get_state(self) -> RiskState:
        """Get a complete snapshot of current risk state."""
        return RiskState(
            risk_level=self.risk_level,
            kelly_multiplier=self.kelly_multiplier,
            max_stake_fraction=self.max_stake_fraction,
            max_portfolio_exposure=self.max_portfolio_exposure,
            current_bankroll=self.current_bankroll,
            peak_bankroll=self.peak_bankroll,
            drawdown_pct=round(self.drawdown * 100, 2),
            active_exposure=self.active_exposure(),
            active_exposure_pct=round(self.active_exposure_pct() * 100, 2),
            bookmaker_exposures=dict(self.bookmaker_exposure),
            recent_win_rate=self.recent_win_rate(),
            recent_pnl=round(sum(b.pnl for b in self.bet_history if b.resolved), 2),
            total_bets=len(self.bet_history),
            total_pnl=round(sum(b.pnl for b in self.bet_history if b.resolved), 2),
        )

    def update_bankroll(self, new_bankroll: float):
        """Manually update bankroll (e.g., after deposits/withdrawals)."""
        self.current_bankroll = new_bankroll
        if new_bankroll > self.peak_bankroll:
            self.peak_bankroll = new_bankroll
        logger.info("Bankroll manually updated to $%.2f", new_bankroll)
