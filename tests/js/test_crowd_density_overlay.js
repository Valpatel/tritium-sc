// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
/**
 * TRITIUM-SC Crowd Density Overlay Tests
 *
 * Tests the crowd density heatmap overlay on the Canvas 2D tactical map:
 * 1. _drawCrowdDensity() function exists in map.js
 * 2. It reads from TritiumStore 'game.crowdDensity'
 * 3. Color mapping: sparse=skip, moderate=yellow, dense=orange, critical=red
 * 4. Handles null/missing grid data gracefully
 * 5. Handles empty grid (no cells)
 * 6. HUD pill renders max_density text and critical_count
 * 7. Critical cells use pulsing alpha (Math.sin)
 * 8. Only renders in civil_unrest mode (checks game.modeType)
 * 9. Integration: called from _draw() render loop
 *
 * Run: node tests/js/test_crowd_density_overlay.js
 */

const fs = require('fs');
const vm = require('vm');

// Simple test runner
let passed = 0, failed = 0;
function assert(cond, msg) {
    if (!cond) { console.error('FAIL:', msg); failed++; }
    else { console.log('PASS:', msg); passed++; }
}

// Read source files
const mapSrc = fs.readFileSync(__dirname + '/../../src/frontend/js/command/map.js', 'utf8');
const storeSrc = fs.readFileSync(__dirname + '/../../src/frontend/js/command/store.js', 'utf8');
const eventsSrc = fs.readFileSync(__dirname + '/../../../tritium-lib/web/events.js', 'utf8');

// ============================================================
// 1. _drawCrowdDensity function exists
// ============================================================

console.log('\n--- _drawCrowdDensity function exists ---');

assert(mapSrc.includes('function _drawCrowdDensity'),
    '_drawCrowdDensity function defined in map.js');

// ============================================================
// 2. Reads from TritiumStore
// ============================================================

console.log('\n--- Reads from TritiumStore ---');

{
    const fnIdx = mapSrc.indexOf('function _drawCrowdDensity');
    assert(fnIdx !== -1, '_drawCrowdDensity found in source');
    if (fnIdx !== -1) {
        // Extract ~1500 chars of the function body
        const snippet = mapSrc.substring(fnIdx, fnIdx + 1500);
        assert(snippet.includes("game.crowdDensity") || snippet.includes('crowdDensity'),
            '_drawCrowdDensity reads crowdDensity from store');
    }
}

// ============================================================
// 3. Color mapping: sparse, moderate, dense, critical
// ============================================================

console.log('\n--- Color mapping ---');

{
    const fnIdx = mapSrc.indexOf('function _drawCrowdDensity');
    if (fnIdx !== -1) {
        const snippet = mapSrc.substring(fnIdx, fnIdx + 4000);

        // sparse should be skipped (no draw)
        assert(snippet.includes('sparse'),
            '_drawCrowdDensity handles sparse cells');

        // moderate -> yellow
        assert(snippet.includes('moderate'),
            '_drawCrowdDensity handles moderate cells');

        // dense -> orange
        assert(snippet.includes('dense'),
            '_drawCrowdDensity handles dense cells');

        // critical -> red
        assert(snippet.includes('critical'),
            '_drawCrowdDensity handles critical cells');
    }
}

// ============================================================
// 4. Color values: yellow for moderate, orange for dense, red for critical
// ============================================================

console.log('\n--- Color value verification ---');

