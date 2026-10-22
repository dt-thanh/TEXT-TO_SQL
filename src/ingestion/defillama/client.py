"""HTTP client for DefiLlama's free TVL API (no API key).

Endpoints (https://api-docs.defillama.com/llms-free.txt):
- /v2/historicalChainTvl/{chain}: daily TVL of one chain;
- /v2/historicalChainTvl: daily TVL of DeFi on all chains together.
Both exclude liquid staking and double-counted TVL, by DefiLlama's own method.
"""

import time
from collections.abc import Callable
from typing import Any
from urllib.parse import quote

import httpx

from src.ingestion.retrying_http import get_json

DEFILLAMA_BASE_URL = "https://api.llama.fi"
CHAIN_TVL_PATH = "/v2/historicalChainTvl"
# Our name for "every chain together", which the API serves without a chain in the path.
ALL_CHAINS = "All"


class DefiLlamaClient:
    """Fetch raw daily TVL points, retrying temporary failures (see retrying_http)."""

    def __init__(
        self,
        http: httpx.Client | None = None,
        max_attempts: int = 5,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._http = http or httpx.Client(base_url=DEFILLAMA_BASE_URL, timeout=30.0)
        self.max_attempts = max_attempts
        self._sleep = sleep

    def __enter__(self) -> "DefiLlamaClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        self._http.close()

    def get_chain_tvl(self, chain: str) -> list[dict[str, Any]]:
        """Raw points [{"date": unix seconds at 00:00 UTC, "tvl": USD}, ...], oldest first."""

        path = CHAIN_TVL_PATH if chain == ALL_CHAINS else f"{CHAIN_TVL_PATH}/{quote(chain)}"
        return get_json(
            self._http,
            path,
            {},
            source="DefiLlama",
            max_attempts=self.max_attempts,
            sleep=self._sleep,
        )
