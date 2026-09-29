"""The HTTP contract of the API: what a client sends and receives (spec §33 "FastAPI").

Pydantic checks the request before any code runs (an empty or 5,000-character question is a 422,
not an LLM call) and documents both shapes at /docs.
"""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, StringConstraints

# Long enough for any real question; short enough that nobody pastes a book into the prompt.
MAX_QUESTION_CHARS = 500


class HealthResponse(BaseModel):
    status: Literal["ok"]


class AskRequest(BaseModel):
    question: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_QUESTION_CHARS)
    ]


class Usage(BaseModel):
    input_tokens: int
    output_tokens: int
    cost_usd: float


class FailedAttempt(BaseModel):
    sql: str
    error: str


class Chart(BaseModel):
    kind: Literal["line", "bar"]
    x: str
    y: list[str]
    color: str | None = None


class AskResponse(BaseModel):
    """One answer. `status` says how the agent's work ended:

    - answered: the SQL ran; `rows` holds the result (possibly empty);
    - declined: the data cannot answer the question; `explanation` says why, `sql` is empty;
    - blocked: the SQL guard refused the last SQL; nothing ran;
    - failed: Snowflake rejected the last SQL after the allowed repairs.
    The SQL is returned in every case where the model wrote one (spec §3.1).
    """

    question: str
    status: Literal["answered", "declined", "blocked", "failed"]
    sql: str
    explanation: str  # how this SQL works, or why the data cannot answer
    columns: list[str]
    rows: list[dict[str, Any]]  # JSON values only: numbers, strings, ISO dates, null
    truncated: bool
    chart: Chart | None
    error: str | None
    violations: list[str]
    repairs: int
    failed_attempts: list[FailedAttempt]
    retrieved: list[str]
    usage: Usage
    llm_seconds: float
    sql_seconds: float
