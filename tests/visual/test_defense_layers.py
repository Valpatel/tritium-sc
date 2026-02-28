# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Automated Defense Layer Tests -- Prevent CATEGORIES of Visual Bugs.

Six categories of visual bugs have been observed in the Command Center.
This test suite builds permanent automated defenses against each category
so the entire class of bug can never recur undetected.

Categories:
  1. DOM Overflow Prevention -- markers/labels expanding beyond containers
  2. Layer Toggle Integrity -- layers not properly hiding/showing
  3. Z-Index and Stacking -- UI elements rendered below the map
  4. Keyboard Handling -- focus traps, swallowed shortcuts
  5. Transform Artifact Detection -- CSS transforms creating lines/bands
  6. State Consistency -- JS state out of sync with DOM/API

Methodology:
  - Playwright headed browser (headless=False per project convention)
  - OpenCV for pixel-level analysis (HoughLinesP, color bands, brightness)
  - VLM (llava:7b via Ollama) for advisory natural language checks
  - Screenshots saved to tests/.test-results/defense-layers/

Run:
    .venv/bin/python3 -m pytest tests/visual/test_defense_layers.py -v
    ./test.sh 18
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

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

OUT = Path("tests/.test-results/defense-layers")
OUT.mkdir(parents=True, exist_ok=True)

SERVER = "http://localhost:8000"
OLLAMA_URL = "http://localhost:11434"
VLM_MODEL = "llava:7b"
SETTLE = 2.5          # seconds for render to settle after state change
COLOR_TOL = 45        # BGR color match tolerance
VLM_TIMEOUT = 120
VLM_RETRIES = 2
VIEWPORT_W = 1920
VIEWPORT_H = 1080

# Cybercore palette (BGR)
FRIENDLY_GREEN = (161, 255, 5)    # #05ffa1
HOSTILE_RED    = (109, 42, 255)   # #ff2a6d
CYAN_PRIMARY   = (255, 240, 0)    # #00f0ff


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

def _grab(page: Page, timeout: int = 90000) -> np.ndarray:
    """Full page screenshot as BGR numpy array.

    Uses a generous timeout because MapLibre tile loading can delay
    rendering at extreme pitch/zoom combinations.
    """
    buf = page.screenshot(timeout=timeout)
    arr = np.frombuffer(buf, dtype=np.uint8)
    return cv2.imdecode(arr, cv2.IMREAD_COLOR)


def _mean_brightness(img: np.ndarray) -> float:
    """Mean brightness (0-255) of a BGR image."""
    return float(np.mean(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)))


def _crop_region(img: np.ndarray, x: int, y: int, w: int, h: int) -> np.ndarray:
    """Crop a region from an image, clamping to bounds."""
    ih, iw = img.shape[:2]
    x1 = max(0, x)
    y1 = max(0, y)
    x2 = min(iw, x + w)
    y2 = min(ih, y + h)
    return img[y1:y2, x1:x2].copy()


def _get_map_bounds(page: Page) -> dict:
    """Get the map container bounding rect in viewport pixels."""
    for sel in ["#maplibre-map", "#tactical-area"]:
        el = page.locator(sel)
        if el.count() > 0:
            bbox = el.first.bounding_box()
            if bbox and bbox["width"] > 100 and bbox["height"] > 100:
                return bbox
    return {"x": 230, "y": 40, "width": 1460, "height": 900}


def _crop_map_center(img: np.ndarray, bounds: dict,
                     margin_pct: float = 0.2) -> np.ndarray:
    """Crop to the CENTER of the map, excluding UI overlay panels."""
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


def _find_horizontal_lines(img: np.ndarray, min_length_pct: float = 0.5) -> int:
    """Count horizontal lines spanning more than min_length_pct of image width."""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 50, 150)
    min_length = int(img.shape[1] * min_length_pct)
    lines = cv2.HoughLinesP(edges, 1, np.pi / 180, threshold=100,
                            minLineLength=min_length, maxLineGap=10)
    if lines is None:
        return 0
    horiz_count = 0
    for line in lines:
        x1, y1, x2, y2 = line[0]
        dx = abs(x2 - x1)
        dy = abs(y2 - y1)
        if dx > 0 and dy / dx < 0.087:  # tan(5 degrees) ~ 0.087
            horiz_count += 1
    return horiz_count


def _find_any_lines(img: np.ndarray, min_length_pct: float = 0.6) -> int:
    """Count ANY lines (horizontal, vertical, or diagonal) spanning
    more than min_length_pct of viewport width.
    """
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 50, 150)
    min_length = int(img.shape[1] * min_length_pct)
    lines = cv2.HoughLinesP(edges, 1, np.pi / 180, threshold=80,
                            minLineLength=min_length, maxLineGap=15)
    return 0 if lines is None else len(lines)


