# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Strict OpenCV visual assertions for SC Command Center.

Each test captures a Playwright screenshot and applies deterministic
pixel-level OpenCV analysis. Tests FAIL when expected visual elements
are missing — no baselines, no golden images, just hard assertions.

Tested views:
  1. Satellite tile color variance in map region
  2. Cyberpunk header bar with cyan pixels
  3. Demo mode generating target markers
  4. NATO-style marker contour shapes
  5. Command palette modal overlay
  6. Battle HUD text density
  7. Console error absence on load
  8. WebSocket connection indicator DOM presence

Usage:
  pytest tests/visual/test_opencv_strict.py -v
"""

from __future__ import annotations

import time
from pathlib import Path

import cv2
import numpy as np
import pytest
import requests

pytestmark = pytest.mark.visual

VIEWPORT_WIDTH = 1920
VIEWPORT_HEIGHT = 1080

SCREENSHOT_DIR = Path(__file__).parent.parent / ".baselines" / "strict"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _screenshot(page, name: str) -> tuple[Path, np.ndarray]:
    """Capture a full-page screenshot and return (path, BGR numpy array)."""
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    path = SCREENSHOT_DIR / f"{name}.png"
    page.screenshot(path=str(path), timeout=60000, animations="disabled")
    img = cv2.imread(str(path))
    assert img is not None, (
        f"Failed to read screenshot '{path}' — file may not have been written."
    )
    return path, img


def _extract_map_region(img: np.ndarray) -> np.ndarray:
    """Extract the center 80% of the screen as the map region.

    The header occupies the top ~50px and the status bar the bottom ~20px,
    so the center 80% is a safe crop of the tactical map area.
    """
    h, w = img.shape[:2]
    x_margin = int(w * 0.10)
    y_margin = int(h * 0.10)
    return img[y_margin:h - y_margin, x_margin:w - x_margin]


# ---------------------------------------------------------------------------
# Test class
# ---------------------------------------------------------------------------

class TestOpenCVStrict:
    """Strict pixel-level visual assertions using Playwright + OpenCV."""

    @pytest.fixture(autouse=True)
    def _setup(self, tritium_server):
        """Launch headless browser pointing at test server."""
        self.server_url = tritium_server.url

        from playwright.sync_api import sync_playwright

        self.pw = sync_playwright().start()
        self.browser = self.pw.chromium.launch(headless=True)
        self.context = self.browser.new_context(
            viewport={"width": VIEWPORT_WIDTH, "height": VIEWPORT_HEIGHT},
        )
        self.page = self.context.new_page()
        self.page.goto(self.server_url)
        self.page.wait_for_load_state("networkidle")
        # Allow map tiles and WebGL to settle
        time.sleep(4)

        yield

        # Cleanup
        try:
            requests.post(f"{self.server_url}/api/demo/stop", timeout=3)
        except Exception:
            pass
        try:
            requests.post(f"{self.server_url}/api/game/reset", timeout=3)
        except Exception:
            pass

        self.browser.close()
        self.pw.stop()

    # -------------------------------------------------------------------
    # 1. Map has satellite tiles (high color variance)
    # -------------------------------------------------------------------

    def test_map_has_satellite_tiles(self):
        """The map area should show satellite imagery with high color variance.

        Satellite tiles produce varied earth tones, greens, grays. A blank
        or failed-to-load map would be near-uniform (dark gray or black).
        We check that the per-channel standard deviation across the center
        80% of the screen exceeds 30.
        """
        _, img = _screenshot(self.page, "map_satellite_tiles")
        map_region = _extract_map_region(img)

        # Compute per-channel std, then take the mean across channels
        per_channel_std = np.std(map_region.astype(np.float64), axis=(0, 1))
        mean_std = float(np.mean(per_channel_std))

        assert mean_std > 30, (
            f"MAP TILES MISSING: Mean color std in map region is {mean_std:.1f} "
            f"(threshold: >30). The map area appears near-uniform, which means "
            f"satellite tiles did not load. Per-channel std: "
            f"B={per_channel_std[0]:.1f}, G={per_channel_std[1]:.1f}, "
            f"R={per_channel_std[2]:.1f}. "
            f"Check that the tile server is reachable and MapLibre initialized."
        )

    # -------------------------------------------------------------------
    # 2. Header bar present with cyan pixels
    # -------------------------------------------------------------------

    def test_header_bar_present(self):
        """The cyberpunk header in the top 50px should contain cyan pixels.

        The header displays 'TRITIUM-SC', mode indicators, and stats using
        the brand cyan (#00f0ff). We scan the top 50px strip for pixels
        in the cyan color range (BGR: high B, high G, low R).
        """
        _, img = _screenshot(self.page, "header_bar")
        top_strip = img[:50, :, :]

        # Cyan in BGR: B~255, G~240, R~0  with generous tolerance
        # #00f0ff = R:0 G:240 B:255 -> BGR(255, 240, 0)
        lower_cyan = np.array([180, 170, 0], dtype=np.uint8)
        upper_cyan = np.array([255, 255, 80], dtype=np.uint8)
        mask = cv2.inRange(top_strip, lower_cyan, upper_cyan)
        cyan_pixel_count = int(cv2.countNonZero(mask))

        assert cyan_pixel_count > 0, (
            f"HEADER BAR MISSING CYAN: Found {cyan_pixel_count} cyan pixels "
            f"in the top 50px strip (expected >0). The cyberpunk header with "
            f"brand color #00f0ff is not rendering. Check that the "
            f"<header id='header-bar'> element exists and cybercore CSS loaded. "
            f"Top strip mean brightness: {float(top_strip.mean()):.1f}."
        )

    # -------------------------------------------------------------------
    # 3. Demo generates target markers
    # -------------------------------------------------------------------

    def test_demo_generates_markers(self):
        """After starting demo, at least 20 distinct colored contours should
        appear in the map area, representing target markers on the map.
        """
        # Start demo mode
        try:
            resp = requests.post(
                f"{self.server_url}/api/demo/start", timeout=10,
            )
            resp.raise_for_status()
        except Exception as exc:
            pytest.skip(f"Demo mode not available: {exc}")
            return

        # Wait for targets to appear on the map
        time.sleep(5)

        # Reload to pick up markers in the DOM/canvas
        self.page.reload()
        self.page.wait_for_load_state("networkidle")
        time.sleep(4)

        _, img = _screenshot(self.page, "demo_markers")
        map_region = _extract_map_region(img)

        # Convert to HSV and look for saturated, bright blobs (markers)
        # Markers are cyan, magenta, green, yellow — all high-saturation
        hsv = cv2.cvtColor(map_region, cv2.COLOR_BGR2HSV)
        # Saturation > 100 and Value > 100 isolates vivid marker colors
        sat_mask = cv2.inRange(
            hsv,
            np.array([0, 100, 100], dtype=np.uint8),
            np.array([180, 255, 255], dtype=np.uint8),
        )

        # Find contours of saturated regions
        contours, _ = cv2.findContours(
            sat_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE,
        )
        # Filter to reasonable marker sizes (10-2000 px area)
        marker_contours = [
            c for c in contours
            if 10 <= cv2.contourArea(c) <= 2000
        ]

        assert len(marker_contours) >= 20, (
            f"DEMO MARKERS MISSING: Found only {len(marker_contours)} "
            f"marker-sized saturated contours in the map area (expected >=20). "
            f"Total saturated contours (all sizes): {len(contours)}. "
            f"Saturated pixel count: {cv2.countNonZero(sat_mask)}. "
            f"Demo targets may not be rendering on the map. "
            f"Check that /api/demo/start populated targets and the frontend "
            f"received them via WebSocket."
        )

    # -------------------------------------------------------------------
    # 4. Markers are NATO-style (small colored rectangles)
    # -------------------------------------------------------------------

    def test_markers_are_nato_style(self):
        """Target markers should be small colored rectangles with aspect
        ratio between 0.5 and 2.0 and area between 50-500px.

        This validates that the rendering engine produces properly shaped
        tactical markers, not random blobs or oversized elements.
        """
        # Start demo for markers
        try:
            resp = requests.post(
                f"{self.server_url}/api/demo/start", timeout=10,
            )
            resp.raise_for_status()
        except Exception as exc:
            pytest.skip(f"Demo mode not available: {exc}")
            return

        time.sleep(5)
        self.page.reload()
        self.page.wait_for_load_state("networkidle")
        time.sleep(4)

        _, img = _screenshot(self.page, "nato_markers")
        map_region = _extract_map_region(img)

        # Isolate vivid colored regions (marker colors)
        hsv = cv2.cvtColor(map_region, cv2.COLOR_BGR2HSV)
        sat_mask = cv2.inRange(
            hsv,
            np.array([0, 100, 100], dtype=np.uint8),
            np.array([180, 255, 255], dtype=np.uint8),
        )

        contours, _ = cv2.findContours(
            sat_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE,
        )

        nato_contours = []
        for c in contours:
            area = cv2.contourArea(c)
            if area < 50 or area > 500:
                continue
            x, y, w, h = cv2.boundingRect(c)
            if h == 0:
                continue
            aspect = w / h
            if 0.5 <= aspect <= 2.0:
                nato_contours.append(c)

        assert len(nato_contours) > 0, (
            f"NO NATO-STYLE MARKERS: Found 0 contours with aspect ratio "
            f"0.5-2.0 and area 50-500px in the map region. "
            f"Total contours found: {len(contours)}. "
            f"Marker shapes may be malformed, too large, or not rendering. "
            f"Check map marker rendering in the frontend canvas/WebGL layer."
        )

    # -------------------------------------------------------------------
    # 5. Command palette modal
    # -------------------------------------------------------------------

    def test_command_palette_modal(self):
        """After Ctrl+K, a dark overlay should cover >30% of screen AND
        a bright input box should exist in the center.

        The command palette is a modal with id='command-palette' that
        overlays the map with a dark backdrop and a centered input field.
        """
        # Open command palette
        self.page.keyboard.press("Control+k")
        time.sleep(1.5)

        _, img = _screenshot(self.page, "command_palette")

        h, w = img.shape[:2]
        total_pixels = h * w

        # Check 1: Dark overlay covers >30% of screen
        # The overlay is semi-transparent dark — pixels with brightness < 100
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        dark_mask = gray < 100
        dark_ratio = float(np.sum(dark_mask)) / total_pixels

        assert dark_ratio > 0.30, (
            f"COMMAND PALETTE OVERLAY MISSING: Only {dark_ratio * 100:.1f}% "
            f"of screen has brightness <100 (expected >30%). "
            f"The modal dark overlay is not rendering. "
            f"Check that Ctrl+K triggers the command palette and the "
            f"#command-palette element becomes visible with a backdrop."
        )

        # Check 2: Bright input box in center region
        # The center 40% of the screen should contain a bright element
        # (the input field / palette container)
        center_x1 = int(w * 0.30)
        center_x2 = int(w * 0.70)
        center_y1 = int(h * 0.20)
        center_y2 = int(h * 0.60)
        center_region = gray[center_y1:center_y2, center_x1:center_x2]

        # Look for a bright patch (the input box / palette card)
        bright_mask = center_region > 150
        bright_count = int(np.sum(bright_mask))

        assert bright_count > 100, (
            f"COMMAND PALETTE INPUT MISSING: Found only {bright_count} "
            f"bright pixels (>150) in the center region (expected >100). "
            f"The command palette overlay is dark but no bright input "
            f"box or card is visible in the center. "
            f"Center region mean brightness: {float(center_region.mean()):.1f}."
        )

        # Close palette
        self.page.keyboard.press("Escape")

    # -------------------------------------------------------------------
    # 6. Battle HUD visible (text-dense right sidebar)
    # -------------------------------------------------------------------

    def test_battle_hud_visible(self):
        """After starting a battle, the right 20% of the screen should
        contain a text-dense HUD region with high-contrast edge count > 1000.

        The battle HUD includes wave counters, health bars, unit lists,
        and score overlays — all of which produce many Canny edges.
        """
        # Switch to battle layout
        self.page.keyboard.press("Control+4")
        time.sleep(1)

        # Place turrets for a meaningful battle
        for x, y in [(0, 0), (8, 0), (-8, 0), (0, 8), (0, -8)]:
            try:
                requests.post(
                    f"{self.server_url}/api/game/place",
                    json={
                        "name": "Turret",
                        "asset_type": "turret",
                        "position": {"x": x, "y": y},
                    },
                    timeout=5,
                )
            except Exception:
                pass

        # Start the battle
        try:
            requests.post(f"{self.server_url}/api/game/begin", timeout=5)
        except Exception:
            pytest.skip("Could not start battle via API")
            return

        # Wait for active combat
        for _ in range(20):
            time.sleep(1)
            try:
                resp = requests.get(
                    f"{self.server_url}/api/game/state", timeout=5,
                )
                state = resp.json()
                if state.get("state") == "active":
                    break
            except Exception:
                pass
        time.sleep(3)

        _, img = _screenshot(self.page, "battle_hud")

        h, w = img.shape[:2]
        # Right 20% of screen
        right_strip = img[:, int(w * 0.80):, :]
        right_gray = cv2.cvtColor(right_strip, cv2.COLOR_BGR2GRAY)
        edges = cv2.Canny(right_gray, 50, 150)
        edge_count = int(cv2.countNonZero(edges))

        assert edge_count > 1000, (
            f"BATTLE HUD NOT VISIBLE: Only {edge_count} high-contrast edges "
            f"found in the right 20% of screen (expected >1000). "
            f"The battle HUD (wave counter, health bars, unit lists, score) "
            f"is not rendering in the sidebar. "
            f"Right strip mean brightness: {float(right_gray.mean()):.1f}. "
            f"Check that the battle layout (Ctrl+4) opens sidebar panels "
            f"and game/begin populates them with combat data."
        )

    # -------------------------------------------------------------------
    # 7. No console errors on load
    # -------------------------------------------------------------------

    def test_no_console_errors_on_load(self):
        """Capture browser console output for 10 seconds after load.
        Assert zero 'error' type messages.

        Console errors during initial load indicate broken imports,
        failed API calls, or JavaScript exceptions that degrade the UI.
        """
        console_errors: list[str] = []

        # Create a fresh page with console listener
        page2 = self.context.new_page()
        page2.on("console", lambda msg: (
            console_errors.append(f"[{msg.type}] {msg.text}")
            if msg.type == "error" else None
        ))

        page2.goto(self.server_url)
        page2.wait_for_load_state("networkidle")

        # Wait 10 seconds for late-firing errors (lazy imports, WS retries)
        time.sleep(10)

        page2.close()

        assert len(console_errors) == 0, (
            f"CONSOLE ERRORS ON LOAD: {len(console_errors)} error(s) detected "
            f"in the first 10 seconds after page load. Errors:\n"
            + "\n".join(f"  {e}" for e in console_errors[:20])
            + (f"\n  ... and {len(console_errors) - 20} more"
               if len(console_errors) > 20 else "")
            + "\nThese JavaScript errors may cause broken UI, missing panels, "
            + "or failed WebSocket connections."
        )

    # -------------------------------------------------------------------
    # 8. WebSocket connection indicator exists
    # -------------------------------------------------------------------

    def test_websocket_connected(self):
        """After load, the WebSocket connection indicator should exist in
        the DOM. The connection-status element with class
        'connection-indicator' is in the header bar.

        We evaluate JS to check for the element and also verify it has
        a data-state attribute (connected or disconnected).
        """
        # Wait a moment for WS to attempt connection
        time.sleep(2)

        # Check for the connection status element
        # The unified.html has: <span id="connection-status" class="connection-indicator" ...>
        has_indicator = self.page.evaluate(
            "!!document.querySelector('#connection-status.connection-indicator')"
        )

        assert has_indicator, (
            "WEBSOCKET INDICATOR MISSING: No element matching "
            "'#connection-status.connection-indicator' found in the DOM. "
            "The header bar should contain a WebSocket connection indicator "
            "showing ONLINE/OFFLINE status. "
            "Check that unified.html includes the connection-status span "
            "and that cybercore/command CSS loaded."
        )

        # Additionally verify the data-state attribute exists
        data_state = self.page.evaluate(
            "document.querySelector('#connection-status')?.getAttribute('data-state')"
        )

        assert data_state is not None, (
            "WEBSOCKET INDICATOR HAS NO STATE: The #connection-status element "
            "exists but has no data-state attribute. Expected 'connected' or "
            "'disconnected'. The WebSocket state management may not be wiring "
            "up to the DOM indicator."
        )

        # Also check the status bar WS indicator
        ws_status_text = self.page.evaluate(
            "document.querySelector('#status-ws')?.textContent || ''"
        )

        assert ws_status_text.strip() != "", (
            "STATUS BAR WS INDICATOR EMPTY: The #status-ws element in the "
            "bottom status bar has no text content. Expected something like "
            "'WS: OK' or 'WS: --'. The status bar may not have initialized."
        )
