"""Parse the DAG folder inside the Airflow image and check the task chain (no database needed)."""

try:
    from airflow.dag_processing.dagbag import DagBag
except ImportError:  # older Airflow layout
    from airflow.models.dagbag import DagBag

EXPECTED = ["acquire", "cohort", "stage", "dbt_run", "dbt_test", "reconcile", "publish"]

bag = DagBag(dag_folder="/opt/airflow/dags")
assert not bag.import_errors, bag.import_errors
dag = bag.dags["claims_pipeline"]
for upstream, downstream in zip(EXPECTED, EXPECTED[1:], strict=False):
    assert downstream in dag.get_task(upstream).downstream_task_ids, (upstream, downstream)
assert dag.get_task("mark_run_failed").trigger_rule == "one_failed"
print(f"claims_pipeline OK: {len(dag.tasks)} tasks, chain {' -> '.join(EXPECTED)}")
