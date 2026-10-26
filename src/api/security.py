"""Access, rate limits and request ids for a single-owner API (spec v1.1, 6.3-6.4).

AUTH_MODE=local: the API and UI listen on 127.0.0.1 only (Makefile, docker-compose.yml), so no
key is asked. AUTH_MODE=deployed: every route except /health needs X-API-Key equal to
FINSIGHT_SERVICE_KEY, and the app refuses to start without one (fail closed). There are no users
or roles: one owner, one key, kept server-side by the UI.

Rate limits are global and in this process (one instance). They stop a looping client or
script from spending the LLM budget in a minute, not a person.
"""

import hmac
import threading
import time
from collections import deque
from collections.abc import Callable
from typing import Annotated

from fastapi import Header, HTTPException

from src.common.config import Settings, get_settings
from src.common.exceptions import ConfigError
from src.common.request_context import new_request_id, note, request_facts_var, request_id_var

__all__ = ["new_request_id", "note", "request_facts_var", "request_id_var"]


def check_startup(settings: Settings) -> None:
    if settings.auth_mode == "deployed" and not settings.finsight_service_key.get_secret_value():
        raise ConfigError("AUTH_MODE=deployed needs FINSIGHT_SERVICE_KEY: refusing to start")


def require_access(x_api_key: Annotated[str | None, Header()] = None) -> None:
    settings = get_settings()
    if settings.auth_mode == "local":
        return
    expected = settings.finsight_service_key.get_secret_value()
    # Constant-time comparison: the time taken says nothing about how much of the key matched.
    if not x_api_key or not hmac.compare_digest(x_api_key.encode(), expected.encode()):
        raise HTTPException(status_code=401, detail="missing or wrong API key")


class RateLimiter:
    """At most `limit` calls per `period` seconds, over a sliding window."""

    def __init__(
        self, limit: int, period: float, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self.limit, self.period, self.clock = limit, period, clock
        self._calls: deque[float] = deque()
        self._lock = threading.Lock()

    def check(self) -> None:
        with self._lock:
            now = self.clock()
            while self._calls and now - self._calls[0] >= self.period:
                self._calls.popleft()
            if len(self._calls) >= self.limit:
                retry = max(1, int(self.period - (now - self._calls[0])) + 1)
                raise HTTPException(
                    status_code=429,
                    detail=f"too many requests: at most {self.limit} per {int(self.period)} s",
                    headers={"Retry-After": str(retry)},
                )
            self._calls.append(now)


LIMITS = {
    "ask": RateLimiter(30, 60),
    "research": RateLimiter(6, 60),
    "brief": RateLimiter(6, 60),
    "watchlist_write": RateLimiter(30, 3600),
}


def rate_limit(name: str) -> Callable[[], None]:
    def dependency() -> None:
        LIMITS[name].check()

    return dependency
