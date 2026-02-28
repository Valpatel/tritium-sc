# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Verify combat effects are visible and positioned near units.

Tests the threeEffectsRoot fix — effects should render in observe mode
(where threeRoot.visible = false but threeEffectsRoot stays visible).

Run: .venv/bin/python3 tests/visual/test_effects_visible.py
"""

import time
from pathlib import Path
from playwright.sync_api import sync_playwright

OUTPUT_DIR = Path("tests/.test-results/effects-visible")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
BASE_URL = "http://localhost:8000"


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page(viewport={"width": 1920, "height": 1080})

        logs = []
        page.on("console", lambda msg: logs.append(f"[{msg.type}] {msg.text}"))

        print("=" * 60)
        print("COMBAT EFFECTS VISIBILITY + POSITIONING TEST")
        print("=" * 60)

        print("\n[1/6] Loading Command Center...")
        page.goto(BASE_URL, wait_until="networkidle")
        time.sleep(5)

        # Set observe mode (which sets threeRoot.visible = false)
        page.evaluate("""() => {
            const s = window._mapState || {};
            if (s.map) {
                s.map.setPitch(0);
                s.map.setBearing(0);
                s.map.setZoom(16);
            }
        }""")
        time.sleep(2)

        page.screenshot(path=str(OUTPUT_DIR / "01_initial.png"))

        print("\n[2/6] Checking threeEffectsRoot setup...")
        setup = page.evaluate("""() => {
            const s = window._mapState || {};
            return {
                hasThreeScene: !!s.threeScene,
                hasThreeRoot: !!s.threeRoot,
                hasEffectsRoot: !!s.threeEffectsRoot,
                threeRootVisible: s.threeRoot ? s.threeRoot.visible : null,
                effectsRootVisible: s.threeEffectsRoot ? s.threeEffectsRoot.visible : null,
                effectsRootName: s.threeEffectsRoot ? s.threeEffectsRoot.name : null,
                effectsRootParent: s.threeEffectsRoot && s.threeEffectsRoot.parent
                    ? s.threeEffectsRoot.parent.type : null,
                showModels3d: s.showModels3d,
                currentMode: s.currentMode,
            };
        }""")
        for k, v in setup.items():
            flag = ""
            if k == 'threeRootVisible' and v is False:
                flag = " (OK - observe mode hides 3D models)"
            if k == 'effectsRootVisible' and v is True:
                flag = " <<< GOOD - effects always visible"
            elif k == 'effectsRootVisible' and v is False:
                flag = " <<< BAD - effects hidden!"
            print(f"  {k}: {v}{flag}")

        print("\n[3/6] Starting battle...")
        page.evaluate("""() => {
            if (window.EventBus) {
                window.EventBus.emit('game:command', { action: 'start' });
            }
        }""")
        time.sleep(8)  # Wait for wave 1 combat

        page.screenshot(path=str(OUTPUT_DIR / "02_battle_started.png"))

        print("\n[4/6] Checking effects state after combat begins...")
        effectsState = page.evaluate("""() => {
            const s = window._mapState || {};
            const effects = s.effects || [];
            const effectsRoot = s.threeEffectsRoot;
            const threeRoot = s.threeRoot;

            let effectsRootChildren = 0;
            let threeRootChildren = 0;
            if (effectsRoot) effectsRootChildren = effectsRoot.children.length;
            if (threeRoot) threeRootChildren = threeRoot.children.length;

            // Check draw calls by forcing a render
            if (s.threeRenderer && s.threeScene && s.threeCamera) {
                s.threeRenderer.info.reset();
            }

            return {
                activeEffects: effects.length,
                effectTypes: effects.map(e => e.type),
                effectsRootChildren,
                threeRootChildren,
                threeRootVisible: threeRoot ? threeRoot.visible : null,
                effectsRootVisible: effectsRoot ? effectsRoot.visible : null,
                rendererCalls: s.threeRenderer ? s.threeRenderer.info.render.calls : -1,
                rendererTriangles: s.threeRenderer ? s.threeRenderer.info.render.triangles : -1,
                rendererPrograms: s.threeRenderer ? s.threeRenderer.info.programs.length : -1,
            };
        }""")
        for k, v in effectsState.items():
            flag = ""
            if k == 'activeEffects' and v > 0:
                flag = " <<< EFFECTS ACTIVE!"
            elif k == 'activeEffects' and v == 0:
                flag = " (no effects yet - may need more combat time)"
            if k == 'effectsRootChildren' and v > 0:
                flag = f" <<< {v} Three.js effect objects"
            print(f"  {k}: {v}{flag}")

        print("\n[5/6] Waiting for more combat, then checking positions...")
        time.sleep(10)

        page.screenshot(path=str(OUTPUT_DIR / "03_mid_battle.png"))

        # Now check if effects are positioned near units
        posCheck = page.evaluate("""() => {
            const s = window._mapState || {};
            const effects = s.effects || [];
            const root = s.threeEffectsRoot;

            // Get all effect mesh world positions
            const effectPositions = [];
            if (root) {
                root.children.forEach(child => {
                    if (child.isMesh || child.isLine) {
                        effectPositions.push({
                            type: child.geometry?.type || 'unknown',
                            x: child.position.x.toFixed(1),
                            y: child.position.y.toFixed(1),
                            z: child.position.z.toFixed(1),
                            visible: child.visible,
                            materialVisible: child.material?.visible,
                        });
                    }
                });
            }

            // Get unit positions for comparison
            const unitPositions = [];
            if (s.threeRoot) {
                s.threeRoot.children.forEach(child => {
                    if (child.isGroup || child.isMesh) {
                        unitPositions.push({
                            name: child.name || 'unnamed',
                            x: child.position.x.toFixed(1),
                            y: child.position.y.toFixed(1),
                            z: child.position.z.toFixed(1),
                        });
                    }
                });
            }

            // Also check DOM explosion markers
            const domExplosions = document.querySelectorAll('.maplibregl-marker');
            let domMarkerCount = domExplosions.length;

            // Force a render and check draw calls
            let drawCalls = 0;
            let triangles = 0;
            if (s.threeRenderer) {
                drawCalls = s.threeRenderer.info.render.calls;
                triangles = s.threeRenderer.info.render.triangles;
            }

            return {
                effectMeshCount: effectPositions.length,
                effectSample: effectPositions.slice(0, 5),
                unitMeshCount: unitPositions.length,
                unitSample: unitPositions.slice(0, 5),
                domMarkerCount,
                drawCalls,
                triangles,
            };
        }""")
        print(f"  Effect meshes in threeEffectsRoot: {posCheck.get('effectMeshCount')}")
        print(f"  Unit meshes in threeRoot: {posCheck.get('unitMeshCount')}")
        print(f"  DOM markers: {posCheck.get('domMarkerCount')}")
        print(f"  Draw calls: {posCheck.get('drawCalls')}")
        print(f"  Triangles: {posCheck.get('triangles')}")

        if posCheck.get('effectSample'):
            print(f"\n  Sample effect positions:")
            for ep in posCheck['effectSample']:
                print(f"    {ep}")

        if posCheck.get('unitSample'):
            print(f"\n  Sample unit positions:")
            for up in posCheck['unitSample']:
                print(f"    {up}")

        print("\n[6/6] Pixel sampling to check for colored effect pixels...")
        # Sample pixels at known locations to see if effects are rendering
        pixelCheck = page.evaluate("""() => {
            const s = window._mapState || {};
            const canvas = s.map?.getCanvas();
            if (!canvas) return { error: 'no canvas' };

            const gl = canvas.getContext('webgl2') || canvas.getContext('webgl');
            if (!gl) return { error: 'no gl context' };

            const w = canvas.width;
            const h = canvas.height;

            // Sample a grid of pixels
            const samples = [];
            for (let row = 0; row < 5; row++) {
                for (let col = 0; col < 5; col++) {
                    const x = Math.floor(w * (col + 0.5) / 5);
                    const y = Math.floor(h * (row + 0.5) / 5);
                    const px = new Uint8Array(4);
                    gl.readPixels(x, y, 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, px);
                    // Only report non-background pixels (bright colors)
                    if (px[0] > 100 || px[1] > 100 || px[2] > 100) {
                        samples.push({
                            x, y,
                            r: px[0], g: px[1], b: px[2], a: px[3],
                        });
                    }
                }
            }

            return {
                canvasSize: { w, h },
                brightPixels: samples.length,
                samples: samples.slice(0, 10),
            };
        }""")
        print(f"  Canvas: {pixelCheck.get('canvasSize')}")
        print(f"  Bright pixel locations: {pixelCheck.get('brightPixels')}/25")
        if pixelCheck.get('samples'):
            for s in pixelCheck['samples'][:5]:
                print(f"    ({s['x']},{s['y']}): rgba({s['r']},{s['g']},{s['b']},{s['a']})")

        page.screenshot(path=str(OUTPUT_DIR / "04_final.png"))

        # Save console logs
        with open(OUTPUT_DIR / "console.txt", "w") as f:
            f.write("\n".join(logs))

        # Count effect-related log entries
        fx_logs = [l for l in logs if 'FX' in l or 'effect' in l.lower() or 'combat' in l.lower()]
        if fx_logs:
            print(f"\n  FX-related console logs ({len(fx_logs)}):")
            for l in fx_logs[:15]:
                print(f"    {l}")

        print(f"\nScreenshots in: {OUTPUT_DIR}")
        print("Browser open 10s for inspection...")
        time.sleep(10)
        browser.close()


if __name__ == "__main__":
    main()
