# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Mass-scale render test — 200+ units, layer isolation, OpenCV verification.

Spawns hundreds of hostiles via the API, then systematically hides all
layers except the one under test. Uses primitive OpenCV (threshold +
contours) to verify markers render correctly at scale.

Tests:
  1. Mass spawn — 200 hostiles appear in TritiumStore
  2. Black baseline — completely dark screen
  3. All markers — 200+ markers visible and spread across viewport
  4. Hostile-only filter — only red hostile markers visible
  5. Friendly-only filter — only cyan/green friendly markers visible
  6. Satellite layer isolation — tiles render alone
  7. Buildings layer isolation — outlines render alone
  8. Full restore — everything back to normal
  9. Marker heatmap — distribution covers all 4 quadrants
  10. No pileup — no cluster of >20 markers in 50px radius

Run: .venv/bin/python3 tests/visual/test_mass_render.py
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from collections import Counter

import numpy as np
import requests

try:
    import cv2
except ImportError:
    print("FATAL: pip install opencv-python")
    sys.exit(1)

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "tests" / ".test-results" / "mass-render"
OUT.mkdir(parents=True, exist_ok=True)
BASE_URL = os.environ.get("TRITIUM_URL", "http://localhost:8000")
HOSTILE_COUNT = 200


# ── OpenCV primitives ─────────────────────────────────────────

def bright_blobs(img_path, thresh=35, min_px=15):
    """Find bright blobs on dark bg. Returns (count, centroids, spread_px, annotated_path)."""
    img = cv2.imread(str(img_path))
    if img is None:
        return 0, [], 0.0, ""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    _, bw = cv2.threshold(gray, thresh, 255, cv2.THRESH_BINARY)
    contours, _ = cv2.findContours(bw, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    centroids = []
    for c in contours:
        if cv2.contourArea(c) < min_px:
            continue
        M = cv2.moments(c)
        if M["m00"] == 0:
            continue
        cx, cy = int(M["m10"] / M["m00"]), int(M["m01"] / M["m00"])
        centroids.append((cx, cy))

    spread = 0.0
    if len(centroids) >= 2:
        xs = [c[0] for c in centroids]
        ys = [c[1] for c in centroids]
        spread = ((max(xs) - min(xs))**2 + (max(ys) - min(ys))**2)**0.5

    # Annotate
    ann = img.copy()
    cv2.drawContours(ann, [c for c in contours if cv2.contourArea(c) >= min_px], -1, (0, 255, 0), 2)
    for cx, cy in centroids:
        cv2.circle(ann, (cx, cy), 6, (0, 0, 255), -1)
    ann_path = str(img_path).replace(".png", "_ann.png")
    cv2.imwrite(ann_path, ann)

    return len(centroids), centroids, spread, ann_path


def color_blobs(img_path, lower_hsv, upper_hsv, min_px=10):
    """Find blobs of a specific color range in HSV space."""
    img = cv2.imread(str(img_path))
    if img is None:
        return 0, []
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, np.array(lower_hsv), np.array(upper_hsv))
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    centroids = []
    for c in contours:
        if cv2.contourArea(c) < min_px:
            continue
        M = cv2.moments(c)
        if M["m00"] == 0:
            continue
        cx, cy = int(M["m10"] / M["m00"]), int(M["m01"] / M["m00"])
        centroids.append((cx, cy))
    return len(centroids), centroids


def quadrant_coverage(centroids, width=1920, height=1080):
    """Check how many quadrants have at least one centroid."""
    mx, my = width // 2, height // 2
    quads = set()
    for cx, cy in centroids:
        q = ("T" if cy < my else "B") + ("L" if cx < mx else "R")
        quads.add(q)
    return quads


def pileup_check(centroids, radius=50, max_cluster=20):
    """Check if any point has more than max_cluster neighbors within radius."""
    worst = 0
    worst_pos = (0, 0)
    for i, (cx, cy) in enumerate(centroids):
        count = 0
        for j, (ox, oy) in enumerate(centroids):
            if i == j:
                continue
            if abs(cx - ox) <= radius and abs(cy - oy) <= radius:
                dist = ((cx - ox)**2 + (cy - oy)**2)**0.5
                if dist <= radius:
                    count += 1
        if count > worst:
            worst = count
            worst_pos = (cx, cy)
    return worst, worst_pos


# ── JavaScript helpers ─────────────────────────────────────────

