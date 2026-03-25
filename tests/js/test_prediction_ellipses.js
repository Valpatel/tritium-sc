// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
/**
 * TRITIUM-SC prediction-ellipses.js tests
 * Tests PredictionEllipseManager: instantiation, start/stop timer,
 * trail data, and graceful handling of empty units.
 * Run: node tests/js/test_prediction_ellipses.js
 */

const fs = require('fs');
const vm = require('vm');

// Simple test runner
let passed = 0, failed = 0;
function assert(cond, msg) {
    if (!cond) { console.error('FAIL:', msg); failed++; }
    else { console.log('PASS:', msg); passed++; }
}

// ============================================================
// DOM + browser mocks
// ============================================================

function createMockElement(tag) {
    const children = [];
    const style = {};
    let _innerHTML = '';

    const el = {
        tagName: (tag || 'DIV').toUpperCase(),
        className: '',
        get innerHTML() { return _innerHTML; },
        set innerHTML(val) { _innerHTML = val; },
        style,
        children,
        appendChild(child) { children.push(child); return child; },
        querySelector() { return null; },
        querySelectorAll() { return []; },
        addEventListener() {},
    };
    return el;
}

const sandbox = {
    Math, Date, console, Map, Set, Array, Object, Number, String, Boolean,
    Infinity, NaN, undefined, parseInt, parseFloat, isNaN, isFinite, JSON,
    Promise, setTimeout, clearTimeout, setInterval, clearInterval, Error,
    document: {
        createElement: createMockElement,
        getElementById: () => null,
        querySelector: () => null,
        addEventListener() {},
    },
    window: { _mapState: null },
    performance: { now: () => Date.now() },
};

const ctx = vm.createContext(sandbox);

// Load events.js (EventBus)
const eventsCode = fs.readFileSync(__dirname + '/../../../tritium-lib/web/events.js', 'utf8');
const eventsPlain = eventsCode
    .replace(/^export\s+/gm, '')
    .replace(/^import\s+.*$/gm, '');
vm.runInContext(eventsPlain, ctx);

// Load store.js (TritiumStore)
const storeCode = fs.readFileSync(__dirname + '/../../src/frontend/js/command/store.js', 'utf8');
const storePlain = storeCode
    .replace(/^export\s+/gm, '')
    .replace(/^import\s+.*$/gm, '');
vm.runInContext(storePlain, ctx);

// Load prediction-ellipses.js
const peCode = fs.readFileSync(__dirname + '/../../src/frontend/js/command/prediction-ellipses.js', 'utf8');
const pePlain = peCode
    .replace(/^export\s+class\s+(\w+)/gm, 'var $1 = class $1')
    .replace(/^export\s+/gm, '')
    .replace(/^import\s+.*$/gm, '');
vm.runInContext(pePlain, ctx);

const PredictionEllipseManager = ctx.PredictionEllipseManager;

// ============================================================
// 1. Instantiation
// ============================================================

console.log('\n--- PredictionEllipseManager instantiation ---');

(function testInstantiate() {
    const mgr = new PredictionEllipseManager();
    assert(mgr !== undefined, 'instantiates without errors');
    assert(mgr._visible === false, '_visible defaults to false');
    assert(mgr._layersAdded === false, '_layersAdded defaults to false');
})();

// ============================================================
// 2. Start and stop timer
// ============================================================

console.log('\n--- start/stop timer ---');

(function testStartSetsTimer() {
    const mgr = new PredictionEllipseManager();
    mgr.start();
    assert(mgr._timer !== null, 'start() sets _timer');
    mgr.stop();
    assert(mgr._timer === null, 'stop() clears _timer');
})();

// ============================================================
// 3. Accept trail data
// ============================================================

console.log('\n--- trail data ---');

(function testSetTrailData() {
    const mgr = new PredictionEllipseManager();
    const trails = new Map();
    trails.set('unit1', [
        { lng: -121.896, lat: 37.716, time: 1000 },
        { lng: -121.8961, lat: 37.7161, time: 2000 },
    ]);
    mgr.setTrailData(trails);
    assert(mgr._trailData.size === 1, 'setTrailData stores trail data');
    assert(mgr._trailData.has('unit1'), 'trail data contains unit1');
})();

// ============================================================
// 4. Handle empty units gracefully
// ============================================================

console.log('\n--- empty units ---');

(function testUpdateWithNoUnits() {
    const mgr = new PredictionEllipseManager();
    let threw = false;
    try {
        mgr._update();
    } catch (e) {
        threw = true;
    }
    assert(!threw, '_update() with no units does not throw');
})();

// ============================================================
// 5. Ellipse generation (indirect via public API)
// ============================================================

console.log('\n--- ellipse generation ---');

(function testManagerHasTrailDataMap() {
    const mgr = new PredictionEllipseManager();
    assert(mgr._trailData instanceof Map, '_trailData is a Map');
    assert(mgr._trailData.size === 0, '_trailData starts empty');
})();

// ============================================================
// Summary
// ============================================================

console.log('\n' + '='.repeat(40));
console.log(`Results: ${passed} passed, ${failed} failed`);
console.log('='.repeat(40));
process.exit(failed > 0 ? 1 : 0);
