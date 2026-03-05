"""InfoFi Scanner — line movement detection, steam moves, and sharp money alerts.

Monitors odds changes across bookmakers to identify:
1. Steam moves — sudden, sharp line movements indicating informed money
2. Reverse line movement (RLM) — line moves opposite to public betting
3. Sharp-to-soft convergence — soft books slowly matching Pinnacle prices
4. Stale lines — bookmakers slow to update after market moves

These signals enhance edge detection by identifying WHEN lines are most
exploitable, not just which lines have static edges.

Reference: Pinnacle market-making approach, CLV literature,
gemchange_ltd thread on market microstructure.
"""

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum

import numpy as np

logger = logging.getLogger(__name__)


class MovementType(str, Enum):
    """Types of line movement detected."""

    STEAM = "steam"  # Fast, large move at sharp books
    REVERSE = "reverse"  # Line moves opposite to expected direction
    STALE = "stale"  # Bookmaker hasn't updated despite market move
    CONVERGENCE = "convergence"  # Soft book moving toward sharp price
    DRIFT = "drift"  # Gradual line movement over time


class AlertPriority(str, Enum):
    """Priority level for line movement alerts."""

    HIGH = "high"  # Act immediately — steam move or large stale line
    MEDIUM = "medium"  # Monitor — convergence or moderate stale line
    LOW = "low"  # Informational — gradual drift


@dataclass
class OddsPoint:
    """A single odds observation at a point in time."""

    bookmaker: str
    outcome: str
    decimal_odds: float
    implied_prob: float
    captured_at: datetime


@dataclass
class LineMovement:
    """A detected line movement event."""

    event_id: str
    sport: str
    movement_type: MovementType
    priority: AlertPriority
    bookmaker: str
    outcome: str

    # Price change
    old_odds: float
    new_odds: float
    odds_change_pct: float  # Percentage change in implied probability

    # Context
    sharp_odds: float | None  # Current Pinnacle odds
    sharp_implied: float | None  # Pinnacle implied probability
    gap_from_sharp: float | None  # How far this book is from sharp line

    detected_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    description: str = ""


@dataclass
class StaleLine:
    """A bookmaker line that appears stale (not updated while market moved)."""

    event_id: str
    bookmaker: str
    outcome: str
    book_odds: float
    book_implied: float
    sharp_odds: float
    sharp_implied: float
    gap: float  # Probability gap between book and sharp
    time_since_update: timedelta | None
    edge_if_accurate: float  # Edge if sharp line is correct


@dataclass
class MarketSnapshot:
    """Complete market state for one event at one point in time."""

    event_id: str
    sport: str
    captured_at: datetime
    odds: dict[str, dict[str, float]]  # {bookmaker: {outcome: decimal_odds}}

    def sharp_odds(self, outcome: str, sharp_book: str = "pinnacle") -> float | None:
        """Get the sharp bookmaker's odds for an outcome."""
        if sharp_book in self.odds and outcome in self.odds[sharp_book]:
            return self.odds[sharp_book][outcome]
        return None


