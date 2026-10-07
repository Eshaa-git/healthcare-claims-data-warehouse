"""Airflow DAG: acquire -> cohort -> stage -> dbt run -> dbt test -> reconcile -> publish.

Each task runs one `claims-dw` step in the pipeline's own virtualenv, so Airflow's dependencies
and the pipeline's (pandas, dbt) never share an environment. Only transient failures (exit code
75: network or database unavailable) are retried; data, contract and check failures fail the
task immediately. Publication happens only if every upstream task succeeded, so a failed run
leaves the last published marts untouched.
"""

from __future__ import annotations

import re
import subprocess
from datetime import datetime, timedelta

from airflow.exceptions import AirflowException, AirflowFailException
from airflow.sdk import dag, get_current_context, task

CLI = "/opt/claims-dw/venv/bin/claims-dw"
EXIT_TRANSIENT = 75
STEPS = ["acquire", "cohort", "stage", "dbt-run", "dbt-test", "reconcile", "publish"]


def pipeline_run_id() -> str:
    """Stable per DAG run, safe for file names and SQL text."""
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", get_current_context()["run_id"])


def run_step(step: str) -> None:
    result = subprocess.run(
        [CLI, step, "--run-id", pipeline_run_id()], capture_output=True, text=True, check=False
    )
    print(result.stdout)
    print(result.stderr)
    if result.returncode == 0:
        return
    if result.returncode == EXIT_TRANSIENT:
        raise AirflowException(f"{step}: transient failure (exit 75); eligible for retry")
    raise AirflowFailException(f"{step}: failed with exit code {result.returncode}; not retried")


@dag(
    dag_id="claims_pipeline",
    schedule=None,
    start_date=datetime(2026, 1, 1),
    catchup=False,
    max_active_runs=1,
    default_args={"retries": 2, "retry_delay": timedelta(seconds=30)},
    tags=["healthcare", "claims", "dbt"],
    doc_md=__doc__,
)
def claims_pipeline():
    tasks = []
    for step in STEPS:

        @task(task_id=step.replace("-", "_"))
        def run(step_name: str = step) -> None:
            run_step(step_name)

        tasks.append(run())

    @task(trigger_rule="one_failed", retries=0)
    def mark_run_failed() -> None:
        subprocess.run([CLI, "mark-failed", "--run-id", pipeline_run_id()], check=False)

    for upstream, downstream in zip(tasks, tasks[1:], strict=False):
        upstream >> downstream
    tasks >> mark_run_failed()


claims_pipeline()
