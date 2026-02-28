// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
/**
 * Unit tests for label-collision.js — bitmap occupancy label placement.
 *
 * Tests the internal helper functions (_markRect, _testRect, _priorityOf,
 * _candidates) and the main resolveLabels() export.
 */

const vm = require('vm');
const fs = require('fs');
const path = require('path');

let passed = 0;
let failed = 0;
function assert(cond, msg) {
    if (cond) { passed++; process.stdout.write(`PASS: ${msg}\n`); }
    else { failed++; process.stderr.write(`FAIL: ${msg}\n`); }
}

// --------------------------------------------------------------------------
// Read source and extract internal functions
// --------------------------------------------------------------------------

const srcPath = path.join(__dirname, '../../frontend/js/command/label-collision.js');
const src = fs.readFileSync(srcPath, 'utf8');

// Convert ES module to CommonJS for vm execution
const cjsSrc = src
    .replace(/^export\s+function\s+/gm, 'function ')
    .replace(/^export\s+/gm, '')
    + '\nvar _exports = { resolveLabels, _markRect, _testRect, _priorityOf, _candidates, PRIORITY, BMP_SCALE, BODY_RADIUS };';

// Create sandbox with minimal DOM stubs
const sandbox = {
    document: {
        createElement: (tag) => {
            if (tag === 'canvas') {
                return {
                    width: 0, height: 0,
                    getContext: () => ({
                        font: '',
                        measureText: (text) => ({ width: text.length * 7 }),
                    }),
                };
            }
            return {};
        },
    },
    Math, Uint8Array, console,
    _exports: null,
};

const ctx = vm.createContext(sandbox);
vm.runInContext(cjsSrc, ctx);
const { resolveLabels, _markRect, _testRect, _priorityOf, _candidates, PRIORITY, BMP_SCALE, BODY_RADIUS } = sandbox._exports;


// --------------------------------------------------------------------------
// Constants
// --------------------------------------------------------------------------

console.log('\n--- Constants ---');
assert(BMP_SCALE === 0.25, 'BMP_SCALE is 0.25');
assert(BODY_RADIUS === 2, 'BODY_RADIUS is 2');
assert(PRIORITY.selected === 0, 'Selected has highest priority (0)');
assert(PRIORITY.hostile === 1, 'Hostile priority is 1');
assert(PRIORITY.friendly === 2, 'Friendly priority is 2');
assert(PRIORITY.neutral === 3, 'Neutral priority is 3');
assert(PRIORITY.dead === 4, 'Dead has lowest priority (4)');


// --------------------------------------------------------------------------
// _markRect
// --------------------------------------------------------------------------

console.log('\n--- _markRect ---');

(function() {
    const bw = 10, bh = 10;
    const bitmap = new Uint8Array(bw * bh);
    _markRect(bitmap, bw, bh, 2, 3, 4, 2);
    // Should mark cells (2,3)-(5,4) inclusive
    assert(bitmap[3 * bw + 2] === 1, 'markRect sets cell (2,3)');
    assert(bitmap[3 * bw + 5] === 1, 'markRect sets cell (5,3)');
    assert(bitmap[4 * bw + 2] === 1, 'markRect sets cell (2,4)');
    assert(bitmap[4 * bw + 5] === 1, 'markRect sets cell (5,4)');
    assert(bitmap[5 * bw + 2] === 0, 'markRect stops at row 5');
    assert(bitmap[3 * bw + 6] === 0, 'markRect stops at col 6');
})();

(function() {
    const bw = 5, bh = 5;
    const bitmap = new Uint8Array(bw * bh);
    _markRect(bitmap, bw, bh, -2, -2, 5, 5);
    // Should clamp to (0,0)-(2,2)
    assert(bitmap[0] === 1, 'markRect clamps negative coords: (0,0)');
    assert(bitmap[2 * bw + 2] === 1, 'markRect clamps: (2,2)');
    assert(bitmap[3 * bw + 0] === 0, 'markRect clamps: (0,3) not set');
})();

(function() {
    const bw = 3, bh = 3;
    const bitmap = new Uint8Array(bw * bh);
    _markRect(bitmap, bw, bh, 1, 1, 100, 100);
    // Should clamp to bitmap bounds
    assert(bitmap[1 * bw + 1] === 1, 'markRect clamps oversized: (1,1)');
    assert(bitmap[2 * bw + 2] === 1, 'markRect clamps oversized: (2,2)');
})();

