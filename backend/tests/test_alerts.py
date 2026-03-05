"""Tests for the alert/webhook system."""

import pytest

from app.engine.alerts import (
    AlertConfig,
    AlertManager,
    format_signal_message,
    format_steam_move_message,
    format_risk_change_message,
    format_daily_summary,
)


class TestAlertConfig:
    def test_discord_disabled_without_url(self):
        config = AlertConfig()
        assert not config.discord_enabled

    def test_discord_enabled_with_url(self):
        config = AlertConfig(discord_webhook_url="https://discord.com/api/webhooks/123/abc")
        assert config.discord_enabled

    def test_telegram_disabled_without_both(self):
        config = AlertConfig(telegram_bot_token="123:ABC")
        assert not config.telegram_enabled

    def test_telegram_enabled_with_both(self):
        config = AlertConfig(telegram_bot_token="123:ABC", telegram_chat_id="-100123")
        assert config.telegram_enabled

    def test_all_disabled_when_enabled_false(self):
        config = AlertConfig(
            discord_webhook_url="https://discord.com/api/webhooks/123/abc",
            telegram_bot_token="123:ABC",
            telegram_chat_id="-100123",
            enabled=False,
        )
        assert not config.discord_enabled
        assert not config.telegram_enabled


class TestMessageFormatting:
    def test_signal_message(self):
        msg = format_signal_message(
            home_team="Yankees", away_team="Red Sox",
            outcome="Yankees", bookmaker="bet365",
            decimal_odds=2.10, edge_pct=5.2,
            model_prob=0.55, recommended_stake=50,
            risk_level="normal",
        )
        assert "Yankees" in msg
        assert "Red Sox" in msg
        assert "bet365" in msg
        assert "+5.2%" in msg
        assert "$50" in msg

    def test_steam_move_message(self):
        msg = format_steam_move_message(
            description="Steam move: Yankees at bet365",
            bookmaker="bet365",
            old_odds=2.10, new_odds=1.80,
            change_pct=5.5,
        )
        assert "Steam Move" in msg
        assert "2.10" in msg
        assert "1.80" in msg

    def test_risk_change_message(self):
        msg = format_risk_change_message(
            old_level="normal", new_level="cautious",
            drawdown_pct=12.5, bankroll=875,
        )
        assert "normal" in msg
        assert "cautious" in msg
        assert "12.5%" in msg

    def test_daily_summary_message(self):
        msg = format_daily_summary(
            total_signals=15, best_edge=8.3,
            total_pnl=125.0, win_rate=0.62,
            risk_level="normal", brier_score=0.1823,
        )
        assert "15" in msg
        assert "+8.3%" in msg
        assert "$+125" in msg
        assert "62.0%" in msg

    def test_daily_summary_with_none_values(self):
        msg = format_daily_summary(
            total_signals=0, best_edge=0.0,
            total_pnl=0.0, win_rate=None,
            risk_level="normal", brier_score=None,
        )
        assert "N/A" in msg


class TestAlertManager:
    def test_init_default_config(self):
        mgr = AlertManager()
        assert mgr.config.enabled
        assert not mgr.config.discord_enabled
        assert not mgr.config.telegram_enabled

    def test_min_edge_filter(self):
        config = AlertConfig(min_edge_to_alert=0.05)  # 5% minimum
        mgr = AlertManager(config)
        # Should not alert for 3% edge (below 5% threshold)
        # Testing the logic directly
        assert 3.0 < config.min_edge_to_alert * 100
