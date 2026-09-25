"""HTTP client for Binance's public spot market-data API."""

import logging
import time
from collections.abc import Callable
from typing import Any

import httpx

from src.common.config import get_settings
from src.common.exceptions import SourceAPIError

logger = logging.getLogger(__name__)

KLINES_PATH = "/api/v3/klines"
MAX_KLINES_PER_REQUEST = 1000
# 429 = rate limited, 5xx = Binance-side trouble. Both are temporary, so we wait and retry.
# Everything else fails at once: 400 (bad symbol) will not fix itself, and 418 means the IP
# is already banned for ignoring 429s, so retrying would only make the ban longer.
RETRYABLE_STATUS = {429, 500, 502, 503, 504}
MAX_BACKOFF_SECONDS = 60.0


def backoff_seconds(attempt: int) -> float:
    """Wait 1s, 2s, 4s, ... (capped) when the server does not say how long to wait."""

    return min(2.0 ** (attempt - 1), MAX_BACKOFF_SECONDS)


def retry_after_seconds(response: httpx.Response) -> float | None:
    """Seconds Binance asked us to wait via the Retry-After header, if present."""

    try:
        return float(response.headers["Retry-After"])
    except (KeyError, ValueError):
        return None


class BinanceClient:
    """Fetch raw kline rows from Binance, retrying temporary failures.

    Only GET requests are sent, so a retry is always safe: asking twice for the same
    candles cannot change anything on Binance's side.
    """

    def __init__(
        self,
        http: httpx.Client | None = None,
        max_attempts: int = 5,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._http = http or httpx.Client(base_url=get_settings().binance_base_url, timeout=10.0)
        self.max_attempts = max_attempts
        self._sleep = sleep

    def __enter__(self) -> "BinanceClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        self._http.close()

    def get_klines(
        self,
        symbol: str,
        interval: str,
        start_ms: int,
        end_ms: int,
        limit: int = MAX_KLINES_PER_REQUEST,
    ) -> list[list[Any]]:
        """Return raw rows whose open time is within [start_ms, end_ms] (both inclusive)."""

        params = {
            "symbol": symbol,
            "interval": interval,
            "startTime": start_ms,
            "endTime": end_ms,
            "limit": limit,
        }
        return self._get(KLINES_PATH, params)

    def _get(self, path: str, params: dict[str, Any]) -> Any:
        for attempt in range(1, self.max_attempts + 1):
            try:
                response = self._http.get(path, params=params)
            except httpx.TransportError as err:
                problem, wait = f"network error: {err}", backoff_seconds(attempt)
            else:
                if response.status_code == 200:
                    return response.json()
                if response.status_code not in RETRYABLE_STATUS:
                    raise SourceAPIError(
                        f"Binance {path} returned HTTP {response.status_code}: "
                        f"{response.text[:200]}"
                    )
                problem = f"HTTP {response.status_code}"
                wait = retry_after_seconds(response) or backoff_seconds(attempt)

            if attempt < self.max_attempts:
                logger.warning(
                    "Binance %s %s (attempt %d/%d), retrying in %.1fs",
                    path,
                    problem,
                    attempt,
                    self.max_attempts,
                    wait,
                )
                self._sleep(wait)

        raise SourceAPIError(f"Binance {path} failed after {self.max_attempts} attempts: {problem}")
