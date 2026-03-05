"""Webhook alerting — sends +EV signals and line movement alerts to
Discord and Telegram channels.

Supports two notification channels:
1. Discord — via webhook URL (no bot token needed)
2. Telegram — via Bot API with chat_id

Alert types:
- New +EV signal detected (edge > threshold)
- Steam move detected (high priority line movement)
- Risk level change (e.g., normal → cautious)
- Daily summary (top signals, P&L, calibration)

All alerts are fire-and-forget with retry on failure.
"""

import logging
from dataclasses import dataclass
from enum import Enum

import httpx

logger = logging.getLogger(__name__)


class AlertChannel(str, Enum):
    DISCORD = "discord"
    TELEGRAM = "telegram"


class AlertType(str, Enum):
    SIGNAL = "signal"
    STEAM_MOVE = "steam_move"
    RISK_CHANGE = "risk_change"
    DAILY_SUMMARY = "daily_summary"


@dataclass
class AlertConfig:
    """Configuration for alert destinations."""

    discord_webhook_url: str | None = None
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None
    min_edge_to_alert: float = 0.03  # Only alert on 3%+ edges
    enabled: bool = True

    @property
    def discord_enabled(self) -> bool:
        return self.enabled and self.discord_webhook_url is not None

    @property
    def telegram_enabled(self) -> bool:
        return self.enabled and self.telegram_bot_token is not None and self.telegram_chat_id is not None


def format_signal_message(
    home_team: str,
    away_team: str,
    outcome: str,
    bookmaker: str,
    decimal_odds: float,
    edge_pct: float,
    model_prob: float,
    recommended_stake: float,
    risk_level: str,
) -> str:
    """Format a +EV signal for messaging."""
    return (
        f"**+EV Signal Detected**\n"
        f"**{home_team}** vs **{away_team}**\n"
        f"Pick: **{outcome}** @ {bookmaker}\n"
        f"Odds: `{decimal_odds:.2f}` | Model: `{model_prob*100:.1f}%`\n"
        f"Edge: `+{edge_pct:.1f}%` | Stake: `${recommended_stake:.0f}`\n"
        f"Risk: {risk_level}"
    )


def format_steam_move_message(
    description: str,
    bookmaker: str,
    old_odds: float,
    new_odds: float,
    change_pct: float,
) -> str:
    """Format a steam move alert."""
    direction = "shortened" if change_pct > 0 else "lengthened"
    return (
        f"**Steam Move Alert**\n"
        f"{description}\n"
        f"Line {direction}: `{old_odds:.2f}` -> `{new_odds:.2f}` ({change_pct:+.1f}%)\n"
        f"Book: {bookmaker}"
    )


def format_risk_change_message(
    old_level: str,
    new_level: str,
    drawdown_pct: float,
    bankroll: float,
) -> str:
    """Format a risk level change alert."""
    emoji_map = {"aggressive": "green", "normal": "blue", "cautious": "yellow", "defensive": "red"}
    return (
        f"**Risk Level Changed**\n"
        f"{old_level} -> **{new_level}**\n"
        f"Drawdown: `{drawdown_pct:.1f}%` | Bankroll: `${bankroll:.0f}`"
    )


def format_daily_summary(
    total_signals: int,
    best_edge: float,
    total_pnl: float,
    win_rate: float | None,
    risk_level: str,
    brier_score: float | None,
) -> str:
    """Format a daily summary."""
    wr = f"{win_rate*100:.1f}%" if win_rate is not None else "N/A"
    brier = f"{brier_score:.4f}" if brier_score is not None else "N/A"
    return (
        f"**Daily Summary**\n"
        f"Signals: `{total_signals}` | Best edge: `+{best_edge:.1f}%`\n"
        f"P&L: `${total_pnl:+.0f}` | Win rate: `{wr}`\n"
        f"Risk: {risk_level} | Brier: `{brier}`"
    )


class AlertManager:
    """Sends alerts to Discord and Telegram."""

    def __init__(self, config: AlertConfig | None = None):
        self.config = config or AlertConfig()
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=10.0)
        return self._client

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None

    async def send_signal_alert(
        self,
        home_team: str,
        away_team: str,
        outcome: str,
        bookmaker: str,
        decimal_odds: float,
        edge_pct: float,
        model_prob: float,
        recommended_stake: float,
        risk_level: str = "normal",
    ):
        """Send a +EV signal alert to all configured channels."""
        if edge_pct < self.config.min_edge_to_alert * 100:
            return

        message = format_signal_message(
            home_team, away_team, outcome, bookmaker,
            decimal_odds, edge_pct, model_prob, recommended_stake, risk_level,
        )
        await self._send_to_all(message)

    async def send_steam_alert(
        self,
        description: str,
        bookmaker: str,
        old_odds: float,
        new_odds: float,
        change_pct: float,
    ):
        """Send a steam move alert."""
        message = format_steam_move_message(description, bookmaker, old_odds, new_odds, change_pct)
        await self._send_to_all(message)

    async def send_risk_change(
        self,
        old_level: str,
        new_level: str,
        drawdown_pct: float,
        bankroll: float,
    ):
        """Send a risk level change alert."""
        message = format_risk_change_message(old_level, new_level, drawdown_pct, bankroll)
        await self._send_to_all(message)

    async def send_daily_summary(
        self,
        total_signals: int,
        best_edge: float,
        total_pnl: float,
        win_rate: float | None,
        risk_level: str,
        brier_score: float | None,
    ):
        """Send the daily summary."""
        message = format_daily_summary(
            total_signals, best_edge, total_pnl, win_rate, risk_level, brier_score,
        )
        await self._send_to_all(message)

    async def _send_to_all(self, message: str):
        """Send message to all enabled channels."""
        if not self.config.enabled:
            return

        if self.config.discord_enabled:
            await self._send_discord(message)

        if self.config.telegram_enabled:
            await self._send_telegram(message)

    async def _send_discord(self, message: str):
        """Send a message to Discord via webhook."""
        if not self.config.discord_webhook_url:
            return

        try:
            client = await self._get_client()
            resp = await client.post(
                self.config.discord_webhook_url,
                json={"content": message},
            )
            if resp.status_code == 204:
                logger.debug("Discord alert sent")
            else:
                logger.warning("Discord alert failed: %d %s", resp.status_code, resp.text)
        except Exception as e:
            logger.error("Discord alert error: %s", e)

    async def _send_telegram(self, message: str):
        """Send a message to Telegram via Bot API."""
        if not self.config.telegram_bot_token or not self.config.telegram_chat_id:
            return

        url = f"https://api.telegram.org/bot{self.config.telegram_bot_token}/sendMessage"
        # Convert markdown bold from **text** to Telegram *text*
        tg_message = message.replace("**", "*")

        try:
            client = await self._get_client()
            resp = await client.post(
                url,
                json={
                    "chat_id": self.config.telegram_chat_id,
                    "text": tg_message,
                    "parse_mode": "Markdown",
                },
            )
            if resp.status_code == 200:
                logger.debug("Telegram alert sent")
            else:
                logger.warning("Telegram alert failed: %d %s", resp.status_code, resp.text)
        except Exception as e:
            logger.error("Telegram alert error: %s", e)
