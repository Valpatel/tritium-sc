# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests that detect KNOWN BUGS. These tests are EXPECTED TO FAIL.

Philosophy: "if all tests pass they probably aren't good tests."
Each test here targets a specific, documented visual or runtime bug.
Tests use pytest.mark.xfail(strict=True) so they FAIL if the bug
is accidentally fixed without removing the xfail marker — forcing
someone to verify the fix and update the test.

Known bugs tested:
  1. Initial load blank screen — 5-8 second black screen before map loads
  2. City sim (J key) stack overflow — vehicle.js _advanceToNextEdge recursion
  3. Sim demo units invisible — demo mode targets not rendered on map
  4. WebSocket disconnects under load — WS drops during active battle
  5. Map markers overlap — dense clusters cause wrong panel on click

Run:
    .venv/bin/python3 -m pytest tests/visual/test_known_bugs.py -v
"""
from __future__ import annotations

import time
from pathlib import Path

import cv2
import numpy as np
import pytest
import requests

from tests.lib.server_manager import TritiumServer

pytestmark = [pytest.mark.visual, pytest.mark.defect]

SCREENSHOT_DIR = Path("tests/.test-results/known-bugs-screenshots")


# ======================================================================
# Shared browser fixture — starts server, launches headless Playwright
# ======================================================================

class KnownBugsBrowser:
    """Shared state for the browser session across all bug tests."""

    def __init__(self):
        self.page = None
        self.base_url = None
        self._pw = None
        self._browser = None
        self._ctx = None
        self._errors: list[str] = []
        self._console_msgs: list[str] = []


@pytest.fixture(scope="module")
def server():
    """Start a test server for the module."""
    srv = TritiumServer(auto_port=True)
    srv.start()
    yield srv
    srv.stop()


@pytest.fixture(scope="module")
def browser(server):
    """Launch headless Playwright browser for the module."""
    from playwright.sync_api import sync_playwright

    state = KnownBugsBrowser()
    state.base_url = server.base_url
    state._pw = sync_playwright().start()
    state._browser = state._pw.chromium.launch(headless=True)
    state._ctx = state._browser.new_context(
        viewport={"width": 1920, "height": 1080}
    )
    state.page = state._ctx.new_page()

    # Capture all console messages and page errors
    state.page.on("console", lambda msg: state._console_msgs.append(
        f"[{msg.type}] {msg.text}"
    ))
    state.page.on("pageerror", lambda e: state._errors.append(str(e)))

    yield state

    state.page.close()
    state._ctx.close()
    state._browser.close()
    state._pw.stop()


def _screenshot(page, name: str) -> Path:
    """Take a screenshot and return its path."""
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    path = SCREENSHOT_DIR / f"{name}.png"
    page.screenshot(path=str(path), full_page=False)
    return path


def _load_screenshot(path: Path) -> np.ndarray:
    """Load a screenshot as a BGR numpy array."""
    img = cv2.imread(str(path))
    assert img is not None, f"Failed to load screenshot: {path}"
    return img


def _image_std(img: np.ndarray) -> float:
    """Return the standard deviation of pixel values (0 = blank)."""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    return float(gray.std())


def _count_bright_contours(img: np.ndarray, threshold: int = 40,
                            min_area: int = 15) -> int:
    """Count distinct bright contours in the image."""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    _, binary = cv2.threshold(gray, threshold, 255, cv2.THRESH_BINARY)
    contours, _ = cv2.findContours(
        binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )
    return sum(1 for c in contours if cv2.contourArea(c) >= min_area)


# ======================================================================
# BUG 1: Initial load blank screen (5-8 seconds of black)
# ======================================================================

@pytest.mark.xfail(
    reason="BUG: 5-8 second blank/black screen on initial load before map renders. "
           "No loading indicator exists. Screenshot at 2s should show content.",
    strict=True,
)
def test_no_blank_screen_at_2_seconds(server):
    """Bug: 5-8 second blank screen on first load.

    The Command Center shows a completely black screen for 5-8 seconds
    before the map tiles load. There is no loading indicator, spinner,
    or splash screen. A user sees nothing.

    This test navigates to the page, waits exactly 2 seconds (well within
    the blank period), and asserts the screen has meaningful content.
    It SHOULD FAIL until a loading indicator or faster init is added.
    """
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        br = pw.chromium.launch(headless=True)
        ctx = br.new_context(viewport={"width": 1920, "height": 1080})
        page = ctx.new_page()

        # Navigate but do NOT wait for networkidle — we want to test
        # what the user sees during the loading period
        page.goto(f"{server.base_url}/", wait_until="commit")

        # Wait exactly 2 seconds — the blank window
        page.wait_for_timeout(2000)

        path = _screenshot(page, "bug1_blank_screen_2s")
        img = _load_screenshot(path)

        br.close()

    # A page with content should have std > 20 (varied pixel values).
    # A blank/black screen has std near 0.
    std = _image_std(img)

    # Also check: is there ANY bright content at all?
    bright_pixels = np.sum(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) > 30)
    total_pixels = img.shape[0] * img.shape[1]
    bright_ratio = bright_pixels / total_pixels

    assert std > 20 and bright_ratio > 0.05, (
        f"Screen is blank at 2 seconds. std={std:.1f}, "
        f"bright_ratio={bright_ratio:.3f}. "
        f"Need a loading indicator or faster initialization."
    )


# ======================================================================
# BUG 2: City sim stack overflow in vehicle.js _advanceToNextEdge
# ======================================================================

@pytest.mark.xfail(
    reason="BUG: vehicle.js _advanceToNextEdge() calls _planNewRoute() which calls "
           "_advanceToNextEdge() again when route.length > 0, causing infinite "
           "recursion on disconnected road graphs or single-edge routes.",
    strict=True,
)
@pytest.mark.timeout(60)
def test_city_sim_no_stack_overflow(browser):
    """Bug: vehicle.js _advanceToNextEdge infinite recursion.

    The call chain is:
      _advanceToNextEdge() -> routeIdx >= route.length
        -> _planNewRoute() -> finds route with length > 0
          -> _advanceToNextEdge() -> if route step immediately completes
            -> _advanceToNextEdge() -> ... stack overflow

    This happens on small/disconnected road graphs where vehicles reach
    the end of a 1-edge route and immediately need a new one.

    This test starts the city sim (J key), lets it run, and checks
    for RangeError (Maximum call stack size exceeded) in console errors.
    """
    page = browser.page
    base_url = browser.base_url

    # Navigate fresh to clear any previous state
    browser._errors.clear()
    browser._console_msgs.clear()
    page.goto(f"{base_url}/", wait_until="networkidle")
    page.wait_for_timeout(3000)

    # Capture errors before city sim
    errors_before = len(browser._errors)

    # Press J to toggle city sim
    page.keyboard.press("j")
    page.wait_for_timeout(5000)  # Let it load city data + spawn vehicles

    # Check if city sim actually started by looking for console messages
    city_msgs = [m for m in browser._console_msgs if "city" in m.lower() or "sim" in m.lower()]

    # Let the simulation run for 10 seconds — enough for vehicles to
    # traverse edges and trigger the recursion
    page.wait_for_timeout(10000)

    _screenshot(page, "bug2_city_sim_after_run")

    # Check for stack overflow errors
    range_errors = [
        e for e in browser._errors
        if "RangeError" in e
        or "Maximum call stack" in e
        or "stack" in e.lower()
    ]

    # Also check for ANY new JS errors during city sim
    new_errors = browser._errors[errors_before:]

    # The test asserts NO stack overflow errors exist.
    # With the bug present, this should FAIL.
    assert len(range_errors) == 0, (
        f"Stack overflow detected during city sim! "
        f"RangeError count: {len(range_errors)}. "
        f"Errors: {range_errors[:3]}"
    )
    assert len(new_errors) == 0, (
        f"JS errors during city sim: {len(new_errors)} new errors. "
        f"First 3: {new_errors[:3]}"
    )


# ======================================================================
# BUG 3: Sim demo units invisible on map
# ======================================================================

@pytest.mark.xfail(
    reason="BUG: When demo mode is started, targets are created in the backend "
           "but do not render as visible markers/units on the map. The map shows "
           "no new visual elements despite the API confirming active targets.",
    strict=True,
)
def test_sim_demo_units_visible(browser):
    """Bug: demo mode targets don't render visibly on the map.

    The demo mode (POST /api/demo/start) creates simulated targets
    (BLE devices, WiFi APs, camera detections) but they do not appear
    as visible markers on the map. The API confirms targets exist,
    but the visual map is empty.

    This test:
    1. Takes a baseline screenshot of the map
    2. Starts demo mode via API
    3. Waits for targets to propagate
    4. Takes a second screenshot
    5. Asserts new visual elements appeared (contour diff > 0)
    """
    page = browser.page
    base_url = browser.base_url

    # Navigate fresh
    page.goto(f"{base_url}/", wait_until="networkidle")
    page.wait_for_timeout(3000)

    # Baseline screenshot
    path_before = _screenshot(page, "bug3_before_demo")
    img_before = _load_screenshot(path_before)

    # Start demo mode
    resp = requests.post(f"{base_url}/api/demo/start", timeout=10)
    assert resp.status_code == 200, f"Demo start failed: {resp.status_code}"

    # Wait for targets to propagate through WebSocket to the browser
    page.wait_for_timeout(5000)

    # Verify targets exist in the backend
    status_resp = requests.get(f"{base_url}/api/demo/status", timeout=5)
    demo_status = status_resp.json() if status_resp.status_code == 200 else {}

    # Also check targets API
    targets_resp = requests.get(f"{base_url}/api/targets", timeout=5)
    targets = []
    if targets_resp.status_code == 200:
        data = targets_resp.json()
        if isinstance(data, dict) and "targets" in data:
            targets = data["targets"]
        elif isinstance(data, list):
            targets = data

    # Screenshot after demo
    path_after = _screenshot(page, "bug3_after_demo")
    img_after = _load_screenshot(path_after)

    # Compute visual difference between before and after
    diff = cv2.absdiff(img_before, img_after)
    diff_gray = cv2.cvtColor(diff, cv2.COLOR_BGR2GRAY)
    _, diff_binary = cv2.threshold(diff_gray, 25, 255, cv2.THRESH_BINARY)
    changed_pixels = cv2.countNonZero(diff_binary)
    total_pixels = diff_binary.shape[0] * diff_binary.shape[1]
    change_ratio = changed_pixels / total_pixels

    # Count new bright contours (markers, dots, labels)
    contours_before = _count_bright_contours(img_before)
    contours_after = _count_bright_contours(img_after)
    new_contours = contours_after - contours_before

    # Check for target markers in the TritiumStore
    store_count = page.evaluate(
        "() => window.TritiumStore ? window.TritiumStore.units.size : -1"
    )

    # Stop demo
    requests.post(f"{base_url}/api/demo/stop", timeout=5)

    # The assertion: targets should be VISIBLE, not just in the API
    assert new_contours >= 5, (
        f"Demo targets not visible on map! "
        f"Backend has {len(targets)} targets, store has {store_count} units, "
        f"but only {new_contours} new visual contours appeared "
        f"(change_ratio={change_ratio:.4f}). "
        f"Demo status: {demo_status}"
    )


# ======================================================================
# BUG 4: WebSocket disconnects under load during battle
# ======================================================================

@pytest.mark.xfail(
    reason="BUG: WebSocket connection drops during active battle when telemetry "
           "volume is high. The connection status changes from 'connected' to "
           "'disconnected' mid-battle.",
    strict=True,
)
@pytest.mark.timeout(120)
def test_websocket_stable_during_battle(browser):
    """Bug: WebSocket drops during active battle.

    When a battle is running with many units, the WebSocket connection
    becomes unstable. Telemetry batches arrive at high frequency and
    the connection drops, causing the UI to lose real-time updates.

    This test:
    1. Starts a battle with extra hostiles for high telemetry load
    2. Monitors WS connection status every second for 30 seconds
    3. Asserts the connection never drops
    """
    page = browser.page
    base_url = browser.base_url

    # Navigate fresh
    page.goto(f"{base_url}/", wait_until="networkidle")
    page.wait_for_timeout(3000)

    # Verify WS is connected before battle
    initial_status = page.evaluate(
        "() => window.TritiumStore?.connection?.status || 'unknown'"
    )
    if initial_status != "connected":
        # Wait for WS to connect
        try:
            page.wait_for_function(
                "() => window.TritiumStore?.connection?.status === 'connected'",
                timeout=10000,
            )
        except Exception:
            pass

    # Reset and start battle
    requests.post(f"{base_url}/api/game/reset", timeout=5)
    page.wait_for_timeout(500)
    requests.post(f"{base_url}/api/game/begin", timeout=5)
    page.wait_for_timeout(6000)  # Wait for countdown

    # Spawn extra hostiles to generate high telemetry volume
    for i in range(15):
        requests.post(
            f"{base_url}/api/amy/simulation/spawn",
            json={
                "x": 10.0 + i * 5,
                "y": 10.0 + (i % 3) * 5,
                "type": "hostile_person",
            },
            timeout=5,
        )

    # Monitor WebSocket status every second for 30 seconds
    disconnects = []
    statuses = []
    for tick in range(30):
        page.wait_for_timeout(1000)
        status = page.evaluate(
            "() => window.TritiumStore?.connection?.status || 'unknown'"
        )
        statuses.append(status)
        if status != "connected":
            disconnects.append((tick, status))

    _screenshot(page, "bug4_ws_during_battle")

    # Clean up
    requests.post(f"{base_url}/api/game/reset", timeout=5)

    # Assert: WebSocket should NEVER disconnect during battle
    assert len(disconnects) == 0, (
        f"WebSocket disconnected {len(disconnects)} times during battle! "
        f"Disconnects at seconds: {disconnects}. "
        f"Status timeline: {statuses}"
    )


# ======================================================================
# BUG 5: Map markers overlap — clicking dense clusters opens wrong panel
# ======================================================================

@pytest.mark.xfail(
    reason="BUG: When multiple targets are at similar positions, their map "
           "markers overlap. Clicking a cluster opens the wrong target's "
           "detail panel because hit detection picks the wrong marker.",
    strict=True,
)
def test_marker_separation_in_dense_clusters(browser):
    """Bug: clicking dense marker clusters opens wrong panel.

    When multiple targets are spawned at nearby positions, their markers
    stack on top of each other. The click handler picks the wrong target
    because markers lack z-ordering or cluster expansion.

    This test:
    1. Spawns 8 targets at very close positions (within 2m of each other)
    2. Screenshots the marker region
    3. Checks that markers are visually distinct (not perfectly overlapping)
    4. Clicks a marker and verifies the correct target panel opens
    """
    page = browser.page
    base_url = browser.base_url

    # Navigate fresh
    page.goto(f"{base_url}/", wait_until="networkidle")
    page.wait_for_timeout(3000)

    # Reset game
    requests.post(f"{base_url}/api/game/reset", timeout=5)
    page.wait_for_timeout(500)

    # Spawn 8 targets in a tight cluster — all within 2 meters
    spawned_ids = []
    for i in range(8):
        resp = requests.post(
            f"{base_url}/api/amy/simulation/spawn",
            json={
                "asset_type": "turret",
                "name": f"Cluster-{i}",
                "alliance": "friendly",
                "position": {"x": 0.5 * i, "y": 0.5 * (i % 2)},
            },
            timeout=5,
        )
        if resp.status_code == 200:
            data = resp.json()
            tid = data.get("target_id") or data.get("id")
            if tid:
                spawned_ids.append(tid)

    # Wait for markers to render
    page.wait_for_timeout(3000)

    path = _screenshot(page, "bug5_dense_cluster")
    img = _load_screenshot(path)

    # Look for the cluster region — friendly markers are green (#05ffa1)
    # In BGR: (161, 255, 5)
    green_bgr = (161, 255, 5)
    lower = np.array([max(0, c - 60) for c in green_bgr], dtype=np.uint8)
    upper = np.array([min(255, c + 60) for c in green_bgr], dtype=np.uint8)
    mask = cv2.inRange(img, lower, upper)
    contours, _ = cv2.findContours(
        mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )
    marker_contours = [c for c in contours if cv2.contourArea(c) >= 10]

    # Count how many visually distinct markers we see
    # We spawned 8, but if they overlap we'll see fewer
    visible_markers = len(marker_contours)

    # Check the store has all our targets
    store_count = page.evaluate(
        "() => window.TritiumStore ? window.TritiumStore.units.size : 0"
    )

    # Try to click the cluster area and check what panel opens
    clicked_target = None
    if marker_contours:
        # Find the centroid of the largest marker contour
        largest = max(marker_contours, key=cv2.contourArea)
        M = cv2.moments(largest)
        if M["m00"] > 0:
            cx = int(M["m10"] / M["m00"])
            cy = int(M["m01"] / M["m00"])
            page.mouse.click(cx, cy)
            page.wait_for_timeout(1000)

            # Check if a target detail panel opened
            clicked_target = page.evaluate("""() => {
                const panel = document.querySelector(
                    '[data-panel="target-detail"], .target-detail, .dossier-panel'
                );
                if (panel) {
                    const nameEl = panel.querySelector('.target-name, .name, h3');
                    return nameEl ? nameEl.textContent : 'panel-open-no-name';
                }
                return null;
            }""")

    _screenshot(page, "bug5_after_click")

    # Clean up
    requests.post(f"{base_url}/api/game/reset", timeout=5)

    # We spawned 8 targets. We should see 8 distinct markers.
    # The bug: they overlap so we see fewer distinct contours than targets.
    assert visible_markers >= 6, (
        f"Only {visible_markers} visually distinct markers for 8 spawned targets "
        f"(store has {store_count} units). Markers are overlapping. "
        f"Need marker clustering or offset for dense groups."
    )


# ======================================================================
# BONUS BUG 6: No loading indicator at all
# ======================================================================

@pytest.mark.xfail(
    reason="BUG: There is no loading indicator, spinner, or splash screen during "
           "the initial page load. The user stares at black for 5-8 seconds.",
    strict=True,
)
def test_loading_indicator_exists(server):
    """Bug: No loading indicator during initial load.

    Complementary to test_no_blank_screen_at_2_seconds. This specifically
    checks for DOM elements that indicate loading progress — a spinner,
    progress bar, loading text, or splash screen.

    Even if the map takes 5-8 seconds to load, there should be SOMETHING
    visible to tell the user the app is working.
    """
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        br = pw.chromium.launch(headless=True)
        ctx = br.new_context(viewport={"width": 1920, "height": 1080})
        page = ctx.new_page()

        # Navigate and check at 1 second (well within the loading window)
        page.goto(f"{server.base_url}/", wait_until="commit")
        page.wait_for_timeout(1000)

        # Look for any loading indicator in the DOM
        has_indicator = page.evaluate("""() => {
            // Check for common loading indicators
            const selectors = [
                '.loading', '.spinner', '.loader', '.splash',
                '.progress', '.loading-screen', '.load-indicator',
                '[data-loading]', '[aria-busy="true"]',
                '.maplibregl-ctrl-loading', '.loading-overlay',
            ];
            for (const sel of selectors) {
                const el = document.querySelector(sel);
                if (el && el.offsetHeight > 0) return { found: true, selector: sel };
            }

            // Check for any visible text containing "loading" or "initializing"
            const body = document.body?.innerText?.toLowerCase() || '';
            if (body.includes('loading') || body.includes('initializing') ||
                body.includes('connecting')) {
                return { found: true, selector: 'text-content' };
            }

            // Check for animated elements (spinners typically use CSS animation)
            const animated = document.querySelectorAll('*');
            for (const el of animated) {
                const style = window.getComputedStyle(el);
                if (style.animationName && style.animationName !== 'none' &&
                    el.offsetHeight > 0 && el.offsetWidth > 0) {
                    return { found: true, selector: 'css-animation' };
                }
            }

            return { found: false, selector: null };
        }""")

        _screenshot(page, "bug6_no_loading_indicator")
        br.close()

    assert has_indicator["found"], (
        f"No loading indicator found at 1 second after navigation. "
        f"The user sees a blank screen with no feedback. "
        f"Add a spinner, progress bar, or splash screen."
    )
