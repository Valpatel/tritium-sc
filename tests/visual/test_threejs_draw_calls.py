# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Diagnostic: count Three.js draw calls and check shader compilation.

We know raw WebGL works inside the custom layer. The question is:
does Three.js r128's render() actually issue any GL draw calls?

Run: .venv/bin/python3 tests/visual/test_threejs_draw_calls.py
"""

import time
from pathlib import Path
from playwright.sync_api import sync_playwright

OUTPUT_DIR = Path("tests/.test-results/threejs-draw-calls")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
BASE_URL = "http://localhost:8000"


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page(viewport={"width": 1920, "height": 1080})

        logs = []
        page.on("console", lambda msg: logs.append(f"[{msg.type}] {msg.text}"))

        print("=" * 60)
        print("THREE.JS DRAW CALL DIAGNOSTIC")
        print("=" * 60)

        print("\n[1/5] Loading Command Center...")
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

        print("\n[2/5] Adding a test sphere and counting draw calls...")
        result = page.evaluate("""() => {
            return new Promise(resolve => {
                const s = window._mapState || {};
                if (!s.threeRenderer || !s.threeScene || !s.threeCamera || !s.threeRoot) {
                    resolve({error: 'Three.js not initialized'});
                    return;
                }

                // Add a test sphere
                const geo = new THREE.SphereGeometry(50, 16, 16);
                const mat = new THREE.MeshBasicMaterial({
                    color: 0xff0000, side: THREE.DoubleSide,
                    depthTest: false, depthWrite: false,
                });
                const mesh = new THREE.Mesh(geo, mat);
                mesh.position.set(0, 0, 5);
                mesh.frustumCulled = false;
                mesh.name = 'diag-sphere';
                s.threeRoot.add(mesh);

                const gl = s.threeRenderer.getContext();

                // Wrap GL draw functions to count calls
                let drawArraysCalls = 0;
                let drawElementsCalls = 0;
                let drawArraysInstancedCalls = 0;
                let drawElementsInstancedCalls = 0;
                let glErrors = [];

                const origDrawArrays = gl.drawArrays.bind(gl);
                const origDrawElements = gl.drawElements.bind(gl);
                const origDrawArraysInstanced = gl.drawArraysInstanced ? gl.drawArraysInstanced.bind(gl) : null;
                const origDrawElementsInstanced = gl.drawElementsInstanced ? gl.drawElementsInstanced.bind(gl) : null;

                gl.drawArrays = function(mode, first, count) {
                    drawArraysCalls++;
                    return origDrawArrays(mode, first, count);
                };
                gl.drawElements = function(mode, count, type, offset) {
                    drawElementsCalls++;
                    return origDrawElements(mode, count, type, offset);
                };
                if (origDrawArraysInstanced) {
                    gl.drawArraysInstanced = function(...args) {
                        drawArraysInstancedCalls++;
                        return origDrawArraysInstanced(...args);
                    };
                }
                if (origDrawElementsInstanced) {
                    gl.drawElementsInstanced = function(...args) {
                        drawElementsInstancedCalls++;
                        return origDrawElementsInstanced(...args);
                    };
                }

                // Also intercept program use and shader compilation
                let programUses = 0;
                const origUseProgram = gl.useProgram.bind(gl);
                gl.useProgram = function(prog) {
                    programUses++;
                    return origUseProgram(prog);
                };

                // Patch render callback
                const layer = s.map.getLayer('three-overlay');
                const impl = layer.implementation;
                const origRender = impl.render;

                let done = false;
                impl.render = function(glCtx, args) {
                    if (done) {
                        origRender.call(impl, glCtx, args);
                        return;
                    }
                    done = true;

                    // Reset counters
                    drawArraysCalls = 0;
                    drawElementsCalls = 0;
                    drawArraysInstancedCalls = 0;
                    drawElementsInstancedCalls = 0;
                    programUses = 0;

                    // Run original render (includes Three.js render)
                    origRender.call(impl, glCtx, args);

                    // Check for GL errors after render
                    let err = glCtx.getError();
                    while (err !== 0) {
                        glErrors.push(err);
                        err = glCtx.getError();
                    }

                    // Also check the render info from Three.js
                    const info = s.threeRenderer.info;

                    // Restore original GL functions
                    glCtx.drawArrays = origDrawArrays;
                    glCtx.drawElements = origDrawElements;
                    if (origDrawArraysInstanced) glCtx.drawArraysInstanced = origDrawArraysInstanced;
                    if (origDrawElementsInstanced) glCtx.drawElementsInstanced = origDrawElementsInstanced;
                    glCtx.useProgram = origUseProgram;

                    resolve({
                        drawArraysCalls,
                        drawElementsCalls,
                        drawArraysInstancedCalls,
                        drawElementsInstancedCalls,
                        totalDrawCalls: drawArraysCalls + drawElementsCalls + drawArraysInstancedCalls + drawElementsInstancedCalls,
                        programUses,
                        glErrors,
                        rendererInfo: info ? {
                            programs: info.programs ? info.programs.length : -1,
                            geometries: info.memory ? info.memory.geometries : -1,
                            textures: info.memory ? info.memory.textures : -1,
                            calls: info.render ? info.render.calls : -1,
                            triangles: info.render ? info.render.triangles : -1,
                            points: info.render ? info.render.points : -1,
                            lines: info.render ? info.render.lines : -1,
                        } : null,
                        sceneChildren: s.threeScene.children.length,
                        rootChildren: s.threeRoot.children.length,
                    });
                };

                setTimeout(() => {
                    if (!done) resolve({error: 'timeout'});
                }, 3000);
            });
        }""")

        print(f"  Result:")
        for k, v in result.items():
            flag = ""
            if k == 'totalDrawCalls' and v == 0:
                flag = " <<< ZERO DRAW CALLS! THREE.JS ISN'T DRAWING!"
            elif k == 'totalDrawCalls' and v > 0:
                flag = " <<< THREE.JS IS DRAWING!"
            elif k == 'glErrors' and v:
                flag = " <<< GL ERRORS!"
            print(f"    {k}: {v}{flag}")

        print("\n[3/5] Checking Three.js render.info after manual render call...")
        manualInfo = page.evaluate("""() => {
            const s = window._mapState || {};
            if (!s.threeRenderer || !s.threeScene || !s.threeCamera) return {error: 'missing'};

            // Reset info counters
            s.threeRenderer.info.reset();

            // Manually trigger a render
            s.threeRenderer.resetState();
            const gl = s.threeRenderer.getContext();
            gl.depthMask(true);
            gl.clear(gl.DEPTH_BUFFER_BIT);
            s.threeRenderer.render(s.threeScene, s.threeCamera);

            return {
                calls: s.threeRenderer.info.render.calls,
                triangles: s.threeRenderer.info.render.triangles,
                points: s.threeRenderer.info.render.points,
                lines: s.threeRenderer.info.render.lines,
                programs: s.threeRenderer.info.programs.length,
                geometries: s.threeRenderer.info.memory.geometries,
                textures: s.threeRenderer.info.memory.textures,
            };
        }""")
        print(f"  Manual render info: {manualInfo}")

        if manualInfo.get('calls', 0) > 0:
            print(f"\n  Three.js IS issuing draw calls ({manualInfo['calls']} calls, {manualInfo['triangles']} triangles)!")
            print("  But the output is not visible. This suggests a GL state issue.")
        else:
            print(f"\n  Three.js is NOT issuing draw calls!")
            print("  This could mean frustum culling, empty scene, or material issues.")

        print("\n[4/5] Checking if frustum culling is the issue...")
        frustumTest = page.evaluate("""() => {
            const s = window._mapState || {};
            if (!s.threeRoot) return {error: 'no root'};

            // Check all mesh objects for frustumCulled
            let total = 0;
            let culled = 0;
            let unculled = 0;
            let visible = 0;
            let invisible = 0;
            let hasGeo = 0;
            let hasMat = 0;

            s.threeRoot.traverse(child => {
                if (child.isMesh) {
                    total++;
                    if (child.frustumCulled) culled++;
                    else unculled++;
                    if (child.visible) visible++;
                    else invisible++;
                    if (child.geometry) hasGeo++;
                    if (child.material) hasMat++;
                }
            });

            // Also check the scene
            let sceneMeshes = 0;
            s.threeScene.traverse(child => {
                if (child.isMesh) sceneMeshes++;
            });

            return {
                rootMeshes: total,
                frustumCulled: culled,
                notCulled: unculled,
                visible: visible,
                invisible: invisible,
                hasGeometry: hasGeo,
                hasMaterial: hasMat,
                totalSceneMeshes: sceneMeshes,
            };
        }""")
        print(f"  Frustum check: {frustumTest}")

        print("\n[5/5] Testing THREE.js render with frustum culling completely disabled...")
        noFrustumTest = page.evaluate("""() => {
            const s = window._mapState || {};

            // Force disable frustum culling on EVERYTHING
            s.threeScene.traverse(child => {
                child.frustumCulled = false;
            });

            // Reset info and render
            s.threeRenderer.info.reset();
            s.threeRenderer.resetState();
            const gl = s.threeRenderer.getContext();
            gl.depthMask(true);
            gl.clear(gl.DEPTH_BUFFER_BIT);
            s.threeRenderer.render(s.threeScene, s.threeCamera);

            return {
                calls: s.threeRenderer.info.render.calls,
                triangles: s.threeRenderer.info.render.triangles,
            };
        }""")
        print(f"  After disabling ALL frustum culling: {noFrustumTest}")

        time.sleep(1)
        page.screenshot(path=str(OUTPUT_DIR / "01_result.png"))

        with open(OUTPUT_DIR / "console.txt", "w") as f:
            f.write("\n".join(logs))

        # Print error logs
        errors = [l for l in logs if 'error' in l.lower() or 'warn' in l.lower()]
        if errors:
            print(f"\n  Errors/warnings: {len(errors)}")
            for e in errors[:10]:
                print(f"    {e}")

        print(f"\nScreenshots in: {OUTPUT_DIR}")
        print("Browser open 15s for inspection...")
        time.sleep(15)
        browser.close()


if __name__ == "__main__":
    main()
