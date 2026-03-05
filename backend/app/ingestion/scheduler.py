"""Adaptive 3-tier polling scheduler for odds ingestion.

Tiers:
  - IDLE:  poll every 5 min  — no games within 6 hours
  - WARM:  poll every 60s    — games 2-6 hours away
  - HOT:   poll every 30s    — games < 2 hours away
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from app.config import settings
from app.ingestion.odds_api_client import OddsAPIError

if TYPE_CHECKING:
    from app.ingestion.pipeline import IngestPipeline

logger = logging.getLogger(__name__)


class PollTier:
    IDLE = "idle"
    WARM = "warm"
    HOT = "hot"


def determine_tier(next_commence: datetime | None) -> tuple[str, int]:
    """Determine the polling tier and interval based on the next event time.

    Returns (tier_name, interval_seconds).
    """
    if next_commence is None:
        return PollTier.IDLE, settings.poll_idle_interval

    now = datetime.now(timezone.utc)
    hours_until = (next_commence - now).total_seconds() / 3600

    if hours_until <= settings.poll_hot_threshold_hours:
        return PollTier.HOT, settings.poll_hot_interval
    elif hours_until <= settings.poll_warm_threshold_hours:
        return PollTier.WARM, settings.poll_warm_interval
    else:
        return PollTier.IDLE, settings.poll_idle_interval


class AdaptiveScheduler:
    """Runs the ingestion loop with adaptive polling intervals."""

    def __init__(self, pipeline: IngestPipeline):
        self.pipeline = pipeline
        self._running = False
        self._current_tier: str = PollTier.IDLE

    @property
    def current_tier(self) -> str:
        return self._current_tier

    async def start(self):
        """Start the adaptive polling loop."""
        self._running = True
        logger.info("Adaptive scheduler started")

        while self._running:
            try:
                next_commence = await self.pipeline.run_cycle()
                tier, interval = determine_tier(next_commence)

                if tier != self._current_tier:
                    logger.info(
                        "Poll tier changed: %s → %s (interval: %ds)",
                        self._current_tier,
                        tier,
                        interval,
                    )
                    self._current_tier = tier

                logger.debug("Next poll in %ds (tier: %s)", interval, tier)
                await asyncio.sleep(interval)

            except OddsAPIError as e:
                if e.status_code == 429:
                    logger.warning("Rate limited — backing off 120s")
                    await asyncio.sleep(120)
                else:
                    logger.error("Odds API error: %s", e)
                    await asyncio.sleep(60)

            except Exception:
                logger.exception("Unexpected error in poll cycle")
                await asyncio.sleep(60)

    def stop(self):
        """Signal the scheduler to stop after the current cycle."""
        self._running = False
        logger.info("Adaptive scheduler stopping")
