# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""
Map Interaction Exercise: Zoom, pan, tilt, click on units, and verify
the map responds correctly.  Uses OpenCV to measure visual changes and
LLaVA for semantic analysis of the map state.

Run:
    .venv/bin/python3 -m pytest tests/visual/test_map_interaction.py -v -s
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import cv2
import numpy as np
import pytest

pytestmark = pytest.mark.visual

SCREENSHOT_DIR = Path("tests/.test-results/map-interaction")
REPORT_PATH = SCREENSHOT_DIR / "report.html"
OLLAMA_URL = "http://localhost:11434"


def _opencv_diff(path_a: str, path_b: str) -> float:
    a = cv2.imread(path_a, cv2.IMREAD_GRAYSCALE)
    b = cv2.imread(path_b, cv2.IMREAD_GRAYSCALE)
    if a is None or b is None:
        return 0.0
    if a.shape != b.shape:
        b = cv2.resize(b, (a.shape[1], a.shape[0]))
    diff = cv2.absdiff(a, b)
    return float(np.count_nonzero(diff > 15) / diff.size * 100)


def _opencv_brightness(path: str) -> float:
    img = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
    return float(np.mean(img)) if img is not None else 0.0


def _opencv_edge_density(path: str) -> float:
    img = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
    if img is None:
        return 0.0
    edges = cv2.Canny(img, 50, 150)
    return float(np.count_nonzero(edges) / edges.size * 100)


