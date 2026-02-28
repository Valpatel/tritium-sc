// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
/**
 * TRITIUM-SC -- Mesh Radio Map Layer tests
 * Run: node tests/js/test_mesh_layer.js
 *
 * Tests mesh node drawing, mesh toggle visibility, center-on-node event,
 * protocol-specific icons, and mesh link rendering.
 *
 * TDD — written before implementation.
 */

const fs = require('fs');
const vm = require('vm');

// Simple test runner
let passed = 0, failed = 0;
function assert(cond, msg) {
    if (!cond) { console.error('FAIL:', msg); failed++; }
    else { console.log('PASS:', msg); passed++; }
}
function assertEqual(a, b, msg) {
    assert(a === b, msg + ` (got ${JSON.stringify(a)}, expected ${JSON.stringify(b)})`);
}
function assertClose(a, b, eps, msg) {
    assert(Math.abs(a - b) < (eps || 0.001), msg + ` (got ${a}, expected ${b})`);
}

// ---------------------------------------------------------------------------
// Load mesh-layer.js into a sandboxed context
// ---------------------------------------------------------------------------

const code = fs.readFileSync(__dirname + '/../../frontend/js/command/mesh-layer.js', 'utf8');

// Mock canvas context that records draw calls
function createMockCtx() {
    const calls = [];
    return {
        calls,
        save() { calls.push({ op: 'save' }); },
        restore() { calls.push({ op: 'restore' }); },
        beginPath() { calls.push({ op: 'beginPath' }); },
        arc(x, y, r, a1, a2) { calls.push({ op: 'arc', x, y, r }); },
        fill() { calls.push({ op: 'fill' }); },
        stroke() { calls.push({ op: 'stroke' }); },
        fillText(text, x, y) { calls.push({ op: 'fillText', text, x, y }); },
        moveTo(x, y) { calls.push({ op: 'moveTo', x, y }); },
        lineTo(x, y) { calls.push({ op: 'lineTo', x, y }); },
        setLineDash(d) { calls.push({ op: 'setLineDash', d }); },
        closePath() { calls.push({ op: 'closePath' }); },
        fillStyle: '',
        strokeStyle: '',
        lineWidth: 1,
        globalAlpha: 1,
        font: '',
        textAlign: 'center',
        textBaseline: 'middle',
    };
}

// Provide a module.exports object so CommonJS export path works in sandbox
const fakeModule = { exports: {} };
const ctx = vm.createContext({
    Math, Date, console, Map, Array, Object, Number, Infinity, Boolean, JSON,
    parseInt, parseFloat, isNaN, isFinite, undefined,
    module: fakeModule,
});
vm.runInContext(code, ctx);

const {
    MESH_PROTOCOL_ICONS,
    MESH_NODE_COLOR,
    MESH_LINK_COLOR,
    MESH_LINK_RANGE,
    meshDrawNodes,
    meshGetIconForProtocol,
    meshShouldDrawLink,
    meshState,
} = fakeModule.exports;

// ============================================================
// Constants validation
// ============================================================

console.log('\n--- Constants ---');

(function testProtocolIcons() {
    assertEqual(MESH_PROTOCOL_ICONS.meshtastic, 'M', 'Meshtastic icon is M');
    assertEqual(MESH_PROTOCOL_ICONS.meshcore, 'C', 'MeshCore icon is C');
    assertEqual(MESH_PROTOCOL_ICONS.web, 'W', 'Web icon is W');
})();

(function testMeshNodeColor() {
    assert(typeof MESH_NODE_COLOR === 'string', 'MESH_NODE_COLOR is a string');
    assert(MESH_NODE_COLOR.length > 0, 'MESH_NODE_COLOR is non-empty');
})();

(function testMeshLinkColor() {
    assert(typeof MESH_LINK_COLOR === 'string', 'MESH_LINK_COLOR is a string');
})();

(function testMeshLinkRange() {
    assert(typeof MESH_LINK_RANGE === 'number', 'MESH_LINK_RANGE is a number');
    assert(MESH_LINK_RANGE > 0, 'MESH_LINK_RANGE is positive');
})();

// ============================================================
// Protocol icon resolution
// ============================================================

console.log('\n--- Protocol Icons ---');

(function testGetIconMeshtastic() {
    assertEqual(meshGetIconForProtocol('meshtastic'), 'M', 'meshtastic -> M');
})();

