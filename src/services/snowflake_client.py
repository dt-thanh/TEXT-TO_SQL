"""Encapsulate Snowflake connections and query execution.

Two ways to connect:
- one connection per execute() (default): simplest, for scripts that run a few statements;
- keep_connection=True: one connection opened on first use and reused, for the agent and the
  API. A key-pair login costs about 2 seconds, and a question runs two or more statements.
  The connector allows one connection to be shared by several threads (each call below uses
  its own cursor), and keep-alive heartbeats stop the idle session from expiring.
"""

import logging
import threading
from typing import Any

import snowflake.connector
from snowflake.connector import DictCursor
from snowflake.connector.errors import Error as SnowflakeDriverError

from src.common.config import Settings, get_settings
from src.common.exceptions import WarehouseError

logger = logging.getLogger(__name__)

# Driver error numbers meaning the session is gone rather than the SQL being wrong:
# 250002 connection is closed, 390112 session expired, 390114 authentication token expired.
SESSION_GONE_ERRNOS = {250002, 390112, 390114}


def refuse_duplicate_columns(description: Any) -> None:
    """Rows come back as dicts keyed by column name: a second column with the same name would
    silently replace the first. Refuse such a result instead of returning half of it."""

    names = [column[0] for column in description or []]
    duplicates = sorted({name for name in names if names.count(name) > 1})
    if duplicates:
        raise WarehouseError(
            f"Query returned duplicate column names: {', '.join(duplicates)}. "
            "Give every column a unique alias."
        )


def run_query(conn: Any, sql: str, params: Any, max_rows: int | None) -> list[dict[str, Any]]:
    with conn.cursor(DictCursor) as cur:
        cur.execute(sql, params)
        refuse_duplicate_columns(cur.description)
        return cur.fetchmany(max_rows) if max_rows else cur.fetchall()


class SnowflakeClient:
    """Narrow Snowflake access layer shared by ingestion, scripts, and the agent."""

    def __init__(
        self,
        settings: Settings | None = None,
        query_tag: str = "finsight",
        statement_timeout_seconds: int | None = None,
        keep_connection: bool = False,
    ) -> None:
        self.settings = settings or get_settings()
        self.session_parameters: dict[str, Any] = {"QUERY_TAG": query_tag}
        if statement_timeout_seconds:
            # Snowflake itself cancels any statement running longer than this.
            self.session_parameters["STATEMENT_TIMEOUT_IN_SECONDS"] = statement_timeout_seconds
        self.keep_connection = keep_connection
        self._connection: Any = None
        self._lock = threading.Lock()  # two threads must not both open "the" connection

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
                client_session_keep_alive=self.keep_connection,
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

        try:
            if not self.keep_connection:
                with self.connect() as conn:
                    return run_query(conn, sql, params, max_rows)
            try:
                return run_query(self._shared_connection(), sql, params, max_rows)
            except SnowflakeDriverError as err:
                if err.errno not in SESSION_GONE_ERRNOS:
                    raise
                # The session died (e.g. hours idle): log in again and run the query once more.
                logger.warning("Snowflake session is gone (%s); reconnecting", err.errno)
                self.close()
                return run_query(self._shared_connection(), sql, params, max_rows)
        except SnowflakeDriverError as err:
            raise WarehouseError(f"Query failed: {err}") from err

    def close(self) -> None:
        """Close the kept connection, if any. The next execute() opens a new one."""

        with self._lock:
            if self._connection is not None:
                try:
                    self._connection.close()
                except SnowflakeDriverError:
                    pass  # it may already be dead; there is nothing left to release
                self._connection = None

    def _shared_connection(self) -> Any:
        with self._lock:
            if self._connection is None or self._connection.is_closed():
                self._connection = self.connect()
            return self._connection
