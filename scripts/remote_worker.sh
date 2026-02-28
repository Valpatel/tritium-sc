#!/bin/bash
# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
# Remote worker/mirror mode launcher — run on any remote test machine
set -euo pipefail

MODE=${1:-"worker"}
SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$SCRIPT_DIR"

case "$MODE" in
    worker)
        echo "=== $(hostname) Test Worker ==="
        .venv/bin/python3 -m pytest tests/amy/ -m unit --tb=short -q
        if command -v ollama &>/dev/null; then
            .venv/bin/python3 tests/ui/test_vision.py --quick --views assets,analytics,amy,war,scenarios 2>/dev/null || true
        fi
        [ -f tests/ui/test_gameplay.py ] && .venv/bin/python3 tests/ui/test_gameplay.py || true
        echo "=== Worker Complete ==="
        ;;
    mirror)
        echo "=== $(hostname) Mirror Mode ==="
        source .venv/bin/activate
        python3 scripts/fake_robots.py --count 3 &
        ROBOT_PID=$!
        trap "kill $ROBOT_PID 2>/dev/null; exit" INT TERM
        MQTT_ENABLED=true uvicorn app.main:app --host 0.0.0.0 --port 8000
        ;;
    robots)
        echo "=== Running fake robot fleet ==="
        source .venv/bin/activate
        shift
        python3 scripts/fake_robots.py "$@"
        ;;
    *)
        echo "Usage: $0 [worker|mirror|robots]"
        exit 1
        ;;
esac
