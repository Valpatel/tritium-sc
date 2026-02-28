# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Diagnostic: check framebuffer binding during Three.js custom layer render.

Theory: MapLibre v4 renders to an internal FBO. Three.js renderer.render()
binds FBO 0 (canvas), so Three.js output goes to wrong target and gets
overwritten when MapLibre composites its FBO to the canvas.

Fix: save the current FBO before Three.js renders and re-bind it after
Three.js resets state.

Run: .venv/bin/python3 tests/visual/test_threejs_fbo_fix.py
"""

import time
from pathlib import Path
from playwright.sync_api import sync_playwright

OUTPUT_DIR = Path("tests/.test-results/threejs-fbo-fix")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
BASE_URL = "http://localhost:8000"


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page(viewport={"width": 1920, "height": 1080})

        logs = []
        page.on("console", lambda msg: logs.append(f"[{msg.type}] {msg.text}"))

        print("=" * 60)
        print("THREE.JS FBO DIAGNOSTIC + FIX")
        print("=" * 60)

        print("\n[1/6] Loading Command Center...")
        page.goto(BASE_URL, wait_until="networkidle")
        time.sleep(5)

        page.evaluate("""() => {
            const s = window._mapState || {};
            if (s.map) {
                s.map.setPitch(0);
                s.map.setBearing(0);
                s.map.setZoom(16);
            }
        }""")
        time.sleep(2)

        print("\n[2/6] Checking framebuffer state during render callback...")
        fboCheck = page.evaluate("""() => {
            return new Promise(resolve => {
                const s = window._mapState || {};
                if (!s.threeRenderer) { resolve({error: 'no renderer'}); return; }

                const gl = s.threeRenderer.getContext();

                // Check current FBO binding (outside of render)
                const outsideFbo = gl.getParameter(gl.FRAMEBUFFER_BINDING);

                // Hook into the render loop by using requestAnimationFrame
                // which fires in the same frame as MapLibre's render
                let resolved = false;
                function checkInRaf() {
                    if (resolved) return;
                    const fbo = gl.getParameter(gl.FRAMEBUFFER_BINDING);
                    // This runs outside the custom layer callback, so the FBO
                    // might be default. We need to instrument the actual render.
                    resolve({
                        outsideFbo: outsideFbo ? 'WebGLFramebuffer' : 'null (canvas)',
                        rafFbo: fbo ? 'WebGLFramebuffer' : 'null (canvas)',
                    });
                    resolved = true;
                }
                requestAnimationFrame(checkInRaf);
                setTimeout(() => {
                    if (!resolved) {
                        resolve({error: 'timeout'});
                        resolved = true;
                    }
                }, 2000);
            });
        }""")
        print(f"  FBO state: {fboCheck}")

        print("\n[3/6] Instrumenting the actual render() callback to check FBO...")
        page.evaluate("""() => {
            const s = window._mapState || {};
            window._fboLog = [];

            // Monkey-patch the Three.js renderer's render method
            const origRender = s.threeRenderer.render.bind(s.threeRenderer);
            s.threeRenderer.render = function(scene, camera) {
                const gl = s.threeRenderer.getContext();

                // What FBO is bound BEFORE Three.js render?
                const fboBefore = gl.getParameter(gl.FRAMEBUFFER_BINDING);

                origRender(scene, camera);

                // What FBO is bound AFTER Three.js render?
                const fboAfter = gl.getParameter(gl.FRAMEBUFFER_BINDING);

                if (window._fboLog.length < 5) {
                    window._fboLog.push({
                        before: fboBefore ? 'FBO' : 'canvas',
                        after: fboAfter ? 'FBO' : 'canvas',
                        beforeId: fboBefore ? 'non-null' : 'null',
                        afterId: fboAfter ? 'non-null' : 'null',
                    });
                    console.log('[FBO] Before=' + (fboBefore ? 'FBO' : 'canvas')
                        + ' After=' + (fboAfter ? 'FBO' : 'canvas'));
                }
            };
            console.log('[FBO] Render hook installed');
        }""")
        time.sleep(2)

        fboLog = page.evaluate("() => window._fboLog || []")
        print(f"  FBO transitions during render ({len(fboLog)} frames):")
        for entry in fboLog:
            print(f"    Before render: {entry['before']}, After render: {entry['after']}")

        # THE KEY QUESTION: Is MapLibre binding an FBO before calling render()?
        has_fbo = any(entry['before'] == 'FBO' for entry in fboLog)
        if has_fbo:
            print("\n  >>> MapLibre IS using an internal FBO!")
            print("  >>> Three.js renders to canvas (FBO 0) instead of MapLibre's FBO!")
            print("  >>> This is why Three.js output is invisible!")
        else:
            print("\n  >>> MapLibre is NOT using an FBO (renders to canvas directly)")
            print("  >>> The issue is NOT FBO-related. Need to investigate further.")

        page.screenshot(path=str(OUTPUT_DIR / "00_before_fix.png"))

        print("\n[4/6] Applying FBO fix — save/restore framebuffer around render...")
        page.evaluate("""() => {
            const s = window._mapState || {};

            // Restore original render
            // We need to patch the custom layer's render method, not the Three.js renderer
            // Let's find and replace the custom layer implementation
            const layer = s.map.getLayer('three-overlay');
            if (!layer || !layer.implementation) {
                console.error('[FBO-FIX] Cannot find three-overlay layer');
                return;
            }

            const impl = layer.implementation;
            const origRender = impl.render.bind(impl);

            // Also restore the unpatched Three.js render
            // (our previous monkey-patch captured the original)
            const gl = s.threeRenderer.getContext();

            impl.render = function(glCtx, args) {
                if (!s.threeScene || !s.threeCamera) return;

                // Pre-render: tick effects + animate units
                // (These are called inside the original render, but we
                //  need to replicate the full logic here)

                // Get MapLibre's projection matrix
                const matrixData = (args && args.defaultProjectionData)
                    ? args.defaultProjectionData.mainMatrix
                    : args;

                // Build combined projection: MapLibreVP * refMatrix
                const m = new THREE.Matrix4().fromArray(matrixData);
                m.multiply(s._refMatrix);
                s.threeCamera.projectionMatrix.copy(m);
                s.threeCamera.projectionMatrixInverse.copy(m).invert();

                // CRITICAL FIX: Save MapLibre's current framebuffer
                const mapFbo = glCtx.getParameter(glCtx.FRAMEBUFFER_BINDING);

                s.threeRenderer.resetState();

                // After resetState, Three.js has reset its internal cache.
                // Re-bind MapLibre's FBO so Three.js renders to the correct target.
                if (mapFbo) {
                    glCtx.bindFramebuffer(glCtx.FRAMEBUFFER, mapFbo);
                }

                glCtx.depthMask(true);
                glCtx.clear(glCtx.DEPTH_BUFFER_BIT);

                // Render Three.js scene
                s.threeRenderer.render(s.threeScene, s.threeCamera);

                // Restore MapLibre's FBO (Three.js render() binds FBO 0)
                if (mapFbo) {
                    glCtx.bindFramebuffer(glCtx.FRAMEBUFFER, mapFbo);
                }

                s.map.triggerRepaint();
            };

            console.log('[FBO-FIX] Patched render with FBO save/restore');
        }""")
        time.sleep(1)

        print("\n[5/6] Adding test spheres after fix...")
        page.evaluate("""() => {
            const s = window._mapState || {};
            if (!s.threeRoot) return;

            // Remove any old test objects
            const toRemove = [];
            s.threeRoot.traverse(child => {
                if (child.name && child.name.startsWith('diag-')) toRemove.push(child);
            });
            toRemove.forEach(obj => {
                obj.parent.remove(obj);
                if (obj.geometry) obj.geometry.dispose();
                if (obj.material) obj.material.dispose();
            });

            // Big red sphere at center
            const geo1 = new THREE.SphereGeometry(50, 16, 16);
            const mat1 = new THREE.MeshBasicMaterial({
                color: 0xff0000, side: THREE.DoubleSide,
                depthTest: false, depthWrite: false,
            });
            const m1 = new THREE.Mesh(geo1, mat1);
            m1.position.set(0, 0, 5);
            m1.frustumCulled = false;
            m1.name = 'diag-red';
            s.threeRoot.add(m1);

            // Green sphere 100m east
            const geo2 = new THREE.SphereGeometry(50, 16, 16);
            const mat2 = new THREE.MeshBasicMaterial({
                color: 0x00ff00, side: THREE.DoubleSide,
                depthTest: false, depthWrite: false,
            });
            const m2 = new THREE.Mesh(geo2, mat2);
            m2.position.set(100, 0, 5);
            m2.frustumCulled = false;
            m2.name = 'diag-green';
            s.threeRoot.add(m2);

            // Blue sphere 100m north
            const geo3 = new THREE.SphereGeometry(50, 16, 16);
            const mat3 = new THREE.MeshBasicMaterial({
                color: 0x0000ff, side: THREE.DoubleSide,
                depthTest: false, depthWrite: false,
            });
            const m3 = new THREE.Mesh(geo3, mat3);
            m3.position.set(0, 100, 5);
            m3.frustumCulled = false;
            m3.name = 'diag-blue';
            s.threeRoot.add(m3);

            console.log('[FBO-FIX] Added 3 test spheres');
        }""")
        time.sleep(3)
        page.screenshot(path=str(OUTPUT_DIR / "01_after_fix.png"))

        # Check FBO transitions after fix
        fboLog2 = page.evaluate("""() => {
            window._fboLog = [];
            return new Promise(resolve => {
                setTimeout(() => resolve(window._fboLog), 1000);
            });
        }""")
        print(f"  FBO transitions after fix ({len(fboLog2)} frames):")
        for entry in fboLog2[:3]:
            print(f"    Before: {entry.get('before')}, After: {entry.get('after')}")

        print("\n[6/6] Checking render output...")
        # Read console logs
        for line in logs[-20:]:
            print(f"  {line}")

        with open(OUTPUT_DIR / "console.txt", "w") as f:
            f.write("\n".join(logs))

        print(f"\nScreenshots in: {OUTPUT_DIR}")
        print("Browser open 15s for inspection...")
        time.sleep(15)
        browser.close()


if __name__ == "__main__":
    main()
