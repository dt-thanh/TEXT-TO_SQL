"""HTTP client for the FRED API (Federal Reserve Bank of St. Louis)."""

import time
from collections.abc import Callable
from datetime import date
from typing import Any

import httpx

from src.common.config import get_settings
from src.common.exceptions import ConfigError
from src.ingestion.retrying_http import get_json

FRED_BASE_URL = "https://api.stlouisfed.org/fred"
MAX_OBSERVATIONS_PER_REQUEST = 100_000
# output_type=3: "observations by vintage date, new and revised observations only".
# Each value comes back tagged with the date FRED first published it, e.g. "DGS10_20241223",
# and asking for a slice of real time never invents vintages at the slice edges.
NEW_AND_REVISED_ONLY = 3


class FredClient:
    """Fetch series metadata and observation changes from FRED.

    The API key travels as a query parameter, so it is part of every request URL.
    retrying_http never puts URLs in error messages and masks the key if it shows up.
    """

    def __init__(
        self,
        http: httpx.Client | None = None,
        api_key: str | None = None,
        max_attempts: int = 5,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if api_key is None:
            api_key = get_settings().fred_api_key.get_secret_value()
        self._api_key = api_key
        if not self._api_key:
            raise ConfigError("Missing FRED_API_KEY in .env")
        self._http = http or httpx.Client(base_url=FRED_BASE_URL, timeout=30.0)
        self.max_attempts = max_attempts
        self._sleep = sleep

    def __enter__(self) -> "FredClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        self._http.close()

    def get_series(self, series_id: str) -> dict[str, Any]:
        """Raw /series payload: title, frequency, units, last_updated, ..."""

        return self._get("/series", {"series_id": series_id})

    def get_observation_changes(
        self,
        series_id: str,
        observation_start: date,
        realtime_start: date,
        realtime_end: date,
        offset: int = 0,
        limit: int = MAX_OBSERVATIONS_PER_REQUEST,
    ) -> dict[str, Any]:
        """Raw /series/observations payload of values first published or revised in the window."""

        return self._get(
            "/series/observations",
            {
                "series_id": series_id,
                "observation_start": observation_start.isoformat(),
                "realtime_start": realtime_start.isoformat(),
                "realtime_end": realtime_end.isoformat(),
                "output_type": NEW_AND_REVISED_ONLY,
                "offset": offset,
                "limit": limit,
            },
        )

    def _get(self, path: str, params: dict[str, Any]) -> Any:
        return get_json(
            self._http,
            path,
            {**params, "api_key": self._api_key, "file_type": "json"},
            source="FRED",
            max_attempts=self.max_attempts,
            sleep=self._sleep,
            secrets=(self._api_key,),
        )
