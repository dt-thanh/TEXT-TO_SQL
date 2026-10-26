"""Onboard the assets the owner added: verify with Binance, backfill, build, mark ready.

Started by the API right after a coin is added (Airflow REST API), with a daily run at 01:30 UTC
as the fallback when the trigger did not get through. Not more often: every run reads the
registry, and each read wakes the Snowflake warehouse for at least a minute of billing.

    load_requested_assets  claim <= 3 requested assets, verify, backfill (exit 99 -> skipped)
    dbt_build_assets       rebuild the Binance models so MART has the new asset
    finalize_assets        assets with daily rows in MART -> ready (then loaded daily)

The steps hand over through the registry status (src/control/onboarding.py), not XCom.
"""

from datetime import UTC, datetime, timedelta

from airflow.providers.standard.operators.bash import BashOperator
from airflow.sdk import DAG

PROJECT_DIR = "/opt/finsight"
VENV = "/opt/finsight-venv/bin"
BINANCE_POOL = "binance_api"  # shared with finsight_daily, created by airflow-init
DBT_POOL = "dbt"


def onboard(step: str) -> str:
    return f"cd {PROJECT_DIR} && {VENV}/python -m scripts.onboard_assets {step}"


with DAG(
    dag_id="finsight_asset_onboarding",
    description="Requested assets → verify → backfill → dbt → ready",
    schedule="30 1 * * *",
    start_date=datetime(2026, 10, 1, tzinfo=UTC),
    catchup=False,
    # Claims are guarded by status, but one run at a time keeps Binance and dbt calm.
    max_active_runs=1,
    # A trigger from the API must run without someone unpausing the DAG first.
    is_paused_upon_creation=False,
    default_args={
        "owner": "finsight",
        "retries": 1,
        "retry_delay": timedelta(minutes=2),
        "execution_timeout": timedelta(minutes=30),
    },
    tags=["finsight"],
) as dag:
    load = BashOperator(
        task_id="load_requested_assets", bash_command=onboard("load"), pool=BINANCE_POOL
    )
    build = BashOperator(
        task_id="dbt_build_assets",
        bash_command=(
            f"cd {PROJECT_DIR}/dbt && {VENV}/dbt deps && "
            f"{VENV}/dbt build --select binance_assets dim_asset+ stg_binance_kline+"
        ),
        pool=DBT_POOL,
    )
    finalize = BashOperator(task_id="finalize_assets", bash_command=onboard("finalize"))

    load >> build >> finalize
