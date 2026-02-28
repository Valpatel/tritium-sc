# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Final verification: combat effects positioned at units, no top-left spill.

Run: .venv/bin/python3 tests/visual/test_effects_final.py
"""

import time
from pathlib import Path
from playwright.sync_api import sync_playwright

OUTPUT_DIR = Path("tests/.test-results/effects-final")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
BASE_URL = "http://localhost:8000"


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page(viewport={"width": 1920, "height": 1080})

        logs = []
        page.on("console", lambda msg: logs.append(f"[{msg.type}] {msg.text}"))

        print("=" * 60)
        print("FINAL EFFECTS VERIFICATION")
        print("=" * 60)

        print("\n[1] Loading Command Center...")
        page.goto(BASE_URL, wait_until="networkidle")
        time.sleep(5)

        print("[2] Starting battle and waiting for combat...")
        page.evaluate("""() => {
            if (window.EventBus) {
                window.EventBus.emit('game:command', { action: 'start' });
            }
        }""")

        # Wait for first combat event
        print("    Waiting for combat events...")
        for i in range(30):
            time.sleep(1)
            fx_count = len([l for l in logs if '[FX-' in l])
            if fx_count > 0:
                print(f"    Combat started after {i+1}s ({fx_count} FX events)")
                break
        else:
            print("    WARNING: No combat events after 30s")

        # Capture rapid screenshots during active combat
        print("[3] Capturing combat frames...")
        for i in range(10):
            time.sleep(0.3)
            page.screenshot(path=str(OUTPUT_DIR / f"combat_{i:02d}.png"))

        # Wait for more combat (eliminations)
        time.sleep(5)
        for i in range(10):
            time.sleep(0.3)
            page.screenshot(path=str(OUTPUT_DIR / f"late_{i:02d}.png"))

        print("[4] Checking marker positions...")
        check = page.evaluate("""() => {
            const markers = document.querySelectorAll('.maplibregl-marker');
            let nearTopLeft = 0;
            let total = markers.length;
            let fxMarkers = 0;

            for (const m of markers) {
                const rect = m.getBoundingClientRect();
                // Check for clipped wrapper (200x200 or 160x160)
                if (rect.width >= 150 && rect.width <= 210) fxMarkers++;
                if (rect.left < 100 && rect.top < 100) nearTopLeft++;
            }

            return { total, fxMarkers, nearTopLeft };
        }""")
        print(f"    Total markers: {check['total']}")
        print(f"    FX markers (clipped): {check['fxMarkers']}")
        print(f"    Near top-left: {check['nearTopLeft']}")

        # Print FX logs
        fx_logs = [l for l in logs if '[FX-' in l]
        print(f"\n[5] FX events: {len(fx_logs)}")
        for l in fx_logs[:10]:
            print(f"    {l}")

        elim_logs = [l for l in logs if '[FX-ELIM]' in l]
        if elim_logs:
            print(f"\n    Eliminations: {len(elim_logs)}")
            for l in elim_logs[:5]:
                print(f"    {l}")

        with open(OUTPUT_DIR / "console.txt", "w") as f:
            f.write("\n".join(logs))

        print(f"\nScreenshots in: {OUTPUT_DIR}")
        print("Browser open 10s for visual inspection...")
        time.sleep(10)
        browser.close()


if __name__ == "__main__":
    main()
