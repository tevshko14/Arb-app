"""Closing Line Value (CLV) tracker — measures signal quality by tracking
how the market moves after we identify an edge.

CLV is the gold standard metric for sharp bettors:
- If the line moves in our direction AFTER we spot the edge, we're
  capturing real information inefficiencies.
- If the line doesn't move, we might just be noise trading.

CLV = (Closing_Line_Prob - Opening_Prob_When_Signaled) / Opening_Prob

Positive CLV = the market agreed with us (sharp move in our direction).
Consistently positive CLV = genuine edge, not just luck.

Reference: gemchange_ltd thread on market efficiency measurement.
"""

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class LineSnapshot:
    """A single odds snapshot at a point in time."""

    bookmaker: str
    outcome: str
    decimal_odds: float
    implied_prob: float
    captured_at: datetime


@dataclass
class CLVRecord:
    """Tracks opening and closing lines for one signal."""

    event_id: str
    sport: str
    bookmaker: str
    outcome: str

    # When we signaled
    signal_odds: float
    signal_implied_prob: float
    signal_model_prob: float
    signal_edge: float
    signaled_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    # At close (game start)
    closing_odds: float | None = None
    closing_implied_prob: float | None = None
    closed_at: datetime | None = None

    # Sharp line at signal vs close
    sharp_odds_at_signal: float | None = None
    sharp_odds_at_close: float | None = None

    @property
    def clv(self) -> float | None:
        """Closing Line Value — how much the line moved in our direction.

        Positive = line moved our way (we had real information).
        """
        if self.closing_implied_prob is None:
            return None
        # CLV measured as probability difference
        return self.closing_implied_prob - self.signal_implied_prob

    @property
    def clv_pct(self) -> float | None:
        """CLV as a percentage of the opening implied probability."""
        if self.closing_implied_prob is None or self.signal_implied_prob <= 0:
            return None
        return (self.closing_implied_prob - self.signal_implied_prob) / self.signal_implied_prob

    @property
    def sharp_clv(self) -> float | None:
        """CLV measured against the sharp (Pinnacle) line movement."""
        if self.sharp_odds_at_signal is None or self.sharp_odds_at_close is None:
            return None
        open_prob = 1.0 / self.sharp_odds_at_signal if self.sharp_odds_at_signal > 1 else 0
        close_prob = 1.0 / self.sharp_odds_at_close if self.sharp_odds_at_close > 1 else 0
        return close_prob - open_prob


@dataclass
class BookmakerProfile:
    """Tracks how soft a bookmaker is — how often they offer +EV lines."""

    bookmaker: str
    total_signals: int = 0
    positive_clv_count: int = 0
    mean_clv: float = 0.0
    mean_edge_offered: float = 0.0
    avg_time_to_correction: float | None = None  # Minutes until line moves

    @property
    def softness_score(self) -> float:
        """How soft this bookmaker is (0-1). Higher = softer = more exploitable."""
        if self.total_signals == 0:
            return 0.0
        hit_rate = self.positive_clv_count / self.total_signals
        # Weight hit rate and average edge equally
        return min(1.0, (hit_rate * 0.5) + (min(self.mean_edge_offered, 0.10) / 0.10 * 0.5))


@dataclass
class CLVReport:
    """Summary of CLV tracking across all signals."""

    total_signals: int
    signals_with_closing: int
    mean_clv: float | None
    median_clv: float | None
    positive_clv_pct: float | None  # What % of signals had positive CLV
    mean_clv_by_sport: dict[str, float]
    bookmaker_profiles: dict[str, BookmakerProfile]
    market_efficiency_score: float | None  # How efficient is the overall market


