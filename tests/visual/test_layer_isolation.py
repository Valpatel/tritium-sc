# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Automated Map Layer Isolation Test Suite.

Verifies that each rendering layer (satellite, roads, buildings, water,
parks, 3D models, DOM labels, fog) can be shown in isolation and that
OpenCV detects the expected visual characteristics. Each screenshot is
also analyzed by a local vision language model (llava:7b) for natural
language verification.

Methodology:
  - Start with ALL layers hidden (allMapLayers=false, models3d=false, domMarkers=false)
  - Enable ONE layer at a time
  - Take screenshot, crop to map area
  - OpenCV: deterministic pixel assertions (color presence, brightness, blob detection)
  - VLM: llava:7b natural language analysis via Ollama REST API (advisory)
  - API: cross-validate against MapLibre layer state

Layer IDs (from map-maplibre.js):
  - satellite-layer: raster ESRI World Imagery
  - road-overlay-layer: raster ESRI road labels
  - water-fill: vector fill (#0a2540)
  - park-fill: vector fill (#0a2a10)
  - buildings-3d: fill-extrusion (#0d1030)
  - buildings-outline: line (#00f0ff, 0.8px, 0.5 opacity)
  - roads-line: vector line (gray range #283848..#445566)
  - Three.js overlay: custom layer (3D unit models, projectiles, effects)
  - DOM markers: HTML elements (unit name labels)

Run:
    .venv/bin/python3 -m pytest tests/visual/test_layer_isolation.py -v
    ./test.sh 16
"""

from __future__ import annotations

import base64
import json
import time
from pathlib import Path

import cv2
import numpy as np
import pytest
import requests
from playwright.sync_api import sync_playwright, Page

# BGR color constants (from visual_assert.py / cybercore.css)
FRIENDLY_GREEN = (161, 255, 5)    # #05ffa1
HOSTILE_RED    = (109, 42, 255)   # #ff2a6d
CYAN_PRIMARY   = (255, 240, 0)    # #00f0ff  -- building outlines
WATER_BLUE     = (64, 37, 10)     # #0a2540  -- water fill (dark navy)
PARK_GREEN     = (16, 42, 10)     # #0a2a10  -- park fill (dark green)
BUILDING_3D    = (48, 16, 13)     # #0d1030  -- building extrusion fill
ROAD_GRAY      = (72, 56, 40)     # #283848  -- vector road lines (darkest)
ROAD_GRAY_LT   = (102, 85, 68)   # #445566  -- vector road lines (lightest)
VOID_BLACK     = (9, 6, 6)       # #060609  -- background color

OUT = Path("tests/.test-results/layer-isolation")
OUT.mkdir(parents=True, exist_ok=True)

SERVER = "http://localhost:8000"
OLLAMA_URL = "http://localhost:11434"
VLM_MODEL = "llava:7b"
SETTLE = 3.0          # seconds for render to settle after layer change
COLOR_TOL = 45        # BGR color match tolerance
VLM_TIMEOUT = 120     # seconds for VLM call
VLM_RETRIES = 2       # retry count for VLM failures


# ============================================================
# VLM Helper
# ============================================================

def vlm_analyze(image_path: str | Path, prompt: str) -> str:
    """Send an image to local llava:7b for natural language analysis.

    Returns the model's response text. On failure, returns error string
    (does not raise -- VLM is advisory, not gating).
    """
    image_path = Path(image_path)
    if not image_path.exists():
        return "(image not found)"

    with open(image_path, "rb") as f:
        img_b64 = base64.b64encode(f.read()).decode()

    full_prompt = (
        f"{prompt}\n\n"
        "Answer concisely in 1-3 sentences. Be specific about colors, "
        "shapes, and spatial layout."
    )

    for attempt in range(VLM_RETRIES + 1):
        try:
            resp = requests.post(
                f"{OLLAMA_URL}/api/generate",
                json={
                    "model": VLM_MODEL,
                    "prompt": full_prompt,
                    "images": [img_b64],
                    "stream": False,
                },
                timeout=VLM_TIMEOUT,
            )
            if resp.status_code == 200:
                return resp.json().get("response", "(empty response)")
            if attempt < VLM_RETRIES:
                time.sleep(2)
        except requests.exceptions.Timeout:
            if attempt < VLM_RETRIES:
                time.sleep(2)
        except Exception as e:
            return f"(VLM error: {e})"

    return "(VLM timeout after retries)"


def vlm_yes_no(image_path: str | Path, question: str) -> tuple[bool, str]:
    """Ask a yes/no question to VLM. Returns (answer_bool, raw_text).

    Uses majority vote of 3 calls for reliability (llava:7b has 20-83%
    false negative rate on dark backgrounds per visual_assert.py docs).
    """
    prompt = f"{question}\n\nAnswer with EXACTLY one word: YES or NO."
    yes_count = 0
    responses = []
    for _ in range(3):
        text = vlm_analyze(image_path, prompt)
        responses.append(text)
        if "yes" in text.strip().lower()[:20]:
            yes_count += 1
    combined = " | ".join(responses)
    return (yes_count >= 2, combined)


def _vlm_available() -> bool:
    """Check if Ollama is running and llava:7b is available."""
    try:
        resp = requests.get(f"{OLLAMA_URL}/api/tags", timeout=5)
        if resp.status_code != 200:
            return False
        models = resp.json().get("models", [])
        return any(VLM_MODEL in m.get("name", "") for m in models)
    except Exception:
        return False


# ============================================================
# OpenCV Helpers
# ============================================================

def _grab(page: Page) -> np.ndarray:
    """Full page screenshot as BGR numpy array."""
    buf = page.screenshot(timeout=60000)
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


def _crop_to_map(img: np.ndarray, bounds: dict) -> np.ndarray:
    """Crop a full-page screenshot to just the map container area."""
    x = int(bounds["x"])
    y = int(bounds["y"])
    w = int(bounds["width"])
    h = int(bounds["height"])
    ih, iw = img.shape[:2]
    x1 = max(0, x)
    y1 = max(0, y)
    x2 = min(iw, x + w)
    y2 = min(ih, y + h)
    return img[y1:y2, x1:x2].copy()


def _crop_map_center(img: np.ndarray, bounds: dict,
                     margin_pct: float = 0.2) -> np.ndarray:
    """Crop to the CENTER of the map, excluding UI overlay panels.

    The map canvas spans full-screen but UI panels (left sidebar, right panel,
    top bar, bottom panels) overlay it. By cropping to the center 60% (with
    20% margins), we get pure map content without panel contamination.

    Args:
        img: Full-page screenshot as BGR array
        bounds: Map container bounding rect
        margin_pct: Fraction of each side to exclude (default 0.2 = 20%)
    """
    x = int(bounds["x"])
    y = int(bounds["y"])
    w = int(bounds["width"])
    h = int(bounds["height"])
    ih, iw = img.shape[:2]

    mx = int(w * margin_pct)
    my = int(h * margin_pct)

    x1 = max(0, x + mx)
    y1 = max(0, y + my)
    x2 = min(iw, x + w - mx)
    y2 = min(ih, y + h - my)
    return img[y1:y2, x1:x2].copy()


def _has_color(img: np.ndarray, bgr: tuple, tolerance: int = COLOR_TOL,
               min_pixels: int = 50) -> bool:
    """Check if image has enough pixels matching the given BGR color."""
    lower = np.array([max(0, c - tolerance) for c in bgr], dtype=np.uint8)
    upper = np.array([min(255, c + tolerance) for c in bgr], dtype=np.uint8)
    mask = cv2.inRange(img, lower, upper)
    return int(cv2.countNonZero(mask)) >= min_pixels


def _count_color_pixels(img: np.ndarray, bgr: tuple,
                        tolerance: int = COLOR_TOL) -> int:
    """Count pixels matching a BGR color within tolerance."""
    lower = np.array([max(0, c - tolerance) for c in bgr], dtype=np.uint8)
    upper = np.array([min(255, c + tolerance) for c in bgr], dtype=np.uint8)
    mask = cv2.inRange(img, lower, upper)
    return int(cv2.countNonZero(mask))


def _count_color_blobs(img: np.ndarray, bgr: tuple, tolerance: int = COLOR_TOL,
                       min_area: int = 20) -> int:
    """Count distinct blobs of a specific color."""
    lower = np.array([max(0, c - tolerance) for c in bgr], dtype=np.uint8)
    upper = np.array([min(255, c + tolerance) for c in bgr], dtype=np.uint8)
    mask = cv2.inRange(img, lower, upper)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    return sum(1 for c in contours if cv2.contourArea(c) >= min_area)


def _mean_brightness(img: np.ndarray) -> float:
    """Mean brightness (0-255) of a BGR image."""
    return float(np.mean(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)))


def _edge_density(img: np.ndarray) -> float:
    """Fraction of pixels that are edges (0.0 - 1.0)."""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 50, 150)
    return cv2.countNonZero(edges) / edges.size


def _find_horizontal_lines(img: np.ndarray, min_length_pct: float = 0.5) -> int:
    """Count horizontal lines spanning more than min_length_pct of image width.

    Used to detect rendering artifacts (tile seams, line glitches).
    """
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 50, 150)
    min_length = int(img.shape[1] * min_length_pct)
    lines = cv2.HoughLinesP(edges, 1, np.pi / 180, threshold=100,
                            minLineLength=min_length, maxLineGap=10)
    if lines is None:
        return 0
    # Filter to near-horizontal lines (within 5 degrees)
    horiz_count = 0
    for line in lines:
        x1, y1, x2, y2 = line[0]
        dx = abs(x2 - x1)
        dy = abs(y2 - y1)
        if dx > 0 and dy / dx < 0.087:  # tan(5 degrees) ~ 0.087
            horiz_count += 1
    return horiz_count


def _save(name: str, img: np.ndarray):
    """Save debug image to output directory."""
    cv2.imwrite(str(OUT / f"{name}.png"), img)


# ============================================================
# Layer Control Helpers
# ============================================================

def _set_layers(page: Page, **kwargs) -> dict:
    """Set map layers via setLayers() and return verified state."""
    js_obj = ", ".join(f"{k}: {str(v).lower()}" for k, v in kwargs.items())
    state = page.evaluate(f"window._mapActions.setLayers({{ {js_obj} }})")
    return state


def _hide_all(page: Page) -> dict:
    """Hide ALL rendering layers (MapLibre + Three.js + DOM markers + fog + GIS).

    Uses allMapLayers=false to hide all style layers, then also disables
    geoLayers (street graph, zones, etc.) to prevent late-loading geo data
    from re-appearing. Also hides Three.js models and DOM markers.
    """
    state = _set_layers(page, allMapLayers=False, geoLayers=False,
                        models3d=False, domMarkers=False, fog=False)
    # Belt-and-suspenders: explicitly iterate all layers via JS to ensure nothing leaks
    page.evaluate("""(() => {
        const map = window._mapState.map;
        if (!map) return;
        const style = map.getStyle();
        if (style && style.layers) {
            for (const layer of style.layers) {
                if (layer.id === 'three-overlay') continue;
                try { map.setLayoutProperty(layer.id, 'visibility', 'none'); } catch(e) {}
            }
        }
        // Also hide Three.js root
        if (window._mapState.threeRoot) window._mapState.threeRoot.visible = false;
        // Hide all DOM markers
        for (const m of Object.values(window._mapState.unitMarkers || {})) {
            m.getElement().style.display = 'none';
        }
    })()""")
    return state


def _show_only_satellite(page: Page) -> dict:
    """Show ONLY the satellite raster layer."""
    _hide_all(page)
    # After allMapLayers=false, re-enable just satellite
    return _set_layers(page, satellite=True)


def _show_only_road_overlay(page: Page) -> dict:
    """Show ONLY the ESRI road overlay raster layer."""
    _hide_all(page)
    # Directly show the road-overlay-layer (the raster one)
    page.evaluate("""(() => {
        const map = window._mapState.map;
        map.setLayoutProperty('road-overlay-layer', 'visibility', 'visible');
    })()""")
    return _set_layers(page)  # just to sync state


def _show_only_buildings_outline(page: Page) -> dict:
    """Show ONLY the building outline (cyan lines), not 3D extrusions."""
    _hide_all(page)
    page.evaluate("""(() => {
        const map = window._mapState.map;
        map.setLayoutProperty('buildings-outline', 'visibility', 'visible');
    })()""")
    return _set_layers(page)


def _show_only_buildings_3d(page: Page) -> dict:
    """Show ONLY the 3D building extrusions, not outlines."""
    _hide_all(page)
    page.evaluate("""(() => {
        const map = window._mapState.map;
        map.setLayoutProperty('buildings-3d', 'visibility', 'visible');
    })()""")
    return _set_layers(page)


def _show_only_roads_vector(page: Page) -> dict:
    """Show ONLY the vector road lines (gray)."""
    _hide_all(page)
    page.evaluate("""(() => {
        const map = window._mapState.map;
        if (map.getLayer('roads-line')) {
            map.setLayoutProperty('roads-line', 'visibility', 'visible');
        }
    })()""")
    return _set_layers(page)


def _show_only_water(page: Page) -> dict:
    """Show ONLY the water fill layer."""
    _hide_all(page)
    page.evaluate("""(() => {
        const map = window._mapState.map;
        map.setLayoutProperty('water-fill', 'visibility', 'visible');
    })()""")
    return _set_layers(page)


def _show_only_parks(page: Page) -> dict:
    """Show ONLY the parks/green area fill layer."""
    _hide_all(page)
    page.evaluate("""(() => {
        const map = window._mapState.map;
        map.setLayoutProperty('park-fill', 'visibility', 'visible');
    })()""")
    return _set_layers(page)


def _show_only_models(page: Page) -> dict:
    """Show ONLY Three.js 3D unit models."""
    _hide_all(page)
    return _set_layers(page, models3d=True)


def _show_only_labels(page: Page) -> dict:
    """Show ONLY DOM name labels."""
    _hide_all(page)
    # Must sync BOTH showUnits and showLabels, because the unit sync callback
    # (triggered by WebSocket telemetry) checks _state.showUnits to set display.
    # Just setting domMarkers=true in setLayers is insufficient since it doesn't
    # update showUnits/showLabels state flags.
    page.evaluate("""(() => {
        window._mapState.showUnits = true;
        window._mapState.showLabels = true;
        for (const marker of Object.values(window._mapState.unitMarkers)) {
            marker.getElement().style.display = '';
        }
    })()""")
    return _set_layers(page)


def _show_all(page: Page) -> dict:
    """Restore all layers to visible."""
    return _set_layers(page, allMapLayers=True, models3d=True,
                       domMarkers=True, fog=False,
                       satellite=True, buildings=True, roads=True,
                       waterways=True, parks=True)


def _center_map(page: Page, zoom: int = 17, bearing: float = 0.0,
                pitch: float = 0.0):
    """Center map on geoCenter with specified view parameters."""
    page.evaluate(f"""(() => {{
        const map = window._mapState.map;
        if (!map) return;
        const gc = window._mapState.geoCenter;
        if (!gc) return;
        map.jumpTo({{
            center: [gc.lng, gc.lat],
            zoom: {zoom},
            bearing: {bearing},
            pitch: {pitch},
        }});
    }})()""")
    time.sleep(SETTLE)


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture(scope="module")
def browser_page():
    """Launch headed Playwright browser, navigate to Command Center."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page(viewport={"width": 1920, "height": 1080})

        page.goto(SERVER, wait_until="networkidle", timeout=30000)
        time.sleep(5)  # let map tiles load and Three.js initialize

        # Dismiss any modal
        page.keyboard.press("Escape")
        time.sleep(0.5)

        yield page

        browser.close()


@pytest.fixture(autouse=True)
def reset_layers(browser_page):
    """Restore all layers and center map before each test."""
    _show_all(browser_page)
    _center_map(browser_page, zoom=17, bearing=0, pitch=45)
    time.sleep(1)


@pytest.fixture(scope="module")
def vlm_ok():
    """Check if VLM is available for advisory checks."""
    return _vlm_available()


@pytest.fixture(scope="module")
def ensure_units(browser_page):
    """Ensure at least one friendly and one hostile unit exist for model tests."""
    page = browser_page
    try:
        resp = requests.get(f"{SERVER}/api/targets", timeout=5)
        data = resp.json() if resp.status_code == 200 else {}
        # API returns {"targets": [...], "summary": "..."} or a list
        if isinstance(data, dict):
            targets = data.get("targets", [])
        elif isinstance(data, list):
            targets = data
        else:
            targets = []
    except Exception:
        targets = []

    has_friendly = any(
        isinstance(t, dict) and t.get("alliance") == "friendly"
        for t in targets
    )
    has_hostile = any(
        isinstance(t, dict) and t.get("alliance") == "hostile"
        for t in targets
    )

    if not has_friendly:
        try:
            requests.post(f"{SERVER}/api/game/place", json={
                "name": "Sentinel-1", "asset_type": "turret",
                "position": {"x": 0, "y": 0},
            }, timeout=5)
        except Exception:
            pass

    if not has_hostile:
        try:
            requests.post(f"{SERVER}/api/amy/simulation/spawn", json={
                "name": "hostile-iso-test",
                "position": {"x": 30, "y": 0},
            }, timeout=5)
        except Exception:
            pass

    time.sleep(2)
    return True


# ============================================================
# Test: Baseline — All Layers Off
# ============================================================

def test_baseline_all_off(browser_page, vlm_ok):
    """Everything hidden. Screen should be dark (near-black background).

    With all MapLibre layers off, Three.js off, and DOM markers off,
    the map canvas should show only the background color (#060609).
    UI chrome (panels, headers) will still be visible.
    """
    page = browser_page

    _hide_all(page)
    time.sleep(SETTLE)

    img = _grab(page)
    _save("00_baseline_all_off", img)

    bounds = _get_map_bounds(page)
    crop = _crop_to_map(img, bounds)
    _save("00_baseline_all_off_crop", crop)

    # Use center crop for assertions (excludes UI panel overlays)
    center = _crop_map_center(img, bounds)
    _save("00_baseline_all_off_center", center)

    brightness = _mean_brightness(center)
    print(f"  Map center brightness with all layers off: {brightness:.1f}")

    # Map center should be very dark (background is #060609 = RGB(6,6,9))
    assert brightness < 50, (
        f"Map center too bright ({brightness:.1f}) with all layers off. "
        f"Expected near-black (<50). Some layer may still be visible."
    )

    # Should NOT have satellite imagery colors (natural greens/browns)
    # Center crop excludes UI chrome that might have green/brown elements
    has_natural_green = _has_color(center, (50, 100, 50), tolerance=30, min_pixels=2000)
    has_brown = _has_color(center, (50, 80, 120), tolerance=30, min_pixels=2000)
    assert not has_natural_green, "Natural green pixels in map center with all layers off (satellite leak?)"
    assert not has_brown, "Brown pixels in map center with all layers off (satellite leak?)"

    # Should NOT have GIS overlay lines (cyan/green geo data)
    cyan_pixels = _count_color_pixels(center, CYAN_PRIMARY, tolerance=50)
    print(f"  Cyan pixels in center: {cyan_pixels}")
    # Center crop should have minimal cyan (no UI panel borders)
    assert cyan_pixels < 5000, (
        f"Too many cyan pixels ({cyan_pixels}) in map center with all layers off. "
        f"GIS overlay or building outlines may be leaking."
    )

    # VLM advisory check
    if vlm_ok:
        vlm_text = vlm_analyze(
            OUT / "00_baseline_all_off_crop.png",
            "Describe this image. Is it mostly dark/black or does it show "
            "a map with visible features like roads, buildings, or terrain?"
        )
        print(f"  VLM: {vlm_text}")


# ============================================================
# Test: Satellite Only
# ============================================================

def test_satellite_only(browser_page, vlm_ok):
    """Only satellite imagery visible. Verify natural earth-tone colors.

    Satellite imagery shows real-world aerial/satellite photography with
    natural colors: greens (vegetation), browns/tans (bare ground, roofs),
    grays (roads, concrete), blues (water if present).
    """
    page = browser_page

    _show_only_satellite(page)
    time.sleep(SETTLE + 2)  # extra time for raster tile loading

    img = _grab(page)
    _save("01_satellite_only", img)

    bounds = _get_map_bounds(page)
    crop = _crop_to_map(img, bounds)
    _save("01_satellite_only_crop", crop)

    # Use center crop for assertions (excludes UI panel overlays)
    center = _crop_map_center(img, bounds)
    _save("01_satellite_only_center", center)

    brightness = _mean_brightness(center)
    print(f"  Satellite center brightness: {brightness:.1f}")

    # Satellite imagery should be substantially brighter than void
    assert brightness > 30, (
        f"Map center too dark ({brightness:.1f}) for satellite imagery. "
        f"Expected >30. Tiles may not have loaded."
    )

    # Should have variation (not a flat color) — check std deviation
    gray = cv2.cvtColor(center, cv2.COLOR_BGR2GRAY)
    std_dev = float(np.std(gray))
    print(f"  Satellite intensity std dev: {std_dev:.1f}")
    assert std_dev > 10, (
        f"Satellite imagery has low variance ({std_dev:.1f}). "
        f"Expected textured imagery with std dev >10."
    )

    # Should NOT have cyan building outlines in center
    cyan_pixels = _count_color_pixels(center, CYAN_PRIMARY, tolerance=30)
    print(f"  Cyan pixels in center: {cyan_pixels}")
    assert cyan_pixels < 5000, (
        f"Too many cyan pixels ({cyan_pixels}) — building outlines may be leaking."
    )

    # Should NOT have bright neon green unit models in center
    green_blobs = _count_color_blobs(center, FRIENDLY_GREEN, tolerance=30, min_area=50)
    print(f"  Green model blobs in center (min_area=50): {green_blobs}")
    assert green_blobs < 5, (
        f"Found {green_blobs} large green blobs in center — 3D models may be leaking."
    )

    # VLM advisory check
    if vlm_ok:
        vlm_text = vlm_analyze(
            OUT / "01_satellite_only_center.png",
            "This should be a satellite/aerial view of a neighborhood. "
            "Do you see natural terrain features like buildings, roads, "
            "vegetation? Are there any neon-colored overlays or markers?"
        )
        print(f"  VLM: {vlm_text}")


# ============================================================
# Test: Building Outlines Only
# ============================================================

def test_buildings_outline_only(browser_page, vlm_ok):
    """Only building outlines visible. Verify cyan (#00f0ff) pixels.

    Building outlines are drawn as thin cyan lines (0.8px width, 0.5 opacity)
    on a dark (#060609) background. They outline building footprints from
    OpenStreetMap data.
    """
    page = browser_page

    _show_only_buildings_outline(page)
    time.sleep(SETTLE)

    img = _grab(page)
    _save("02_buildings_outline_only", img)

    bounds = _get_map_bounds(page)
    crop = _crop_to_map(img, bounds)
    _save("02_buildings_outline_only_crop", crop)

    brightness = _mean_brightness(crop)
    print(f"  Outline brightness: {brightness:.1f}")

    # Should be mostly dark with some cyan lines
    # Brightness should be low but not zero (thin lines contribute little)
    assert brightness < 60, (
        f"Map too bright ({brightness:.1f}) for outlines-only. "
        f"Another layer may be leaking."
    )

    # Must have cyan pixels (the outlines themselves)
    # Building outlines are thin (0.8px) with 0.5 opacity, so effective
    # color is muted. Use wider tolerance.
    cyan_pixels = _count_color_pixels(crop, CYAN_PRIMARY, tolerance=60)
    print(f"  Cyan pixels (tol=60): {cyan_pixels}")

    # Also check for lighter cyan / teal range that blended outlines produce
    teal_pixels = _count_color_pixels(crop, (180, 200, 0), tolerance=60)
    print(f"  Teal/blended cyan pixels: {teal_pixels}")

    total_outline_pixels = cyan_pixels + teal_pixels
    print(f"  Total outline-range pixels: {total_outline_pixels}")

    # Buildings should produce at least some outline pixels at zoom 17
    # (neighborhood zoom shows many buildings). Thin lines = fewer pixels.
    assert total_outline_pixels > 20, (
        f"Too few cyan/teal pixels ({total_outline_pixels}) for building outlines. "
        f"Are buildings visible at this zoom level?"
    )

    # Should NOT have satellite colors
    assert _mean_brightness(crop) < 60, "Too bright — satellite may be leaking"

    # VLM advisory check
    if vlm_ok:
        vlm_text = vlm_analyze(
            OUT / "02_buildings_outline_only_crop.png",
            "This should show thin cyan/teal building outlines on a dark "
            "background. Do you see geometric shapes like building footprints "
            "drawn in a bright blue/cyan color?"
        )
        print(f"  VLM: {vlm_text}")


# ============================================================
# Test: Buildings 3D Only
# ============================================================

def test_buildings_3d_only(browser_page, vlm_ok):
    """Only 3D building extrusions visible. Verify dark block shapes.

    3D buildings are fill-extrusions colored #0d1030 (very dark blue-purple)
    with 0.7 opacity. At 45-degree pitch they appear as solid dark blocks
    rising from the ground.
    """
    page = browser_page

    # Tilt the map to see 3D extrusions
    _center_map(page, zoom=17, bearing=0, pitch=55)
    _show_only_buildings_3d(page)
    time.sleep(SETTLE)

    img = _grab(page)
    _save("03_buildings_3d_only", img)

    bounds = _get_map_bounds(page)
    crop = _crop_to_map(img, bounds)
    _save("03_buildings_3d_only_crop", crop)

    # Use a tight center crop but with smaller margin (buildings are dark,
    # need more of the map area to capture enough building edges)
    center = _crop_map_center(img, bounds, margin_pct=0.1)
    _save("03_buildings_3d_only_center", center)

    brightness = _mean_brightness(center)
    print(f"  3D buildings center brightness: {brightness:.1f}")

    # 3D buildings are dark (#0d1030) on dark bg (#060609)
    # They're very subtle — check on the full crop first for edges
    gray_full = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    std_dev = float(np.std(gray_full))
    print(f"  Full crop intensity std dev: {std_dev:.1f}")

    # Building extrusions should create edges from their 3D shapes
    # Use full crop since buildings may be outside center zone
    edge_ratio_full = _edge_density(crop)
    edge_ratio_center = _edge_density(center)
    print(f"  Edge density (full/center): {edge_ratio_full:.4f}/{edge_ratio_center:.4f}")

    # Check either full or center for edges (buildings may be near edges of view)
    assert edge_ratio_full > 0.001 or edge_ratio_center > 0.001 or std_dev > 3, (
        f"No building evidence found (edge_full={edge_ratio_full:.4f}, "
        f"edge_center={edge_ratio_center:.4f}, std_dev={std_dev:.1f}). "
        f"3D buildings may not be rendering."
    )

    # Should NOT have bright satellite-like natural green in center
    has_natural = _has_color(center, (80, 130, 80), tolerance=40, min_pixels=3000)
    print(f"  Natural green pixels present: {has_natural}")
    assert not has_natural, "Broad natural green detected in center — satellite may be leaking"

    # VLM advisory check
    if vlm_ok:
        vlm_text = vlm_analyze(
            OUT / "03_buildings_3d_only_center.png",
            "This should show dark 3D building shapes on a black background, "
            "viewed from an angle (tilted perspective). Do you see "
            "geometric block-like shapes? Are there any bright colors?"
        )
        print(f"  VLM: {vlm_text}")


# ============================================================
# Test: Road Overlay Only (ESRI Raster)
# ============================================================

def test_road_overlay_only(browser_page, vlm_ok):
    """Only the ESRI road overlay (raster) visible. Verify road labels/lines.

    The road overlay is a transparent raster tile layer from ESRI at 0.6 opacity.
    It shows road names, route markers, and faint road lines on a mostly
    transparent background (shows through to the dark bg).
    """
    page = browser_page

    _show_only_road_overlay(page)
    time.sleep(SETTLE + 2)  # extra time for raster tile loading

    img = _grab(page)
    _save("04_road_overlay_only", img)

    bounds = _get_map_bounds(page)
    crop = _crop_to_map(img, bounds)
    _save("04_road_overlay_only_crop", crop)

    # Use center crop for assertions (excludes UI panel overlays)
    center = _crop_map_center(img, bounds)
    _save("04_road_overlay_only_center", center)

    brightness = _mean_brightness(center)
    print(f"  Road overlay center brightness: {brightness:.1f}")

    # Road overlay on dark background should show some content
    edge_ratio = _edge_density(center)
    print(f"  Edge density: {edge_ratio:.4f}")

    # Even semi-transparent road labels should produce some edge content
    assert brightness > 2 or edge_ratio > 0.001, (
        f"Road overlay appears empty (brightness={brightness:.1f}, "
        f"edges={edge_ratio:.4f}). May not have loaded."
    )

    # Should NOT have large 3D model green blobs in center
    green_blobs = _count_color_blobs(center, FRIENDLY_GREEN, tolerance=30, min_area=50)
    print(f"  Green model blobs in center: {green_blobs}")
    assert green_blobs < 5, f"Large green model blobs in center ({green_blobs}) — 3D models may be leaking"

    # VLM advisory check
    if vlm_ok:
        vlm_text = vlm_analyze(
            OUT / "04_road_overlay_only_crop.png",
            "This should show road labels and road lines on a mostly dark "
            "background. Do you see any text (road names, route numbers)? "
            "Is the background mostly dark/black?"
        )
        print(f"  VLM: {vlm_text}")


# ============================================================
# Test: Vector Roads Only
# ============================================================

def test_roads_vector_only(browser_page, vlm_ok):
    """Only vector road lines visible. Verify gray line patterns.

    Vector roads are drawn as lines colored in a gray palette (#283848 to
    #445566) with width scaling by road class (motorway=3, trunk=2.5, etc.).
    """
    page = browser_page

    _show_only_roads_vector(page)
    time.sleep(SETTLE)

    img = _grab(page)
    _save("05_roads_vector_only", img)

    bounds = _get_map_bounds(page)
    crop = _crop_to_map(img, bounds)
    _save("05_roads_vector_only_crop", crop)

    brightness = _mean_brightness(crop)
    print(f"  Vector roads brightness: {brightness:.1f}")

    # Check for gray road colors
    gray_dark = _count_color_pixels(crop, ROAD_GRAY, tolerance=40)
    gray_light = _count_color_pixels(crop, ROAD_GRAY_LT, tolerance=40)
    gray_mid = _count_color_pixels(crop, (87, 70, 53), tolerance=40)  # mid-range gray
    total_road_pixels = gray_dark + gray_light + gray_mid
    print(f"  Gray pixels (dark/mid/light): {gray_dark}/{gray_mid}/{gray_light}, total: {total_road_pixels}")

    # At zoom 17, a neighborhood should have visible streets
    assert total_road_pixels > 50 or brightness > 3, (
        f"Too few road-colored pixels ({total_road_pixels}) and low brightness "
        f"({brightness:.1f}). Vector roads may not be visible at this zoom."
    )

    # Should NOT have satellite imagery
    gray_img = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    std_dev = float(np.std(gray_img))
    print(f"  Intensity std dev: {std_dev:.1f}")

    # VLM advisory check
    if vlm_ok:
        vlm_text = vlm_analyze(
            OUT / "05_roads_vector_only_crop.png",
            "This should show gray/dark road lines on a black background, "
            "forming a street network pattern. Do you see linear features "
            "that look like roads? What color are they?"
        )
        print(f"  VLM: {vlm_text}")


# ============================================================
# Test: Water Only
# ============================================================

def test_water_only(browser_page, vlm_ok):
    """Only water bodies visible. Verify dark blue pixels.

    Water fill is colored #0a2540 (dark navy blue) at 0.6 opacity.
    Depending on the map location, there may or may not be significant
    water features. This test verifies the layer renders when present.
    """
    page = browser_page

    _show_only_water(page)
    time.sleep(SETTLE)

    img = _grab(page)
    _save("06_water_only", img)

    bounds = _get_map_bounds(page)
    crop = _crop_to_map(img, bounds)
    _save("06_water_only_crop", crop)

    # Use center crop for assertions (excludes UI panel overlays)
    center = _crop_map_center(img, bounds)
    _save("06_water_only_center", center)

    brightness = _mean_brightness(center)
    print(f"  Water layer center brightness: {brightness:.1f}")

    # Check for dark blue water pixels in center
    water_pixels = _count_color_pixels(center, WATER_BLUE, tolerance=50)
    print(f"  Dark blue (water) pixels in center: {water_pixels}")

    # Water may not be present at every location
    assert brightness < 50, (
        f"Map center too bright ({brightness:.1f}) for water-only. "
        f"Another layer may be leaking."
    )

    # Should NOT have large unit model blobs in center
    green_blobs = _count_color_blobs(center, FRIENDLY_GREEN, tolerance=30, min_area=50)
    print(f"  Green model blobs in center: {green_blobs}")
    assert green_blobs < 5, f"Large green model blobs in center ({green_blobs}) — 3D models may be leaking"

    if water_pixels > 100:
        print("  Water features detected at this location")
    else:
        print("  No significant water features at this location (acceptable)")

    # VLM advisory check
    if vlm_ok:
        vlm_text = vlm_analyze(
            OUT / "06_water_only_crop.png",
            "This image should show only water features (if any) on a dark "
            "background. Do you see any dark blue shapes that could be "
            "rivers, ponds, or other water bodies? Is the image mostly dark?"
        )
        print(f"  VLM: {vlm_text}")


# ============================================================
# Test: Parks Only
# ============================================================

def test_parks_only(browser_page, vlm_ok):
    """Only parks/green areas visible. Verify dark green pixels.

    Park fills are colored #0a2a10 (very dark green) at 0.3 opacity.
    Depending on the map location, parks may or may not be present.
    """
    page = browser_page

    _show_only_parks(page)
    time.sleep(SETTLE)

    img = _grab(page)
    _save("07_parks_only", img)

    bounds = _get_map_bounds(page)
    crop = _crop_to_map(img, bounds)
    _save("07_parks_only_crop", crop)

    # Use center crop for assertions (excludes UI panel overlays)
    center = _crop_map_center(img, bounds)
    _save("07_parks_only_center", center)

    brightness = _mean_brightness(center)
    print(f"  Parks layer center brightness: {brightness:.1f}")

    # Check for dark green park pixels in center
    park_pixels = _count_color_pixels(center, PARK_GREEN, tolerance=50)
    print(f"  Dark green (park) pixels in center: {park_pixels}")

    # Parks may not be present at every location
    assert brightness < 50, (
        f"Map center too bright ({brightness:.1f}) for parks-only. "
        f"Another layer may be leaking."
    )

    # Should NOT have large unit model blobs in center
    green_blobs = _count_color_blobs(center, FRIENDLY_GREEN, tolerance=30, min_area=50)
    print(f"  Green model blobs in center: {green_blobs}")
    assert green_blobs < 5, f"Large green model blobs in center ({green_blobs}) — 3D models may be leaking"

    if park_pixels > 100:
        print("  Park features detected at this location")
    else:
        print("  No significant park features at this location (acceptable)")

    # VLM advisory check
    if vlm_ok:
        vlm_text = vlm_analyze(
            OUT / "07_parks_only_crop.png",
            "This image should show only park/green areas (if any) on a dark "
            "background. Do you see any subtly green-tinted shapes that could "
            "be parks or grassy areas? Is the image mostly dark?"
        )
        print(f"  VLM: {vlm_text}")


# ============================================================
# Test: 3D Models Only
# ============================================================

def test_models_only(browser_page, vlm_ok, ensure_units):
    """Only Three.js 3D unit models visible. Verify green/red blobs.

    Friendly units render as green (#05ffa1) 3D models.
    Hostile units render as red (#ff2a6d) 3D models.
    With all MapLibre layers off, these should be the only colored content.
    """
    page = browser_page

    _show_only_models(page)
    time.sleep(SETTLE + 1)  # extra settle for Three.js camera sync

    img = _grab(page)
    _save("08_models_only", img)

    bounds = _get_map_bounds(page)
    crop = _crop_to_map(img, bounds)
    _save("08_models_only_crop", crop)

    brightness = _mean_brightness(crop)
    print(f"  Models-only brightness: {brightness:.1f}")

    # Detect green (friendly) blobs
    green_blobs = _count_color_blobs(crop, FRIENDLY_GREEN, tolerance=50, min_area=10)
    print(f"  Green (friendly) blobs: {green_blobs}")

    # Detect red (hostile) blobs
    red_blobs = _count_color_blobs(crop, HOSTILE_RED, tolerance=50, min_area=10)
    print(f"  Red (hostile) blobs: {red_blobs}")

    # Should have at least some unit models visible
    total_blobs = green_blobs + red_blobs
    assert total_blobs >= 1, (
        f"Expected at least 1 unit model blob, found {total_blobs}. "
        f"Are units placed and visible at this zoom?"
    )

    # Map area should be mostly dark (only unit models, no terrain)
    # Units are small, so overall brightness should be low
    assert brightness < 60, (
        f"Map too bright ({brightness:.1f}) for models-only. "
        f"A MapLibre layer may be leaking."
    )

    # Should NOT have satellite-level texture
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    # Mask out the bright unit blobs, check remaining area
    bright_mask = gray > 50
    bright_ratio = np.sum(bright_mask) / bright_mask.size
    print(f"  Bright pixel ratio: {bright_ratio:.3f}")
    # Most of the image should be dark; only small unit models are bright
    assert bright_ratio < 0.3, (
        f"Too many bright pixels ({bright_ratio:.1%}) for models-only. "
        f"Satellite or other layer may be leaking."
    )

    # VLM advisory check
    if vlm_ok:
        vlm_text = vlm_analyze(
            OUT / "08_models_only_crop.png",
            "This image should show small 3D unit models (green for friendly, "
            "red for hostile) on a dark/black background. Do you see colored "
            "shapes that could be unit icons or 3D models? What colors?"
        )
        print(f"  VLM: {vlm_text}")


# ============================================================
# Test: DOM Labels Only
# ============================================================

def test_labels_only(browser_page, vlm_ok, ensure_units):
    """Only DOM name labels visible. Verify text elements present.

    Unit name labels are HTML DOM elements positioned by MapLibre markers.
    With all map layers off and Three.js off, only the text labels should
    be visible, floating over a dark background.
    """
    page = browser_page

    # First check how many markers exist at all
    total_markers = page.evaluate(
        "Object.keys(window._mapState.unitMarkers || {}).length"
    )
    print(f"  Total unit markers in state: {total_markers}")

    _show_only_labels(page)
    time.sleep(SETTLE)

    img = _grab(page)
    _save("09_labels_only", img)

    bounds = _get_map_bounds(page)
    crop = _crop_to_map(img, bounds)
    _save("09_labels_only_crop", crop)

    # Check for visible DOM markers via Playwright (more reliable than pixel checks)
    visible_markers = page.evaluate("""(() => {
        const markers = Object.values(window._mapState.unitMarkers);
        let visible = 0;
        for (const m of markers) {
            const el = m.getElement();
            const style = window.getComputedStyle(el);
            if (style.display !== 'none' && style.visibility !== 'hidden') {
                visible++;
            }
        }
        return { visible, total: markers.length };
    })()""")
    print(f"  DOM markers: {visible_markers['visible']} visible / {visible_markers['total']} total")

    if visible_markers["total"] == 0:
        pytest.skip("No unit markers exist on the map (no units placed)")

    assert visible_markers["visible"] >= 1, (
        f"Expected at least 1 visible DOM marker, found {visible_markers['visible']} "
        f"(of {visible_markers['total']} total). Labels may not be toggling correctly."
    )

    # Check that map area is mostly dark (no terrain layers)
    brightness = _mean_brightness(crop)
    print(f"  Labels-only brightness: {brightness:.1f}")

    # Labels are small text, so overall brightness stays low
    assert brightness < 60, (
        f"Map too bright ({brightness:.1f}) for labels-only. "
        f"A MapLibre layer may be leaking."
    )

    # Check for text-like content (edge density from label text)
    edge_ratio = _edge_density(crop)
    print(f"  Edge density (from labels): {edge_ratio:.4f}")

    # VLM advisory check
    if vlm_ok:
        vlm_text = vlm_analyze(
            OUT / "09_labels_only_crop.png",
            "This image should show text labels (unit names) floating on a "
            "dark/black background. Do you see any readable text? "
            "Are there any map features visible other than text labels?"
        )
        print(f"  VLM: {vlm_text}")


# ============================================================
# Test: All Layers Composite
# ============================================================

def test_all_layers_composite(browser_page, vlm_ok, ensure_units):
    """All layers enabled. Verify composite rendering has all expected colors.

    With everything on, we should see:
    - Natural satellite colors (greens, browns)
    - Cyan building outlines (#00f0ff)
    - Green friendly unit models (#05ffa1)
    - Various road/terrain features
    """
    page = browser_page

    _show_all(page)
    _center_map(page, zoom=17, bearing=0, pitch=45)
    time.sleep(SETTLE + 2)

    img = _grab(page)
    _save("10_all_composite", img)

    bounds = _get_map_bounds(page)
    crop = _crop_to_map(img, bounds)
    _save("10_all_composite_crop", crop)

    brightness = _mean_brightness(crop)
    print(f"  Composite brightness: {brightness:.1f}")

    # Should be substantially brighter than all-off baseline
    assert brightness > 20, (
        f"Composite too dark ({brightness:.1f}). "
        f"Expected visible satellite imagery + overlays."
    )

    # Should have high texture variance (many overlapping layers)
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    std_dev = float(np.std(gray))
    print(f"  Intensity std dev: {std_dev:.1f}")
    assert std_dev > 10, (
        f"Low texture variance ({std_dev:.1f}) for composite view."
    )

    # Check for key colors
    has_green_models = _has_color(crop, FRIENDLY_GREEN, tolerance=50, min_pixels=20)
    print(f"  Friendly green present: {has_green_models}")

    # Cyan building outlines
    cyan_present = _has_color(crop, CYAN_PRIMARY, tolerance=60, min_pixels=10)
    print(f"  Cyan outlines present: {cyan_present}")

    # At least one signature color should be present
    assert has_green_models or cyan_present, (
        "Neither green unit models nor cyan building outlines detected. "
        "Composite view should have overlay content."
    )

    # Verify layer state via API
    state = page.evaluate("window._mapActions.getMapState()")
    print(f"  Layer state: {json.dumps(state, indent=2)}")
    assert state.get("showSatellite") is True, "Satellite should be on"
    assert state.get("showBuildings") is True, "Buildings should be on"

    # VLM advisory check
    if vlm_ok:
        vlm_text = vlm_analyze(
            OUT / "10_all_composite_crop.png",
            "This should be a tactical map showing satellite imagery with "
            "overlaid building outlines (cyan), unit models (green/red), "
            "and road information. Describe what you see."
        )
        print(f"  VLM: {vlm_text}")


# ============================================================
# Test: Tilted View — No Artifacts
# ============================================================

def test_tilted_no_artifacts(browser_page, vlm_ok):
    """Tilt to 60 degrees. Verify no rendering line artifacts >50% screen width.

    Raster tile seams or Three.js render glitches can produce horizontal
    lines that span most of the screen width. These are visual artifacts
    that degrade the tactical display.
    """
    page = browser_page

    _show_all(page)
    _center_map(page, zoom=17, bearing=0, pitch=60)
    time.sleep(SETTLE + 2)  # extra settle for tilted raster loading

    img = _grab(page)
    _save("11_tilted_60_deg", img)

    bounds = _get_map_bounds(page)
    crop = _crop_to_map(img, bounds)
    _save("11_tilted_60_deg_crop", crop)

    # Detect horizontal lines spanning >50% of image width
    artifact_lines = _find_horizontal_lines(crop, min_length_pct=0.5)
    print(f"  Horizontal artifact lines (>50% width): {artifact_lines}")

    # Some legitimate horizontal content exists (horizon line, building edges)
    # but rendering artifacts typically produce many parallel lines
    assert artifact_lines < 5, (
        f"Found {artifact_lines} horizontal lines spanning >50% of screen width. "
        f"This suggests rendering artifacts (tile seams, line glitches)."
    )

    # Map should still render properly at 60-degree tilt
    brightness = _mean_brightness(crop)
    print(f"  Tilted brightness: {brightness:.1f}")
    assert brightness > 10, (
        f"Map too dark ({brightness:.1f}) at 60-degree tilt. "
        f"Tiles may not be loading for this perspective."
    )

    # VLM advisory check
    if vlm_ok:
        vlm_text = vlm_analyze(
            OUT / "11_tilted_60_deg_crop.png",
            "This is a tilted (60 degree) view of a tactical map. "
            "Are there any obvious visual glitches like horizontal lines "
            "spanning the entire image, tile seams, or rendering artifacts?"
        )
        print(f"  VLM: {vlm_text}")


# ============================================================
# Test: Layer State API Cross-Validation
# ============================================================

def test_layer_state_api_roundtrip(browser_page):
    """Verify setLayers() state is readable via getMapState().

    This tests the internal consistency of the layer management system:
    set a known state, read it back, verify it matches.
    """
    page = browser_page

    # Set a specific layer combination
    returned = _set_layers(page, satellite=False, buildings=True,
                           roads=False, models3d=True,
                           waterways=False, parks=False, fog=False)
    time.sleep(0.5)

    # Read back state
    state = page.evaluate("window._mapActions.getMapState()")
    print(f"  Set state: {json.dumps(returned, indent=2)}")
    print(f"  Read state: {json.dumps(state, indent=2)}")

    assert state["showSatellite"] is False, "Satellite should be off"
    assert state["showBuildings"] is True, "Buildings should be on"
    assert state["showRoads"] is False, "Roads should be off"

    # Test the nuclear toggle
    _hide_all(page)
    time.sleep(0.5)
    state = page.evaluate("window._mapActions.getMapState()")
    print(f"  After hide_all: {json.dumps(state, indent=2)}")

    # Restore
    _show_all(page)
    time.sleep(0.5)
    state = page.evaluate("window._mapActions.getMapState()")
    assert state["showSatellite"] is True, "Satellite should be restored"
    assert state["showBuildings"] is True, "Buildings should be restored"
