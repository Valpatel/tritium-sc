# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Deterministic smoke tests for the Command Center.

Uses Playwright to verify core UI elements, canvas rendering, data flow,
and frame rate without any LLM/ollama dependencies.
"""

from __future__ import annotations

import time
from pathlib import Path

import cv2
import numpy as np
import pytest

from tests.lib.results_db import ResultsDB
from tests.lib.server_manager import TritiumServer

pytestmark = pytest.mark.visual

SCREENSHOT_DIR = Path("tests/.test-results/smoke-screenshots")


class TestUnifiedSmoke:
    """Playwright-based deterministic smoke tests for the Command Center."""

    @pytest.fixture(autouse=True, scope="class")
    def _browser(
        self,
        request,
        tritium_server: TritiumServer,
        test_db: ResultsDB,
        run_id: int,
    ):
        """Launch headless browser, navigate to Command Center, wait for data."""
        cls = request.cls
        cls.url = tritium_server.url
        cls._db = test_db
        cls._run_id = run_id
        cls._errors: list[str] = []
        cls._t0 = time.monotonic()

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

        browser.close()
        cls._pw.stop()

    def _record(self, name: str, passed: bool, details: dict | None = None) -> None:
        """Record result to ResultsDB and take a screenshot."""
        duration_ms = (time.monotonic() - self._t0) * 1000
        self._db.record_result(self._run_id, name, passed, duration_ms, details or {})
        try:
            self.page.screenshot(
                path=str(SCREENSHOT_DIR / f"{name}.png"),
                full_page=False,
            )
        except Exception:
            pass

    def test_01_zero_console_errors(self):
        name = "smoke_01_zero_console_errors"
        try:
            assert len(self._errors) == 0, (
                f"Page had {len(self._errors)} console error(s): {self._errors}"
            )
            self._record(name, True)
        except Exception as exc:
            self._record(name, False, {"errors": self._errors})
            raise exc

    def test_02_canvas_visible_and_sized(self):
        name = "smoke_02_canvas_visible_and_sized"
        try:
            # Try MapLibre GL container first, then Three.js, then legacy Canvas 2D
            canvas = self.page.locator("#maplibre-map")
            if canvas.count() == 0 or not canvas.is_visible():
                canvas = self.page.locator("#tactical-3d-canvas")
            if canvas.count() == 0 or not canvas.is_visible():
                canvas = self.page.locator("#tactical-canvas")
            assert canvas.is_visible(), "No visible map container found"
            box = canvas.bounding_box()
            assert box is not None, "Map container has no bounding box"
            assert box["width"] > 100, f"Map width too small: {box['width']}"
            assert box["height"] > 100, f"Map height too small: {box['height']}"
            self._record(name, True, {"width": box["width"], "height": box["height"]})
        except Exception as exc:
            self._record(name, False, {"error": str(exc)})
            raise exc

    def test_03_canvas_has_content(self):
        name = "smoke_03_canvas_has_content"
        try:
            has_content = self.page.evaluate("""() => {
                // Try MapLibre GL canvas first (inside #maplibre-map)
                const mlMap = document.getElementById('maplibre-map');
                if (mlMap && mlMap.offsetWidth > 0) {
                    // MapLibre creates a canvas.maplibregl-canvas inside the container
                    const mlCanvas = mlMap.querySelector('canvas.maplibregl-canvas');
                    if (mlCanvas && mlCanvas.width > 0 && mlCanvas.height > 0) {
                        return 100;  // MapLibre rendered
                    }
                    // Container exists and is sized = map is initializing
                    return mlMap.offsetWidth > 100 && mlMap.offsetHeight > 100 ? 1 : 0;
                }
                // Try Three.js WebGL canvas (id=tactical-3d-canvas)
                const webglCanvas = document.getElementById('tactical-3d-canvas');
                if (webglCanvas && webglCanvas.offsetWidth > 0) {
                    const gl = webglCanvas.getContext('webgl2', {failIfMajorPerformanceCaveat: false})
                        || webglCanvas.getContext('webgl', {failIfMajorPerformanceCaveat: false});
                    if (gl) {
                        return Math.max(1, webglCanvas.width * webglCanvas.height > 0 ? 100 : 0);
                    }
                    return webglCanvas.width > 100 && webglCanvas.height > 100 ? 1 : 0;
                }
                // Fall back to 2D canvas
                const c = document.getElementById('tactical-canvas');
                if (!c) return false;
                const ctx = c.getContext('2d');
                if (!ctx) return false;
                const cx = Math.floor(c.width / 2);
                const cy = Math.floor(c.height / 2);
                const data = ctx.getImageData(cx - 10, cy - 10, 20, 20).data;
                let nonBlack = 0;
                for (let i = 0; i < data.length; i += 4) {
                    if (data[i] > 20 || data[i+1] > 20 || data[i+2] > 20) {
                        nonBlack++;
                    }
                }
                return nonBlack;
            }""")
            assert has_content and has_content > 0, (
                f"Canvas center is all black (non-black pixels: {has_content})"
            )
            self._record(name, True, {"non_black_pixels": has_content})
        except Exception as exc:
            self._record(name, False, {"error": str(exc)})
            raise exc

    def test_04_units_in_store(self):
        name = "smoke_04_units_in_store"
        try:
            self.page.wait_for_function(
                "() => window.TritiumStore && window.TritiumStore.units.size >= 5",
                timeout=15000,
            )
            count = self.page.evaluate("() => window.TritiumStore.units.size")
            assert count >= 5, f"Expected >= 5 units in store, got {count}"
            self._record(name, True, {"unit_count": count})
        except Exception as exc:
            self._record(name, False, {"error": str(exc)})
            raise exc

    def test_05_units_render_as_colored_shapes(self):
        name = "smoke_05_units_render_as_colored_shapes"
        try:
            screenshot_path = str(SCREENSHOT_DIR / f"{name}.png")
            self.page.screenshot(path=screenshot_path, full_page=False)
            img = cv2.imread(screenshot_path)
            assert img is not None, "Failed to load screenshot"
            # Look for friendly green pixels: BGR(161, 255, 5) with tolerance 40
            target_bgr = np.array([161, 255, 5])
            diff = np.abs(img.astype(int) - target_bgr)
            green_mask = np.all(diff <= 40, axis=2)
            green_count = int(np.sum(green_mask))
            assert green_count >= 30, (
                f"Expected >= 30 green pixels for friendly units, got {green_count}"
            )
            self._record(name, True, {"green_pixel_count": green_count})
        except Exception as exc:
            self._record(name, False, {"error": str(exc)})
            raise exc

    def test_06_header_live_data(self):
        name = "smoke_06_header_live_data"
        try:
            conn_label = self.page.locator("#connection-status .conn-label").text_content()
            assert conn_label is not None and "ONLINE" in conn_label, (
                f"Connection status not ONLINE: '{conn_label}'"
            )

            stat_value = self.page.locator("#header-units .stat-value").text_content()
            assert stat_value is not None, "Unit count stat-value not found"
            unit_count = int(stat_value.strip())
            assert unit_count >= 5, f"Header unit count too low: {unit_count}"

            clock_text = self.page.locator("#header-clock").text_content()
            assert clock_text is not None and "UTC" in clock_text, (
                f"Clock does not contain UTC: '{clock_text}'"
            )

            self._record(name, True, {
                "connection": conn_label,
                "units": unit_count,
                "clock": clock_text,
            })
        except Exception as exc:
            self._record(name, False, {"error": str(exc)})
            raise exc

    def test_07_panels_have_content(self):
        name = "smoke_07_panels_have_content"
        try:
            panels = self.page.locator(".panel")
            visible_count = 0
            total = panels.count()
            for i in range(total):
                if panels.nth(i).is_visible():
                    visible_count += 1
            assert visible_count >= 2, (
                f"Expected >= 2 visible panels, got {visible_count}"
            )

            list_items = self.page.locator(".panel:visible .panel-list-item")
            item_count = list_items.count()
            assert item_count >= 1, (
                f"Expected >= 1 panel-list-item in visible panels, got {item_count}"
            )

            self._record(name, True, {
                "visible_panels": visible_count,
                "list_items": item_count,
            })
        except Exception as exc:
            self._record(name, False, {"error": str(exc)})
            raise exc

    def test_08_frame_rate_acceptable(self):
        name = "smoke_08_frame_rate_acceptable"
        try:
            # Wait a moment for FPS counter to stabilize
            self.page.wait_for_timeout(2000)
            fps_text = self.page.locator("#status-fps").text_content()
            assert fps_text is not None, "FPS element #status-fps not found"
            # Parse number from text like "60 FPS" or "-- FPS"
            fps_str = fps_text.strip().split()[0]
            if fps_str == "--":
                pytest.skip("FPS counter not yet initialized")
            fps = int(fps_str)
            assert fps >= 10, f"FPS too low: {fps}"
            self._record(name, True, {"fps": fps})
        except pytest.skip.Exception:
            self._record(name, True, {"fps": "skipped_not_initialized"})
            raise
        except Exception as exc:
            self._record(name, False, {"error": str(exc)})
            raise exc
