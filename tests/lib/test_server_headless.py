# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Verify headless server (AMY_ENABLED=false) serves game APIs.

This is the critical test that proves the simulation engine works
independently of Amy's hardware requirements.
"""
import sys
import time
import requests
from tests.lib.server_manager import TritiumServer


def main():
    print("Starting headless server (AMY_ENABLED=false, SIMULATION_ENABLED=true)...")
    server = TritiumServer(auto_port=True)
    try:
        server.start(timeout=30)
        print(f"  Server running at {server.base_url}")
    except RuntimeError as e:
        print(f"  FAIL: Server failed to start: {e}")
        sys.exit(1)

    failures = []

    def check(label, fn):
        try:
            result = fn()
            print(f"  PASS: {label} -> {result}")
        except Exception as e:
            print(f"  FAIL: {label} -> {e}")
            failures.append(label)

    # Health
    check("GET /health", lambda: requests.get(f"{server.base_url}/health", timeout=5).json())

    # Game state
    check("GET /api/game/state", lambda: requests.get(f"{server.base_url}/api/game/state", timeout=5).json())

    # Sim targets
    check("GET /api/amy/simulation/targets", lambda: requests.get(f"{server.base_url}/api/amy/simulation/targets", timeout=5).json())

    # Unified targets
    check("GET /api/targets", lambda: requests.get(f"{server.base_url}/api/targets", timeout=5).json())

    # Place unit
    check("POST /api/game/place", lambda: requests.post(
        f"{server.base_url}/api/game/place",
        json={"name": "test-turret", "asset_type": "turret", "position": {"x": 5, "y": 5}},
        timeout=5,
    ).json())

    # Begin war
    check("POST /api/game/begin", lambda: requests.post(f"{server.base_url}/api/game/begin", timeout=5).json())

    # Wait for game to start
    time.sleep(3)

    # Game state after begin
    check("GET /api/game/state (active)", lambda: requests.get(f"{server.base_url}/api/game/state", timeout=5).json())

    # Hostiles
    check("GET /api/targets/hostiles", lambda: requests.get(f"{server.base_url}/api/targets/hostiles", timeout=5).json())

    # Friendlies
    check("GET /api/targets/friendlies", lambda: requests.get(f"{server.base_url}/api/targets/friendlies", timeout=5).json())

    # Reset
    check("POST /api/game/reset", lambda: requests.post(f"{server.base_url}/api/game/reset", timeout=5).json())

    # Game state after reset
    check("GET /api/game/state (reset)", lambda: requests.get(f"{server.base_url}/api/game/state", timeout=5).json())

    # Spawn hostile
    check("POST /api/amy/simulation/spawn", lambda: requests.post(
        f"{server.base_url}/api/amy/simulation/spawn",
        json={"name": "test-hostile", "alliance": "hostile", "asset_type": "person"},
        timeout=5,
    ).json())

    server.stop()
    print(f"\n{'='*50}")
    if failures:
        print(f"FAILED: {len(failures)} endpoints broken:")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    else:
        print("ALL ENDPOINTS PASS in headless mode")
        sys.exit(0)


if __name__ == "__main__":
    main()
