#!/bin/bash
# Redeploy bmtm-api on the VPS through PM2 and verify it is healthy.
set -euo pipefail
cd "$(dirname "$0")"

git pull --ff-only
.venv/bin/pip install -q -r requirements.txt
pm2 restart bmtm-api

for _ in {1..15}; do
  if curl -fs -m 3 -o /dev/null http://127.0.0.1:8000/api/v1/health; then
    echo "bmtm-api healthy"
    exit 0
  fi
  sleep 2
done

echo "bmtm-api failed its health check" >&2
exit 1
