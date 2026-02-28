# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Diagnostic: trace combat effect positions during a real battle.

Hooks into EventBus combat events in the browser, captures the exact
game coordinates and screen coordinates where effects are placed,
and takes screenshots at each elimination for visual verification.

Run: .venv/bin/python3 tests/visual/test_effect_position_trace.py
"""

import time
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

OUTPUT_DIR = Path("tests/.test-results/effect-position-trace")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
BASE_URL = "http://localhost:8000"


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page(viewport={"width": 1920, "height": 1080})

        console_logs = []
        page.on("console", lambda msg: console_logs.append(f"[{msg.type}] {msg.text}"))

        print("[1/7] Loading Command Center...")
        page.goto(BASE_URL, wait_until="networkidle")
        time.sleep(3)

        # Install combat event interceptors
        print("[2/7] Installing combat event interceptors...")
        page.evaluate("""() => {
            window._effectTrace = [];
            window._elimScreenshots = [];

            // Hook into _gameToLngLat to trace what it returns
            const origEmit = window.EventBus.emit.bind(window.EventBus);
            window.EventBus.emit = function(type, data) {
                if (type === 'combat:projectile') {
                    // Resolve what the effect handler will use
                    const srcUnit = data.source_id ? window.TritiumStore.units.get(data.source_id) : null;
                    const tgtUnit = data.target_id ? window.TritiumStore.units.get(data.target_id) : null;
                    const srcPos = srcUnit?.position || data.source_pos || {};
                    const tgtPos = tgtUnit?.position || data.target_pos || {};
                    window._effectTrace.push({
                        type: 'combat:projectile',
                        time: Date.now(),
                        srcFromStore: !!srcUnit?.position,
                        tgtFromStore: !!tgtUnit?.position,
                        srcX: srcPos.x, srcY: srcPos.y,
                        tgtX: tgtPos.x, tgtY: tgtPos.y,
                        rawData: JSON.parse(JSON.stringify(data))
                    });
                }
                if (type === 'combat:elimination') {
                    const elimUnit = data.target_id ? window.TritiumStore.units.get(data.target_id) : null;
                    const pos = (elimUnit?.position) || data.position || {};
                    window._effectTrace.push({
                        type: 'combat:elimination',
                        time: Date.now(),
                        posFromStore: !!elimUnit?.position,
                        posX: pos.x, posY: pos.y,
                        posType: typeof pos.x,
                        posIsNaN: isNaN(pos.x),
                        rawPosition: data.position,
                        storePosition: elimUnit?.position,
                        targetId: data.target_id,
                        targetInStore: !!elimUnit,
                    });
                    // Flag for screenshot
                    window._lastElimTime = Date.now();
                }
                if (type === 'combat:hit') {
                    const hitUnit = data.target_id ? window.TritiumStore.units.get(data.target_id) : null;
                    const pos = (hitUnit?.position) || data.position || {};
                    window._effectTrace.push({
                        type: 'combat:hit',
                        time: Date.now(),
                        posFromStore: !!hitUnit?.position,
                        posX: pos.x, posY: pos.y,
                        rawPosition: data.position,
                    });
                }
                return origEmit(type, data);
            };

            console.log('[TRACE] Combat event interceptors installed');
        }""")

        # Also install a DOM mutation observer to track where markers appear
        page.evaluate("""() => {
            window._domEffectLog = [];
            const observer = new MutationObserver((mutations) => {
                for (const m of mutations) {
                    for (const node of m.addedNodes) {
                        if (node.nodeType !== 1) continue;
                        const marker = node.closest?.('.maplibregl-marker');
                        if (!marker) continue;
                        // Check if this is an effect marker (not a unit marker)
                        if (node.classList?.contains('tritium-unit-marker')) continue;
                        if (node.classList?.contains('tritium-unit-inner')) continue;
                        const style = node.style?.cssText || '';
                        if (style.includes('pointer-events') || style.includes('radial-gradient')
                            || style.includes('fx-flash') || style.includes('fx-explode')
                            || style.includes('fx-shockwave') || style.includes('fx-float-text')) {
                            const transform = marker.style?.transform || 'NONE';
                            const rect = marker.getBoundingClientRect();
                            window._domEffectLog.push({
                                time: Date.now(),
                                transform,
                                screenX: Math.round(rect.left + rect.width/2),
                                screenY: Math.round(rect.top + rect.height/2),
                                width: Math.round(rect.width),
                                height: Math.round(rect.height),
                                tag: style.substring(0, 80),
                            });
                        }
                    }
                }
            });
            const mapContainer = document.querySelector('.maplibregl-map') || document.body;
            observer.observe(mapContainer, { childList: true, subtree: true });
            console.log('[TRACE] DOM mutation observer installed');
        }""")

        # Reset and start battle
        print("[3/7] Resetting game...")
        page.evaluate("() => fetch('/api/game/reset', {method:'POST'}).then(r=>r.json())")
        time.sleep(1)

        # Get geoCenter and mapState info
        geo_info = page.evaluate("""() => {
            const ms = window._mapState || {};
            return {
                geoCenter: ms.geoCenter,
                hasMap: !!ms.map,
                hasThreeScene: !!ms.threeScene,
                initialized: ms.initialized,
                ms: ms._ms,
            };
        }""")
        print(f"  GeoCenter: {json.dumps(geo_info.get('geoCenter'))}")
        print(f"  Map state: initialized={geo_info.get('initialized')}, threeScene={geo_info.get('hasThreeScene')}")
        print(f"  Meter scale (_ms): {geo_info.get('ms')}")

        # Get current units
        units_info = page.evaluate("""() => {
            const result = [];
            if (window.TritiumStore?.units) {
                window.TritiumStore.units.forEach((u, id) => {
                    if (u.alliance === 'friendly') {
                        result.push({
                            id: id.substring(0, 8),
                            name: u.name,
                            posX: u.position?.x,
                            posY: u.position?.y,
                        });
                    }
                });
            }
            return result;
        }""")
        print(f"  Friendly units: {len(units_info)}")
        for u in units_info[:5]:
            print(f"    {u['name']}: ({u['posX']}, {u['posY']})")

        page.screenshot(path=str(OUTPUT_DIR / "01_before_battle.png"))

        # Begin battle
        print("[4/7] Starting battle...")
        page.evaluate("() => fetch('/api/game/begin', {method:'POST'}).then(r=>r.json())")
        time.sleep(7)  # Wait for countdown + wave 1

        page.screenshot(path=str(OUTPUT_DIR / "02_wave1_active.png"))

        # Wait for combat to happen (30 seconds of waves)
        print("[5/7] Monitoring combat events for 40 seconds...")
        elim_count = 0
        for tick in range(80):  # 80 * 0.5s = 40s
            time.sleep(0.5)

            # Check for new eliminations
            trace = page.evaluate("() => window._effectTrace || []")
            elims = [t for t in trace if t.get('type') == 'combat:elimination']
            if len(elims) > elim_count:
                # New elimination! Take screenshot
                for e in elims[elim_count:]:
                    elim_count = len(elims)
                    print(f"  ELIM #{elim_count}: pos=({e.get('posX')}, {e.get('posY')}) "
                          f"fromStore={e.get('posFromStore')} "
                          f"posType={e.get('posType')} isNaN={e.get('posIsNaN')}")
                    if e.get('rawPosition'):
                        print(f"    rawPosition: {json.dumps(e.get('rawPosition'))}")
                    if e.get('storePosition'):
                        print(f"    storePosition: {json.dumps(e.get('storePosition'))}")
                    page.screenshot(path=str(OUTPUT_DIR / f"03_elim_{elim_count}.png"))

            # Take periodic screenshots during combat
            if tick % 10 == 0:
                page.screenshot(path=str(OUTPUT_DIR / f"04_combat_t{tick}.png"))

        # Collect all trace data
        print("[6/7] Collecting trace data...")
        trace = page.evaluate("() => window._effectTrace || []")
        dom_log = page.evaluate("() => window._domEffectLog || []")

        print(f"\n  Total combat events: {len(trace)}")
        projectiles = [t for t in trace if t.get('type') == 'combat:projectile']
        hits = [t for t in trace if t.get('type') == 'combat:hit']
        elims = [t for t in trace if t.get('type') == 'combat:elimination']

        print(f"  Projectiles: {len(projectiles)}")
        print(f"  Hits: {len(hits)}")
        print(f"  Eliminations: {len(elims)}")

        print(f"\n  DOM effect markers logged: {len(dom_log)}")
        for d in dom_log[:10]:
            print(f"    screen=({d.get('screenX')}, {d.get('screenY')}) "
                  f"size={d.get('width')}x{d.get('height')} "
                  f"transform={d.get('transform', 'NONE')[:60]}")

        # Check for position anomalies
        print("\n  Position analysis:")
        zero_positions = [t for t in elims if (t.get('posX') == 0 and t.get('posY') == 0)]
        nan_positions = [t for t in elims if t.get('posIsNaN')]
        none_positions = [t for t in elims if t.get('posX') is None]
        store_found = [t for t in elims if t.get('posFromStore')]
        store_missing = [t for t in elims if not t.get('posFromStore')]

        print(f"    Elims with store position: {len(store_found)}")
        print(f"    Elims missing from store: {len(store_missing)}")
        print(f"    Elims at (0,0): {len(zero_positions)}")
        print(f"    Elims with NaN position: {len(nan_positions)}")
        print(f"    Elims with None position: {len(none_positions)}")

        if store_missing:
            print("\n  STORE MISSES:")
            for t in store_missing:
                print(f"    targetId={t.get('targetId')}, targetInStore={t.get('targetInStore')}")
                print(f"    rawPosition={json.dumps(t.get('rawPosition'))}")

        # Save all data
        with open(OUTPUT_DIR / "trace_data.json", "w") as f:
            json.dump({"trace": trace, "domLog": dom_log, "geoInfo": geo_info}, f, indent=2)

        # Relevant console messages
        effect_logs = [l for l in console_logs if "TRACE" in l or "EFFECT" in l or "error" in l.lower()]
        with open(OUTPUT_DIR / "console.txt", "w") as f:
            f.write("\n".join(console_logs))
        print(f"\n  Console messages with TRACE/EFFECT/error: {len(effect_logs)}")
        for l in effect_logs[:10]:
            print(f"    {l}")

        page.screenshot(path=str(OUTPUT_DIR / "05_final.png"))
        print("\n[7/7] Done.")
        print(f"Data saved to: {OUTPUT_DIR}")

        print("\nBrowser open 10s for inspection...")
        time.sleep(10)
        browser.close()


if __name__ == "__main__":
    main()
