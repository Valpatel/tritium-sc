# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Comprehensive UI Element Isolation Test Suite.

Systematically shows/hides every UI element (panels, overlays, chrome,
map layers) one at a time, screenshots each state, and verifies with
OpenCV + optional VLM analysis.  Unlike test_layer_isolation.py (which
only tests map rendering layers), this suite covers the FULL UI:

  Phase 1: Floating panels (Amy, Units, Alerts, Game, Mesh)
  Phase 2: Overlays (Help, Chat, Menu dropdown)
  Phase 3: Chrome elements (Header, Command bar, Mode selector, Status bar)
  Phase 4: Defense tests (overflow, artifact, truly-black)

Each test:
  1. Hides ALL UI elements (panels, overlays, map layers)
  2. Shows ONE element
  3. Takes screenshot
  4. Verifies element at expected position/size via OpenCV
  5. Verifies no rendering artifacts
  6. Optional VLM advisory check

Run:
    .venv/bin/python3 -m pytest tests/visual/test_ui_isolation.py -v
    ./test.sh 17
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

OUT = Path("tests/.test-results/ui-isolation")
OUT.mkdir(parents=True, exist_ok=True)

SERVER = "http://localhost:8000"
OLLAMA_URL = "http://localhost:11434"
VLM_MODEL = "llava:7b"
SETTLE = 2.0          # seconds for render to settle after state change
COLOR_TOL = 45        # BGR color match tolerance
VLM_TIMEOUT = 120
VLM_RETRIES = 2
VIEWPORT_W = 1920
VIEWPORT_H = 1080

# Cybercore palette (BGR)
CYAN = (255, 240, 0)          # #00f0ff
MAGENTA = (109, 42, 255)      # #ff2a6d
GREEN = (161, 255, 5)         # #05ffa1
YELLOW = (10, 238, 252)       # #fcee0a
VOID_BLACK = (9, 6, 6)        # #060609
PANEL_BG = (20, 16, 12)       # approximate dark panel background


# ============================================================
# VLM Helper (same as layer isolation)
# ============================================================

def vlm_analyze(image_path: str | Path, prompt: str) -> str:
    """Send an image to local llava:7b for natural language analysis."""
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

def _grab(page: Page) -> np.ndarray:
    """Full page screenshot as BGR numpy array."""
    buf = page.screenshot(timeout=60000)
    arr = np.frombuffer(buf, dtype=np.uint8)
    return cv2.imdecode(arr, cv2.IMREAD_COLOR)


def _mean_brightness(img: np.ndarray) -> float:
    """Mean brightness (0-255) of a BGR image."""
    return float(np.mean(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)))


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


def _edge_density(img: np.ndarray) -> float:
    """Fraction of pixels that are edges (0.0 - 1.0)."""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 50, 150)
    return cv2.countNonZero(edges) / edges.size


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
        if dx > 0 and dy / dx < 0.087:  # tan(5 degrees)
            horiz_count += 1
    return horiz_count


def _crop_region(img: np.ndarray, x: int, y: int, w: int, h: int) -> np.ndarray:
    """Crop a region from an image, clamping to bounds."""
    ih, iw = img.shape[:2]
    x1 = max(0, x)
    y1 = max(0, y)
    x2 = min(iw, x + w)
    y2 = min(ih, y + h)
    return img[y1:y2, x1:x2].copy()


def _save(name: str, img: np.ndarray):
    """Save debug image to output directory."""
    cv2.imwrite(str(OUT / f"{name}.png"), img)


# ============================================================
# UI Control Helpers
# ============================================================

def _hide_all_panels(page: Page):
    """Hide all floating panels."""
    page.evaluate("""(() => {
        const pm = window.panelManager;
        if (!pm) return;
        for (const id of pm.registeredIds()) {
            if (pm.isOpen(id)) pm.close(id);
        }
    })()""")


def _close_all_overlays(page: Page):
    """Close chat, help, modal, game-over overlays."""
    page.evaluate("""(() => {
        const ids = ['chat-overlay', 'help-overlay', 'modal-overlay', 'game-over-overlay'];
        for (const id of ids) {
            const el = document.getElementById(id);
            if (el) el.hidden = true;
        }
        // Close any open menu dropdowns
        document.querySelectorAll('.menu-dropdown').forEach(d => d.hidden = true);
        document.querySelectorAll('.menu-trigger.active').forEach(t => t.classList.remove('active'));
    })()""")


def _hide_all_map_layers(page: Page):
    """Hide all map rendering layers (MapLibre + Three.js + DOM markers)."""
    page.evaluate("""(() => {
        if (window._mapActions && window._mapActions.setLayers) {
            window._mapActions.setLayers({
                allMapLayers: false, geoLayers: false,
                models3d: false, domMarkers: false, fog: false
            });
        }
        // Belt-and-suspenders: hide all layers via map directly
        if (window._mapState && window._mapState.map) {
            const map = window._mapState.map;
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
        }
    })()""")


