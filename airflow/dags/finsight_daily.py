"""FinSight daily pipeline: load new source data into RAW, then rebuild STAGING → CORE → MART.

Airflow only decides WHEN each step runs, in WHAT ORDER, and what to do on failure. Every step
is a command that already works by hand (make load-binance, make load-fred, make dbt-build), so
the business logic stays in src/ and dbt/, not in this file (spec §15).
"""

from datetime import UTC, datetime, timedelta

from airflow.providers.standard.operators.bash import BashOperator
from airflow.sdk import DAG

PROJECT_DIR = "/opt/finsight"  # the repo, mounted by airflow/docker-compose.yml
VENV = "/opt/finsight-venv/bin"  # FinSight's own packages, installed by airflow/Dockerfile


def dbt(command: str) -> str:
    """Shell command that runs dbt from the dbt project folder with FinSight's virtualenv."""

    return f"cd {PROJECT_DIR}/dbt && {VENV}/dbt {command}"


default_args = {
    "owner": "finsight",
    # A network blip or a Snowflake hiccup should not fail the whole day. The loaders and dbt
    # are idempotent (MERGE), so running a failed task again is always safe.
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
    # A step that hangs must fail, not block tomorrow's run forever.
    "execution_timeout": timedelta(minutes=45),
}

with DAG(
    dag_id="finsight_daily",
    description="Binance + FRED → RAW, then dbt STAGING → CORE → MART",
    # 00:30 UTC: the UTC day has just closed, so yesterday's last hourly candle is final.
    schedule="30 0 * * *",
    start_date=datetime(2026, 9, 1, tzinfo=UTC),
    # The loaders find their own starting point from the watermark in RAW, so Airflow never
    # needs to replay missed days one by one: after downtime, a single run catches up.
    catchup=False,
    # Two runs at once would read the same watermark and load the same window twice in parallel.
    max_active_runs=1,
    default_args=default_args,
    tags=["finsight"],
) as dag:
    load_binance = BashOperator(
        task_id="load_binance",
        bash_command=f"cd {PROJECT_DIR} && {VENV}/python -m scripts.load_binance",
    )

    load_fred = BashOperator(
        task_id="load_fred",
        bash_command=f"cd {PROJECT_DIR} && {VENV}/python -m scripts.load_fred",
    )

    # One task per layer: a failed test stops the layers above it, and the UI shows which
    # layer broke. `dbt deps` first, so a fresh clone works without a manual `make dbt-deps`.
    dbt_staging = BashOperator(
        task_id="dbt_build_staging",
        bash_command=dbt("deps") + " && " + dbt("build --select path:seeds path:models/staging"),
    )

    dbt_core = BashOperator(
        task_id="dbt_build_core",
        bash_command=dbt("build --select path:models/core"),
    )

    dbt_marts = BashOperator(
        task_id="dbt_build_marts",
        bash_command=dbt("build --select path:models/marts"),
    )

    # Both loads can run at the same time (different sources, different RAW tables);
    # dbt waits for both, then the layers go bottom-up.
    [load_binance, load_fred] >> dbt_staging >> dbt_core >> dbt_marts
