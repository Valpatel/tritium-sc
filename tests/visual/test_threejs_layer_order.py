# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Diagnostic: check layer ordering and test persistent raw GL drawing.

Key tests:
1. What layers exist and in what order? Is something rendering ON TOP of three-overlay?
2. Draw raw GL EVERY frame to see if it's visible (persistent, not one-shot)
3. Move three-overlay to the very top of the layer stack

Run: .venv/bin/python3 tests/visual/test_threejs_layer_order.py
"""

import time
from pathlib import Path
from playwright.sync_api import sync_playwright

OUTPUT_DIR = Path("tests/.test-results/threejs-layer-order")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
BASE_URL = "http://localhost:8000"


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page(viewport={"width": 1920, "height": 1080})

        logs = []
        page.on("console", lambda msg: logs.append(f"[{msg.type}] {msg.text}"))

        print("=" * 60)
        print("THREE.JS LAYER ORDER + PERSISTENT RAW GL TEST")
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

        print("\n[2/6] Listing all MapLibre layers in render order...")
        layers = page.evaluate("""() => {
            const s = window._mapState || {};
            if (!s.map) return [];
            const style = s.map.getStyle();
            return style.layers.map(l => ({
                id: l.id,
                type: l.type,
                source: l.source || '',
            }));
        }""")
        threeIdx = -1
        for i, layer in enumerate(layers):
            marker = ""
            if layer['id'] == 'three-overlay':
                marker = " <<< THREE.JS CUSTOM LAYER"
                threeIdx = i
            elif threeIdx >= 0 and i > threeIdx:
                marker = " <<< RENDERS AFTER THREE.JS!"
            print(f"  [{i:2d}] {layer['type']:15s} {layer['id']}{marker}")

        if threeIdx >= 0 and threeIdx < len(layers) - 1:
            after_count = len(layers) - threeIdx - 1
            print(f"\n  WARNING: {after_count} layers render AFTER three-overlay!")
            print(f"  These layers may cover/occlude Three.js output!")

        page.screenshot(path=str(OUTPUT_DIR / "00_current.png"))

        print("\n[3/6] Moving three-overlay to the VERY TOP of layer stack...")
        page.evaluate("""() => {
            const s = window._mapState || {};
            if (!s.map) return;
            try {
                s.map.moveLayer('three-overlay');
                console.log('[LAYER] Moved three-overlay to top');
            } catch(e) {
                console.error('[LAYER] Failed to move: ' + e.message);
            }
        }""")
        time.sleep(2)

        # Re-check layer order
        layers2 = page.evaluate("""() => {
            const s = window._mapState || {};
            const style = s.map.getStyle();
            return style.layers.map(l => l.id);
        }""")
        threeIdx2 = layers2.index('three-overlay') if 'three-overlay' in layers2 else -1
        print(f"  three-overlay is now at index {threeIdx2} of {len(layers2)} (was {threeIdx})")
        if threeIdx2 == len(layers2) - 1:
            print(f"  SUCCESS: three-overlay is now the LAST layer (renders on top)")

        # Add test spheres
        page.evaluate("""() => {
            const s = window._mapState || {};
            if (!s.threeRoot) return;

            // Clear existing diag objects
            const toRemove = [];
            s.threeRoot.traverse(child => {
                if (child.name && child.name.startsWith('diag-')) toRemove.push(child);
            });
            toRemove.forEach(obj => {
                obj.parent.remove(obj);
                if (obj.geometry) obj.geometry.dispose();
                if (obj.material) obj.material.dispose();
            });

            // Add bright red sphere at center
            const geo = new THREE.SphereGeometry(50, 16, 16);
            const mat = new THREE.MeshBasicMaterial({
                color: 0xff0000, side: THREE.DoubleSide,
                depthTest: false, depthWrite: false,
            });
            const mesh = new THREE.Mesh(geo, mat);
            mesh.position.set(0, 0, 5);
            mesh.frustumCulled = false;
            mesh.name = 'diag-red';
            s.threeRoot.add(mesh);
            console.log('[LAYER] Added test sphere');
        }""")
        time.sleep(2)
        page.screenshot(path=str(OUTPUT_DIR / "01_top_layer.png"))

        print("\n[4/6] Testing persistent raw GL rectangle (draws every frame)...")
        page.evaluate("""() => {
            const s = window._mapState || {};
            const gl = s.threeRenderer.getContext();

            // Create a persistent shader program
            const vsrc = `
                attribute vec2 a_pos;
                void main() {
                    gl_Position = vec4(a_pos, 0.0, 1.0);
                }
            `;
            const fsrc = `
                precision mediump float;
                void main() {
                    gl_FragColor = vec4(1.0, 0.0, 0.0, 0.8);
                }
            `;

            function compileShader(type, src) {
                const shader = gl.createShader(type);
                gl.shaderSource(shader, src);
                gl.compileShader(shader);
                return shader;
            }

            const vs = compileShader(gl.VERTEX_SHADER, vsrc);
            const fs = compileShader(gl.FRAGMENT_SHADER, fsrc);
            const prog = gl.createProgram();
            gl.attachShader(prog, vs);
            gl.attachShader(prog, fs);
            gl.linkProgram(prog);

            const vertices = new Float32Array([
                -0.3, -0.3,
                 0.3, -0.3,
                -0.3,  0.3,
                 0.3,  0.3,
            ]);
            const buf = gl.createBuffer();
            gl.bindBuffer(gl.ARRAY_BUFFER, buf);
            gl.bufferData(gl.ARRAY_BUFFER, vertices, gl.STATIC_DRAW);

            const aPos = gl.getAttribLocation(prog, 'a_pos');

            // Store for use in render loop
            window._rawGl = { prog, buf, aPos };
            console.log('[RAW-GL] Persistent program created');

            // Patch the render to draw raw GL EVERY frame AFTER Three.js
            const layer = s.map.getLayer('three-overlay');
            const impl = layer.implementation;
            const origRender = impl.render;

            impl.render = function(glCtx, args) {
                // Original Three.js render
                origRender.call(impl, glCtx, args);

                // Then draw raw GL rectangle on top
                const raw = window._rawGl;
                if (!raw) return;

                // Save Three.js state
                s.threeRenderer.resetState();

                glCtx.useProgram(raw.prog);
                glCtx.bindBuffer(glCtx.ARRAY_BUFFER, raw.buf);
                glCtx.enableVertexAttribArray(raw.aPos);
                glCtx.vertexAttribPointer(raw.aPos, 2, glCtx.FLOAT, false, 0, 0);

                glCtx.disable(glCtx.DEPTH_TEST);
                glCtx.disable(glCtx.STENCIL_TEST);
                glCtx.disable(glCtx.SCISSOR_TEST);
                glCtx.disable(glCtx.BLEND);
                glCtx.disable(glCtx.CULL_FACE);
                glCtx.colorMask(true, true, true, true);

                glCtx.drawArrays(glCtx.TRIANGLE_STRIP, 0, 4);

                // Reset for MapLibre
                s.threeRenderer.resetState();
            };
            console.log('[RAW-GL] Persistent draw hook installed');
        }""")
        time.sleep(3)
        page.screenshot(path=str(OUTPUT_DIR / "02_raw_gl_persistent.png"))

        print("\n[5/6] Checking if raw GL rectangle is visible...")
        # The raw GL rectangle should cover ~30% of the screen center with red

        print("\n[6/6] Final: readback pixel at screen center...")
        pixels = page.evaluate("""() => {
            return new Promise(resolve => {
                requestAnimationFrame(() => {
                    const s = window._mapState || {};
                    const gl = s.threeRenderer.getContext();
                    const cx = Math.floor(gl.drawingBufferWidth / 2);
                    const cy = Math.floor(gl.drawingBufferHeight / 2);
                    const px = new Uint8Array(4);
                    gl.readPixels(cx, cy, 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, px);
                    resolve({
                        center: {r: px[0], g: px[1], b: px[2], a: px[3]},
                        isRed: px[0] > 200 && px[1] < 50 && px[2] < 50,
                    });
                });
            });
        }""")
        print(f"  Center pixel: {pixels}")

        with open(OUTPUT_DIR / "console.txt", "w") as f:
            f.write("\n".join(logs))

        # Print recent logs
        for line in logs[-15:]:
            print(f"  {line}")

        print(f"\nScreenshots in: {OUTPUT_DIR}")
        print("Browser open 15s for inspection...")
        time.sleep(15)
        browser.close()


if __name__ == "__main__":
    main()