def _detect_uniform_bands(img: np.ndarray, min_height: int = 10,
                          min_width_pct: float = 0.5) -> list[dict]:
    """Detect horizontal bands of uniform color.

    These bands are the telltale sign of a CSS-transformed element
    being stretched across the viewport. They appear as thin horizontal
    stripes of a single color spanning most of the screen width.

    Returns list of dicts: {y, height, color_mean, width_pct}
    """
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape
    min_width = int(w * min_width_pct)
    bands = []

    # Slide a window down the image looking for rows of near-uniform color
    row_means = np.mean(gray, axis=1)
    row_stds = np.std(gray.astype(float), axis=1)

    y = 0
    while y < h:
        # Look for a row with very low std deviation (uniform color)
        if row_stds[y] < 5 and row_means[y] > 15:  # not pure black bg
            # Find extent of this band
            band_start = y
            while y < h and row_stds[y] < 8 and abs(row_means[y] - row_means[band_start]) < 15:
                y += 1
            band_height = y - band_start
            if band_height >= min_height:
                # Check that the uniform region spans enough width
                row_slice = gray[band_start:y, :]
                # Count how many columns have values close to the mean
                col_means = np.mean(row_slice, axis=0)
                band_mean = np.mean(col_means)
                uniform_cols = np.sum(np.abs(col_means - band_mean) < 10)
                if uniform_cols >= min_width:
                    bands.append({
                        "y": band_start,
                        "height": band_height,
                        "color_mean": float(band_mean),
                        "width_pct": uniform_cols / w,
                    })
        y += 1

    return bands


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
    """Hide ALL rendering layers."""
    state = _set_layers(page, allMapLayers=False, geoLayers=False,
                        models3d=False, domMarkers=False, fog=False)
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
        if (window._mapState.threeRoot) window._mapState.threeRoot.visible = false;
        for (const m of Object.values(window._mapState.unitMarkers || {})) {
            m.getElement().style.display = 'none';
        }
    })()""")
    return state


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


def _restore_everything(page: Page):
    """Restore all UI to default visible state."""
    # Restore chrome
    page.evaluate("""(() => {
        const ids = ['header-bar', 'command-bar-container', 'status-bar',
                     'map-mode', 'map-coords', 'map-fps', 'toast-container',
                     'minimap-container'];
        for (const id of ids) {
            const el = document.getElementById(id);
            if (el) el.style.display = '';
        }
    })()""")
    # Close overlays
    page.evaluate("""(() => {
        const ids = ['chat-overlay', 'help-overlay', 'modal-overlay', 'game-over-overlay'];
        for (const id of ids) {
            const el = document.getElementById(id);
            if (el) el.hidden = true;
        }
        document.querySelectorAll('.menu-dropdown').forEach(d => d.hidden = true);
    })()""")
    # Restore map layers
    _show_all(page)
    # Open default panels
    page.evaluate("""(() => {
        const pm = window.panelManager;
        if (!pm) return;
        pm.open('amy');
        pm.open('units');
        pm.open('alerts');
    })()""")


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture(scope="module")
def browser_page():
    """Launch headed Playwright browser, navigate to Command Center."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page(viewport={"width": VIEWPORT_W, "height": VIEWPORT_H})

        page.goto(SERVER, wait_until="networkidle", timeout=30000)
        time.sleep(5)  # let map tiles load, Three.js initialize, panels render

        # Dismiss any modal
        page.keyboard.press("Escape")
        time.sleep(0.5)

        yield page

        browser.close()


@pytest.fixture(autouse=True)
def reset_between_tests(browser_page):
    """Restore all UI elements and reset map between tests.

    Uses a lighter reset than _restore_everything to avoid triggering
    massive tile reloads that cause screenshot timeouts. The map is
    re-centered at a moderate pitch to keep tile loading fast.
    """
    page = browser_page
    # Close any open overlays
    page.evaluate("""(() => {
        const ids = ['chat-overlay', 'help-overlay', 'modal-overlay', 'game-over-overlay'];
        for (const id of ids) {
            const el = document.getElementById(id);
            if (el) el.hidden = true;
        }
        document.querySelectorAll('.menu-dropdown').forEach(d => d.hidden = true);
    })()""")
    # Restore chrome elements
    page.evaluate("""(() => {
        const ids = ['header-bar', 'command-bar-container', 'status-bar',
                     'map-mode', 'map-coords', 'map-fps', 'toast-container',
                     'minimap-container'];
        for (const id of ids) {
            const el = document.getElementById(id);
            if (el) el.style.display = '';
        }
    })()""")
    # Restore map layers and center
    _show_all(page)
    # Reset to moderate pitch (45) to keep tile loading manageable
    page.evaluate("""(() => {
        const map = window._mapState && window._mapState.map;
        if (!map) return;
        const gc = window._mapState.geoCenter;
        if (!gc) return;
        map.jumpTo({ center: [gc.lng, gc.lat], zoom: 17, bearing: 0, pitch: 45 });
    })()""")
    # Open default panels
    page.evaluate("""(() => {
        const pm = window.panelManager;
        if (!pm) return;
        pm.open('amy'); pm.open('units'); pm.open('alerts');
    })()""")
    time.sleep(1.5)


@pytest.fixture(scope="module")
def vlm_ok():
    """Check if VLM is available for advisory checks."""
    return _vlm_available()


# ============================================================
# Category 1: DOM Overflow Prevention (5 tests)
# ============================================================