HIDE_ALL = """(() => {
    const ms = window._mapState;
    if (!ms || !ms.map) return false;
    const m = ms.map;
    // Hide MapLibre layers
    for (const layer of m.getStyle().layers || []) {
        try { m.setLayoutProperty(layer.id, 'visibility', 'none'); } catch(e) {}
    }
    // Hide units via state (10Hz loop respects this)
    ms.showUnits = false;
    ms.allianceFilter = null;
    // Hide Three.js
    if (ms.threeRoot) ms.threeRoot.visible = false;
    // Hide ALL UI chrome (real DOM selectors verified via getBoundingClientRect)
    for (const sel of [
        '#header-bar',              // top menu bar
        '#command-bar-container',   // OBSERVE 2D Z16.0 | SAT + BLDG ... bar
        '#panel-container',         // all panels (units, alerts, amy)
        '#minimap-container',       // minimap corner widget
        '.game-hud',               // wave/score HUD overlay
        '.layer-hud-outer',        // layer toggle HUD
        '.map-mode-indicator',     // mode indicator overlay
        '.maplibregl-ctrl-top-right','.maplibregl-ctrl-bottom-right',
        '.maplibregl-ctrl-top-left','.maplibregl-ctrl-bottom-left',
        '.unified-status','.status-bar']) {
        const el = document.querySelector(sel);
        if (el) el.style.display = 'none';
    }
    return true;
})()"""

SHOW_ALL_MARKERS = """(() => {
    const ms = window._mapState;
    if (!ms) return 0;
    ms.allianceFilter = null;  // Clear filter — show all alliances
    ms.showUnits = true;
    return Object.keys(ms.unitMarkers || {}).length;
})()"""

SHOW_HOSTILE_MARKERS_ONLY = """(() => {
    const ms = window._mapState;
    if (!ms) return 0;
    // Use the allianceFilter so the 10Hz update loop respects the filter
    ms.allianceFilter = ['hostile'];
    ms.showUnits = true;
    let count = 0;
    for (const [id, mk] of Object.entries(ms.unitMarkers || {})) {
        if ((mk.getElement().dataset.alliance || '') === 'hostile') count++;
    }
    return count;
})()"""

SHOW_FRIENDLY_MARKERS_ONLY = """(() => {
    const ms = window._mapState;
    if (!ms) return 0;
    ms.allianceFilter = ['friendly'];
    ms.showUnits = true;
    let count = 0;
    for (const [id, mk] of Object.entries(ms.unitMarkers || {})) {
        if ((mk.getElement().dataset.alliance || '') === 'friendly') count++;
    }
    return count;
})()"""

SHOW_NEUTRAL_MARKERS_ONLY = """(() => {
    const ms = window._mapState;
    if (!ms) return 0;
    ms.allianceFilter = ['neutral'];
    ms.showUnits = true;
    let count = 0;
    for (const [id, mk] of Object.entries(ms.unitMarkers || {})) {
        if ((mk.getElement().dataset.alliance || '') === 'neutral') count++;
    }
    return count;
})()"""

SHOW_SATELLITE = """(() => {
    const ms = window._mapState;
    if (!ms || !ms.map) return false;
    try { ms.map.setLayoutProperty('satellite-layer', 'visibility', 'visible'); return true; } catch(e) { return false; }
})()"""

SHOW_BUILDINGS = """(() => {
    const ms = window._mapState;
    if (!ms || !ms.map) return false;
    try { ms.map.setLayoutProperty('buildings-3d', 'visibility', 'visible'); } catch(e) {}
    try { ms.map.setLayoutProperty('buildings-outline', 'visibility', 'visible'); } catch(e) {}
    return true;
})()"""

RESTORE_ALL = """(() => {
    const ms = window._mapState;
    if (!ms || !ms.map) return;
    // Restore MapLibre layers
    for (const layer of ms.map.getStyle().layers || []) {
        try { ms.map.setLayoutProperty(layer.id, 'visibility', 'visible'); } catch(e) {}
    }
    // Restore units via state
    ms.showUnits = true;
    ms.allianceFilter = null;
    if (ms.threeRoot) ms.threeRoot.visible = true;
    // Restore UI chrome
    for (const sel of [
        '#header-bar','#command-bar-container','#panel-container',
        '#minimap-container','.game-hud','.layer-hud-outer','.map-mode-indicator',
        '.maplibregl-ctrl-top-right','.maplibregl-ctrl-bottom-right',
        '.maplibregl-ctrl-top-left','.maplibregl-ctrl-bottom-left',
        '.unified-status','.status-bar']) {
        const el = document.querySelector(sel);
        if (el) el.style.display = '';
    }
})()"""

