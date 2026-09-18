"""Retrieve Snowflake schema metadata for LLM context.

TODO: Query GET_DDL or INFORMATION_SCHEMA and cache sanitized metadata.
"""

from src.services.snowflake_client import SnowflakeClient


def get_schema_context(client: SnowflakeClient) -> str:
    """Declare the schema-context tool contract without querying Snowflake.

    TODO: Return compact table, column, key, and description metadata.
    """

    _ = client
    raise NotImplementedError("TODO: implement Snowflake schema introspection")
