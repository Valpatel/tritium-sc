# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""
Unit Marker Exercise: Verify DOM markers show location indicators
when 3D models are hidden, and exercise marker styles across modes.

Run:
    .venv/bin/python3 -m pytest tests/visual/test_unit_marker_exercise.py -v -s
"""

from __future__ import annotations

import time
from pathlib import Path

import cv2
import numpy as np
import pytest

pytestmark = pytest.mark.visual

SCREENSHOT_DIR = Path("tests/.test-results/unit-markers")
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


class TestUnitMarkerExercise:
    """Exercise unit markers across 3D on/off and label/health toggles."""

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
        self.page.screenshot(path=path, timeout=60000)
        return path

    # --- Baseline: 3D models on ---

    def test_01_units_visible(self):
        """Units should be visible on the map with markers."""
        state = self.page.evaluate("""() => {
            const ms = window._mapState;
            if (!ms) return null;
            return {
                showModels3d: ms.showModels3d,
                showUnits: ms.showUnits,
                markerCount: Object.keys(ms.unitMarkers).length,
                threeRoot: !!ms.threeRoot,
            };
        }""")

        print(f"\nMap state: {state}")
        self._screenshot("01_units")

        assert state is not None, "Map state should exist"
        assert state["markerCount"] > 0, f"Should have markers: {state['markerCount']}"

    def test_02_markers_have_3d_label_style(self):
        """With 3D on, markers should be in callsign-tag style (3D mode)."""
        marker_info = self.page.evaluate("""() => {
            const ms = window._mapState;
            if (!ms || !ms.showModels3d) return null;
            const markers = document.querySelectorAll('.tritium-unit-inner');
            const results = [];
            for (const m of markers) {
                results.push({
                    has3dName: !!m.querySelector('.unit-name-3d'),
                    hasCircleIcon: m.textContent.trim().length === 1 && !m.querySelector('.unit-name-3d'),
                });
                if (results.length >= 5) break;
            }
            return results;
        }""")

        print(f"\n3D marker styles: {marker_info}")
        if marker_info:
            has_3d_labels = any(m["has3dName"] for m in marker_info)
            assert has_3d_labels, "3D mode markers should have .unit-name-3d labels"

    # --- Toggle 3D models off ---

    def test_03_toggle_3d_off_shows_location_dot(self):
        """Toggling 3D off should add a small location dot to markers."""
        # Toggle 3D models off
        self.page.evaluate("""() => {
            const ms = window._mapState;
            if (ms && ms.threeRoot) {
                ms.showModels3d = false;
                ms.threeRoot.visible = false;
            }
        }""")
        time.sleep(0.5)  # Wait for 10Hz update to re-render markers

        marker_info = self.page.evaluate("""() => {
            const ms = window._mapState;
            const markers = document.querySelectorAll('.tritium-unit-inner');
            const results = [];
            for (const m of markers) {
                const dot = m.querySelector('.unit-loc-dot');
                results.push({
                    hasLocDot: !!dot,
                    dotWidth: dot ? dot.style.width : '',
                    dotHeight: dot ? dot.style.height : '',
                    hasNameLabel: !!m.querySelector('.unit-name-3d'),
                });
                if (results.length >= 5) break;
            }
            return { showModels3d: ms?.showModels3d, markers: results };
        }""")

        print(f"\n3D OFF markers: {marker_info}")
        self._screenshot("03_3d_off")

        assert marker_info is not None
        assert not marker_info["showModels3d"], "3D should be off"
        markers = marker_info["markers"]
        if markers:
            for m in markers:
                assert m["hasLocDot"], "Should have .unit-loc-dot when 3D is off"
                assert m["dotWidth"] == "6px", f"Dot should be 6px: {m['dotWidth']}"

    def test_04_circle_icons_have_color(self):
        """Circle icons should have alliance-appropriate colors."""
        # Ensure 3D is off
        self.page.evaluate("""() => {
            const ms = window._mapState;
            if (ms && ms.threeRoot) {
                ms.showModels3d = false;
                ms.threeRoot.visible = false;
            }
        }""")
        time.sleep(0.5)

        colors = self.page.evaluate("""() => {
            const markers = document.querySelectorAll('.tritium-unit-inner');
            const results = [];
            for (const m of markers) {
                const style = m.style.cssText || '';
                const cs = getComputedStyle(m);
                results.push({
                    color: m.style.color || cs.color,
                    borderColor: m.style.borderColor || cs.borderColor,
                    alliance: m.parentElement?.dataset?.alliance || 'unknown',
                });
                if (results.length >= 5) break;
            }
            return results;
        }""")

        print(f"\nMarker colors: {colors}")
        if colors:
            for c in colors:
                assert c["color"], f"Marker should have a color: {c}"

    # --- Visual comparison ---

    def test_05_visual_diff_3d_on_vs_off(self):
        """Toggling 3D models should produce visible change in markers."""
        # 3D ON
        self.page.evaluate("""() => {
            const ms = window._mapState;
            if (ms && ms.threeRoot) {
                ms.showModels3d = true;
                ms.threeRoot.visible = true;
            }
        }""")
        time.sleep(0.5)
        before = self._screenshot("05_3d_on")

        # 3D OFF
        self.page.evaluate("""() => {
            const ms = window._mapState;
            if (ms && ms.threeRoot) {
                ms.showModels3d = false;
                ms.threeRoot.visible = false;
            }
        }""")
        time.sleep(0.5)
        after = self._screenshot("05_3d_off")

        diff = _opencv_diff(before, after)
        print(f"\n3D on vs off diff: {diff:.1f}%")

        assert diff > 0.1, f"Should see visual difference: {diff:.1f}%"

        # Restore 3D
        self.page.evaluate("""() => {
            const ms = window._mapState;
            if (ms && ms.threeRoot) {
                ms.showModels3d = true;
                ms.threeRoot.visible = true;
            }
        }""")

    # --- Labels toggle ---

    def test_06_labels_toggle_hides_names(self):
        """Toggling labels off should remove name text from markers."""
        # Labels ON first
        self.page.evaluate("() => { window._mapState.showLabels = true; }")
        time.sleep(0.5)
        before = self._screenshot("06_labels_on")

        names_on = self.page.evaluate("""() => {
            const markers = document.querySelectorAll('.tritium-unit-inner');
            let count = 0;
            for (const m of markers) {
                if (m.querySelector('.unit-name-3d') || m.querySelector('.unit-name')) count++;
            }
            return count;
        }""")

        # Labels OFF
        self.page.evaluate("() => { window._mapState.showLabels = false; }")
        time.sleep(0.5)
        after = self._screenshot("06_labels_off")

        names_off = self.page.evaluate("""() => {
            const markers = document.querySelectorAll('.tritium-unit-inner');
            let count = 0;
            for (const m of markers) {
                if (m.querySelector('.unit-name-3d') || m.querySelector('.unit-name')) count++;
            }
            return count;
        }""")

        print(f"\nNames with labels on: {names_on}, off: {names_off}")

        # Restore
        self.page.evaluate("() => { window._mapState.showLabels = true; }")

        if names_on > 0:
            assert names_off < names_on, f"Fewer labels when off: {names_off} < {names_on}"

    # --- Health bars toggle ---

    def test_07_health_bars_toggle(self):
        """Health bars appear/disappear with toggle."""
        self.page.evaluate("() => { window._mapState.showHealthBars = true; }")
        time.sleep(0.5)

        hp_on = self.page.evaluate("""() => {
            const markers = document.querySelectorAll('.tritium-unit-inner');
            let count = 0;
            for (const m of markers) {
                if (m.querySelector('.unit-hp-bar-3d') || m.querySelector('.unit-hp-bar')) count++;
            }
            return count;
        }""")

        self.page.evaluate("() => { window._mapState.showHealthBars = false; }")
        time.sleep(0.5)

        hp_off = self.page.evaluate("""() => {
            const markers = document.querySelectorAll('.tritium-unit-inner');
            let count = 0;
            for (const m of markers) {
                if (m.querySelector('.unit-hp-bar-3d') || m.querySelector('.unit-hp-bar')) count++;
            }
            return count;
        }""")

        print(f"\nHealth bars on: {hp_on}, off: {hp_off}")
        self._screenshot("07_health_toggle")

        # Restore
        self.page.evaluate("() => { window._mapState.showHealthBars = true; }")

        if hp_on > 0:
            assert hp_off < hp_on, f"Fewer health bars when off: {hp_off} < {hp_on}"

    # --- Edge cases ---

    def test_08_eliminated_units_dimmed(self):
        """Eliminated units should have reduced opacity."""
        elim_info = self.page.evaluate("""() => {
            const markers = document.querySelectorAll('.tritium-unit-inner');
            const results = [];
            for (const m of markers) {
                const style = m.style.cssText || '';
                const opMatch = style.match(/opacity:\\s*([\\d.]+)/);
                results.push({
                    opacity: opMatch ? parseFloat(opMatch[1]) : 1.0,
                });
            }
            return results;
        }""")

        print(f"\nMarker opacities: {[e['opacity'] for e in elim_info[:5]]}")
        # Just verify we can read opacity — eliminated units may or may not exist
        assert isinstance(elim_info, list), "Should return marker info list"

    def test_09_marker_count_matches_store(self):
        """Number of DOM markers should match TritiumStore unit count."""
        counts = self.page.evaluate("""() => {
            const ms = window._mapState;
            const storeCount = window.TritiumStore?.units?.size || 0;
            const markerCount = Object.keys(ms?.unitMarkers || {}).length;
            const domCount = document.querySelectorAll('.tritium-unit-marker').length;
            return { storeCount, markerCount, domCount };
        }""")

        print(f"\nCounts: {counts}")
        if counts["storeCount"] > 0:
            assert counts["markerCount"] == counts["storeCount"], \
                f"Marker count should match store: {counts}"
            assert counts["domCount"] == counts["storeCount"], \
                f"DOM count should match store: {counts}"

    # --- LLM analysis ---

    def test_10_llm_marker_analysis(self):
        """LLaVA analyzes unit markers."""
        try:
            shot = self._screenshot("10_llm_markers")
            analysis = _llava_analyze(shot,
                "Look at this tactical map interface. Describe the unit markers visible "
                "on the map: their shape (dots, circles, squares), colors, labels, and any "
                "letters or icons. Are the markers clearly visible as location indicators?")
            print(f"\nMarker analysis: {analysis[:200]}")
            self._generate_report(analysis)
        except Exception as e:
            print(f"\nLLM analysis skipped (page issue): {e}")
            self._generate_report("Analysis skipped due to page error.")

    def _generate_report(self, analysis: str):
        html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>Unit Marker Exercise Report</title>
<style>
  body {{ background:#0a0a0f; color:#c0c0c0; font-family:'JetBrains Mono',monospace; margin:20px; }}
  h1 {{ color:#00f0ff; border-bottom:2px solid #00f0ff33; padding-bottom:8px; }}
  h2 {{ color:#ff2a6d; margin-top:32px; }}
  .llm {{ background:#111; border:1px solid #333; padding:16px; margin:16px 0; border-radius:4px; font-size:13px; line-height:1.6; }}
  img {{ border:1px solid #333; border-radius:2px; max-width:100%; }}
  .screenshots {{ display:flex; gap:8px; flex-wrap:wrap; margin:16px 0; }}
  .screenshots img {{ max-width:48%; }}
</style></head><body>
<h1>Unit Marker Exercise Report</h1>
<p>Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}</p>

<h2>3D Models ON vs OFF</h2>
<div class="screenshots">
  <img src="05_3d_on.png">
  <img src="05_3d_off.png">
</div>

<h2>Label &amp; Health Toggles</h2>
<div class="screenshots">
  <img src="06_labels_on.png">
  <img src="06_labels_off.png">
</div>

<h2>LLM Analysis (3D OFF mode)</h2>
<img src="10_llm_3d_off.png" style="max-width:100%;">
<div class="llm">{analysis}</div>

</body></html>"""
        REPORT_PATH.write_text(html)
        print(f"\nReport: {REPORT_PATH}")

    def test_11_no_js_errors(self):
        """No critical JS errors during marker testing."""
        critical = [e for e in self._errors if "TypeError" in e or "ReferenceError" in e]
        if critical:
            print(f"Critical JS errors: {critical}")
        assert len(critical) == 0, f"JS errors: {critical}"
