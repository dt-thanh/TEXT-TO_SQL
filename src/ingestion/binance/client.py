"""HTTP client for Binance's public spot market-data API."""

import time
from collections.abc import Callable
from typing import Any

import httpx

from src.common.config import get_settings
from src.ingestion.retrying_http import get_json

KLINES_PATH = "/api/v3/klines"
MAX_KLINES_PER_REQUEST = 1000


class BinanceClient:
    """Fetch raw kline rows from Binance, retrying temporary failures (see retrying_http)."""

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
        return get_json(
            self._http,
            KLINES_PATH,
            params,
            source="Binance",
            max_attempts=self.max_attempts,
            sleep=self._sleep,
        )
