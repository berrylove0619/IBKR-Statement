#!/usr/bin/env bash
set -euo pipefail

SAMPLE_CSV="/app/ibkr_show_worker/worker/fixtures/daily_sample.csv"

echo "[worker-init] starting initialization ..."

echo "[worker-init] creating Elasticsearch indices ..."
python -m worker.main init-es

echo "[worker-init] checking Elasticsearch health ..."
python -m worker.main es-health

if [ "${DEMO_MODE:-true}" = "true" ]; then
    echo "[worker-init] DEMO_MODE=true — importing sample data from ${SAMPLE_CSV}"
    python -m worker.main import-daily-file --file "${SAMPLE_CSV}"
    echo "[worker-init] sample data import complete."
else
    echo "[worker-init] DEMO_MODE=false — skipping sample data import."
fi

echo "[worker-init] initialization finished."