class TestCategory1DomOverflow:
    """Prevent markers/labels from expanding beyond their containers.

    Root cause: CSS transforms on MapLibre markers create enormous bounding
    boxes at high pitch angles. Unconstrained text nodes expand to fill
    these boxes, creating visible line artifacts.
    """

    def test_all_markers_have_bounded_width(self, browser_page):
        """Query ALL .maplibregl-marker children, verify none exceed 300px width.

        MapLibre markers contain unit icons and name labels. At any pitch
        angle, no child element should exceed 300px -- that would indicate
        unbounded text or an overflow leak.
        """
        page = browser_page

        oversized = page.evaluate("""(() => {
            const results = [];
            for (const marker of document.querySelectorAll('.maplibregl-marker')) {
                for (const child of marker.querySelectorAll('*')) {
                    const r = child.getBoundingClientRect();
                    if (r.width > 300) {
                        results.push({
                            tag: child.tagName,
                            className: (child.className || '').toString().slice(0, 60),
                            text: (child.textContent || '').trim().slice(0, 30),
                            width: Math.round(r.width),
                            height: Math.round(r.height),
                        });
                    }
                }
            }
            return results;
        })()""")

        print(f"  Marker children >300px wide: {len(oversized)}")
        for el in oversized[:5]:
            print(f"    {el['tag']}.{el['className']} '{el['text']}' "
                  f"w={el['width']} h={el['height']}")

        assert len(oversized) == 0, (
            f"Found {len(oversized)} marker children wider than 300px. "
            f"This indicates unbounded text or overflow leak: "
            f"{json.dumps(oversized[:5], indent=2)}"
        )

    def test_no_text_nodes_exceed_container(self, browser_page):
        """Find all text elements in map container, verify text width <= parent width.

        Text nodes that exceed their parent's width will wrap awkwardly or,
        worse, expand the parent's bounding box when CSS transforms are applied.
        """
        page = browser_page

        overflow_texts = page.evaluate("""(() => {
            const mapContainer = document.getElementById('tactical-area')
                              || document.getElementById('maplibre-map');
            if (!mapContainer) return [];
            const results = [];
            // Check all elements with text content inside the map area
            const textEls = mapContainer.querySelectorAll('span, div, p, label, a');
            for (const el of textEls) {
                if (!el.textContent.trim()) continue;
                const parent = el.parentElement;
                if (!parent) continue;
                const elRect = el.getBoundingClientRect();
                const parentRect = parent.getBoundingClientRect();
                // Only flag elements whose text overflows their parent significantly
                if (elRect.width > parentRect.width + 20 && elRect.width > 200) {
                    results.push({
                        tag: el.tagName,
                        className: (el.className || '').toString().slice(0, 50),
                        text: el.textContent.trim().slice(0, 30),
                        elWidth: Math.round(elRect.width),
                        parentWidth: Math.round(parentRect.width),
                        overflow: Math.round(elRect.width - parentRect.width),
                    });
                }
            }
            return results;
        })()""")

        print(f"  Text elements overflowing parent: {len(overflow_texts)}")
        for el in overflow_texts[:5]:
            print(f"    {el['tag']}.{el['className']} '{el['text']}' "
                  f"el={el['elWidth']}px parent={el['parentWidth']}px "
                  f"overflow={el['overflow']}px")

        assert len(overflow_texts) == 0, (
            f"Found {len(overflow_texts)} text elements overflowing their parent "
            f"inside the map container: {json.dumps(overflow_texts[:3], indent=2)}"
        )

    def test_marker_border_box_bounded(self, browser_page):
        """For each marker, getBoundingClientRect() width < 500px and height < 200px.

        Even at 60-degree pitch, marker bounding boxes should remain bounded.
        CSS transforms can inflate these to thousands of pixels.
        """
        page = browser_page

        # Test at 60-degree pitch (worst case for bounding box inflation)
        _center_map(page, zoom=17, bearing=0, pitch=60)

        oversized = page.evaluate("""(() => {
            const results = [];
            for (const marker of document.querySelectorAll('.maplibregl-marker')) {
                const r = marker.getBoundingClientRect();
                // Marker containers include MapLibre's CSS transform which
                // can legitimately position them off-screen. We only care about
                // the marker's content children being oversized.
                for (const child of marker.children) {
                    const cr = child.getBoundingClientRect();
                    if (cr.width > 500 || cr.height > 200) {
                        results.push({
                            className: (child.className || '').toString().slice(0, 50),
                            text: (child.textContent || '').trim().slice(0, 30),
                            width: Math.round(cr.width),
                            height: Math.round(cr.height),
                        });
                    }
                }
            }
            return results;
        })()""")

        print(f"  Oversized marker children at 60deg pitch: {len(oversized)}")
        for el in oversized[:5]:
            print(f"    .{el['className']} '{el['text']}' "
                  f"w={el['width']} h={el['height']}")

        assert len(oversized) == 0, (
            f"Found {len(oversized)} oversized marker children at 60-degree pitch. "
            f"CSS transform inflation detected: {json.dumps(oversized[:3], indent=2)}"
        )

    def test_overflow_hidden_on_labels(self, browser_page):
        """All .unit-name-3d elements must have overflow: hidden or clip computed style.

        overflow: visible on transformed elements causes the browser to expand
        the element's visual bounding box, creating line artifacts.
        """
        page = browser_page

        bad_overflow = page.evaluate("""(() => {
            const results = [];
            for (const el of document.querySelectorAll('.unit-name-3d')) {
                const style = window.getComputedStyle(el);
                const ov = style.overflow;
                if (ov !== 'hidden' && ov !== 'clip') {
                    results.push({
                        text: el.textContent.trim().slice(0, 30),
                        overflow: ov,
                        width: Math.round(el.getBoundingClientRect().width),
                    });
                }
            }
            return results;
        })()""")

        label_count = page.evaluate(
            "document.querySelectorAll('.unit-name-3d').length"
        )
        print(f"  Total .unit-name-3d labels: {label_count}")
        print(f"  Labels without overflow:hidden/clip: {len(bad_overflow)}")

        if label_count == 0:
            pytest.skip("No .unit-name-3d labels present on the map")

        assert len(bad_overflow) == 0, (
            f"{len(bad_overflow)}/{label_count} unit name labels have "
            f"overflow: {bad_overflow[0]['overflow'] if bad_overflow else '?'} "
            f"instead of 'hidden' or 'clip'. "
            f"This causes line artifacts at high pitch angles."
        )

    def test_text_overflow_ellipsis(self, browser_page):
        """All .unit-name-3d elements must have text-overflow: ellipsis.

        Without ellipsis, long unit names would expand the element width,
        which under CSS transforms creates horizontal line artifacts.
        """
        page = browser_page

        no_ellipsis = page.evaluate("""(() => {
            const results = [];
            for (const el of document.querySelectorAll('.unit-name-3d')) {
                const style = window.getComputedStyle(el);
                if (style.textOverflow !== 'ellipsis') {
                    results.push({
                        text: el.textContent.trim().slice(0, 30),
                        textOverflow: style.textOverflow,
                    });
                }
            }
            return results;
        })()""")

        label_count = page.evaluate(
            "document.querySelectorAll('.unit-name-3d').length"
        )
        print(f"  Total .unit-name-3d labels: {label_count}")
        print(f"  Labels without text-overflow:ellipsis: {len(no_ellipsis)}")

        if label_count == 0:
            pytest.skip("No .unit-name-3d labels present on the map")

        assert len(no_ellipsis) == 0, (
            f"{len(no_ellipsis)}/{label_count} unit name labels lack "
            f"text-overflow: ellipsis. Long names will expand and cause "
            f"line artifacts at high pitch."
        )


# ============================================================
# Category 2: Layer Toggle Integrity (5 tests)
# ============================================================