class CLVTracker:
    """Tracks Closing Line Value across all signals."""

    def __init__(self):
        self.records: list[CLVRecord] = []
        self.bookmaker_profiles: dict[str, BookmakerProfile] = {}
        self._by_event: dict[str, list[CLVRecord]] = defaultdict(list)

    def record_signal(
        self,
        event_id: str,
        sport: str,
        bookmaker: str,
        outcome: str,
        signal_odds: float,
        signal_model_prob: float,
        signal_edge: float,
        sharp_odds: float | None = None,
    ) -> CLVRecord:
        """Record a new signal for CLV tracking."""
        implied = 1.0 / signal_odds if signal_odds > 1 else 1.0
        record = CLVRecord(
            event_id=event_id,
            sport=sport,
            bookmaker=bookmaker,
            outcome=outcome,
            signal_odds=signal_odds,
            signal_implied_prob=implied,
            signal_model_prob=signal_model_prob,
            signal_edge=signal_edge,
            sharp_odds_at_signal=sharp_odds,
        )
        self.records.append(record)
        self._by_event[event_id].append(record)

        # Update bookmaker profile
        if bookmaker not in self.bookmaker_profiles:
            self.bookmaker_profiles[bookmaker] = BookmakerProfile(bookmaker=bookmaker)
        profile = self.bookmaker_profiles[bookmaker]
        profile.total_signals += 1
        # Running average of edge offered
        profile.mean_edge_offered = (
            (profile.mean_edge_offered * (profile.total_signals - 1) + signal_edge)
            / profile.total_signals
        )

        return record

    def record_closing_line(
        self,
        event_id: str,
        bookmaker: str,
        outcome: str,
        closing_odds: float,
        sharp_closing_odds: float | None = None,
    ):
        """Record the closing line (at game start) for a previously signaled bet."""
        for record in self._by_event.get(event_id, []):
            if record.bookmaker == bookmaker and record.outcome == outcome:
                record.closing_odds = closing_odds
                record.closing_implied_prob = 1.0 / closing_odds if closing_odds > 1 else 1.0
                record.closed_at = datetime.now(timezone.utc)
                record.sharp_odds_at_close = sharp_closing_odds

                clv = record.clv
                if clv is not None and clv > 0:
                    profile = self.bookmaker_profiles.get(record.bookmaker)
                    if profile:
                        profile.positive_clv_count += 1

                logger.info(
                    "CLV recorded: %s %s @ %s — CLV: %+.2f%% (%.3f → %.3f)",
                    event_id,
                    outcome,
                    bookmaker,
                    (record.clv_pct or 0) * 100,
                    record.signal_implied_prob,
                    record.closing_implied_prob or 0,
                )
                return

    def get_closed_records(self, sport: str | None = None) -> list[CLVRecord]:
        """Get all records that have closing lines."""
        closed = [r for r in self.records if r.closing_odds is not None]
        if sport:
            closed = [r for r in closed if r.sport == sport]
        return closed

    def generate_report(self) -> CLVReport:
        """Generate a full CLV report."""
        closed = self.get_closed_records()

        if not closed:
            return CLVReport(
                total_signals=len(self.records),
                signals_with_closing=0,
                mean_clv=None,
                median_clv=None,
                positive_clv_pct=None,
                mean_clv_by_sport={},
                bookmaker_profiles=dict(self.bookmaker_profiles),
                market_efficiency_score=None,
            )

        clvs = [r.clv for r in closed if r.clv is not None]
        clv_arr = np.array(clvs) if clvs else np.array([0.0])

        # Positive CLV percentage
        positive_count = sum(1 for c in clvs if c > 0)
        positive_pct = positive_count / len(clvs) if clvs else 0.0

        # Per-sport CLV
        sports = set(r.sport for r in closed)
        sport_clvs = {}
        for sport in sports:
            sport_records = [r for r in closed if r.sport == sport and r.clv is not None]
            if sport_records:
                sport_clvs[sport] = float(np.mean([r.clv for r in sport_records]))

        # Update bookmaker profile CLV averages
        for bookmaker, profile in self.bookmaker_profiles.items():
            book_records = [r for r in closed if r.bookmaker == bookmaker and r.clv is not None]
            if book_records:
                profile.mean_clv = float(np.mean([r.clv for r in book_records]))

        # Market efficiency: how quickly do lines converge?
        # Higher positive CLV % = more inefficient market = more opportunity
        efficiency = 1.0 - positive_pct if clvs else None

        return CLVReport(
            total_signals=len(self.records),
            signals_with_closing=len(closed),
            mean_clv=float(clv_arr.mean()),
            median_clv=float(np.median(clv_arr)),
            positive_clv_pct=round(positive_pct * 100, 2),
            mean_clv_by_sport=sport_clvs,
            bookmaker_profiles=dict(self.bookmaker_profiles),
            market_efficiency_score=round(efficiency, 4) if efficiency is not None else None,
        )

    def get_softest_bookmakers(self, min_signals: int = 5) -> list[BookmakerProfile]:
        """Rank bookmakers by softness (most exploitable first)."""
        profiles = [
            p for p in self.bookmaker_profiles.values()
            if p.total_signals >= min_signals
        ]
        return sorted(profiles, key=lambda p: p.softness_score, reverse=True)
