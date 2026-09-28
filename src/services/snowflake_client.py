"""Encapsulate Snowflake connections and query execution."""

import logging
from typing import Any

import snowflake.connector
from snowflake.connector import DictCursor
from snowflake.connector.errors import Error as SnowflakeDriverError

from src.common.config import Settings, get_settings
from src.common.exceptions import WarehouseError

logger = logging.getLogger(__name__)


class SnowflakeClient:
    """Narrow Snowflake access layer shared by ingestion, scripts, and the agent."""

    def __init__(
        self,
        settings: Settings | None = None,
        query_tag: str = "finsight",
        statement_timeout_seconds: int | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.session_parameters: dict[str, Any] = {"QUERY_TAG": query_tag}
        if statement_timeout_seconds:
            # Snowflake itself cancels any statement running longer than this.
            self.session_parameters["STATEMENT_TIMEOUT_IN_SECONDS"] = statement_timeout_seconds

    def connect(self) -> Any:
        """Open a connection with key-pair auth."""

        s = self.settings
        s.require_snowflake()
        passphrase = s.snowflake_private_key_passphrase
        logger.info(
            "Connecting to Snowflake account=%s user=%s role=%s",
            s.snowflake_account,
            s.snowflake_user,
            s.snowflake_role,
        )
        try:
            return snowflake.connector.connect(
                account=s.snowflake_account,
                user=s.snowflake_user,
                role=s.snowflake_role,
                warehouse=s.snowflake_warehouse,
                database=s.snowflake_database,
                private_key_file=str(s.snowflake_private_key_path),
                private_key_file_pwd=passphrase.get_secret_value() if passphrase else None,
                session_parameters=self.session_parameters,
            )
        except SnowflakeDriverError as err:
            raise WarehouseError(f"Could not connect to Snowflake: {err}") from err

    def execute(
        self,
        sql: str,
        params: dict[str, Any] | None = None,
        max_rows: int | None = None,
    ) -> list[dict[str, Any]]:
        """Run one statement and return rows as dicts keyed by UPPERCASE column name.

        max_rows stops reading after that many rows, whatever the query returns.
        """

        with self.connect() as conn, conn.cursor(DictCursor) as cur:
            try:
                cur.execute(sql, params)
                return cur.fetchmany(max_rows) if max_rows else cur.fetchall()
            except SnowflakeDriverError as err:
                raise WarehouseError(f"Query failed: {err}") from err
