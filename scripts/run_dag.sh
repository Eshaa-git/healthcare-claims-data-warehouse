#!/usr/bin/env bash
# Trigger claims_pipeline through the Airflow scheduler and wait for the DAG run to finish.
set -euo pipefail
# usage: scripts/run_dag.sh [conf-json]
CONF="${1:-}"
RUN_ID="manual__$(date -u +%Y%m%dT%H%M%SZ)"
TIMEOUT="${DAG_TIMEOUT_SECONDS:-3600}"
af() { docker compose exec -T airflow airflow "$@"; }

export CLAIMS_DW_GIT_COMMIT="$(git describe --always --dirty --abbrev=40 2>/dev/null)"
running=$(docker compose exec -T airflow printenv CLAIMS_DW_GIT_COMMIT 2>/dev/null || true)
if [[ "$running" != "$CLAIMS_DW_GIT_COMMIT" ]]; then
  echo "stack runs commit ${running:-unknown}, checkout is $CLAIMS_DW_GIT_COMMIT: run make up first"; exit 1
fi

af dags unpause claims_pipeline >/dev/null
if [[ -n "$CONF" ]]; then
  af dags trigger claims_pipeline --run-id "$RUN_ID" --conf "$CONF" >/dev/null
else
  af dags trigger claims_pipeline --run-id "$RUN_ID" >/dev/null
fi
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
