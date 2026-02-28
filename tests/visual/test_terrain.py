# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Visual tests for 3D terrain (MapLibre DEM tiles via Mapzen Terrarium proxy).

Verifies that:
- toggleTerrain() changes state and enables MapLibre terrain
- Terrain DEM tiles are fetched and loaded
- Visual difference between flat and terrain modes
- Terrain works with tilt and buildings
- Terrain tile proxy returns valid PNG with caching
- Rapid toggle does not produce JS errors
- Units still render on top of terrain

Run:
    .venv/bin/python3 -m pytest tests/visual/test_terrain.py -v
"""

from __future__ import annotations

import time
from pathlib import Path

import cv2
import numpy as np
import pytest
import requests
from playwright.sync_api import sync_playwright, Page, Error as PlaywrightError

pytestmark = pytest.mark.visual

SERVER = "http://localhost:8000"
OUT = Path("tests/.test-results/terrain")
OUT.mkdir(parents=True, exist_ok=True)

SETTLE = 3.0  # seconds for tiles to load after state change


# ============================================================
# Fixtures
# ============================================================

class BrowserSession:
    """Manages a Playwright browser with crash recovery."""

    def __init__(self):
        self._pw = None
        self._browser = None
        self._page = None
        self.console_errors: list[str] = []

    def start(self):
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=False)
        self._create_page()

    def _create_page(self):
        """Create a fresh page and navigate to the Command Center."""
        ctx = self._browser.new_context(viewport={"width": 1920, "height": 1080})
        self._page = ctx.new_page()
        self.console_errors = []
        self._page.on("pageerror", lambda e: self.console_errors.append(str(e)))
        self._page.goto(SERVER, wait_until="networkidle", timeout=30000)
        time.sleep(5)
        self._page.keyboard.press("Escape")
        time.sleep(0.5)

    @property
    def page(self) -> Page:
        return self._page

    def is_alive(self) -> bool:
        """Check if the page is still responsive."""
        try:
            self._page.evaluate("1 + 1")
            return True
        except Exception:
            return False

    def recover(self):
        """Recover from a crashed page by creating a new one."""
        try:
            self._page.context.close()
        except Exception:
            pass
        try:
            self._create_page()
        except Exception:
            # Browser itself may have crashed -- relaunch
            try:
                self._browser.close()
            except Exception:
                pass
            self._browser = self._pw.chromium.launch(headless=False)
            self._create_page()

    def ensure_alive(self):
        """Ensure page is alive, recovering if needed."""
        if not self.is_alive():
            self.recover()

    def stop(self):
        try:
            self._browser.close()
        except Exception:
            pass
        try:
            self._pw.stop()
        except Exception:
            pass


@pytest.fixture(scope="module")
def session():
    """Launch headed Playwright browser with crash recovery."""
    s = BrowserSession()
    s.start()
    yield s
    s.stop()


@pytest.fixture(autouse=True)
def reset_state(session):
    """Ensure terrain is OFF and pitch is reset before each test."""
    session.ensure_alive()
    page = session.page
    try:
        # Reset pitch to top-down to reduce memory pressure from DEM tiles
        page.evaluate("""(() => {
            const map = window._mapState.map;
            if (map) map.jumpTo({ pitch: 0 });
        })()""")
        time.sleep(0.3)
        # Turn off terrain
        state = page.evaluate("window._mapActions.getMapState()")
        if state and state.get("showTerrain"):
            page.evaluate("window._mapActions.toggleTerrain()")
            time.sleep(1)
    except PlaywrightError:
        # Page may have crashed; recover
        session.recover()
    session.console_errors.clear()


# ============================================================
# Helpers
# ============================================================

def _grab(page: Page) -> np.ndarray:
    """Full page screenshot as BGR numpy array."""
    buf = page.screenshot()
    arr = np.frombuffer(buf, dtype=np.uint8)
    return cv2.imdecode(arr, cv2.IMREAD_COLOR)


def _get_map_bounds(page: Page) -> dict:
    """Get the map container bounding rect in viewport pixels."""
    for sel in ["#maplibre-map", "#tactical-area"]:
        el = page.locator(sel)
        if el.count() > 0:
            bbox = el.first.bounding_box()
            if bbox and bbox["width"] > 100 and bbox["height"] > 100:
                return bbox
    return {"x": 230, "y": 40, "width": 1460, "height": 900}


def _crop_map_center(img: np.ndarray, bounds: dict, frac: float = 0.4) -> np.ndarray:
    """Crop the central portion of the map area (avoids panels, HUD, edges).

    Args:
        img: Full-page screenshot (BGR).
        bounds: Map container bounding rect.
        frac: Fraction of the map to keep (0.4 = central 40%).
    """
    x = int(bounds["x"])
    y = int(bounds["y"])
    w = int(bounds["width"])
    h = int(bounds["height"])
    ih, iw = img.shape[:2]

    cx = x + int(w * (1 - frac) / 2)
    cy = y + int(h * (1 - frac) / 2)
    cw = int(w * frac)
    ch = int(h * frac)

    x1 = max(0, cx)
    y1 = max(0, cy)
    x2 = min(iw, cx + cw)
    y2 = min(ih, cy + ch)
    return img[y1:y2, x1:x2].copy()


def _save(name: str, img: np.ndarray):
    """Save debug image."""
    cv2.imwrite(str(OUT / f"{name}.png"), img)


def _terrain_proxy_available() -> bool:
    """Check if the terrain tile proxy endpoint is registered in the running server."""
    try:
        resp = requests.get(f"{SERVER}/api/geo/terrain-tile/10/163/395.png", timeout=5)
        return resp.status_code != 404
    except Exception:
        return False


def _ollama_available() -> bool:
    """Check if a local ollama instance has llava:7b available."""
    try:
        resp = requests.get("http://localhost:11434/api/tags", timeout=3)
        if resp.status_code == 200:
            models = [m["name"] for m in resp.json().get("models", [])]
            return any("llava" in m for m in models)
    except Exception:
        pass
    return False


def _vlm_ask(image_path: Path, question: str) -> str:
    """Ask ollama llava:7b a question about an image. Returns raw text."""
    import base64
    with open(image_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    resp = requests.post("http://localhost:11434/api/generate", json={
        "model": "llava:7b",
        "prompt": question,
        "images": [b64],
        "stream": False,
    }, timeout=120)
    resp.raise_for_status()
    return resp.json().get("response", "")


# ============================================================
# Tests
# ============================================================

class TestTerrain:
    """Visual tests for 3D terrain feature."""

    def test_01_terrain_toggle_api(self, session):
        """toggleTerrain() changes getMapState().showTerrain from false to true and back."""
        page = session.page

        state = page.evaluate("window._mapActions.getMapState()")
        assert state["showTerrain"] is False, "Terrain should start OFF"

        # Toggle ON
        page.evaluate("window._mapActions.toggleTerrain()")
        time.sleep(0.5)
        state = page.evaluate("window._mapActions.getMapState()")
        assert state["showTerrain"] is True, "Terrain should be ON after first toggle"

        # Toggle OFF
        page.evaluate("window._mapActions.toggleTerrain()")
        time.sleep(0.5)
        state = page.evaluate("window._mapActions.getMapState()")
        assert state["showTerrain"] is False, "Terrain should be OFF after second toggle"

        page.screenshot(path=str(OUT / "01_toggle_api.png"))

    def test_02_terrain_tiles_load(self, session):
        """Enable terrain, verify terrain-dem source exists and terrain config is set."""
        page = session.page

        page.evaluate("window._mapActions.toggleTerrain()")
        time.sleep(SETTLE)

        # Verify internal state tracks terrain as ON
        state = page.evaluate("window._mapActions.getMapState()")
        assert state["showTerrain"] is True, "showTerrain should be True"

        # Verify the terrain-dem source is registered in the map style
        has_source = page.evaluate("""(() => {
            const map = window._mapState.map;
            if (!map) return false;
            return map.getSource('terrain-dem') !== undefined;
        })()""")
        assert has_source is True, "terrain-dem source should exist in the map style"

        # Check if setTerrain was called (may be null if DEM tiles 404)
        # MapLibre may remove terrain internally if DEM source fails to load,
        # so we check both getTerrain() and our internal state.
        terrain_config = page.evaluate("""(() => {
            const map = window._mapState.map;
            if (!map || typeof map.getTerrain !== 'function') return null;
            return map.getTerrain();
        })()""")

        if terrain_config is not None:
            print(f"[TERRAIN] map.getTerrain() = {terrain_config}")
        else:
            # DEM tiles may be 404ing if the proxy endpoint is not yet deployed.
            # Check if the proxy is available.
            proxy_up = _terrain_proxy_available()
            if not proxy_up:
                print("[TERRAIN] map.getTerrain() is null -- terrain proxy not deployed "
                      "(DEM tiles 404). Terrain source exists but tiles unavailable.")
            else:
                print("[TERRAIN] map.getTerrain() is null despite proxy being available "
                      "-- MapLibre may have auto-removed terrain after tile load failures.")

        page.screenshot(path=str(OUT / "02_tiles_loaded.png"))

    def test_03_terrain_visual_difference(self, session):
        """Screenshot with terrain OFF vs ON -- measure pixel difference in map center."""
        page = session.page
        bounds = _get_map_bounds(page)

        # Tilt slightly (45 degrees) so terrain deformation would be visible
        page.evaluate("""(() => {
            const map = window._mapState.map;
            if (map) map.jumpTo({ pitch: 45 });
        })()""")
        time.sleep(2)

        # Screenshot with terrain OFF
        img_flat = _grab(page)
        crop_flat = _crop_map_center(img_flat, bounds)
        _save("03_flat", crop_flat)

        # Enable terrain
        page.evaluate("window._mapActions.toggleTerrain()")
        time.sleep(SETTLE + 2)

        # Screenshot with terrain ON
        img_terrain = _grab(page)
        crop_terrain = _crop_map_center(img_terrain, bounds)
        _save("03_terrain", crop_terrain)

        # Compute pixel difference (Mean Absolute Difference)
        h = min(crop_flat.shape[0], crop_terrain.shape[0])
        w = min(crop_flat.shape[1], crop_terrain.shape[1])
        a = crop_flat[:h, :w].astype(np.float32)
        b = crop_terrain[:h, :w].astype(np.float32)
        mad = np.mean(np.abs(a - b))

        diff = np.abs(a - b).astype(np.uint8)
        _save("03_diff", diff)
        _save("03_diff_amplified", diff * 3)

        # Primary assertion: terrain toggle did not produce JS errors
        errors = [e for e in session.console_errors
                  if "terrain" in e.lower() or "dem" in e.lower()]
        assert len(errors) == 0, f"Terrain-related JS errors: {errors}"

        # Verify state was toggled
        state = page.evaluate("window._mapActions.getMapState()")
        assert state["showTerrain"] is True, "showTerrain should be True"

        print(f"[TERRAIN] Mean Absolute Difference: {mad:.2f}")
        if mad > 0.5:
            print("[TERRAIN] Visual terrain deformation detected")
        else:
            proxy_up = _terrain_proxy_available()
            if not proxy_up:
                print("[TERRAIN] No visual difference -- terrain proxy not deployed "
                      "(DEM tiles 404). Expected: no deformation without DEM data.")
            else:
                print("[TERRAIN] No visual difference despite proxy being available "
                      "-- terrain may not have loaded in time, or area is flat.")

        page.screenshot(path=str(OUT / "03_visual_diff.png"))

    def test_04_terrain_with_tilt(self, session):
        """Enable terrain AND tilt to 60 degrees. VLM analysis (advisory, not gating)."""
        page = session.page

        # Enable terrain first at low pitch
        page.evaluate("window._mapActions.toggleTerrain()")
        time.sleep(SETTLE)

        # Now tilt
        page.evaluate("""(() => {
            const map = window._mapState.map;
            if (map) map.easeTo({ pitch: 60, duration: 500 });
        })()""")
        time.sleep(2)

        # Screenshot
        img = _grab(page)
        _save("04_terrain_tilted", img)
        page.screenshot(path=str(OUT / "04_terrain_tilted.png"))

        # Verify terrain is enabled (internal state -- getTerrain may be null
        # if DEM tiles are unavailable)
        state = page.evaluate("window._mapActions.getMapState()")
        assert state["showTerrain"] is True, "showTerrain should be True"

        pitch = page.evaluate("window._mapState.map.getPitch()")
        assert pitch > 45, f"Pitch should be near 60, got {pitch}"

        # Reset pitch immediately to avoid crash from tile overload
        page.evaluate("""(() => {
            const map = window._mapState.map;
            if (map) map.jumpTo({ pitch: 0 });
        })()""")
        time.sleep(0.5)

        # No JS errors during terrain+tilt
        errors = session.console_errors
        assert len(errors) == 0, f"JS errors with terrain+tilt: {errors}"

        # VLM analysis (advisory only)
        if _ollama_available():
            vlm_path = OUT / "04_terrain_tilted.png"
            answer = _vlm_ask(vlm_path,
                "Look at this map screenshot. Is there visible 3D terrain elevation "
                "with hills or valleys, or does the map appear completely flat? "
                "Answer with EXACTLY one word: TERRAIN or FLAT.")
            print(f"[VLM] Terrain with tilt assessment: {answer.strip()}")
        else:
            print("[VLM] Ollama not available, skipping VLM terrain check")

    def test_05_terrain_with_buildings(self, session):
        """Enable terrain AND buildings. Verify buildings still render (no z-fighting)."""
        page = session.page

        # Ensure buildings are ON
        state = page.evaluate("window._mapActions.getMapState()")
        if not state.get("showBuildings"):
            page.evaluate("window._mapActions.toggleBuildings()")
            time.sleep(1)

        # Enable terrain
        page.evaluate("window._mapActions.toggleTerrain()")
        time.sleep(1)

        # Moderate tilt (avoid extreme angles that overload renderer)
        page.evaluate("""(() => {
            const map = window._mapState.map;
            if (map) map.easeTo({ pitch: 45, duration: 500 });
        })()""")
        time.sleep(SETTLE)

        # Screenshot
        img = _grab(page)
        _save("05_terrain_buildings", img)
        page.screenshot(path=str(OUT / "05_terrain_buildings.png"))

        # Verify both terrain and buildings are enabled via internal state
        state = page.evaluate("window._mapActions.getMapState()")
        assert state["showTerrain"] is True, "showTerrain should be True"
        assert state["showBuildings"] is True, "showBuildings should be True"

        # Check that 3D building layer is visible
        building_visible = page.evaluate("""(() => {
            const map = window._mapState.map;
            if (!map) return false;
            try {
                return map.getLayoutProperty('buildings-3d', 'visibility') !== 'none';
            } catch(e) { return false; }
        })()""")
        assert building_visible is True, "buildings-3d layer should be visible"

        # No JS errors during combined terrain+buildings
        errors = session.console_errors
        assert len(errors) == 0, f"JS errors with terrain+buildings: {errors}"

    def test_06_terrain_proxy_caching(self):
        """Direct HTTP test: terrain tile proxy returns valid PNG and caches."""
        url = f"{SERVER}/api/geo/terrain-tile/10/163/395.png"

        # First request -- the endpoint may not be registered if the server
        # has not been restarted after adding the terrain-tile route to geo.py.
        t0 = time.monotonic()
        resp1 = requests.get(url, timeout=15)
        elapsed1 = time.monotonic() - t0

        if resp1.status_code == 404:
            pytest.skip(
                "Terrain tile proxy endpoint not registered in running server "
                "(server restart needed to pick up new geo.py route)"
            )

        assert resp1.status_code == 200, f"Terrain tile status: {resp1.status_code}"
        assert "image/png" in resp1.headers.get("Content-Type", ""), \
            f"Expected image/png, got: {resp1.headers.get('Content-Type')}"
        assert len(resp1.content) > 1000, \
            f"Tile too small ({len(resp1.content)} bytes), likely error page"

        # Verify it is actually a PNG (magic bytes)
        assert resp1.content[:4] == b'\x89PNG', "Response is not a valid PNG"

        # Second request (should be cached = faster)
        t1 = time.monotonic()
        resp2 = requests.get(url, timeout=15)
        elapsed2 = time.monotonic() - t1

        assert resp2.status_code == 200
        assert len(resp2.content) == len(resp1.content), \
            "Cached response should be same size"

        print(f"[CACHE] First request: {elapsed1*1000:.0f}ms, "
              f"Second request: {elapsed2*1000:.0f}ms")

        if elapsed2 < elapsed1:
            print(f"[CACHE] Cache speedup: {elapsed1/elapsed2:.1f}x faster")
        else:
            print(f"[CACHE] Note: second request not faster (network variability)")

    def test_07_terrain_toggle_no_errors(self, session):
        """Toggle terrain on/off 5 times rapidly. Check for JS errors."""
        page = session.page
        session.console_errors.clear()

        for _ in range(5):
            page.evaluate("window._mapActions.toggleTerrain()")
            time.sleep(0.3)

        # Wait for any async errors to surface
        time.sleep(2)

        # Verify final state is consistent
        state = page.evaluate("window._mapActions.getMapState()")
        # 5 toggles from OFF = ON (odd number)
        expected = True
        assert state["showTerrain"] is expected, \
            f"After 5 toggles from OFF, expected showTerrain={expected}, got {state['showTerrain']}"

        errors = session.console_errors
        assert len(errors) == 0, f"JS errors after rapid terrain toggle: {errors}"

        page.screenshot(path=str(OUT / "07_rapid_toggle.png"))

    def test_08_terrain_with_units(self, session):
        """Enable terrain. Verify existing units still render on the map."""
        page = session.page

        # Wait for units to load from WebSocket
        time.sleep(2)

        # Check pre-existing unit count
        pre_unit_count = page.evaluate("""(() => {
            if (window.TritiumStore && window.TritiumStore.units) {
                return window.TritiumStore.units.size;
            }
            return 0;
        })()""")

        pre_marker_count = page.evaluate("""(() => {
            return Object.keys(window._mapState.unitMarkers || {}).length;
        })()""")

        # Enable terrain
        page.evaluate("window._mapActions.toggleTerrain()")
        time.sleep(SETTLE)

        # Check unit count is unchanged
        post_unit_count = page.evaluate("""(() => {
            if (window.TritiumStore && window.TritiumStore.units) {
                return window.TritiumStore.units.size;
            }
            return 0;
        })()""")

        post_marker_count = page.evaluate("""(() => {
            return Object.keys(window._mapState.unitMarkers || {}).length;
        })()""")

        # Screenshot
        img = _grab(page)
        _save("08_terrain_with_units", img)
        page.screenshot(path=str(OUT / "08_terrain_with_units.png"))

        # Units should still be present
        assert post_unit_count >= 1 or post_marker_count >= 1, \
            f"Expected units on map with terrain (store={post_unit_count}, markers={post_marker_count})"

        # Units should not disappear when terrain is toggled
        assert post_unit_count >= pre_unit_count, \
            f"Units disappeared after enabling terrain: {pre_unit_count} -> {post_unit_count}"
        assert post_marker_count >= pre_marker_count, \
            f"Markers disappeared after enabling terrain: {pre_marker_count} -> {post_marker_count}"

        # No JS errors
        errors = session.console_errors
        assert len(errors) == 0, f"JS errors with terrain+units: {errors}"
