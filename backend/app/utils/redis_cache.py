"""Redis cache for real-time odds data."""

import json
import logging

import redis.asyncio as redis

from app.config import settings

logger = logging.getLogger(__name__)


class OddsCache:
    """Thin Redis wrapper for caching latest odds per event."""

    # Key patterns:
    #   odds:latest:{event_id}:{bookmaker}:{market}:{outcome} → price (float)
    #   events:next_commence:{sport} → ISO timestamp of next game

    TTL_SECONDS = 3600  # 1 hour — stale data auto-expires

    def __init__(self):
        self._redis: redis.Redis | None = None

    async def connect(self):
        self._redis = redis.from_url(
            settings.redis_url, decode_responses=True
        )
        await self._redis.ping()
        logger.info("Redis connected: %s", settings.redis_url)

    async def close(self):
        if self._redis:
            await self._redis.aclose()

    def _odds_key(
        self, event_id: str, bookmaker: str, market: str, outcome: str
    ) -> str:
        return f"odds:latest:{event_id}:{bookmaker}:{market}:{outcome}"

    async def set_odds(
        self,
        event_id: str,
        bookmaker: str,
        market: str,
        outcome: str,
        price: float,
        point: float | None = None,
    ):
        """Cache the latest price for an event/book/market/outcome."""
        key = self._odds_key(event_id, bookmaker, market, outcome)
        value = json.dumps({"price": price, "point": point})
        await self._redis.set(key, value, ex=self.TTL_SECONDS)

    async def get_odds(
        self, event_id: str, bookmaker: str, market: str, outcome: str
    ) -> dict | None:
        """Retrieve cached odds. Returns None if expired or missing."""
        key = self._odds_key(event_id, bookmaker, market, outcome)
        raw = await self._redis.get(key)
        if raw is None:
            return None
        return json.loads(raw)

    async def set_next_commence(self, sport: str, iso_timestamp: str):
        """Cache the next event start time for a sport (used by scheduler)."""
        key = f"events:next_commence:{sport}"
        await self._redis.set(key, iso_timestamp, ex=self.TTL_SECONDS)

    async def get_next_commence(self, sport: str) -> str | None:
        key = f"events:next_commence:{sport}"
        return await self._redis.get(key)

    async def health_check(self) -> bool:
        """Return True if Redis is reachable."""
        try:
            return await self._redis.ping()
        except Exception:
            return False


# Singleton
odds_cache = OddsCache()
