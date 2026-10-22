"""The HTTP contract of the API: what a client sends and receives (spec §33 "FastAPI").

Pydantic checks the request before any code runs (an empty or 5,000-character question is a 422,
not an LLM call) and documents both shapes at /docs.
"""

from datetime import date
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
    total_seconds: float  # the whole question, metadata lookup included
    data_as_of: date | None  # newest finished UTC day in the data: answers stop there


class Finding(BaseModel):
    claim: str
    evidence_ids: list[str]


class EvidenceValue(BaseModel):
    column: str
    value: float | str | None  # str for dates
    unit: str
    description: str


class Evidence(BaseModel):
    """One verified metric result: the SQL that produced it and its values."""

    id: str
    metric_id: str
    metric_name: str
    params: dict[str, str]
    sql: str
    sources: list[str]
    data_window: str
    n: int | None
    values: list[EvidenceValue]
    pit_mode: str | None
    usable: bool  # False: too few observations, not used by the findings


class PlanStep(BaseModel):
    metric_id: str
    params: dict[str, str]
    status: str  # done | failed | insufficient_data | skipped
    reason: str | None = None


class ResearchResponse(BaseModel):
    """A research answer. `status` is decided by code from what ran:

    - complete: every planned metric ran with enough data and every finding is grounded;
    - partial: a metric failed or was skipped, or a finding was dropped (a number not in the
      evidence);
    - insufficient_data: metrics ran but none had enough observations;
    - declined: no catalog metric answers the question (`decline_reason` says why);
    - error: nothing could run.
    Every number in `findings` comes from `evidence`, whose SQL is included.
    """

    question: str
    status: Literal["complete", "partial", "insufficient_data", "declined", "error"]
    findings: list[Finding]
    evidence: list[Evidence]
    caveats: list[str]
    plan: list[PlanStep]
    decline_reason: str
    analysis_window: list[str] | None  # [start, end]
    data_as_of: date | None
    usage: Usage
    llm_seconds: float
    sql_seconds: float
    total_seconds: float
    report_markdown: str

