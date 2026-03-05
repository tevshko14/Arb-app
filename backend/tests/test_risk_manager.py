"""Tests for the Risk Manager — dynamic Kelly tuning and drawdown protection."""

import pytest

from app.engine.risk_manager import (
    RiskManager,
    RiskLevel,
    BetRecord,
    KELLY_MULTIPLIERS,
    MAX_STAKE_BY_LEVEL,
    MAX_PORTFOLIO_BY_LEVEL,
)


class TestRiskLevels:
    def test_initial_state_is_normal(self):
        rm = RiskManager(initial_bankroll=1000.0)
        assert rm.risk_level == RiskLevel.NORMAL

    def test_caution_on_10pct_drawdown(self):
        rm = RiskManager(initial_bankroll=1000.0, drawdown_caution_threshold=0.10)
        rm.current_bankroll = 890.0  # 11% drawdown
        assert rm.risk_level == RiskLevel.CAUTIOUS

    def test_defensive_on_20pct_drawdown(self):
        rm = RiskManager(initial_bankroll=1000.0, drawdown_defensive_threshold=0.20)
        rm.current_bankroll = 790.0  # 21% drawdown
        assert rm.risk_level == RiskLevel.DEFENSIVE

    def test_aggressive_on_winning_streak(self):
        rm = RiskManager(initial_bankroll=1000.0, win_rate_window=5)
        # Simulate 5 consecutive wins
        for i in range(5):
            bet = BetRecord(
                event_id=f"evt_{i}", outcome="Team A", bookmaker="bet365",
                stake=50, decimal_odds=2.0, model_prob=0.55,
            )
            rm.record_bet(bet)
            rm.resolve_bet(f"evt_{i}", "Team A", won=True)
        # Low drawdown + good win rate → aggressive
        assert rm.risk_level == RiskLevel.AGGRESSIVE

    def test_drawdown_calculation(self):
        rm = RiskManager(initial_bankroll=1000.0)
        rm.current_bankroll = 850.0
        assert rm.drawdown == pytest.approx(0.15)

    def test_peak_bankroll_updates(self):
        rm = RiskManager(initial_bankroll=1000.0)
        rm.current_bankroll = 1200.0
        rm.peak_bankroll = 1200.0
        rm.current_bankroll = 1100.0
        assert rm.drawdown == pytest.approx(100.0 / 1200.0, abs=0.001)


class TestKellyMultipliers:
    def test_normal_kelly(self):
        rm = RiskManager()
        assert rm.kelly_multiplier == KELLY_MULTIPLIERS[RiskLevel.NORMAL]
        assert rm.kelly_multiplier == 0.50

    def test_defensive_reduces_kelly(self):
        rm = RiskManager(initial_bankroll=1000.0)
        rm.current_bankroll = 750.0  # 25% drawdown → defensive
        assert rm.kelly_multiplier == KELLY_MULTIPLIERS[RiskLevel.DEFENSIVE]
        assert rm.kelly_multiplier < 0.50

    def test_max_stake_varies_by_level(self):
        rm = RiskManager()
        assert rm.max_stake_fraction == MAX_STAKE_BY_LEVEL[RiskLevel.NORMAL]

    def test_portfolio_limit_varies_by_level(self):
        rm = RiskManager()
        assert rm.max_portfolio_exposure == MAX_PORTFOLIO_BY_LEVEL[RiskLevel.NORMAL]


