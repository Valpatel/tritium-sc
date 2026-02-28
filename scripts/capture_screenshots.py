# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Capture fresh screenshots of the Command Center for docs.

Takes screenshots of key UI states including thought bubbles.
"""

import time
from pathlib import Path
from playwright.sync_api import sync_playwright

OUTPUT_DIR = Path("docs/screenshots")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

BASE_URL = "http://localhost:8000"


def capture(page, name, delay=0):
    if delay:
        time.sleep(delay)
    path = OUTPUT_DIR / f"{name}.png"
    page.screenshot(path=str(path), full_page=False)
    print(f"  captured: {path}")
    return path


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            device_scale_factor=1,
        )
        page = context.new_page()

        print("Loading command center...")
        page.goto(BASE_URL, wait_until="networkidle")
        page.wait_for_timeout(3000)

        # 1. Command center default
        print("\n[1/7] Command center - observe mode")
        capture(page, "command-center", delay=1)

        # 2. Wait for thought bubbles (8-15s interval)
        print("\n[2/7] Waiting for thought bubbles to appear (~20s)...")
        page.wait_for_timeout(20000)
        capture(page, "command-center-thoughts", delay=0)

        # 3. Zoom in to see thought bubbles clearly
        print("\n[3/7] Zoomed view with thought bubbles")
        page.mouse.move(960, 540)
        for _ in range(5):
            page.mouse.wheel(0, -200)
            page.wait_for_timeout(200)
        page.wait_for_timeout(10000)  # Wait for next thought cycle
        capture(page, "zoomed-thoughts", delay=0)

        # 4. Tactical mode
        print("\n[4/7] Tactical mode")
        page.keyboard.press("t")
        capture(page, "tactical-mode", delay=1)

        # 5. Setup mode
        print("\n[5/7] Setup mode")
        page.keyboard.press("s")
        capture(page, "setup-mode", delay=1)

        # Back to observe
        page.keyboard.press("o")
        page.wait_for_timeout(500)

        # 6. Start battle
        print("\n[6/7] Battle - countdown + combat")
        page.keyboard.press("b")
        capture(page, "battle-countdown", delay=3)

        # 7. Combat in progress (wait for hostiles)
        print("\n[7/7] Battle - combat with NPC reactions")
        page.wait_for_timeout(12000)
        capture(page, "battle-combat", delay=0)

        print(f"\nDone! Screenshots saved to {OUTPUT_DIR}/")
        print("Keeping browser open for 10s...")
        page.wait_for_timeout(10000)
        browser.close()


if __name__ == "__main__":
    main()