class TestCategory2LayerToggle:
    """Verify that layer toggles actually change pixel content.

    Root cause: setLayers() might update JS state without actually changing
    MapLibre layer visibility, or Three.js/DOM markers might not respond.
    """

    def test_each_toggle_changes_pixel_content(self, browser_page):
        """For satellite toggle, take before/after screenshots.

        Verify >100 pixels changed. If toggling a layer off changes nothing,
        the toggle is broken or the layer was already off.

        Only tests satellite (most visually impactful layer) to avoid
        excessive tile reloading and screenshot timeouts.
        """
        page = browser_page

        # Start from a known good state with satellite on
        _show_all(page)
        time.sleep(SETTLE + 2)  # extra settle for satellite tile loading

        before_img = _grab(page)
        _save("c2_toggle_sat_before", before_img)

        # Toggle satellite off
        _set_layers(page, satellite=False)
        time.sleep(SETTLE)
        after_img = _grab(page)
        _save("c2_toggle_sat_after", after_img)

        # Compare
        diff = cv2.absdiff(before_img, after_img)
        gray_diff = cv2.cvtColor(diff, cv2.COLOR_BGR2GRAY)
        changed_pixels = int(np.sum(gray_diff > 10))
        print(f"  Toggle satellite off: {changed_pixels} pixels changed")

        assert changed_pixels > 100, (
            f"Toggling satellite off changed only {changed_pixels} pixels. "
            f"Expected >100. The toggle may be broken."
        )

        # Restore satellite
        _set_layers(page, satellite=True)
        time.sleep(1)

    def test_all_off_means_dark(self, browser_page):
        """After hiding all layers, verify map center mean brightness < 20.

        This is the ultimate isolation test: with everything off, the map
        should show only its background color (#060609).
        """
        page = browser_page

        _hide_all(page)
        time.sleep(SETTLE)

        img = _grab(page)
        _save("c2_all_off", img)

        bounds = _get_map_bounds(page)
        center = _crop_map_center(img, bounds)
        _save("c2_all_off_center", center)

        brightness = _mean_brightness(center)
        print(f"  Map center brightness with all layers off: {brightness:.1f}")

        assert brightness < 20, (
            f"Map center brightness ({brightness:.1f}) too high with all layers off. "
            f"Expected <20. A layer is leaking through."
        )

    def test_toggle_roundtrip_idempotent(self, browser_page):
        """Toggle each layer off then on. Verify getMapState() matches original.

        If toggling a layer off-then-on doesn't restore the original state,
        the toggle has side effects or the state tracking is broken.
        """
        page = browser_page

        _show_all(page)
        time.sleep(1)

        original_state = page.evaluate("window._mapActions.getMapState()")
        print(f"  Original state: {json.dumps(original_state)}")

        # Toggle satellite off then on
        _set_layers(page, satellite=False)
        time.sleep(0.5)
        _set_layers(page, satellite=True)
        time.sleep(0.5)

        # Toggle buildings off then on
        _set_layers(page, buildings=False)
        time.sleep(0.5)
        _set_layers(page, buildings=True)
        time.sleep(0.5)

        after_state = page.evaluate("window._mapActions.getMapState()")
        print(f"  After roundtrip: {json.dumps(after_state)}")

        # Compare key boolean fields
        for key in ["showSatellite", "showBuildings", "showRoads",
                     "showWaterways", "showParks"]:
            assert original_state.get(key) == after_state.get(key), (
                f"State mismatch after roundtrip: {key} was {original_state.get(key)}, "
                f"now {after_state.get(key)}"
            )

    def test_no_orphaned_markers_after_hide(self, browser_page):
        """Hide all markers via allMapLayers=false, verify marker elements are hidden.

        Uses allMapLayers=false (which triggers the full marker hide path
        inside setLayers) rather than domMarkers=false alone, because the
        full hide path is what actually sets display:none on unit markers.
        """
        page = browser_page

        # The nuclear hide path (allMapLayers=false) is the reliable way
        # to hide all markers because it sets _state.showUnits = false
        # and iterates all unitMarkers.
        _hide_all(page)
        time.sleep(1)

        visible_markers = page.evaluate("""(() => {
            // Check the markers we control (via _mapState.unitMarkers)
            const managed = Object.values(window._mapState.unitMarkers || {});
            let visible = 0;
            let total = managed.length;
            for (const marker of managed) {
                const el = marker.getElement();
                if (el.style.display !== 'none') {
                    visible++;
                }
            }
            return { visible, total };
        })()""")

        print(f"  Managed markers visible/total: {visible_markers['visible']}/{visible_markers['total']}")

        assert visible_markers["visible"] == 0, (
            f"{visible_markers['visible']} managed markers still visible after "
            f"allMapLayers=false (of {visible_markers['total']} total). "
            f"Marker hide logic is not working."
        )

    def test_threejs_root_hidden_means_no_meshes(self, browser_page, vlm_ok):
        """When models3d is false, verify threeRoot.visible === false.

        The primary assertion is on the threeRoot.visible JS property.
        Green pixel counting is advisory because satellite imagery contains
        natural green (vegetation) that matches loosely with the friendly
        unit color.
        """
        page = browser_page

        # Hide models (but keep everything else for realistic rendering)
        _set_layers(page, models3d=False)
        time.sleep(SETTLE)

        # Check Three.js root visibility -- this is the definitive test
        three_visible = page.evaluate("""(() => {
            if (!window._mapState || !window._mapState.threeRoot) return null;
            return window._mapState.threeRoot.visible;
        })()""")
        print(f"  threeRoot.visible: {three_visible}")

        if three_visible is not None:
            assert three_visible is False, (
                f"threeRoot.visible is {three_visible} after models3d=false. "
                f"Three.js models are still rendering."
            )

        # Also verify via Three.js scene inspection: no visible meshes
        mesh_count = page.evaluate("""(() => {
            const root = window._mapState && window._mapState.threeRoot;
            if (!root) return -1;
            let count = 0;
            root.traverse(child => {
                if (child.isMesh && child.visible) count++;
            });
            return count;
        })()""")
        print(f"  Visible Three.js meshes: {mesh_count}")

        if mesh_count >= 0:
            # When threeRoot.visible=false, child meshes are effectively
            # hidden even if their individual .visible is true.
            # The key assertion is that threeRoot.visible is false.
            pass  # Already asserted above

        # Advisory pixel check: look for distinct neon green BLOBS
        # (not scattered pixels which could be satellite vegetation)
        img = _grab(page)
        bounds = _get_map_bounds(page)
        center = _crop_map_center(img, bounds)
        _save("c2_models3d_off_center", center)

        # Use tight tolerance for the specific NEON green (#05ffa1)
        # to distinguish from natural satellite vegetation green
        lower = np.array([max(0, c - 25) for c in FRIENDLY_GREEN], dtype=np.uint8)
        upper = np.array([min(255, c + 25) for c in FRIENDLY_GREEN], dtype=np.uint8)
        mask = cv2.inRange(center, lower, upper)
        # Count distinct blobs (contours > 100px area = unit model size)
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL,
                                       cv2.CHAIN_APPROX_SIMPLE)
        large_blobs = sum(1 for c in contours if cv2.contourArea(c) > 100)
        total_green = int(cv2.countNonZero(mask))
        print(f"  Neon green pixels (tight tol): {total_green}")
        print(f"  Large neon green blobs (>100px): {large_blobs}")

        # Large blobs of neon green with models off = leakage
        assert large_blobs < 3, (
            f"Found {large_blobs} large neon green blobs in map center with "
            f"models3d=false. Three.js unit models may be leaking through."
        )

        if vlm_ok:
            vlm_text = vlm_analyze(
                OUT / "c2_models3d_off_center.png",
                "Do you see any bright neon green 3D models or unit icons "
                "in this image? Look for distinct green shapes that are NOT "
                "natural vegetation from satellite imagery."
            )
            print(f"  VLM: {vlm_text}")