class LineMovementTracker:
    """Tracks odds changes over time and detects significant movements."""

    def __init__(
        self,
        steam_threshold: float = 0.03,  # 3% implied prob change = steam
        stale_threshold: float = 0.04,  # 4% gap from sharp = stale
        min_snapshots: int = 2,
        sharp_book: str = "pinnacle",
    ):
        self.steam_threshold = steam_threshold
        self.stale_threshold = stale_threshold
        self.min_snapshots = min_snapshots
        self.sharp_book = sharp_book

        # History: {event_id: [MarketSnapshot, ...]}
        self.history: dict[str, list[MarketSnapshot]] = defaultdict(list)
        # Alerts
        self.alerts: list[LineMovement] = []

    def add_snapshot(self, snapshot: MarketSnapshot):
        """Add a new market snapshot and check for movements."""
        self.history[snapshot.event_id].append(snapshot)
        # Keep last 100 snapshots per event
        if len(self.history[snapshot.event_id]) > 100:
            self.history[snapshot.event_id] = self.history[snapshot.event_id][-100:]

    def detect_movements(self, event_id: str) -> list[LineMovement]:
        """Analyze recent snapshots for an event and detect significant movements."""
        snapshots = self.history.get(event_id, [])
        if len(snapshots) < self.min_snapshots:
            return []

        movements: list[LineMovement] = []
        current = snapshots[-1]
        previous = snapshots[-2]

        for bookmaker, outcomes in current.odds.items():
            for outcome, new_odds in outcomes.items():
                old_odds = previous.odds.get(bookmaker, {}).get(outcome)
                if old_odds is None:
                    continue

                new_implied = 1.0 / new_odds if new_odds > 1 else 1.0
                old_implied = 1.0 / old_odds if old_odds > 1 else 1.0
                change = new_implied - old_implied

                if abs(change) < 0.005:
                    continue  # Ignore tiny movements

                sharp_odds = current.sharp_odds(outcome, self.sharp_book)
                sharp_implied = 1.0 / sharp_odds if sharp_odds and sharp_odds > 1 else None
                gap = abs(new_implied - sharp_implied) if sharp_implied else None

                # Detect steam moves (large, fast changes)
                if abs(change) >= self.steam_threshold:
                    movement = LineMovement(
                        event_id=event_id,
                        sport=current.sport,
                        movement_type=MovementType.STEAM,
                        priority=AlertPriority.HIGH,
                        bookmaker=bookmaker,
                        outcome=outcome,
                        old_odds=old_odds,
                        new_odds=new_odds,
                        odds_change_pct=round(change * 100, 2),
                        sharp_odds=sharp_odds,
                        sharp_implied=sharp_implied,
                        gap_from_sharp=round(gap, 4) if gap else None,
                        description=f"Steam move: {outcome} at {bookmaker} moved {change:+.1%}",
                    )
                    movements.append(movement)
                    logger.info("STEAM MOVE: %s", movement.description)

                # Detect convergence (soft book moving toward sharp)
                elif bookmaker != self.sharp_book and sharp_implied is not None:
                    old_gap = abs(old_implied - sharp_implied)
                    new_gap = abs(new_implied - sharp_implied)
                    if new_gap < old_gap and old_gap - new_gap > 0.01:
                        movement = LineMovement(
                            event_id=event_id,
                            sport=current.sport,
                            movement_type=MovementType.CONVERGENCE,
                            priority=AlertPriority.MEDIUM,
                            bookmaker=bookmaker,
                            outcome=outcome,
                            old_odds=old_odds,
                            new_odds=new_odds,
                            odds_change_pct=round(change * 100, 2),
                            sharp_odds=sharp_odds,
                            sharp_implied=sharp_implied,
                            gap_from_sharp=round(new_gap, 4),
                            description=f"Convergence: {bookmaker} moving toward sharp on {outcome}",
                        )
                        movements.append(movement)

        self.alerts.extend(movements)
        return movements

    def find_stale_lines(self, event_id: str) -> list[StaleLine]:
        """Find bookmaker lines that are stale (far from sharp line)."""
        snapshots = self.history.get(event_id, [])
        if not snapshots:
            return []

        current = snapshots[-1]
        stale: list[StaleLine] = []

        for bookmaker, outcomes in current.odds.items():
            if bookmaker == self.sharp_book:
                continue

            for outcome, book_odds in outcomes.items():
                sharp_odds = current.sharp_odds(outcome, self.sharp_book)
                if sharp_odds is None:
                    continue

                book_implied = 1.0 / book_odds if book_odds > 1 else 1.0
                sharp_implied = 1.0 / sharp_odds if sharp_odds > 1 else 1.0
                gap = sharp_implied - book_implied

                # If the sharp line implies higher probability than this book offers,
                # the book's line is stale/soft
                if gap >= self.stale_threshold:
                    edge = (sharp_implied * book_odds) - 1.0
                    stale.append(StaleLine(
                        event_id=event_id,
                        bookmaker=bookmaker,
                        outcome=outcome,
                        book_odds=book_odds,
                        book_implied=round(book_implied, 4),
                        sharp_odds=sharp_odds,
                        sharp_implied=round(sharp_implied, 4),
                        gap=round(gap, 4),
                        time_since_update=None,
                        edge_if_accurate=round(edge, 4),
                    ))

        # Sort by gap descending (most stale first)
        stale.sort(key=lambda s: s.gap, reverse=True)

        if stale:
            logger.info(
                "Found %d stale lines for event %s (worst gap: %.1f%%)",
                len(stale), event_id, stale[0].gap * 100,
            )

        return stale

    def get_market_consensus(self, event_id: str) -> dict[str, float] | None:
        """Calculate market consensus probability from all bookmakers.

        Uses median implied probability (vig-removed) across all books.
        Useful as an alternative "truth" when Pinnacle is unavailable.
        """
        snapshots = self.history.get(event_id, [])
        if not snapshots:
            return None

        current = snapshots[-1]
        outcome_probs: dict[str, list[float]] = defaultdict(list)

        for bookmaker, outcomes in current.odds.items():
            # Remove vig for this bookmaker
            raw_probs = {o: 1.0 / odds if odds > 1 else 1.0 for o, odds in outcomes.items()}
            total = sum(raw_probs.values())
            if total > 0:
                for o, p in raw_probs.items():
                    outcome_probs[o].append(p / total)

        if not outcome_probs:
            return None

        # Median across bookmakers (robust to outliers)
        consensus = {o: float(np.median(probs)) for o, probs in outcome_probs.items()}

        # Normalize
        total = sum(consensus.values())
        if total > 0:
            consensus = {o: p / total for o, p in consensus.items()}

        return consensus

    def get_recent_alerts(
        self, hours: int = 24, priority: AlertPriority | None = None
    ) -> list[LineMovement]:
        """Get recent line movement alerts."""
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        alerts = [a for a in self.alerts if a.detected_at >= cutoff]
        if priority:
            alerts = [a for a in alerts if a.priority == priority]
        return alerts

    def movement_velocity(self, event_id: str, outcome: str, bookmaker: str) -> float | None:
        """Calculate how fast a line is moving (implied prob change per minute).

        Useful for detecting gradual drift vs sudden moves.
        """
        snapshots = self.history.get(event_id, [])
        if len(snapshots) < 3:
            return None

        points = []
        for snap in snapshots[-10:]:
            odds = snap.odds.get(bookmaker, {}).get(outcome)
            if odds and odds > 1:
                points.append((snap.captured_at, 1.0 / odds))

        if len(points) < 2:
            return None

        # Linear regression over recent points
        times = [(p[0] - points[0][0]).total_seconds() / 60.0 for p in points]
        probs = [p[1] for p in points]

        if max(times) - min(times) < 1:
            return None

        coeffs = np.polyfit(times, probs, 1)
        return float(coeffs[0])  # Slope = prob change per minute