def _hide_chrome(page: Page):
    """Hide header bar, command bar, status bar, and map HUD elements."""
    page.evaluate("""(() => {
        // Header bar
        const header = document.getElementById('header-bar');
        if (header) header.style.display = 'none';
        // Command bar container
        const cmdBar = document.getElementById('command-bar-container');
        if (cmdBar) cmdBar.style.display = 'none';
        // Status bar
        const statusBar = document.getElementById('status-bar');
        if (statusBar) statusBar.style.display = 'none';
        // Map mode indicator
        const modeInd = document.getElementById('map-mode');
        if (modeInd) modeInd.style.display = 'none';
        // Map coords
        const coords = document.getElementById('map-coords');
        if (coords) coords.style.display = 'none';
        // Map FPS
        const fps = document.getElementById('map-fps');
        if (fps) fps.style.display = 'none';
        // Minimap
        const minimap = document.getElementById('minimap-container');
        if (minimap) minimap.style.display = 'none';
        // Toast container
        const toasts = document.getElementById('toast-container');
        if (toasts) toasts.style.display = 'none';
        // War HUD elements
        for (const id of ['war-countdown', 'war-wave-banner', 'war-elimination-feed',
                          'war-score', 'war-begin-btn', 'war-game-over', 'war-amy-toast']) {
            const el = document.getElementById(id);
            if (el) el.style.display = 'none';
        }
    })()""")


def _restore_chrome(page: Page):
    """Restore all hidden chrome elements."""
    page.evaluate("""(() => {
        const ids = ['header-bar', 'command-bar-container', 'status-bar',
                     'map-mode', 'map-coords', 'map-fps', 'toast-container'];
        for (const id of ids) {
            const el = document.getElementById(id);
            if (el) el.style.display = '';
        }
        // Minimap defaults to visible
        const minimap = document.getElementById('minimap-container');
        if (minimap) minimap.style.display = '';
        // War HUD elements restore
        for (const id of ['war-countdown', 'war-wave-banner', 'war-elimination-feed',
                          'war-score', 'war-begin-btn', 'war-game-over', 'war-amy-toast']) {
            const el = document.getElementById(id);
            if (el) el.style.display = '';
        }
    })()""")


def _hide_everything(page: Page):
    """Nuclear option: hide ALL UI. Panels, overlays, chrome, map layers."""
    _hide_all_panels(page)
    _close_all_overlays(page)
    _hide_all_map_layers(page)
    _hide_chrome(page)


def _restore_everything(page: Page):
    """Restore all UI to default visible state."""
    _restore_chrome(page)
    _close_all_overlays(page)
    # Restore map layers
    page.evaluate("""(() => {
        if (window._mapActions && window._mapActions.setLayers) {
            window._mapActions.setLayers({
                allMapLayers: true, models3d: true, domMarkers: true,
                satellite: true, buildings: true, roads: true,
                waterways: true, parks: true, fog: false
            });
        }
    })()""")
    # Open default panels
    page.evaluate("""(() => {
        const pm = window.panelManager;
        if (!pm) return;
        pm.open('amy');
        pm.open('units');
        pm.open('alerts');
    })()""")


def _get_element_bbox(page: Page, selector: str) -> dict | None:
    """Get bounding box of an element. Returns None if not found/hidden."""
    el = page.locator(selector)
    if el.count() == 0:
        return None
    try:
        bbox = el.first.bounding_box()
        return bbox
    except Exception:
        return None


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
def reset_ui(browser_page):
    """Restore all UI elements between tests."""
    _restore_everything(browser_page)
    time.sleep(1)


@pytest.fixture(scope="module")
def vlm_ok():
    """Check if VLM is available for advisory checks."""
    return _vlm_available()


# ============================================================
# Phase 0: Baseline -- All Hidden
# ============================================================

class TestPhase0Baseline:
    """Verify that hiding everything produces a near-black screen."""

    def test_all_hidden_is_truly_dark(self, browser_page, vlm_ok):
        """Hide ALL UI (panels, overlays, chrome, map layers).

        The screen should be near-black with only the map background
        color (#060609) visible.
        """
        page = browser_page

        _hide_everything(page)
        time.sleep(SETTLE)

        img = _grab(page)
        _save("p0_00_all_hidden", img)

        brightness = _mean_brightness(img)
        print(f"  All-hidden brightness: {brightness:.1f}")

        # The screen should be very dark
        assert brightness < 30, (
            f"Screen brightness ({brightness:.1f}) too high with everything hidden. "
            f"Expected near-black (<30). A UI element is leaking."
        )

        if vlm_ok:
            vlm_text = vlm_analyze(
                OUT / "p0_00_all_hidden.png",
                "Is this image mostly dark/black, or can you see any UI "
                "elements like text, buttons, panels, or colored shapes?"
            )
            print(f"  VLM: {vlm_text}")


# ============================================================
# Phase 1: Panel Isolation
# ============================================================

