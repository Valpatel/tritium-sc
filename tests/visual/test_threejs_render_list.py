# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Diagnostic: check Three.js render list, exceptions, and render target.

Three.js r128 issues zero draw calls despite 880 visible meshes.
Check: render lists, exceptions, render targets, camera layers.

Run: .venv/bin/python3 tests/visual/test_threejs_render_list.py
"""

import time
from pathlib import Path
from playwright.sync_api import sync_playwright

OUTPUT_DIR = Path("tests/.test-results/threejs-render-list")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
BASE_URL = "http://localhost:8000"


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page(viewport={"width": 1920, "height": 1080})

        logs = []
        page.on("console", lambda msg: logs.append(f"[{msg.type}] {msg.text}"))

        print("=" * 60)
        print("THREE.JS RENDER LIST + EXCEPTION DIAGNOSTIC")
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

        print("\n[2/6] Checking camera, scene, and layers...")
        check1 = page.evaluate("""() => {
            const s = window._mapState || {};
            const cam = s.threeCamera;
            const scene = s.threeScene;
            const root = s.threeRoot;

            // Check camera
            const camInfo = {
                type: cam.constructor.name,
                isCamera: cam.isCamera,
                isPerspective: cam.isPerspectiveCamera || false,
                isOrthographic: cam.isOrthographicCamera || false,
                layersMask: cam.layers.mask,
                visible: cam.visible,
                matrixWorld: cam.matrixWorld.elements.slice(0, 4).map(v => v.toFixed(4)),
                projMatrix00: cam.projectionMatrix.elements[0].toExponential(3),
            };

            // Check scene
            const sceneInfo = {
                visible: scene.visible,
                layersMask: scene.layers.mask,
                childCount: scene.children.length,
                autoUpdate: scene.autoUpdate,
            };

            // Check root
            const rootInfo = {
                visible: root.visible,
                layersMask: root.layers.mask,
                childCount: root.children.length,
            };

            // Sample a mesh
            let sampleMesh = null;
            root.traverse(child => {
                if (!sampleMesh && child.isMesh) {
                    sampleMesh = {
                        name: child.name,
                        type: child.constructor.name,
                        isMesh: child.isMesh,
                        visible: child.visible,
                        frustumCulled: child.frustumCulled,
                        layersMask: child.layers.mask,
                        hasGeometry: !!child.geometry,
                        hasAttributes: child.geometry ? !!child.geometry.attributes.position : false,
                        vertexCount: child.geometry && child.geometry.attributes.position
                            ? child.geometry.attributes.position.count : 0,
                        hasMaterial: !!child.material,
                        materialType: child.material ? child.material.constructor.name : 'none',
                        materialVisible: child.material ? child.material.visible : null,
                        renderOrder: child.renderOrder,
                    };
                }
            });

            return {camera: camInfo, scene: sceneInfo, root: rootInfo, sampleMesh};
        }""")

        print("  Camera:")
        for k, v in check1.get('camera', {}).items():
            print(f"    {k}: {v}")
        print("  Scene:")
        for k, v in check1.get('scene', {}).items():
            print(f"    {k}: {v}")
        print("  Root:")
        for k, v in check1.get('root', {}).items():
            print(f"    {k}: {v}")
        print("  Sample mesh:")
        for k, v in check1.get('sampleMesh', {}).items():
            print(f"    {k}: {v}")

        print("\n[3/6] Testing render() with exception catching...")
        renderTest = page.evaluate("""() => {
            const s = window._mapState || {};
            let exception = null;
            let renderTarget = null;

            try {
                // Check render target before
                renderTarget = s.threeRenderer.getRenderTarget();

                // Try rendering
                s.threeRenderer.info.reset();
                s.threeRenderer.resetState();

                const gl = s.threeRenderer.getContext();
                gl.depthMask(true);
                gl.clear(gl.DEPTH_BUFFER_BIT);

                s.threeRenderer.render(s.threeScene, s.threeCamera);

            } catch(e) {
                exception = {
                    message: e.message,
                    stack: e.stack ? e.stack.substring(0, 500) : null,
                };
            }

            return {
                exception,
                renderTarget: renderTarget ? 'non-null' : 'null (screen)',
                calls: s.threeRenderer.info.render.calls,
                programs: s.threeRenderer.info.programs.length,
            };
        }""")
        print(f"  Exception: {renderTest.get('exception')}")
        print(f"  Render target: {renderTest.get('renderTarget')}")
        print(f"  Draw calls: {renderTest.get('calls')}")
        print(f"  Programs: {renderTest.get('programs')}")

        print("\n[4/6] Manually building and rendering a simple mesh (bypass scene)...")
        manualTest = page.evaluate("""() => {
            const s = window._mapState || {};
            const renderer = s.threeRenderer;
            const camera = s.threeCamera;
            const gl = renderer.getContext();

            // Create a minimal scene with just one mesh
            const testScene = new THREE.Scene();
            const testGeo = new THREE.BoxGeometry(100, 100, 100);
            const testMat = new THREE.MeshBasicMaterial({color: 0xff0000});
            const testMesh = new THREE.Mesh(testGeo, testMat);
            testMesh.frustumCulled = false;
            testScene.add(testMesh);
            testScene.updateMatrixWorld(true);

            // Reset and render
            renderer.info.reset();
            renderer.resetState();
            gl.depthMask(true);
            gl.clear(gl.DEPTH_BUFFER_BIT);

            let exception = null;
            try {
                renderer.render(testScene, camera);
            } catch(e) {
                exception = e.message;
            }

            const result = {
                calls: renderer.info.render.calls,
                triangles: renderer.info.render.triangles,
                programs: renderer.info.programs.length,
                exception,
            };

            // Clean up
            testGeo.dispose();
            testMat.dispose();

            return result;
        }""")
        print(f"  Minimal scene render: {manualTest}")

        if manualTest.get('calls', 0) == 0:
            print("\n  Even a minimal scene produces zero draw calls!")
            print("  The Three.js renderer itself is broken.")

        print("\n[5/6] Checking if it's a WebGL2 vs WebGL1 issue...")
        glVersion = page.evaluate("""() => {
            const s = window._mapState || {};
            const gl = s.threeRenderer.getContext();
            return {
                version: gl.getParameter(gl.VERSION),
                shadingLanguageVersion: gl.getParameter(gl.SHADING_LANGUAGE_VERSION),
                isWebGL2: gl instanceof WebGL2RenderingContext,
                rendererCapabilities: {
                    isWebGL2: s.threeRenderer.capabilities.isWebGL2,
                    maxTextures: s.threeRenderer.capabilities.maxTextures,
                    maxVertexUniforms: s.threeRenderer.capabilities.maxVertexUniforms,
                    precision: s.threeRenderer.capabilities.precision,
                },
            };
        }""")
        print(f"  GL version: {glVersion.get('version')}")
        print(f"  GLSL version: {glVersion.get('shadingLanguageVersion')}")
        print(f"  Is WebGL2: {glVersion.get('isWebGL2')}")
        print(f"  Three.js capabilities: {glVersion.get('rendererCapabilities')}")

        print("\n[6/6] Testing with a fresh renderer on the SAME canvas...")
        freshTest = page.evaluate("""() => {
            const s = window._mapState || {};
            const canvas = s.map.getCanvas();
            const gl = canvas.getContext('webgl2');

            if (!gl) return {error: 'could not get webgl2 context'};

            // Try creating a brand new Three.js renderer
            let freshRenderer;
            try {
                freshRenderer = new THREE.WebGLRenderer({
                    canvas: canvas,
                    context: gl,
                    antialias: true,
                });
                freshRenderer.autoClear = false;
            } catch(e) {
                return {error: 'renderer creation failed: ' + e.message};
            }

            // Create a simple scene
            const scene = new THREE.Scene();
            const cam = new THREE.Camera();
            cam.projectionMatrix.copy(s.threeCamera.projectionMatrix);

            const geo = new THREE.BoxGeometry(100, 100, 100);
            const mat = new THREE.MeshBasicMaterial({color: 0x00ff00});
            const mesh = new THREE.Mesh(geo, mat);
            mesh.frustumCulled = false;
            scene.add(mesh);

            // Render
            freshRenderer.info.reset();
            freshRenderer.resetState();
            gl.depthMask(true);
            gl.clear(gl.DEPTH_BUFFER_BIT);

            let exception = null;
            try {
                freshRenderer.render(scene, cam);
            } catch(e) {
                exception = e.message;
            }

            const result = {
                calls: freshRenderer.info.render.calls,
                triangles: freshRenderer.info.render.triangles,
                programs: freshRenderer.info.programs.length,
                geometries: freshRenderer.info.memory.geometries,
                exception,
            };

            geo.dispose();
            mat.dispose();
            freshRenderer.dispose();

            return result;
        }""")
        print(f"  Fresh renderer: {freshTest}")

        with open(OUTPUT_DIR / "console.txt", "w") as f:
            f.write("\n".join(logs))

        # Check for errors
        errors = [l for l in logs if l.startswith('[error]')]
        warnings = [l for l in logs if l.startswith('[warning]')]
        if errors:
            print(f"\n  Console errors ({len(errors)}):")
            for e in errors[:10]:
                print(f"    {e}")
        if warnings:
            print(f"\n  Console warnings ({len(warnings)}):")
            for w in warnings[:5]:
                print(f"    {w}")

        print(f"\nScreenshots in: {OUTPUT_DIR}")
        print("Browser open 10s for inspection...")
        time.sleep(10)
        browser.close()


if __name__ == "__main__":
    main()
