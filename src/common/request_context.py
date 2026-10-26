"""The request being served: its id (for log lines and Snowflake QUERY_TAGs) and facts for its
CONTROL.REQUEST_LOG row. Context variables, so each request (thread) sees its own."""

import re
import uuid
from contextvars import ContextVar
from typing import Any

REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
NO_REQUEST = "-"

request_id_var: ContextVar[str] = ContextVar("request_id", default=NO_REQUEST)
request_facts_var: ContextVar[dict[str, Any] | None] = ContextVar("request_facts", default=None)


def new_request_id(given: str | None) -> str:
    """Keep a caller's id when it is safe to log; otherwise make one."""

    if given and REQUEST_ID_PATTERN.match(given):
        return given
    return uuid.uuid4().hex


def note(**facts: Any) -> None:
    """Add facts about the current request to its log row (no-op outside a request)."""

    current = request_facts_var.get()
    if current is not None:
        current.update(facts)
