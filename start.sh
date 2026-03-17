#!/bin/bash
# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
# TRITIUM-SC — Start the server
# Usage: ./start.sh [port] [--tls]
#
# TLS mode:
#   ./start.sh --tls                     # Uses TLS_CERT_FILE and TLS_KEY_FILE env vars
#   ./start.sh 8443 --tls                # Custom port + TLS
#   TLS_CERT_FILE=cert.pem TLS_KEY_FILE=key.pem ./start.sh --tls
#
# Generate self-signed cert for development:
#   openssl req -x509 -newkey rsa:4096 -keyout key.pem -out cert.pem -days 365 -nodes \
#     -subj '/CN=tritium-sc'

PORT=${1:-8000}
DIR="$(cd "$(dirname "$0")" && pwd)"
VENV="$DIR/.venv/bin/python3"
TLS_MODE=false

# Parse arguments
for arg in "$@"; do
    case "$arg" in
        --tls) TLS_MODE=true ;;
        [0-9]*) PORT="$arg" ;;
    esac
done

if [ ! -f "$VENV" ]; then
    echo "ERROR: Virtual environment not found at $DIR/.venv"
    echo "Run: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
    exit 1
fi

# GB10 (sm_121) CUDA not supported by PyTorch — force CPU for Whisper/YOLO
export CUDA_VISIBLE_DEVICES=""
export PYTHONPATH="$DIR/src${PYTHONPATH:+:$PYTHONPATH}"

if [ "$TLS_MODE" = true ]; then
    CERT="${TLS_CERT_FILE:-$DIR/conf/cert.pem}"
    KEY="${TLS_KEY_FILE:-$DIR/conf/key.pem}"

    if [ ! -f "$CERT" ]; then
        echo "ERROR: TLS certificate not found at $CERT"
        echo "Set TLS_CERT_FILE or place cert.pem in conf/"
        echo "Generate self-signed: openssl req -x509 -newkey rsa:4096 -keyout key.pem -out cert.pem -days 365 -nodes -subj '/CN=tritium-sc'"
        exit 1
    fi
    if [ ! -f "$KEY" ]; then
        echo "ERROR: TLS private key not found at $KEY"
        echo "Set TLS_KEY_FILE or place key.pem in conf/"
        exit 1
    fi

    echo "TRITIUM-SC starting on https://localhost:$PORT (TLS)"
    while true; do
        "$DIR/.venv/bin/uvicorn" app.main:app --host 0.0.0.0 --port "$PORT" \
            --ssl-certfile "$CERT" --ssl-keyfile "$KEY"
        EXIT_CODE=$?
        if [ "$EXIT_CODE" -eq 42 ]; then
            echo ""; echo "TRITIUM-SC restarting (requested by API)..."; echo ""
            sleep 1
        else
            exit $EXIT_CODE
        fi
    done
else
    echo "TRITIUM-SC starting on http://localhost:$PORT"
    # Auto-restart loop: exit code 42 = restart requested (from API/UI)
    while true; do
        "$DIR/.venv/bin/uvicorn" app.main:app --host 0.0.0.0 --port "$PORT"
        EXIT_CODE=$?
        if [ "$EXIT_CODE" -eq 42 ]; then
            echo ""
            echo "TRITIUM-SC restarting (requested by API)..."
            echo ""
            sleep 1
        else
            echo "TRITIUM-SC exited with code $EXIT_CODE"
            exit $EXIT_CODE
        fi
    done
fi
