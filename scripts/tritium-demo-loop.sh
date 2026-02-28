#!/usr/bin/env bash
# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
# TRITIUM-SC Demo Loop Launcher
# Starts the server (if not running) and runs the full autonomous demo in
# continuous loop mode with 10-wave battles.
#
# Usage:
#   ./scripts/tritium-demo-loop.sh           # launch demo loop
#   ./scripts/tritium-demo-loop.sh --waves 3 # quick 3-wave battles

set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$DIR"

VENV="$DIR/.venv/bin/python3"
PORT=8000
EXTRA_ARGS=("$@")

# Check if server is already running on the port
if curl -sf "http://localhost:$PORT/api/amy/status" > /dev/null 2>&1; then
    echo "[TRITIUM] Server already running on port $PORT"
    SERVER_FLAG="--no-server --port $PORT"
else
    echo "[TRITIUM] Server will be auto-started"
    SERVER_FLAG="--port $PORT"
fi

echo "========================================"
echo "  TRITIUM-SC DEMO LOOP"
echo "  Press Ctrl+C to stop"
echo "========================================"

exec "$VENV" "$DIR/scripts/demo_story.py" \
    --forever \
    --waves 10 \
    $SERVER_FLAG \
    "${EXTRA_ARGS[@]}"
