// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
/**
 * facade-shader.js — Procedural building window grid shader
 *
 * Custom THREE.ShaderMaterial that renders a grid of lit windows
 * on building walls. Cheaper than individual PlaneGeometry meshes.
 * Uses step/fract UV math to create window rectangles with
 * position-seeded random lighting and night-time emissive glow.
 */

const _vertexShader = `
    varying vec2 vUv;
    varying vec3 vWorldPosition;

    void main() {
        vUv = uv;
        vec4 worldPos = modelMatrix * vec4(position, 1.0);
        vWorldPosition = worldPos.xyz;
        gl_Position = projectionMatrix * viewMatrix * worldPos;
    }
`;

const _fragmentShader = `
    uniform float buildingHeight;
    uniform float wallWidth;
    uniform float floorHeight;
    uniform float windowWidth;
    uniform float windowHeight;
    uniform float windowSpacing;
    uniform float emissiveIntensity;
    uniform float time;

    varying vec2 vUv;
    varying vec3 vWorldPosition;

    // Simple hash for pseudo-random per-window lighting
    float hash(vec2 p) {
        return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453123);
    }

    void main() {
        // Map UVs to world-scale coordinates
        float worldU = vUv.x * wallWidth;
        float worldV = vUv.y * buildingHeight;

        // Grid cell for this fragment
        float cellX = windowSpacing;
        float cellY = floorHeight;

        // Position within the current cell
        float localX = mod(worldU, cellX);
        float localY = mod(worldV, cellY);

        // Center the window in each cell
        float marginX = (cellX - windowWidth) * 0.5;
        float marginY = (cellY - windowHeight) * 0.5;

        // Is this fragment inside a window?
        float inWindowX = step(marginX, localX) * step(localX, marginX + windowWidth);
        float inWindowY = step(marginY, localY) * step(localY, marginY + windowHeight);
        float inWindow = inWindowX * inWindowY;

        // Skip ground floor (below first floorHeight)
        float aboveGround = step(floorHeight * 0.5, worldV);
        inWindow *= aboveGround;

        // Per-window random: is this window lit?
        float cellIdX = floor(worldU / cellX);
        float cellIdY = floor(worldV / cellY);
        float rnd = hash(vec2(cellIdX, cellIdY) + floor(vWorldPosition.xz * 0.1));

        // ~60% of windows lit, with slow temporal flicker
        float flicker = sin(time * 0.3 + rnd * 6.28) * 0.05;
        float lit = step(0.4, rnd + flicker);

        // Window color: warm yellow-orange with slight per-window variation
        vec3 warmColor = vec3(1.0, 0.85, 0.4);
        vec3 coolColor = vec3(0.6, 0.8, 1.0);
        vec3 windowColor = mix(warmColor, coolColor, step(0.85, rnd));

        // Wall base color (dark, near-black)
        vec3 wallColor = vec3(0.05, 0.05, 0.08);

        // Combine: window glow on top of wall
        float windowBrightness = inWindow * lit * mix(0.3, 1.0, emissiveIntensity);
        vec3 color = mix(wallColor, windowColor, windowBrightness);

        // Overall alpha: wall is semi-transparent, windows are opaque when lit
        float alpha = mix(0.75, 0.95, windowBrightness);

        gl_FragColor = vec4(color, alpha);
    }
`;

/**
 * Create a facade shader material for building walls.
 *
 * @param {Object} options
 * @param {number} [options.buildingHeight=10] - Total building height in meters
 * @param {number} [options.wallWidth=20] - Wall width in meters
 * @param {number} [options.floorHeight=3.0] - Floor-to-floor height
 * @param {number} [options.windowWidth=1.0] - Window width in meters
 * @param {number} [options.windowHeight=1.2] - Window height in meters
 * @param {number} [options.windowSpacing=3.0] - Horizontal spacing between window centers
 * @param {number} [options.emissiveIntensity=0.0] - Emissive glow (0.0 = day, 1.0 = night)
 * @param {number} [options.time=0] - Animation time for flicker
 * @returns {THREE.ShaderMaterial}
 */
export function createFacadeShaderMaterial(options = {}) {
    return new THREE.ShaderMaterial({
        uniforms: {
            buildingHeight: { value: options.buildingHeight ?? 10 },
            wallWidth: { value: options.wallWidth ?? 20 },
            floorHeight: { value: options.floorHeight ?? 3.0 },
            windowWidth: { value: options.windowWidth ?? 1.0 },
            windowHeight: { value: options.windowHeight ?? 1.2 },
            windowSpacing: { value: options.windowSpacing ?? 3.0 },
            emissiveIntensity: { value: options.emissiveIntensity ?? 0.0 },
            time: { value: options.time ?? 0 },
        },
        vertexShader: _vertexShader,
        fragmentShader: _fragmentShader,
        transparent: true,
        side: THREE.DoubleSide,
        depthWrite: false,
    });
}
