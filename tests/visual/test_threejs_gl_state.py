# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Diagnostic: dump all WebGL state during custom layer render.

Check every GL flag that could hide Three.js output:
color mask, blend, depth, stencil, scissor, viewport, etc.

Also try raw WebGL drawing (no Three.js) to isolate the issue.

Run: .venv/bin/python3 tests/visual/test_threejs_gl_state.py
"""

import time
from pathlib import Path
from playwright.sync_api import sync_playwright

OUTPUT_DIR = Path("tests/.test-results/threejs-gl-state")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
BASE_URL = "http://localhost:8000"


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page(viewport={"width": 1920, "height": 1080})

        logs = []
        page.on("console", lambda msg: logs.append(f"[{msg.type}] {msg.text}"))

        print("=" * 60)
        print("WEBGL STATE DIAGNOSTIC")
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

        print("\n[2/5] Capturing GL state inside custom layer render callback...")
        glState = page.evaluate("""() => {
            return new Promise(resolve => {
                const s = window._mapState || {};
                if (!s.threeRenderer) { resolve({error: 'no renderer'}); return; }

                const gl = s.threeRenderer.getContext();
                const layer = s.map.getLayer('three-overlay');
                if (!layer || !layer.implementation) {
                    resolve({error: 'no layer'});
                    return;
                }

                const impl = layer.implementation;
                const origRender = impl.render;

                let captured = false;
                impl.render = function(glCtx, args) {
                    // Call original first to set up the normal state
                    origRender.call(impl, glCtx, args);

                    if (!captured) {
                        captured = true;

                        // Dump ALL relevant GL state
                        const state = {
                            // Color
                            colorMask: Array.from(glCtx.getParameter(glCtx.COLOR_WRITEMASK)),
                            clearColor: Array.from(glCtx.getParameter(glCtx.COLOR_CLEAR_VALUE)),

                            // Blend
                            blendEnabled: glCtx.isEnabled(glCtx.BLEND),
                            blendSrcRGB: glCtx.getParameter(glCtx.BLEND_SRC_RGB),
                            blendDstRGB: glCtx.getParameter(glCtx.BLEND_DST_RGB),
                            blendSrcAlpha: glCtx.getParameter(glCtx.BLEND_SRC_ALPHA),
                            blendDstAlpha: glCtx.getParameter(glCtx.BLEND_DST_ALPHA),
                            blendEqRGB: glCtx.getParameter(glCtx.BLEND_EQUATION_RGB),
                            blendEqAlpha: glCtx.getParameter(glCtx.BLEND_EQUATION_ALPHA),

                            // Depth
                            depthTest: glCtx.isEnabled(glCtx.DEPTH_TEST),
                            depthFunc: glCtx.getParameter(glCtx.DEPTH_FUNC),
                            depthMask: glCtx.getParameter(glCtx.DEPTH_WRITEMASK),
                            depthRange: Array.from(glCtx.getParameter(glCtx.DEPTH_RANGE)),
                            depthClear: glCtx.getParameter(glCtx.DEPTH_CLEAR_VALUE),

                            // Stencil
                            stencilTest: glCtx.isEnabled(glCtx.STENCIL_TEST),
                            stencilFunc: glCtx.getParameter(glCtx.STENCIL_FUNC),
                            stencilRef: glCtx.getParameter(glCtx.STENCIL_REF),
                            stencilMask: glCtx.getParameter(glCtx.STENCIL_VALUE_MASK),
                            stencilWriteMask: glCtx.getParameter(glCtx.STENCIL_WRITEMASK),

                            // Scissor
                            scissorTest: glCtx.isEnabled(glCtx.SCISSOR_TEST),
                            scissorBox: Array.from(glCtx.getParameter(glCtx.SCISSOR_BOX)),

                            // Viewport
                            viewport: Array.from(glCtx.getParameter(glCtx.VIEWPORT)),

                            // Framebuffer
                            fbo: glCtx.getParameter(glCtx.FRAMEBUFFER_BINDING) ? 'FBO' : 'canvas',

                            // Cull
                            cullFace: glCtx.isEnabled(glCtx.CULL_FACE),
                            cullMode: glCtx.getParameter(glCtx.CULL_FACE_MODE),
                            frontFace: glCtx.getParameter(glCtx.FRONT_FACE),

                            // Program
                            currentProgram: glCtx.getParameter(glCtx.CURRENT_PROGRAM) ? 'active' : 'none',

                            // Canvas
                            canvasWidth: glCtx.canvas.width,
                            canvasHeight: glCtx.canvas.height,
                            drawingBufferWidth: glCtx.drawingBufferWidth,
                            drawingBufferHeight: glCtx.drawingBufferHeight,
                        };

                        resolve(state);
                    }
                };

                // Fallback timeout
                setTimeout(() => {
                    if (!captured) resolve({error: 'timeout - render not called'});
                }, 3000);
            });
        }""")

        print("  GL State AFTER Three.js render:")
        for k, v in glState.items():
            flag = ""
            # Flag suspicious values
            if k == 'colorMask' and not all(v):
                flag = " <<< COLOR WRITES DISABLED!"
            if k == 'stencilTest' and v:
                flag = " <<< STENCIL TEST ENABLED!"
            if k == 'scissorTest' and v:
                flag = " <<< SCISSOR TEST ENABLED!"
            if k == 'depthTest' and v:
                flag = " (expected after render)"
            if k == 'blendEnabled' and v:
                flag = " (blending active)"
            print(f"    {k}: {v}{flag}")

        print("\n[3/5] Trying raw WebGL draw inside custom layer render...")
        rawGlResult = page.evaluate("""() => {
            return new Promise(resolve => {
                const s = window._mapState || {};
                const gl = s.threeRenderer.getContext();
                const layer = s.map.getLayer('three-overlay');
                const impl = layer.implementation;
                const origRender = impl.render;

                let done = false;
                impl.render = function(glCtx, args) {
                    // Call original first
                    origRender.call(impl, glCtx, args);

                    if (done) return;
                    done = true;

                    // Now try raw WebGL: draw a red rectangle covering 25% of screen
                    try {
                        // Create shader program
                        const vsrc = `
                            attribute vec2 a_pos;
                            void main() {
                                gl_Position = vec4(a_pos, 0.0, 1.0);
                            }
                        `;
                        const fsrc = `
                            precision mediump float;
                            void main() {
                                gl_FragColor = vec4(1.0, 0.0, 0.0, 1.0);
                            }
                        `;

                        function compileShader(type, src) {
                            const shader = glCtx.createShader(type);
                            glCtx.shaderSource(shader, src);
                            glCtx.compileShader(shader);
                            if (!glCtx.getShaderParameter(shader, glCtx.COMPILE_STATUS)) {
                                return {error: glCtx.getShaderInfoLog(shader)};
                            }
                            return shader;
                        }

                        const vs = compileShader(glCtx.VERTEX_SHADER, vsrc);
                        const fs = compileShader(glCtx.FRAGMENT_SHADER, fsrc);
                        if (vs.error || fs.error) {
                            resolve({error: 'shader compile', vs: vs.error, fs: fs.error});
                            return;
                        }

                        const prog = glCtx.createProgram();
                        glCtx.attachShader(prog, vs);
                        glCtx.attachShader(prog, fs);
                        glCtx.linkProgram(prog);
                        if (!glCtx.getProgramParameter(prog, glCtx.LINK_STATUS)) {
                            resolve({error: 'link', msg: glCtx.getProgramInfoLog(prog)});
                            return;
                        }

                        // Set up vertex buffer - a quad in NDC covering center of screen
                        const vertices = new Float32Array([
                            -0.5, -0.5,
                             0.5, -0.5,
                            -0.5,  0.5,
                             0.5,  0.5,
                        ]);
                        const buf = glCtx.createBuffer();
                        glCtx.bindBuffer(glCtx.ARRAY_BUFFER, buf);
                        glCtx.bufferData(glCtx.ARRAY_BUFFER, vertices, glCtx.STATIC_DRAW);

                        const aPos = glCtx.getAttribLocation(prog, 'a_pos');
                        glCtx.enableVertexAttribArray(aPos);
                        glCtx.vertexAttribPointer(aPos, 2, glCtx.FLOAT, false, 0, 0);

                        // Set GL state for drawing
                        glCtx.useProgram(prog);
                        glCtx.disable(glCtx.DEPTH_TEST);
                        glCtx.disable(glCtx.STENCIL_TEST);
                        glCtx.disable(glCtx.SCISSOR_TEST);
                        glCtx.disable(glCtx.BLEND);
                        glCtx.colorMask(true, true, true, true);
                        glCtx.depthMask(false);

                        // Draw
                        glCtx.drawArrays(glCtx.TRIANGLE_STRIP, 0, 4);

                        // Check GL error
                        const err = glCtx.getError();

                        // Clean up
                        glCtx.deleteProgram(prog);
                        glCtx.deleteShader(vs);
                        glCtx.deleteShader(fs);
                        glCtx.deleteBuffer(buf);

                        // Reset state for MapLibre
                        s.threeRenderer.resetState();

                        resolve({
                            success: true,
                            glError: err,
                            glErrorName: err === 0 ? 'NO_ERROR' : 'ERROR_' + err,
                        });

                    } catch(e) {
                        resolve({error: 'exception', message: e.message});
                    }
                };

                setTimeout(() => { if (!done) resolve({error: 'timeout'}); }, 3000);
            });
        }""")
        print(f"  Raw WebGL result: {rawGlResult}")
        time.sleep(1)
        page.screenshot(path=str(OUTPUT_DIR / "01_raw_webgl.png"))

        print("\n[4/5] Testing with pre-render GL state capture (before Three.js)...")
        preRenderState = page.evaluate("""() => {
            return new Promise(resolve => {
                const s = window._mapState || {};
                const gl = s.threeRenderer.getContext();
                const layer = s.map.getLayer('three-overlay');
                const impl = layer.implementation;
                const origRender = impl.render;

                let done = false;
                impl.render = function(glCtx, args) {
                    if (!done) {
                        done = true;
                        // Capture state BEFORE Three.js renders
                        const beforeState = {
                            colorMask: Array.from(glCtx.getParameter(glCtx.COLOR_WRITEMASK)),
                            depthTest: glCtx.isEnabled(glCtx.DEPTH_TEST),
                            stencilTest: glCtx.isEnabled(glCtx.STENCIL_TEST),
                            scissorTest: glCtx.isEnabled(glCtx.SCISSOR_TEST),
                            blendEnabled: glCtx.isEnabled(glCtx.BLEND),
                            viewport: Array.from(glCtx.getParameter(glCtx.VIEWPORT)),
                            fbo: glCtx.getParameter(glCtx.FRAMEBUFFER_BINDING) ? 'FBO' : 'canvas',
                        };

                        // Let Three.js render
                        origRender.call(impl, glCtx, args);

                        // Capture state AFTER
                        const afterState = {
                            colorMask: Array.from(glCtx.getParameter(glCtx.COLOR_WRITEMASK)),
                            depthTest: glCtx.isEnabled(glCtx.DEPTH_TEST),
                            stencilTest: glCtx.isEnabled(glCtx.STENCIL_TEST),
                            scissorTest: glCtx.isEnabled(glCtx.SCISSOR_TEST),
                            blendEnabled: glCtx.isEnabled(glCtx.BLEND),
                            viewport: Array.from(glCtx.getParameter(glCtx.VIEWPORT)),
                            fbo: glCtx.getParameter(glCtx.FRAMEBUFFER_BINDING) ? 'FBO' : 'canvas',
                        };

                        resolve({before: beforeState, after: afterState});
                    } else {
                        origRender.call(impl, glCtx, args);
                    }
                };

                setTimeout(() => { if (!done) resolve({error: 'timeout'}); }, 3000);
            });
        }""")
        print("  BEFORE Three.js render:")
        if preRenderState.get('before'):
            for k, v in preRenderState['before'].items():
                print(f"    {k}: {v}")
        print("  AFTER Three.js render:")
        if preRenderState.get('after'):
            for k, v in preRenderState['after'].items():
                print(f"    {k}: {v}")

        print("\n[5/5] Checking Three.js version...")
        version = page.evaluate("() => typeof THREE !== 'undefined' ? THREE.REVISION : 'unknown'")
        print(f"  Three.js revision: {version}")

        # Save console logs
        with open(OUTPUT_DIR / "console.txt", "w") as f:
            f.write("\n".join(logs))

        print(f"\nScreenshots in: {OUTPUT_DIR}")
        print("Browser open 15s for inspection...")
        time.sleep(15)
        browser.close()


if __name__ == "__main__":
    main()
