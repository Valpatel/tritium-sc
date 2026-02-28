#!/usr/bin/env python3
# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Run test tiers and record results to ResultsDB + generate HTML report.

Usage:
    python3 scripts/run_with_report.py [suite_label]
    # Defaults to "session-17" as suite label

Runs:
  1. Tier 1 (syntax)   — recorded individually
  2. Tier 2 (pytest)   — uses pytest-json-report for per-test recording
  3. Tier 3 (JS)       — recorded per test file
  4. Tier 8 (lib)      — pytest per-test
  5. Tier 8b (ROS2)    — pytest per-test
  6. Tier 11 (smoke)   — pytest per-test
  7. New meshtastic bridge unit tests
  8. New mesh router API tests
  9. New mesh panel JS tests

Then generates HTML report + JSON metrics.
"""

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

# Add src to path
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from tests.lib.results_db import ResultsDB
from tests.lib.report_gen import ReportGenerator

DB_PATH = str(ROOT / "tests/.test-results/results.db")
REPORT_DIR = str(ROOT / "tests/.test-results/reports")
VENV_PYTHON = str(ROOT / ".venv/bin/python3")


def git_hash():
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(ROOT), timeout=5,
        ).decode().strip()
    except Exception:
        return "unknown"


def run_cmd(cmd, cwd=None, timeout=300):
    """Run a command, return (success, stdout, duration_ms)."""
    t0 = time.monotonic()
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
            cwd=cwd or str(ROOT),
            env={**os.environ, "PYTHONPATH": f"{ROOT}/src", "CUDA_VISIBLE_DEVICES": ""},
        )
        dur = (time.monotonic() - t0) * 1000
        return result.returncode == 0, result.stdout + result.stderr, dur
    except subprocess.TimeoutExpired:
        dur = (time.monotonic() - t0) * 1000
        return False, "TIMEOUT", dur
    except Exception as e:
        dur = (time.monotonic() - t0) * 1000
        return False, str(e), dur


def run_pytest_with_json(db, run_id, label, pytest_args):
    """Run pytest with JSON report, record each test result."""
    json_file = ROOT / "tests/.test-results" / f"_tmp_{label}.json"
    cmd = [
        VENV_PYTHON, "-m", "pytest",
        *pytest_args,
        f"--json-report-file={json_file}",
        "--json-report",
        "--tb=short", "-q",
    ]
    ok, output, total_dur = run_cmd(cmd)

    # Parse JSON report for per-test results
    tests_recorded = 0
    if json_file.exists():
        try:
            data = json.loads(json_file.read_text())
            for t in data.get("tests", []):
                name = t.get("nodeid", "unknown")
                passed = t.get("outcome") == "passed"
                dur = t.get("call", {}).get("duration", 0) * 1000
                detail = ""
                if not passed:
                    detail = t.get("call", {}).get("longrepr", "")[:500]
                db.record_result(run_id, f"{label}::{name}", passed, dur, detail)
                tests_recorded += 1
        except Exception as e:
            print(f"  Warning: JSON parse failed for {label}: {e}")

    # If JSON didn't work, record as single result
    if tests_recorded == 0:
        db.record_result(run_id, f"{label}::all", ok, total_dur,
                         "" if ok else output[:500])

    # Clean up
    if json_file.exists():
        json_file.unlink()

    return ok, tests_recorded


def run_syntax_checks(db, run_id):
    """Tier 1: syntax check Python + JS files."""
    py_files = [
        "src/amy/commander.py", "src/amy/comms/meshtastic_bridge.py",
        "src/app/main.py", "src/app/config.py", "src/app/routers/mesh.py",
        "src/amy/simulation/combat.py", "src/amy/simulation/game_mode.py",
        "tests/lib/layout_validator.py", "tests/ui/test_layout_validation.py",
    ]
    js_files = [
        "frontend/js/command/main.js", "frontend/js/command/websocket.js",
        "frontend/js/command/panels/mesh.js",
        "frontend/js/war.js", "frontend/js/app.js",
    ]

    count = 0
    for f in py_files:
        fp = ROOT / f
        if fp.exists():
            ok, _, dur = run_cmd(["python3", "-m", "py_compile", str(fp)])
            db.record_result(run_id, f"syntax::py_compile::{f}", ok, dur, "")
            count += 1

    for f in js_files:
        fp = ROOT / f
        if fp.exists():
            ok, _, dur = run_cmd(["node", "--check", str(fp)])
            db.record_result(run_id, f"syntax::node_check::{f}", ok, dur, "")
            count += 1

    return count


def run_js_tests(db, run_id):
    """Tier 3: JS tests."""
    js_tests = [
        "test_war_math.js", "test_war_audio.js", "test_war_fog.js",
        "test_geo_math.js", "test_panel_manager.js", "test_mesh_panel.js",
    ]
    total = 0
    for jt in js_tests:
        fp = ROOT / "tests/js" / jt
        if fp.exists():
            ok, output, dur = run_cmd(["node", str(fp)])
            # Count individual test results from output
            import re
            passed = len(re.findall(r"^PASS:", output, re.MULTILINE))
            failed = len(re.findall(r"^FAIL:", output, re.MULTILINE))
            db.record_result(
                run_id, f"js::{jt}", ok, dur,
                f"{passed} passed, {failed} failed" if ok else output[:500],
            )
            total += passed
    return total


def main():
    suite = sys.argv[1] if len(sys.argv) > 1 else "session-17"

    print(f"=== TRITIUM-SC Test Run: {suite} ===")
    print(f"DB: {DB_PATH}")
    print(f"Reports: {REPORT_DIR}")

    db = ResultsDB(db_path=DB_PATH)
    run_id = db.record_run(suite, git_hash(), socket.gethostname())
    print(f"Run ID: {run_id}")

    t0 = time.monotonic()

    # Tier 1: Syntax
    print("\n--- Tier 1: Syntax Check ---")
    n = run_syntax_checks(db, run_id)
    print(f"  {n} files checked")

    # Tier 2: Python unit tests
    print("\n--- Tier 2: Python Unit Tests ---")
    ok, n = run_pytest_with_json(db, run_id, "unit", [
        str(ROOT / "tests/amy/"), "-m", "unit",
    ])
    print(f"  {'PASS' if ok else 'FAIL'}: {n} tests recorded")

    # Tier 3: JS tests
    print("\n--- Tier 3: JS Tests ---")
    n = run_js_tests(db, run_id)
    print(f"  {n} individual JS tests passed")

    # Tier 8: Test infrastructure
    print("\n--- Tier 8: Test Infrastructure ---")
    ok, n = run_pytest_with_json(db, run_id, "lib", [
        str(ROOT / "tests/lib/"), "-m", "unit",
    ])
    print(f"  {'PASS' if ok else 'FAIL'}: {n} tests recorded")

    # Tier 8b: ROS2
    print("\n--- Tier 8b: ROS2 Robot Tests ---")
    ok, n = run_pytest_with_json(db, run_id, "ros2", [
        str(ROOT / "examples/ros2-robot/tests/"),
    ])
    print(f"  {'PASS' if ok else 'FAIL'}: {n} tests recorded")

    # Tier 11: Smoke tests (needs running server)
    print("\n--- Tier 11: UI Smoke Tests ---")
    ok, n = run_pytest_with_json(db, run_id, "smoke", [
        str(ROOT / "tests/visual/test_unified_smoke.py"), "-v",
    ])
    print(f"  {'PASS' if ok else 'FAIL'}: {n} tests recorded")

    elapsed = time.monotonic() - t0
    print(f"\n=== Total time: {elapsed:.1f}s ===")

    # Generate report
    print("\n--- Generating Report ---")
    gen = ReportGenerator(db, output_dir=REPORT_DIR)
    report_path = gen.generate(run_id)
    print(f"HTML Report: {report_path}")

    json_path = gen.export_json(run_id)
    print(f"JSON Metrics: {json_path}")

    print(f"\nSQLite DB: {DB_PATH}")
    print(f"\n=== Done ===")


if __name__ == "__main__":
    main()
