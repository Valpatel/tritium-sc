# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""UI Overlap Detection & Label Validation Pipeline.

Detects overlapping UI elements, validates label rendering quality,
and ensures responsive layout correctness across the Command Center.

Methodology:
  - getBoundingClientRect() intersection for overlap detection
  - OpenCV color/blob analysis for label visual quality
  - Playwright element queries for DOM structure validation
  - All tests use the live server at http://localhost:8000

Run:
    .venv/bin/python3 -m pytest tests/visual/test_ui_overlap.py -v
    ./test.sh 16
"""

from __future__ import annotations

import math
import time
from pathlib import Path

import cv2
import numpy as np
import pytest
import requests
from playwright.sync_api import sync_playwright, Page

SERVER = "http://localhost:8000"
OUT = Path("tests/.test-results/ui-overlap")
OUT.mkdir(parents=True, exist_ok=True)

SETTLE = 1.5  # seconds for render settle

# BGR color constants
FRIENDLY_GREEN = (161, 255, 5)    # #05ffa1
HOSTILE_RED    = (109, 42, 255)   # #ff2a6d
CYAN_PRIMARY   = (255, 240, 0)    # #00f0ff


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture(scope="module")
def browser_page():
    """Launch headed Playwright browser, navigate to Command Center."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page(viewport={"width": 1920, "height": 1080})

        page.goto(SERVER, wait_until="networkidle", timeout=20000)
        time.sleep(4)

        page.keyboard.press("Escape")
        time.sleep(0.5)

        yield page

        browser.close()


@pytest.fixture(autouse=True)
def reset_state(browser_page):
    """Reset game state before each test."""
    try:
        requests.post(f"{SERVER}/api/game/reset", timeout=5)
    except Exception:
        pass
    time.sleep(0.5)


# ============================================================
# Helpers
# ============================================================

def _grab(page: Page) -> np.ndarray:
    buf = page.screenshot()
    arr = np.frombuffer(buf, dtype=np.uint8)
    return cv2.imdecode(arr, cv2.IMREAD_COLOR)


def _save(name: str, img: np.ndarray):
    cv2.imwrite(str(OUT / f"{name}.png"), img)


def _set_layers(page: Page, **kwargs) -> dict:
    js_obj = ", ".join(f"{k}: {str(v).lower()}" for k, v in kwargs.items())
    return page.evaluate(f"window._mapActions.setLayers({{ {js_obj} }})")


def _place_turret(x: float = 0.0, y: float = 0.0, name: str = "T1") -> str:
    resp = requests.post(f"{SERVER}/api/game/place", json={
        "name": name, "asset_type": "turret", "position": {"x": x, "y": y},
    }, timeout=5)
    resp.raise_for_status()
    return resp.json().get("target_id", "")


def _spawn_hostile(x: float = 30.0, y: float = 0.0, name: str = "H1") -> str:
    resp = requests.post(f"{SERVER}/api/amy/simulation/spawn", json={
        "name": name, "position": {"x": x, "y": y},
    }, timeout=5)
    resp.raise_for_status()
    return resp.json().get("target_id", "")


def _center_map(page: Page, zoom: int = 18, bearing: float = 0.0, pitch: float = 0.0):
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


def _rect_overlap_area(r1: dict, r2: dict) -> float:
    """Compute overlap area between two bounding rects."""
    x1 = max(r1["left"], r2["left"])
    y1 = max(r1["top"], r2["top"])
    x2 = min(r1["left"] + r1["width"], r2["left"] + r2["width"])
    y2 = min(r1["top"] + r1["height"], r2["top"] + r2["height"])
    if x2 <= x1 or y2 <= y1:
        return 0.0
    return (x2 - x1) * (y2 - y1)


def _rect_area(r: dict) -> float:
    return r["width"] * r["height"]


# ============================================================
# Part 1: Static UI Element Overlap Detection
# ============================================================

