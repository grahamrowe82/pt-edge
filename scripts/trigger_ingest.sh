#!/usr/bin/env bash
# Trigger a daily ingest run by restarting the worker service on Render.
# The worker checks on startup whether today's run has completed;
# if not, it runs immediately.
#
# Usage: ./scripts/trigger_ingest.sh

set -euo pipefail

SERVICE_ID="srv-d77c6s14tr6s739h798g"  # pt-edge-daily-ingest-worker

if [ -z "${RENDER_API_KEY:-}" ]; then
    echo "Error: RENDER_API_KEY not set" >&2
    exit 1
fi

echo "Restarting ingest worker to trigger immediate run..."
curl -sf -X POST \
    -H "Authorization: Bearer $RENDER_API_KEY" \
    "https://api.render.com/v1/services/$SERVICE_ID/restart" \
    | python3 -m json.tool 2>/dev/null || true

echo "Done. Worker will check sync_log and run if today's ingest is missing."