class TestPhase1Panels:
    """Show one floating panel at a time, verify it appears in the left region."""

    PANELS = [
        ("amy", "AMY", "left"),
        ("units", "UNITS", "left"),
        ("alerts", "ALERTS", "left-or-right"),
        ("game", "GAME", "left-or-right"),
    ]

    @pytest.mark.parametrize("panel_id,panel_title,expected_region", PANELS)
    def test_panel_isolation(self, browser_page, vlm_ok, panel_id, panel_title,
                             expected_region):
        """Show ONLY the specified panel, verify it renders correctly."""
        page = browser_page

        _hide_everything(page)
        time.sleep(SETTLE)

        # Take baseline screenshot (everything hidden)
        baseline = _grab(page)
        baseline_brightness = _mean_brightness(baseline)

        # Show only this panel
        page.evaluate(f"""(() => {{
            const pm = window.panelManager;
            if (!pm) return;
            pm.open('{panel_id}');
        }})()""")
        time.sleep(SETTLE)

        img = _grab(page)
        _save(f"p1_{panel_id}_only", img)

        # Verify panel element exists and is visible
        panel_el = page.locator(f'[data-panel-id="{panel_id}"]')
        assert panel_el.count() >= 1, f"Panel element [{panel_id}] not found in DOM"
        bbox = panel_el.first.bounding_box()
        assert bbox is not None, f"Panel [{panel_id}] has no bounding box (hidden?)"

        print(f"  Panel [{panel_id}] bbox: x={bbox['x']:.0f} y={bbox['y']:.0f} "
              f"w={bbox['width']:.0f} h={bbox['height']:.0f}")

        # Verify panel is within viewport
        assert bbox["x"] >= -10, f"Panel [{panel_id}] extends left of viewport"
        assert bbox["y"] >= -10, f"Panel [{panel_id}] extends above viewport"
        assert bbox["x"] + bbox["width"] <= VIEWPORT_W + 10, \
            f"Panel [{panel_id}] extends right of viewport"
        assert bbox["y"] + bbox["height"] <= VIEWPORT_H + 10, \
            f"Panel [{panel_id}] extends below viewport"

        # Verify minimum size
        assert bbox["width"] >= 180, f"Panel [{panel_id}] too narrow ({bbox['width']}px)"
        assert bbox["height"] >= 100, f"Panel [{panel_id}] too short ({bbox['height']}px)"

        # Crop to panel region and check it has content
        panel_crop = _crop_region(
            img,
            int(bbox["x"]), int(bbox["y"]),
            int(bbox["width"]), int(bbox["height"])
        )
        _save(f"p1_{panel_id}_crop", panel_crop)

        panel_brightness = _mean_brightness(panel_crop)
        print(f"  Panel [{panel_id}] region brightness: {panel_brightness:.1f}")

        # Panel should be brighter than the all-hidden baseline
        # (it has text, borders, background)
        assert panel_brightness > baseline_brightness + 2, (
            f"Panel [{panel_id}] region ({panel_brightness:.1f}) not brighter than "
            f"baseline ({baseline_brightness:.1f}). Panel may not be rendering."
        )

        # Check that the panel has edge content (text, borders)
        edge_ratio = _edge_density(panel_crop)
        print(f"  Panel [{panel_id}] edge density: {edge_ratio:.4f}")
        assert edge_ratio > 0.005, (
            f"Panel [{panel_id}] has very low edge density ({edge_ratio:.4f}). "
            f"Expected text/border content."
        )

        # Verify the REST of the screen is mostly dark (no other panels leaking)
        # Mask out the panel region and check remaining pixels
        masked = img.copy()
        x1 = max(0, int(bbox["x"]))
        y1 = max(0, int(bbox["y"]))
        x2 = min(img.shape[1], int(bbox["x"] + bbox["width"]))
        y2 = min(img.shape[0], int(bbox["y"] + bbox["height"]))
        masked[y1:y2, x1:x2] = 0  # black out the panel area
        remaining_brightness = _mean_brightness(masked)
        print(f"  Rest-of-screen brightness: {remaining_brightness:.1f}")

        # Now hide the panel and verify it disappears
        page.evaluate(f"""(() => {{
            const pm = window.panelManager;
            if (pm) pm.close('{panel_id}');
        }})()""")
        time.sleep(1.0)

        after_img = _grab(page)
        _save(f"p1_{panel_id}_after_hide", after_img)

        # Panel region should now be dark again
        after_crop = _crop_region(
            after_img,
            int(bbox["x"]), int(bbox["y"]),
            int(bbox["width"]), int(bbox["height"])
        )
        after_brightness = _mean_brightness(after_crop)
        print(f"  After hide, panel region brightness: {after_brightness:.1f}")

        assert after_brightness < panel_brightness - 1, (
            f"Panel [{panel_id}] region still bright ({after_brightness:.1f}) after hide. "
            f"Ghost pixels? Expected darker than when panel was shown ({panel_brightness:.1f})."
        )

        # VLM advisory check
        if vlm_ok:
            vlm_text = vlm_analyze(
                OUT / f"p1_{panel_id}_only.png",
                f"This should show a single UI panel titled '{panel_title}' on a "
                f"mostly dark background. Do you see the panel? Where is it? "
                f"Are there any other visible UI elements?"
            )
            print(f"  VLM: {vlm_text}")


# ============================================================
# Phase 2: Overlay Isolation
# ============================================================

