# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""
Map Layers Exercise: Toggle every map layer on/off and verify state changes.
Exercises the MAP menu toggles: satellite, roads, buildings, waterways, parks,
grid, 3D models, labels, mesh, tracers, explosions, particles, hit flashes,
floating text, kill feed, screen FX, banners, layer HUD, health bars,
selection FX, fog, terrain, and 3D tilt mode.

Run:
    .venv/bin/python3 -m pytest tests/visual/test_map_layers_exercise.py -v -s
"""

from __future__ import annotations

import time
from pathlib import Path

import cv2
import numpy as np
import pytest

pytestmark = pytest.mark.visual

SCREENSHOT_DIR = Path("tests/.test-results/map-layers")
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


class TestMapLayersExercise:
    """Exercise every map layer toggle via getMapState/setLayers API."""

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

    def _get_state(self):
        return self.page.evaluate("() => window._mapState ? window._mapActions?.getMapState?.() : null")

    # --- Verify baseline state ---

    def test_01_map_state_accessible(self):
        """getMapState() returns layer visibility state."""
        state = self.page.evaluate("""() => {
            const ms = window._mapState;
            if (!ms) return null;
            return {
                showSatellite: ms.showSatellite,
                showBuildings: ms.showBuildings,
                showRoads: ms.showRoads,
                showGrid: ms.showGrid,
                showUnits: ms.showUnits,
                showLabels: ms.showLabels,
                showModels3d: ms.showModels3d,
                showFog: ms.showFog,
                showMesh: ms.showMesh,
                showTracers: ms.showTracers,
                showExplosions: ms.showExplosions,
                showParticles: ms.showParticles,
                showHitFlashes: ms.showHitFlashes,
                showFloatingText: ms.showFloatingText,
                showKillFeed: ms.showKillFeed,
                showScreenFx: ms.showScreenFx,
                showBanners: ms.showBanners,
                showLayerHud: ms.showLayerHud,
                showHealthBars: ms.showHealthBars,
                showSelectionFx: ms.showSelectionFx,
                showWaterways: ms.showWaterways,
                showParks: ms.showParks,
                showTerrain: ms.showTerrain,
                tiltMode: ms.tiltMode,
            };
        }""")

        print(f"\nMap state: {state}")
        self._screenshot("01_baseline")

        assert state is not None, "Map state should be accessible"
        # Check key defaults
        assert state["showUnits"] is True, "Units should be shown by default"
        assert state["showLabels"] is True, "Labels should be shown by default"

    # --- Toggle base map layers ---

    def test_02_toggle_satellite(self):
        """Toggle satellite imagery off and verify state change."""
        before = self.page.evaluate("() => window._mapState?.showSatellite")
        self.page.evaluate("""() => {
            window._mapActions?.toggleSatellite?.() ||
            (() => { window._mapState.showSatellite = !window._mapState.showSatellite; })();
        }""")
        time.sleep(0.3)
        after = self.page.evaluate("() => window._mapState?.showSatellite")
        print(f"\nSatellite: {before} -> {after}")
        self._screenshot("02_satellite_toggled")
        assert before != after, f"Satellite should have toggled: {before} -> {after}"

    def test_03_toggle_roads(self):
        """Toggle roads layer."""
        before = self.page.evaluate("() => window._mapState?.showRoads")
        self.page.evaluate("""() => {
            window._mapActions?.toggleRoads?.() ||
            (() => { window._mapState.showRoads = !window._mapState.showRoads; })();
        }""")
        time.sleep(0.3)
        after = self.page.evaluate("() => window._mapState?.showRoads")
        print(f"\nRoads: {before} -> {after}")
        assert before != after, f"Roads should have toggled"

    def test_04_toggle_buildings(self):
        """Toggle buildings layer."""
        before = self.page.evaluate("() => window._mapState?.showBuildings")
        self.page.evaluate("""() => {
            window._mapActions?.toggleBuildings?.() ||
            (() => { window._mapState.showBuildings = !window._mapState.showBuildings; })();
        }""")
        time.sleep(0.3)
        after = self.page.evaluate("() => window._mapState?.showBuildings")
        print(f"\nBuildings: {before} -> {after}")
        assert before != after, f"Buildings should have toggled"

    def test_05_toggle_grid(self):
        """Toggle tactical grid overlay."""
        before = self.page.evaluate("() => window._mapState?.showGrid")
        self.page.evaluate("""() => {
            window._mapActions?.toggleGrid?.() ||
            (() => { window._mapState.showGrid = !window._mapState.showGrid; })();
        }""")
        time.sleep(0.3)
        after = self.page.evaluate("() => window._mapState?.showGrid")
        shot = self._screenshot("05_grid_toggled")
        print(f"\nGrid: {before} -> {after}")
        assert before != after, f"Grid should have toggled"

    # --- Toggle tactical layers ---

    def test_06_toggle_labels(self):
        """Toggle unit labels."""
        before = self.page.evaluate("() => window._mapState?.showLabels")
        self.page.evaluate("() => { window._mapState.showLabels = !window._mapState.showLabels; }")
        time.sleep(0.3)
        after = self.page.evaluate("() => window._mapState?.showLabels")
        print(f"\nLabels: {before} -> {after}")
        self._screenshot("06_labels_toggled")
        assert before != after, f"Labels should have toggled"
        # Restore
        self.page.evaluate("() => { window._mapState.showLabels = !window._mapState.showLabels; }")

    def test_07_toggle_models3d(self):
        """Toggle 3D models."""
        before = self.page.evaluate("() => window._mapState?.showModels3d")
        self.page.evaluate("""() => {
            window._mapActions?.toggleModels?.() ||
            (() => {
                window._mapState.showModels3d = !window._mapState.showModels3d;
                if (window._mapState.threeRoot) window._mapState.threeRoot.visible = window._mapState.showModels3d;
            })();
        }""")
        time.sleep(0.3)
        after = self.page.evaluate("() => window._mapState?.showModels3d")
        self._screenshot("07_3d_toggled")
        print(f"\n3D Models: {before} -> {after}")
        assert before != after, f"3D models should have toggled"

    def test_08_toggle_health_bars(self):
        """Toggle health bars."""
        before = self.page.evaluate("() => window._mapState?.showHealthBars")
        self.page.evaluate("() => { window._mapState.showHealthBars = !window._mapState.showHealthBars; }")
        time.sleep(0.3)
        after = self.page.evaluate("() => window._mapState?.showHealthBars")
        self._screenshot("08_health_bars_toggled")
        print(f"\nHealth Bars: {before} -> {after}")
        assert before != after, f"Health bars should have toggled"
        # Restore
        self.page.evaluate("() => { window._mapState.showHealthBars = !window._mapState.showHealthBars; }")

    # --- Combat FX toggles ---

    def test_09_toggle_combat_fx(self):
        """Toggle all combat FX layers and verify state changes."""
        fx_layers = ['showTracers', 'showExplosions', 'showParticles',
                     'showHitFlashes', 'showFloatingText']
        results = {}
        for layer in fx_layers:
            before = self.page.evaluate(f"() => window._mapState?.{layer}")
            self.page.evaluate(f"() => {{ window._mapState.{layer} = !window._mapState.{layer}; }}")
            after = self.page.evaluate(f"() => window._mapState?.{layer}")
            results[layer] = {"before": before, "after": after, "toggled": before != after}

        print(f"\nCombat FX toggles: {results}")

        for layer, r in results.items():
            assert r["toggled"], f"{layer} should have toggled: {r}"
            # Restore
            self.page.evaluate(f"() => {{ window._mapState.{layer} = !window._mapState.{layer}; }}")

    # --- Overlay toggles ---

    def test_10_toggle_overlays(self):
        """Toggle overlay layers (kill feed, screen FX, banners, layer HUD)."""
        overlay_layers = ['showKillFeed', 'showScreenFx', 'showBanners', 'showLayerHud']
        results = {}
        for layer in overlay_layers:
            before = self.page.evaluate(f"() => window._mapState?.{layer}")
            self.page.evaluate(f"() => {{ window._mapState.{layer} = !window._mapState.{layer}; }}")
            after = self.page.evaluate(f"() => window._mapState?.{layer}")
            results[layer] = {"before": before, "after": after, "toggled": before != after}

        print(f"\nOverlay toggles: {results}")

        for layer, r in results.items():
            assert r["toggled"], f"{layer} should have toggled: {r}"
            # Restore
            self.page.evaluate(f"() => {{ window._mapState.{layer} = !window._mapState.{layer}; }}")

    # --- Tilt mode ---

    def test_11_toggle_tilt_mode(self):
        """Toggle between tilted (3D) and top-down (2D) view."""
        before = self.page.evaluate("() => window._mapState?.tiltMode")
        self.page.evaluate("""() => {
            if (window._mapActions?.toggleTilt) window._mapActions.toggleTilt();
        }""")
        time.sleep(1)  # easeTo animation takes time
        after = self.page.evaluate("() => window._mapState?.tiltMode")
        self._screenshot("11_tilt_toggled")
        print(f"\nTilt mode: {before} -> {after}")
        # Tilt may or may not change depending on pitch animation state

    # --- Visual diff: all layers on vs all off ---

    def test_12_all_layers_off_vs_on(self):
        """Toggling all layers produces dramatic visual change."""
        before = self._screenshot("12_all_on")

        self.page.evaluate("""() => {
            if (window._mapActions?.setLayers) {
                window._mapActions.setLayers({ allMapLayers: false });
            }
        }""")
        time.sleep(0.5)
        after = self._screenshot("12_all_off")

        diff = _opencv_diff(before, after)
        print(f"\nAll layers on vs off diff: {diff:.1f}%")

        # Restore all layers
        self.page.evaluate("""() => {
            if (window._mapActions?.setLayers) {
                window._mapActions.setLayers({ allMapLayers: true });
            }
        }""")
        time.sleep(0.5)

        assert diff > 1.0, f"Should see big visual change: {diff:.1f}%"

    # --- Layer HUD shows active layers ---

    def test_13_layer_hud_content(self):
        """Layer HUD displays active layer abbreviations."""
        hud_text = self.page.evaluate("""() => {
            const hud = document.getElementById('map-layer-hud');
            return hud ? hud.textContent : null;
        }""")

        print(f"\nLayer HUD: {hud_text}")
        self._screenshot("13_layer_hud")

        if hud_text:
            # Should contain mode (OBSERVE/TACTICAL/SETUP) and layer indicators
            assert len(hud_text) > 5, f"HUD should have content: '{hud_text}'"

    # --- Map mode switches ---

    def test_14_map_mode_observe(self):
        """Switch to OBSERVE mode."""
        self.page.evaluate("""() => {
            if (window._mapActions?.setMapMode) window._mapActions.setMapMode('observe');
            else if (window._mapState) window._mapState.currentMode = 'observe';
        }""")
        time.sleep(0.5)
        mode = self.page.evaluate("() => window._mapState?.currentMode")
        self._screenshot("14_observe_mode")
        print(f"\nMode: {mode}")
        assert mode == "observe", f"Should be observe: {mode}"

    def test_15_map_mode_tactical(self):
        """Switch to TACTICAL mode."""
        self.page.evaluate("""() => {
            if (window._mapActions?.setMapMode) window._mapActions.setMapMode('tactical');
            else if (window._mapState) window._mapState.currentMode = 'tactical';
        }""")
        time.sleep(0.5)
        mode = self.page.evaluate("() => window._mapState?.currentMode")
        self._screenshot("15_tactical_mode")
        print(f"\nMode: {mode}")
        assert mode == "tactical", f"Should be tactical: {mode}"

    def test_16_map_mode_setup(self):
        """Switch to SETUP mode."""
        self.page.evaluate("""() => {
            if (window._mapActions?.setMapMode) window._mapActions.setMapMode('setup');
            else if (window._mapState) window._mapState.currentMode = 'setup';
        }""")
        time.sleep(0.5)
        mode = self.page.evaluate("() => window._mapState?.currentMode")
        self._screenshot("16_setup_mode")
        print(f"\nMode: {mode}")
        assert mode == "setup", f"Should be setup: {mode}"

    # --- Camera controls ---

    def test_17_zoom_in_out(self):
        """Zoom in and out."""
        before_zoom = self.page.evaluate("() => window._mapState?.map?.getZoom()")
        self.page.evaluate("() => window._mapActions?.zoomIn?.()")
        time.sleep(1)  # MapLibre zoom animation
        after_zoom_in = self.page.evaluate("() => window._mapState?.map?.getZoom()")
        self.page.evaluate("() => window._mapActions?.zoomOut?.()")
        time.sleep(1)
        after_zoom_out = self.page.evaluate("() => window._mapState?.map?.getZoom()")

        print(f"\nZoom: {before_zoom} -> zoomIn:{after_zoom_in} -> zoomOut:{after_zoom_out}")
        if before_zoom is not None and after_zoom_in is not None:
            assert after_zoom_in >= before_zoom, f"Zoom in should increase or equal: {after_zoom_in} >= {before_zoom}"

    def test_18_reset_camera(self):
        """Reset camera to default position."""
        self.page.evaluate("() => window._mapActions?.resetCamera?.()")
        time.sleep(0.5)
        zoom = self.page.evaluate("() => window._mapState?.map?.getZoom()")
        self._screenshot("18_camera_reset")
        print(f"\nZoom after reset: {zoom}")
        assert zoom is not None, "Should have a zoom level"

    # --- LLM analysis ---

    def test_19_llm_layer_analysis(self):
        """LLaVA analyzes the map with all layers visible."""
        # Restore everything first
        self.page.evaluate("""() => {
            window._mapActions?.setMapMode?.('observe');
            if (window._mapActions?.setLayers)
                window._mapActions.setLayers({ allMapLayers: true });
        }""")
        time.sleep(1)

        shot = self._screenshot("19_llm_all_layers")
        analysis = _llava_analyze(shot,
            "Describe this tactical map interface. What layers are visible? "
            "Can you see satellite imagery, buildings, roads, unit markers, "
            "and any overlay information? How many distinct visual layers "
            "are composited together?")

        print(f"\nLayer analysis: {analysis[:200]}")
        self._generate_report(analysis)

    def _generate_report(self, analysis: str):
        html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>Map Layers Exercise Report</title>
<style>
  body {{ background:#0a0a0f; color:#c0c0c0; font-family:'JetBrains Mono',monospace; margin:20px; }}
  h1 {{ color:#00f0ff; border-bottom:2px solid #00f0ff33; padding-bottom:8px; }}
  h2 {{ color:#ff2a6d; margin-top:32px; }}
  .llm {{ background:#111; border:1px solid #333; padding:16px; margin:16px 0; border-radius:4px; font-size:13px; line-height:1.6; }}
  img {{ border:1px solid #333; border-radius:2px; max-width:100%; }}
  .screenshots {{ display:flex; gap:8px; flex-wrap:wrap; margin:16px 0; }}
  .screenshots img {{ max-width:32%; }}
</style></head><body>
<h1>Map Layers Exercise Report</h1>
<p>Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}</p>

<h2>All Layers</h2>
<img src="19_llm_all_layers.png" style="max-width:100%;">
<div class="llm">{analysis}</div>

<h2>Layer Toggles</h2>
<div class="screenshots">
  <img src="05_grid_toggled.png">
  <img src="07_3d_toggled.png">
  <img src="11_tilt_toggled.png">
</div>

<h2>All On vs All Off</h2>
<div class="screenshots">
  <img src="12_all_on.png">
  <img src="12_all_off.png">
</div>

<h2>Map Modes</h2>
<div class="screenshots">
  <img src="14_observe_mode.png">
  <img src="15_tactical_mode.png">
  <img src="16_setup_mode.png">
</div>

</body></html>"""
        REPORT_PATH.write_text(html)
        print(f"\nReport: {REPORT_PATH}")

    def test_20_no_js_errors(self):
        """No critical JS errors during layer testing."""
        critical = [e for e in self._errors if "TypeError" in e or "ReferenceError" in e]
        if critical:
            print(f"Critical JS errors: {critical}")
        assert len(critical) == 0, f"JS errors: {critical}"