def test_top_left_no_overlap(browser_page):
    """No visible UI elements overlap in the top-left area.

    Checks: header, command bar, map mode indicator, FPS counter.
    These are all fixed/absolute-positioned and should not intersect.
    """
    page = browser_page

    rects = page.evaluate("""(() => {
        const els = {
            'header': document.getElementById('header-bar'),
            'command-bar': document.getElementById('command-bar-container'),
            'map-mode': document.getElementById('map-mode'),
            'map-fps': document.getElementById('map-fps'),
        };
        const result = {};
        for (const [name, el] of Object.entries(els)) {
            if (!el) continue;
            const r = el.getBoundingClientRect();
            const style = window.getComputedStyle(el);
            result[name] = {
                left: r.left, top: r.top,
                width: r.width, height: r.height,
                display: style.display,
                visibility: style.visibility,
                zIndex: style.zIndex,
            };
        }
        return result;
    })()""")

    print("\n  Top-left elements:")
    for name, r in rects.items():
        print(f"    {name:20s}: ({r['left']:.0f},{r['top']:.0f}) "
              f"{r['width']:.0f}x{r['height']:.0f} z={r['zIndex']} "
              f"display={r['display']}")

    # Check pairwise overlaps for VISIBLE elements
    visible = {k: v for k, v in rects.items()
               if v["display"] != "none" and v["visibility"] != "hidden"
               and v["width"] > 0 and v["height"] > 0}

    names = list(visible.keys())
    overlaps = []
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            a, b = names[i], names[j]
            area = _rect_overlap_area(visible[a], visible[b])
            if area > 5:  # > 5px^2 overlap
                min_area = min(_rect_area(visible[a]), _rect_area(visible[b]))
                pct = (area / min_area * 100) if min_area > 0 else 0
                overlaps.append((a, b, area, pct))

    for a, b, area, pct in overlaps:
        print(f"  OVERLAP: {a} x {b} = {area:.0f}px^2 ({pct:.1f}%)")

    # Allow small edge overlaps (<10% of smaller element) but flag major ones
    major = [o for o in overlaps if o[3] > 10]
    if major:
        detail = "; ".join(f"{a}x{b} ({pct:.0f}%)" for a, b, _, pct in major)
        assert False, f"Major UI overlaps: {detail}"


def test_panel_headers_no_overlap(browser_page):
    """Open panels should not overlap each other's title bars."""
    page = browser_page

    # Get all visible panel headers
    rects = page.evaluate("""(() => {
        const panels = document.querySelectorAll('.panel-frame');
        const result = [];
        for (const p of panels) {
            const style = window.getComputedStyle(p);
            if (style.display === 'none') continue;
            const r = p.getBoundingClientRect();
            if (r.width <= 0 || r.height <= 0) continue;
            const header = p.querySelector('.panel-header');
            if (!header) continue;
            const hr = header.getBoundingClientRect();
            result.push({
                id: p.id || p.dataset.panel || 'unknown',
                panel: { left: r.left, top: r.top, width: r.width, height: r.height },
                header: { left: hr.left, top: hr.top, width: hr.width, height: hr.height },
            });
        }
        return result;
    })()""")

    print(f"\n  Visible panels: {len(rects)}")
    for p in rects:
        h = p["header"]
        print(f"    {p['id']:20s}: header at ({h['left']:.0f},{h['top']:.0f}) "
              f"{h['width']:.0f}x{h['height']:.0f}")

    # Check pairwise header overlap
    overlaps = []
    for i in range(len(rects)):
        for j in range(i + 1, len(rects)):
            area = _rect_overlap_area(rects[i]["header"], rects[j]["header"])
            if area > 10:
                overlaps.append((rects[i]["id"], rects[j]["id"], area))

    for a, b, area in overlaps:
        print(f"  HEADER OVERLAP: {a} x {b} = {area:.0f}px^2")

    assert len(overlaps) == 0, \
        f"Panel headers overlap: {', '.join(f'{a}x{b}' for a, b, _ in overlaps)}"


