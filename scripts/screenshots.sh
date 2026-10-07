#!/usr/bin/env bash
# Capture the dashboard and Airflow DAG view from the running stack (headless Chrome, no window).
set -euo pipefail
mkdir -p docs/screenshots
uv run python scripts/screenshot.py "http://127.0.0.1:${DASHBOARD_HOST_PORT:-8501}/" \
  docs/screenshots/dashboard.png --wait-text "Data quality"
