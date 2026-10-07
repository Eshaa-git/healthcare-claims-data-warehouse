"""Airflow DAG: acquire -> cohort -> stage -> dbt run -> dbt test -> reconcile -> publish.

Each task runs one `claims-dw` step in the pipeline's own virtualenv, so Airflow's dependencies
and the pipeline's (pandas, dbt) never share an environment. Only transient failures (exit code
75: network or database unavailable) are retried; data, contract and check failures fail the
task immediately. Publication happens only if every upstream task succeeded, so a failed run
leaves the last published marts untouched. A run can be triggered with conf
{"fail_after_chunks": 1, "fail_dataset": "drug_events"} to inject a load failure (recovery demo).
"""

from __future__ import annotations

import os
import re
import subprocess
from datetime import datetime, timedelta

from airflow.sdk import dag, get_current_context, task
from airflow.sdk.exceptions import AirflowException, AirflowFailException

CLI = "/opt/claims-dw/venv/bin/claims-dw"
EXIT_TRANSIENT = 75
STEPS = ["acquire", "cohort", "stage", "dbt-run", "dbt-test", "reconcile", "publish"]


def pipeline_run_id() -> str:
    """Stable per DAG run, safe for file names and SQL text."""
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", get_current_context()["run_id"])


# Optional DAG-run conf for recovery demos, e.g. {"fail_after_chunks": 1, "fail_dataset": "drug_events"}
INJECTION_CONF = {
    "fail_after_chunks": "CLAIMS_DW_FAIL_AFTER_CHUNKS",
    "fail_dataset": "CLAIMS_DW_FAIL_DATASET",
}


def run_step(step: str) -> None:
    env = dict(os.environ)
    conf = get_current_context()["dag_run"].conf or {}
    for key, var in INJECTION_CONF.items():
        if key in conf:
            env[var] = str(conf[key])
    result = subprocess.run(
        [CLI, step, "--run-id", pipeline_run_id()],
        capture_output=True,
        text=True,
        check=False,
        env=env,
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
        """Record the failure in ops.pipeline_runs, then fail so the DAG run itself is failed."""
        subprocess.run(
            [CLI, "finish-run", "--status", "failed", "--run-id", pipeline_run_id()], check=False
        )
        raise AirflowFailException("an upstream pipeline step failed; nothing was published")

    for upstream, downstream in zip(tasks, tasks[1:], strict=False):
        upstream >> downstream
    tasks >> mark_run_failed()


claims_pipeline()
