"""Define state shared by all Text-to-SQL graph nodes.

TODO: Refine result and error types once execution contracts are stable.
"""

from typing import Any, TypedDict


class AgentState(TypedDict, total=False):
    """Mutable state for generate, validate, execute, repair, and explain steps.

    TODO: Add message history and structured observability fields if needed.
    """

    question: str
    schema_context: str
    sql: str
    validated_sql: str
    result: list[dict[str, Any]]
    explanation: str
    error: str | None
    retries: int
    max_retries: int
    validation_passed: bool
    execution_succeeded: bool