{
    const fnIdx = mapSrc.indexOf('function _drawCrowdDensity');
    if (fnIdx !== -1) {
        const snippet = mapSrc.substring(fnIdx, fnIdx + 4000);

        // Yellow/amber for moderate (some form of yellow in rgba)
        const hasYellow = /rgba?\s*\(\s*2[0-5]\d\s*,\s*2[0-5]\d\s*,\s*\d{1,3}/.test(snippet) ||
                          snippet.includes('fcee0a') ||
                          snippet.includes('yellow');
        assert(hasYellow, 'moderate cells use yellow/amber color');

        // Orange for dense
        const hasOrange = /rgba?\s*\(\s*2[0-5]\d\s*,\s*1[0-6]\d\s*,\s*\d{1,2}/.test(snippet) ||
                          snippet.includes('ff8800') || snippet.includes('orange') ||
                          snippet.includes('ff6') || snippet.includes('255, 140') ||
                          snippet.includes('255, 165');
        assert(hasOrange, 'dense cells use orange color');

        // Red for critical
        const hasRed = /rgba?\s*\(\s*2[0-5]\d\s*,\s*[0-5]?\d\s*,\s*[0-5]?\d/.test(snippet) ||
                       snippet.includes('ff2a6d') || snippet.includes('ff0000') ||
                       snippet.includes('255, 0') || snippet.includes('255, 42');
        assert(hasRed, 'critical cells use red color');
    }
}

// ============================================================
// 5. Handles null/missing grid data gracefully
// ============================================================

console.log('\n--- Null/missing data handling ---');

{
    const fnIdx = mapSrc.indexOf('function _drawCrowdDensity');
    if (fnIdx !== -1) {
        const snippet = mapSrc.substring(fnIdx, fnIdx + 500);
        // Should have an early return or guard for missing data
        const hasGuard = snippet.includes('!data') || snippet.includes('!grid') ||
                         snippet.includes('return') || snippet.includes('if (');
        assert(hasGuard, '_drawCrowdDensity has guard clause for missing data');
    }
}

// ============================================================
// 6. HUD pill renders max_density and critical_count
// ============================================================

console.log('\n--- HUD density indicator ---');

{
    // Look for a HUD drawing section related to crowd density
    const hasHudDensity = mapSrc.includes('max_density') || mapSrc.includes('maxDensity') ||
                          mapSrc.includes('CROWD') || mapSrc.includes('DENSITY');
    assert(hasHudDensity, 'map.js includes crowd density HUD text');

    const hasCriticalCount = mapSrc.includes('critical_count') || mapSrc.includes('criticalCount');
    assert(hasCriticalCount, 'map.js references critical_count for HUD display');
}

// ============================================================
// 7. Critical cells use pulsing alpha (Math.sin)
// ============================================================

console.log('\n--- Critical pulsing alpha ---');

{
    const fnIdx = mapSrc.indexOf('function _drawCrowdDensity');
    if (fnIdx !== -1) {
        const snippet = mapSrc.substring(fnIdx, fnIdx + 4000);
        assert(snippet.includes('Math.sin'), '_drawCrowdDensity uses Math.sin for pulse');
        assert(snippet.includes('critical'), '_drawCrowdDensity has critical-specific logic');
    }
}

// ============================================================
// 8. Only renders in civil_unrest mode
// ============================================================

console.log('\n--- Civil unrest mode gate ---');

{
    const fnIdx = mapSrc.indexOf('function _drawCrowdDensity');
    if (fnIdx !== -1) {
        const snippet = mapSrc.substring(fnIdx, fnIdx + 800);
        assert(snippet.includes('civil_unrest'),
            '_drawCrowdDensity checks for civil_unrest mode');
        assert(snippet.includes('game.modeType') || snippet.includes('modeType') || snippet.includes('gameMode'),
            '_drawCrowdDensity reads game mode type from store');
    }
}

// ============================================================
// 9. Called from _draw() render loop
// ============================================================

console.log('\n--- Render loop integration ---');

{
    const drawIdx = mapSrc.indexOf('function _draw()');
    assert(drawIdx !== -1, '_draw() function found');
    if (drawIdx !== -1) {
        // Get the _draw function body (4000 chars covers all layers)
        const snippet = mapSrc.substring(drawIdx, drawIdx + 4000);
        assert(snippet.includes('_drawCrowdDensity'),
            '_draw() calls _drawCrowdDensity');
    }
}

// ============================================================
// 10. Uses worldToScreen for coordinate transforms
// ============================================================

console.log('\n--- Coordinate transform ---');

{
    const fnIdx = mapSrc.indexOf('function _drawCrowdDensity');
    if (fnIdx !== -1) {
        const snippet = mapSrc.substring(fnIdx, fnIdx + 4000);
        assert(snippet.includes('worldToScreen'),
            '_drawCrowdDensity uses worldToScreen for coordinate transform');
    }
}

// ============================================================
// 11. Draws filled rectangles for grid cells
// ============================================================

console.log('\n--- Draws filled rectangles ---');

{
    const fnIdx = mapSrc.indexOf('function _drawCrowdDensity');
    if (fnIdx !== -1) {
        const snippet = mapSrc.substring(fnIdx, fnIdx + 4000);
        assert(snippet.includes('fillRect'),
            '_drawCrowdDensity uses fillRect for grid cells');
    }
}

// ============================================================
// 12. Uses ctx.save/restore pattern
// ============================================================

console.log('\n--- Save/restore pattern ---');

{
    const fnIdx = mapSrc.indexOf('function _drawCrowdDensity');
    if (fnIdx !== -1) {
        const snippet = mapSrc.substring(fnIdx, fnIdx + 4000);
        assert(snippet.includes('ctx.save') || snippet.includes('.save()'),
            '_drawCrowdDensity saves canvas state');
        assert(snippet.includes('ctx.restore') || snippet.includes('.restore()'),
            '_drawCrowdDensity restores canvas state');
    }
}

// ============================================================
// 13. Functional test: color mapping logic via VM
// ============================================================

console.log('\n--- Functional test: color mapping logic ---');

{
    // Extract the color-mapping portion and test it directly
    // Define the CROWD_DENSITY_COLORS constant (expected pattern)
    const colorMatch = mapSrc.match(/CROWD_DENSITY_COLORS\s*=\s*\{[^}]+\}/);
    if (colorMatch) {
        const colorDef = colorMatch[0];
        assert(!colorDef.includes('sparse') ||
               colorDef.match(/sparse.*null|sparse.*undefined/),
            'sparse has no color (skip)');
        assert(colorDef.includes('moderate'), 'CROWD_DENSITY_COLORS has moderate');
        assert(colorDef.includes('dense'), 'CROWD_DENSITY_COLORS has dense');
        assert(colorDef.includes('critical'), 'CROWD_DENSITY_COLORS has critical');
    } else {
        // Try inline color checks instead
        const fnIdx = mapSrc.indexOf('function _drawCrowdDensity');
        if (fnIdx !== -1) {
            const snippet = mapSrc.substring(fnIdx, fnIdx + 4000);
            // Check that sparse is explicitly skipped
            const sparseSkipped = snippet.includes("'sparse'") &&
                (snippet.includes('continue') || snippet.includes('skip') || snippet.includes('!=='));
            assert(sparseSkipped || snippet.includes('sparse'),
                'sparse cells are handled (skipped or with no-op)');
        }
    }
}

// ============================================================
// 14. Functional test: _drawCrowdDensity with mock canvas ctx
// ============================================================

console.log('\n--- Functional test: mock canvas execution ---');

{
    // Set up a minimal sandbox to test _drawCrowdDensity in isolation
    // Strip ES module syntax to make it loadable in Node
    let code = storeSrc
        .replace(/export\s+/g, '')
        .replace(/import\s+.*?from\s+['"][^'"]+['"];?\s*/g, '');

    code += '\n' + eventsSrc
        .replace(/export\s+/g, '')
        .replace(/import\s+.*?from\s+['"][^'"]+['"];?\s*/g, '');

    // Extract just _drawCrowdDensity and its dependencies from map.js
    // We need: worldToScreen, _state, the constants, and _drawCrowdDensity
    // Also grab CROWD_DENSITY_COLORS if it exists
    const mapCodeStripped = mapSrc
        .replace(/export\s+/g, '')
        .replace(/import\s+.*?from\s+['"][^'"]+['"];?\s*/g, '');

    // Extract the _drawCrowdDensity function
    const fnStart = mapCodeStripped.indexOf('function _drawCrowdDensity');
    if (fnStart === -1) {
        assert(false, '_drawCrowdDensity not found for functional test');
    } else {
        let depth = 0, fnEnd = fnStart, foundOpen = false;
        for (let i = fnStart; i < mapCodeStripped.length; i++) {
            if (mapCodeStripped[i] === '{') { depth++; foundOpen = true; }
            if (mapCodeStripped[i] === '}') { depth--; }
            if (foundOpen && depth === 0) { fnEnd = i + 1; break; }
        }
        const fnBody = mapCodeStripped.substring(fnStart, fnEnd);

        // Build a minimal test sandbox
        const mockFillRects = [];
        const mockFillTexts = [];
        let mockFillStyle = '';
        let mockGlobalAlpha = 1;
        let savedCount = 0;
        let restoredCount = 0;

        const mockCtx = {
            get fillStyle() { return mockFillStyle; },
            set fillStyle(v) { mockFillStyle = v; },
            get globalAlpha() { return mockGlobalAlpha; },
            set globalAlpha(v) { mockGlobalAlpha = v; },
            save() { savedCount++; },
            restore() { restoredCount++; },
            fillRect(x, y, w, h) { mockFillRects.push({ x, y, w, h, fill: mockFillStyle, alpha: mockGlobalAlpha }); },
            fillText(text, x, y) { mockFillTexts.push({ text, x, y, fill: mockFillStyle }); },
            font: '',
            textAlign: '',
            textBaseline: '',
            beginPath() {},
            arc() {},
            fill() {},
            stroke() {},
            strokeStyle: '',
            lineWidth: 1,
            measureText(t) { return { width: t.length * 7 }; },
            setLineDash() {},
            closePath() {},
            moveTo() {},
            lineTo() {},
            strokeRect() {},
        };

        // Try to create a runnable context
        try {
            const ctx = vm.createContext({
                Math, console, Array, Object, Number, String, JSON, Map, Set,
                Date: { now: () => 100000 },
                Infinity, undefined, Error,
                performance: { now: () => 100000 },
            });

            // Load the store + events
            vm.runInContext(code, ctx);

            // Set up store data for civil_unrest mode
            vm.runInContext(`
                TritiumStore.set('game.modeType', 'civil_unrest');
                TritiumStore.set('game.crowdDensity', {
                    grid: [
                        ['sparse', 'moderate', 'dense'],
                        ['moderate', 'critical', 'sparse'],
                    ],
                    cell_size: 10.0,
                    bounds: [-50, -30, -20, -10],
                    max_density: 'critical',
                    critical_count: 1,
                });
            `, ctx);

            // Inject worldToScreen and _state needed by _drawCrowdDensity
            vm.runInContext(`
                var _state = {
                    canvas: { width: 1600, height: 900 },
                    dpr: 1,
                    cam: { x: 0, y: 0, zoom: 1.0 },
                    lastFrameTime: 100000,
                };
                function worldToScreen(wx, wy) {
                    var cssW = _state.canvas.width / _state.dpr;
                    var cssH = _state.canvas.height / _state.dpr;
                    var sx = (wx - _state.cam.x) * _state.cam.zoom + cssW / 2;
                    var sy = -(wy - _state.cam.y) * _state.cam.zoom + cssH / 2;
                    return { x: sx, y: sy };
                }
                var FONT_FAMILY = '"JetBrains Mono", monospace';
            `, ctx);

            // Also inject any constants that _drawCrowdDensity might reference
            // Look for CROWD_DENSITY_COLORS constant
            const colorConstMatch = mapCodeStripped.match(/(?:const|var|let)\s+CROWD_DENSITY_COLORS\s*=\s*\{[^}]+\}/);
            if (colorConstMatch) {
                vm.runInContext(colorConstMatch[0] + ';', ctx);
            }

            // Inject _drawCrowdDensity
            vm.runInContext(fnBody, ctx);

            // Make mock ctx available
            ctx._mockCtx = mockCtx;
            ctx._mockFillRects = mockFillRects;
            ctx._mockFillTexts = mockFillTexts;

            // Call _drawCrowdDensity
            vm.runInContext(`
                _drawCrowdDensity(_mockCtx);
            `, ctx);

            // Check that rectangles were drawn (moderate, dense, critical = 4 non-sparse cells)
            assert(mockFillRects.length >= 3,
                'fillRect called for non-sparse cells (got ' + mockFillRects.length + ')');

            // Check that sparse cells were NOT drawn (grid has 2 sparse out of 6 total)
            // 4 non-sparse grid cells + 2 HUD pill rects (background + accent bar) = 6
            assert(mockFillRects.length <= 7,
                'sparse cells not drawn (expected <=7 rects for 4 grid + HUD, got ' + mockFillRects.length + ')');

            // Check that save/restore were called
            assert(savedCount > 0, 'ctx.save() was called');
            assert(restoredCount > 0, 'ctx.restore() was called');

            // Test with null data -- should not throw
            vm.runInContext(`
                TritiumStore.set('game.crowdDensity', null);
            `, ctx);

            const rectsBefore = mockFillRects.length;
            vm.runInContext(`
                _drawCrowdDensity(_mockCtx);
            `, ctx);
            // Should not have drawn additional rects
            assert(mockFillRects.length === rectsBefore || mockFillRects.length <= rectsBefore + 1,
                'null crowdDensity does not draw grid cells');

            // Test with battle mode -- should not render
            vm.runInContext(`
                TritiumStore.set('game.modeType', 'battle');
                TritiumStore.set('game.crowdDensity', {
                    grid: [['critical', 'critical']],
                    cell_size: 10.0,
                    bounds: [0, 0, 20, 10],
                    max_density: 'critical',
                    critical_count: 2,
                });
            `, ctx);

            const rectsBeforeBattle = mockFillRects.length;
            vm.runInContext(`
                _drawCrowdDensity(_mockCtx);
            `, ctx);
            assert(mockFillRects.length === rectsBeforeBattle,
                'battle mode does not render crowd density');

        } catch (e) {
            assert(false, 'Functional test failed with error: ' + e.message);
        }
    }
}

// ============================================================
// 15. HUD pill drawing verification
// ============================================================

console.log('\n--- HUD pill drawing ---');

{
    // Check that there's a HUD section that draws density info
    const fnIdx = mapSrc.indexOf('function _drawCrowdDensity');
    if (fnIdx !== -1) {
        const snippet = mapSrc.substring(fnIdx, fnIdx + 5000);
        const hasHudPill = snippet.includes('fillText') &&
            (snippet.includes('DENSITY') || snippet.includes('CROWD') ||
             snippet.includes('max_density') || snippet.includes('maxDensity'));
        assert(hasHudPill, '_drawCrowdDensity draws HUD pill with density text');
    }
}

// ============================================================
// 16. Grid cell bounds are used for positioning
// ============================================================

console.log('\n--- Grid cell bounds positioning ---');

{
    const fnIdx = mapSrc.indexOf('function _drawCrowdDensity');
    if (fnIdx !== -1) {
        const snippet = mapSrc.substring(fnIdx, fnIdx + 4000);
        assert(snippet.includes('bounds') || snippet.includes('cell_size') || snippet.includes('cellSize'),
            '_drawCrowdDensity uses grid bounds or cell_size for positioning');
    }
}

// ============================================================
// 17. globalAlpha or rgba used for transparency
// ============================================================

console.log('\n--- Transparency handling ---');

{
    const fnIdx = mapSrc.indexOf('function _drawCrowdDensity');
    if (fnIdx !== -1) {
        const snippet = mapSrc.substring(fnIdx, fnIdx + 4000);
        const hasAlpha = snippet.includes('globalAlpha') || snippet.includes('rgba');
        assert(hasAlpha, '_drawCrowdDensity uses transparency (globalAlpha or rgba)');
    }
}

// ============================================================
// 18. Layer ordering: crowd density drawn before targets
// ============================================================

console.log('\n--- Layer ordering ---');

{
    const drawIdx = mapSrc.indexOf('function _draw()');
    if (drawIdx !== -1) {
        const snippet = mapSrc.substring(drawIdx, drawIdx + 4000);
        const crowdIdx = snippet.indexOf('_drawCrowdDensity');
        const targetIdx = snippet.indexOf('_drawTargets');
        if (crowdIdx !== -1 && targetIdx !== -1) {
            assert(crowdIdx < targetIdx,
                '_drawCrowdDensity called before _drawTargets (correct layer order)');
        } else {
            assert(false, 'Both _drawCrowdDensity and _drawTargets should be in _draw()');
        }
    }
}

// ============================================================
// Summary
// ============================================================

console.log('\n' + '='.repeat(50));
console.log(`test_crowd_density_overlay.js: ${passed} passed, ${failed} failed`);
console.log('='.repeat(50));
process.exit(failed > 0 ? 1 : 0);
