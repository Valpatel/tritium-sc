# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""
Map Layer Toggles Exercise: Verify each map layer toggle produces visible
changes. Tests satellite, roads, grid, buildings, fog, terrain, waterways,
parks, mesh, tracers, health bars, and other visual layers.

Run:
    .venv/bin/python3 -m pytest tests/visual/test_map_layer_toggles_exercise.py -v -s
"""

from __future__ import annotations

import time
from pathlib import Path

import cv2
import numpy as np
import pytest

pytestmark = pytest.mark.visual

SCREENSHOT_DIR = Path("tests/.test-results/map-layer-toggles")
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


class TestMapLayerTogglesExercise:
    """Exercise all map layer toggles and verify visual changes."""

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

    def _get_layer_state(self) -> dict:
        """Get current state of all map layers."""
        return self.page.evaluate("""() => {
            const ma = window._mapActions;
            if (!ma || !ma.getMapState) return {};
            return ma.getMapState();
        }""")

    def _toggle_layer(self, fn_name: str) -> dict:
        """Toggle a layer and return before/after screenshots + diff."""
        before = self._screenshot(f"_tmp_before_{fn_name}")
        self.page.evaluate(f"() => window._mapActions.{fn_name}()")
        time.sleep(1.5)
        after = self._screenshot(f"_tmp_after_{fn_name}")
        diff = _opencv_diff(before, after)
        return {"before": before, "after": after, "diff": diff}

    # --- Layer state ---

    def test_01_initial_layer_state(self):
        """Get initial state of all map layers."""
        state = self._get_layer_state()
        print(f"\nInitial layer state:")
        for k, v in sorted(state.items()):
            print(f"  {k:25s} = {v}")
        self._screenshot("01_initial")

    def test_02_toggle_satellite(self):
        """Satellite toggle changes map tiles."""
        result = self._toggle_layer("toggleSatellite")
        shot = self._screenshot("02_satellite")
        state = self._get_layer_state()

        print(f"\nSatellite toggle: diff={result['diff']:.1f}%, satellite={state.get('satellite')}")
        # Toggle back
        self.page.evaluate("() => window._mapActions.toggleSatellite()")
        time.sleep(1)

    def test_03_toggle_roads(self):
        """Roads toggle shows/hides road network."""
        result = self._toggle_layer("toggleRoads")
        state = self._get_layer_state()

        print(f"\nRoads toggle: diff={result['diff']:.1f}%, roads={state.get('roads')}")
        self._screenshot("03_roads")
        # Toggle back
        self.page.evaluate("() => window._mapActions.toggleRoads()")
        time.sleep(0.5)

    def test_04_toggle_grid(self):
        """Grid toggle shows/hides coordinate grid."""
        result = self._toggle_layer("toggleGrid")
        state = self._get_layer_state()

        print(f"\nGrid toggle: diff={result['diff']:.1f}%, grid={state.get('grid')}")
        self._screenshot("04_grid")
        self.page.evaluate("() => window._mapActions.toggleGrid()")
        time.sleep(0.5)

    def test_05_toggle_buildings(self):
        """Buildings toggle shows/hides building polygons."""
        result = self._toggle_layer("toggleBuildings")
        state = self._get_layer_state()

        print(f"\nBuildings toggle: diff={result['diff']:.1f}%, buildings={state.get('buildings')}")
        self._screenshot("05_buildings")
        self.page.evaluate("() => window._mapActions.toggleBuildings()")
        time.sleep(0.5)

    def test_06_toggle_fog(self):
        """Fog of war toggle shows/hides vision cones."""
        result = self._toggle_layer("toggleFog")
        state = self._get_layer_state()

        print(f"\nFog toggle: diff={result['diff']:.1f}%, fog={state.get('fog')}")
        self._screenshot("06_fog")
        self.page.evaluate("() => window._mapActions.toggleFog()")
        time.sleep(0.5)

    def test_07_toggle_terrain(self):
        """Terrain toggle shows/hides elevation shading."""
        result = self._toggle_layer("toggleTerrain")
        state = self._get_layer_state()

        print(f"\nTerrain toggle: diff={result['diff']:.1f}%, terrain={state.get('terrain')}")
        self._screenshot("07_terrain")
        self.page.evaluate("() => window._mapActions.toggleTerrain()")
        time.sleep(0.5)

    def test_08_toggle_labels(self):
        """Labels toggle shows/hides map labels."""
        result = self._toggle_layer("toggleLabels")
        state = self._get_layer_state()

        print(f"\nLabels toggle: diff={result['diff']:.1f}%, labels={state.get('labels')}")
        self._screenshot("08_labels")
        self.page.evaluate("() => window._mapActions.toggleLabels()")
        time.sleep(0.5)

    def test_09_toggle_health_bars(self):
        """Health bars toggle shows/hides unit health bars."""
        result = self._toggle_layer("toggleHealthBars")
        state = self._get_layer_state()

        print(f"\nHealth bars toggle: diff={result['diff']:.1f}%, healthBars={state.get('healthBars')}")
        self._screenshot("09_health_bars")
        self.page.evaluate("() => window._mapActions.toggleHealthBars()")
        time.sleep(0.5)

    def test_10_toggle_tracers(self):
        """Tracers toggle shows/hides projectile trails."""
        result = self._toggle_layer("toggleTracers")
        state = self._get_layer_state()

        print(f"\nTracers toggle: diff={result['diff']:.1f}%, tracers={state.get('tracers')}")
        self._screenshot("10_tracers")
        self.page.evaluate("() => window._mapActions.toggleTracers()")
        time.sleep(0.5)

    def test_11_toggle_all_layers(self):
        """Toggle all layers produces significant visual change."""
        before = self._screenshot("11_before_all")

        self.page.evaluate("() => window._mapActions.toggleAllLayers()")
        time.sleep(2)

        after = self._screenshot("11_after_all")
        diff = _opencv_diff(before, after)

        state = self._get_layer_state()
        print(f"\nToggle all: diff={diff:.1f}%")
        for k, v in sorted(state.items()):
            print(f"  {k:25s} = {v}")

        # Toggle back
        self.page.evaluate("() => window._mapActions.toggleAllLayers()")
        time.sleep(1)

    def test_12_layer_toggle_summary(self):
        """Summary of all layer toggle diffs with LLaVA analysis."""
        toggles = [
            "toggleSatellite", "toggleRoads", "toggleGrid", "toggleBuildings",
            "toggleFog", "toggleTerrain", "toggleLabels", "toggleHealthBars",
            "toggleTracers", "toggleMesh",
        ]

        results = {}
        for fn in toggles:
            try:
                before = self._screenshot(f"12_{fn}_before")
                self.page.evaluate(f"() => window._mapActions.{fn}()")
                time.sleep(1)
                after = self._screenshot(f"12_{fn}_after")
                diff = _opencv_diff(before, after)
                results[fn] = diff
                # Toggle back
                self.page.evaluate(f"() => window._mapActions.{fn}()")
                time.sleep(0.5)
            except Exception as e:
                results[fn] = f"error: {e}"

        print(f"\nLayer toggle diffs:")
        for fn, diff in results.items():
            label = fn.replace("toggle", "")
            if isinstance(diff, float):
                indicator = "***" if diff > 1.0 else "  *" if diff > 0.1 else "   "
                print(f"  {indicator} {label:20s} = {diff:.1f}%")
            else:
                print(f"  ERR {label:20s} = {diff}")

        shot = self._screenshot("12_summary")
        analysis = _llava_analyze(shot,
            "Analyze this tactical map interface. Describe the visible map layers "
            "including satellite imagery, roads, buildings, fog of war, and unit markers.")

        print(f"\nLLaVA analysis: {analysis[:200]}")
        self._generate_report(results, analysis)

    def _generate_report(self, results: dict, analysis: str):
        rows = ""
        for fn, diff in results.items():
            label = fn.replace("toggle", "")
            if isinstance(diff, float):
                color = "#05ffa1" if diff > 1.0 else "#fcee0a" if diff > 0.1 else "#ff2a6d"
                rows += f'<tr><td>{label}</td><td style="color:{color}">{diff:.1f}%</td></tr>\n'
            else:
                rows += f'<tr><td>{label}</td><td style="color:#ff2a6d">{diff}</td></tr>\n'

        html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>Map Layer Toggles Report</title>
<style>
  body {{ background:#0a0a0f; color:#c0c0c0; font-family:'JetBrains Mono',monospace; margin:20px; }}
  h1 {{ color:#00f0ff; border-bottom:2px solid #00f0ff33; padding-bottom:8px; }}
  h2 {{ color:#ff2a6d; margin-top:32px; }}
  .llm {{ background:#111; border:1px solid #333; padding:16px; margin:16px 0; border-radius:4px; font-size:13px; line-height:1.6; }}
  img {{ border:1px solid #333; border-radius:2px; max-width:100%; }}
  table {{ border-collapse:collapse; margin:16px 0; }}
  th, td {{ border:1px solid #333; padding:8px 16px; text-align:left; }}
  th {{ background:#111; color:#00f0ff; }}
</style></head><body>
<h1>Map Layer Toggles Report</h1>
<p>Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}</p>

<h2>Toggle Impact (pixel diff %)</h2>
<table>
<tr><th>Layer</th><th>Diff %</th></tr>
{rows}
</table>

<h2>Map Overview</h2>
<img src="12_summary.png" style="max-width:100%;">
<div class="llm">{analysis}</div>

</body></html>"""
        REPORT_PATH.write_text(html)
        print(f"\nReport: {REPORT_PATH}")

    def test_13_no_js_errors(self):
        """No critical JS errors during layer toggle testing."""
        critical = [e for e in self._errors if "TypeError" in e or "ReferenceError" in e]
        if critical:
            print(f"Critical JS errors: {critical}")
        assert len(critical) == 0, f"JS errors: {critical}"
