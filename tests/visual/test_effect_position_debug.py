# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Diagnostic: capture combat effects with larger sizing for visibility.

Run: .venv/bin/python3 tests/visual/test_effect_position_debug.py
"""

import time
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

OUTPUT_DIR = Path("tests/.test-results/effect-position-debug")
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
        time.sleep(4)

        print("[2/6] Reset + begin battle...")
        page.evaluate("() => fetch('/api/game/reset', {method:'POST'}).then(r=>r.json())")
        time.sleep(1)
        page.evaluate("() => fetch('/api/game/begin', {method:'POST'}).then(r=>r.json())")
        time.sleep(1)
        page.screenshot(path=str(OUTPUT_DIR / "00_battle_started.png"))

        print("[3/6] Waiting for combat events (up to 60s)...")
        shot = 0
        for tick in range(120):
            time.sleep(0.5)

            # Check effects count
            data = page.evaluate("""() => {
                const s = window._mapState || {};
                const effects = s.effects || [];
                return {
                    count: effects.length,
                    types: effects.map(e => e.type),
                    childCount: s.threeRoot ? s.threeRoot.children.length : 0,
                };
            }""")

            if data['count'] > 0:
                page.screenshot(path=str(OUTPUT_DIR / f"fx_{shot:03d}.png"))
                print(f"  t={tick*0.5:.0f}s: {data['count']} effects ({', '.join(data['types'][:5])}), "
                      f"{data['childCount']} scene children")
                shot += 1

                if shot >= 30:
                    break

            if tick % 20 == 0:
                gs = page.evaluate("() => fetch('/api/game/state').then(r=>r.json())")
                print(f"  t={tick*0.5:.0f}s: state={gs['state']} wave={gs['wave']} remaining={gs.get('wave_hostiles_remaining',0)}")

        print(f"\n[4/6] Captured {shot} effect screenshots")

        # Also inject a manual test: a long-lasting DOM marker at a known position
        print("[5/6] Injecting test markers at known positions...")
        page.evaluate("""() => {
            const s = window._mapState || {};
            if (!s.map || !s.geoCenter) return;

            // Place colored circles at specific game positions
            const positions = [
                { gx: 0, gy: 0, label: 'CENTER (0,0)', color: '#fcee0a' },
                { gx: 0, gy: 50, label: 'TURRET (0,50)', color: '#05ffa1' },
                { gx: -40, gy: 35, label: 'NW (-40,35)', color: '#05ffa1' },
                { gx: 40, gy: -35, label: 'SE (40,-35)', color: '#05ffa1' },
                { gx: 100, gy: -100, label: 'FAR SE (100,-100)', color: '#ff2a6d' },
            ];

            const R = 6378137;
            const latRad = s.geoCenter.lat * Math.PI / 180;

            for (const p of positions) {
                const dLng = p.gx / (R * Math.cos(latRad)) * (180 / Math.PI);
                const dLat = p.gy / R * (180 / Math.PI);
                const lngLat = [s.geoCenter.lng + dLng, s.geoCenter.lat + dLat];

                const el = document.createElement('div');
                el.style.cssText = [
                    'width:40px; height:40px; border-radius:50%;',
                    'border:4px solid ' + p.color + ';',
                    'background:' + p.color + '33;',
                    'pointer-events:none; position:relative;',
                    'box-shadow: 0 0 15px ' + p.color + ';',
                ].join('');
                const label = document.createElement('div');
                label.textContent = p.label;
                label.style.cssText = [
                    'position:absolute; top:-20px; left:50%; transform:translateX(-50%);',
                    'color:' + p.color + '; font-size:10px; font-family:monospace;',
                    'white-space:nowrap; text-shadow:0 0 3px #000;',
                ].join('');
                el.appendChild(label);

                new maplibregl.Marker({ element: el, anchor: 'center' })
                    .setLngLat(lngLat)
                    .addTo(s.map);
            }
        }""")
        time.sleep(1)
        page.screenshot(path=str(OUTPUT_DIR / "99_test_markers.png"))

        # Save console log
        with open(OUTPUT_DIR / "console.txt", "w") as f:
            f.write("\n".join(logs))

        print(f"[6/6] Done. Screenshots: {OUTPUT_DIR}")
        print("Browser open 15s for inspection...")
        time.sleep(15)
        browser.close()


if __name__ == "__main__":
    main()
