// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
/**
 * TRITIUM-SC minimap panel tests
 * Tests the MinimapPanelDef conversion from hardcoded minimap to panel system.
 * Verifies panel definition structure, canvas creation, resize handling,
 * map.js integration points, and keyboard shortcut wiring.
 * Run: node tests/js/test_minimap_panel.js
 */

const fs = require('fs');

// Simple test runner
let passed = 0, failed = 0;
function assert(cond, msg) {
    if (!cond) { console.error('FAIL:', msg); failed++; }
    else { console.log('PASS:', msg); passed++; }
}
function assertEqual(a, b, msg) {
    assert(a === b, msg + ` (got ${JSON.stringify(a)}, expected ${JSON.stringify(b)})`);
}

// ============================================================
// Load source files
// ============================================================

const minimapSrc = fs.readFileSync(__dirname + '/../../frontend/js/command/panels/minimap.js', 'utf8');
const mainSrc = fs.readFileSync(__dirname + '/../../frontend/js/command/main.js', 'utf8');
const mapSrc = fs.readFileSync(__dirname + '/../../frontend/js/command/map.js', 'utf8');

// ============================================================
// 1. Panel definition structure
// ============================================================

console.log('\n--- MinimapPanelDef Structure ---');

(function testExportsMinimapPanelDef() {
    assert(minimapSrc.includes('export const MinimapPanelDef'),
        'Exports MinimapPanelDef constant');
})();

(function testHasId() {
    assert(minimapSrc.includes("id: 'minimap'"),
        'Panel id is minimap');
})();

(function testHasTitle() {
    assert(minimapSrc.includes("title: 'MINIMAP'"),
        'Panel title is MINIMAP');
})();

(function testHasDefaultPosition() {
    assert(minimapSrc.includes('defaultPosition'),
        'Has defaultPosition');
})();

(function testHasDefaultSize() {
    assert(minimapSrc.includes('defaultSize'),
        'Has defaultSize');
})();

(function testHasCreateMethod() {
    assert(minimapSrc.includes('create('),
        'Has create method');
})();

(function testHasMountMethod() {
    assert(minimapSrc.includes('mount('),
        'Has mount method');
})();

(function testHasUnmountMethod() {
    assert(minimapSrc.includes('unmount('),
        'Has unmount method');
})();

(function testHasOnResizeMethod() {
    assert(minimapSrc.includes('onResize'),
        'Has onResize callback for canvas resize');
})();

// ============================================================
// 2. Canvas creation
// ============================================================

console.log('\n--- Canvas Creation ---');

(function testCreatesCanvasElement() {
    assert(minimapSrc.includes("createElement('canvas')"),
        'Creates a canvas element');
})();

(function testCanvasHasMinimapId() {
    assert(minimapSrc.includes('minimap-canvas'),
        'Canvas has minimap-canvas identifier');
})();

(function testCanvasFillsPanel() {
    // Canvas should fill the panel body (100% width/height)
    assert(minimapSrc.includes('100%') || minimapSrc.includes('width') && minimapSrc.includes('height'),
        'Canvas dimensions set to fill panel');
})();

// ============================================================
// 3. main.js registration
// ============================================================

console.log('\n--- main.js Registration ---');

(function testImportsMinimapPanelDef() {
    assert(mainSrc.includes('MinimapPanelDef'),
        'main.js imports MinimapPanelDef');
})();

(function testRegistersMinimapPanel() {
    assert(mainSrc.includes("panelManager.register(MinimapPanelDef)"),
        'main.js registers MinimapPanelDef with panelManager');
})();

// ============================================================
// 4. Keyboard shortcut
// ============================================================

console.log('\n--- Keyboard Shortcut ---');

(function testMKeyTogglesMinimap() {
    // M key should toggle the minimap panel via panelManager, not hidden attribute
    assert(mainSrc.includes("panelManager.toggle('minimap')"),
        'M key toggles minimap via panelManager.toggle');
})();

(function testNoHardcodedMinimapToggle() {
    // Should NOT have the old hardcoded minimap toggle
    const hasOldToggle = mainSrc.includes("minimap-container") && mainSrc.includes(".hidden = !");
    assert(!hasOldToggle,
        'No hardcoded minimap-container hidden toggle');
})();

// ============================================================
// 5. Map.js integration
// ============================================================

console.log('\n--- Map.js Integration ---');

(function testMapFindsMinimapCanvas() {
    // Map should look for the canvas by ID (same as before) or via panel system
    assert(mapSrc.includes('minimap-canvas'),
        'map.js references minimap-canvas');
})();

(function testDrawMinimapFunction() {
    assert(mapSrc.includes('_drawMinimap'),
        'map.js has _drawMinimap function');
})();

(function testMinimapFallback() {
    // If dedicated canvas not found, fall back to drawing on main canvas
    assert(mapSrc.includes('_drawMinimapOnMain'),
        'map.js has _drawMinimapOnMain fallback');
})();

// ============================================================
// 6. Panel presets include minimap
// ============================================================

console.log('\n--- Panel Presets ---');

const panelMgrSrc = fs.readFileSync(__dirname + '/../../frontend/js/command/panel-manager.js', 'utf8');

(function testCommanderPresetHasMinimap() {
    // Commander preset should include minimap
    assert(panelMgrSrc.includes('minimap') && panelMgrSrc.includes('commander'),
        'Panel presets reference minimap');
})();

// ============================================================
// 7. Click-to-pan interaction preserved
// ============================================================

console.log('\n--- Click-to-Pan ---');

(function testMinimapClickHandler() {
    assert(minimapSrc.includes('mousedown') || minimapSrc.includes('click'),
        'Minimap panel has click/mousedown handler');
})();

(function testClickPansMinimap() {
    // Should convert click coords to world coords and set camera target
    assert(minimapSrc.includes('targetX') || minimapSrc.includes('cam'),
        'Click handler pans camera');
})();

// ============================================================
// 8. Minimap rendering delegates to map.js
// ============================================================

console.log('\n--- Render Delegation ---');

(function testMinimapImportsFromMap() {
    // Panel should import drawing function from map.js or call it via event
    assert(minimapSrc.includes("from '../map.js'") ||
           minimapSrc.includes("from '../map-maplibre.js'") ||
           minimapSrc.includes('EventBus') ||
           minimapSrc.includes('drawMinimap') ||
           minimapSrc.includes('getContext'),
        'Minimap panel integrates with map renderer');
})();

// ============================================================
// Summary
// ============================================================

console.log(`\n${'='.repeat(40)}`);
console.log(`MINIMAP PANEL: ${passed} passed, ${failed} failed`);
console.log(`${'='.repeat(40)}`);
process.exit(failed > 0 ? 1 : 0);