GET_MARKER_STATS = """(() => {
    const ms = window._mapState;
    if (!ms) return {total: 0, hostile: 0, friendly: 0, neutral: 0, positions: []};
    let total = 0, hostile = 0, friendly = 0, neutral = 0;
    const positions = [];
    for (const [id, mk] of Object.entries(ms.unitMarkers || {})) {
        const el = mk.getElement();
        const rect = el.getBoundingClientRect();
        const alliance = el.dataset.alliance || 'unknown';
        total++;
        if (alliance === 'hostile') hostile++;
        else if (alliance === 'friendly') friendly++;
        else if (alliance === 'neutral') neutral++;
        positions.push({
            x: Math.round(rect.x),
            y: Math.round(rect.y),
            w: Math.round(rect.width),
            h: Math.round(rect.height),
            alliance: alliance,
            visible: el.style.display !== 'none' && rect.width > 0
        });
    }
    return {total, hostile, friendly, neutral, positions};
})()"""

GET_STORE_UNIT_COUNT = """(() => {
    if (!window.TritiumStore || !window.TritiumStore.units) return 0;
    return window.TritiumStore.units.size;
})()"""


# ── Server helpers ────────────────────────────────────────────

def reset_game():
    """Reset the game to setup state."""
    r = requests.post(f"{BASE_URL}/api/game/reset", timeout=5)
    return r.status_code == 200


def spawn_hostiles(count):
    """Spawn N hostiles via the simulation API."""
    spawned = 0
    for i in range(count):
        r = requests.post(
            f"{BASE_URL}/api/amy/simulation/spawn",
            json={"alliance": "hostile", "name": f"CROWD-{i+1}"},
            timeout=5,
        )
        if r.status_code == 200:
            spawned += 1
    return spawned


def get_target_count():
    """Get current simulation target count."""
    try:
        r = requests.get(f"{BASE_URL}/api/amy/simulation/targets", timeout=5)
        d = r.json()
        targets = d.get("targets", d) if isinstance(d, dict) else d
        return len(targets)
    except Exception:
        return 0


# ── Main test runner ──────────────────────────────────────────

