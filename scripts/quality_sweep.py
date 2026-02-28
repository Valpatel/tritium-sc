#!/usr/bin/env python3
# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Quality sweep for Command Center.

Captures screenshots, measures metrics, records to SQLite, generates reports.

Usage:
    python3 scripts/quality_sweep.py              # Single sweep against running server
    python3 scripts/quality_sweep.py --watch       # Continuous (every 60s)
    python3 scripts/quality_sweep.py --baseline    # Capture new baselines
    python3 scripts/quality_sweep.py --report      # Generate HTML report from latest
    python3 scripts/quality_sweep.py --url URL     # Custom server URL (default: http://localhost:8000)
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path

# Add src/ for app/amy imports, project root for tests.lib imports
_PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "src"))
sys.path.insert(0, str(_PROJECT_ROOT))

from tests.lib.results_db import ResultsDB
from tests.lib.report_gen import ReportGenerator

RESULTS_DB_PATH = str(_PROJECT_ROOT / "tests" / ".test-results" / "smoke-results.db")
BASELINE_DIR = _PROJECT_ROOT / "tests" / ".baselines" / "unified"
SCREENSHOT_DIR = _PROJECT_ROOT / "tests" / ".test-results" / "smoke-screenshots"


def _git_hash() -> str:
    """Get current short git hash."""
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(_PROJECT_ROOT),
            stderr=subprocess.DEVNULL,
        ).decode().strip()
    except Exception:
        return "unknown"


def _check_server(url: str) -> bool:
    """Check if the server is reachable."""
    import urllib.request
    try:
        urllib.request.urlopen(f"{url}/api/game/state", timeout=5)
        return True
    except Exception:
        return False


def _check_playwright() -> bool:
    """Check if Playwright is importable and browsers installed."""
    try:
        from playwright.sync_api import sync_playwright
        return True
    except ImportError:
        return False


def _capture_metrics(page) -> dict:
    """Capture all metrics from the page."""
    metrics = {}

    # Console errors
    console_errors = []

    def _on_console(msg):
        if msg.type == "error":
            console_errors.append(msg.text)

    page.on("console", _on_console)
    # Give a moment for any pending errors
    page.wait_for_timeout(500)
    metrics["console_errors"] = len(console_errors)
    metrics["console_error_messages"] = console_errors[:10]

    # Unit count via TritiumStore
    try:
        unit_count = page.evaluate(
            """() => {
                if (window.TritiumStore && window.TritiumStore.units) {
                    return window.TritiumStore.units.size;
                }
                return 0;
            }"""
        )
        metrics["unit_count"] = unit_count
    except Exception:
        metrics["unit_count"] = 0

    # Canvas brightness (sample center region)
    try:
        brightness = page.evaluate(
            """() => {
                const c = document.querySelector('canvas');
                if (!c) return -1;
                const ctx = c.getContext('2d');
                if (!ctx) return -1;
                const w = c.width, h = c.height;
                const sx = Math.floor(w * 0.25), sy = Math.floor(h * 0.25);
                const sw = Math.floor(w * 0.5), sh = Math.floor(h * 0.5);
                const data = ctx.getImageData(sx, sy, sw, sh).data;
                let nonBlack = 0;
                const total = data.length / 4;
                for (let i = 0; i < data.length; i += 4) {
                    if (data[i] > 20 || data[i+1] > 20 || data[i+2] > 20) nonBlack++;
                }
                return total > 0 ? (nonBlack / total * 100) : 0;
            }"""
        )
        metrics["canvas_brightness_pct"] = round(brightness, 1) if brightness >= 0 else None
    except Exception:
        metrics["canvas_brightness_pct"] = None

    # FPS from status element
    try:
        fps_text = page.evaluate(
            """() => {
                const el = document.getElementById('status-fps');
                return el ? el.textContent : '';
            }"""
        )
        metrics["fps_text"] = fps_text
        # Parse numeric FPS
        import re
        m = re.search(r"(\d+)", fps_text or "")
        metrics["fps"] = int(m.group(1)) if m else None
    except Exception:
        metrics["fps_text"] = ""
        metrics["fps"] = None

    # WebSocket connection state
    try:
        ws_state = page.evaluate(
            """() => {
                const el = document.getElementById('connection-status');
                if (!el) return 'unknown';
                return el.dataset.state || el.textContent || 'unknown';
            }"""
        )
        metrics["ws_state"] = ws_state
    except Exception:
        metrics["ws_state"] = "unknown"

    # Visible panel count
    try:
        panel_count = page.evaluate(
            """() => {
                const panels = document.querySelectorAll('.panel');
                let visible = 0;
                panels.forEach(p => {
                    if (p.offsetParent !== null && p.style.display !== 'none') visible++;
                });
                return visible;
            }"""
        )
        metrics["visible_panels"] = panel_count
    except Exception:
        metrics["visible_panels"] = 0

    return metrics


def _take_screenshot(page, name: str, out_dir: Path) -> Path:
    """Take a screenshot and return its path."""
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{name}.png"
    page.screenshot(path=str(path))
    return path


def _print_summary(metrics: dict, screenshots: list[Path]) -> None:
    """Print a summary table to stdout."""
    print("\n" + "=" * 60)
    print("  TRITIUM-SC Quality Sweep Results")
    print("=" * 60)
    print(f"  Console errors:     {metrics.get('console_errors', '?')}")
    print(f"  Unit count:         {metrics.get('unit_count', '?')}")
    print(f"  Canvas brightness:  {metrics.get('canvas_brightness_pct', '?')}%")
    print(f"  FPS:                {metrics.get('fps', '?')} ({metrics.get('fps_text', '')})")
    print(f"  WebSocket state:    {metrics.get('ws_state', '?')}")
    print(f"  Visible panels:     {metrics.get('visible_panels', '?')}")
    print("-" * 60)
    for s in screenshots:
        print(f"  Screenshot: {s}")
    print("=" * 60 + "\n")


