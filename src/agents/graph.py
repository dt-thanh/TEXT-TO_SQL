"""Build the LangGraph state machine for the Text-to-SQL workflow.

TODO: Inject configured node dependencies and persist graph checkpoints.
"""

from typing import Literal

from langgraph.graph import END, START, StateGraph

from src.agents.nodes.execute_sql import execute_sql
from src.agents.nodes.explain_result import explain_result
from src.agents.nodes.generate_sql import generate_sql
from src.agents.nodes.repair_sql import repair_sql
from src.agents.nodes.validate_sql import validate_sql
from src.agents.state import AgentState


def route_after_validation(state: AgentState) -> Literal["execute", "repair", "end"]:
    """Choose the next stub node after SQL validation.

    TODO: Standardize terminal validation errors and retry-budget handling.
    """

    if state.get("validation_passed"):
        return "execute"
    if state.get("retries", 0) < state.get("max_retries", 2):
        return "repair"
    return "end"


def route_after_execution(state: AgentState) -> Literal["explain", "repair", "end"]:
    """Route execution errors into self-repair while retries remain.

    TODO: Classify retryable Snowflake errors instead of checking one flag.
    """

    if state.get("execution_succeeded") and not state.get("error"):
        return "explain"
    if state.get("retries", 0) < state.get("max_retries", 2):
        return "repair"
    return "end"


def build_graph():
    """Compile the skeleton StateGraph with a self-repair loop.

    TODO: Add async nodes, tracing, timeouts, and dependency injection.
    """

    builder = StateGraph(AgentState)
    builder.add_node("generate_sql", generate_sql)
    builder.add_node("validate_sql", validate_sql)
    builder.add_node("execute_sql", execute_sql)
    builder.add_node("repair_sql", repair_sql)
    builder.add_node("explain_result", explain_result)

    builder.add_edge(START, "generate_sql")
    builder.add_edge("generate_sql", "validate_sql")
    builder.add_conditional_edges(
        "validate_sql",
        route_after_validation,
        {"execute": "execute_sql", "repair": "repair_sql", "end": END},
    )
    # Required self-repair branch: execution errors return to repair_sql.
    builder.add_conditional_edges(
        "execute_sql",
        route_after_execution,
        {"explain": "explain_result", "repair": "repair_sql", "end": END},
    )
    builder.add_edge("repair_sql", "validate_sql")
    builder.add_edge("explain_result", END)
    return builder.compile()


graph = build_graph()
