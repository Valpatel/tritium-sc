# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Diagnostic: identify what creates visual artifacts in the top-left corner.

Watch DOM mutations and screenshot rapidly during combat to catch transient
elements appearing at position (0,0) / top-left corner.

Run: .venv/bin/python3 tests/visual/test_topleft_debug.py
"""

import time
from pathlib import Path
from playwright.sync_api import sync_playwright

OUTPUT_DIR = Path("tests/.test-results/topleft-debug")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
BASE_URL = "http://localhost:8000"


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page(viewport={"width": 1920, "height": 1080})

        logs = []
        page.on("console", lambda msg: logs.append(f"[{msg.type}] {msg.text}"))

        print("=" * 60)
        print("TOP-LEFT CORNER ARTIFACT DIAGNOSTIC")
        print("=" * 60)

        print("\n[1/5] Loading Command Center...")
        page.goto(BASE_URL, wait_until="networkidle")
        time.sleep(5)

        # Install DOM mutation observer to catch elements appearing near top-left
        page.evaluate("""() => {
            window._tlDebug = {
                hits: [],
                markerPositions: [],
            };

            // Monitor MapLibre marker container for new children
            const mc = document.querySelector('.maplibregl-canvas-container')
                    || document.querySelector('.maplibregl-map');
            if (!mc) { console.warn('[TL-DBG] no map container found'); return; }

            // Watch for all marker-related elements
            const observer = new MutationObserver((mutations) => {
                for (const m of mutations) {
                    for (const node of m.addedNodes) {
                        if (!(node instanceof HTMLElement)) continue;

                        // Check if this is a marker or FX element
                        const rect = node.getBoundingClientRect();
                        const style = window.getComputedStyle(node);
                        const transform = style.transform || '';
                        const animation = style.animation || style.animationName || '';

                        // Record elements near top-left (within 200px of corner)
                        if (rect.left < 200 && rect.top < 200) {
                            window._tlDebug.hits.push({
                                tag: node.tagName,
                                class: node.className,
                                rect: { x: Math.round(rect.x), y: Math.round(rect.y),
                                        w: Math.round(rect.width), h: Math.round(rect.height) },
                                transform: transform.substring(0, 80),
                                animation: animation.substring(0, 80),
                                innerHTML: node.innerHTML.substring(0, 100),
                                time: Date.now(),
                            });
                        }
                    }
                }
            });

            observer.observe(document.body, { childList: true, subtree: true });

            // Also periodically sample all MapLibre markers
            setInterval(() => {
                const markers = document.querySelectorAll('.maplibregl-marker');
                for (const marker of markers) {
                    const rect = marker.getBoundingClientRect();
                    if (rect.left < 200 && rect.top < 200) {
                        window._tlDebug.markerPositions.push({
                            rect: { x: Math.round(rect.x), y: Math.round(rect.y),
                                    w: Math.round(rect.width), h: Math.round(rect.height) },
                            transform: marker.style.transform?.substring(0, 80) || '',
                            childCount: marker.children.length,
                            innerHTML: marker.innerHTML.substring(0, 100),
                            time: Date.now(),
                        });
                    }
                }
            }, 50);  // Check every 50ms

            // Monitor fx-screen-flash overlay
            const container = document.querySelector('.cmd-map-container')
                           || document.querySelector('#map-container');
            if (container) {
                const flashObserver = new MutationObserver(() => {
                    const flash = container.querySelector('.fx-screen-flash');
                    if (flash) {
                        const cs = window.getComputedStyle(flash);
                        const opacity = parseFloat(cs.opacity);
                        if (opacity > 0.01) {
                            window._tlDebug.hits.push({
                                tag: 'SCREEN-FLASH',
                                opacity: opacity,
                                background: cs.background?.substring(0, 80),
                                animation: cs.animation?.substring(0, 80),
                                time: Date.now(),
                            });
                        }
                    }
                });
                flashObserver.observe(container, { childList: true, subtree: true, attributes: true });
            }

            console.log('[TL-DBG] Monitoring installed');
        }""")
        time.sleep(1)

        print("\n[2/5] Starting battle...")
        page.evaluate("""() => {
            if (window.EventBus) {
                window.EventBus.emit('game:command', { action: 'start' });
            }
        }""")

        print("\n[3/5] Rapid screenshots during combat (30 frames over 15s)...")
        for i in range(30):
            time.sleep(0.5)
            page.screenshot(path=str(OUTPUT_DIR / f"frame_{i:03d}.png"))

        print("\n[4/5] Checking top-left debug data...")
        debug = page.evaluate("""() => {
            return {
                domHits: window._tlDebug.hits.length,
                domHitSamples: window._tlDebug.hits.slice(0, 20),
                markerHits: window._tlDebug.markerPositions.length,
                markerSamples: window._tlDebug.markerPositions.slice(0, 20),
            };
        }""")

        print(f"\n  DOM elements appearing near top-left: {debug['domHits']}")
        if debug['domHitSamples']:
            for h in debug['domHitSamples']:
                print(f"    {h}")

        print(f"\n  MapLibre markers near top-left: {debug['markerHits']}")
        if debug['markerSamples']:
            for m in debug['markerSamples']:
                print(f"    {m}")

        print("\n[5/5] Checking all markers for position anomalies...")
        markerCheck = page.evaluate("""() => {
            const markers = document.querySelectorAll('.maplibregl-marker');
            const results = [];
            for (const m of markers) {
                const rect = m.getBoundingClientRect();
                const transform = m.style.transform || '';

                // Check for markers at default position (transform: none or translate(0, 0))
                if (!transform || transform === 'none' ||
                    transform.includes('translate(0px') ||
                    transform.includes('translate(0,') ||
                    rect.x < 5 && rect.y < 5) {
                    results.push({
                        rect: { x: Math.round(rect.x), y: Math.round(rect.y),
                                w: Math.round(rect.width), h: Math.round(rect.height) },
                        transform,
                        classes: m.className,
                        html: m.innerHTML.substring(0, 100),
                    });
                }
            }
            return {
                totalMarkers: markers.length,
                anomalousMarkers: results.length,
                anomalies: results.slice(0, 10),
            };
        }""")
        print(f"\n  Total markers: {markerCheck['totalMarkers']}")
        print(f"  Anomalous (near 0,0): {markerCheck['anomalousMarkers']}")
        if markerCheck['anomalies']:
            for a in markerCheck['anomalies']:
                print(f"    {a}")

        with open(OUTPUT_DIR / "console.txt", "w") as f:
            f.write("\n".join(logs))

        fx_logs = [l for l in logs if 'TL-DBG' in l or 'FX' in l]
        if fx_logs:
            print(f"\n  Debug console logs ({len(fx_logs)}):")
            for l in fx_logs[:20]:
                print(f"    {l}")

        print(f"\nScreenshots in: {OUTPUT_DIR}")
        print("Browser open 10s for inspection...")
        time.sleep(10)
        browser.close()


if __name__ == "__main__":
    main()