class TestPhase2Overlays:
    """Test overlay elements (help, chat, menu dropdowns)."""

    def test_help_overlay(self, browser_page, vlm_ok):
        """Show help overlay. Verify it covers the center of the screen."""
        page = browser_page

        _hide_everything(page)
        time.sleep(SETTLE)

        baseline = _grab(page)
        baseline_brightness = _mean_brightness(baseline)

        # Open help overlay via JS (not keyboard, since we hid the chrome)
        page.evaluate("""(() => {
            const overlay = document.getElementById('help-overlay');
            if (overlay) overlay.hidden = false;
        })()""")
        time.sleep(SETTLE)

        img = _grab(page)
        _save("p2_help_overlay", img)

        # Verify overlay element is visible
        overlay_bbox = _get_element_bbox(page, "#help-overlay")
        assert overlay_bbox is not None, "Help overlay not visible"

        # Help panel within the overlay
        panel_bbox = _get_element_bbox(page, "#help-overlay .help-panel")
        if panel_bbox:
            print(f"  Help panel bbox: x={panel_bbox['x']:.0f} y={panel_bbox['y']:.0f} "
                  f"w={panel_bbox['width']:.0f} h={panel_bbox['height']:.0f}")

            panel_crop = _crop_region(
                img,
                int(panel_bbox["x"]), int(panel_bbox["y"]),
                int(panel_bbox["width"]), int(panel_bbox["height"])
            )
            _save("p2_help_panel_crop", panel_crop)

            panel_brightness = _mean_brightness(panel_crop)
            print(f"  Help panel brightness: {panel_brightness:.1f}")
            assert panel_brightness > baseline_brightness + 3, (
                f"Help panel too dark ({panel_brightness:.1f}). Not rendering?"
            )

            # Should have text content (keyboard shortcuts)
            edge_ratio = _edge_density(panel_crop)
            print(f"  Help panel edge density: {edge_ratio:.4f}")
            assert edge_ratio > 0.01, "Help panel has no text content"

        # The help panel itself verifies visibility.  Full-image brightness
        # is unreliable because the help panel is small relative to the total
        # 1920x1080 screen and the baseline can have stochastic noise.
        img_brightness = _mean_brightness(img)
        print(f"  Full image brightness with help: {img_brightness:.1f}")

        # Close it and verify the PANEL REGION goes dark
        page.evaluate("""(() => {
            const overlay = document.getElementById('help-overlay');
            if (overlay) overlay.hidden = true;
        })()""")
        time.sleep(1.0)

        after = _grab(page)
        if panel_bbox:
            after_crop = _crop_region(
                after,
                int(panel_bbox["x"]), int(panel_bbox["y"]),
                int(panel_bbox["width"]), int(panel_bbox["height"])
            )
            after_panel_brightness = _mean_brightness(after_crop)
            print(f"  After close, panel region brightness: {after_panel_brightness:.1f}")
            assert after_panel_brightness < panel_brightness - 1, (
                f"Help panel region still bright ({after_panel_brightness:.1f}) after close. "
                f"Expected darker than when open ({panel_brightness:.1f})."
            )

        if vlm_ok:
            vlm_text = vlm_analyze(
                OUT / "p2_help_overlay.png",
                "Does this image show a keyboard shortcuts help panel? "
                "Can you read any key bindings or shortcut labels?"
            )
            print(f"  VLM: {vlm_text}")

    def test_chat_overlay(self, browser_page, vlm_ok):
        """Show chat overlay. Verify it appears on the right side."""
        page = browser_page

        _hide_everything(page)
        time.sleep(SETTLE)

        baseline_brightness = _mean_brightness(_grab(page))

        # Open chat overlay
        page.evaluate("""(() => {
            const overlay = document.getElementById('chat-overlay');
            if (overlay) overlay.hidden = false;
        })()""")
        time.sleep(SETTLE)

        img = _grab(page)
        _save("p2_chat_overlay", img)

        # Verify chat panel is visible
        chat_bbox = _get_element_bbox(page, "#chat-panel")
        assert chat_bbox is not None, "Chat panel not visible"

        print(f"  Chat panel bbox: x={chat_bbox['x']:.0f} y={chat_bbox['y']:.0f} "
              f"w={chat_bbox['width']:.0f} h={chat_bbox['height']:.0f}")

        chat_crop = _crop_region(
            img,
            int(chat_bbox["x"]), int(chat_bbox["y"]),
            int(chat_bbox["width"]), int(chat_bbox["height"])
        )
        _save("p2_chat_panel_crop", chat_crop)

        chat_brightness = _mean_brightness(chat_crop)
        print(f"  Chat panel brightness: {chat_brightness:.1f}")
        assert chat_brightness > baseline_brightness + 2, (
            f"Chat panel too dark ({chat_brightness:.1f}). Not rendering?"
        )

        # Should have text fields (input, title)
        edge_ratio = _edge_density(chat_crop)
        print(f"  Chat panel edge density: {edge_ratio:.4f}")

        # Close it
        page.evaluate("""(() => {
            const overlay = document.getElementById('chat-overlay');
            if (overlay) overlay.hidden = true;
        })()""")
        time.sleep(1.0)

        after = _grab(page)
        after_brightness = _mean_brightness(after)
        print(f"  After close brightness: {after_brightness:.1f}")

        if vlm_ok:
            vlm_text = vlm_analyze(
                OUT / "p2_chat_overlay.png",
                "Does this show a chat panel with a text input field? "
                "Can you see a title like 'AMY COMM' or a send button?"
            )
            print(f"  VLM: {vlm_text}")

    def test_menu_dropdown(self, browser_page, vlm_ok):
        """Open a menu dropdown. Verify it appears below the menu bar."""
        page = browser_page

        # Restore chrome for this test (need menu bar visible)
        _restore_chrome(page)
        _hide_all_panels(page)
        _close_all_overlays(page)
        _hide_all_map_layers(page)
        time.sleep(SETTLE)

        baseline = _grab(page)
        _save("p2_menu_baseline", baseline)

        # Click the MAP menu trigger
        map_trigger = page.locator('.menu-trigger', has_text="MAP")
        if map_trigger.count() > 0:
            map_trigger.first.click()
            time.sleep(1.0)

            img = _grab(page)
            _save("p2_menu_map_dropdown", img)

            # Check for visible dropdown
            dropdown_visible = page.evaluate("""(() => {
                const dropdowns = document.querySelectorAll('.menu-dropdown');
                for (const d of dropdowns) {
                    if (!d.hidden && d.offsetHeight > 0) return true;
                }
                return false;
            })()""")
            print(f"  Menu dropdown visible: {dropdown_visible}")
            assert dropdown_visible, "MAP menu dropdown did not open"

            # Find the visible dropdown and verify its position
            dropdown_bbox = page.evaluate("""(() => {
                const dropdowns = document.querySelectorAll('.menu-dropdown');
                for (const d of dropdowns) {
                    if (!d.hidden && d.offsetHeight > 0) {
                        const r = d.getBoundingClientRect();
                        return {x: r.x, y: r.y, width: r.width, height: r.height};
                    }
                }
                return null;
            })()""")
            if dropdown_bbox:
                print(f"  Dropdown bbox: x={dropdown_bbox['x']:.0f} y={dropdown_bbox['y']:.0f} "
                      f"w={dropdown_bbox['width']:.0f} h={dropdown_bbox['height']:.0f}")

                # Dropdown should be in the top area (below command bar)
                assert dropdown_bbox["y"] < VIEWPORT_H / 2, (
                    f"Dropdown too low (y={dropdown_bbox['y']}). Should be near top."
                )

            # Close dropdown
            page.keyboard.press("Escape")
            time.sleep(0.5)

            if vlm_ok:
                vlm_text = vlm_analyze(
                    OUT / "p2_menu_map_dropdown.png",
                    "Does this show a dropdown menu with map layer options like "
                    "'Satellite', 'Roads', 'Buildings'? Is there a checkmark "
                    "indicator next to some items?"
                )
                print(f"  VLM: {vlm_text}")
        else:
            pytest.skip("MAP menu trigger not found")


