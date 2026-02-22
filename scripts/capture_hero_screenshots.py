#!/usr/bin/env python3
"""Capture high-resolution hero screenshots for the README.

Starts a headless TRITIUM-SC server, drives the /unified Command Center
through three distinct visual states, and saves 1920x1080 screenshots
to docs/screenshots/.

Screenshots:
  1. command-center.png  — Tactical overview with panels and units
  2. game-combat.png     — Active wave combat with projectiles
  3. neighborhood-wide.png — Zoomed-out satellite neighborhood view

Usage:
    .venv/bin/python3 scripts/capture_hero_screenshots.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import cv2
import numpy as np
import requests

# Add project root to path for imports
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT))

from tests.lib.server_manager import TritiumServer

OUTPUT_DIR = PROJECT_ROOT / "docs" / "screenshots"

# BGR colors from the UI (for scoring combat frames)
FRIENDLY_GREEN_BGR = np.array([161, 255, 5])    # #05ffa1
HOSTILE_RED_BGR = np.array([109, 42, 255])       # #ff2a6d


def log(msg: str) -> None:
    ts = time.strftime("%H:%M:%S")
    print(f"  [{ts}] {msg}")


def count_color_pixels(img: np.ndarray, target_bgr: np.ndarray,
                       tolerance: int = 50) -> int:
    """Count pixels close to a target color."""
    lower = np.clip(target_bgr.astype(int) - tolerance, 0, 255).astype(np.uint8)
    upper = np.clip(target_bgr.astype(int) + tolerance, 0, 255).astype(np.uint8)
    mask = cv2.inRange(img, lower, upper)
    return int(np.count_nonzero(mask))


def score_combat_frame(img: np.ndarray) -> float:
    """Score a frame by how much visible combat activity it has.

    Higher = more red + green blobs + overall brightness (more action).
    """
    green = count_color_pixels(img, FRIENDLY_GREEN_BGR, tolerance=50)
    red = count_color_pixels(img, HOSTILE_RED_BGR, tolerance=60)
    # Weight red higher since hostiles are what makes it look like combat
    return green + red * 2.0


def api_get(base_url: str, path: str):
    try:
        resp = requests.get(f"{base_url}{path}", timeout=5)
        return resp.json() if resp.status_code == 200 else None
    except Exception:
        return None


def api_post(base_url: str, path: str, data: dict | None = None):
    try:
        resp = requests.post(f"{base_url}{path}", json=data or {}, timeout=5)
        return resp.json() if resp.status_code in (200, 400) else None
    except Exception:
        return None


def get_targets(base_url: str) -> list[dict]:
    data = api_get(base_url, "/api/amy/simulation/targets")
    if isinstance(data, dict):
        return data.get("targets", [])
    return data if isinstance(data, list) else []


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print("=" * 70)
    print("  TRITIUM-SC Hero Screenshot Capture")
    print("=" * 70)

    # ---- Start server ----
    log("Starting server...")
    server = TritiumServer(auto_port=True)
    server.start()
    log(f"Server running at {server.url}")

    try:
        return run_capture(server)
    finally:
        log("Stopping server...")
        server.stop()
        log("Done.")


def run_capture(server: TritiumServer) -> int:
    from playwright.sync_api import sync_playwright

    log("Launching headless Chromium (1920x1080)...")
    pw = sync_playwright().start()
    browser = pw.chromium.launch(headless=True)
    ctx = browser.new_context(viewport={"width": 1920, "height": 1080})
    page = ctx.new_page()

    try:
        # Navigate to /unified
        log("Navigating to /unified...")
        page.goto(f"{server.url}/unified", wait_until="networkidle")
        page.wait_for_timeout(3000)

        # Wait for simulation data (units on the map)
        log("Waiting for simulation units...")
        try:
            page.wait_for_function(
                "() => window.TritiumStore && window.TritiumStore.units && window.TritiumStore.units.size >= 3",
                timeout=15000,
            )
            log("Units loaded.")
        except Exception:
            log("WARNING: TritiumStore units not detected, continuing anyway...")

        # Let the map render and satellite tiles load
        page.wait_for_timeout(3000)

        # ==================================================================
        # Screenshot 1: Command Center — Tactical Overview
        # ==================================================================
        log("--- Screenshot 1: Command Center ---")

        # Ensure panels are visible (Units list, Amy thoughts)
        # The default /unified view should show panels
        page.wait_for_timeout(1000)

        path1 = str(OUTPUT_DIR / "command-center.png")
        page.screenshot(path=path1)
        img1 = cv2.imread(path1)
        green1 = count_color_pixels(img1, FRIENDLY_GREEN_BGR)
        log(f"Saved: {path1} ({img1.shape[1]}x{img1.shape[0]}, green pixels: {green1})")

        # ==================================================================
        # Screenshot 2: Battle — Active Combat
        # ==================================================================
        log("--- Screenshot 2: Active Combat ---")

        # Reset game state
        api_post(server.url, "/api/game/reset")
        page.wait_for_timeout(1000)

        # Place turrets in a visually interesting spread (diamond + corners)
        turret_positions = [
            (0, 0, "Alpha"),
            (12, 5, "Bravo"),
            (-12, 5, "Charlie"),
            (6, -10, "Delta"),
            (-6, -10, "Echo"),
            (15, -5, "Foxtrot"),
            (-15, -5, "Golf"),
        ]
        for x, y, name in turret_positions:
            api_post(server.url, "/api/game/place", {
                "name": name, "asset_type": "turret",
                "position": {"x": x, "y": y},
            })
        log(f"Placed {len(turret_positions)} turrets")

        page.wait_for_timeout(2000)

        # Begin war
        api_post(server.url, "/api/game/begin")
        log("War begun. Waiting for hostiles...")

        # Wait for hostiles to spawn (up to 30s)
        hostile_found = False
        for tick in range(30):
            time.sleep(1)
            targets = get_targets(server.url)
            hostiles = [t for t in targets if t.get("alliance") == "hostile"]
            if hostiles:
                hostile_found = True
                log(f"Hostiles detected at t={tick}s: {len(hostiles)} hostiles")
                break
            if tick % 10 == 0:
                log(f"Waiting... t={tick}s")

        if not hostile_found:
            log("WARNING: No hostiles spawned within 30s")

        # Let combat develop for a few seconds
        page.wait_for_timeout(3000)

        # Burst capture: 10 frames over 5 seconds, pick best
        log("Burst capturing 10 frames...")
        best_score = -1.0
        best_img = None
        for i in range(10):
            burst_path = str(OUTPUT_DIR / f"_burst_{i}.png")
            page.screenshot(path=burst_path)
            img = cv2.imread(burst_path)
            score = score_combat_frame(img)
            if score > best_score:
                best_score = score
                best_img = img
                log(f"  Frame {i}: score={score:.0f} (new best)")
            else:
                log(f"  Frame {i}: score={score:.0f}")
            page.wait_for_timeout(500)

        # Save best combat frame
        path2 = str(OUTPUT_DIR / "game-combat.png")
        if best_img is not None:
            cv2.imwrite(path2, best_img)
            log(f"Saved: {path2} (best score: {best_score:.0f})")
        else:
            page.screenshot(path=path2)
            log(f"Saved: {path2} (fallback single frame)")

        # Clean up burst files
        for i in range(10):
            burst_file = OUTPUT_DIR / f"_burst_{i}.png"
            if burst_file.exists():
                burst_file.unlink()

        # ==================================================================
        # Screenshot 3: Neighborhood — Wide Strategic View
        # ==================================================================
        log("--- Screenshot 3: Neighborhood Wide View ---")

        # Reset game to show default patrol units (less clutter than combat)
        api_post(server.url, "/api/game/reset")
        page.wait_for_timeout(3000)

        # Hide panels for a cleaner wide view
        page.evaluate("""() => {
            document.querySelectorAll('.panel').forEach(p => {
                p.style.display = 'none';
            });
        }""")
        page.wait_for_timeout(500)

        # Zoom out by directly setting the camera zoom in warState
        # Zoom is clamped to [0.3, 5.0] in the wheel handler; set to minimum
        page.evaluate("""() => {
            if (window.warState && window.warState.cam) {
                window.warState.cam.targetZoom = 0.3;
                window.warState.cam.zoom = 0.3;
                // Center on the map origin for a balanced view
                window.warState.cam.targetX = 0;
                window.warState.cam.targetY = 0;
                window.warState.cam.x = 0;
                window.warState.cam.y = 0;
            }
        }""")
        log("Zoomed out to 0.3x (minimum) for wide neighborhood view")

        # Let the map re-render at the new zoom level
        page.wait_for_timeout(3000)

        path3 = str(OUTPUT_DIR / "neighborhood-wide.png")
        page.screenshot(path=path3)
        img3 = cv2.imread(path3)
        log(f"Saved: {path3} ({img3.shape[1]}x{img3.shape[0]})")

        # ==================================================================
        # Summary
        # ==================================================================
        print()
        print("=" * 70)
        print("  CAPTURE COMPLETE")
        print("=" * 70)
        for name in ["command-center.png", "game-combat.png", "neighborhood-wide.png"]:
            fpath = OUTPUT_DIR / name
            if fpath.exists():
                img = cv2.imread(str(fpath))
                size_kb = fpath.stat().st_size // 1024
                print(f"  {name:30s} {img.shape[1]}x{img.shape[0]}  {size_kb}KB")
            else:
                print(f"  {name:30s} MISSING")
        print("=" * 70)

        return 0

    finally:
        browser.close()
        pw.stop()


if __name__ == "__main__":
    sys.exit(main())
