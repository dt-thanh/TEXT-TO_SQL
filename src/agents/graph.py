"""The Text-to-SQL workflow as a LangGraph state machine, with a bounded repair loop (spec §20).

    START → retrieve_context → generate_sql ─(no SQL: cannot answer)─────────────────→ END
                                    │
                                    ▼
             ┌──────────────→ validate_sql ─(final violation / no repairs left)──→ END
             │                  │        │
             │           (fixable error) (valid)
             │                  │        ▼
        repair_sql ◄────────────┘   execute_sql ─(rows, or unfixable error)──────→ END
          │  ▲                             │
          │  └───────(compilation error, repairs left)
          └─(no SQL: gave up)────────────────────────────────────────────────────→ END

Every path ends: each repair increases `repairs`, and no repair starts once it reaches
max_repairs. LangGraph's recursion_limit (25 steps by default in the pinned 0.4.5; newer
versions default higher) is only the last safety net.
"""

from functools import partial
from typing import Any, Literal

from langgraph.graph import END, START, StateGraph

from src.agents.nodes.execute_sql import execute_sql
from src.agents.nodes.generate_sql import generate_sql
from src.agents.nodes.repair_sql import repair_sql
from src.agents.nodes.retrieve_context import retrieve_context
from src.agents.nodes.validate_sql import validate_sql
from src.agents.state import AgentState

# Each repair is one more LLM call (~$0.0004) and a few seconds. Two fixes most slips; a model
# that failed three times on the same question is unlikely to succeed on the fourth.
MAX_REPAIRS = 2


def route_after_writing(state: AgentState) -> Literal["validate", "end"]:
    """An empty SQL means the model decided the data cannot answer the question."""

    return "validate" if state.get("sql") else "end"


def route_after_check(
    state: AgentState, *, on_success: str, max_repairs: int
) -> Literal["execute", "repair", "end"]:
    """After validation or execution: go on, repair, or stop."""

    if state.get("error") is None:
        return on_success
    if state.get("retryable") and state.get("repairs", 0) < max_repairs:
        return "repair"
    return "end"


def build_graph(llm: Any, warehouse: Any, max_rows: int, max_repairs: int = MAX_REPAIRS) -> Any:
    """Compile the graph for one LLM client and one warehouse connection."""

    builder = StateGraph(AgentState)
    builder.add_node("retrieve_context", partial(retrieve_context, warehouse=warehouse))
    builder.add_node("generate_sql", partial(generate_sql, llm=llm))
    builder.add_node("validate_sql", partial(validate_sql, max_rows=max_rows))
    builder.add_node("execute_sql", partial(execute_sql, warehouse=warehouse, max_rows=max_rows))
    builder.add_node("repair_sql", partial(repair_sql, llm=llm))

    builder.add_edge(START, "retrieve_context")
    builder.add_edge("retrieve_context", "generate_sql")
    for writer in ("generate_sql", "repair_sql"):
        builder.add_conditional_edges(
            writer, route_after_writing, {"validate": "validate_sql", "end": END}
        )
    builder.add_conditional_edges(
        "validate_sql",
        partial(route_after_check, on_success="execute", max_repairs=max_repairs),
        {"execute": "execute_sql", "repair": "repair_sql", "end": END},
    )
    builder.add_conditional_edges(
        "execute_sql",
        partial(route_after_check, on_success="end", max_repairs=max_repairs),
        {"repair": "repair_sql", "end": END},
    )
    return builder.compile()