def _run_single_sweep(url: str, db: ResultsDB) -> int:
    """Run a single quality sweep. Returns the run_id."""
    from playwright.sync_api import sync_playwright

    git_hash = _git_hash()
    machine = platform.node()
    run_id = db.record_run("quality-sweep", git_hash, machine)

    screenshots = []
    t0 = time.time()

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1920, "height": 1080})

        # Navigate and wait
        page.goto(f"{url}/")
        page.wait_for_load_state("networkidle")
        time.sleep(3)

        # Screenshot at load (t=0)
        s1 = _take_screenshot(page, "load_t0", SCREENSHOT_DIR)
        screenshots.append(s1)

        # Wait for units (t=3s)
        time.sleep(3)
        s2 = _take_screenshot(page, "units_t3", SCREENSHOT_DIR)
        screenshots.append(s2)

        # Capture metrics
        metrics = _capture_metrics(page)

        # Screenshot after 10s
        time.sleep(4)
        s3 = _take_screenshot(page, "steady_t10", SCREENSHOT_DIR)
        screenshots.append(s3)

        browser.close()

    elapsed_ms = (time.time() - t0) * 1000

    # Record results
    passed = (
        metrics.get("console_errors", 0) == 0
        and metrics.get("canvas_brightness_pct") is not None
        and (metrics.get("canvas_brightness_pct") or 0) > 5
    )

    db.record_result(
        run_id=run_id,
        test_name="quality_sweep",
        passed=passed,
        duration_ms=elapsed_ms,
        details=metrics,
    )

    # Record screenshots
    for s in screenshots:
        db.record_screenshot(
            run_id=run_id,
            test_name="quality_sweep",
            phase=s.stem,
            image_path=str(s),
            opencv_results={},
            llava_response="",
            llava_host="",
            llava_ms=0,
            api_state=metrics,
        )

    db.finish_run(run_id)

    _print_summary(metrics, screenshots)
    return run_id


def _run_baseline(url: str, db: ResultsDB) -> None:
    """Capture baselines: screenshots + metrics JSON."""
    from playwright.sync_api import sync_playwright

    BASELINE_DIR.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1920, "height": 1080})

        page.goto(f"{url}/")
        page.wait_for_load_state("networkidle")
        time.sleep(5)

        # Capture baseline screenshots
        _take_screenshot(page, "baseline_load", BASELINE_DIR)
        time.sleep(3)
        _take_screenshot(page, "baseline_steady", BASELINE_DIR)

        # Capture metrics
        metrics = _capture_metrics(page)

        browser.close()

    # Save metrics as JSON
    metrics_path = BASELINE_DIR / "baseline_metrics.json"
    metrics_path.write_text(json.dumps(metrics, indent=2))

    print(f"Baselines saved to {BASELINE_DIR}/")
    print(f"  baseline_load.png")
    print(f"  baseline_steady.png")
    print(f"  baseline_metrics.json")

    # Also run a sweep for the DB record
    _run_single_sweep(url, db)


def _run_report(db: ResultsDB) -> None:
    """Generate an HTML report from the latest sweep run."""
    trend = db.get_trend("quality-sweep", last_n=1)
    if not trend:
        print("No quality-sweep runs found in the database.")
        print(f"  DB path: {RESULTS_DB_PATH}")
        sys.exit(1)

    run_id = trend[-1]["id"]
    gen = ReportGenerator(db, output_dir=str(_PROJECT_ROOT / "tests" / ".test-results" / "reports"))
    path = gen.generate(run_id)
    print(f"Report generated: {path}")
    json_path = gen.export_json(run_id)
    print(f"JSON metrics: {json_path}")


def _run_watch(url: str, db: ResultsDB, interval: int = 60) -> None:
    """Continuous sweep every interval seconds."""
    print(f"Watch mode: sweeping every {interval}s (Ctrl+C to stop)")
    try:
        while True:
            print(f"\n[{time.strftime('%H:%M:%S')}] Running sweep...")
            try:
                _run_single_sweep(url, db)
            except Exception as e:
                print(f"  Sweep failed: {e}")
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\nWatch mode stopped.")


def main():
    parser = argparse.ArgumentParser(
        description="Quality sweep for Command Center"
    )
    parser.add_argument(
        "--url", default="http://localhost:8000",
        help="Server URL (default: http://localhost:8000)",
    )
    parser.add_argument(
        "--watch", action="store_true",
        help="Continuous sweep every 60s",
    )
    parser.add_argument(
        "--baseline", action="store_true",
        help="Capture new baselines",
    )
    parser.add_argument(
        "--report", action="store_true",
        help="Generate HTML report from latest run",
    )
    parser.add_argument(
        "--interval", type=int, default=60,
        help="Watch interval in seconds (default: 60)",
    )
    args = parser.parse_args()

    # Check Playwright availability
    if not _check_playwright() and not args.report:
        print("ERROR: Playwright is not installed.")
        print("  Install with: pip install playwright && playwright install chromium")
        sys.exit(1)

    db = ResultsDB(db_path=RESULTS_DB_PATH)

    # Report mode does not need a running server
    if args.report:
        _run_report(db)
        db.close()
        return

    # All other modes need a running server
    if not _check_server(args.url):
        print(f"ERROR: Server not reachable at {args.url}")
        print("  Start it with: ./start.sh")
        sys.exit(1)

    try:
        if args.baseline:
            _run_baseline(args.url, db)
        elif args.watch:
            _run_watch(args.url, db, interval=args.interval)
        else:
            _run_single_sweep(args.url, db)
    finally:
        db.close()


if __name__ == "__main__":
    main()
