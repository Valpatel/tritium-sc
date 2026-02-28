# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Multi-unit visual validation tests.

Verifies that the system correctly renders, tracks, and removes multiple
friendly and hostile units on the tactical map.  Uses a dual validation
strategy:
  - Primary: Playwright DOM queries for .tritium-unit-marker elements
  - Cross-validation: OpenCV blob detection on screenshots

The unit markers render as DOM overlay elements on MapLibre with
alliance-specific colors (#05ffa1 friendly, #ff2a6d hostile).  In 3D mode
markers are name labels; in 2D mode they are icon circles.  Both modes
use the same marker CSS class and data attributes.

Run:
    .venv/bin/python3 -m pytest tests/visual/test_multi_unit.py -v

Requires a running server (auto-started by the TritiumServer fixture).
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

from tests.lib.server_manager import TritiumServer

pytestmark = pytest.mark.visual

# BGR color constants (matching cybercore.css)
FRIENDLY_GREEN = (161, 255, 5)    # #05ffa1
HOSTILE_RED    = (109, 42, 255)   # #ff2a6d

OUT = Path("tests/.test-results/multi-unit")
OUT.mkdir(parents=True, exist_ok=True)

SETTLE = 2.5          # seconds for render to settle
COLOR_TOL = 55        # BGR color match tolerance


# ============================================================
# Helpers -- Screenshots & OpenCV
# ============================================================

def _grab(page: Page) -> np.ndarray:
    """Full page screenshot as BGR numpy array."""
    buf = page.screenshot()
    arr = np.frombuffer(buf, dtype=np.uint8)
    return cv2.imdecode(arr, cv2.IMREAD_COLOR)


def _get_map_bounds(page: Page) -> dict:
    """Get the map container's bounding rect in viewport pixels."""
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


def _detect_color_blobs(img: np.ndarray, bgr: tuple, tolerance: int = COLOR_TOL,
                        min_area: int = 10, max_aspect: float = 8.0) -> list[dict]:
    """Detect blobs of a specific color.

    Uses relaxed defaults (min_area=10, max_aspect=8) to catch small DOM
    marker elements which may be thin labels or small circles.

    Returns list of {centroid, area, bbox, aspect_ratio}.
    """
    lower = np.array([max(0, c - tolerance) for c in bgr], dtype=np.uint8)
    upper = np.array([min(255, c + tolerance) for c in bgr], dtype=np.uint8)
    mask = cv2.inRange(img, lower, upper)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    blobs = []
    for c in contours:
        area = cv2.contourArea(c)
        if area < min_area:
            continue
        M = cv2.moments(c)
        if M["m00"] == 0:
            continue
        cx = int(M["m10"] / M["m00"])
        cy = int(M["m01"] / M["m00"])
        x, y, w, h = cv2.boundingRect(c)
        aspect = max(w, h) / max(1, min(w, h))
        if aspect > max_aspect:
            continue
        blobs.append({
            "centroid": (cx, cy),
            "area": area,
            "bbox": (x, y, w, h),
            "aspect_ratio": aspect,
        })
    return blobs


def _has_color(img: np.ndarray, bgr: tuple, tolerance: int = COLOR_TOL,
               min_pixels: int = 20) -> bool:
    """Check if image has enough pixels matching the given BGR color."""
    lower = np.array([max(0, c - tolerance) for c in bgr], dtype=np.uint8)
    upper = np.array([min(255, c + tolerance) for c in bgr], dtype=np.uint8)
    mask = cv2.inRange(img, lower, upper)
    return int(cv2.countNonZero(mask)) >= min_pixels


def _distance(p1: tuple, p2: tuple) -> float:
    """Euclidean distance between two points."""
    return math.sqrt((p1[0] - p2[0]) ** 2 + (p1[1] - p2[1]) ** 2)


def _save(name: str, img: np.ndarray):
    """Save debug image."""
    cv2.imwrite(str(OUT / f"{name}.png"), img)


# ============================================================
# Helpers -- DOM Marker Queries
# ============================================================

def _count_dom_markers(page: Page, alliance: str | None = None) -> int:
    """Count .tritium-unit-marker DOM elements, optionally filtered by alliance.

    This is the ground-truth count: if MapLibre created a marker for the unit,
    it will have a DOM element regardless of whether OpenCV can detect it in a
    screenshot.
    """
    if alliance:
        sel = f'.tritium-unit-marker[data-alliance="{alliance}"]'
    else:
        sel = '.tritium-unit-marker'
    return page.locator(sel).count()


def _get_dom_marker_ids(page: Page, alliance: str | None = None) -> list[str]:
    """Get data-unit-id values from marker DOM elements."""
    if alliance:
        sel = f'.tritium-unit-marker[data-alliance="{alliance}"]'
    else:
        sel = '.tritium-unit-marker'
    return page.eval_on_selector_all(
        sel, "els => els.map(e => e.dataset.unitId || '')"
    )


def _get_marker_viewport_pos(page: Page, target_id: str) -> tuple[float, float] | None:
    """Get a marker's viewport position via its bounding box center."""
    sel = f'.tritium-unit-marker[data-unit-id="{target_id}"]'
    loc = page.locator(sel)
    if loc.count() == 0:
        return None
    bbox = loc.first.bounding_box()
    if bbox is None:
        return None
    return (bbox["x"] + bbox["width"] / 2, bbox["y"] + bbox["height"] / 2)


def _get_projected_pos(page: Page, target_id: str) -> tuple[float, float] | None:
    """Get marker position via map.project() -- the geo-anchor in viewport coords."""
    result = page.evaluate(f"""(() => {{
        if (!window._mapState) return null;
        const marker = window._mapState.unitMarkers['{target_id}'];
        if (!marker) return null;
        const lngLat = marker.getLngLat();
        const point = window._mapState.map.project(lngLat);
        const container = window._mapState.map.getContainer();
        const rect = container.getBoundingClientRect();
        return {{ x: rect.left + point.x, y: rect.top + point.y }};
    }})()""")
    if result is None:
        return None
    return (result["x"], result["y"])


def _sync_store_removal(page: Page, target_id: str):
    """Remove a unit from the TritiumStore so the frontend cleans up markers.

    The backend DELETE API removes the unit from the simulation engine, but the
    frontend store is only updated via WebSocket telemetry batches (which add/update
    but never explicitly remove).  This call simulates the cleanup that would
    happen once the telemetry batch no longer includes the removed unit, or when
    a proper 'target_removed' WebSocket event is implemented.
    """
    page.evaluate(f"window.TritiumStore && window.TritiumStore.removeUnit('{target_id}')")


# ============================================================
# Helpers -- Game API
# ============================================================

def _place_turret(server_url: str, x: float = 0.0, y: float = 0.0,
                  name: str = "Alpha-1") -> str:
    """Place a friendly turret via the game API. Returns target_id."""
    resp = requests.post(f"{server_url}/api/game/place", json={
        "name": name, "asset_type": "turret", "position": {"x": x, "y": y},
    }, timeout=5)
    resp.raise_for_status()
    data = resp.json()
    return data.get("target_id", "")


def _spawn_hostile(server_url: str, x: float = 30.0, y: float = 0.0,
                   name: str = "hostile-test") -> str:
    """Spawn a hostile via the simulation API. Returns target_id."""
    resp = requests.post(f"{server_url}/api/amy/simulation/spawn", json={
        "name": name, "alliance": "hostile", "asset_type": "rover",
        "position": {"x": x, "y": y},
    }, timeout=5)
    resp.raise_for_status()
    data = resp.json()
    target = data.get("target", {})
    return target.get("target_id", "")


def _remove_target(server_url: str, target_id: str) -> bool:
    """Remove a simulation target. Returns True if removed."""
    resp = requests.delete(
        f"{server_url}/api/amy/simulation/targets/{target_id}", timeout=5,
    )
    return resp.status_code == 200


def _reset_game(server_url: str):
    """Reset game to setup state."""
    try:
        requests.post(f"{server_url}/api/game/reset", timeout=5)
    except Exception:
        pass


def _get_targets(server_url: str) -> list[dict]:
    """Get all simulation targets."""
    resp = requests.get(f"{server_url}/api/amy/simulation/targets", timeout=5)
    resp.raise_for_status()
    data = resp.json()
    return data.get("targets", [])


# ============================================================
# Helpers -- Map Control
# ============================================================

def _center_map(page: Page, zoom: int = 18, bearing: float = 0.0,
                pitch: float = 0.0):
    """Center map on (0,0) game coords with specified zoom/bearing/pitch."""
    page.evaluate(f"""(() => {{
        const map = window._mapState && window._mapState.map;
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
def server():
    """Start a TritiumServer for this module."""
    srv = TritiumServer(auto_port=True)
    srv.start()
    yield srv
    srv.stop()


@pytest.fixture(scope="module")
def browser_page(server):
    """Launch headless Playwright browser, navigate to Command Center."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1920, "height": 1080})

        page.goto(server.url, wait_until="networkidle", timeout=30000)
        time.sleep(4)

        # Dismiss any modal
        page.keyboard.press("Escape")
        time.sleep(0.5)

        yield page

        browser.close()


@pytest.fixture(autouse=True)
def reset_between_tests(server, browser_page):
    """Reset game state before each test."""
    _reset_game(server.url)
    time.sleep(1.5)


# ============================================================
# Test 1: Spawn 5 friendly units and verify 5 green blobs
# ============================================================

def test_spawn_5_friendly_units(server, browser_page):
    """Place 5 turrets at known positions, verify 5 show up.

    Positions: (0,0), (50,0), (0,50), (-50,0), (0,-50) -- spread around origin.
    Primary: count DOM markers with data-alliance="friendly".
    Cross-validation: OpenCV detects alliance-colored pixels in the map area.
    """
    page = browser_page
    url = server.url

    # Record baseline marker count (pre-existing level units)
    baseline_markers = _count_dom_markers(page, "friendly")

    positions = [
        (0.0, 0.0, "T-Center"),
        (50.0, 0.0, "T-East"),
        (0.0, 50.0, "T-North"),
        (-50.0, 0.0, "T-West"),
        (0.0, -50.0, "T-South"),
    ]

    placed_ids = []
    for x, y, name in positions:
        tid = _place_turret(url, x=x, y=y, name=name)
        placed_ids.append(tid)
        assert tid, f"Failed to place turret at ({x}, {y})"

    time.sleep(2.0)

    # Center map to see all 5 units
    _center_map(page, zoom=16, bearing=0, pitch=0)

    # Primary: DOM marker count
    friendly_count = _count_dom_markers(page, "friendly")
    new_markers = friendly_count - baseline_markers
    print(f"\n  Baseline friendly markers: {baseline_markers}")
    print(f"  After placement: {friendly_count} (+{new_markers} new)")

    # Screenshot for cross-validation
    img = _grab(page)
    _save("01_five_friendlies", img)

    map_bounds = _get_map_bounds(page)
    crop = _crop_to_map(img, map_bounds)
    _save("01_five_friendlies_crop", crop)

    # Cross-validation: green pixels in the map area
    green_present = _has_color(crop, FRIENDLY_GREEN, tolerance=COLOR_TOL,
                               min_pixels=20)
    print(f"  Green color present in map: {green_present}")

    # Assert: at least 5 new friendly markers created
    assert new_markers >= 5, (
        f"Expected at least 5 new friendly markers, found {new_markers} "
        f"(baseline={baseline_markers}, total={friendly_count})"
    )
    assert green_present, (
        "Expected green (#05ffa1) pixels in map area for friendly markers"
    )


# ============================================================
# Test 2: Spawn hostile and verify red/magenta presence
# ============================================================

def test_spawn_hostile(server, browser_page):
    """Spawn a hostile at (30, 30), verify a hostile marker appears.

    Primary: DOM marker with data-alliance="hostile".
    Cross-validation: OpenCV detects red (#ff2a6d) pixels in the map area.
    """
    page = browser_page
    url = server.url

    baseline_hostiles = _count_dom_markers(page, "hostile")

    tid = _spawn_hostile(url, x=30.0, y=30.0, name="hostile-vis-test")
    assert tid, "Failed to spawn hostile"

    time.sleep(2.0)
    _center_map(page, zoom=17, bearing=0, pitch=0)

    # Primary: DOM hostile marker count
    hostile_count = _count_dom_markers(page, "hostile")
    new_hostiles = hostile_count - baseline_hostiles
    print(f"\n  Baseline hostile markers: {baseline_hostiles}")
    print(f"  After spawn: {hostile_count} (+{new_hostiles} new)")

    # Cross-validation: screenshot
    img = _grab(page)
    _save("02_hostile_spawn", img)
    map_bounds = _get_map_bounds(page)
    crop = _crop_to_map(img, map_bounds)
    _save("02_hostile_spawn_crop", crop)

    red_blobs = _detect_color_blobs(crop, HOSTILE_RED, tolerance=COLOR_TOL,
                                    min_area=8, max_aspect=10.0)
    print(f"  Red blobs (OpenCV): {len(red_blobs)}")
    for i, b in enumerate(red_blobs[:5]):
        print(f"    blob[{i}]: centroid={b['centroid']} area={b['area']:.0f}")

    assert new_hostiles >= 1, (
        f"Expected at least 1 new hostile marker, found {new_hostiles}"
    )
    assert len(red_blobs) >= 1, (
        f"Expected at least 1 red blob for hostile unit, found {len(red_blobs)}"
    )


# ============================================================
# Test 3: Friendly and hostile colors are distinct
# ============================================================

def test_friendly_and_hostile_colors(server, browser_page):
    """Place both friendly and hostile units, verify both alliances present.

    Primary: DOM markers for both alliances exist.
    Cross-validation: Both green and red pixels are present in the screenshot,
    and the markers are spatially separated (checked via map.project positions).
    """
    page = browser_page
    url = server.url

    ftid = _place_turret(url, x=0.0, y=0.0, name="Friendly-1")
    assert ftid, "Failed to place friendly"

    htid = _spawn_hostile(url, x=40.0, y=0.0, name="Hostile-1")
    assert htid, "Failed to spawn hostile"

    time.sleep(2.0)
    _center_map(page, zoom=17, bearing=0, pitch=0)

    # Primary: both alliances have markers
    friendly_ids = _get_dom_marker_ids(page, "friendly")
    hostile_ids = _get_dom_marker_ids(page, "hostile")
    print(f"\n  Friendly marker IDs: {len(friendly_ids)}")
    print(f"  Hostile marker IDs: {len(hostile_ids)}")

    assert ftid in friendly_ids, f"Placed friendly '{ftid}' not in DOM markers"
    assert htid in hostile_ids, f"Spawned hostile '{htid}' not in DOM markers"

    # Cross-validation: screenshot colors
    img = _grab(page)
    _save("03_both_colors", img)
    map_bounds = _get_map_bounds(page)
    crop = _crop_to_map(img, map_bounds)
    _save("03_both_colors_crop", crop)

    green_present = _has_color(crop, FRIENDLY_GREEN, tolerance=COLOR_TOL,
                               min_pixels=10)
    red_present = _has_color(crop, HOSTILE_RED, tolerance=COLOR_TOL,
                             min_pixels=10)
    print(f"  Green (friendly) pixels: {green_present}")
    print(f"  Red (hostile) pixels: {red_present}")

    assert green_present, "Expected green pixels for friendly marker"
    assert red_present, "Expected red pixels for hostile marker"

    # Verify spatial separation via map.project() positions
    fpos = _get_projected_pos(page, ftid)
    hpos = _get_projected_pos(page, htid)
    if fpos and hpos:
        dist = _distance(fpos, hpos)
        print(f"  Friendly projected: {fpos}, Hostile projected: {hpos}, "
              f"distance: {dist:.1f}px")
        assert dist >= 10.0, (
            f"Friendly and hostile markers too close ({dist:.1f}px)"
        )


# ============================================================
# Test 4: Unit positions match expected relative layout
# ============================================================

def test_unit_positions_match_expected(server, browser_page):
    """Place units at known positions, verify their projected screen positions
    have the correct relative arrangement.

    Places 3 units in an L-shape:
      A at (20, 20), B at (-20, 20), C at (20, -20)
    Verifies:
      - All 3 have map.project() positions within the map bounds
      - A and B have the same Y (same northing), different X
      - A and C have the same X (same easting), different Y
      - Positions are separated by a meaningful distance
    """
    page = browser_page
    url = server.url

    units = [
        (20.0, 20.0, "Pos-A"),
        (-20.0, 20.0, "Pos-B"),
        (20.0, -20.0, "Pos-C"),
    ]

    placed = []
    for x, y, name in units:
        tid = _place_turret(url, x=x, y=y, name=name)
        assert tid, f"Failed to place turret at ({x}, {y})"
        placed.append((tid, x, y, name))

    time.sleep(2.0)
    _center_map(page, zoom=17, bearing=0, pitch=0)

    img = _grab(page)
    _save("04_position_match", img)

    # Get projected positions for each unit
    positions = {}
    map_bounds = _get_map_bounds(page)
    for tid, x, y, name in placed:
        pos = _get_projected_pos(page, tid)
        if pos is not None:
            positions[name] = pos
            print(f"    {name} ({tid}): game=({x},{y}) -> screen=({pos[0]:.0f},{pos[1]:.0f})")
        else:
            print(f"    {name} ({tid}): no projection available")

    assert len(positions) >= 3, (
        f"Expected projections for all 3 units, got {len(positions)}"
    )

    a = positions["Pos-A"]
    b = positions["Pos-B"]
    c = positions["Pos-C"]

    # A and B share y=20 game coords, so should have similar screen Y
    # (within 10px tolerance for sub-pixel differences)
    y_diff_ab = abs(a[1] - b[1])
    print(f"    A-B Y difference: {y_diff_ab:.1f}px (expect < 10)")
    assert y_diff_ab < 10, (
        f"A and B at same game-Y should have similar screen-Y, diff={y_diff_ab:.1f}px"
    )

    # A and C share x=20 game coords, so should have similar screen X
    x_diff_ac = abs(a[0] - c[0])
    print(f"    A-C X difference: {x_diff_ac:.1f}px (expect < 10)")
    assert x_diff_ac < 10, (
        f"A and C at same game-X should have similar screen-X, diff={x_diff_ac:.1f}px"
    )

    # A and B should be separated horizontally (40m apart at zoom 17)
    x_diff_ab = abs(a[0] - b[0])
    print(f"    A-B X separation: {x_diff_ab:.1f}px (expect > 20)")
    assert x_diff_ab > 20, (
        f"A and B should be horizontally separated, diff={x_diff_ab:.1f}px"
    )

    # A and C should be separated vertically (40m apart at zoom 17)
    y_diff_ac = abs(a[1] - c[1])
    print(f"    A-C Y separation: {y_diff_ac:.1f}px (expect > 20)")
    assert y_diff_ac > 20, (
        f"A and C should be vertically separated, diff={y_diff_ac:.1f}px"
    )


# ============================================================
# Test 5: Unit removal -- API + store cleanup + DOM verification
# ============================================================

def test_unit_removal(server, browser_page):
    """Place a unit, verify it exists in API and DOM, remove via API,
    sync the store, verify the DOM marker is gone.

    The full removal flow:
      1. DELETE /api/amy/simulation/targets/{id} removes from engine
      2. TritiumStore.removeUnit(id) cleans up the client store
      3. _updateUnits() loop removes the marker from DOM

    Step 2 is called explicitly because the current WebSocket protocol
    does not send target_removed events -- the store only gets add/update
    via telemetry batches.
    """
    page = browser_page
    url = server.url

    baseline_count = _count_dom_markers(page, "friendly")

    # Place a turret at origin
    tid = _place_turret(url, x=0.0, y=0.0, name="Remove-Me")
    assert tid, "Failed to place turret"
    time.sleep(2.0)
    _center_map(page, zoom=18, bearing=0, pitch=0)

    # Verify marker present in DOM
    after_place = _count_dom_markers(page, "friendly")
    marker_exists = page.locator(
        f'.tritium-unit-marker[data-unit-id="{tid}"]'
    ).count()
    print(f"\n  After place: {after_place} friendly markers "
          f"(baseline={baseline_count}), target marker exists={marker_exists}")
    assert marker_exists == 1, f"Expected marker for '{tid}' to exist"

    # Verify in API
    targets_before = _get_targets(url)
    target_ids_before = [t.get("target_id") for t in targets_before]
    assert tid in target_ids_before, f"'{tid}' not in API targets"

    # Screenshot before
    img_before = _grab(page)
    _save("05_removal_before", img_before)

    # Remove via API
    removed = _remove_target(url, tid)
    assert removed, f"Failed to remove target {tid}"

    # Verify removed from API
    targets_after = _get_targets(url)
    target_ids_after = [t.get("target_id") for t in targets_after]
    assert tid not in target_ids_after, (
        f"'{tid}' still in API targets after removal"
    )

    # Wait for engine to stop including unit in telemetry batches,
    # then repeatedly sync store removal until DOM marker disappears.
    # The telemetry batcher may re-add the unit if its buffer still
    # contains old data, so we retry the store removal several times.
    time.sleep(1.5)
    marker_gone = 1  # assume present initially
    for attempt in range(6):
        _sync_store_removal(page, tid)
        time.sleep(0.5)
        marker_gone = page.locator(
            f'.tritium-unit-marker[data-unit-id="{tid}"]'
        ).count()
        if marker_gone == 0:
            print(f"  Marker removed after {attempt + 1} sync attempt(s)")
            break

    after_remove = _count_dom_markers(page, "friendly")
    print(f"  After remove + sync: {after_remove} friendly markers, "
          f"target marker exists={marker_gone}")

    # Screenshot after
    img_after = _grab(page)
    _save("05_removal_after", img_after)

    assert marker_gone == 0, (
        f"Expected marker for '{tid}' to be removed from DOM after store sync"
    )
    assert after_remove < after_place, (
        f"Expected fewer markers after removal: before={after_place}, "
        f"after={after_remove}"
    )


# ============================================================
# Test 6: Rapid spawn/despawn -- verify clean final state
# ============================================================

def test_rapid_spawn_despawn(server, browser_page):
    """Rapidly create and remove 10 units, verify the map cleans up.

    Primary: DOM marker count returns to baseline after all removals
    (including store sync).
    """
    page = browser_page
    url = server.url

    _center_map(page, zoom=17, bearing=0, pitch=0)

    baseline = _count_dom_markers(page, "friendly")
    print(f"\n  Baseline friendly markers: {baseline}")

    # Spawn 10 units in a circle
    ids = []
    for i in range(10):
        angle = (2 * math.pi * i) / 10
        x = 30.0 * math.cos(angle)
        y = 30.0 * math.sin(angle)
        tid = _place_turret(url, x=x, y=y, name=f"Rapid-{i}")
        if tid:
            ids.append(tid)

    time.sleep(2.0)

    mid_count = _count_dom_markers(page, "friendly")
    new_markers = mid_count - baseline
    print(f"  After spawn: {mid_count} friendly markers (+{new_markers} new)")

    # Screenshot mid-state
    img_mid = _grab(page)
    _save("06_rapid_mid", img_mid)

    assert new_markers >= 8, (
        f"Expected at least 8 new markers from 10 placements, got {new_markers}"
    )

    # Remove all via API
    removed_count = 0
    for tid in ids:
        if _remove_target(url, tid):
            removed_count += 1
    print(f"  API removed: {removed_count}/{len(ids)}")

    # Wait for engine to process removals, then sync store
    time.sleep(1.0)
    for tid in ids:
        _sync_store_removal(page, tid)

    # Wait for _updateUnits() to process (runs every 100ms)
    # and for any in-flight telemetry batches to settle
    time.sleep(2.0)

    # Second sync pass to catch any telemetry re-adds
    for tid in ids:
        _sync_store_removal(page, tid)
    time.sleep(1.0)

    # Verify cleanup
    final_count = _count_dom_markers(page, "friendly")
    print(f"  Final friendly markers: {final_count} (baseline was {baseline})")

    img_final = _grab(page)
    _save("06_rapid_final", img_final)
    _save("06_rapid_final_crop", _crop_to_map(
        img_final, _get_map_bounds(page),
    ))

    # Final count should be within +1 of baseline (tolerance for timing)
    assert final_count <= baseline + 1, (
        f"Map not clean after removal: baseline={baseline}, "
        f"final={final_count}"
    )


# ============================================================
# Test 7: Many units performance -- 20 units, FPS stays usable
# ============================================================

def test_many_units_performance(server, browser_page):
    """Spawn 20 units and verify the renderer maintains usable frame rate.

    Measures FPS via requestAnimationFrame over a 2-second window.
    Threshold is 4 FPS -- headless Chromium with Three.js + satellite tiles
    + 3D models on ARM hardware runs slower than a desktop browser.
    Also validates that all 20 units have DOM markers.
    """
    page = browser_page
    url = server.url

    baseline = _count_dom_markers(page, "friendly")

    # Place 20 friendly units in a 4x5 grid
    ids = []
    for i in range(20):
        row = i // 5
        col = i % 5
        x = (col - 2) * 20.0
        y = (row - 2) * 20.0
        tid = _place_turret(url, x=x, y=y, name=f"Perf-{i}")
        if tid:
            ids.append(tid)

    print(f"\n  Placed {len(ids)} units (target: 20)")
    assert len(ids) >= 15, f"Only placed {len(ids)}/20 units"

    time.sleep(2.0)
    _center_map(page, zoom=16, bearing=0, pitch=0)

    # Verify all units are in DOM
    total_friendly = _count_dom_markers(page, "friendly")
    new_markers = total_friendly - baseline
    print(f"  Friendly markers: {total_friendly} (+{new_markers} new)")
    assert new_markers >= 15, (
        f"Expected at least 15 new markers, got {new_markers}"
    )

    # Screenshot
    img = _grab(page)
    _save("07_performance", img)

    # Measure FPS: count requestAnimationFrame callbacks over 2 seconds
    fps = page.evaluate("""() => {
        return new Promise(resolve => {
            let count = 0;
            const start = performance.now();
            const duration = 2000;

            function tick() {
                count++;
                if (performance.now() - start < duration) {
                    requestAnimationFrame(tick);
                } else {
                    const elapsed = (performance.now() - start) / 1000;
                    resolve(count / elapsed);
                }
            }
            requestAnimationFrame(tick);
        });
    }""")

    print(f"  Measured FPS with {len(ids)} units: {fps:.1f}")

    # 4 FPS minimum: headless Chromium + Three.js + satellite tiles on ARM
    # is significantly slower than a real desktop browser.  The goal here is
    # to detect catastrophic performance regressions (< 1 FPS), not to
    # enforce desktop-level frame rates.
    assert fps >= 4.0, (
        f"FPS dropped below 4 with {len(ids)} units: measured {fps:.1f} FPS"
    )