(function testGetIconMeshcore() {
    assertEqual(meshGetIconForProtocol('meshcore'), 'C', 'meshcore -> C');
})();

(function testGetIconWeb() {
    assertEqual(meshGetIconForProtocol('web'), 'W', 'web -> W');
})();

(function testGetIconUnknown() {
    const icon = meshGetIconForProtocol('unknown_protocol');
    assert(typeof icon === 'string' && icon.length > 0, 'Unknown protocol returns fallback icon');
})();

// ============================================================
// Mesh link distance check
// ============================================================

console.log('\n--- Link Distance ---');

(function testLinkWithinRange() {
    const a = { x: 0, y: 0 };
    const b = { x: 10, y: 0 };
    assert(meshShouldDrawLink(a, b, 100), 'Nearby nodes should draw link');
})();

(function testLinkOutOfRange() {
    const a = { x: 0, y: 0 };
    const b = { x: 10000, y: 10000 };
    assert(!meshShouldDrawLink(a, b, 100), 'Distant nodes should not draw link');
})();

(function testLinkExactRange() {
    const a = { x: 0, y: 0 };
    const b = { x: 100, y: 0 };
    assert(meshShouldDrawLink(a, b, 100), 'Nodes at exact range should draw link');
})();

// ============================================================
// Draw function
// ============================================================

console.log('\n--- Draw Function ---');

(function testMeshDrawNodesExists() {
    assertEqual(typeof meshDrawNodes, 'function', 'meshDrawNodes is a function');
})();

(function testMeshLayerDrawsNodes() {
    const mockCtx = createMockCtx();
    const worldToScreen = (wx, wy) => ({ x: wx * 10, y: wy * 10 });

    const meshTargets = [
        { target_id: 'mesh_001', x: 5, y: 10, asset_type: 'mesh_radio',
          metadata: { mesh_protocol: 'meshtastic' } },
        { target_id: 'meshcore_002', x: 15, y: 20, asset_type: 'mesh_radio',
          metadata: { mesh_protocol: 'meshcore' } },
    ];

    meshDrawNodes(mockCtx, worldToScreen, meshTargets, true);

    // Should have drawn something (save/restore + fill operations)
    const fillTexts = mockCtx.calls.filter(c => c.op === 'fillText');
    assert(fillTexts.length >= 2, 'Should draw at least 2 text labels (one per node)');

    // Check that the protocol icons were used
    const icons = fillTexts.map(c => c.text);
    assert(icons.includes('M'), 'Should draw M for meshtastic node');
    assert(icons.includes('C'), 'Should draw C for meshcore node');
})();

(function testMeshToggleHidesLayer() {
    const mockCtx = createMockCtx();
    const worldToScreen = (wx, wy) => ({ x: wx * 10, y: wy * 10 });

    const meshTargets = [
        { target_id: 'mesh_001', x: 5, y: 10, asset_type: 'mesh_radio',
          metadata: { mesh_protocol: 'meshtastic' } },
    ];

    // Draw with visible=false — should produce no draw calls
    meshDrawNodes(mockCtx, worldToScreen, meshTargets, false);

    const fillTexts = mockCtx.calls.filter(c => c.op === 'fillText');
    assertEqual(fillTexts.length, 0, 'No text drawn when mesh layer is hidden');
})();

(function testMeshDrawEmpty() {
    const mockCtx = createMockCtx();
    const worldToScreen = (wx, wy) => ({ x: wx * 10, y: wy * 10 });

    // Draw with no targets — should not crash
    meshDrawNodes(mockCtx, worldToScreen, [], true);
    assert(true, 'Drawing with empty target list does not crash');
})();

// ============================================================
// Mesh state
// ============================================================

console.log('\n--- Mesh State ---');

(function testMeshStateExists() {
    assert(meshState !== undefined, 'meshState exists');
    assertEqual(typeof meshState.visible, 'boolean', 'meshState.visible is boolean');
})();

(function testMeshStateDefaultVisible() {
    assertEqual(meshState.visible, true, 'Mesh layer visible by default');
})();

// ============================================================
// Summary
// ============================================================

console.log(`\n=== MESH LAYER: ${passed} passed, ${failed} failed ===`);
process.exit(failed > 0 ? 1 : 0);
