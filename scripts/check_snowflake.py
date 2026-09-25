"""Show which Snowflake account, user, role and warehouse FinSight connects as.

Run from the repository root: make check-snowflake
"""

import logging
import sys

from src.common.config import get_settings
from src.common.exceptions import FinSightError
from src.common.logging_config import setup_logging
from src.services.snowflake_client import SnowflakeClient

logger = logging.getLogger(__name__)

CHECK_SQL = """
SELECT
    CURRENT_ACCOUNT()   AS account_name,
    CURRENT_USER()      AS user_name,
    CURRENT_ROLE()      AS role_name,
    CURRENT_WAREHOUSE() AS warehouse_name,
    CURRENT_DATABASE()  AS database_name,
    CURRENT_VERSION()   AS snowflake_version
"""


def main() -> int:
    setup_logging(get_settings().log_level)
    try:
        row = SnowflakeClient().execute(CHECK_SQL)[0]
    except FinSightError as err:
        logger.error("Snowflake check failed: %s", err)
        return 1

    for column, value in row.items():
        logger.info("%-18s %s", column, value)
    return 0


if __name__ == "__main__":
    sys.exit(main())
