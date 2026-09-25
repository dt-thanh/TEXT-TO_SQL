"""Smoke-test the executable LangGraph skeleton.

TODO: Cover validation failures, execution failures, and exhausted retries.
"""

from src.agents.graph import graph


def test_stub_graph_reaches_explanation() -> None:
    """Verify that the placeholder happy path reaches its terminal node.

    TODO: Replace placeholder assertions when node implementations are added.
    """

    result = graph.invoke({"question": "Câu hỏi thử nghiệm", "max_retries": 2})

    assert result["execution_succeeded"] is True
    assert result["explanation"].startswith("TODO:")
