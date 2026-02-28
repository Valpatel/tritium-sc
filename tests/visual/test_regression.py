# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Screenshot baseline comparison — detects visual regressions between commits.

Compares current screenshots against golden baselines using SSIM (structural
similarity). First run captures baselines; subsequent runs compare.

Usage:
  pytest tests/visual/test_regression.py -v              # Compare against baselines
  pytest tests/visual/test_regression.py --update-baselines  # Capture new baselines

Requires: tritium_server fixture, OpenCV.
"""

from __future__ import annotations

import time
from pathlib import Path

import cv2
import numpy as np
import pytest
import requests

BASELINE_DIR = Path("tests/.baselines")
SSIM_THRESHOLD = 0.85  # Below this = regression detected


def _ssim(img1: np.ndarray, img2: np.ndarray) -> float:
    """Compute Structural Similarity Index between two images.

    Simplified SSIM using luminance and contrast components.
    Returns a value between -1 and 1, where 1 means identical.
    """
    # Convert to grayscale if needed
    if len(img1.shape) == 3:
        img1 = cv2.cvtColor(img1, cv2.COLOR_BGR2GRAY)
    if len(img2.shape) == 3:
        img2 = cv2.cvtColor(img2, cv2.COLOR_BGR2GRAY)

    # Resize to match if different sizes
    if img1.shape != img2.shape:
        img2 = cv2.resize(img2, (img1.shape[1], img1.shape[0]))

    img1 = img1.astype(np.float64)
    img2 = img2.astype(np.float64)

    # Constants
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


def _capture_view(page, name: str) -> tuple[Path, np.ndarray]:
    """Capture a screenshot and return path + numpy array."""
    d = BASELINE_DIR / "current"
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{name}.png"
    page.screenshot(path=str(path))
    img = cv2.imread(str(path))
    return path, img


def _get_baseline(name: str) -> np.ndarray | None:
    """Load a baseline image, or None if it doesn't exist."""
    path = BASELINE_DIR / "golden" / f"{name}.png"
    if not path.exists():
        return None
    return cv2.imread(str(path))


def _save_baseline(name: str, img: np.ndarray) -> Path:
    """Save an image as a golden baseline."""
    d = BASELINE_DIR / "golden"
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{name}.png"
    cv2.imwrite(str(path), img)
    return path


class TestScreenshotRegression:
    """Compare current screenshots against golden baselines."""

    @pytest.fixture(autouse=True)
    def _setup(self, tritium_server, request):
        """Set up browser and check mode."""
        self.server_url = tritium_server.url
        self.update_mode = request.config.getoption("--update-baselines", default=False)

        # Reset game
        try:
            requests.post(f"{self.server_url}/api/game/reset", timeout=5)
        except Exception:
            pass
        time.sleep(1)

        from playwright.sync_api import sync_playwright
        self.pw = sync_playwright().start()
        self.browser = self.pw.chromium.launch(headless=True)
        self.page = self.browser.new_page(viewport={"width": 1920, "height": 1080})
        self.page.goto(self.server_url)
        self.page.wait_for_load_state("networkidle")

        yield

        self.browser.close()
        self.pw.stop()

    def _compare_or_update(self, name: str, img: np.ndarray) -> None:
        """Compare with baseline or update it."""
        if self.update_mode:
            path = _save_baseline(name, img)
            pytest.skip(f"Baseline updated: {path}")
            return

        baseline = _get_baseline(name)
        if baseline is None:
            _save_baseline(name, img)
            pytest.skip(f"No baseline found, captured initial: {name}")
            return

        score = _ssim(baseline, img)
        assert score >= SSIM_THRESHOLD, (
            f"Visual regression detected for '{name}': "
            f"SSIM={score:.4f} < {SSIM_THRESHOLD} threshold. "
            f"Run with --update-baselines to accept the new appearance."
        )

    def test_war_room_setup_baseline(self):
        """War Room setup view hasn't regressed."""
        self.page.keyboard.press("w")
        time.sleep(3)

        # Place some turrets for a populated view
        for x, y in [(0, 0), (8, 0), (-8, 0)]:
            try:
                requests.post(
                    f"{self.server_url}/api/game/place",
                    json={"name": "Turret", "asset_type": "turret", "position": {"x": x, "y": y}},
                    timeout=5,
                )
            except Exception:
                pass
        time.sleep(2)

        _, img = _capture_view(self.page, "war_room_setup")
        self._compare_or_update("war_room_setup", img)

    def test_countdown_baseline(self):
        """Countdown overlay hasn't regressed."""
        self.page.keyboard.press("w")
        time.sleep(2)

        # Place turrets and start game
        for x, y in [(0, 0), (5, 0)]:
            requests.post(
                f"{self.server_url}/api/game/place",
                json={"name": "Turret", "asset_type": "turret", "position": {"x": x, "y": y}},
                timeout=5,
            )
        requests.post(f"{self.server_url}/api/game/begin", timeout=5)
        time.sleep(1.5)

        _, img = _capture_view(self.page, "countdown")
        self._compare_or_update("countdown", img)

    def test_active_combat_baseline(self):
        """Active combat view hasn't regressed."""
        self.page.keyboard.press("w")
        time.sleep(2)

        for x, y in [(0, 0), (8, 0), (-8, 0), (0, 8), (0, -8)]:
            requests.post(
                f"{self.server_url}/api/game/place",
                json={"name": "Turret", "asset_type": "turret", "position": {"x": x, "y": y}},
                timeout=5,
            )
        requests.post(f"{self.server_url}/api/game/begin", timeout=5)

        # Wait for active combat
        for _ in range(15):
            time.sleep(1)
            try:
                resp = requests.get(f"{self.server_url}/api/game/state", timeout=5)
                state = resp.json()
                if state.get("state") == "active" and state.get("total_eliminations", state.get("total_kills", 0)) > 0:
                    break
            except Exception:
                pass
        time.sleep(2)

        _, img = _capture_view(self.page, "active_combat")
        self._compare_or_update("active_combat", img)

    def test_amy_dashboard_baseline(self):
        """Amy dashboard view hasn't regressed."""
        self.page.keyboard.press("y")
        time.sleep(3)

        _, img = _capture_view(self.page, "amy_dashboard")
        self._compare_or_update("amy_dashboard", img)

    def test_grid_view_baseline(self):
        """Grid view hasn't regressed."""
        self.page.keyboard.press("g")
        time.sleep(3)

        _, img = _capture_view(self.page, "grid_view")
        self._compare_or_update("grid_view", img)
