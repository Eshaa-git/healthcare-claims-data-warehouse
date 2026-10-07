#!/usr/bin/env bash
# Fail clearly when .env is missing or still has placeholder credentials.
set -euo pipefail
[[ -f .env ]] || { echo "Missing .env: cp .env.example .env and fill in the values"; exit 1; }
required=(WAREHOUSE_ADMIN_PASSWORD LOADER_PASSWORD TRANSFORMER_PASSWORD DASHBOARD_PASSWORD
          AIRFLOW_DB_PASSWORD AIRFLOW_FERNET_KEY AIRFLOW_JWT_SECRET)
bad=()
for key in "${required[@]}"; do
  value=$(grep -E "^${key}=" .env | tail -1 | cut -d= -f2- || true)
  [[ -z "$value" || "$value" == "change-me" ]] && bad+=("$key")
done
if (( ${#bad[@]} )); then
  echo "Set these in .env: ${bad[*]}"; exit 1
fi
echo ".env OK"
