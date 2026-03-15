# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Visual smoke test: verify Command Center renders correctly.

Wave 110 — Uses Playwright to screenshot the Command Center and verify:
- Dark theme renders (background is dark, not white)
- Map canvas or container is present and visible
- Menu bar is present and visible
- No JS console errors on load

Marked @pytest.mark.visual so it only runs with ./test.sh 10 or --visual.
"""
from __future__ import annotations

import time
from pathlib import Path

import numpy as np
import pytest

from tests.lib.results_db import ResultsDB
from tests.lib.server_manager import TritiumServer

pytestmark = pytest.mark.visual

SCREENSHOT_DIR = Path("tests/.test-results/render-screenshots")


class TestCommandCenterRender:
    """Playwright-based render verification for the Command Center."""

    @pytest.fixture(autouse=True, scope="class")
    def _browser(
        self,
        request,
        tritium_server: TritiumServer,
        test_db: ResultsDB,
        run_id: int,
    ):
        """Launch headless browser and navigate to Command Center."""
        cls = request.cls
        cls.url = tritium_server.url
        cls._db = test_db
        cls._run_id = run_id
        cls._errors: list[str] = []

        SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)

        from playwright.sync_api import sync_playwright

        cls._pw = sync_playwright().start()
        browser = cls._pw.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width": 1920, "height": 1080})
        cls.page = ctx.new_page()
        cls.page.on("pageerror", lambda e: cls._errors.append(str(e)))
        cls.page.goto(f"{cls.url}/", wait_until="networkidle")
        cls.page.wait_for_timeout(3000)

        yield

        cls.page.close()
        ctx.close()
        browser.close()
        cls._pw.stop()

    def test_dark_theme_renders(self):
        """Verify the page renders with a dark background (not white/blank)."""
        screenshot_path = SCREENSHOT_DIR / "dark_theme.png"
        self.page.screenshot(path=str(screenshot_path))

        # Load screenshot and check that the average color is dark
        import cv2
        img = cv2.imread(str(screenshot_path))
        assert img is not None, "Screenshot failed to save"

        # Average pixel brightness — dark theme should be well below 100
        avg_brightness = np.mean(img)
        assert avg_brightness < 100, (
            f"Page appears too bright (avg={avg_brightness:.1f}). "
            f"Expected dark theme with avg < 100."
        )

    def test_map_container_present(self):
        """Verify a map container or canvas element is present and visible."""
        # Check for canvas (Three.js or 2D canvas map) or map container div
        canvas = self.page.query_selector("canvas")
        map_div = self.page.query_selector("#map, .map-container, #war-room, .war-room")

        has_map = canvas is not None or map_div is not None
        assert has_map, (
            "No map element found. Expected a <canvas> or map container div."
        )

        # If canvas exists, verify it has non-zero dimensions
        if canvas is not None:
            box = canvas.bounding_box()
            assert box is not None, "Canvas has no bounding box"
            assert box["width"] > 100, f"Canvas too narrow: {box['width']}px"
            assert box["height"] > 100, f"Canvas too short: {box['height']}px"

    def test_menu_bar_visible(self):
        """Verify the menu bar / navigation is present."""
        # Look for common menu selectors
        selectors = [
            "nav", ".menu-bar", ".menubar", "#menu-bar",
            ".toolbar", ".top-bar", ".header-bar",
            "[class*='menu']", "[class*='nav']",
        ]
        found = False
        for sel in selectors:
            el = self.page.query_selector(sel)
            if el is not None:
                box = el.bounding_box()
                if box and box["width"] > 200:
                    found = True
                    break

        assert found, "No visible menu bar / navigation element found."

    def test_no_js_errors_on_load(self):
        """Verify no JavaScript errors occurred during page load."""
        # Filter out known benign errors (e.g. WebSocket connection refused)
        critical_errors = [
            e for e in self._errors
            if "WebSocket" not in e and "ERR_CONNECTION_REFUSED" not in e
        ]
        assert len(critical_errors) == 0, (
            f"JavaScript errors on load: {critical_errors}"
        )

    def test_screenshot_not_blank(self):
        """Verify the screenshot has actual content (not all one color)."""
        screenshot_path = SCREENSHOT_DIR / "content_check.png"
        self.page.screenshot(path=str(screenshot_path))

        import cv2
        img = cv2.imread(str(screenshot_path))
        assert img is not None

        # Check color variance — a real UI has diverse pixel values
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        std_dev = np.std(gray)
        assert std_dev > 5.0, (
            f"Screenshot appears blank/uniform (std_dev={std_dev:.1f}). "
            f"Expected varied content."
        )