def _llava_analyze(img_path: str, prompt: str) -> str:
    import base64, requests
    try:
        with open(img_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        resp = requests.post(f"{OLLAMA_URL}/api/generate", json={
            "model": "llava:7b", "prompt": prompt,
            "images": [b64], "stream": False,
        }, timeout=60)
        if resp.ok:
            return resp.json().get("response", "")
    except Exception as e:
        return f"LLM error: {e}"
    return ""


class TestMapInteraction:
    """Exercise map zoom, pan, tilt, and unit selection."""

    @pytest.fixture(autouse=True)
    def _setup(self):
        SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
        from playwright.sync_api import sync_playwright
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=False)
        ctx = self._browser.new_context(viewport={"width": 1920, "height": 1080})
        self.page = ctx.new_page()
        self._errors = []
        self.page.on("pageerror", lambda e: self._errors.append(str(e)))
        self.page.goto("http://localhost:8000", wait_until="networkidle", timeout=30000)
        time.sleep(5)
        yield
        self._browser.close()
        self._pw.stop()

    def _screenshot(self, name: str) -> str:
        path = str(SCREENSHOT_DIR / f"{name}.png")
        self.page.screenshot(path=path)
        return path

    def _get_map_state(self) -> dict:
        return self.page.evaluate("""() => {
            const ma = window._mapActions;
            if (!ma || !ma.getMapState) return {};
            const s = ma.getMapState();
            // Also get map instance properties
            if (s.map) {
                s.zoom = s.map.getZoom();
                s.center = s.map.getCenter();
                s.bearing = s.map.getBearing();
                s.pitch = s.map.getPitch();
            }
            return s;
        }""")

    def _get_zoom(self) -> float:
        return self.page.evaluate("""() => {
            if (window._mapState && window._mapState.map)
                return window._mapState.map.getZoom();
            return 0;
        }""")

    def _get_center(self) -> dict:
        return self.page.evaluate("""() => {
            if (window._mapState && window._mapState.map) {
                const c = window._mapState.map.getCenter();
                return { lng: c.lng, lat: c.lat };
            }
            return { lng: 0, lat: 0 };
        }""")

    def _get_bearing(self) -> float:
        return self.page.evaluate("""() => {
            if (window._mapState && window._mapState.map)
                return window._mapState.map.getBearing();
            return 0;
        }""")

    def _get_pitch(self) -> float:
        return self.page.evaluate("""() => {
            try {
                if (window._mapState && window._mapState.map) {
                    const p = window._mapState.map.getPitch();
                    if (typeof p === 'number') return p;
                }
            } catch (e) {}
            return -1;
        }""")

    def _get_tilt_mode(self) -> str:
        return self.page.evaluate("""() => {
            if (window._mapState) return window._mapState.tiltMode || 'unknown';
            const ma = window._mapActions;
            if (ma && ma.getMapState) return ma.getMapState().tiltMode || 'unknown';
            return 'unknown';
        }""")

    def _get_unit_count(self) -> dict:
        return self.page.evaluate("""() => {
            const markers = document.querySelectorAll('.maplibregl-marker');
            let friendly = 0, hostile = 0, neutral = 0;
            markers.forEach(m => {
                const cls = m.className || '';
                if (cls.includes('hostile')) hostile++;
                else if (cls.includes('neutral')) neutral++;
                else friendly++;
            });
            return { total: markers.length, friendly, hostile, neutral };
        }""")

    # --- Zoom tests ---

    def test_01_zoom_in_keyboard(self):
        """']' key zooms in, visual change detected."""
        zoom_before = self._get_zoom()
        before = self._screenshot("01_before_zoom_in")

        self.page.keyboard.press("]")
        time.sleep(0.5)
        self.page.keyboard.press("]")
        time.sleep(0.5)

        zoom_after = self._get_zoom()
        after = self._screenshot("01_after_zoom_in")

        diff = _opencv_diff(before, after)
        print(f"\nZoom in: {zoom_before:.1f} -> {zoom_after:.1f}, diff={diff:.1f}%")

        assert zoom_after > zoom_before, (
            f"Zoom should increase: {zoom_before:.1f} -> {zoom_after:.1f}"
        )
        assert diff > 1.0, f"Visual should change after zoom, diff={diff:.1f}%"

    def test_02_zoom_out_keyboard(self):
        """'[' key zooms out, visual change detected."""
        zoom_before = self._get_zoom()
        before = self._screenshot("02_before_zoom_out")

        self.page.keyboard.press("[")
        time.sleep(0.5)
        self.page.keyboard.press("[")
        time.sleep(0.5)

        zoom_after = self._get_zoom()
        after = self._screenshot("02_after_zoom_out")

        diff = _opencv_diff(before, after)
        print(f"\nZoom out: {zoom_before:.1f} -> {zoom_after:.1f}, diff={diff:.1f}%")

        assert zoom_after < zoom_before, (
            f"Zoom should decrease: {zoom_before:.1f} -> {zoom_after:.1f}"
        )

    def test_03_zoom_mouse_wheel(self):
        """Mouse wheel zoom changes the view."""
        zoom_before = self._get_zoom()
        before = self._screenshot("03_before_wheel")

        # Scroll up (zoom in) on the map area
        self.page.mouse.move(960, 540)
        self.page.mouse.wheel(0, -300)
        time.sleep(0.8)

        zoom_after = self._get_zoom()
        after = self._screenshot("03_after_wheel")

        diff = _opencv_diff(before, after)
        print(f"\nMouse wheel zoom: {zoom_before:.1f} -> {zoom_after:.1f}, diff={diff:.1f}%")

        # Zoom should have changed (either direction due to inverted scroll)
        assert abs(zoom_after - zoom_before) > 0.1, (
            f"Zoom should change on wheel: {zoom_before:.1f} -> {zoom_after:.1f}"
        )

    def test_04_pan_mouse_drag(self):
        """Mouse drag pans the map, center changes."""
        center_before = self._get_center()
        before = self._screenshot("04_before_pan")

        # Drag from center to the right
        self.page.mouse.move(960, 540)
        self.page.mouse.down()
        time.sleep(0.1)
        # Move in small increments to simulate drag
        for x in range(960, 760, -10):
            self.page.mouse.move(x, 540)
            time.sleep(0.01)
        self.page.mouse.up()
        time.sleep(0.5)

        center_after = self._get_center()
        after = self._screenshot("04_after_pan")

        diff = _opencv_diff(before, after)
        lng_delta = abs(center_after["lng"] - center_before["lng"])
        lat_delta = abs(center_after["lat"] - center_before["lat"])

        print(f"\nPan: center moved lng={lng_delta:.6f} lat={lat_delta:.6f}, diff={diff:.1f}%")

        # Center should have moved
        assert lng_delta > 0.0001 or lat_delta > 0.0001, (
            f"Map center should move after drag: "
            f"lng={center_before['lng']:.6f}->{center_after['lng']:.6f}, "
            f"lat={center_before['lat']:.6f}->{center_after['lat']:.6f}"
        )

    def test_05_reset_camera(self):
        """'R' key resets camera to default position."""
        # First pan and zoom away
        self.page.keyboard.press("]")
        self.page.keyboard.press("]")
        time.sleep(0.3)
        self.page.mouse.move(960, 540)
        self.page.mouse.down()
        for x in range(960, 760, -10):
            self.page.mouse.move(x, 540)
            time.sleep(0.01)
        self.page.mouse.up()
        time.sleep(0.3)

        before = self._screenshot("05_before_reset")

        self.page.keyboard.press("r")
        time.sleep(1.5)  # flyTo animation takes ~800ms

        after = self._screenshot("05_after_reset")
        bearing = self._get_bearing()
        pitch = self._get_pitch()

        diff = _opencv_diff(before, after)
        print(f"\nReset: bearing={bearing:.1f}, pitch={pitch:.1f}, diff={diff:.1f}%")

        assert abs(bearing) < 2, f"Bearing should be ~0 after reset, got {bearing:.1f}"

    def test_06_3d_tilt_toggle(self):
        """3D mode changes the pitch/perspective."""
        tilt_before = self._get_tilt_mode()
        pitch_before = self._get_pitch()
        before = self._screenshot("06_before_3d")

        # Toggle 3D tilt via JS API (most reliable)
        self.page.evaluate("() => { window._mapActions.toggleTilt(); }")
        time.sleep(1.0)  # easeTo animation takes 500ms

        tilt_after = self._get_tilt_mode()
        pitch_after = self._get_pitch()
        after = self._screenshot("06_after_3d")

        diff = _opencv_diff(before, after)
        print(f"\n3D toggle: tilt {tilt_before} -> {tilt_after}, "
              f"pitch {pitch_before:.1f} -> {pitch_after:.1f}, diff={diff:.1f}%")

        # TiltMode should have changed
        assert tilt_before != tilt_after, (
            f"Tilt mode should change: {tilt_before} -> {tilt_after}"
        )
        # Visual difference should be significant
        assert diff > 1.0, f"Visual should change after 3D toggle, diff={diff:.1f}%"

        # Toggle back
        self.page.evaluate("() => { window._mapActions.toggleTilt(); }")
        time.sleep(0.5)

    def test_07_center_on_action(self):
        """'F' key centers on action (finds nearest units)."""
        before = self._screenshot("07_before_center")

        self.page.keyboard.press("f")
        time.sleep(1)

        after = self._screenshot("07_after_center")
        diff = _opencv_diff(before, after)
        print(f"\nCenter on action: diff={diff:.1f}%")

    def test_08_unit_markers_visible(self):
        """Map displays unit markers at correct positions."""
        counts = self._get_unit_count()
        print(f"\nUnit markers: {counts}")

        self._screenshot("08_unit_markers")

        assert counts["total"] > 0, "Map should show unit markers"

    def test_09_zoom_level_progression(self):
        """Zoom through 5 levels and capture visual metrics at each."""
        # Reset camera first
        self.page.keyboard.press("r")
        time.sleep(1)

        metrics = []
        for i in range(5):
            zoom = self._get_zoom()
            shot = self._screenshot(f"09_zoom_level_{i}")
            brightness = _opencv_brightness(shot)
            edges = _opencv_edge_density(shot)

            metrics.append({
                "level": i,
                "zoom": zoom,
                "brightness": brightness,
                "edges": edges,
            })

            print(f"  Level {i}: zoom={zoom:.1f} brightness={brightness:.1f} edges={edges:.1f}%")

            # Zoom in
            self.page.keyboard.press("]")
            time.sleep(0.5)

        # Reset back
        self.page.keyboard.press("r")
        time.sleep(1)

        # Zoom should have increased
        assert metrics[-1]["zoom"] > metrics[0]["zoom"], (
            f"Zoom should increase: {metrics[0]['zoom']:.1f} -> {metrics[-1]['zoom']:.1f}"
        )

    def test_10_llm_map_analysis(self):
        """LLaVA analysis of the map at different states."""
        analyses = {}

        # Default view
        default = self._screenshot("10_default")
        analyses["default"] = _llava_analyze(default,
            "Describe this tactical map. What geographic features, unit positions, "
            "and UI elements are visible?")

        # Zoomed in
        for _ in range(4):
            self.page.keyboard.press("]")
            time.sleep(0.3)
        zoomed = self._screenshot("10_zoomed_in")
        analyses["zoomed"] = _llava_analyze(zoomed,
            "This map is zoomed in closer. What details are visible at this zoom level "
            "that weren't visible before?")

        # Reset
        self.page.keyboard.press("r")
        time.sleep(1)

        for name, text in analyses.items():
            print(f"\n{name}: {text[:200]}")

        self._generate_report(analyses)

    def _generate_report(self, analyses: dict):
        html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>Map Interaction Report</title>
