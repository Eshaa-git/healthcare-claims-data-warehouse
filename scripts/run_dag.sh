#!/usr/bin/env bash
# Trigger claims_pipeline through the Airflow scheduler and wait for the DAG run to finish.
set -euo pipefail
RUN_ID="manual__$(date -u +%Y%m%dT%H%M%SZ)"
TIMEOUT="${DAG_TIMEOUT_SECONDS:-3600}"
af() { docker compose exec -T airflow airflow "$@"; }

af dags unpause claims_pipeline >/dev/null
af dags trigger claims_pipeline --run-id "$RUN_ID" >/dev/null
echo "triggered $RUN_ID"
start=$(date +%s)
while :; do
  state=$(af dags list-runs claims_pipeline -o json 2>/dev/null \
    | python3 -c "import json,sys; r=[x for x in json.load(sys.stdin) if x['run_id']=='$RUN_ID']; print(r[0]['state'] if r else 'missing')")
  case "$state" in
    success) echo "DAG run $RUN_ID: success"; exit 0 ;;
    failed)  echo "DAG run $RUN_ID: failed"
             af tasks states-for-dag-run claims_pipeline "$RUN_ID" -o table || true
             exit 1 ;;
  esac
  (( $(date +%s) - start > TIMEOUT )) && { echo "timed out waiting for $RUN_ID ($state)"; exit 1; }
  sleep 10
done
