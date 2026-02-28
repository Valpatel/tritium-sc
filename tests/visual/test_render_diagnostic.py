# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Rendering pipeline diagnostic test.

Opens the Command Center, starts a battle, and captures diagnostic
screenshots + data dumps to identify rendering issues.

This test targets the ACTUAL renderer: MapLibre GL JS + Three.js overlay.
(NOT the legacy Canvas 2D map.js which is inactive.)

Diagnostics:
1. Map container sizing (is #tactical-area visible?)
2. MapLibre initialization status
3. Geo reference point (geoCenter)
4. Unit positions in TritiumStore
5. DOM marker positions (MapLibre Marker elements)
6. Layer isolation: markers only (hide 3D), labels only
7. Coordinate conversion verification (_gameToLngLat)
8. Screenshots at each stage

Run: .venv/bin/python3 tests/visual/test_render_diagnostic.py
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

# Ensure src/ on path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

OUTPUT_DIR = ROOT / "tests" / ".test-results" / "render-diagnostic"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

BASE_URL = os.environ.get("TRITIUM_URL", "http://localhost:8000")


def run_diagnostics():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page(viewport={"width": 1920, "height": 1080})

        # Enable console logging
        console_messages = []
        page.on("console", lambda msg: console_messages.append(f"[{msg.type}] {msg.text}"))

        print(f"{'='*60}")
        print(f"RENDER DIAGNOSTIC — MapLibre + Three.js Pipeline")
        print(f"{'='*60}")

        # ---- Step 1: Load page ----
        print(f"\n[1/9] Loading {BASE_URL} ...")
        page.goto(BASE_URL)
        page.wait_for_timeout(4000)  # Wait for MapLibre tiles + WS connection

        page.screenshot(path=str(OUTPUT_DIR / "01_initial.png"))
        print(f"  Saved 01_initial.png")

        # ---- Step 2: Check container sizing ----
        print("\n[2/9] Container sizing diagnostic...")
        container_info = page.evaluate("""
            (() => {
                const area = document.getElementById('tactical-area');
                const mapDiv = document.getElementById('maplibre-map');
                const legacyCanvas = document.getElementById('tactical-canvas');
                const mlCanvas = mapDiv ? mapDiv.querySelector('canvas') : null;

                return {
                    tacticalArea: area ? {
                        clientWidth: area.clientWidth,
                        clientHeight: area.clientHeight,
                        offsetWidth: area.offsetWidth,
                        offsetHeight: area.offsetHeight,
                        display: getComputedStyle(area).display,
                        position: getComputedStyle(area).position,
                        rect: area.getBoundingClientRect(),
                    } : 'NOT FOUND',
                    maplibreDiv: mapDiv ? {
                        clientWidth: mapDiv.clientWidth,
                        clientHeight: mapDiv.clientHeight,
                        display: getComputedStyle(mapDiv).display,
                        rect: mapDiv.getBoundingClientRect(),
                    } : 'NOT FOUND',
                    legacyCanvas: legacyCanvas ? {
                        display: getComputedStyle(legacyCanvas).display,
                        width: legacyCanvas.width,
                        height: legacyCanvas.height,
                    } : 'NOT FOUND',
                    maplibreCanvas: mlCanvas ? {
                        width: mlCanvas.width,
                        height: mlCanvas.height,
                        clientWidth: mlCanvas.clientWidth,
                        clientHeight: mlCanvas.clientHeight,
                    } : 'NOT FOUND',
                    dpr: window.devicePixelRatio,
                };
            })()
        """)
        with open(OUTPUT_DIR / "02_container_info.json", "w") as f:
            json.dump(container_info, f, indent=2)
        print(f"  tactical-area: {json.dumps(container_info.get('tacticalArea', 'N/A'), indent=4)}")
        print(f"  maplibre-map:  {json.dumps(container_info.get('maplibreDiv', 'N/A'), indent=4)}")
        print(f"  legacy canvas: {container_info.get('legacyCanvas', 'N/A')}")
        print(f"  ML canvas:     {container_info.get('maplibreCanvas', 'N/A')}")

        # ---- Step 3: MapLibre + geoCenter status ----
        print("\n[3/9] MapLibre + geoCenter status...")
        map_status = page.evaluate("""
            (() => {
                const ms = window._mapState;
                if (!ms) return { error: '_mapState not found on window' };

                return {
                    initialized: ms.initialized,
                    geoCenter: ms.geoCenter,
                    mapExists: !!ms.map,
                    threeRendererExists: !!ms.threeRenderer,
                    threeSceneExists: !!ms.threeScene,
                    threeRootExists: !!ms.threeRoot,
                    showUnits: ms.showUnits,
                    showLabels: ms.showLabels,
                    showModels3d: ms.showModels3d,
                    currentMode: ms.currentMode,
                    tiltMode: ms.tiltMode,
                    unitMarkerCount: Object.keys(ms.unitMarkers || {}).length,
                    unitMeshCount: Object.keys(ms.unitMeshes || {}).length,
                    effectCount: (ms.effects || []).length,
                };
            })()
        """)
        with open(OUTPUT_DIR / "03_map_status.json", "w") as f:
            json.dump(map_status, f, indent=2)
        print(f"  {json.dumps(map_status, indent=4)}")

        # ---- Step 4: Start battle ----
        print("\n[4/9] Starting battle...")
        # First try resetting
        reset_result = page.evaluate(
            "fetch('/api/game/reset', {method:'POST'}).then(r=>r.json()).catch(e=>({error:e.message}))"
        )
        print(f"  Reset: {reset_result}")
        page.wait_for_timeout(1000)

        # Check available scenarios
        scenarios = page.evaluate(
            "fetch('/api/game/scenarios').then(r=>r.json()).catch(e=>({error:e.message}))"
        )
        print(f"  Available scenarios: {scenarios}")

        # Start battle
        battle_result = page.evaluate(
            "fetch('/api/game/battle/street_combat', {method:'POST'}).then(r=>r.json()).catch(e=>({error:e.message}))"
        )
        print(f"  Battle: {battle_result}")
        page.wait_for_timeout(6000)  # Wait for countdown + first wave

        page.screenshot(path=str(OUTPUT_DIR / "04_battle_started.png"))
        print(f"  Saved 04_battle_started.png")

        # ---- Step 5: Unit positions in TritiumStore ----
        print("\n[5/9] TritiumStore unit positions...")
        unit_dump = page.evaluate("""
            (() => {
                const store = window.TritiumStore || {};
                if (!store.units) return { error: 'TritiumStore.units not found' };
                const result = [];
                for (const [id, unit] of store.units) {
                    result.push({
                        id,
                        name: unit.name,
                        type: unit.type,
                        alliance: unit.alliance,
                        position: unit.position,
                        status: unit.status,
                        health: unit.health,
                        maxHealth: unit.maxHealth,
                        fsmState: unit.fsmState || unit.fsm_state,
                    });
                }
                return { count: result.length, units: result };
            })()
        """)
        with open(OUTPUT_DIR / "05_unit_dump.json", "w") as f:
            json.dump(unit_dump, f, indent=2)
        print(f"  Units in store: {unit_dump.get('count', 'unknown')}")
        if "units" in unit_dump:
            for u in unit_dump["units"][:20]:
                pos = u.get("position") or {}
                x = pos.get("x", "?")
                y = pos.get("y", "?")
                print(f"    {u['id']}: ({x}, {y}) [{u.get('alliance', '?')}] [{u.get('status', '?')}] [{u.get('type', '?')}]")

        # ---- Step 6: DOM marker positions ----
        print("\n[6/9] DOM marker positions...")
        marker_info = page.evaluate("""
            (() => {
                const markers = document.querySelectorAll('.tritium-unit-marker');
                const result = [];
                for (const el of markers) {
                    const rect = el.getBoundingClientRect();
                    const parent = el.closest('.maplibregl-marker');
                    const parentTransform = parent ? getComputedStyle(parent).transform : 'none';
                    result.push({
                        unitId: el.dataset.unitId,
                        alliance: el.dataset.alliance,
                        display: getComputedStyle(el).display,
                        visibility: getComputedStyle(el).visibility,
                        opacity: getComputedStyle(el).opacity,
                        rect: { x: rect.x, y: rect.y, w: rect.width, h: rect.height },
                        parentTransform: parentTransform,
                        textContent: el.textContent.trim().slice(0, 20),
                    });
                }
                return { count: result.length, markers: result };
            })()
        """)
        with open(OUTPUT_DIR / "06_marker_positions.json", "w") as f:
            json.dump(marker_info, f, indent=2)
        print(f"  DOM markers found: {marker_info.get('count', 0)}")
        if "markers" in marker_info:
            for m in marker_info["markers"][:20]:
                r = m.get("rect", {})
                print(f"    {m['unitId']}: screen({r.get('x','?'):.0f}, {r.get('y','?'):.0f}) "
                      f"size={r.get('w','?'):.0f}x{r.get('h','?'):.0f} "
                      f"[{m.get('alliance','?')}] display={m.get('display')} "
                      f"text='{m.get('textContent','')}'")

        # Check if markers are clustered
        if "markers" in marker_info and len(marker_info["markers"]) > 1:
            xs = [m["rect"]["x"] for m in marker_info["markers"] if m["rect"].get("x") is not None]
            ys = [m["rect"]["y"] for m in marker_info["markers"] if m["rect"].get("y") is not None]
            if xs:
                x_range = max(xs) - min(xs)
                y_range = max(ys) - min(ys)
                print(f"\n  MARKER SPREAD: x_range={x_range:.0f}px, y_range={y_range:.0f}px")
                if x_range < 50 and y_range < 50:
                    print(f"  >>> WARNING: All markers clustered within {x_range:.0f}x{y_range:.0f}px!")
                    print(f"  >>> Avg position: ({sum(xs)/len(xs):.0f}, {sum(ys)/len(ys):.0f})")

        # ---- Step 7: Coordinate conversion test ----
        print("\n[7/9] Coordinate conversion test...")
        coord_test = page.evaluate("""
            (() => {
                const ms = window._mapState;
                if (!ms || !ms.geoCenter) return { error: 'no _mapState or geoCenter' };

                // Test converting known game positions to lng/lat
                const R = 6378137;
                const latRad = ms.geoCenter.lat * Math.PI / 180;
                const testPositions = [
                    { gx: 0, gy: 0, label: 'origin' },
                    { gx: 50, gy: 50, label: '50m NE' },
                    { gx: -50, gy: -50, label: '50m SW' },
                    { gx: 100, gy: 0, label: '100m E' },
                    { gx: 0, gy: 100, label: '100m N' },
                ];

                const results = [];
                for (const tp of testPositions) {
                    const dLng = tp.gx / (R * Math.cos(latRad)) * (180 / Math.PI);
                    const dLat = tp.gy / R * (180 / Math.PI);
                    const lng = ms.geoCenter.lng + dLng;
                    const lat = ms.geoCenter.lat + dLat;

                    // Project to screen coordinates via MapLibre
                    let screenPos = null;
                    if (ms.map) {
                        const px = ms.map.project([lng, lat]);
                        screenPos = { x: px.x, y: px.y };
                    }

                    results.push({
                        label: tp.label,
                        gamePos: { x: tp.gx, y: tp.gy },
                        lngLat: { lng, lat },
                        screenPos,
                    });
                }

                // Map viewport info
                const center = ms.map ? ms.map.getCenter() : null;
                const zoom = ms.map ? ms.map.getZoom() : null;
                const pitch = ms.map ? ms.map.getPitch() : null;
                const bearing = ms.map ? ms.map.getBearing() : null;
                const bounds = ms.map ? ms.map.getBounds() : null;

                return {
                    geoCenter: ms.geoCenter,
                    mapCenter: center ? { lng: center.lng, lat: center.lat } : null,
                    zoom, pitch, bearing,
                    bounds: bounds ? {
                        sw: { lng: bounds._sw.lng, lat: bounds._sw.lat },
                        ne: { lng: bounds._ne.lng, lat: bounds._ne.lat },
                    } : null,
                    conversions: results,
                };
            })()
        """)
        with open(OUTPUT_DIR / "07_coord_test.json", "w") as f:
            json.dump(coord_test, f, indent=2)
        print(f"  geoCenter: {coord_test.get('geoCenter')}")
        print(f"  mapCenter: {coord_test.get('mapCenter')}")
        print(f"  zoom: {coord_test.get('zoom')}, pitch: {coord_test.get('pitch')}, bearing: {coord_test.get('bearing')}")
        if "conversions" in coord_test:
            for c in coord_test["conversions"]:
                sp = c.get("screenPos") or {}
                print(f"    {c['label']}: game({c['gamePos']['x']}, {c['gamePos']['y']}) "
                      f"→ lng/lat({c['lngLat']['lng']:.6f}, {c['lngLat']['lat']:.6f}) "
                      f"→ screen({sp.get('x', '?'):.1f}, {sp.get('y', '?'):.1f})")

        # ---- Step 8: Layer isolation ----
        print("\n[8/9] Layer isolation tests...")

        # 8a: Hide 3D models, show only DOM markers
        page.evaluate("""
            (() => {
                const ms = window._mapState;
                if (!ms) return;
                // Hide 3D unit meshes
                ms.showModels3d = false;
                if (ms.threeScene) {
                    for (const [id, mesh] of Object.entries(ms.unitMeshes || {})) {
                        mesh.visible = false;
                    }
                }
                // Make sure DOM markers are visible
                ms.showUnits = true;
                ms.showLabels = true;
                for (const marker of Object.values(ms.unitMarkers || {})) {
                    marker.getElement().style.display = '';
                    // Make markers VERY visible for debugging
                    marker.getElement().style.outline = '3px solid yellow';
                }
            })()
        """)
        page.wait_for_timeout(500)
        page.screenshot(path=str(OUTPUT_DIR / "08a_markers_only.png"))
        print(f"  Saved 08a_markers_only.png (DOM markers highlighted, 3D hidden)")

        # 8b: Hide DOM markers, show only 3D models
        page.evaluate("""
            (() => {
                const ms = window._mapState;
                if (!ms) return;
                // Hide DOM markers
                for (const marker of Object.values(ms.unitMarkers || {})) {
                    marker.getElement().style.display = 'none';
                }
                // Show 3D models
                ms.showModels3d = true;
                if (ms.threeScene) {
                    for (const [id, mesh] of Object.entries(ms.unitMeshes || {})) {
                        mesh.visible = true;
                    }
                }
            })()
        """)
        page.wait_for_timeout(500)
        page.screenshot(path=str(OUTPUT_DIR / "08b_3d_only.png"))
        print(f"  Saved 08b_3d_only.png (3D models only, DOM markers hidden)")

        # 8c: Restore everything
        page.evaluate("""
            (() => {
                const ms = window._mapState;
                if (!ms) return;
                ms.showUnits = true;
                ms.showLabels = true;
                ms.showModels3d = true;
                for (const marker of Object.values(ms.unitMarkers || {})) {
                    marker.getElement().style.display = '';
                    marker.getElement().style.outline = '';
                }
                if (ms.threeScene) {
                    for (const [id, mesh] of Object.entries(ms.unitMeshes || {})) {
                        mesh.visible = true;
                    }
                }
            })()
        """)
        page.wait_for_timeout(500)
        page.screenshot(path=str(OUTPUT_DIR / "08c_all_restored.png"))
        print(f"  Saved 08c_all_restored.png (everything restored)")

        # ---- Step 9: Wait and final capture ----
        print("\n[9/9] Final capture after 10s of battle...")
        page.wait_for_timeout(10000)
        page.screenshot(path=str(OUTPUT_DIR / "09_after_10s.png"))

        # Final state dump
        final_state = page.evaluate("""
            (() => {
                const ms = window._mapState;
                const store = window.TritiumStore;

                const markers = document.querySelectorAll('.tritium-unit-marker');
                const markerPositions = [];
                for (const el of markers) {
                    const rect = el.getBoundingClientRect();
                    markerPositions.push({
                        unitId: el.dataset.unitId,
                        rect: { x: rect.x, y: rect.y, w: rect.width, h: rect.height },
                        text: el.textContent.trim().slice(0, 20),
                    });
                }

                const unitPositions = [];
                if (store && store.units) {
                    for (const [id, unit] of store.units) {
                        unitPositions.push({
                            id,
                            position: unit.position,
                            status: unit.status,
                            alliance: unit.alliance,
                        });
                    }
                }

                return {
                    markerCount: markerPositions.length,
                    unitCount: unitPositions.length,
                    markers: markerPositions,
                    units: unitPositions,
                    mapInitialized: ms ? ms.initialized : false,
                    threeActive: ms ? !!ms.threeRoot : false,
                    meshCount: ms ? Object.keys(ms.unitMeshes || {}).length : 0,
                };
            })()
        """)
        with open(OUTPUT_DIR / "09_final_state.json", "w") as f:
            json.dump(final_state, f, indent=2)
        print(f"  Final: {final_state.get('unitCount', 0)} units in store, "
              f"{final_state.get('markerCount', 0)} DOM markers, "
              f"{final_state.get('meshCount', 0)} 3D meshes")

        # ---- Summary ----
        print(f"\n{'='*60}")
        print("DIAGNOSTIC SUMMARY")
        print(f"{'='*60}")

        issues = []

        # Check container
        ta = container_info.get("tacticalArea", {})
        if isinstance(ta, str):
            issues.append(f"tactical-area: {ta}")
        elif ta.get("clientWidth", 0) == 0 or ta.get("clientHeight", 0) == 0:
            issues.append(f"tactical-area has zero dimensions: {ta.get('clientWidth')}x{ta.get('clientHeight')}")

        # Check MapLibre
        if not map_status.get("initialized"):
            issues.append("MapLibre NOT initialized")
        if not map_status.get("geoCenter"):
            issues.append("geoCenter NOT set")
        if not map_status.get("mapExists"):
            issues.append("MapLibre map instance NOT created")

        # Check units
        uc = unit_dump.get("count", 0)
        if uc == 0:
            issues.append("NO units in TritiumStore")
        mc = marker_info.get("count", 0)
        if mc == 0:
            issues.append("NO DOM markers found")
        if uc > 0 and mc == 0:
            issues.append(f"{uc} units in store but 0 DOM markers — markers not created!")

        # Check marker spread
        if "markers" in marker_info and len(marker_info["markers"]) > 1:
            xs = [m["rect"]["x"] for m in marker_info["markers"]]
            ys = [m["rect"]["y"] for m in marker_info["markers"]]
            x_range = max(xs) - min(xs)
            y_range = max(ys) - min(ys)
            if x_range < 50 and y_range < 50:
                issues.append(f"Markers CLUSTERED: spread only {x_range:.0f}x{y_range:.0f}px — likely coordinate conversion bug")
            avg_x = sum(xs) / len(xs)
            if avg_x < 200:
                issues.append(f"Markers on LEFT side: avg_x={avg_x:.0f}px — possible geoCenter or projection issue")

        # Check coordinate conversion
        if "conversions" in coord_test:
            for c in coord_test["conversions"]:
                sp = c.get("screenPos") or {}
                if sp.get("x") is not None and sp.get("y") is not None:
                    sx, sy = sp["x"], sp["y"]
                    if sx < -500 or sx > 2500 or sy < -500 or sy > 1500:
                        issues.append(f"Coordinate '{c['label']}' projects far off-screen: ({sx:.0f}, {sy:.0f})")

        # Check battle
        if isinstance(battle_result, dict) and "error" in battle_result:
            issues.append(f"Battle API error: {battle_result['error']}")
        if isinstance(battle_result, dict) and "detail" in battle_result:
            issues.append(f"Battle API error: {battle_result['detail']}")

        # Print console errors
        errors = [m for m in console_messages if "error" in m.lower() or "ERR" in m]
        if errors:
            issues.append(f"{len(errors)} console errors")
            print(f"\n  CONSOLE ERRORS ({len(errors)}):")
            for e in errors[:15]:
                print(f"    {e}")

        if issues:
            print(f"\n  ISSUES FOUND ({len(issues)}):")
            for i, issue in enumerate(issues, 1):
                print(f"    {i}. {issue}")
        else:
            print("\n  No issues detected — rendering pipeline looks healthy.")

        browser.close()

    print(f"\nAll diagnostic files saved to: {OUTPUT_DIR}")


if __name__ == "__main__":
    run_diagnostics()