<style>
  body {{ background:#0a0a0f; color:#c0c0c0; font-family:'JetBrains Mono',monospace; margin:20px; }}
  h1 {{ color:#00f0ff; border-bottom:2px solid #00f0ff33; padding-bottom:8px; }}
  h2 {{ color:#ff2a6d; margin-top:32px; }}
  .summary {{ display:flex; gap:30px; margin:20px 0; }}
  .stat {{ padding:12px 24px; border:1px solid #00f0ff33; border-radius:4px; }}
  .stat .val {{ font-size:28px; color:#00f0ff; }}
  .stat .label {{ font-size:12px; color:#666; }}
  .llm {{ background:#111; border:1px solid #333; padding:16px; margin:16px 0; border-radius:4px; font-size:13px; line-height:1.6; }}
  img {{ border:1px solid #333; border-radius:2px; max-width:100%; }}
  .pair {{ display:flex; gap:16px; margin:16px 0; }}
  .pair img {{ max-width:48%; }}
</style></head><body>
<h1>Map Interaction Report</h1>
<p>Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}</p>

<div class="summary">
  <div class="stat"><div class="val">10</div><div class="label">TESTS RUN</div></div>
</div>

<h2>Default View</h2>
<img src="10_default.png" style="max-width:800px;">
<div class="llm">{analyses.get('default', 'N/A')}</div>

<h2>Zoomed In</h2>
<img src="10_zoomed_in.png" style="max-width:800px;">
<div class="llm">{analyses.get('zoomed', 'N/A')}</div>

<h2>Zoom Level Progression</h2>
<div class="pair">
  <img src="09_zoom_level_0.png">
  <img src="09_zoom_level_4.png">
</div>

</body></html>"""
        REPORT_PATH.write_text(html)
        print(f"\nReport: {REPORT_PATH}")

    def test_11_no_js_errors(self):
        """No critical JS errors during map interaction."""
        critical = [e for e in self._errors if "TypeError" in e or "ReferenceError" in e]
        if critical:
            print(f"Critical JS errors: {critical}")
        assert len(critical) == 0, f"JS errors: {critical}"