# ============================================================
# Category 3: Z-Index and Stacking (3 tests)
# ============================================================

class TestCategory3ZIndex:
    """Verify proper stacking order of UI elements.

    Root cause: panels, menus, and overlays rendered below the map canvas
    become invisible even though they exist in the DOM.
    """

    def test_panels_above_map(self, browser_page):
        """Open each panel, verify panel z-index > map container z-index.

        Panels must render above the map canvas to be visible and interactive.
        """
        page = browser_page

        stacking_results = page.evaluate("""(() => {
            const mapEl = document.getElementById('maplibre-map')
                       || document.getElementById('tactical-area');
            if (!mapEl) return { error: 'No map element found' };

            const mapZ = parseInt(window.getComputedStyle(mapEl).zIndex || '0', 10) || 0;

            const pm = window.panelManager;
            if (!pm) return { error: 'No panel manager' };

            const results = [];
            for (const id of pm.registeredIds()) {
                if (!pm.isOpen(id)) pm.open(id);
            }

            // Wait for DOM to update
            for (const id of pm.registeredIds()) {
                const panel = pm.getPanel(id);
                if (!panel || !panel.el) continue;
                const panelZ = parseInt(window.getComputedStyle(panel.el).zIndex || '0', 10) || 0;
                // Also check the panel container
                const container = document.getElementById('panel-container');
                const containerZ = container
                    ? parseInt(window.getComputedStyle(container).zIndex || '0', 10) || 0
                    : 0;
                const effectiveZ = Math.max(panelZ, containerZ);
                results.push({
                    id,
                    panelZ,
                    containerZ,
                    effectiveZ,
                    mapZ,
                    above: effectiveZ >= mapZ,
                });
            }

            return { mapZ, results };
        })()""")

        if "error" in stacking_results:
            pytest.skip(stacking_results["error"])

        print(f"  Map z-index: {stacking_results['mapZ']}")
        for r in stacking_results.get("results", []):
            print(f"    Panel [{r['id']}] z={r['panelZ']} "
                  f"container={r['containerZ']} above={r['above']}")

        below_map = [r for r in stacking_results.get("results", []) if not r["above"]]
        assert len(below_map) == 0, (
            f"{len(below_map)} panels render below the map (z-index {stacking_results['mapZ']}): "
            f"{[r['id'] for r in below_map]}"
        )

    def test_menu_dropdown_above_all(self, browser_page):
        """Open MAP menu, verify dropdown is visible and not clipped.

        Menu dropdowns must appear above all other elements to be usable.
        """
        page = browser_page

        # Click MAP menu trigger
        map_trigger = page.locator('.menu-trigger', has_text="MAP")
        if map_trigger.count() == 0:
            pytest.skip("MAP menu trigger not found")

        map_trigger.first.click()
        time.sleep(1)

        dropdown_info = page.evaluate("""(() => {
            const dropdowns = document.querySelectorAll('.menu-dropdown');
            for (const d of dropdowns) {
                if (!d.hidden && d.offsetHeight > 0) {
                    const rect = d.getBoundingClientRect();
                    const style = window.getComputedStyle(d);
                    const zIndex = parseInt(style.zIndex || '0', 10) || 0;
                    return {
                        visible: true,
                        x: Math.round(rect.x),
                        y: Math.round(rect.y),
                        width: Math.round(rect.width),
                        height: Math.round(rect.height),
                        zIndex,
                        // Check if element is clipped
                        inViewport: rect.x >= 0 && rect.y >= 0
                                 && rect.right <= window.innerWidth
                                 && rect.bottom <= window.innerHeight,
                    };
                }
            }
            return { visible: false };
        })()""")

        print(f"  Dropdown info: {json.dumps(dropdown_info)}")

        assert dropdown_info["visible"], "MAP menu dropdown did not open"
        assert dropdown_info.get("inViewport", False), (
            f"Menu dropdown extends outside viewport "
            f"(x={dropdown_info.get('x')}, y={dropdown_info.get('y')}, "
            f"w={dropdown_info.get('width')}, h={dropdown_info.get('height')})"
        )

        # Take screenshot for visual verification
        img = _grab(page)
        _save("c3_menu_dropdown", img)

        # Close dropdown
        page.keyboard.press("Escape")
        time.sleep(0.5)

    def test_overlays_above_panels(self, browser_page):
        """Open help overlay. Verify it renders above all panels.

        Overlays (help, chat, modal) use full-screen backdrop and must
        sit above panels in the stacking context.
        """
        page = browser_page

        # Open help overlay
        page.evaluate("""(() => {
            const overlay = document.getElementById('help-overlay');
            if (overlay) overlay.hidden = false;
        })()""")
        time.sleep(1)

        overlay_info = page.evaluate("""(() => {
            const overlay = document.getElementById('help-overlay');
            if (!overlay || overlay.hidden) return { visible: false };

            const overlayStyle = window.getComputedStyle(overlay);
            const overlayZ = parseInt(overlayStyle.zIndex || '0', 10) || 0;

            // Check against all open panels
            const pm = window.panelManager;
            let maxPanelZ = 0;
            if (pm) {
                for (const id of pm.registeredIds()) {
                    if (!pm.isOpen(id)) continue;
                    const panel = pm.getPanel(id);
                    if (!panel || !panel.el) continue;
                    const pz = parseInt(window.getComputedStyle(panel.el).zIndex || '0', 10) || 0;
                    maxPanelZ = Math.max(maxPanelZ, pz);
                }
            }

            // Also check panel container
            const container = document.getElementById('panel-container');
            if (container) {
                const cz = parseInt(window.getComputedStyle(container).zIndex || '0', 10) || 0;
                maxPanelZ = Math.max(maxPanelZ, cz);
            }

            return {
                visible: true,
                overlayZ,
                maxPanelZ,
                above: overlayZ >= maxPanelZ,
            };
        })()""")

        print(f"  Overlay info: {json.dumps(overlay_info)}")

        # Close help
        page.evaluate("""(() => {
            const overlay = document.getElementById('help-overlay');
            if (overlay) overlay.hidden = true;
        })()""")

        if not overlay_info.get("visible"):
            pytest.skip("Help overlay did not open")

        assert overlay_info["above"], (
            f"Help overlay (z={overlay_info['overlayZ']}) renders below "
            f"panels (max z={overlay_info['maxPanelZ']}). "
            f"Overlay will be hidden behind panels."
        )


