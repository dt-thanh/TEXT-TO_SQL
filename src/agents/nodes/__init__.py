"""The nodes of the Text-to-SQL graph (src/agents/graph.py), one step each.

A node takes the state and returns only the keys it changes. Dependencies (LLM, warehouse, limits)
are keyword-only arguments, bound with functools.partial when the graph is built, so tests can pass
fakes and no node reaches for a global client.
"""