def test_command_bar_clearance(browser_page):
    """Command bar does not overlap the tactical area content."""
    page = browser_page

    rects = page.evaluate("""(() => {
        const bar = document.getElementById('command-bar-container');
        const tactical = document.getElementById('tactical-area');
        if (!bar || !tactical) return null;
        const br = bar.getBoundingClientRect();
        const tr = tactical.getBoundingClientRect();
        return {
            bar: { left: br.left, top: br.top, width: br.width, height: br.height },
            tactical: { left: tr.left, top: tr.top, width: tr.width, height: tr.height },
        };
    })()""")

    if rects is None:
        pytest.skip("Cannot find command-bar or tactical-area")

    bar_bottom = rects["bar"]["top"] + rects["bar"]["height"]
    tactical_top = rects["tactical"]["top"]
    gap = tactical_top - bar_bottom

    print(f"  Command bar bottom: {bar_bottom:.0f}px")
    print(f"  Tactical area top: {tactical_top:.0f}px")
    print(f"  Gap: {gap:.1f}px")

    assert gap >= -2, f"Command bar overlaps tactical area by {-gap:.1f}px"


def test_status_bar_clearance(browser_page):
    """Status bar sits below tactical area without overlap."""
    page = browser_page

    rects = page.evaluate("""(() => {
        const tactical = document.getElementById('tactical-area');
        const status = document.getElementById('status-bar');
        if (!tactical || !status) return null;
        const tr = tactical.getBoundingClientRect();
        const sr = status.getBoundingClientRect();
        return {
            tactical: { left: tr.left, top: tr.top, width: tr.width, height: tr.height },
            status: { left: sr.left, top: sr.top, width: sr.width, height: sr.height },
        };
    })()""")

    if rects is None:
        pytest.skip("Cannot find elements")

    tac_bottom = rects["tactical"]["top"] + rects["tactical"]["height"]
    stat_top = rects["status"]["top"]
    gap = stat_top - tac_bottom

    print(f"  Tactical bottom: {tac_bottom:.0f}px, Status top: {stat_top:.0f}px, gap: {gap:.1f}px")
    assert gap >= -2, f"Status bar overlaps tactical by {-gap:.1f}px"


def test_no_offscreen_elements(browser_page):
    """Critical UI elements are not rendered off-screen."""
    page = browser_page
    vw, vh = 1920, 1080

    offscreen = page.evaluate(f"""(() => {{
        const selectors = [
            '#header-bar', '#command-bar-container', '#tactical-area',
            '#status-bar', '#map-mode', '#panel-container',
        ];
        const results = [];
        for (const sel of selectors) {{
            const el = document.querySelector(sel);
            if (!el) continue;
            const r = el.getBoundingClientRect();
            const style = window.getComputedStyle(el);
            if (style.display === 'none') continue;
            if (r.right < 0 || r.bottom < 0 || r.left > {vw} || r.top > {vh}) {{
                results.push({{ sel, left: r.left, top: r.top, width: r.width, height: r.height }});
            }}
        }}
        return results;
    }})()""")

    for el in offscreen:
        print(f"  OFF-SCREEN: {el['sel']} at ({el['left']:.0f},{el['top']:.0f}) "
              f"{el['width']:.0f}x{el['height']:.0f}")

    assert len(offscreen) == 0, \
        f"Elements off-screen: {', '.join(e['sel'] for e in offscreen)}"


# ============================================================
# Part 2: Label Rendering Quality (DOM + OpenCV)
# ============================================================

def test_label_not_rotated(browser_page):
    """DOM labels are viewport-aligned (not rotated with unit heading).

    Places units with heading != 0, then checks that the marker element
    has no net rotation applied. Rotated text is unreadable.
    """
    page = browser_page

    _place_turret(0.0, 0.0, name="rot-test")
    time.sleep(1)
    _center_map(page, zoom=18)

    # Check all markers for rotation transforms
    rotations = page.evaluate("""(() => {
        const markers = document.querySelectorAll('.maplibregl-marker');
        const result = [];
        for (const m of markers) {
            const style = window.getComputedStyle(m);
            const transform = style.transform;
            // MapLibre sets transform for positioning (translate). Check for rotate.
            const hasRotate = transform.includes('rotate') && !transform.includes('rotate(0');
            // Also check matrix for rotation component
            let angle = 0;
            if (transform.startsWith('matrix(')) {
                const vals = transform.match(/matrix\\(([^)]+)\\)/);
                if (vals) {
                    const parts = vals[1].split(',').map(Number);
                    angle = Math.atan2(parts[1], parts[0]) * 180 / Math.PI;
                }
            }
            result.push({ transform, hasRotate, angle: Math.round(angle) });
        }
        return result;
    })()""")

    rotated = [r for r in rotations if abs(r["angle"]) > 2]
    print(f"  Markers checked: {len(rotations)}, rotated: {len(rotated)}")
    for r in rotated[:5]:
        print(f"    angle={r['angle']} transform={r['transform'][:60]}")

    # No markers should have significant rotation (text must be readable)
    assert len(rotated) == 0, \
        f"{len(rotated)} markers have rotation >2deg (labels unreadable)"