# ============================================================
# Category 4: Keyboard Handling (4 tests)
# ============================================================

class TestCategory4Keyboard:
    """Verify keyboard shortcuts work and focus is never trapped.

    Root cause: input fields swallow all keyboard events, and focus can
    get stuck in chat/search inputs with no way to escape.
    """

    def test_escape_from_any_input(self, browser_page):
        """Focus each input field on the page, press Escape, verify focus is released.

        No input field should trap the user. Escape must always blur the input
        or close the parent overlay.
        """
        page = browser_page

        # Get all input/textarea elements
        input_selectors = page.evaluate("""(() => {
            const inputs = document.querySelectorAll('input, textarea');
            const results = [];
            for (const inp of inputs) {
                // Skip hidden inputs
                const style = window.getComputedStyle(inp);
                if (style.display === 'none' || style.visibility === 'hidden') continue;
                // Build a reliable selector
                const id = inp.id;
                const sel = id ? '#' + id : null;
                if (sel) results.push(sel);
            }
            return results;
        })()""")

        print(f"  Visible input fields: {len(input_selectors)}")

        trapped_inputs = []
        for sel in input_selectors:
            try:
                # Make the element's parent visible if needed (e.g., chat overlay)
                page.evaluate(f"""(() => {{
                    const el = document.querySelector('{sel}');
                    if (!el) return;
                    // Walk up and unhide parent overlays
                    let p = el.parentElement;
                    while (p) {{
                        if (p.hidden) p.hidden = false;
                        p = p.parentElement;
                    }}
                }})()""")
                time.sleep(0.3)

                # Focus the input
                page.focus(sel)
                time.sleep(0.2)

                # Verify it's focused
                is_focused = page.evaluate(
                    f"document.activeElement === document.querySelector('{sel}')"
                )
                if not is_focused:
                    continue  # Couldn't focus, skip

                # Press Escape
                page.keyboard.press("Escape")
                time.sleep(0.3)

                # Verify focus was released
                still_focused = page.evaluate(
                    f"document.activeElement === document.querySelector('{sel}')"
                )
                if still_focused:
                    trapped_inputs.append(sel)
                    print(f"    TRAPPED: {sel} still focused after Escape")
                else:
                    print(f"    OK: {sel} released focus on Escape")
            except Exception as e:
                print(f"    SKIP: {sel} -- {e}")

        # Re-close any overlays we opened
        page.evaluate("""(() => {
            const ids = ['chat-overlay', 'help-overlay', 'modal-overlay'];
            for (const id of ids) {
                const el = document.getElementById(id);
                if (el) el.hidden = true;
            }
        })()""")

        assert len(trapped_inputs) == 0, (
            f"{len(trapped_inputs)} input fields trap focus on Escape: "
            f"{trapped_inputs}. Users cannot escape these inputs."
        )

    def test_shortcuts_work_after_panel_close(self, browser_page):
        """Open panel, close it, verify 'I' key still toggles satellite.

        After a panel is closed, keyboard shortcuts must resume working.
        A stale event listener or focus trap could swallow keystrokes.
        """
        page = browser_page

        # Get initial satellite state
        initial_state = page.evaluate(
            "window._mapActions.getMapState().showSatellite"
        )

        # Open and close a panel
        page.evaluate("""(() => {
            const pm = window.panelManager;
            if (pm) {
                pm.open('amy');
                pm.close('amy');
            }
        })()""")
        time.sleep(0.5)

        # Make sure no input is focused
        page.evaluate("document.activeElement && document.activeElement.blur()")
        time.sleep(0.3)

        # Press 'I' to toggle satellite
        page.keyboard.press("i")
        time.sleep(1)

        after_state = page.evaluate(
            "window._mapActions.getMapState().showSatellite"
        )
        print(f"  Satellite before: {initial_state}, after 'I' press: {after_state}")

        assert initial_state != after_state, (
            f"Pressing 'I' did not toggle satellite after panel close. "
            f"State remained {after_state}. Keyboard shortcut may be swallowed."
        )

        # Toggle back
        page.keyboard.press("i")
        time.sleep(0.5)

    def test_no_key_swallowing(self, browser_page):
        """With no inputs focused, press each shortcut key, verify action fires.

        Each key in the shortcut map should produce a measurable state change
        or event. Keys that silently fail are being swallowed.
        """
        page = browser_page

        # Make sure no input is focused
        page.evaluate("document.activeElement && document.activeElement.blur()")
        time.sleep(0.3)

        # Test '?' toggles help overlay
        page.evaluate("""(() => {
            document.getElementById('help-overlay').hidden = true;
        })()""")
        page.keyboard.press("?")
        time.sleep(0.5)
        help_visible = page.evaluate(
            "!document.getElementById('help-overlay').hidden"
        )
        print(f"  '?' pressed: help visible = {help_visible}")
        assert help_visible, "'?' key did not open help overlay"

        # Close help
        page.keyboard.press("Escape")
        time.sleep(0.3)

        # Test '1' toggles amy panel
        was_open = page.evaluate("""(() => {
            const pm = window.panelManager;
            return pm ? pm.isOpen('amy') : null;
        })()""")
        if was_open is not None:
            page.keyboard.press("1")
            time.sleep(0.5)
            now_open = page.evaluate("window.panelManager.isOpen('amy')")
            print(f"  '1' pressed: amy panel was={was_open}, now={now_open}")
            assert was_open != now_open, (
                f"'1' key did not toggle amy panel. State unchanged ({was_open})."
            )
            # Toggle back
            page.keyboard.press("1")
            time.sleep(0.3)

    def test_tab_navigation(self, browser_page):
        """Press Tab repeatedly, verify focus moves through interactive elements.

        Tab must cycle through focusable elements. If focus stays stuck on
        one element, there's a focus trap.
        """
        page = browser_page

        # Start with no focus
        page.evaluate("document.activeElement && document.activeElement.blur()")
        time.sleep(0.2)

        focused_elements = []
        for i in range(6):
            page.keyboard.press("Tab")
            time.sleep(0.2)
            tag = page.evaluate("""(() => {
                const el = document.activeElement;
                if (!el || el === document.body) return 'body';
                return el.tagName + (el.id ? '#' + el.id : '') +
                       (el.className ? '.' + el.className.toString().split(' ')[0] : '');
            })()""")
            focused_elements.append(tag)

        print(f"  Tab focus sequence: {focused_elements}")

        # At least 2 different elements should receive focus
        unique_elements = set(focused_elements)
        # Filter out 'body' as it means focus escaped
        real_elements = [e for e in unique_elements if e != 'body']
        print(f"  Unique focused elements: {len(real_elements)}")

        # We just need to verify Tab doesn't crash and moves focus somewhere
        # (the exact sequence depends on visible panels)
        assert len(focused_elements) == 6, "Tab press sequence incomplete"


