"""Tests for OddsAPIClient with mocked HTTP responses."""

import pytest
import httpx

from app.ingestion.odds_api_client import OddsAPIClient, OddsAPIError


@pytest.fixture
def client():
    return OddsAPIClient()


class TestQuotaTracking:
    def test_update_usage_from_headers(self, client):
        headers = httpx.Headers({
            "x-requests-remaining": "450",
            "x-requests-used": "50",
        })
        client._update_usage(headers)
        assert client.requests_remaining == 450
        assert client._used_requests == 50

    def test_missing_headers_no_crash(self, client):
        headers = httpx.Headers({})
        client._update_usage(headers)
        assert client.requests_remaining is None


class TestOddsAPIError:
    def test_error_properties(self):
        err = OddsAPIError(429, "Rate limited")
        assert err.status_code == 429
        assert "Rate limited" in str(err)
        assert "429" in str(err)

    def test_error_is_exception(self):
        with pytest.raises(OddsAPIError):
            raise OddsAPIError(401, "Bad key")