(function() {
    const bw = 5, bh = 5;
    const bitmap = new Uint8Array(bw * bh);
    _markRect(bitmap, bw, bh, 10, 10, 5, 5);
    // Entirely out of bounds — nothing should be marked
    const sum = bitmap.reduce((a, b) => a + b, 0);
    assert(sum === 0, 'markRect out of bounds marks nothing');
})();


// --------------------------------------------------------------------------
// _testRect
// --------------------------------------------------------------------------

console.log('\n--- _testRect ---');

(function() {
    const bw = 10, bh = 10;
    const bitmap = new Uint8Array(bw * bh);
    assert(_testRect(bitmap, bw, bh, 0, 0, 5, 5) === false, 'testRect empty bitmap returns false');
    _markRect(bitmap, bw, bh, 3, 3, 2, 2);
    assert(_testRect(bitmap, bw, bh, 3, 3, 2, 2) === true, 'testRect overlapping marked area returns true');
    assert(_testRect(bitmap, bw, bh, 0, 0, 3, 3) === false, 'testRect non-overlapping returns false');
    assert(_testRect(bitmap, bw, bh, 2, 2, 3, 3) === true, 'testRect partial overlap returns true');
})();

(function() {
    const bw = 5, bh = 5;
    const bitmap = new Uint8Array(bw * bh);
    bitmap[2 * bw + 2] = 1;  // Single occupied cell at (2,2)
    assert(_testRect(bitmap, bw, bh, 2, 2, 1, 1) === true, 'testRect single cell collision');
    assert(_testRect(bitmap, bw, bh, 0, 0, 1, 1) === false, 'testRect no collision with single cell');
})();


// --------------------------------------------------------------------------
// _priorityOf
// --------------------------------------------------------------------------

console.log('\n--- _priorityOf ---');

(function() {
    assert(_priorityOf({ id: 'u1', alliance: 'hostile' }, null) === PRIORITY.hostile,
        'hostile gets hostile priority');
    assert(_priorityOf({ id: 'u1', alliance: 'friendly' }, null) === PRIORITY.friendly,
        'friendly gets friendly priority');
    assert(_priorityOf({ id: 'u1', alliance: 'neutral' }, null) === PRIORITY.neutral,
        'neutral gets neutral priority');
    assert(_priorityOf({ id: 'u1', alliance: 'civilian' }, null) === PRIORITY.neutral,
        'unknown alliance defaults to neutral');
    assert(_priorityOf({ id: 'u1', alliance: 'friendly', status: 'dead' }, null) === PRIORITY.dead,
        'dead friendly gets dead priority');
    assert(_priorityOf({ id: 'u1', alliance: 'hostile', status: 'neutralized' }, null) === PRIORITY.dead,
        'neutralized hostile gets dead priority');
    assert(_priorityOf({ id: 'sel1', alliance: 'friendly' }, 'sel1') === PRIORITY.selected,
        'selected unit gets selected priority');
    assert(_priorityOf({ id: 'u1', alliance: 'hostile' }, 'sel1') === PRIORITY.hostile,
        'non-selected hostile keeps hostile priority');
})();

(function() {
    // Edge cases
    assert(_priorityOf({ id: 'u1' }, null) === PRIORITY.neutral,
        'missing alliance defaults to neutral');
    assert(_priorityOf({ id: 'u1', alliance: '', status: '' }, null) === PRIORITY.neutral,
        'empty strings default to neutral');
    assert(_priorityOf({ id: 'u1', alliance: 'HOSTILE' }, null) === PRIORITY.hostile,
        'uppercase alliance normalized');
    assert(_priorityOf({ id: 'u1', alliance: 'Friendly' }, null) === PRIORITY.friendly,
        'mixed case alliance normalized');
})();


// --------------------------------------------------------------------------
// _candidates
// --------------------------------------------------------------------------

console.log('\n--- _candidates ---');