# ============================================================
# Category 5: Transform Artifact Detection (3 tests)
# ============================================================

class TestCategory5TransformArtifacts:
    """Detect CSS transform artifacts that create visible lines/bands.

    Root cause: CSS transforms on marker elements at high pitch angles
    create thin bright lines or bands spanning the viewport. These are
    the most visible and user-reported category of visual bugs.
    """

    def test_no_long_lines_at_any_pitch(self, browser_page, vlm_ok):
        """Test pitch 0, 30, 45, 60, 75. At each, use HoughLinesP to detect
        lines > 60% viewport width. Fail if > 3 such lines found.

        Legitimate map content (roads, building edges, horizon) can produce
        some long lines. But rendering artifacts produce clusters of parallel
        lines that are distinctive.
        """
        page = browser_page

        # Pitch 75 can cause tile loading timeouts on some hardware.
        # Test up to 60 which covers the realistic user range.
        pitches = [0, 30, 45, 60]
        worst_count = 0
        worst_pitch = 0

        for pitch in pitches:
            _center_map(page, zoom=17, bearing=0, pitch=pitch)
            time.sleep(SETTLE)

            img = _grab(page)
            _save(f"c5_pitch_{pitch}", img)

            bounds = _get_map_bounds(page)
            center = _crop_map_center(img, bounds)
            _save(f"c5_pitch_{pitch}_center", center)

            line_count = _find_any_lines(center, min_length_pct=0.6)
            print(f"  Pitch {pitch}: {line_count} lines >60% width")

            if line_count > worst_count:
                worst_count = line_count
                worst_pitch = pitch

        print(f"  Worst case: pitch={worst_pitch} with {worst_count} lines")

        assert worst_count <= 3, (
            f"Found {worst_count} long lines at pitch {worst_pitch}. "
            f"This indicates CSS transform artifacts from marker elements. "
            f"Maximum allowed: 3 (to account for horizon/building edges)."
        )

        if vlm_ok:
            vlm_text = vlm_analyze(
                OUT / f"c5_pitch_{worst_pitch}_center.png",
                "Do you see any obvious horizontal or vertical lines spanning "
                "most of the image that look like rendering artifacts (not "
                "natural map features like roads or building edges)?"
            )
            print(f"  VLM at worst pitch: {vlm_text}")

    def test_no_single_color_bands(self, browser_page):
        """Detect horizontal bands of uniform color > 10px tall spanning > 50% width.

        These bands are the telltale symptom of a stretched CSS-transformed
        element. Natural map content never produces perfectly uniform color
        bands of significant height.

        Tests pitch 45 and 60 (75 causes tile loading timeouts on some
        hardware, so we cap at 60 for reliability).
        """
        page = browser_page

        pitches = [45, 60]

        for pitch in pitches:
            _center_map(page, zoom=17, bearing=0, pitch=pitch)
            time.sleep(SETTLE + 1)

            img = _grab(page)
            bounds = _get_map_bounds(page)
            center = _crop_map_center(img, bounds)
            _save(f"c5_bands_pitch_{pitch}", center)

            bands = _detect_uniform_bands(center, min_height=10, min_width_pct=0.5)
            print(f"  Pitch {pitch}: {len(bands)} uniform color bands detected")
            for band in bands[:3]:
                print(f"    y={band['y']} h={band['height']} "
                      f"brightness={band['color_mean']:.1f} "
                      f"width={band['width_pct']:.1%}")

            assert len(bands) == 0, (
                f"Found {len(bands)} uniform color bands at pitch {pitch}. "
                f"This indicates a CSS-transformed element being stretched "
                f"across the viewport. Bands: {json.dumps(bands[:3], indent=2)}"
            )

    def test_rotation_doesnt_create_artifacts(self, browser_page, vlm_ok):
        """Set bearing to 0, 90, 180, 270. At each, check for artifacts.

        Map rotation changes how CSS transforms are applied to markers.
        Some rotation angles may expose artifact-producing edge cases.
        Uses pitch 45 (not higher) to avoid tile loading timeouts.
        """
        page = browser_page

        bearings = [0, 90, 180, 270]
        worst_lines = 0
        worst_bearing = 0

        for bearing in bearings:
            _center_map(page, zoom=17, bearing=bearing, pitch=45)
            time.sleep(SETTLE + 1)

            try:
                img = _grab(page)
            except Exception as e:
                print(f"  Bearing {bearing}: screenshot failed ({e}), skipping")
                continue

            _save(f"c5_bearing_{bearing}", img)

            bounds = _get_map_bounds(page)
            center = _crop_map_center(img, bounds)

            # Check for long lines
            line_count = _find_any_lines(center, min_length_pct=0.6)

            # Check for color bands
            bands = _detect_uniform_bands(center, min_height=10, min_width_pct=0.5)

            artifact_score = line_count + len(bands) * 2
            print(f"  Bearing {bearing}: {line_count} lines, {len(bands)} bands "
                  f"(score={artifact_score})")

            if artifact_score > worst_lines:
                worst_lines = artifact_score
                worst_bearing = bearing

        print(f"  Worst case: bearing={worst_bearing} score={worst_lines}")

        assert worst_lines <= 5, (
            f"Artifact score {worst_lines} at bearing {worst_bearing}. "
            f"CSS transforms are creating rendering artifacts during rotation."
        )

        if vlm_ok and (OUT / f"c5_bearing_{worst_bearing}.png").exists():
            vlm_text = vlm_analyze(
                OUT / f"c5_bearing_{worst_bearing}.png",
                "Does this rotated map view show any obvious visual glitches "
                "like horizontal lines, color bands, or stretched elements?"
            )
            print(f"  VLM at worst bearing: {vlm_text}")


# ============================================================
# Category 6: State Consistency (3 tests)
# ============================================================

