"""Start an Airflow DAG run through Airflow 3's REST API (POST /api/v2/dags/{id}/dagRuns).

Used to begin asset onboarding as soon as the owner adds a coin. It is best effort: if Airflow is
not running or refuses, the request still succeeds and the DAG's daily schedule picks the asset
up. Claiming in the DAG is guarded by the registry status, so extra runs never load twice.
"""

import logging

import httpx

from src.common.config import Settings, get_settings

logger = logging.getLogger(__name__)

ONBOARDING_DAG = "finsight_asset_onboarding"
TIMEOUT_SECONDS = 5.0


def trigger_dag(
    dag_id: str = ONBOARDING_DAG,
    settings: Settings | None = None,
    http: httpx.Client | None = None,
) -> bool:
    """True when Airflow accepted a new run. Never raises: problems are logged and False."""

    s = settings or get_settings()
    if not s.airflow_api_url:
        logger.info("AIRFLOW_API_URL is not set: %s will start on its schedule", dag_id)
        return False
    client = http or httpx.Client(base_url=s.airflow_api_url.rstrip("/"), timeout=TIMEOUT_SECONDS)
    try:
        token = client.post(
            "/auth/token",
            json={
                "username": s.airflow_api_user,
                "password": s.airflow_api_password.get_secret_value(),
            },
        )
        token.raise_for_status()
        response = client.post(
            f"/api/v2/dags/{dag_id}/dagRuns",
            json={"logical_date": None},
            headers={"Authorization": f"Bearer {token.json()['access_token']}"},
        )
        response.raise_for_status()
    except (httpx.HTTPError, KeyError, ValueError) as err:
        # The message names the endpoint and status only: no credentials, no token.
        logger.warning("Could not start %s through Airflow: %s", dag_id, type(err).__name__)
        return False
    finally:
        if http is None:
            client.close()
    logger.info("Started %s: run %s", dag_id, response.json().get("dag_run_id"))
    return True