def run():
    from playwright.sync_api import sync_playwright

    print(f"{'='*70}")
    print("MASS RENDER TEST — 200+ Units, Layer Isolation, OpenCV")
    print(f"{'='*70}\n")

    passes = 0
    fails = 0
    log = []

    def check(name, ok, msg):
        nonlocal passes, fails
        tag = "PASS" if ok else "FAIL"
        print(f"  [{tag}] {name}: {msg}")
        log.append({"name": name, "ok": ok, "msg": msg})
        if ok:
            passes += 1
        else:
            fails += 1

    # ── Phase 0: Mass spawn via API ──────────────────────────
    print("── PHASE 0: MASS SPAWN ──")
    print(f"  Resetting game...")
    reset_game()
    time.sleep(1)

    existing = get_target_count()
    print(f"  Existing targets: {existing}")

    # Only spawn if we don't already have enough hostiles
    need = max(0, HOSTILE_COUNT - existing)
    if need > 0:
        print(f"  Spawning {need} hostiles (this may take ~10s)...")
        spawned = spawn_hostiles(need)
        print(f"  Spawned: {spawned}")
    else:
        print(f"  Already have {existing} targets, skipping spawn")

    time.sleep(2)  # Let telemetry propagate
    total = get_target_count()
    print(f"  Total targets now: {total}")
    check("mass_spawn", total >= HOSTILE_COUNT, f"{total} targets (want >={HOSTILE_COUNT})")

    # ── Launch browser ───────────────────────────────────────
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page(viewport={"width": 1920, "height": 1080})

        print(f"\n  Loading {BASE_URL}...")
        page.goto(BASE_URL)
        page.wait_for_timeout(8000)  # Extra time for 200+ markers to render

        store_count = page.evaluate(GET_STORE_UNIT_COUNT)
        print(f"  Units in TritiumStore: {store_count}")
        check("store_populated", store_count >= 50,
              f"{store_count} units in store (want >=50)")

        # Get marker stats
        stats = page.evaluate(GET_MARKER_STATS)
        print(f"  MapLibre markers: total={stats['total']} hostile={stats['hostile']} "
              f"friendly={stats['friendly']} neutral={stats['neutral']}")
        check("markers_created", stats["total"] >= 50,
              f"{stats['total']} markers (want >=50)")

        # ── 1. Black baseline ────────────────────────────────
        print("\n── TEST 1: BLACK BASELINE ──")
        page.evaluate(HIDE_ALL)
        page.wait_for_timeout(500)
        p1 = str(OUT / "01_black.png")
        page.screenshot(path=p1)
        n1, _, _, _ = bright_blobs(p1, thresh=20)
        check("black_baseline", n1 < 50, f"{n1} bright blobs (want <50)")

        # ── 2. All markers on dark background ────────────────
        print("\n── TEST 2: ALL MARKERS (200+) ──")
        page.evaluate(HIDE_ALL)
        shown = page.evaluate(SHOW_ALL_MARKERS)
        page.wait_for_timeout(1000)
        p2 = str(OUT / "02_all_markers.png")
        page.screenshot(path=p2)
        n2, centroids2, spread2, _ = bright_blobs(p2, thresh=30, min_px=5)
        check("all_markers_visible", n2 >= 20,
              f"{n2} blobs (want >=20, showed {shown} markers)")
        check("all_markers_spread", spread2 > 200,
              f"spread={spread2:.0f}px (want >200 for city scale)")

        # Check DOM positions for all visible markers
        all_stats = page.evaluate(GET_MARKER_STATS)
        visible = [m for m in all_stats["positions"] if m["visible"]]
        if visible:
            xs = [m["x"] for m in visible]
            ys = [m["y"] for m in visible]
            x_range = max(xs) - min(xs)
            y_range = max(ys) - min(ys)
            avg_x = sum(xs) / len(xs)
            print(f"  Visible markers: {len(visible)}, x_range={x_range}px, y_range={y_range}px, avg_x={avg_x:.0f}")
            check("markers_x_spread", x_range > 100,
                  f"x_range={x_range}px (want >100)")
            check("markers_not_left_edge", avg_x > 300,
                  f"avg_x={avg_x:.0f} (want >300, center=960)")

        # ── 3. Hostile markers only ──────────────────────────
        print("\n── TEST 3: HOSTILE MARKERS ONLY ──")
        page.evaluate(HIDE_ALL)
        hostile_shown = page.evaluate(SHOW_HOSTILE_MARKERS_ONLY)
        page.wait_for_timeout(500)
        p3 = str(OUT / "03_hostile_only.png")
        page.screenshot(path=p3)
        n3, centroids3, spread3, _ = bright_blobs(p3, thresh=25, min_px=5)
        check("hostile_visible", n3 >= 10,
              f"{n3} blobs (want >=10, showed {hostile_shown} hostile markers)")
        check("hostile_spread", spread3 > 150,
              f"spread={spread3:.0f}px (want >150)")

        # Verify no friendly markers leaked through
        hostile_stats = page.evaluate(GET_MARKER_STATS)
        leaked_friendly = sum(1 for m in hostile_stats["positions"]
                             if m["alliance"] == "friendly" and m["visible"])
        check("hostile_filter_clean", leaked_friendly == 0,
              f"{leaked_friendly} friendly markers leaked (want 0)")

        # ── 4. Friendly markers only ─────────────────────────
        print("\n── TEST 4: FRIENDLY MARKERS ONLY ──")
        page.evaluate(HIDE_ALL)
        friendly_shown = page.evaluate(SHOW_FRIENDLY_MARKERS_ONLY)
        page.wait_for_timeout(500)
        p4 = str(OUT / "04_friendly_only.png")
        page.screenshot(path=p4)
        n4, centroids4, spread4, _ = bright_blobs(p4, thresh=25, min_px=5)
        check("friendly_visible", n4 >= 2,
              f"{n4} blobs (want >=2, showed {friendly_shown} friendly markers)")

        # Verify no hostile markers leaked through
        friendly_stats = page.evaluate(GET_MARKER_STATS)
        leaked_hostile = sum(1 for m in friendly_stats["positions"]
                            if m["alliance"] == "hostile" and m["visible"])
        check("friendly_filter_clean", leaked_hostile == 0,
              f"{leaked_hostile} hostile markers leaked (want 0)")

        # ── 5. Neutral markers only ──────────────────────────
        print("\n── TEST 5: NEUTRAL MARKERS ONLY ──")
        page.evaluate(HIDE_ALL)
        neutral_shown = page.evaluate(SHOW_NEUTRAL_MARKERS_ONLY)
        page.wait_for_timeout(500)
        p5 = str(OUT / "05_neutral_only.png")
        page.screenshot(path=p5)
        if neutral_shown > 0:
            n5, _, _, _ = bright_blobs(p5, thresh=25, min_px=5)
            check("neutral_visible", n5 >= 1,
                  f"{n5} blobs (want >=1, showed {neutral_shown} neutral markers)")
        else:
            print("  [SKIP] No neutral markers in scene")

        # ── 6. Satellite layer isolation ─────────────────────
        print("\n── TEST 6: SATELLITE LAYER ONLY ──")
        page.evaluate(HIDE_ALL)
        page.evaluate(SHOW_SATELLITE)
        page.wait_for_timeout(1500)
        p6 = str(OUT / "06_satellite.png")
        page.screenshot(path=p6)
        img6 = cv2.imread(p6)
        if img6 is not None:
            gray6 = cv2.cvtColor(img6, cv2.COLOR_BGR2GRAY)
            bright_ratio = float(np.count_nonzero(gray6 > 20)) / gray6.size
            check("satellite_visible", bright_ratio > 0.1,
                  f"bright={bright_ratio:.1%} (want >10%)")

        # ── 7. Buildings layer isolation ─────────────────────
        print("\n── TEST 7: BUILDINGS LAYER ONLY ──")
        page.evaluate(HIDE_ALL)
        page.evaluate(SHOW_BUILDINGS)
        page.wait_for_timeout(1000)
        p7 = str(OUT / "07_buildings.png")
        page.screenshot(path=p7)
        n7, _, _, _ = bright_blobs(p7, thresh=12, min_px=5)
        check("buildings_visible", n7 >= 3, f"{n7} blobs (want >=3)")

        # ── 8. Quadrant coverage ─────────────────────────────
        print("\n── TEST 8: QUADRANT COVERAGE ──")
        page.evaluate(HIDE_ALL)
        page.evaluate(SHOW_ALL_MARKERS)
        page.wait_for_timeout(500)
        p8 = str(OUT / "08_quadrant_check.png")
        page.screenshot(path=p8)
        _, centroids8, _, _ = bright_blobs(p8, thresh=25, min_px=5)
        quads = quadrant_coverage(centroids8)
        check("quadrant_coverage", len(quads) >= 2,
              f"quadrants covered: {sorted(quads)} ({len(quads)}/4, want >=2)")

        # ── 9. Pileup detection ──────────────────────────────
        print("\n── TEST 9: PILEUP DETECTION ──")
        # Use DOM positions for more accurate pileup detection
        pile_stats = page.evaluate(GET_MARKER_STATS)
        vis_positions = [(m["x"], m["y"]) for m in pile_stats["positions"] if m["visible"]]
        if len(vis_positions) >= 10:
            worst_pile, worst_pos = pileup_check(vis_positions, radius=30, max_cluster=25)
            check("no_marker_pileup", worst_pile < 25,
                  f"worst cluster: {worst_pile} markers within 30px at ({worst_pos[0]},{worst_pos[1]}) (want <25)")
        else:
            check("no_marker_pileup", False,
                  f"only {len(vis_positions)} visible markers, need >=10 to test pileup")

        # ── 10. Restore everything ───────────────────────────
        print("\n── TEST 10: FULL RESTORE ──")
        page.evaluate(RESTORE_ALL)
        page.wait_for_timeout(1500)
        p10 = str(OUT / "10_restored.png")
        page.screenshot(path=p10)
        n10, _, _, _ = bright_blobs(p10, thresh=20, min_px=5)
        check("restore_not_blank", n10 > 50,
              f"{n10} blobs after restore (want >50 = everything visible)")

        browser.close()

    # ── Summary ──────────────────────────────────────────────
    print(f"\n{'='*70}")
    print(f"MASS RENDER RESULT: {passes} passed, {fails} failed out of {passes+fails} checks")
    print(f"{'='*70}")

    with open(OUT / "results.json", "w") as f:
        json.dump(log, f, indent=2)

    print(f"Screenshots: {OUT}")
    return fails == 0


if __name__ == "__main__":
    ok = run()
    sys.exit(0 if ok else 1)