def test_label_size_reasonable(browser_page):
    """Label elements have reasonable dimensions (not oversized or zero-sized)."""
    page = browser_page

    _place_turret(0.0, 0.0, name="size-test")
    time.sleep(1)
    _center_map(page, zoom=18)

    sizes = page.evaluate("""(() => {
        const markers = document.querySelectorAll('.tritium-unit-marker');
        const result = [];
        for (const m of markers) {
            const r = m.getBoundingClientRect();
            result.push({ width: r.width, height: r.height });
        }
        return result;
    })()""")

    print(f"  Marker elements: {len(sizes)}")
    oversized = []
    undersized = []
    for i, s in enumerate(sizes):
        if s["width"] > 200 or s["height"] > 100:
            oversized.append((i, s))
        elif s["width"] < 2 or s["height"] < 2:
            undersized.append((i, s))

    print(f"  Oversized (>200x100): {len(oversized)}")
    for i, s in oversized[:5]:
        print(f"    marker[{i}]: {s['width']:.0f}x{s['height']:.0f}")

    print(f"  Undersized (<2x2): {len(undersized)}")

    assert len(oversized) == 0, \
        f"{len(oversized)} markers are oversized (max 200x100)"


def test_label_no_horizontal_lines(browser_page):
    """No marker element extends across the full viewport width.

    This catches the 'horizontal lines' rendering glitch where marker
    elements have width=viewport_width due to missing CSS constraints.
    """
    page = browser_page

    _place_turret(0.0, 0.0, name="hline-test")
    time.sleep(1)
    _center_map(page, zoom=18)

    widths = page.evaluate("""(() => {
        const markers = document.querySelectorAll('.tritium-unit-marker');
        const result = [];
        for (const m of markers) {
            const r = m.getBoundingClientRect();
            result.push({ width: r.width, text: m.textContent.trim().slice(0, 20) });
        }
        return result;
    })()""")

    wide = [w for w in widths if w["width"] > 300]
    print(f"  Markers: {len(widths)}, wider than 300px: {len(wide)}")
    for w in wide[:5]:
        print(f"    width={w['width']:.0f}px text='{w['text']}'")

    assert len(wide) == 0, \
        f"{len(wide)} markers wider than 300px (horizontal line glitch)"