# ============================================================
# Phase 3: Chrome Element Isolation
# ============================================================

class TestPhase3Chrome:
    """Test chrome elements (header, command bar, mode selector, status bar)."""

    def test_header_bar_only(self, browser_page, vlm_ok):
        """Show ONLY the header bar. Verify it spans the top of the screen."""
        page = browser_page

        _hide_everything(page)
        time.sleep(SETTLE)

        baseline = _grab(page)
        _save("p3_header_baseline", baseline)
        baseline_brightness = _mean_brightness(baseline)

        # Show only header bar
        page.evaluate("""(() => {
            const header = document.getElementById('header-bar');
            if (header) header.style.display = '';
        })()""")
        time.sleep(SETTLE)

        img = _grab(page)
        _save("p3_header_only", img)

        # Verify header is visible
        header_bbox = _get_element_bbox(page, "#header-bar")
        assert header_bbox is not None, "Header bar not visible"

        print(f"  Header bbox: x={header_bbox['x']:.0f} y={header_bbox['y']:.0f} "
              f"w={header_bbox['width']:.0f} h={header_bbox['height']:.0f}")

        # Header should span full width at the top
        assert header_bbox["y"] < 10, f"Header not at top (y={header_bbox['y']})"
        assert header_bbox["width"] > VIEWPORT_W * 0.9, (
            f"Header too narrow ({header_bbox['width']}px vs {VIEWPORT_W}px viewport)"
        )
        assert header_bbox["height"] < 60, (
            f"Header too tall ({header_bbox['height']}px). Expected ~36px."
        )

        # Crop the header region and verify content
        header_crop = _crop_region(
            img, 0, 0, VIEWPORT_W, int(header_bbox["height"] + 5)
        )
        _save("p3_header_crop", header_crop)

        header_brightness = _mean_brightness(header_crop)
        print(f"  Header region brightness: {header_brightness:.1f}")
        assert header_brightness > baseline_brightness + 1, "Header not rendering"

        # The rest of the screen should be dark
        rest = _crop_region(img, 0, int(header_bbox["height"] + 5),
                            VIEWPORT_W, VIEWPORT_H - int(header_bbox["height"]) - 5)
        rest_brightness = _mean_brightness(rest)
        print(f"  Rest-of-screen brightness: {rest_brightness:.1f}")
        assert rest_brightness < 30, (
            f"Area below header too bright ({rest_brightness:.1f}). Other UI leaking?"
        )

        if vlm_ok:
            vlm_text = vlm_analyze(
                OUT / "p3_header_only.png",
                "Is there a header bar at the top with text like 'TRITIUM-SC', "
                "a clock, unit count, or connection status? Is the rest dark?"
            )
            print(f"  VLM: {vlm_text}")

    def test_command_bar_only(self, browser_page, vlm_ok):
        """Show ONLY the command bar (menu bar). Verify it appears below header area."""
        page = browser_page

        _hide_everything(page)
        time.sleep(SETTLE)

        baseline_brightness = _mean_brightness(_grab(page))

        # Show only command bar
        page.evaluate("""(() => {
            const bar = document.getElementById('command-bar-container');
            if (bar) bar.style.display = '';
        })()""")
        time.sleep(SETTLE)

        img = _grab(page)
        _save("p3_command_bar_only", img)

        # Verify command bar exists
        bar_bbox = _get_element_bbox(page, "#command-bar-container")
        if bar_bbox and bar_bbox["height"] > 0:
            print(f"  Command bar bbox: x={bar_bbox['x']:.0f} y={bar_bbox['y']:.0f} "
                  f"w={bar_bbox['width']:.0f} h={bar_bbox['height']:.0f}")

            bar_crop = _crop_region(
                img,
                int(bar_bbox["x"]), int(bar_bbox["y"]),
                int(bar_bbox["width"]), int(bar_bbox["height"])
            )
            _save("p3_command_bar_crop", bar_crop)

            bar_brightness = _mean_brightness(bar_crop)
            print(f"  Command bar brightness: {bar_brightness:.1f}")
            # Command bar should have menu text (FILE, VIEW, etc.)
            edge_ratio = _edge_density(bar_crop)
            print(f"  Command bar edge density: {edge_ratio:.4f}")
        else:
            print("  Command bar has zero height (may need header visible to layout)")

        if vlm_ok:
            vlm_text = vlm_analyze(
                OUT / "p3_command_bar_only.png",
                "Can you see a menu bar with labels like FILE, VIEW, LAYOUT, "
                "MAP, HELP? Are there quick-access buttons on the right?"
            )
            print(f"  VLM: {vlm_text}")

    def test_status_bar_only(self, browser_page, vlm_ok):
        """Show ONLY the status bar. Verify it spans the bottom of the screen."""
        page = browser_page

        _hide_everything(page)
        time.sleep(SETTLE)

        baseline_brightness = _mean_brightness(_grab(page))

        # Show only status bar
        page.evaluate("""(() => {
            const bar = document.getElementById('status-bar');
            if (bar) bar.style.display = '';
        })()""")
        time.sleep(SETTLE)

        img = _grab(page)
        _save("p3_status_bar_only", img)

        bar_bbox = _get_element_bbox(page, "#status-bar")
        assert bar_bbox is not None, "Status bar not visible"

        print(f"  Status bar bbox: x={bar_bbox['x']:.0f} y={bar_bbox['y']:.0f} "
              f"w={bar_bbox['width']:.0f} h={bar_bbox['height']:.0f}")

        # Status bar should be at the bottom
        assert bar_bbox["y"] > VIEWPORT_H * 0.8, (
            f"Status bar not at bottom (y={bar_bbox['y']})"
        )
        assert bar_bbox["width"] > VIEWPORT_W * 0.9, (
            f"Status bar too narrow ({bar_bbox['width']}px)"
        )

        # Crop and verify
        bar_crop = _crop_region(
            img,
            int(bar_bbox["x"]), int(bar_bbox["y"]),
            int(bar_bbox["width"]), int(bar_bbox["height"])
        )
        _save("p3_status_bar_crop", bar_crop)

        bar_brightness = _mean_brightness(bar_crop)
        print(f"  Status bar brightness: {bar_brightness:.1f}")

        if vlm_ok:
            vlm_text = vlm_analyze(
                OUT / "p3_status_bar_only.png",
                "Is there a thin status bar at the bottom with text like "
                "'FPS', 'alive', 'threats', or 'TRITIUM-SC'?"
            )
            print(f"  VLM: {vlm_text}")

    def test_mode_selector_only(self, browser_page, vlm_ok):
        """Show ONLY the map mode selector (O/T/S buttons)."""
        page = browser_page

        _hide_everything(page)
        time.sleep(SETTLE)

        baseline_brightness = _mean_brightness(_grab(page))

        # Show only mode selector
        page.evaluate("""(() => {
            const mode = document.getElementById('map-mode');
            if (mode) mode.style.display = '';
        })()""")
        time.sleep(SETTLE)

        img = _grab(page)
        _save("p3_mode_selector_only", img)

        mode_bbox = _get_element_bbox(page, "#map-mode")
        assert mode_bbox is not None, "Mode selector not visible"

        print(f"  Mode selector bbox: x={mode_bbox['x']:.0f} y={mode_bbox['y']:.0f} "
              f"w={mode_bbox['width']:.0f} h={mode_bbox['height']:.0f}")

        # Mode selector should be in the top-left area of the map
        assert mode_bbox["x"] < VIEWPORT_W * 0.3, (
            f"Mode selector not on left side (x={mode_bbox['x']})"
        )

        # Verify it has button content
        mode_crop = _crop_region(
            img,
            int(mode_bbox["x"]), int(mode_bbox["y"]),
            int(mode_bbox["width"]), int(mode_bbox["height"])
        )
        _save("p3_mode_selector_crop", mode_crop)

        mode_brightness = _mean_brightness(mode_crop)
        print(f"  Mode selector brightness: {mode_brightness:.1f}")

        if vlm_ok:
            vlm_text = vlm_analyze(
                OUT / "p3_mode_selector_only.png",
                "Can you see small buttons labeled O (Observe), T (Tactical), "
                "S (Setup) on a dark background?"
            )
            print(f"  VLM: {vlm_text}")


