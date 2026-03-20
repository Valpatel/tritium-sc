#!/usr/bin/env python3
"""Verify terrain API integration after server restart.

Run this after restarting the SC server to confirm all terrain
endpoints work and the GIS layer catalog includes segmented terrain.

Usage:
    python3 scripts/verify_terrain.py
"""

import json
import sys
import requests

BASE = "http://localhost:8000"


def check(name, url, expect_key=None, expect_min_count=None):
    """Check an API endpoint."""
    try:
        r = requests.get(f"{BASE}{url}", timeout=5)
        if r.status_code == 404:
            print(f"  FAIL  {name}: 404 Not Found (server needs restart?)")
            return False
        if r.status_code != 200:
            print(f"  FAIL  {name}: HTTP {r.status_code}")
            return False
        data = r.json()
        if expect_key and expect_key not in (data if isinstance(data, dict) else {}):
            print(f"  FAIL  {name}: missing key '{expect_key}'")
            return False
        if expect_min_count is not None:
            count = len(data) if isinstance(data, list) else len(data.get("features", []))
            if count < expect_min_count:
                print(f"  FAIL  {name}: expected >={expect_min_count} items, got {count}")
                return False
            print(f"  PASS  {name}: {count} items")
        else:
            print(f"  PASS  {name}")
        return True
    except Exception as e:
        print(f"  FAIL  {name}: {e}")
        return False


def main():
    print("Tritium Terrain Integration Verification")
    print("=" * 50)

    results = []

    # Core API health
    results.append(check("Server health", "/api/amy/status", expect_key="state"))
    results.append(check("Demo status", "/api/demo/status", expect_key="active"))

    # Terrain API (new)
    results.append(check("Terrain status", "/api/terrain/status", expect_key="cached_areas"))
    results.append(check("Terrain brief", "/api/terrain/brief", expect_key="brief"))
    results.append(check("Terrain layer", "/api/terrain/layer", expect_min_count=0))
    results.append(check("Terrain query", "/api/terrain/query?lat=30.266&lon=-97.748"))

    # GIS catalog with segmented terrain
    try:
        r = requests.get(f"{BASE}/api/geo/layers/catalog", timeout=5)
        data = r.json()
        terrain_layer = [l for l in data if l["id"] == "segmented-terrain"]
        if terrain_layer:
            print(f"  PASS  GIS catalog has segmented-terrain: {terrain_layer[0]['feature_count']} features")
            results.append(True)
        else:
            print(f"  FAIL  GIS catalog missing segmented-terrain layer")
            results.append(False)
    except Exception as e:
        print(f"  FAIL  GIS catalog: {e}")
        results.append(False)

    # Segmented terrain endpoint
    results.append(check("Segmented terrain GeoJSON", "/api/geo/layers/segmented-terrain", expect_min_count=0))

    # Target tracker fields
    try:
        r = requests.get(f"{BASE}/api/targets", timeout=5)
        data = r.json()
        targets = data if isinstance(data, list) else data.get("targets", [])
        if targets:
            t = targets[0]
            has_first_seen = "first_seen" in t
            has_signal_count = "signal_count" in t
            if has_first_seen and has_signal_count:
                print(f"  PASS  Target tracker has first_seen + signal_count")
                results.append(True)
            else:
                print(f"  FAIL  Target missing first_seen={has_first_seen}, signal_count={has_signal_count}")
                results.append(False)
        else:
            print(f"  SKIP  No targets to verify")
            results.append(True)
    except Exception as e:
        print(f"  FAIL  Target fields: {e}")
        results.append(False)

    print("=" * 50)
    passed = sum(results)
    total = len(results)
    print(f"Results: {passed}/{total} passed")
    if passed < total:
        print("\nNote: terrain endpoints require server restart to activate.")
        print("Run: cd tritium-sc && ./start.sh")
    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