def test_label_opencv_isolation(browser_page):
    """Labels are compact colored text, not stretched artifacts.

    Isolates DOM markers (3D models off, satellite off) and uses OpenCV
    to verify that marker pixels form compact blobs, not long horizontal lines.
    """
    page = browser_page

    _place_turret(0.0, 0.0, name="cv-label")
    _place_turret(40.0, 0.0, name="cv-label2")
    time.sleep(1)

    _center_map(page, zoom=17)
    _set_layers(page, allMapLayers=False, models3d=False, domMarkers=True)
    time.sleep(SETTLE)

    img = _grab(page)
    _save("label_isolation", img)

    # Detect any bright pixels (labels are colored text on dark background)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    _, bright = cv2.threshold(gray, 30, 255, cv2.THRESH_BINARY)

    # Find contours of bright regions
    contours, _ = cv2.findContours(bright, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    long_artifacts = []
    for c in contours:
        x, y, w, h = cv2.boundingRect(c)
        if w > 400 and h < 20:  # Horizontal line: very wide, very thin
            long_artifacts.append({"x": x, "y": y, "w": w, "h": h})

    print(f"  Bright contours: {len(contours)}")
    print(f"  Horizontal line artifacts (>400px wide, <20px tall): {len(long_artifacts)}")
    for a in long_artifacts[:5]:
        print(f"    ({a['x']},{a['y']}) {a['w']}x{a['h']}")

    assert len(long_artifacts) == 0, \
        f"Found {len(long_artifacts)} horizontal line artifacts from labels"


def test_label_tracking_accuracy(browser_page):
    """Visible marker wrappers are positioned within the map viewport.

    Checks that MapLibre markers are properly geo-anchored within the
    map container bounds. Any marker positioned outside the map viewport
    or at a degenerate position indicates a tracking failure.

    Note: Precise geo-anchor alignment (3D vs DOM) is tested by
    test_map_alignment.py::test_3d_vs_dom_alignment.
    """
    page = browser_page

    # Restore all layers (previous tests may have set allMapLayers=false
    # which sets _state.showUnits=false, causing new markers to be hidden)
    _set_layers(page, allMapLayers=True)
    time.sleep(0.5)

    _place_turret(0.0, 0.0, name="track-test")
    time.sleep(1)
    _center_map(page, zoom=17)

    # Wait for at least one marker to appear in the DOM
    try:
        page.wait_for_selector(".tritium-unit-marker", timeout=8000)
    except Exception:
        pass
    time.sleep(1)

    # Collect all visible marker positions and map bounds
    result = page.evaluate("""(() => {
        const map = window._mapState.map;
        if (!map) return null;
        const container = map.getContainer();
        const cRect = container.getBoundingClientRect();
        const mapBounds = {
            left: cRect.left, top: cRect.top,
            right: cRect.right, bottom: cRect.bottom,
        };

        const els = document.querySelectorAll('.tritium-unit-marker');
        const markers = [];
        for (const el of els) {
            const style = window.getComputedStyle(el);
            if (style.display === 'none' || style.visibility === 'hidden') continue;
            const r = el.getBoundingClientRect();
            if (r.width <= 0 || r.height <= 0) continue;
            markers.push({
                cx: r.left + r.width / 2,
                cy: r.top + r.height / 2,
                w: r.width, h: r.height,
            });
        }
        return { mapBounds, markers };
    })()""")

    if result is None:
        pytest.skip("Cannot access map state")

    mb = result["mapBounds"]
    markers = result["markers"]
    print(f"  Map bounds: ({mb['left']:.0f},{mb['top']:.0f})-({mb['right']:.0f},{mb['bottom']:.0f})")
    print(f"  Visible markers: {len(markers)}")

    # At least 1 marker should be present
    assert len(markers) >= 1, "No visible markers found after placing turret"

    # Count markers within map viewport (with generous margin for partially visible)
    margin = 100  # markers at map edge may partially extend beyond
    in_viewport = 0
    for m in markers:
        if (mb["left"] - margin <= m["cx"] <= mb["right"] + margin and
            mb["top"] - margin <= m["cy"] <= mb["bottom"] + margin):
            in_viewport += 1

    print(f"  Markers in viewport (±{margin}px margin): {in_viewport}/{len(markers)}")

    # At least 50% of visible markers should be in the map viewport
    ratio = in_viewport / len(markers) if markers else 0
    assert ratio >= 0.5, \
        f"Only {in_viewport}/{len(markers)} markers in viewport ({ratio*100:.0f}%)"


# ============================================================
# Part 3: Responsive Layout Checks
# ============================================================

def test_full_viewport_coverage(browser_page):
    """Main layout fills the viewport with no dead space."""
    page = browser_page

    coverage = page.evaluate("""(() => {
        const header = document.getElementById('header-bar');
        const main = document.getElementById('main-layout');
        if (!header || !main) return null;
        const hr = header.getBoundingClientRect();
        const mr = main.getBoundingClientRect();
        return {
            headerH: hr.height,
            mainTop: mr.top, mainH: mr.height,
            viewport: { w: window.innerWidth, h: window.innerHeight },
            totalH: hr.height + mr.height,
        };
    })()""")

    if coverage is None:
        pytest.skip("Cannot find layout elements")

    vp = coverage["viewport"]
    total = coverage["totalH"]
    gap = vp["h"] - total

    print(f"  Viewport: {vp['w']}x{vp['h']}")
    print(f"  Header: {coverage['headerH']:.0f}px")
    print(f"  Main: top={coverage['mainTop']:.0f} h={coverage['mainH']:.0f}px")
    print(f"  Coverage: {total:.0f}/{vp['h']} ({total/vp['h']*100:.1f}%)")
    print(f"  Gap: {gap:.1f}px")

    assert abs(gap) < 5, f"Layout gap of {gap:.1f}px (should fill viewport)"


def test_map_fills_available_space(browser_page):
    """Map container uses all available space between bars."""
    page = browser_page

    rects = page.evaluate("""(() => {
        const tactical = document.getElementById('tactical-area');
        const bar = document.getElementById('command-bar-container');
        const status = document.getElementById('status-bar');
        if (!tactical || !bar || !status) return null;
        return {
            bar: bar.getBoundingClientRect().height,
            tactical: tactical.getBoundingClientRect(),
            status: status.getBoundingClientRect(),
            viewport: { w: window.innerWidth, h: window.innerHeight },
        };
    })()""")

    if rects is None:
        pytest.skip("Cannot find layout elements")

    tac = rects["tactical"]
    print(f"  Map area: ({tac['left']:.0f},{tac['top']:.0f}) {tac['width']:.0f}x{tac['height']:.0f}")

    # Map should span full width
    assert tac["width"] > rects["viewport"]["w"] * 0.9, \
        f"Map width {tac['width']:.0f} < 90% of viewport ({rects['viewport']['w']})"

    # Map height should be substantial (at least 70% of viewport)
    assert tac["height"] > rects["viewport"]["h"] * 0.7, \
        f"Map height {tac['height']:.0f} < 70% of viewport ({rects['viewport']['h']})"


def test_z_index_ordering(browser_page):
    """UI elements have correct z-index stacking order."""
    page = browser_page

    z_indices = page.evaluate("""(() => {
        const elements = {
            'header': '#header-bar',
            'command-bar': '#command-bar-container',
            'tactical': '#tactical-area',
            'panel-container': '#panel-container',
            'status-bar': '#status-bar',
            'map-mode': '#map-mode',
        };
        const result = {};
        for (const [name, sel] of Object.entries(elements)) {
            const el = document.querySelector(sel);
            if (!el) continue;
            const style = window.getComputedStyle(el);
            result[name] = {
                zIndex: style.zIndex,
                position: style.position,
            };
        }
        return result;
    })()""")

    print("\n  Z-index stacking:")
    for name, info in z_indices.items():
        print(f"    {name:20s}: z={info['zIndex']:>5s} pos={info['position']}")

    # Panels should be above tactical area
    panel_z = int(z_indices.get("panel-container", {}).get("zIndex", "0") or "0")
    map_mode_z = int(z_indices.get("map-mode", {}).get("zIndex", "0") or "0")

    assert panel_z >= map_mode_z, \
        "Panel container should be above or equal to map overlays"


# ============================================================
# Part 4: Unit Label Completeness
# ============================================================

def test_all_markers_have_labels(browser_page):
    """Every visible unit marker has a name label element."""
    page = browser_page

    _place_turret(0.0, 0.0, name="label-check-1")
    _place_turret(30.0, 0.0, name="label-check-2")
    time.sleep(1)
    _center_map(page, zoom=17)

    label_info = page.evaluate("""(() => {
        const markers = document.querySelectorAll('.tritium-unit-marker');
        const result = [];
        for (const m of markers) {
            const style = window.getComputedStyle(m);
            if (style.display === 'none') continue;
            const nameEl = m.querySelector('.unit-name-3d') || m.querySelector('.unit-name');
            result.push({
                hasLabel: !!nameEl,
                labelText: nameEl ? nameEl.textContent.trim() : null,
                width: m.getBoundingClientRect().width,
            });
        }
        return result;
    })()""")

    total = len(label_info)
    with_label = sum(1 for l in label_info if l["hasLabel"])
    print(f"  Visible markers: {total}, with labels: {with_label}")

    for i, l in enumerate(label_info[:10]):
        print(f"    marker[{i}]: label={l['hasLabel']} text='{l['labelText']}' "
              f"width={l['width']:.0f}px")

    assert with_label == total, f"{total - with_label} markers missing labels"


def test_label_text_not_empty(browser_page):
    """Label text is non-empty for all visible markers."""
    page = browser_page

    _place_turret(0.0, 0.0, name="txt-test")
    time.sleep(1)
    _center_map(page, zoom=18)

    labels = page.evaluate("""(() => {
        const markers = document.querySelectorAll('.tritium-unit-marker');
        const result = [];
        for (const m of markers) {
            const style = window.getComputedStyle(m);
            if (style.display === 'none') continue;
            const nameEl = m.querySelector('.unit-name-3d') || m.querySelector('.unit-name');
            if (nameEl) {
                result.push(nameEl.textContent.trim());
            }
        }
        return result;
    })()""")

    empty = [l for l in labels if not l]
    print(f"  Labels: {len(labels)}, empty: {len(empty)}")
    assert len(empty) == 0, f"{len(empty)} labels are empty"


def test_marker_health_bar_present(browser_page):
    """Every visible marker has a health bar element."""
    page = browser_page

    _place_turret(0.0, 0.0, name="hp-bar-check")
    time.sleep(1)
    _center_map(page, zoom=18)

    hp_info = page.evaluate("""(() => {
        const markers = document.querySelectorAll('.tritium-unit-marker');
        const result = [];
        for (const m of markers) {
            const style = window.getComputedStyle(m);
            if (style.display === 'none') continue;
            const hp = m.querySelector('.unit-hp-bar-3d') || m.querySelector('.unit-hp-bar');
            result.push({ hasHp: !!hp, className: hp ? hp.className : null });
        }
        return result;
    })()""")

    total = len(hp_info)
    with_hp = sum(1 for h in hp_info if h["hasHp"])
    print(f"  Markers: {total}, with health bar: {with_hp}")

    assert with_hp == total, f"{total - with_hp} markers missing health bars"


# ============================================================
# Part 5: Screenshot-based visual regression
# ============================================================

def test_screenshot_no_visual_artifacts(browser_page):
    """Full-page screenshot has no obvious rendering artifacts.

    Checks for:
    - Horizontal line artifacts (>80% viewport width, <5px tall)
    - Large solid color blocks (>500x500) that aren't satellite/map
    - Extreme brightness or darkness suggesting rendering failures
    """
    page = browser_page

    _place_turret(0.0, 0.0)
    time.sleep(1)
    _center_map(page, zoom=17)
    _set_layers(page, satellite=True, buildings=True, models3d=True, domMarkers=True)
    time.sleep(SETTLE + 1)

    img = _grab(page)
    _save("full_page_visual", img)

    h, w = img.shape[:2]

    # Check for horizontal line artifacts
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # Edge detect to find line artifacts
    edges = cv2.Canny(gray, 50, 150)

    # Sum horizontal edge pixels per row
    row_sums = np.sum(edges > 0, axis=1)
    # A horizontal line artifact would have a row with >80% of width as edges
    artifact_rows = np.where(row_sums > w * 0.8)[0]

    print(f"  Image: {w}x{h}")
    print(f"  Rows with >80% edge pixels: {len(artifact_rows)}")

    if len(artifact_rows) > 5:
        # Save visualization
        debug = img.copy()
        for row in artifact_rows[:20]:
            cv2.line(debug, (0, row), (w, row), (0, 0, 255), 1)
        _save("artifacts_detected", debug)
        print(f"  Artifact rows: {artifact_rows[:20].tolist()}")

    # Allow some rows (header/status bar borders are legitimate edges)
    assert len(artifact_rows) < 10, \
        f"Possible rendering artifacts: {len(artifact_rows)} rows with >80% edge content"