(function() {
    const tw = 60, th = 20;
    const cands = _candidates(tw, th);
    assert(cands.length === 8, 'candidates returns 8 positions');

    // Position 0 (preferred): below center
    assert(cands[0][0] === -(tw / 2), 'candidate 0 x is -halfW');
    assert(cands[0][1] > 0, 'candidate 0 y is positive (below)');

    // Position 1: above
    assert(cands[1][1] < 0, 'candidate 1 y is negative (above)');

    // Position 2: right
    assert(cands[2][0] > 0, 'candidate 2 x is positive (right)');

    // Position 3: left
    assert(cands[3][0] < 0, 'candidate 3 x is negative (left)');

    // All candidates should be distinct
    const strs = cands.map(c => `${c[0]},${c[1]}`);
    const unique = new Set(strs);
    assert(unique.size === 8, 'all 8 candidates are unique positions');
})();

(function() {
    // Different sizes should produce different offsets
    const small = _candidates(30, 10);
    const large = _candidates(120, 30);
    assert(small[0][0] !== large[0][0], 'different widths give different x offsets');
})();


// --------------------------------------------------------------------------
// resolveLabels
// --------------------------------------------------------------------------

console.log('\n--- resolveLabels ---');

const worldToScreen = (wx, wy) => ({ x: wx, y: wy });

(function() {
    const result = resolveLabels([], 800, 600, 1, null, worldToScreen);
    assert(Array.isArray(result), 'returns array for empty input');
    assert(result.length === 0, 'empty entries returns empty results');
})();

(function() {
    const result = resolveLabels(null, 800, 600, 1, null, worldToScreen);
    assert(Array.isArray(result), 'returns array for null input');
    assert(result.length === 0, 'null entries returns empty results');
})();

(function() {
    const entries = [{ id: 'u1', text: 'Rover', worldX: 400, worldY: 300, alliance: 'friendly' }];
    const results = resolveLabels(entries, 800, 600, 1, null, worldToScreen);
    assert(results.length === 1, 'single entry returns 1 result');
    assert(results[0].id === 'u1', 'result has correct id');
    assert(results[0].text === 'Rover', 'result has correct text');
    assert(typeof results[0].labelX === 'number', 'result has numeric labelX');
    assert(typeof results[0].labelY === 'number', 'result has numeric labelY');
    assert(results[0].anchorX === 400, 'anchorX matches worldX');
    assert(results[0].anchorY === 300, 'anchorY matches worldY');
    assert(results[0].bgWidth > 0, 'bgWidth is positive');
    assert(results[0].bgHeight > 0, 'bgHeight is positive');
    assert(results[0].alliance === 'friendly', 'alliance preserved');
})();

(function() {
    const entries = [
        { id: 'u1', text: 'Rover', worldX: 400, worldY: 300, alliance: 'friendly' },
        { id: 'u2', text: 'Drone', worldX: 400, worldY: 300, alliance: 'friendly' },
    ];
    const results = resolveLabels(entries, 800, 600, 1, null, worldToScreen);
    assert(results.length === 2, 'overlapping entries both placed');
    // At least one should be displaced
    const anyDisplaced = results.some(r => r.displaced);
    assert(anyDisplaced, 'overlapping labels cause displacement');
})();

(function() {
    // Selected unit should be placed first (priority 0)
    const entries = [
        { id: 'u1', text: 'Hostile', worldX: 400, worldY: 300, alliance: 'hostile' },
        { id: 'u2', text: 'Selected', worldX: 400, worldY: 300, alliance: 'friendly' },
    ];
    const results = resolveLabels(entries, 800, 600, 1, 'u2', worldToScreen);
    assert(results.length === 2, 'both units placed');
    const sel = results.find(r => r.id === 'u2');
    // Selected should get preferred position (not displaced)
    assert(sel.displaced === false, 'selected unit not displaced');
})();

(function() {
    // Off-screen units should be filtered
    const entries = [
        { id: 'u1', text: 'Visible', worldX: 400, worldY: 300, alliance: 'friendly' },
        { id: 'u2', text: 'OffScreen', worldX: -500, worldY: -500, alliance: 'friendly' },
    ];
    const results = resolveLabels(entries, 800, 600, 1, null, worldToScreen);
    assert(results.length === 1, 'off-screen unit filtered');
    assert(results[0].id === 'u1', 'visible unit kept');
})();