class TestBetTracking:
    def test_record_and_resolve_win(self):
        rm = RiskManager(initial_bankroll=1000.0)
        bet = BetRecord(
            event_id="evt_1", outcome="Team A", bookmaker="pinnacle",
            stake=50, decimal_odds=2.0, model_prob=0.55,
        )
        rm.record_bet(bet)
        rm.resolve_bet("evt_1", "Team A", won=True)

        assert rm.current_bankroll == 1050.0
        assert bet.resolved
        assert bet.won
        assert bet.pnl == 50.0

    def test_record_and_resolve_loss(self):
        rm = RiskManager(initial_bankroll=1000.0)
        bet = BetRecord(
            event_id="evt_1", outcome="Team A", bookmaker="bet365",
            stake=50, decimal_odds=2.0, model_prob=0.55,
        )
        rm.record_bet(bet)
        rm.resolve_bet("evt_1", "Team A", won=False)

        assert rm.current_bankroll == 950.0
        assert bet.pnl == -50.0

    def test_active_exposure(self):
        rm = RiskManager(initial_bankroll=1000.0)
        for i in range(3):
            rm.record_bet(BetRecord(
                event_id=f"evt_{i}", outcome="A", bookmaker="bet365",
                stake=30, decimal_odds=2.0, model_prob=0.55,
            ))
        assert rm.active_exposure() == 90.0
        assert rm.active_exposure_pct() == pytest.approx(0.09)


class TestBookmakerExposure:
    def test_bookmaker_limit_enforced(self):
        rm = RiskManager(initial_bankroll=1000.0, max_bookmaker_exposure_pct=0.20)
        # Place $150 at bet365
        for i in range(3):
            rm.record_bet(BetRecord(
                event_id=f"evt_{i}", outcome="A", bookmaker="bet365",
                stake=50, decimal_odds=2.0, model_prob=0.55,
            ))
        # $50 more would be $200, which is exactly 20% of $1000
        assert rm.check_bookmaker_limit("bet365", 50) is True
        # $60 more would be $210 > $200 limit
        assert rm.check_bookmaker_limit("bet365", 60) is False

    def test_different_bookmakers_independent(self):
        rm = RiskManager(initial_bankroll=1000.0, max_bookmaker_exposure_pct=0.20)
        rm.record_bet(BetRecord(
            event_id="evt_1", outcome="A", bookmaker="bet365",
            stake=150, decimal_odds=2.0, model_prob=0.55,
        ))
        # pinnacle limit is independent of bet365
        assert rm.check_bookmaker_limit("pinnacle", 150) is True

    def test_bookmaker_pnl_tracking(self):
        rm = RiskManager(initial_bankroll=1000.0)
        rm.record_bet(BetRecord(
            event_id="evt_1", outcome="A", bookmaker="bet365",
            stake=50, decimal_odds=2.0, model_prob=0.55,
        ))
        rm.resolve_bet("evt_1", "A", won=True)
        assert rm.bookmaker_exposure["bet365"].pnl == 50.0
        assert rm.bookmaker_exposure["bet365"].wins == 1


class TestCanPlaceBet:
    def test_allows_normal_bet(self):
        rm = RiskManager(initial_bankroll=1000.0)
        allowed, reason = rm.can_place_bet(50.0, "bet365")
        assert allowed
        assert reason == "ok"

    def test_blocks_when_portfolio_full(self):
        rm = RiskManager(initial_bankroll=1000.0)
        # Place bets totaling 19% of bankroll
        for i in range(19):
            rm.record_bet(BetRecord(
                event_id=f"evt_{i}", outcome="A", bookmaker=f"book_{i}",
                stake=10, decimal_odds=2.0, model_prob=0.55,
            ))
        # 20th bet at $20 would push to 21% > 20% normal limit
        allowed, reason = rm.can_place_bet(20.0, "new_book")
        assert not allowed
        assert "portfolio limit" in reason

    def test_circuit_breaker_at_25pct_bankroll(self):
        rm = RiskManager(initial_bankroll=1000.0)
        rm.current_bankroll = 240.0  # Below 25% of initial
        allowed, reason = rm.can_place_bet(10.0, "bet365")
        assert not allowed
        assert "Circuit breaker" in reason


class TestRiskState:
    def test_get_state_snapshot(self):
        rm = RiskManager(initial_bankroll=1000.0)
        state = rm.get_state()
        assert state.risk_level == RiskLevel.NORMAL
        assert state.current_bankroll == 1000.0
        assert state.drawdown_pct == 0.0
        assert state.total_bets == 0

    def test_manual_bankroll_update(self):
        rm = RiskManager(initial_bankroll=1000.0)
        rm.update_bankroll(1500.0)
        assert rm.current_bankroll == 1500.0
        assert rm.peak_bankroll == 1500.0
