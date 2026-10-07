# One image for the Airflow orchestrator, the pipeline CLI and the Streamlit dashboard.
# The pipeline (pandas, dbt, Streamlit) lives in its own virtualenv at /opt/claims-dw/venv so it
# never conflicts with Airflow's pinned dependencies.
FROM apache/airflow:3.3.2-python3.12

USER root
RUN mkdir -p /opt/claims-dw/data /opt/claims-dw/reports \
    && chown -R airflow:root /opt/claims-dw
USER airflow

ENV CLAIMS_DW_HOME=/opt/claims-dw
WORKDIR /opt/claims-dw

# Locked, hash-checked dependencies exported from uv.lock (`make lock`).
COPY --chown=airflow:root requirements.lock.txt ./
RUN python -m venv /opt/claims-dw/venv \
    && /opt/claims-dw/venv/bin/pip install --no-cache-dir --require-hashes -r requirements.lock.txt

COPY --chown=airflow:root pyproject.toml README.md ./
COPY --chown=airflow:root src ./src
RUN /opt/claims-dw/venv/bin/pip install --no-cache-dir --no-deps .

COPY --chown=airflow:root config ./config
COPY --chown=airflow:root migrations ./migrations
COPY --chown=airflow:root dbt ./dbt
COPY --chown=airflow:root app ./app
COPY --chown=airflow:root scripts/check_dag.py ./scripts/check_dag.py
COPY --chown=airflow:root dags /opt/airflow/dags
