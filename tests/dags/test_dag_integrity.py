"""The DAG files import cleanly and finsight_daily keeps its intended shape.

A mistake in a DAG file fails no other test: Airflow only shows an import error in its UI and
the daily pipeline quietly stops running. This test parses airflow/dags the way the
dag-processor does. It needs Airflow itself, which the project's virtualenv does not install
(the Airflow image has its own); the CI "dags" job installs it, everywhere else it is skipped.
"""

from pathlib import Path

import pytest

# Ask for the submodule, not "airflow": the repository's own airflow/ folder (Dockerfile, dags/)
# is importable as a namespace package named "airflow" even where Airflow is not installed.
# An installed Airflow is a regular package and wins over that folder.
pytest.importorskip("airflow.dag_processing.dagbag", reason="Apache Airflow is not installed here")

# Airflow 3 location (airflow.models.dagbag is deprecated); example DAGs are no longer loaded.
from airflow.dag_processing.dagbag import DagBag  # noqa: E402  (only importable when Airflow is)

DAGS_FOLDER = Path(__file__).resolve().parents[2] / "airflow" / "dags"


@pytest.fixture(scope="module")
def dagbag() -> DagBag:
    return DagBag(dag_folder=str(DAGS_FOLDER))


def test_every_dag_file_imports_without_errors(dagbag: DagBag) -> None:
    assert dagbag.import_errors == {}
    assert {"finsight_daily", "finsight_asset_onboarding"} <= set(dagbag.dags)


def test_the_daily_pipeline_runs_its_steps_in_order(dagbag: DagBag) -> None:
    dag = dagbag.dags["finsight_daily"]

    downstream = {task.task_id: sorted(task.downstream_task_ids) for task in dag.tasks}

    assert downstream == {
        "load_binance": ["check_source_freshness"],
        "load_fred": ["check_source_freshness"],
        "load_defillama": ["check_source_freshness"],
        "check_source_freshness": ["dbt_build_staging"],
        "dbt_build_staging": ["dbt_build_core"],
        "dbt_build_core": ["dbt_build_marts"],
        "dbt_build_marts": ["generate_daily_brief"],
        "generate_daily_brief": [],
        "refresh_binance_catalog": [],
    }


def test_onboarding_loads_then_builds_then_marks_ready(dagbag: DagBag) -> None:
    dag = dagbag.dags["finsight_asset_onboarding"]

    downstream = {task.task_id: sorted(task.downstream_task_ids) for task in dag.tasks}

    assert downstream == {
        "load_requested_assets": ["dbt_build_assets"],
        "dbt_build_assets": ["finalize_assets"],
        "finalize_assets": [],
    }
    assert dag.max_active_runs == 1


def test_both_dags_share_one_binance_job_and_one_dbt_build_at_a_time(dagbag: DagBag) -> None:
    pools = {
        (dag_id, task.task_id): task.pool
        for dag_id in ("finsight_daily", "finsight_asset_onboarding")
        for task in dagbag.dags[dag_id].tasks
    }

    assert {k for k, pool in pools.items() if pool == "binance_api"} == {
        ("finsight_daily", "load_binance"),
        ("finsight_daily", "refresh_binance_catalog"),
        ("finsight_asset_onboarding", "load_requested_assets"),
    }
    assert {k for k, pool in pools.items() if pool == "dbt"} == {
        ("finsight_daily", "dbt_build_staging"),
        ("finsight_daily", "dbt_build_core"),
        ("finsight_daily", "dbt_build_marts"),
        ("finsight_asset_onboarding", "dbt_build_assets"),
    }


def test_the_daily_pipeline_never_overlaps_or_replays_missed_days(dagbag: DagBag) -> None:
    # The loaders find their own window from the watermark: replaying days would only reload
    # the same data, and two runs at once would load the same window twice.
    dag = dagbag.dags["finsight_daily"]

    assert dag.catchup is False
    assert dag.max_active_runs == 1
    # The brief retries once only: each attempt may spend LLM budget.
    retries = {task.task_id: task.retries for task in dag.tasks if task.retries != 2}
    assert retries == {"generate_daily_brief": 1}
