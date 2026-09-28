# Airflow image for FinSight: the official Airflow image plus FinSight's own Python packages.
#
# FinSight's packages (snowflake-connector, dbt, httpx, ...) go into a SEPARATE virtualenv,
# /opt/finsight-venv. Airflow pins hundreds of packages of its own; installing ours next to them
# would risk version clashes. DAG tasks call /opt/finsight-venv/bin/python and .../dbt, so the
# two worlds never mix. The project code itself is mounted at run time (docker-compose.yml).
FROM apache/airflow:3.3.2-python3.11

USER root
RUN mkdir -p /opt/finsight-venv && chown airflow:0 /opt/finsight-venv

USER airflow
RUN python -m venv /opt/finsight-venv \
    && /opt/finsight-venv/bin/pip install --no-cache-dir --upgrade pip

# dbt-core needs dbt-core-experimental-parser, which PyPI ships only as a small source package
# whose installer downloads a 55 MB prebuilt binary from GitHub (60 s timeout). On a slow link
# that download can fail, so it gets its own step with up to 3 attempts. Docker caches each
# step: once this one succeeds, rebuilds skip the download. Keep the version equal to .venv's.
RUN for attempt in 1 2 3; do \
        /opt/finsight-venv/bin/pip install --no-cache-dir "dbt-core-experimental-parser==2.0.5" \
        && exit 0; \
        echo "download failed (attempt ${attempt}/3), retrying in 10s"; sleep 10; \
    done; exit 1

COPY requirements.txt /tmp/finsight-requirements.txt
RUN /opt/finsight-venv/bin/pip install --no-cache-dir -r /tmp/finsight-requirements.txt
