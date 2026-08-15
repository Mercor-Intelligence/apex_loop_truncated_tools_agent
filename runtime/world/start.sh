#!/usr/bin/env bash
#
# Entrypoint for a Harbor task's world sidecar. Starts the gateway, seeds
# the world, then stays in the foreground for the life of the trial.
#
set -euo pipefail

PORT="${PORT:-8000}"
WORLD_LOGS_DIR="${WORLD_LOGS_DIR:-/logs/world}"

mkdir -p "$WORLD_LOGS_DIR"

# Harbor reuses the log volume across a task's containers; stale readiness
# markers would let the agent start against a world that has not been seeded.
rm -f "$WORLD_LOGS_DIR/.initial_snapshot_done" \
      "$WORLD_LOGS_DIR/initial_snapshot.tar.gz" \
      "$WORLD_LOGS_DIR/final_snapshot.tar.gz" \
      "$WORLD_LOGS_DIR"/*.partial

cd /app
uvicorn runner.main:app --host 0.0.0.0 --port "$PORT" &
GATEWAY_PID=$!

if ! python /app/tools/boot.py; then
    echo "start.sh: world boot failed — stopping gateway" >&2
    kill "$GATEWAY_PID" 2>/dev/null || true
    wait "$GATEWAY_PID" 2>/dev/null || true
    exit 1
fi

# Exit with the gateway: a dead server should fail the trial, not hang it.
wait "$GATEWAY_PID"