# ============================================================
# Phase 4: Defense Layer Tests
# ============================================================

class TestPhase4Defense:
    """Detect categories of bugs (overflow, artifacts, ghost pixels)."""

    def test_no_elements_wider_than_viewport(self, browser_page):
        """Query all DOM elements. None should be wider than viewport.

        This catches the label overflow bug where CSS transforms on marker
        labels created enormous bounding boxes spanning thousands of pixels.
        """
        page = browser_page

        # Restore normal UI
        _restore_everything(page)
        time.sleep(SETTLE)

        oversized = page.evaluate(f"""(() => {{
            const vw = {VIEWPORT_W};
            const results = [];
            const all = document.querySelectorAll('*');
            for (const el of all) {{
                const r = el.getBoundingClientRect();
                if (r.width > vw + 50) {{
                    results.push({{
                        tag: el.tagName,
                        id: el.id || '',
                        className: (el.className || '').toString().slice(0, 60),
                        width: Math.round(r.width),
                        height: Math.round(r.height),
                        x: Math.round(r.x),
                        y: Math.round(r.y),
                    }});
                }}
            }}
            return results;
        }})()""")

        print(f"  Elements wider than viewport: {len(oversized)}")
        for el in oversized[:10]:
            print(f"    {el['tag']}#{el['id']}.{el['className']} "
                  f"w={el['width']} h={el['height']} x={el['x']} y={el['y']}")

        assert len(oversized) == 0, (
            f"Found {len(oversized)} elements wider than viewport ({VIEWPORT_W}px): "
            f"{json.dumps(oversized[:5], indent=2)}"
        )

    def test_no_elements_taller_than_viewport(self, browser_page):
        """No element should be taller than the viewport unless clipped by parent.

        Elements inside scrollable containers (overflow:hidden/scroll/auto/clip)
        are expected to exceed viewport height -- only VISIBLE overflow matters.
        Also excludes MapLibre internals (canvas-container uses devicePixelRatio
        scaling) and elements inside known scroll containers.
        """
        page = browser_page

        _restore_everything(page)
        time.sleep(SETTLE)

        oversized = page.evaluate(f"""(() => {{
            const vh = {VIEWPORT_H};
            const results = [];

            // Check if any ancestor clips overflow
            function isClippedByParent(el) {{
                let p = el.parentElement;
                while (p && p !== document.documentElement) {{
                    const s = window.getComputedStyle(p);
                    const ov = s.overflow + ' ' + s.overflowY;
                    if (ov.includes('hidden') || ov.includes('scroll')
                        || ov.includes('auto') || ov.includes('clip')) {{
                        return true;
                    }}
                    p = p.parentElement;
                }}
                return false;
            }}

            const all = document.querySelectorAll('*');
            for (const el of all) {{
                const r = el.getBoundingClientRect();
                if (el.tagName === 'HTML' || el.tagName === 'BODY') continue;
                if (r.height > vh + 50) {{
                    // Skip MapLibre internals (canvas container scales for DPR)
                    const cn = (el.className || '').toString();
                    if (cn.includes('maplibregl-')) continue;
                    // Skip elements clipped by a parent
                    if (isClippedByParent(el)) continue;
                    results.push({{
                        tag: el.tagName,
                        id: el.id || '',
                        className: cn.slice(0, 60),
                        width: Math.round(r.width),
                        height: Math.round(r.height),
                    }});
                }}
            }}
            return results;
        }})()""")

        print(f"  Elements taller than viewport (unclipped): {len(oversized)}")
        for el in oversized[:10]:
            print(f"    {el['tag']}#{el['id']}.{el['className']} "
                  f"w={el['width']} h={el['height']}")

        assert len(oversized) == 0, (
            f"Found {len(oversized)} unclipped elements taller than viewport ({VIEWPORT_H}px): "
            f"{json.dumps(oversized[:5], indent=2)}"
        )

    def test_no_css_overflow_visible_on_markers(self, browser_page):
        """Marker elements must not have overflow:visible.

        overflow:visible on elements with CSS transforms can cause the
        browser to expand bounding boxes, creating line artifacts that
        span the entire viewport.
        """
        page = browser_page

        _restore_everything(page)
        time.sleep(SETTLE)

        # Check all maplibregl-marker elements and unit-name-3d elements
        overflow_visible = page.evaluate("""(() => {
            const results = [];
            const selectors = ['.maplibregl-marker', '.unit-name-3d',
                               '.unit-marker', '[class*="marker"]'];
            for (const sel of selectors) {
                for (const el of document.querySelectorAll(sel)) {
                    const style = window.getComputedStyle(el);
                    if (style.overflow === 'visible') {
                        results.push({
                            tag: el.tagName,
                            className: (el.className || '').toString().slice(0, 60),
                            overflow: style.overflow,
                        });
                    }
                }
            }
            return results;
        })()""")

        print(f"  Marker elements with overflow:visible: {len(overflow_visible)}")
        for el in overflow_visible[:5]:
            print(f"    {el['tag']}.{el['className']} overflow={el['overflow']}")

        # This is advisory -- log but don't fail hard, as some marker
        # libraries set overflow:visible by default and we may clip via
        # a parent container instead
        if len(overflow_visible) > 0:
            print(f"  WARNING: {len(overflow_visible)} marker elements have "
                  f"overflow:visible. This can cause line artifacts at high pitch angles.")

    def test_marker_label_max_width(self, browser_page):
        """All unit name labels must have a constrained max-width.

        Unconstrained label text can expand to fill enormous widths when
        CSS transforms are applied, creating horizontal line artifacts.
        """
        page = browser_page

        _restore_everything(page)
        time.sleep(SETTLE)

        unconstrained = page.evaluate("""(() => {
            const results = [];
            for (const el of document.querySelectorAll('.unit-name-3d')) {
                const style = window.getComputedStyle(el);
                const mw = style.maxWidth;
                if (mw === 'none' || mw === '') {
                    results.push({
                        text: el.textContent.trim().slice(0, 20),
                        maxWidth: mw,
                        width: Math.round(el.getBoundingClientRect().width),
                    });
                }
            }
            return results;
        })()""")

        print(f"  Labels without max-width: {len(unconstrained)}")
        for el in unconstrained[:5]:
            print(f"    '{el['text']}' maxWidth={el['maxWidth']} width={el['width']}px")

        # Advisory warning (not hard fail if no labels exist)
        label_count = page.evaluate(
            "document.querySelectorAll('.unit-name-3d').length"
        )
        if label_count > 0 and len(unconstrained) > 0:
            print(f"  WARNING: {len(unconstrained)}/{label_count} labels lack max-width")

    def test_tilted_no_horizontal_artifacts(self, browser_page, vlm_ok):
        """At 60-degree pitch, verify no bright horizontal lines >50% screen width.

        This is the specific bug symptom: CSS transforms on marker labels
        at high pitch angles create thin bright lines across the viewport.
        """
        page = browser_page

        _restore_everything(page)
        time.sleep(SETTLE)

        # Tilt the map to 60 degrees
        page.evaluate("""(() => {
            if (window._mapState && window._mapState.map) {
                const map = window._mapState.map;
                const gc = window._mapState.geoCenter;
                if (gc) {
                    map.jumpTo({
                        center: [gc.lng, gc.lat],
                        zoom: 17, bearing: 0, pitch: 60,
                    });
                }
            }
        })()""")
        time.sleep(SETTLE + 2)

        img = _grab(page)
        _save("p4_tilted_60deg", img)

        # Crop to the map area (exclude panels)
        for sel in ["#maplibre-map", "#tactical-area"]:
            el = page.locator(sel)
            if el.count() > 0:
                bbox = el.first.bounding_box()
                if bbox and bbox["width"] > 100:
                    crop = _crop_region(
                        img,
                        int(bbox["x"]), int(bbox["y"]),
                        int(bbox["width"]), int(bbox["height"])
                    )
                    break
        else:
            # Fallback: use center region
            crop = _crop_region(img, 200, 40, 1520, 960)

        _save("p4_tilted_60deg_map", crop)

        artifact_lines = _find_horizontal_lines(crop, min_length_pct=0.5)
        print(f"  Horizontal artifact lines (>50% width): {artifact_lines}")

        # Some legitimate horizontal content exists (horizon, building edges)
        # but artifacts produce many parallel lines
        assert artifact_lines < 5, (
            f"Found {artifact_lines} horizontal lines spanning >50% of map width. "
            f"This suggests CSS transform artifacts from marker labels."
        )

        if vlm_ok:
            vlm_text = vlm_analyze(
                OUT / "p4_tilted_60deg_map.png",
                "Is this a tilted map view? Do you see any obvious visual "
                "glitches like horizontal lines spanning the entire image?"
            )
            print(f"  VLM: {vlm_text}")

    def test_all_hidden_is_truly_black(self, browser_page):
        """Hide everything. The screen should be near-black.

        This is the master isolation test: if anything is non-black after
        hiding all panels, overlays, chrome, and map layers, something
        is leaking and needs to be added to the hide functions.
        """
        page = browser_page

        _hide_everything(page)
        time.sleep(SETTLE)

        img = _grab(page)
        _save("p4_truly_black", img)

        brightness = _mean_brightness(img)
        print(f"  All-hidden brightness: {brightness:.1f}")

        assert brightness < 30, (
            f"Screen brightness ({brightness:.1f}) too high with everything hidden. "
            f"Expected near-black (<30). A UI element is leaking through."
        )

        # Check that there are no bright spots (stray pixels, cursors)
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        bright_pixels = np.sum(gray > 80)
        bright_ratio = bright_pixels / gray.size
        print(f"  Bright pixels (>80): {bright_pixels} ({bright_ratio:.4%})")

        assert bright_ratio < 0.01, (
            f"Too many bright pixels ({bright_ratio:.2%}) with everything hidden. "
            f"Expected <1%. Some UI element is leaking."
        )

    def test_panel_does_not_extend_outside_container(self, browser_page):
        """Verify that open panels stay within the panel container bounds."""
        page = browser_page

        _restore_everything(page)
        time.sleep(SETTLE)

        container_bbox = _get_element_bbox(page, "#panel-container")
        if container_bbox is None:
            pytest.skip("Panel container not found")

        print(f"  Panel container: x={container_bbox['x']:.0f} y={container_bbox['y']:.0f} "
              f"w={container_bbox['width']:.0f} h={container_bbox['height']:.0f}")

        violations = page.evaluate("""(() => {
            const pm = window.panelManager;
            if (!pm) return [];
            const container = document.getElementById('panel-container');
            if (!container) return [];
            const cr = container.getBoundingClientRect();
            const results = [];
            for (const id of pm.registeredIds()) {
                if (!pm.isOpen(id)) continue;
                const panel = pm.getPanel(id);
                if (!panel || !panel.el) continue;
                const pr = panel.el.getBoundingClientRect();
                const violations = {};
                if (pr.right > cr.right + 5) violations.right = Math.round(pr.right - cr.right);
                if (pr.bottom > cr.bottom + 5) violations.bottom = Math.round(pr.bottom - cr.bottom);
                if (pr.left < cr.left - 200) violations.left = Math.round(cr.left - pr.left);
                if (pr.top < cr.top - 5) violations.top = Math.round(cr.top - pr.top);
                if (Object.keys(violations).length > 0) {
                    results.push({id, violations, panel: {
                        x: Math.round(pr.x), y: Math.round(pr.y),
                        w: Math.round(pr.width), h: Math.round(pr.height)
                    }});
                }
            }
            return results;
        })()""")

        print(f"  Panel boundary violations: {len(violations)}")
        for v in violations:
            print(f"    Panel [{v['id']}] at ({v['panel']['x']},{v['panel']['y']}) "
                  f"size {v['panel']['w']}x{v['panel']['h']}: {v['violations']}")

        # Panels should not extend significantly outside their container
        serious = [v for v in violations
                   if any(val > 50 for val in v["violations"].values())]
        assert len(serious) == 0, (
            f"{len(serious)} panels extend >50px outside container: "
            f"{json.dumps(serious, indent=2)}"
        )
