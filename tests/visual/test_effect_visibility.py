# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Visual test: verify combat effects are visible and correctly positioned.

After the AdditiveBlending -> NormalBlending fix, effects should be visible
on bright satellite tiles and positioned at the correct unit locations.

Run: .venv/bin/python3 tests/visual/test_effect_visibility.py
"""

import time
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

OUTPUT_DIR = Path("tests/.test-results/effect-visibility")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
BASE_URL = "http://localhost:8000"


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page(viewport={"width": 1920, "height": 1080})

        logs = []
        page.on("console", lambda msg: logs.append(f"[{msg.type}] {msg.text}"))

        print("[1/6] Loading Command Center...")
        page.goto(BASE_URL, wait_until="networkidle")
        time.sleep(3)

        print("[2/6] Resetting game...")
        page.evaluate("() => fetch('/api/game/reset', {method:'POST'}).then(r=>r.json())")
        time.sleep(1)

        # Get unit positions
        units = page.evaluate("""() => {
            const result = [];
            window.TritiumStore.units.forEach((u, id) => {
                if (u.alliance === 'friendly' && u.position) {
                    result.push({id, name: u.name, x: u.position.x, y: u.position.y});
                }
            });
            return result;
        }""")
        print(f"  {len(units)} friendly units")

        # Pick Heavy Turret Front Gate at (0, 50) — a known stationary unit
        target = None
        for u in units:
            if 'heavy_turret' in (u.get('name', '') + u.get('id', '')).lower() or u.get('x') == 0 and u.get('y') == 50:
                target = u
                break
        if not target:
            target = units[0] if units else {'id': 'fake', 'name': 'Test', 'x': 0, 'y': 0}
        print(f"  Target: {target['name']} at ({target['x']}, {target['y']})")

        page.screenshot(path=str(OUTPUT_DIR / "01_before.png"))

        # Inject a series of combat events at known positions
        print("[3/6] Injecting combat events at target position...")
        tid = target['id']
        tx = target['x']
        ty = target['y']

        # Projectile from (0,0) to target
        page.evaluate(f"""() => {{
            window.EventBus.emit('combat:projectile', {{
                source_id: 'fake-src',
                source_pos: {{ x: 0, y: 0 }},
                target_id: '{tid}',
                target_pos: {{ x: {tx}, y: {ty} }},
                projectile_type: 'nerf_heavy_turret',
                damage: 25
            }});
        }}""")

        # Take screenshots during tracer flight
        for i in range(5):
            time.sleep(0.12)
            page.screenshot(path=str(OUTPUT_DIR / f"02_tracer_{i}.png"))

        # Hit at target position
        page.evaluate(f"""() => {{
            window.EventBus.emit('combat:hit', {{
                target_id: '{tid}',
                source_id: 'fake-src',
                projectile_type: 'nerf_heavy_turret',
                damage: 25,
                position: {{ x: {tx}, y: {ty} }}
            }});
        }}""")
        time.sleep(0.05)
        page.screenshot(path=str(OUTPUT_DIR / "03_hit.png"))
        time.sleep(0.1)
        page.screenshot(path=str(OUTPUT_DIR / "03_hit_late.png"))

        # Elimination at target position
        page.evaluate(f"""() => {{
            window.EventBus.emit('combat:elimination', {{
                target_id: '{tid}',
                target_name: '{target["name"]}',
                interceptor_name: 'Test Debug',
                position: {{ x: {tx}, y: {ty} }},
                method: 'nerf_heavy_turret'
            }});
        }}""")
        for i in range(10):
            time.sleep(0.15)
            page.screenshot(path=str(OUTPUT_DIR / f"04_elim_{i}.png"))

        print("  Screenshots captured")

        # Check Three.js effect state
        print("[4/6] Checking Three.js effect state...")
        state = page.evaluate("""() => {
            const s = window._mapState || {};
            const effects = s.effects || [];
            const info = [];
            for (const fx of effects) {
                const meshList = fx.meshes || (fx.particles ? fx.particles.map(p=>p.mesh) : []);
                const positions = meshList.slice(0, 3).map(m => ({
                    x: m.position.x.toFixed(1),
                    y: m.position.y.toFixed(1),
                    z: m.position.z.toFixed(1),
                    visible: m.visible,
                    opacity: m.material ? m.material.opacity.toFixed(2) : 'N/A',
                    blending: m.material ? m.material.blending : 'N/A',
                }));
                info.push({
                    type: fx.type,
                    meshCount: meshList.length,
                    positions,
                });
            }
            return {
                effectsCount: effects.length,
                threeRootChildren: s.threeRoot ? s.threeRoot.children.length : 0,
                effects: info,
            };
        }""")
        print(f"  Active effects: {state.get('effectsCount', 0)}")
        print(f"  ThreeRoot children: {state.get('threeRootChildren', 0)}")
        for e in state.get('effects', []):
            print(f"    {e['type']}: {e['meshCount']} meshes")
            for p in e.get('positions', []):
                blend_name = {0: 'NoBlending', 1: 'NormalBlending', 2: 'AdditiveBlending'}.get(p.get('blending'), str(p.get('blending')))
                print(f"      pos=({p['x']},{p['y']},{p['z']}) vis={p['visible']} opacity={p['opacity']} blend={blend_name}")

        # Verify blending mode is Normal (1) not Additive (2)
        all_blendings = []
        for e in state.get('effects', []):
            for p in e.get('positions', []):
                if isinstance(p.get('blending'), (int, float)):
                    all_blendings.append(p['blending'])
        additive_count = sum(1 for b in all_blendings if b == 2)
        normal_count = sum(1 for b in all_blendings if b == 1)
        print(f"\n  Blending check: {normal_count} NormalBlending, {additive_count} AdditiveBlending")
        if additive_count > 0:
            print("  WARNING: Some effects still use AdditiveBlending!")

        # Check console logs for FX debug messages
        print("\n[5/6] Console FX logs:")
        fx_logs = [l for l in logs if l.startswith("[log] [FX-")]
        for l in fx_logs:
            print(f"  {l}")

        # Final screenshot
        page.screenshot(path=str(OUTPUT_DIR / "05_final.png"))
        with open(OUTPUT_DIR / "console.txt", "w") as f:
            f.write("\n".join(logs))
        with open(OUTPUT_DIR / "state.json", "w") as f:
            json.dump(state, f, indent=2)

        print("\n[6/6] Done.")
        print(f"Screenshots in: {OUTPUT_DIR}")
        print("\nBrowser open 10s for inspection...")
        time.sleep(10)
        browser.close()


if __name__ == "__main__":
    main()