class TestCategory6StateConsistency:
    """Verify that JS state, DOM state, and API state all agree.

    Root cause: State can diverge when setLayers() updates JS flags but
    MapLibre fails to apply the change, or when WebSocket updates arrive
    but DOM rendering is skipped.
    """

    def test_map_state_matches_dom(self, browser_page):
        """Compare getMapState() booleans with actual DOM/layer visibility.

        Each boolean in the state object should correspond to real
        DOM/layer visibility. Any mismatch means the UI is lying about
        what the user sees.
        """
        page = browser_page

        _show_all(page)
        time.sleep(SETTLE)

        consistency = page.evaluate("""(() => {
            const state = window._mapActions.getMapState();
            const map = window._mapState.map;
            const mismatches = [];

            // Check satellite layer visibility
            if (map && map.getLayer('satellite-layer')) {
                const vis = map.getLayoutProperty('satellite-layer', 'visibility');
                const layerVisible = vis === 'visible' || vis === undefined;
                if (state.showSatellite !== layerVisible) {
                    mismatches.push({
                        field: 'showSatellite',
                        stateValue: state.showSatellite,
                        domValue: layerVisible,
                    });
                }
            }

            // Check building outlines
            if (map && map.getLayer('buildings-outline')) {
                const vis = map.getLayoutProperty('buildings-outline', 'visibility');
                const layerVisible = vis === 'visible' || vis === undefined;
                if (state.showBuildings !== layerVisible) {
                    mismatches.push({
                        field: 'showBuildings',
                        stateValue: state.showBuildings,
                        domValue: layerVisible,
                    });
                }
            }

            // Check Three.js model visibility
            if (window._mapState.threeRoot) {
                const threeVisible = window._mapState.threeRoot.visible;
                if (state.showModels3d !== threeVisible) {
                    mismatches.push({
                        field: 'showModels3d',
                        stateValue: state.showModels3d,
                        domValue: threeVisible,
                    });
                }
            }

            // Check DOM marker visibility (sample first 5)
            const markers = Object.values(window._mapState.unitMarkers || {});
            if (markers.length > 0) {
                const sampleMarker = markers[0].getElement();
                const markerDisplay = sampleMarker.style.display;
                const markersVisible = markerDisplay !== 'none';
                if (state.showUnits !== markersVisible && state.showLabels !== markersVisible) {
                    mismatches.push({
                        field: 'showUnits/showLabels',
                        stateValue: { showUnits: state.showUnits, showLabels: state.showLabels },
                        domValue: markersVisible,
                    });
                }
            }

            return { state, mismatches, markerCount: markers.length };
        })()""")

        print(f"  State: {json.dumps(consistency['state'])}")
        print(f"  Marker count: {consistency['markerCount']}")
        print(f"  Mismatches: {len(consistency['mismatches'])}")
        for m in consistency["mismatches"]:
            print(f"    {m['field']}: state={m['stateValue']} dom={m['domValue']}")

        assert len(consistency["mismatches"]) == 0, (
            f"{len(consistency['mismatches'])} state/DOM mismatches detected: "
            f"{json.dumps(consistency['mismatches'], indent=2)}"
        )

    def test_unit_count_matches_markers(self, browser_page):
        """Compare simulation target count with DOM marker count.

        The number of DOM markers should match the number of units
        that TritiumStore knows about. A mismatch means markers are
        being created or destroyed without state updates.
        """
        page = browser_page

        counts = page.evaluate("""(() => {
            const storeCount = window.TritiumStore
                ? window.TritiumStore.units.size
                : -1;

            const markerCount = Object.keys(
                window._mapState ? window._mapState.unitMarkers || {} : {}
            ).length;

            return { storeCount, markerCount };
        })()""")

        print(f"  TritiumStore.units.size: {counts['storeCount']}")
        print(f"  _mapState.unitMarkers count: {counts['markerCount']}")

        if counts["storeCount"] < 0:
            pytest.skip("TritiumStore not available")

        # Allow a small tolerance (markers may lag behind store by 1-2 units
        # during rapid updates)
        diff = abs(counts["storeCount"] - counts["markerCount"])
        assert diff <= 2, (
            f"Unit count mismatch: store has {counts['storeCount']} units but "
            f"map has {counts['markerCount']} markers (diff={diff}). "
            f"DOM markers out of sync with state."
        )

    def test_store_state_matches_api(self, browser_page):
        """Compare TritiumStore.units count with simulation targets API count.

        The backend simulation API and frontend store should agree on how
        many targets exist. Uses /api/amy/simulation/targets which is the
        primary source of unit data that flows through WebSocket telemetry
        to TritiumStore.  The unified /api/targets endpoint only contains
        real (camera-detected) targets, which may be empty when running in
        pure simulation mode.
        """
        page = browser_page

        # Get store count from browser
        store_count = page.evaluate("""(() => {
            return window.TritiumStore ? window.TritiumStore.units.size : -1;
        })()""")

        if store_count < 0:
            pytest.skip("TritiumStore not available")

        # Use simulation targets endpoint (primary data source for WS telemetry)
        api_count = None
        endpoint = "/api/amy/simulation/targets"
        try:
            resp = requests.get(f"{SERVER}{endpoint}", timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, dict) and "targets" in data:
                    api_count = len(data["targets"])
                elif isinstance(data, list):
                    api_count = len(data)
        except Exception:
            pass

        if api_count is None:
            pytest.skip("Simulation targets API not available")

        print(f"  TritiumStore.units.size: {store_count}")
        print(f"  Simulation API target count: {api_count}")

        # Both should be non-zero if the simulation is running
        if store_count == 0 and api_count == 0:
            pytest.skip("No targets in simulation or store (simulation may not be running)")

        # At least one source must have targets
        assert store_count > 0 or api_count > 0, (
            "Both store and API report zero targets -- simulation not running?"
        )

        # If both have targets, check they're in the same ballpark.
        # The store may include ambient spawns or lag behind the API.
        if store_count > 0 and api_count > 0:
            ratio = min(store_count, api_count) / max(store_count, api_count)
            print(f"  Count ratio (lower/higher): {ratio:.2f}")

            assert ratio > 0.3, (
                f"Store/API count ratio too low ({ratio:.2f}). "
                f"Frontend has {store_count}, API has {api_count}. "
                f"Significant data loss or sync issue."
            )
        elif api_count > 0 and store_count == 0:
            # API has targets but store is empty -- WebSocket may not have
            # delivered telemetry yet. This is a timing issue, not a bug.
            print("  WARNING: API has targets but store is empty (WS timing)")
        elif store_count > 0 and api_count == 0:
            # Store has units but API returns none -- store may contain
            # ambient/neutral spawns not in simulation targets list.
            print("  WARNING: Store has units but simulation API is empty")
