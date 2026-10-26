"""GET JSON from a public data API, retrying temporary failures. Shared by every source."""

import logging
from collections.abc import Callable
from typing import Any

import httpx

from src.common.exceptions import SourceAPIError

logger = logging.getLogger(__name__)

# 429 = rate limited, 5xx = server-side trouble: both are temporary, so wait and retry.
# Anything else fails at once: a 400 (bad parameter) will not fix itself, and Binance's 418
# means the IP is already banned for ignoring 429s, so retrying would only extend the ban.
RETRYABLE_STATUS = {429, 500, 502, 503, 504}
MAX_BACKOFF_SECONDS = 60.0


def backoff_seconds(attempt: int) -> float:
    """Wait 1s, 2s, 4s, ... (capped) when the server does not say how long to wait."""

    return min(2.0 ** (attempt - 1), MAX_BACKOFF_SECONDS)


def retry_after_seconds(response: httpx.Response) -> float | None:
    """Seconds the server asked us to wait via the Retry-After header, if present."""

    try:
        return float(response.headers["Retry-After"])
    except (KeyError, ValueError):
        return None


def get_json(
    http: httpx.Client,
    path: str,
    params: dict[str, Any],
    *,
    source: str,
    max_attempts: int,
    sleep: Callable[[float], None],
    secrets: tuple[str, ...] = (),
) -> Any:
    """GET `path` and return the JSON body, retrying network errors, 429, 5xx and non-JSON 200s.

    Error messages end up in logs, so they never contain the request URL (it carries the
    query string, API key included), and every value in `secrets` is masked as ***.
    Only GET is used, so retrying is always safe.
    """

    def masked(text: str) -> str:
        for secret in secrets:
            if secret:
                text = text.replace(secret, "***")
        return text

    for attempt in range(1, max_attempts + 1):
        try:
            response = http.get(path, params=params)
        except httpx.TransportError as err:
            problem, wait = f"network error: {masked(str(err))}", backoff_seconds(attempt)
        else:
            if response.status_code == 200:
                try:
                    return response.json()
                except ValueError:
                    # A maintenance page served with 200 (seen on FRED, 2026-10) is temporary:
                    # retry it like a 5xx instead of crashing with a raw JSONDecodeError.
                    content_type = response.headers.get("content-type", "unknown")
                    problem = f"HTTP 200 without JSON (content-type {content_type})"
                    wait = backoff_seconds(attempt)
            elif response.status_code in RETRYABLE_STATUS:
                problem = f"HTTP {response.status_code}"
                wait = retry_after_seconds(response) or backoff_seconds(attempt)
            else:
                raise SourceAPIError(
                    masked(
                        f"{source} {path} returned HTTP {response.status_code}: "
                        f"{response.text[:200]}"
                    ),
                    status_code=response.status_code,
                )

        if attempt < max_attempts:
            logger.warning(
                "%s %s %s (attempt %d/%d), retrying in %.1fs",
                source,
                path,
                problem,
                attempt,
                max_attempts,
                wait,
            )
            sleep(wait)

    raise SourceAPIError(f"{source} {path} failed after {max_attempts} attempts: {problem}")