(function() {
    // Many units spread out — all should be placed
    const entries = [];
    for (let i = 0; i < 10; i++) {
        entries.push({
            id: `u${i}`,
            text: `Unit ${i}`,
            worldX: 100 + i * 70,
            worldY: 300,
            alliance: 'friendly',
        });
    }
    const results = resolveLabels(entries, 800, 600, 1, null, worldToScreen);
    assert(results.length === 10, 'all 10 spread-out units placed');
})();

(function() {
    // Dead units get lowest priority
    const entries = [
        { id: 'u1', text: 'Dead', worldX: 400, worldY: 300, alliance: 'hostile', status: 'dead' },
        { id: 'u2', text: 'Alive', worldX: 400, worldY: 300, alliance: 'hostile', status: 'active' },
    ];
    const results = resolveLabels(entries, 800, 600, 1, null, worldToScreen);
    assert(results.length === 2, 'dead and alive both placed');
    const alive = results.find(r => r.id === 'u2');
    assert(alive.displaced === false, 'alive hostile not displaced');
})();

(function() {
    // Zoom affects font size
    const entries = [{ id: 'u1', text: 'Test', worldX: 400, worldY: 300, alliance: 'friendly' }];
    const r1 = resolveLabels(entries, 800, 600, 0.5, null, worldToScreen);
    const r2 = resolveLabels(entries, 800, 600, 2.0, null, worldToScreen);
    // At zoom 2.0, font is larger so bgHeight should be bigger
    assert(r2[0].bgHeight >= r1[0].bgHeight, 'higher zoom produces equal or larger labels');
})();

(function() {
    // Hostile vs friendly priority
    const entries = [
        { id: 'u1', text: 'Friendly', worldX: 400, worldY: 300, alliance: 'friendly' },
        { id: 'u2', text: 'Hostile', worldX: 400, worldY: 300, alliance: 'hostile' },
    ];
    const results = resolveLabels(entries, 800, 600, 1, null, worldToScreen);
    const hostile = results.find(r => r.id === 'u2');
    assert(hostile.displaced === false, 'hostile gets priority over friendly');
})();

(function() {
    // Default alliance and status
    const entries = [{ id: 'u1', text: 'No alliance', worldX: 400, worldY: 300 }];
    const results = resolveLabels(entries, 800, 600, 1, null, worldToScreen);
    assert(results[0].alliance === 'neutral', 'missing alliance defaults to neutral');
    assert(results[0].status === 'active', 'missing status defaults to active');
})();

(function() {
    // Result has all expected fields
    const entries = [{ id: 'u1', text: 'Test', worldX: 400, worldY: 300, alliance: 'friendly', status: 'active' }];
    const results = resolveLabels(entries, 800, 600, 1, null, worldToScreen);
    const r = results[0];
    const fields = ['id', 'text', 'labelX', 'labelY', 'anchorX', 'anchorY', 'displaced', 'bgWidth', 'bgHeight', 'alliance', 'status'];
    fields.forEach(f => {
        assert(f in r, `result has field: ${f}`);
    });
})();


// --------------------------------------------------------------------------
// Performance: many units
// --------------------------------------------------------------------------

console.log('\n--- Performance ---');

(function() {
    const entries = [];
    for (let i = 0; i < 50; i++) {
        entries.push({
            id: `u${i}`,
            text: `Unit ${i} - Name`,
            worldX: 50 + (i % 10) * 80,
            worldY: 50 + Math.floor(i / 10) * 80,
            alliance: i % 3 === 0 ? 'hostile' : 'friendly',
            status: i % 7 === 0 ? 'dead' : 'active',
        });
    }
    const start = Date.now();
    const results = resolveLabels(entries, 800, 600, 1, 'u0', worldToScreen);
    const elapsed = Date.now() - start;
    assert(results.length === 50, '50 units all placed');
    assert(elapsed < 50, `50 units resolved in ${elapsed}ms (budget: 50ms)`);
})();


// --------------------------------------------------------------------------
// Summary
// --------------------------------------------------------------------------

console.log(`\n${'='.repeat(50)}`);
console.log(`Results: ${passed} passed, ${failed} failed`);
console.log(`${'='.repeat(50)}`);
process.exit(failed > 0 ? 1 : 0);
