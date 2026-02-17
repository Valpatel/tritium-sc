#!/bin/bash
# TRITIUM-SC — Start the server
# Usage: ./start.sh [port]

PORT=${1:-8000}
DIR="$(cd "$(dirname "$0")" && pwd)"
VENV="$DIR/.venv/bin/python3"

if [ ! -f "$VENV" ]; then
    echo "ERROR: Virtual environment not found at $DIR/.venv"
    echo "Run: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
    exit 1
fi

# GB10 (sm_121) CUDA not supported by PyTorch — force CPU for Whisper/YOLO
export CUDA_VISIBLE_DEVICES=""

echo "TRITIUM-SC starting on http://localhost:$PORT"
exec "$DIR/.venv/bin/uvicorn" app.main:app --host 0.0.0.0 --port "$PORT"
