# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Render sweep — simple OpenCV visual verification of each layer.

Core diagnostic: clears screen to black, shows ONE element type,
captures screenshot, uses primitive OpenCV (threshold + contours)
to verify elements exist and are spread across the screen.

Catches: labels piling up, units not rendering, layers missing.

Run: .venv/bin/python3 tests/visual/test_render_sweep.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import numpy as np

try:
    import cv2
except ImportError:
    print("FATAL: pip install opencv-python")
    sys.exit(1)

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "tests" / ".test-results" / "render-sweep"
OUT.mkdir(parents=True, exist_ok=True)
BASE_URL = os.environ.get("TRITIUM_URL", "http://localhost:8000")


# ── OpenCV primitives ─────────────────────────────────────────
def bright_blobs(img_path, thresh=35, min_px=15):
    """Find bright blobs on dark bg. Returns (count, centroids, spread_px, annotated_path)."""
    img = cv2.imread(img_path)
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
    ann_path = img_path.replace(".png", "_ann.png")
    cv2.imwrite(ann_path, ann)

    return len(centroids), centroids, spread, ann_path


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
    // Hide ALL UI chrome (real DOM selectors)
    for (const sel of [
        '#header-bar','#command-bar-container','#panel-container',
        '#minimap-container','.game-hud','.layer-hud-outer','.map-mode-indicator',
        '.maplibregl-ctrl-top-right','.maplibregl-ctrl-bottom-right',
        '.maplibregl-ctrl-top-left','.maplibregl-ctrl-bottom-left',
        '.unified-status','.status-bar']) {
        const el = document.querySelector(sel);
        if (el) el.style.display = 'none';
    }
    return true;
})()"""

SHOW_MARKERS = """(() => {
    const ms = window._mapState;
    if (!ms) return 0;
    // Show all units via state (10Hz loop will display them)
    ms.showUnits = true;
    ms.allianceFilter = null;
    return Object.keys(ms.unitMarkers || {}).length;
})()"""

SHOW_3D = """(() => {
    const ms = window._mapState;
    if (!ms || !ms.threeRoot) return false;
    ms.threeRoot.visible = true;
    return true;
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
    for (const layer of ms.map.getStyle().layers || []) {
        try { ms.map.setLayoutProperty(layer.id, 'visibility', 'visible'); } catch(e) {}
    }
    // Restore units via state
    ms.showUnits = true;
    ms.allianceFilter = null;
    if (ms.threeRoot) ms.threeRoot.visible = true;
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

# ── Marker position JS check ──────────────────────────────────
MARKER_POSITIONS = """(() => {
    const markers = document.querySelectorAll('.tritium-unit-marker');
    const result = [];
    for (const el of markers) {
        const rect = el.getBoundingClientRect();
        result.push({ x: Math.round(rect.x), y: Math.round(rect.y), w: Math.round(rect.width) });
    }
    return result;
})()"""


def run():
    from playwright.sync_api import sync_playwright

    print(f"{'='*60}")
    print("RENDER SWEEP — OpenCV Layer Verification")
    print(f"{'='*60}\n")

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

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page(viewport={"width": 1920, "height": 1080})

        print(f"Loading {BASE_URL}...")
        page.goto(BASE_URL)
        page.wait_for_timeout(5000)

        unit_count = page.evaluate("window.TritiumStore && window.TritiumStore.units ? window.TritiumStore.units.size : 0")
        print(f"Units in store: {unit_count}\n")

        # ── 1. Black baseline ──────────────────────────────
        print("── BLACK BASELINE ──")
        page.evaluate(HIDE_ALL)
        page.wait_for_timeout(500)
        p1 = str(OUT / "01_black.png")
        page.screenshot(path=p1)
        n, _, _, _ = bright_blobs(p1, thresh=20)
        check("black_baseline", n < 50, f"{n} bright blobs (want <50, some UI chrome leaks)")

        # ── 2. DOM markers only ────────────────────────────
        print("\n── DOM MARKERS ONLY ──")
        page.evaluate(HIDE_ALL)
        shown = page.evaluate(SHOW_MARKERS)
        page.wait_for_timeout(500)
        p2 = str(OUT / "02_markers.png")
        page.screenshot(path=p2)
        n, centroids, spread, ann = bright_blobs(p2, thresh=30, min_px=8)
        check("markers_visible", n >= 2, f"{n} blobs (want >=2, showed {shown} markers)")
        check("markers_spread", spread > 80, f"spread={spread:.0f}px (want >80)")

        # Also verify via DOM positions
        positions = page.evaluate(MARKER_POSITIONS)
        if positions:
            xs = [m["x"] for m in positions]
            dom_spread = max(xs) - min(xs) if len(xs) > 1 else 0
            avg_x = sum(xs) / len(xs) if xs else 0
            check("markers_dom_spread", dom_spread > 30, f"DOM x-spread={dom_spread}px (want >30)")
            check("markers_not_left", avg_x > 200, f"avg_x={avg_x:.0f} (want >200, center=960)")

        # ── 3. 3D models only ──────────────────────────────
        print("\n── 3D MODELS ONLY ──")
        page.evaluate(HIDE_ALL)
        has_3d = page.evaluate(SHOW_3D)
        page.wait_for_timeout(800)
        p3 = str(OUT / "03_3d.png")
        page.screenshot(path=p3)
        n3, _, spread3, _ = bright_blobs(p3, thresh=25, min_px=30)
        if has_3d:
            check("3d_visible", n3 >= 1, f"{n3} blobs (want >=1)")
            check("3d_spread", spread3 > 50, f"spread={spread3:.0f}px (want >50)")
        else:
            print("  [SKIP] No Three.js root — 3D models not active")

        # ── 4. Satellite only ──────────────────────────────
        print("\n── SATELLITE ONLY ──")
        page.evaluate(HIDE_ALL)
        page.evaluate(SHOW_SATELLITE)
        page.wait_for_timeout(1500)  # tile loading
        p4 = str(OUT / "04_satellite.png")
        page.screenshot(path=p4)
        img4 = cv2.imread(p4)
        if img4 is not None:
            gray4 = cv2.cvtColor(img4, cv2.COLOR_BGR2GRAY)
            bright_ratio = float(np.count_nonzero(gray4 > 20)) / gray4.size
            check("satellite_visible", bright_ratio > 0.1, f"bright={bright_ratio:.1%} (want >10%)")
        else:
            check("satellite_visible", False, "could not read screenshot")

        # ── 5. Buildings only ──────────────────────────────
        print("\n── BUILDINGS ONLY ──")
        page.evaluate(HIDE_ALL)
        page.evaluate(SHOW_BUILDINGS)
        page.wait_for_timeout(1000)
        p5 = str(OUT / "05_buildings.png")
        page.screenshot(path=p5)
        n5, _, _, _ = bright_blobs(p5, thresh=12, min_px=5)
        check("buildings_visible", n5 >= 3, f"{n5} blobs (want >=3)")

        # ── Restore ────────────────────────────────────────
        print("\n── RESTORE ──")
        page.evaluate(RESTORE_ALL)
        page.wait_for_timeout(1000)
        p6 = str(OUT / "06_restored.png")
        page.screenshot(path=p6)
        print(f"  Final screenshot: {p6}")

        browser.close()

    # Summary
    print(f"\n{'='*60}")
    print(f"RESULT: {passes} passed, {fails} failed")
    print(f"{'='*60}")

    with open(OUT / "results.json", "w") as f:
        json.dump(log, f, indent=2)

    print(f"Files: {OUT}")
    return fails == 0


if __name__ == "__main__":
    ok = run()
    sys.exit(0 if ok else 1)
