"""Define validated API request and response payloads.

TODO: Add query metadata, timing, and typed tabular results.
"""

from typing import Any, Literal

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    """Health endpoint response.

    TODO: Extend only if dependency readiness becomes part of this endpoint.
    """

    status: Literal["ok"]


class AskRequest(BaseModel):
    """Natural-language question submitted by a client.

    TODO: Add optional conversation and semantic-model identifiers.
    """

    question: str = Field(min_length=1, examples=["BTC ra sao khi lợi suất 10 năm > 4%?"])


class AskResponse(BaseModel):
    """Placeholder shape for a future agent answer.

    TODO: Finalize the contract after the graph output schema is implemented.
    """

    question: str
    status: Literal["stub", "ok", "error"] = "stub"
    sql: str | None = None
    result: list[dict[str, Any]] | None = None
    answer: str | None = None
    error: str | None = None
