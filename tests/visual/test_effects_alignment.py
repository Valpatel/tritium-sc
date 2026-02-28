# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Diagnostic: verify combat effects appear at the same position as unit markers.

Injects fake combat events at known unit positions and verifies:
1. DOM effects (MapLibre markers) appear at the same lng/lat as unit markers
2. Three.js effects appear at the same game-meter coordinates as unit meshes
3. Screenshots zoomed in to clearly show alignment

Run: .venv/bin/python3 tests/visual/test_effects_alignment.py
"""

import time
import json
from pathlib import Path

from playwright.sync_api import sync_playwright


OUTPUT_DIR = Path("tests/.test-results/effects-alignment")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

BASE_URL = "http://localhost:8000"


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page(viewport={"width": 1920, "height": 1080})

        logs = []
        page.on("console", lambda msg: logs.append(f"[{msg.type}] {msg.text}"))

        print("[1/9] Loading Command Center...")
        page.goto(BASE_URL, wait_until="networkidle")
        time.sleep(3)

        # Reset game to setup mode
        print("[2/9] Resetting game...")
        page.evaluate("() => fetch('/api/game/reset', {method:'POST'}).then(r=>r.json())")
        time.sleep(1)

        # Get friendly unit positions
        print("[3/9] Reading unit positions...")
        units = page.evaluate("""() => {
            const result = [];
            if (window.TritiumStore?.units) {
                window.TritiumStore.units.forEach((u, id) => {
                    result.push({
                        id, name: u.name, type: u.type, alliance: u.alliance,
                        position: u.position
                    });
                });
            }
            return result;
        }""")

        friendlies = [u for u in units if u.get("alliance") == "friendly"]
        print(f"  Found {len(friendlies)} friendly units")

        # Pick a stationary turret
        target_unit = None
        for u in friendlies:
            t = (u.get("type") or "").lower()
            if "heavy_turret" in t:
                target_unit = u
                break
        if not target_unit:
            for u in friendlies:
                t = (u.get("type") or "").lower()
                if "turret" in t:
                    target_unit = u
                    break
        if not target_unit:
            target_unit = friendlies[0]

        tx = target_unit["position"]["x"]
        ty = target_unit["position"]["y"]
        tid = target_unit["id"]
        print(f"  Target: {target_unit['name']} at ({tx:.1f}, {ty:.1f})")

        # ZOOM IN to the target unit area
        print("[4/9] Zooming map to target unit...")
        page.evaluate(f"""() => {{
            // Get the map instance
            const mapEl = document.getElementById('map');
            if (mapEl && mapEl._mapInstance) {{
                mapEl._mapInstance.flyTo({{
                    center: window._gameToLngLatGlobal ? window._gameToLngLatGlobal({tx}, {ty}) : mapEl._mapInstance.getCenter(),
                    zoom: 19,
                    duration: 0
                }});
            }}
        }}""")
        time.sleep(0.5)

        # Try getting the map via the module's exposed function
        zoom_result = page.evaluate(f"""() => {{
            // Find maplibregl map instance — it's stored in the custom layer's map reference
            // or we can find it via the canvas
            const canvases = document.querySelectorAll('canvas.maplibregl-canvas');
            for (const c of canvases) {{
                const parent = c.closest('.maplibregl-map');
                if (parent && parent._mapInstance) {{
                    parent._mapInstance.jumpTo({{ zoom: 19 }});
                    return 'zoomed via parent._mapInstance';
                }}
            }}
            // Try getting map from maplibregl global
            if (typeof maplibregl !== 'undefined') {{
                // Search for map container
                const mapDiv = document.getElementById('map') || document.querySelector('[class*=maplibre]');
                // The map object might be stored in a closure — inject a getter via EventBus
                // Actually, let's just set the zoom via the map's resize
                return 'maplibregl found but no direct reference';
            }}
            return 'no map found';
        }}""")
        print(f"  Zoom attempt: {zoom_result}")

        # Use a different approach — find the map reference through the custom layer
        page.evaluate(f"""() => {{
            // The map-maplibre module likely stores map on _state which isn't accessible.
            // But we CAN emit a centering event that the module handles.
            if (window.EventBus) {{
                window.EventBus.emit('map:center', {{ x: {tx}, y: {ty}, zoom: 19 }});
            }}
        }}""")
        time.sleep(1)

        page.screenshot(path=str(OUTPUT_DIR / "01_zoomed_before.png"))

        # Check if centering worked
        print("[5/9] Installing position verifiers...")
        page.evaluate("""() => {
            // Override _spawnDomFlash and _spawnDomExplosion to log marker positions
            window._domEffectPositions = [];
            window._threeEffectPositions = [];

            // Hook into EventBus to capture what happens after combat events
            const origEmit = window.EventBus.emit.bind(window.EventBus);
            window._effectHookInstalled = true;

            // We can't access module-scoped functions directly.
            // Instead, we'll monitor DOM mutations for new maplibregl markers
            // and check Three.js root children count changes.

            // Mutation observer for DOM effects
            const observer = new MutationObserver((mutations) => {
                for (const m of mutations) {
                    for (const node of m.addedNodes) {
                        if (node.nodeType === 1) {
                            // Check for combat effect markers (non-unit markers)
                            const style = node.style?.cssText || '';
                            if (style.includes('fx-flash') || style.includes('fx-explode') ||
                                style.includes('fx-shockwave') || style.includes('fx-float-text') ||
                                style.includes('radial-gradient') && style.includes('pointer-events:none')) {
                                // This is likely a combat effect DOM element
                                // Get its position via the MapLibre marker transform
                                const markerEl = node.closest('.maplibregl-marker');
                                if (markerEl) {
                                    const transform = markerEl.style.transform || '';
                                    window._domEffectPositions.push({
                                        transform,
                                        time: Date.now(),
                                        html: node.outerHTML.substring(0, 200)
                                    });
                                }
                            }
                        }
                    }
                }
            });
            const mapContainer = document.querySelector('.maplibregl-map') || document.body;
            observer.observe(mapContainer, { childList: true, subtree: true });
            window._effectObserver = observer;

            console.log('[ALIGN] Position verifiers installed');
        }""")

        # Also add a visible debug marker at the target position for reference
        page.evaluate(f"""() => {{
            // Add a large, bright reference circle at the target position
            if (typeof maplibregl !== 'undefined') {{
                const geoCenter = window.TritiumStore?.get?.('geo.center');
                if (geoCenter) {{
                    const R = 6378137;
                    const latRad = geoCenter.lat * Math.PI / 180;
                    const dLng = {tx} / (R * Math.cos(latRad)) * (180 / Math.PI);
                    const dLat = {ty} / R * (180 / Math.PI);
                    const lng = geoCenter.lng + dLng;
                    const lat = geoCenter.lat + dLat;

                    // Create a big green crosshair at the target
                    const cross = document.createElement('div');
                    cross.style.cssText = `
                        width: 40px; height: 40px; position: relative; pointer-events: none;
                        border: 3px solid #05ffa1; border-radius: 50%;
                        box-shadow: 0 0 20px #05ffa1;
                    `;
                    const hLine = document.createElement('div');
                    hLine.style.cssText = 'position:absolute; top:50%; left:-10px; right:-10px; height:2px; background:#05ffa1;';
                    const vLine = document.createElement('div');
                    vLine.style.cssText = 'position:absolute; left:50%; top:-10px; bottom:-10px; width:2px; background:#05ffa1;';
                    cross.appendChild(hLine);
                    cross.appendChild(vLine);

                    // Find map instance
                    const maps = document.querySelectorAll('.maplibregl-canvas');
                    let mapInst = null;
                    if (maps.length > 0) {{
                        const mapContainer = maps[0].closest('.maplibregl-map');
                        // Walk up to find getMap or use global
                    }}

                    // Use the same approach as unit markers
                    window._debugCrosshair = new maplibregl.Marker({{ element: cross, anchor: 'center' }})
                        .setLngLat([lng, lat]);
                    // We need the map instance to add it...
                    // Try to get it from the module
                    console.log('[ALIGN] Debug crosshair lngLat: ' + lng + ', ' + lat);
                    window._debugCrosshairLngLat = [lng, lat];
                }}
            }}
        }}""")

        # Get the map instance handle for zooming — check if the module exposed it
        print("[6/9] Trying to access map for zoom...")
        map_access = page.evaluate("""() => {
            // Check common patterns
            const checks = {
                'window._mapState': !!window._mapState,
                'window._mapInstance': !!window._mapInstance,
                'document.getElementById("map")': !!document.getElementById('map'),
                'maplibregl': typeof maplibregl !== 'undefined',
            };
            // Also check the actual map container's internal reference
            const container = document.querySelector('.maplibregl-map');
            if (container) {
                // MapLibre stores the map on the container as a _map property (internal)
                const keys = [];
                for (const k in container) {
                    if (k.startsWith('_') && typeof container[k] === 'object' && container[k]?.getZoom) {
                        keys.push(k);
                    }
                }
                checks['container_map_keys'] = keys;
            }

            // Try to get zoom level
            try {
                const maps = maplibregl.Map;  // this is the constructor, not instance
            } catch(e) {}

            return checks;
        }""")
        print(f"  Map access: {json.dumps(map_access, indent=2)}")

        # Approach: find the map through its container element
        zoomed = page.evaluate("""() => {
            const container = document.querySelector('.maplibregl-map');
            if (!container) return 'no container';
            // MapLibre attaches the map instance to the container element
            // Try iterating all properties
            for (const key of Object.getOwnPropertyNames(container)) {
                const val = container[key];
                if (val && typeof val === 'object' && typeof val.getZoom === 'function') {
                    val.jumpTo({ zoom: 19 });
                    return 'zoomed via ' + key;
                }
            }
            // Also try non-enumerable via prototype chain
            let proto = container;
            while (proto) {
                for (const key of Object.getOwnPropertyNames(proto)) {
                    try {
                        const val = container[key];
                        if (val && typeof val === 'object' && typeof val.getZoom === 'function') {
                            val.jumpTo({ zoom: 19 });
                            return 'zoomed via prototype ' + key;
                        }
                    } catch(e) {}
                }
                proto = Object.getPrototypeOf(proto);
                if (proto === HTMLElement.prototype) break;
            }
            return 'map method not found on container';
        }""")
        print(f"  Zoom result: {zoomed}")

        # Alternative: use keyboard shortcuts or evaluate the module's internal
        # Actually, the map.js module might listen for a specific EventBus event for centering
        # Let's look for that — or just scroll the map via the wheel event
        page.evaluate("""() => {
            // Dispatch wheel event to zoom in
            const canvas = document.querySelector('.maplibregl-canvas');
            if (canvas) {
                for (let i = 0; i < 15; i++) {
                    canvas.dispatchEvent(new WheelEvent('wheel', {
                        deltaY: -100, clientX: 960, clientY: 540,
                        bubbles: true, cancelable: true
                    }));
                }
            }
        }""")
        time.sleep(2)

        page.screenshot(path=str(OUTPUT_DIR / "02_zoomed_in.png"))
        print("  Screenshot: 02_zoomed_in.png")

        # Now inject effects
        print("[7/9] Injecting combat events at known unit position...")

        # Tracer from origin to turret
        page.evaluate(f"""() => {{
            window.EventBus.emit('combat:projectile', {{
                source_id: 'fake-source',
                source_pos: {{ x: 0, y: 0 }},
                target_id: '{tid}',
                target_pos: {{ x: {tx}, y: {ty} }},
                projectile_type: 'nerf_missile_launcher',
                damage: 50
            }});
        }}""")

        # Take screenshots during tracer flight
        for i in range(5):
            time.sleep(0.1)
            page.screenshot(path=str(OUTPUT_DIR / f"03_tracer_{i}.png"))

        # Hit
        page.evaluate(f"""() => {{
            window.EventBus.emit('combat:hit', {{
                target_id: '{tid}',
                source_id: 'fake-source',
                projectile_type: 'nerf_missile_launcher',
                damage: 50,
                position: {{ x: {tx}, y: {ty} }}
            }});
        }}""")
        time.sleep(0.1)
        page.screenshot(path=str(OUTPUT_DIR / "04_hit.png"))

        # Elimination
        page.evaluate(f"""() => {{
            window.EventBus.emit('combat:elimination', {{
                target_id: '{tid}',
                target_name: '{target_unit["name"]}',
                interceptor_name: 'Debug Turret',
                position: {{ x: {tx}, y: {ty} }},
                method: 'nerf_missile_launcher'
            }});
        }}""")
        for i in range(8):
            time.sleep(0.15)
            page.screenshot(path=str(OUTPUT_DIR / f"05_elim_{i}.png"))

        print("  Screenshots captured during effect lifecycle")

        # Capture programmatic data about effect positions
        print("[8/9] Verifying positions programmatically...")

        # Get the actual pixel positions of unit markers and effect markers
        position_data = page.evaluate(f"""() => {{
            // Find the unit marker for our target
            const unitMarker = document.querySelector('[data-unit-id="{tid}"]');
            let unitMarkerPos = null;
            if (unitMarker) {{
                const rect = unitMarker.getBoundingClientRect();
                unitMarkerPos = {{ left: rect.left, top: rect.top, width: rect.width, height: rect.height }};
                // Also get the maplibregl marker transform
                const closest = unitMarker.closest('.maplibregl-marker');
                if (closest) {{
                    unitMarkerPos.transform = closest.style.transform;
                }}
            }}

            // Find all current maplibregl markers that look like effects
            const allMarkers = document.querySelectorAll('.maplibregl-marker');
            const effectMarkers = [];
            for (const m of allMarkers) {{
                // Effect markers have pointer-events:none children
                const child = m.firstElementChild;
                if (child && child.style.pointerEvents === 'none') {{
                    effectMarkers.push({{
                        transform: m.style.transform,
                        rect: m.getBoundingClientRect(),
                        html: m.innerHTML.substring(0, 100)
                    }});
                }}
            }}

            // Get Three.js root children info
            let threeInfo = null;
            // Can't access _state directly, but check if effects array is accessible
            // via some global path

            return {{
                unitMarkerPos,
                effectMarkerCount: effectMarkers.length,
                effectMarkers: effectMarkers.slice(0, 5),
                domEffectPositions: window._domEffectPositions || [],
                totalMarkers: allMarkers.length
            }};
        }}""")

        print(f"  Unit marker position: {json.dumps(position_data.get('unitMarkerPos'), indent=2)}")
        print(f"  Effect markers found: {position_data.get('effectMarkerCount', 0)}")
        print(f"  Total markers: {position_data.get('totalMarkers', 0)}")
        print(f"  DOM effect positions captured: {len(position_data.get('domEffectPositions', []))}")

        for em in position_data.get("effectMarkers", []):
            print(f"    Effect marker transform: {em.get('transform', 'none')}")
            print(f"    Effect marker rect: {json.dumps(em.get('rect', {}))}")

        for dep in position_data.get("domEffectPositions", [])[:5]:
            print(f"    DOM effect: transform={dep.get('transform', 'none')}")

        with open(OUTPUT_DIR / "position_data.json", "w") as f:
            json.dump(position_data, f, indent=2)

        # Console log dump
        with open(OUTPUT_DIR / "console_log.txt", "w") as f:
            f.write("\n".join(logs))

        errors = [l for l in logs if l.startswith("[error]")]
        align_logs = [l for l in logs if "ALIGN" in l]
        if errors:
            print(f"\n  Console errors:")
            for e in errors[:5]:
                print(f"    {e}")
        for a in align_logs:
            print(f"  {a}")

        print("[9/9] Done.")
        print(f"Screenshots in: {OUTPUT_DIR}")

        print("\nBrowser open 10s for inspection...")
        time.sleep(10)
        browser.close()


if __name__ == "__main__":
    main()
