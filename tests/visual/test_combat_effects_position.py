# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Visual test: capture combat effects positioning during battle.

Starts a battle, captures screenshots at key moments (wave start, combat,
elimination), and saves them for manual inspection.

Run: .venv/bin/python3 tests/visual/test_combat_effects_position.py
"""

import time
import json
from pathlib import Path

from playwright.sync_api import sync_playwright


OUTPUT_DIR = Path("tests/.test-results/combat-effects-debug")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

BASE_URL = "http://localhost:8000"


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page(viewport={"width": 1920, "height": 1080})

        # Collect console logs
        logs = []
        page.on("console", lambda msg: logs.append(f"[{msg.type}] {msg.text}"))

        print("[1/8] Loading Command Center...")
        page.goto(BASE_URL, wait_until="networkidle")
        time.sleep(3)

        # Screenshot initial state
        page.screenshot(path=str(OUTPUT_DIR / "01_initial.png"))
        print(f"  Screenshot: {OUTPUT_DIR / '01_initial.png'}")

        # Check units in store
        unit_count = page.evaluate("() => window.TritiumStore?.units?.size || 0")
        print(f"  Units in store: {unit_count}")

        # Get geo center
        geo_center = page.evaluate("""() => {
            const mapState = window._mapState || {};
            return {
                geoCenter: mapState.geoCenter || null,
                initialized: mapState.initialized || false
            };
        }""")
        print(f"  Geo center: {geo_center}")

        # Reset and begin battle
        print("[2/8] Resetting game...")
        resp = page.evaluate("() => fetch('/api/game/reset', {method:'POST'}).then(r=>r.json())")
        print(f"  Reset: {resp}")
        time.sleep(1)

        print("[3/8] Beginning battle...")
        resp = page.evaluate("() => fetch('/api/game/begin', {method:'POST'}).then(r=>r.json())")
        print(f"  Begin: {resp}")

        # Wait for countdown
        time.sleep(6)
        page.screenshot(path=str(OUTPUT_DIR / "02_wave1_start.png"))
        print(f"  Screenshot: {OUTPUT_DIR / '02_wave1_start.png'}")

        # Log unit positions
        unit_data = page.evaluate("""() => {
            const result = [];
            if (window.TritiumStore?.units) {
                window.TritiumStore.units.forEach((u, id) => {
                    result.push({
                        id, name: u.name, type: u.type, alliance: u.alliance,
                        position: u.position, status: u.status,
                        fsmState: u.fsmState
                    });
                });
            }
            return result;
        }""")
        print(f"  Units ({len(unit_data)}):")
        for u in unit_data[:10]:
            print(f"    {u['id']}: {u.get('name','')} at ({u['position']['x']:.1f}, {u['position']['y']:.1f}) [{u['alliance']}] {u.get('status','?')} fsm={u.get('fsmState','?')}")

        # Save unit data as JSON
        with open(OUTPUT_DIR / "unit_positions.json", "w") as f:
            json.dump(unit_data, f, indent=2)

        # Add console intercept for combat events
        page.evaluate("""() => {
            window._combatEvents = [];
            const origEmit = window.EventBus?.emit;
            if (origEmit) {
                window.EventBus.emit = function(type, data) {
                    if (type.startsWith('combat:')) {
                        window._combatEvents.push({type, data: JSON.parse(JSON.stringify(data || {})), time: Date.now()});
                    }
                    return origEmit.apply(this, arguments);
                };
            }
        }""")

        # Wait for combat to start (wave 1 spawns hostiles, then engagement)
        print("[4/8] Waiting for combat engagement (15s)...")
        time.sleep(15)
        page.screenshot(path=str(OUTPUT_DIR / "03_combat_active.png"))
        print(f"  Screenshot: {OUTPUT_DIR / '03_combat_active.png'}")

        # Capture combat events
        combat_events = page.evaluate("() => window._combatEvents || []")
        print(f"  Combat events captured: {len(combat_events)}")
        if combat_events:
            with open(OUTPUT_DIR / "combat_events.json", "w") as f:
                json.dump(combat_events, f, indent=2)
            # Show first few
            for ev in combat_events[:5]:
                pos_info = ""
                if ev['data'].get('source_pos'):
                    sp = ev['data']['source_pos']
                    pos_info += f" src=({sp.get('x',0):.1f},{sp.get('y',0):.1f})"
                if ev['data'].get('target_pos'):
                    tp = ev['data']['target_pos']
                    pos_info += f" tgt=({tp.get('x',0):.1f},{tp.get('y',0):.1f})"
                if ev['data'].get('position'):
                    p = ev['data']['position']
                    pos_info += f" pos=({p.get('x',0):.1f},{p.get('y',0):.1f})"
                print(f"    {ev['type']}{pos_info}")

        # Get current unit positions again
        unit_data2 = page.evaluate("""() => {
            const result = [];
            if (window.TritiumStore?.units) {
                window.TritiumStore.units.forEach((u, id) => {
                    result.push({
                        id, name: u.name, type: u.type, alliance: u.alliance,
                        position: u.position, status: u.status
                    });
                });
            }
            return result;
        }""")
        print(f"\n  Units now ({len(unit_data2)}):")
        for u in unit_data2[:10]:
            print(f"    {u['id']}: at ({u['position']['x']:.1f}, {u['position']['y']:.1f}) [{u['alliance']}] {u.get('status','?')}")

        # More combat screenshots
        print("[5/8] Capturing more combat (10s)...")
        time.sleep(5)
        page.screenshot(path=str(OUTPUT_DIR / "04_combat_mid.png"))
        time.sleep(5)
        page.screenshot(path=str(OUTPUT_DIR / "05_combat_late.png"))
        print(f"  Screenshots saved")

        # Check effects state
        effects_state = page.evaluate("""() => {
            const mapState = window._mapState || {};
            return {
                effectsCount: mapState.effects?.length || 0,
                unitMeshCount: mapState.unitMeshes ? Object.keys(mapState.unitMeshes).length : 0,
                threeRootChildren: mapState.threeRoot?.children?.length || 0,
                effectsActive: mapState.effectsActive || false,
            };
        }""")
        print(f"  Effects state: {effects_state}")

        # Wait for more combat / eliminations
        print("[6/8] Waiting for eliminations (20s)...")
        time.sleep(20)
        page.screenshot(path=str(OUTPUT_DIR / "06_eliminations.png"))

        # Final combat events count
        combat_events2 = page.evaluate("() => (window._combatEvents || []).length")
        print(f"  Total combat events: {combat_events2}")

        # All combat events with positions
        all_events = page.evaluate("() => window._combatEvents || []")
        with open(OUTPUT_DIR / "all_combat_events.json", "w") as f:
            json.dump(all_events, f, indent=2)

        # Check for any console errors
        errors = [l for l in logs if l.startswith("[error]")]
        if errors:
            print(f"\n  Console errors ({len(errors)}):")
            for e in errors[:10]:
                print(f"    {e}")

        print("[7/8] Final screenshot...")
        page.screenshot(path=str(OUTPUT_DIR / "07_final.png"))

        # Dump full console log
        with open(OUTPUT_DIR / "console_log.txt", "w") as f:
            f.write("\n".join(logs))

        print(f"\n[8/8] Done. {len(logs)} console messages, {combat_events2} combat events")
        print(f"Screenshots saved to: {OUTPUT_DIR}")

        # Keep browser open for manual inspection
        print("\nBrowser staying open for 10s for inspection...")
        time.sleep(10)

        browser.close()


if __name__ == "__main__":
    main()
