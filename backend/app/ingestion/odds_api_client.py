"""The-Odds-API client with adaptive polling."""

import logging
import time
from datetime import datetime, timezone

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


class OddsAPIError(Exception):
    """Raised when The-Odds-API returns an error."""

    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"Odds API error {status_code}: {detail}")


class OddsAPIClient:
    """HTTP client for The-Odds-API v4.

    Handles authentication, rate-limit awareness, and response parsing.
    """

    def __init__(self):
        self.base_url = settings.odds_api_base_url
        self.api_key = settings.odds_api_key
        self._client = httpx.AsyncClient(timeout=30.0)
        self._remaining_requests: int | None = None
        self._used_requests: int | None = None

    async def close(self):
        await self._client.aclose()

    @property
    def requests_remaining(self) -> int | None:
        return self._remaining_requests

    def _update_usage(self, headers: httpx.Headers):
        """Track API quota from response headers."""
        remaining = headers.get("x-requests-remaining")
        used = headers.get("x-requests-used")
        if remaining is not None:
            self._remaining_requests = int(remaining)
        if used is not None:
            self._used_requests = int(used)
            logger.info(
                "Odds API quota: %s used, %s remaining",
                self._used_requests,
                self._remaining_requests,
            )

    async def get_events(self, sport: str) -> list[dict]:
        """Fetch upcoming events for a sport.

        Returns raw event list from The-Odds-API.
        """
        url = f"{self.base_url}/sports/{sport}/odds"
        params = {
            "apiKey": self.api_key,
            "regions": "us,us2,eu",  # Covers books operating in Canada
            "markets": "h2h,spreads,totals",
            "oddsFormat": "decimal",
        }

        start = time.monotonic()
        resp = await self._client.get(url, params=params)
        latency_ms = int((time.monotonic() - start) * 1000)

        self._update_usage(resp.headers)

        if resp.status_code == 401:
            raise OddsAPIError(401, "Invalid API key")
        if resp.status_code == 429:
            raise OddsAPIError(429, "Rate limit exceeded")
        if resp.status_code != 200:
            raise OddsAPIError(resp.status_code, resp.text[:500])

        events = resp.json()
        logger.info(
            "Fetched %d events for %s in %dms", len(events), sport, latency_ms
        )
        return events

    async def get_sports(self) -> list[dict]:
        """Fetch all available sports (useful for discovery)."""
        url = f"{self.base_url}/sports"
        params = {"apiKey": self.api_key}
        resp = await self._client.get(url, params=params)
        self._update_usage(resp.headers)

        if resp.status_code != 200:
            raise OddsAPIError(resp.status_code, resp.text[:500])
        return resp.json()
