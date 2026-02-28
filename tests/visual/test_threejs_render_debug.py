# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Diagnostic: is Three.js actually rendering anything on the MapLibre canvas?

Tests:
1. Is the render() callback being called?
2. What projection matrix values are present?
3. Does a large bright sphere produce visible pixels?
4. Does a Mercator-space sphere produce visible pixels?
5. What WebGL state is active during render?

Run: .venv/bin/python3 tests/visual/test_threejs_render_debug.py
"""

import time
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

OUTPUT_DIR = Path("tests/.test-results/threejs-render-debug")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
BASE_URL = "http://localhost:8000"


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page(viewport={"width": 1920, "height": 1080})

        logs = []
        page.on("console", lambda msg: logs.append(f"[{msg.type}] {msg.text}"))

        print("=" * 60)
        print("THREE.JS RENDER DIAGNOSTIC")
        print("=" * 60)

        print("\n[1/8] Loading Command Center...")
        page.goto(BASE_URL, wait_until="networkidle")
        time.sleep(5)

        # Set deterministic camera
        page.evaluate("""() => {
            const s = window._mapState || {};
            if (s.map) {
                s.map.setPitch(0);
                s.map.setBearing(0);
                s.map.setZoom(16);
            }
        }""")
        time.sleep(2)

        print("\n[2/8] Checking Three.js initialization...")
        init = page.evaluate("""() => {
            const s = window._mapState || {};
            const result = {
                hasScene: !!s.threeScene,
                hasCamera: !!s.threeCamera,
                hasRenderer: !!s.threeRenderer,
                hasRoot: !!s.threeRoot,
                hasRefMatrix: !!s._refMatrix,
                ms: s._ms,
                refMc: s._refMc ? {x: s._refMc.x, y: s._refMc.y, z: s._refMc.z} : null,
                sceneChildren: s.threeScene ? s.threeScene.children.length : -1,
                rootChildren: s.threeRoot ? s.threeRoot.children.length : -1,
            };

            // Check if three-overlay layer exists in MapLibre
            if (s.map) {
                try {
                    const layer = s.map.getLayer('three-overlay');
                    result.layerExists = !!layer;
                } catch(e) {
                    result.layerExists = false;
                    result.layerError = e.message;
                }
            }

            // Check WebGL context state
            if (s.threeRenderer) {
                const gl = s.threeRenderer.getContext();
                result.glContextLost = gl.isContextLost();
                result.glViewport = Array.from(gl.getParameter(gl.VIEWPORT));
                result.glDrawingBufferSize = {
                    w: gl.drawingBufferWidth,
                    h: gl.drawingBufferHeight,
                };
            }

            return result;
        }""")
        for k, v in init.items():
            print(f"  {k}: {v}")

        if not init.get('hasScene'):
            print("\n  FATAL: Three.js scene not initialized. Aborting.")
            browser.close()
            return

        print("\n[3/8] Installing render() diagnostic hook...")
        page.evaluate("""() => {
            window._renderDiag = {
                calls: 0,
                lastMatrix: null,
                lastError: null,
                glState: null,
            };

            const s = window._mapState || {};

            // Store original render and wrap it
            if (!s._origRender) {
                // We can't easily intercept the custom layer's render()
                // since MapLibre calls it internally. Instead, instrument
                // the camera projection matrix setter.
                const origProj = s.threeCamera.projectionMatrix;

                // Count frames by watching for triggerRepaint calls
                const origRepaint = s.map.triggerRepaint.bind(s.map);
                let repaintCount = 0;
                s.map.triggerRepaint = function() {
                    repaintCount++;
                    return origRepaint();
                };
                window._renderDiag.getRepaintCount = () => repaintCount;
            }
        }""")
        time.sleep(2)

        repaintsBefore = page.evaluate("() => window._renderDiag.getRepaintCount ? window._renderDiag.getRepaintCount() : -1")
        time.sleep(2)
        repaintsAfter = page.evaluate("() => window._renderDiag.getRepaintCount ? window._renderDiag.getRepaintCount() : -1")
        fps = (repaintsAfter - repaintsBefore) / 2
        print(f"  Repaint rate: {fps:.1f} fps (expect ~60)")
        print(f"  Repaints in 2s: {repaintsAfter - repaintsBefore}")

        page.screenshot(path=str(OUTPUT_DIR / "00_baseline.png"))

        print("\n[4/8] Reading camera projection matrix...")
        matrix = page.evaluate("""() => {
            const s = window._mapState || {};
            if (!s.threeCamera) return {error: 'no camera'};

            const pe = s.threeCamera.projectionMatrix.elements;
            const re = s._refMatrix ? s._refMatrix.elements : null;

            return {
                proj: Array.from(pe).map(v => v.toExponential(4)),
                ref: re ? Array.from(re).map(v => v.toExponential(4)) : null,
                projDet: new THREE.Matrix4().copy(s.threeCamera.projectionMatrix).determinant(),
            };
        }""")
        print(f"  Projection matrix (col-major):")
        if matrix.get('proj'):
            m = matrix['proj']
            for row in range(4):
                vals = [m[row + col * 4] for col in range(4)]
                print(f"    [{', '.join(vals)}]")
        print(f"  Determinant: {matrix.get('projDet')}")
        if matrix.get('ref'):
            print(f"  RefMatrix elements: {matrix['ref'][:8]}...")

        print("\n[5/8] Injecting test sphere (50m radius, bright red)...")
        page.evaluate("""() => {
            const s = window._mapState || {};
            if (!s.threeRoot) return;

            // Remove any existing test objects
            const toRemove = [];
            s.threeRoot.traverse(child => {
                if (child.name && child.name.startsWith('diag-')) toRemove.push(child);
            });
            toRemove.forEach(obj => {
                obj.parent.remove(obj);
                if (obj.geometry) obj.geometry.dispose();
                if (obj.material) obj.material.dispose();
            });

            // Create a big bright red sphere at game center
            const geo = new THREE.SphereGeometry(50, 16, 16);
            const mat = new THREE.MeshBasicMaterial({
                color: 0xff0000,
                side: THREE.DoubleSide,
                depthTest: false,
                depthWrite: false,
            });
            const mesh = new THREE.Mesh(geo, mat);
            mesh.position.set(0, 0, 5);
            mesh.frustumCulled = false;
            mesh.name = 'diag-sphere-red';
            s.threeRoot.add(mesh);

            // Create a second sphere offset 100m east
            const geo2 = new THREE.SphereGeometry(50, 16, 16);
            const mat2 = new THREE.MeshBasicMaterial({
                color: 0x00ff00,
                side: THREE.DoubleSide,
                depthTest: false,
                depthWrite: false,
            });
            const mesh2 = new THREE.Mesh(geo2, mat2);
            mesh2.position.set(100, 0, 5);
            mesh2.frustumCulled = false;
            mesh2.name = 'diag-sphere-green';
            s.threeRoot.add(mesh2);

            console.log('[DIAG] Added 2 spheres. Root children: ' + s.threeRoot.children.length);

            // Log the world positions after matrix update
            s.threeScene.updateMatrixWorld(true);
            const wp1 = mesh.getWorldPosition(new THREE.Vector3());
            const wp2 = mesh2.getWorldPosition(new THREE.Vector3());
            console.log('[DIAG] Sphere1 worldPos: ' + wp1.x.toFixed(2) + ',' + wp1.y.toFixed(2) + ',' + wp1.z.toFixed(2));
            console.log('[DIAG] Sphere2 worldPos: ' + wp2.x.toFixed(2) + ',' + wp2.y.toFixed(2) + ',' + wp2.z.toFixed(2));

            // Test: manually project sphere center to clip space
            const projMat = s.threeCamera.projectionMatrix;
            const clip1 = wp1.clone().applyMatrix4(projMat);
            const clip2 = wp2.clone().applyMatrix4(projMat);
            console.log('[DIAG] Sphere1 clipSpace: ' + clip1.x.toFixed(6) + ',' + clip1.y.toFixed(6) + ',' + clip1.z.toFixed(6) + ',' + ' w=' + clip1.w);
            console.log('[DIAG] Sphere2 clipSpace: ' + clip2.x.toFixed(6) + ',' + clip2.y.toFixed(6) + ',' + clip2.z.toFixed(6) + ',' + ' w=' + clip2.w);

            // Compute NDC (clip / w)
            if (clip1.w) {
                console.log('[DIAG] Sphere1 NDC: ' + (clip1.x).toFixed(6) + ',' + (clip1.y).toFixed(6) + ',' + (clip1.z).toFixed(6));
            }
        }""")
        time.sleep(2)
        page.screenshot(path=str(OUTPUT_DIR / "01_spheres_injected.png"))

        print("\n[6/8] Manual render test — force render with simple scene...")
        page.evaluate("""() => {
            const s = window._mapState || {};
            if (!s.threeRenderer || !s.threeCamera) return;

            // Create a standalone test: render a full-screen red triangle
            // using an orthographic camera to see if the WebGL renderer works at all
            const testScene = new THREE.Scene();
            const testCam = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1);

            // Full-screen quad in NDC
            const quadGeo = new THREE.PlaneGeometry(0.5, 0.5);
            const quadMat = new THREE.MeshBasicMaterial({
                color: 0xff00ff, // bright magenta
                side: THREE.DoubleSide,
                depthTest: false,
            });
            const quad = new THREE.Mesh(quadGeo, quadMat);
            quad.position.z = -0.5;
            testScene.add(quad);

            // Manually trigger a render with the test scene
            const gl = s.threeRenderer.getContext();
            s.threeRenderer.resetState();
            gl.depthMask(true);
            gl.clear(gl.DEPTH_BUFFER_BIT);
            s.threeRenderer.render(testScene, testCam);

            console.log('[DIAG] Forced render of test scene with orthographic camera');

            // Clean up
            quadGeo.dispose();
            quadMat.dispose();
        }""")
        time.sleep(0.5)
        page.screenshot(path=str(OUTPUT_DIR / "02_forced_ortho_render.png"))

        print("\n[7/8] Testing pixel readback during render callback...")
        # This hooks into the actual render loop to read pixels
        pixelTest = page.evaluate("""() => {
            return new Promise(resolve => {
                const s = window._mapState || {};
                if (!s.threeRenderer) { resolve({error: 'no renderer'}); return; }

                const gl = s.threeRenderer.getContext();

                // Use requestAnimationFrame to read pixels right after a render
                let attempts = 0;
                function check() {
                    attempts++;
                    // Read pixels from different locations
                    const w = gl.drawingBufferWidth;
                    const h = gl.drawingBufferHeight;
                    const cx = Math.floor(w / 2);
                    const cy = Math.floor(h / 2);

                    const results = {};

                    // Center
                    const p1 = new Uint8Array(4);
                    gl.readPixels(cx, cy, 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, p1);
                    results.center = {r: p1[0], g: p1[1], b: p1[2], a: p1[3]};

                    // Scan for any non-zero pixels on the canvas
                    let nonZero = 0;
                    let samples = [];
                    for (let y = 0; y < h; y += 100) {
                        for (let x = 0; x < w; x += 100) {
                            const px = new Uint8Array(4);
                            gl.readPixels(x, y, 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, px);
                            if (px[0] > 0 || px[1] > 0 || px[2] > 0) {
                                nonZero++;
                                if (samples.length < 5) {
                                    samples.push({x, y, r: px[0], g: px[1], b: px[2], a: px[3]});
                                }
                            }
                        }
                    }

                    results.nonZeroPixels = nonZero;
                    results.totalSampled = Math.ceil(w/100) * Math.ceil(h/100);
                    results.samples = samples;
                    results.bufferSize = {w, h};
                    results.attempts = attempts;
                    resolve(results);
                }

                // Wait for next frame
                requestAnimationFrame(check);
            });
        }""")
        print(f"  Buffer size: {pixelTest.get('bufferSize')}")
        print(f"  Center pixel: {pixelTest.get('center')}")
        print(f"  Non-zero pixels: {pixelTest.get('nonZeroPixels')}/{pixelTest.get('totalSampled')}")
        for s in pixelTest.get('samples', []):
            print(f"    ({s['x']},{s['y']}): rgba=({s['r']},{s['g']},{s['b']},{s['a']})")

        print("\n[8/8] Checking console logs for errors and diagnostics...")
        # Filter for relevant messages
        diag_msgs = [l for l in logs if 'DIAG' in l or 'error' in l.lower() or 'warn' in l.lower() or 'three' in l.lower() or 'webgl' in l.lower()]
        for msg in diag_msgs[:30]:
            print(f"  {msg}")

        # Check for any JavaScript errors
        errors = [l for l in logs if l.startswith('[error]')]
        if errors:
            print(f"\n  ERRORS ({len(errors)}):")
            for e in errors[:10]:
                print(f"    {e}")

        # Save all logs
        with open(OUTPUT_DIR / "console.txt", "w") as f:
            f.write("\n".join(logs))

        # Summary
        print("\n" + "=" * 60)
        print("SUMMARY")
        print("=" * 60)
        print(f"  Three.js initialized: {init.get('hasScene', False)}")
        print(f"  Layer exists: {init.get('layerExists', False)}")
        print(f"  GL context lost: {init.get('glContextLost', False)}")
        print(f"  Repaint rate: {fps:.1f} fps")
        print(f"  Scene children: {init.get('sceneChildren', -1)}")
        print(f"  Root children: {init.get('rootChildren', -1)}")
        print(f"  Meter scale (ms): {init.get('ms')}")
        print(f"  readPixels non-zero: {pixelTest.get('nonZeroPixels', 0)}/{pixelTest.get('totalSampled', 0)}")

        if pixelTest.get('nonZeroPixels', 0) == 0:
            print("\n  DIAGNOSIS: readPixels returns ALL zeros.")
            print("  This usually means:")
            print("    A) preserveDrawingBuffer=false (normal for MapLibre)")
            print("    B) Render IS happening but buffer is cleared after swap")
            print("    C) The screenshot will show the composited result even if readPixels doesn't")
            print("\n  Check the screenshots to see if spheres are visible!")

        print(f"\nScreenshots in: {OUTPUT_DIR}")
        print("Browser open 15s for inspection...")
        time.sleep(15)
        browser.close()


if __name__ == "__main__":
    main()
