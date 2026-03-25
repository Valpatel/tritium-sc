# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Automated visual regression test suite.

Captures screenshots of key views and compares them against golden baselines
using SSIM (Structural Similarity Index). First run creates baselines;
subsequent runs detect regressions when SSIM drops below threshold.

Views tested:
  1. Main map (no demo) — default Command Center on load
  2. Demo mode with targets — /api/demo/start then wait for targets
  3. Battle mode HUD — begin battle and capture active combat
  4. Command palette open — Ctrl+K overlay
  5. Layout switching — Commander / Observer / Tactical / Battle presets
  6. City sim running — press J to toggle city simulation

Usage:
  pytest tests/visual/test_visual_regression.py -v
  pytest tests/visual/test_visual_regression.py -v --update-baselines

Requires: tritium_server fixture, Playwright, OpenCV.
"""

from __future__ import annotations

import time
from pathlib import Path

import cv2
import numpy as np
import pytest
import requests

pytestmark = pytest.mark.visual

BASELINE_DIR = Path(__file__).parent.parent / ".baselines"
GOLDEN_DIR = BASELINE_DIR / "golden"
CURRENT_DIR = BASELINE_DIR / "current"
DIFF_DIR = BASELINE_DIR / "diffs"

SSIM_THRESHOLD = 0.85  # Below this = visual regression detected

# Viewport for consistent captures
VIEWPORT_WIDTH = 1920
VIEWPORT_HEIGHT = 1080


# ---------------------------------------------------------------------------
# SSIM calculation (pure OpenCV, no skimage dependency)
# ---------------------------------------------------------------------------

def _ssim(img1: np.ndarray, img2: np.ndarray) -> float:
    """Compute Structural Similarity Index between two images.

    Uses the standard SSIM formula with Gaussian-weighted windows.
    Returns a value between -1 and 1, where 1 means identical.
    """
    # Convert to grayscale if colour
    if len(img1.shape) == 3:
        img1 = cv2.cvtColor(img1, cv2.COLOR_BGR2GRAY)
    if len(img2.shape) == 3:
        img2 = cv2.cvtColor(img2, cv2.COLOR_BGR2GRAY)

    # Resize to match if different dimensions
    if img1.shape != img2.shape:
        img2 = cv2.resize(img2, (img1.shape[1], img1.shape[0]))

    img1 = img1.astype(np.float64)
    img2 = img2.astype(np.float64)

    # SSIM constants (Wang et al., 2004)
    c1 = (0.01 * 255) ** 2
    c2 = (0.03 * 255) ** 2

    mu1 = cv2.GaussianBlur(img1, (11, 11), 1.5)
    mu2 = cv2.GaussianBlur(img2, (11, 11), 1.5)

    mu1_sq = mu1 ** 2
    mu2_sq = mu2 ** 2
    mu1_mu2 = mu1 * mu2

    sigma1_sq = cv2.GaussianBlur(img1 ** 2, (11, 11), 1.5) - mu1_sq
    sigma2_sq = cv2.GaussianBlur(img2 ** 2, (11, 11), 1.5) - mu2_sq
    sigma12 = cv2.GaussianBlur(img1 * img2, (11, 11), 1.5) - mu1_mu2

    ssim_map = ((2 * mu1_mu2 + c1) * (2 * sigma12 + c2)) / \
               ((mu1_sq + mu2_sq + c1) * (sigma1_sq + sigma2_sq + c2))

    return float(ssim_map.mean())


def _save_diff_image(name: str, baseline: np.ndarray, current: np.ndarray) -> Path:
    """Generate and save a visual diff image highlighting changed regions."""
    DIFF_DIR.mkdir(parents=True, exist_ok=True)

    g1 = cv2.cvtColor(baseline, cv2.COLOR_BGR2GRAY) if len(baseline.shape) == 3 else baseline
    g2 = cv2.cvtColor(current, cv2.COLOR_BGR2GRAY) if len(current.shape) == 3 else current

    if g1.shape != g2.shape:
        g2 = cv2.resize(g2, (g1.shape[1], g1.shape[0]))

    diff = cv2.absdiff(g1, g2)
    # Amplify differences for visibility
    _, thresh = cv2.threshold(diff, 25, 255, cv2.THRESH_BINARY)

    # Create a colour overlay: red where pixels differ
    if len(current.shape) == 3:
        overlay = current.copy()
        if overlay.shape[:2] != thresh.shape:
            overlay = cv2.resize(overlay, (thresh.shape[1], thresh.shape[0]))
    else:
        overlay = cv2.cvtColor(g2, cv2.COLOR_GRAY2BGR)

    overlay[thresh > 0] = (0, 0, 255)  # Red highlight on changed pixels

    path = DIFF_DIR / f"{name}_diff.png"
    cv2.imwrite(str(path), overlay)
    return path


# ---------------------------------------------------------------------------
# Screenshot helpers
# ---------------------------------------------------------------------------

def _capture(page, name: str) -> tuple[Path, np.ndarray]:
    """Capture a screenshot, return the file path and numpy array."""
    CURRENT_DIR.mkdir(parents=True, exist_ok=True)
    path = CURRENT_DIR / f"{name}.png"
    page.screenshot(path=str(path), timeout=60000, animations="disabled")
    img = cv2.imread(str(path))
    return path, img


def _load_baseline(name: str) -> np.ndarray | None:
    """Load a golden baseline image, or None if not present."""
    path = GOLDEN_DIR / f"{name}.png"
    if not path.exists():
        return None
    return cv2.imread(str(path))


def _save_baseline(name: str, img: np.ndarray) -> Path:
    """Save an image as a golden baseline."""
    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
    path = GOLDEN_DIR / f"{name}.png"
    cv2.imwrite(str(path), img)
    return path


def _is_not_black(img: np.ndarray, threshold: float = 10.0) -> bool:
    """Return True if the image is not predominantly black.

    A mean pixel value above `threshold` indicates visible content.
    """
    return float(img.mean()) > threshold


# ---------------------------------------------------------------------------
# Test class
# ---------------------------------------------------------------------------

class TestVisualRegression:
    """Automated visual regression suite comparing screenshots to baselines."""

    @pytest.fixture(autouse=True)
    def _setup(self, tritium_server, request):
        """Start browser, navigate to Command Center, wire update mode."""
        self.server_url = tritium_server.url
        self.update_mode = request.config.getoption("--update-baselines", default=False)

        # Reset game state to a known baseline
        try:
            requests.post(f"{self.server_url}/api/game/reset", timeout=5)
        except Exception:
            pass

        # Stop demo if running
        try:
            requests.post(f"{self.server_url}/api/demo/stop", timeout=5)
        except Exception:
            pass

        time.sleep(1)

        from playwright.sync_api import sync_playwright

        self.pw = sync_playwright().start()
        self.browser = self.pw.chromium.launch(headless=True)
        self.page = self.browser.new_page(
            viewport={"width": VIEWPORT_WIDTH, "height": VIEWPORT_HEIGHT},
        )
        self.page.goto(self.server_url)
        self.page.wait_for_load_state("networkidle")
        # Extra settling time for WebGL and map tiles
        time.sleep(3)

        yield

        # Cleanup: stop demo if we started it
        try:
            requests.post(f"{self.server_url}/api/demo/stop", timeout=3)
        except Exception:
            pass

        self.browser.close()
        self.pw.stop()

    def _compare_or_create(self, name: str, img: np.ndarray) -> None:
        """Compare screenshot against golden baseline.

        - If --update-baselines: save as new baseline (skip test).
        - If no baseline exists: create it (skip test, report new baseline).
        - If baseline exists: compute SSIM, fail if below threshold.
        """
        assert img is not None, f"Screenshot capture failed for '{name}'"
        assert _is_not_black(img), (
            f"Screenshot '{name}' is a black screen — UI did not render. "
            f"Check server startup and frontend loading."
        )

        if self.update_mode:
            path = _save_baseline(name, img)
            pytest.skip(f"Baseline updated: {path}")
            return

        baseline = _load_baseline(name)
        if baseline is None:
            path = _save_baseline(name, img)
            pytest.skip(f"New baseline created: {path}")
            return

        score = _ssim(baseline, img)

        if score < SSIM_THRESHOLD:
            diff_path = _save_diff_image(name, baseline, img)
            pytest.fail(
                f"Visual regression detected for '{name}': "
                f"SSIM={score:.4f} < {SSIM_THRESHOLD} threshold. "
                f"Diff image: {diff_path}. "
                f"Current screenshot: {CURRENT_DIR / f'{name}.png'}. "
                f"Run with --update-baselines to accept the new appearance."
            )

    # -------------------------------------------------------------------
    # View 1: Main map view (no demo)
    # -------------------------------------------------------------------

    def test_main_map_view(self):
        """Default Command Center map view has not regressed.

        This is the very first thing a user sees: satellite map, menu bar,
        status bar, no panels open by default (observer-like state).
        """
        # Close any panels that auto-opened
        self.page.keyboard.press("Escape")
        time.sleep(1)

        _, img = _capture(self.page, "main_map_view")
        self._compare_or_create("main_map_view", img)

    # -------------------------------------------------------------------
    # View 2: Demo mode with targets
    # -------------------------------------------------------------------

    def test_demo_mode_with_targets(self):
        """Demo mode populates targets on the map without regression."""
        # Start demo mode via API
        try:
            resp = requests.post(
                f"{self.server_url}/api/demo/start", timeout=10,
            )
            resp.raise_for_status()
        except Exception as exc:
            pytest.skip(f"Demo mode not available: {exc}")
            return

        # Wait for targets to appear on map
        time.sleep(5)

        # Reload page to pick up demo state visually
        self.page.reload()
        self.page.wait_for_load_state("networkidle")
        time.sleep(4)

        _, img = _capture(self.page, "demo_mode_targets")
        self._compare_or_create("demo_mode_targets", img)

        # Cleanup
        try:
            requests.post(f"{self.server_url}/api/demo/stop", timeout=5)
        except Exception:
            pass

    # -------------------------------------------------------------------
    # View 3: Battle mode HUD
    # -------------------------------------------------------------------

    def test_battle_mode_hud(self):
        """Battle mode HUD (wave counter, health bars, units) has not regressed."""
        # Switch to battle layout first
        self.page.keyboard.press("Control+4")
        time.sleep(1)

        # Place some turrets for a meaningful battle view
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
            pytest.skip("Could not start battle")
            return

        # Wait for active combat with hostiles spawned
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

        _, img = _capture(self.page, "battle_mode_hud")
        self._compare_or_create("battle_mode_hud", img)

    # -------------------------------------------------------------------
    # View 4: Command palette open
    # -------------------------------------------------------------------

    def test_command_palette_open(self):
        """Command palette (Ctrl+K) overlay has not regressed."""
        # Open command palette
        self.page.keyboard.press("Control+k")
        time.sleep(1.5)

        # Verify the palette element exists before capture
        palette = self.page.query_selector("#command-palette")
        if palette is None:
            # Try the forward slash shortcut as fallback
            self.page.keyboard.press("Escape")
            time.sleep(0.5)
            self.page.keyboard.press("/")
            time.sleep(1.5)
            palette = self.page.query_selector("#command-palette")

        _, img = _capture(self.page, "command_palette_open")
        self._compare_or_create("command_palette_open", img)

        # Close palette
        self.page.keyboard.press("Escape")

    # -------------------------------------------------------------------
    # View 5: Layout switching (all 4 presets)
    # -------------------------------------------------------------------

    def test_layout_commander(self):
        """Commander layout preset (Ctrl+1) has not regressed."""
        self.page.keyboard.press("Control+1")
        time.sleep(2)

        _, img = _capture(self.page, "layout_commander")
        self._compare_or_create("layout_commander", img)

    def test_layout_observer(self):
        """Observer layout preset (Ctrl+2) has not regressed."""
        self.page.keyboard.press("Control+2")
        time.sleep(2)

        _, img = _capture(self.page, "layout_observer")
        self._compare_or_create("layout_observer", img)

    def test_layout_tactical(self):
        """Tactical layout preset (Ctrl+3) has not regressed."""
        self.page.keyboard.press("Control+3")
        time.sleep(2)

        _, img = _capture(self.page, "layout_tactical")
        self._compare_or_create("layout_tactical", img)

    def test_layout_battle(self):
        """Battle layout preset (Ctrl+4) has not regressed."""
        self.page.keyboard.press("Control+4")
        time.sleep(2)

        _, img = _capture(self.page, "layout_battle")
        self._compare_or_create("layout_battle", img)

    # -------------------------------------------------------------------
    # View 6: City sim running
    # -------------------------------------------------------------------

    def test_city_sim_running(self):
        """City simulation (J key) with traffic has not regressed."""
        # Toggle city sim on
        self.page.keyboard.press("j")
        time.sleep(5)  # Allow vehicles and pedestrians to spawn and move

        _, img = _capture(self.page, "city_sim_running")
        self._compare_or_create("city_sim_running", img)

        # Toggle city sim off
        self.page.keyboard.press("j")
