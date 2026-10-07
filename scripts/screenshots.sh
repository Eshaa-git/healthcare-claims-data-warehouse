#!/usr/bin/env bash
# Capture evidence screenshots from the running stack with headless Chrome (no window, muted):
#   docs/screenshots/dashboard.png    Streamlit dashboard over the published marts
#   docs/screenshots/dbt_docs.png     dbt docs page for fact_inpatient_claim (columns and tests)
set -euo pipefail
mkdir -p docs/screenshots
uv run python scripts/screenshot.py "http://127.0.0.1:${DASHBOARD_HOST_PORT:-8501}/" \
  docs/screenshots/dashboard.png --wait-text "Data quality"

# dbt docs: generate inside the container against the warehouse, serve the static site locally.
docker compose exec -T airflow bash -c \
  'cd /opt/claims-dw && DBT_HOST=warehouse-db DBT_PORT=5432 DBT_DATABASE=$WAREHOUSE_DB \
   DBT_USER=claims_transformer DBT_PASSWORD=$TRANSFORMER_PASSWORD DBT_SCHEMA=dw_build \
   venv/bin/dbt docs generate --project-dir dbt --profiles-dir dbt --quiet'
site=$(mktemp -d)
for f in index.html manifest.json catalog.json; do
  docker compose cp "airflow:/opt/claims-dw/dbt/target/$f" "$site/$f" >/dev/null
done
uv run python -m http.server 8599 --bind 127.0.0.1 --directory "$site" >/dev/null 2>&1 &
server=$!
trap 'kill $server; rm -rf "$site"' EXIT
sleep 1
uv run python scripts/screenshot.py \
  "http://127.0.0.1:8599/#!/model/model.claims_warehouse.fact_inpatient_claim" \
  docs/screenshots/dbt_docs.png --wait-text "inpatient_claim_key" --height 1300
