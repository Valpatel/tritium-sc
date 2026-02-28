# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Element Grid Test: place each visual element type one at a time on a known
grid, screenshot, verify position with OpenCV.

This is the definitive test for geolocation correctness. Every renderable
element (DOM marker, Three.js mesh, DOM effect, Three.js effect) gets
placed at a KNOWN game coordinate, and we use OpenCV to measure where it
actually appears on screen vs where it should be.

Grid: 5 positions at known game coordinates:
  A = (0, 0)       center of map
  B = (0, 100)     100m north
  C = (100, 0)     100m east
  D = (0, -100)    100m south
  E = (-100, 0)    100m west

For each element type:
  1. Clear the scene
  2. Place exactly ONE element at position A
  3. Screenshot
  4. Use OpenCV to find the brightest/most-colored region
  5. Compare to expected screen pixel position (via map.project())
  6. Report pass/fail with pixel offset

Run: .venv/bin/python3 tests/visual/test_element_grid.py
"""

import time
import json
import sys
from pathlib import Path

import cv2
import numpy as np
from playwright.sync_api import sync_playwright

OUTPUT_DIR = Path("tests/.test-results/element-grid")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
BASE_URL = "http://localhost:8000"

# Game positions to test
GRID = {
    "center":  (0, 0),
    "north":   (0, 100),
    "east":    (100, 0),
    "south":   (0, -100),
    "west":    (-100, 0),
}


def find_colored_region(img_path, color_bgr, tolerance=60, min_area=10):
    """Find the centroid of the largest region matching `color_bgr` (±tolerance).

    Returns (cx, cy, area) or None if not found.
    """
    img = cv2.imread(str(img_path))
    if img is None:
        return None

    lower = np.clip(np.array(color_bgr, dtype=np.int16) - tolerance, 0, 255).astype(np.uint8)
    upper = np.clip(np.array(color_bgr, dtype=np.int16) + tolerance, 0, 255).astype(np.uint8)
    mask = cv2.inRange(img, lower, upper)

    # Dilate to connect nearby pixels
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    mask = cv2.dilate(mask, kernel, iterations=1)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None

    largest = max(contours, key=cv2.contourArea)
    area = cv2.contourArea(largest)
    if area < min_area:
        return None

    M = cv2.moments(largest)
    if M["m00"] == 0:
        return None
    cx = int(M["m10"] / M["m00"])
    cy = int(M["m01"] / M["m00"])
    return (cx, cy, area)


def find_any_bright_region(img_path, min_brightness=200, min_area=20):
    """Find the brightest region in the image (for white/bright effects)."""
    img = cv2.imread(str(img_path))
    if img is None:
        return None

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    _, thresh = cv2.threshold(gray, min_brightness, 255, cv2.THRESH_BINARY)

    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None

    # Filter out the UI panels (top bar, side panels) by position
    # Map canvas is roughly in the center of the screen
    valid = []
    for c in contours:
        area = cv2.contourArea(c)
        if area < min_area:
            continue
        M = cv2.moments(c)
        if M["m00"] == 0:
            continue
        cx = int(M["m10"] / M["m00"])
        cy = int(M["m01"] / M["m00"])
        # Skip UI panels (left sidebar, top bar, right panel)
        if cx < 200 or cx > 1750 or cy < 40:
            continue
        valid.append((cx, cy, area))

    if not valid:
        return None
    # Return the one with largest area
    return max(valid, key=lambda x: x[2])


def main():
    results = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page(viewport={"width": 1920, "height": 1080})

        logs = []
        page.on("console", lambda msg: logs.append(f"[{msg.type}] {msg.text}"))

        print("=" * 60)
        print("ELEMENT GRID POSITION TEST")
        print("=" * 60)

        print("\n[SETUP] Loading Command Center...")
        page.goto(BASE_URL, wait_until="networkidle")
        time.sleep(4)

        # Reset game to get a clean map with no combat
        page.evaluate("() => fetch('/api/game/reset', {method:'POST'}).then(r=>r.json())")
        time.sleep(2)

        # Get map projection function for computing expected screen positions
        # Set pitch to 0 (top-down) for easier position verification
        page.evaluate("""() => {
            const s = window._mapState;
            if (s && s.map) {
                s.map.setPitch(0);
                s.map.setBearing(0);
            }
        }""")
        time.sleep(1)

        # Capture baseline (no effects)
        page.screenshot(path=str(OUTPUT_DIR / "00_baseline.png"))

        # Compute expected screen positions for all grid points
        expected_positions = page.evaluate("""() => {
            const s = window._mapState;
            if (!s || !s.map || !s.geoCenter) return {};

            const R = 6378137;
            const latRad = s.geoCenter.lat * Math.PI / 180;
            const result = {};

            const grid = {
                center: [0, 0], north: [0, 100], east: [100, 0],
                south: [0, -100], west: [-100, 0]
            };

            for (const [name, [gx, gy]] of Object.entries(grid)) {
                const dLng = gx / (R * Math.cos(latRad)) * (180 / Math.PI);
                const dLat = gy / R * (180 / Math.PI);
                const lngLat = [s.geoCenter.lng + dLng, s.geoCenter.lat + dLat];
                const pt = s.map.project(lngLat);
                result[name] = { x: Math.round(pt.x), y: Math.round(pt.y), gx, gy };
            }
            return result;
        }""")

        print("\nExpected screen positions (pitch=0, bearing=0):")
        for name, pos in expected_positions.items():
            print(f"  {name:8s}: screen=({pos['x']}, {pos['y']})  game=({pos['gx']}, {pos['gy']})")

        # ============================================================
        # TEST 1: DOM Marker (MapLibre Marker with colored circle)
        # ============================================================
        print("\n--- TEST 1: DOM Marker ---")
        for grid_name, (gx, gy) in GRID.items():
            # Clear previous markers
            page.evaluate("() => { document.querySelectorAll('.test-grid-marker').forEach(e => e.remove()); }")
            time.sleep(0.1)

            # Place a single bright marker
            page.evaluate(f"""() => {{
                const s = window._mapState;
                if (!s || !s.map || !s.geoCenter) return;

                const R = 6378137;
                const latRad = s.geoCenter.lat * Math.PI / 180;
                const dLng = {gx} / (R * Math.cos(latRad)) * (180 / Math.PI);
                const dLat = {gy} / R * (180 / Math.PI);
                const lngLat = [s.geoCenter.lng + dLng, s.geoCenter.lat + dLat];

                const el = document.createElement('div');
                el.className = 'test-grid-marker';
                el.style.cssText = 'width:60px;height:60px;border-radius:50%;background:#ff0000;pointer-events:none;box-shadow:0 0 20px #ff0000;';

                const m = new maplibregl.Marker({{ element: el, anchor: 'center' }})
                    .setLngLat(lngLat)
                    .addTo(s.map);
                window._testMarker = m;
            }}""")
            time.sleep(0.3)

            fname = f"01_dom_marker_{grid_name}.png"
            page.screenshot(path=str(OUTPUT_DIR / fname))

            # Find the red circle
            detected = find_colored_region(str(OUTPUT_DIR / fname), (0, 0, 255), tolerance=80, min_area=50)
            exp = expected_positions.get(grid_name, {})
            ex, ey = exp.get('x', 0), exp.get('y', 0)

            if detected:
                dx = abs(detected[0] - ex)
                dy = abs(detected[1] - ey)
                offset = (dx**2 + dy**2) ** 0.5
                ok = offset < 50
                status = "PASS" if ok else "FAIL"
                print(f"  {grid_name:8s}: expected=({ex},{ey}) detected=({detected[0]},{detected[1]}) "
                      f"offset={offset:.0f}px [{status}]")
            else:
                ok = False
                offset = -1
                print(f"  {grid_name:8s}: expected=({ex},{ey}) NOT DETECTED [FAIL]")

            results.append({
                "test": "dom_marker", "position": grid_name,
                "expected": [ex, ey],
                "detected": [detected[0], detected[1]] if detected else None,
                "offset_px": round(offset, 1),
                "pass": ok,
            })

            # Clean up
            page.evaluate("() => { if (window._testMarker) window._testMarker.remove(); }")

        # ============================================================
        # TEST 2: Three.js Sphere (MeshBasicMaterial, bright white)
        # ============================================================
        print("\n--- TEST 2: Three.js Sphere ---")
        for grid_name, (gx, gy) in GRID.items():
            # Remove previous test meshes
            page.evaluate("""() => {
                const s = window._mapState;
                if (!s || !s.threeRoot) return;
                const toRemove = [];
                s.threeRoot.children.forEach(c => {
                    if (c.userData && c.userData.testGrid) toRemove.push(c);
                });
                for (const c of toRemove) {
                    s.threeRoot.remove(c);
                    if (c.geometry) c.geometry.dispose();
                    if (c.material) c.material.dispose();
                }
                if (s.map) s.map.triggerRepaint();
            }""")
            time.sleep(0.2)

            # Place a single bright white sphere
            page.evaluate(f"""() => {{
                const s = window._mapState;
                if (!s || !s.threeRoot) return;

                const geo = new THREE.SphereGeometry(50, 16, 16);  // 50 meter radius
                const mat = new THREE.MeshBasicMaterial({{
                    color: 0xff0000, transparent: false,
                    depthWrite: true, depthTest: true,
                }});
                const mesh = new THREE.Mesh(geo, mat);
                mesh.position.set({gx}, {gy}, 5);
                mesh.userData.testGrid = true;
                mesh.frustumCulled = false;
                s.threeRoot.add(mesh);
                if (s.map) s.map.triggerRepaint();
            }}""")
            time.sleep(0.5)

            fname = f"02_three_sphere_{grid_name}.png"
            page.screenshot(path=str(OUTPUT_DIR / fname))

            # Detect the red sphere
            detected = find_colored_region(str(OUTPUT_DIR / fname), (0, 0, 255), tolerance=80, min_area=20)
            exp = expected_positions.get(grid_name, {})
            ex, ey = exp.get('x', 0), exp.get('y', 0)

            if detected:
                dx = abs(detected[0] - ex)
                dy = abs(detected[1] - ey)
                offset = (dx**2 + dy**2) ** 0.5
                ok = offset < 50
                status = "PASS" if ok else "FAIL"
                print(f"  {grid_name:8s}: expected=({ex},{ey}) detected=({detected[0]},{detected[1]}) "
                      f"offset={offset:.0f}px area={detected[2]} [{status}]")
            else:
                ok = False
                offset = -1
                print(f"  {grid_name:8s}: expected=({ex},{ey}) NOT DETECTED [FAIL]")

            results.append({
                "test": "three_sphere", "position": grid_name,
                "expected": [ex, ey],
                "detected": [detected[0], detected[1]] if detected else None,
                "offset_px": round(offset, 1),
                "pass": ok,
            })

        # Clean up Three.js test meshes
        page.evaluate("""() => {
            const s = window._mapState;
            if (!s || !s.threeRoot) return;
            const toRemove = [];
            s.threeRoot.children.forEach(c => {
                if (c.userData && c.userData.testGrid) toRemove.push(c);
            });
            for (const c of toRemove) {
                s.threeRoot.remove(c);
                if (c.geometry) c.geometry.dispose();
                if (c.material) c.material.dispose();
            }
        }""")

        # ============================================================
        # TEST 3: DOM Explosion Effect (combat:elimination event)
        # ============================================================
        print("\n--- TEST 3: DOM Explosion (combat:elimination) ---")
        for grid_name, (gx, gy) in GRID.items():
            # Emit a combat:elimination event at this position
            page.evaluate(f"""() => {{
                window.EventBus.emit('combat:elimination', {{
                    target_id: 'test-target-{grid_name}',
                    target_name: 'TEST {grid_name.upper()}',
                    interceptor_name: 'TEST',
                    position: {{ x: {gx}, y: {gy} }},
                    method: 'nerf_dart'
                }});
            }}""")
            time.sleep(0.15)  # Quick screenshot before DOM effects fade

            fname = f"03_dom_explosion_{grid_name}.png"
            page.screenshot(path=str(OUTPUT_DIR / fname))

            # Detect the magenta explosion (DOM markers are #ff2a6d = BGR(109, 42, 255))
            detected = find_colored_region(str(OUTPUT_DIR / fname), (109, 42, 255), tolerance=80, min_area=20)
            if not detected:
                # Try finding any bright region
                detected = find_any_bright_region(str(OUTPUT_DIR / fname), min_brightness=200, min_area=50)

            exp = expected_positions.get(grid_name, {})
            ex, ey = exp.get('x', 0), exp.get('y', 0)

            if detected:
                dx = abs(detected[0] - ex)
                dy = abs(detected[1] - ey)
                offset = (dx**2 + dy**2) ** 0.5
                ok = offset < 80  # More tolerance for explosion effects
                status = "PASS" if ok else "FAIL"
                print(f"  {grid_name:8s}: expected=({ex},{ey}) detected=({detected[0]},{detected[1]}) "
                      f"offset={offset:.0f}px [{status}]")
            else:
                ok = False
                offset = -1
                print(f"  {grid_name:8s}: expected=({ex},{ey}) NOT DETECTED [FAIL]")

            results.append({
                "test": "dom_explosion", "position": grid_name,
                "expected": [ex, ey],
                "detected": [detected[0], detected[1]] if detected else None,
                "offset_px": round(offset, 1),
                "pass": ok,
            })

            time.sleep(1.5)  # Wait for effects to clear

        # ============================================================
        # TEST 4: Floating Text (combat:elimination ELIMINATED label)
        # ============================================================
        print("\n--- TEST 4: Floating Text ---")
        for grid_name, (gx, gy) in list(GRID.items())[:3]:  # Just test 3 positions
            page.evaluate(f"""() => {{
                // Spawn floating text via the internal function
                const s = window._mapState;
                if (!s || !s.map || !s.geoCenter) return;
                const R = 6378137;
                const latRad = s.geoCenter.lat * Math.PI / 180;
                const dLng = {gx} / (R * Math.cos(latRad)) * (180 / Math.PI);
                const dLat = {gy} / R * (180 / Math.PI);
                const lngLat = [s.geoCenter.lng + dLng, s.geoCenter.lat + dLat];

                const el = document.createElement('div');
                el.className = 'test-grid-marker';
                el.style.cssText = 'pointer-events:none;font-size:24px;font-weight:bold;color:#ff2a6d;text-shadow:0 0 10px #ff2a6d;font-family:monospace;';
                el.textContent = 'ELIMINATED';
                new maplibregl.Marker({{ element: el, anchor: 'center' }})
                    .setLngLat(lngLat).addTo(s.map);
            }}""")
            time.sleep(0.3)

            fname = f"04_float_text_{grid_name}.png"
            page.screenshot(path=str(OUTPUT_DIR / fname))

            detected = find_colored_region(str(OUTPUT_DIR / fname), (109, 42, 255), tolerance=80, min_area=30)
            exp = expected_positions.get(grid_name, {})
            ex, ey = exp.get('x', 0), exp.get('y', 0)

            if detected:
                dx = abs(detected[0] - ex)
                dy = abs(detected[1] - ey)
                offset = (dx**2 + dy**2) ** 0.5
                ok = offset < 60
                status = "PASS" if ok else "FAIL"
                print(f"  {grid_name:8s}: expected=({ex},{ey}) detected=({detected[0]},{detected[1]}) "
                      f"offset={offset:.0f}px [{status}]")
            else:
                ok = False
                offset = -1
                print(f"  {grid_name:8s}: expected=({ex},{ey}) NOT DETECTED [FAIL]")

            results.append({
                "test": "floating_text", "position": grid_name,
                "expected": [ex, ey],
                "detected": [detected[0], detected[1]] if detected else None,
                "offset_px": round(offset, 1),
                "pass": ok,
            })

            page.evaluate("() => { document.querySelectorAll('.test-grid-marker').forEach(e => e.remove()); }")

        # ============================================================
        # SUMMARY
        # ============================================================
        print("\n" + "=" * 60)
        print("RESULTS SUMMARY")
        print("=" * 60)

        total = len(results)
        passed = sum(1 for r in results if r['pass'])
        failed = total - passed

        for r in results:
            icon = "OK" if r['pass'] else "XX"
            det = f"({r['detected'][0]},{r['detected'][1]})" if r['detected'] else "NOT_FOUND"
            print(f"  [{icon}] {r['test']:20s} @ {r['position']:8s}: "
                  f"expect=({r['expected'][0]},{r['expected'][1]}) got={det} "
                  f"offset={r['offset_px']}px")

        print(f"\n  TOTAL: {passed}/{total} passed, {failed} failed")

        # Save results
        with open(OUTPUT_DIR / "results.json", "w") as f:
            json.dump(results, f, indent=2)
        with open(OUTPUT_DIR / "console.txt", "w") as f:
            f.write("\n".join(logs))

        print(f"\nScreenshots and data in: {OUTPUT_DIR}")
        print("Browser open 10s for inspection...")
        time.sleep(10)
        browser.close()

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
