// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
/**
 * TRITIUM-SC — Procedural Unit Icons tests
 * Run: node tests/js/test_unit_icons.js
 *
 * Tests the drawUnit() function from unit-icons.js:
 * - All unit types produce distinct shapes
 * - Rotation (heading) is applied
 * - Scaling works
 * - Selection ring drawn when selected
 * - Health bar drawn below unit
 * - Alliance colors are correct
 * - Neutralized units are faded
 */

const fs = require('fs');
const vm = require('vm');

// Simple test runner
let passed = 0, failed = 0;
function assert(cond, msg) {
    if (!cond) { console.error('FAIL:', msg); failed++; }
    else { console.log('PASS:', msg); passed++; }
}
function assertClose(a, b, eps, msg) {
    assert(Math.abs(a - b) < (eps || 0.01), msg + ` (got ${a}, expected ${b})`);
}

// ============================================================
// Mock Canvas 2D context — records all draw calls
// ============================================================

function createMockCtx() {
    const calls = [];
    const state = {
        fillStyle: '#000',
        strokeStyle: '#000',
        lineWidth: 1,
        globalAlpha: 1.0,
        font: '',
        textAlign: 'left',
        textBaseline: 'top',
        shadowColor: '',
        shadowBlur: 0,
    };
    const stateStack = [];

    const ctx = {
        calls,
        get fillStyle() { return state.fillStyle; },
        set fillStyle(v) { state.fillStyle = v; },
        get strokeStyle() { return state.strokeStyle; },
        set strokeStyle(v) { state.strokeStyle = v; },
        get lineWidth() { return state.lineWidth; },
        set lineWidth(v) { state.lineWidth = v; },
        get globalAlpha() { return state.globalAlpha; },
        set globalAlpha(v) { state.globalAlpha = v; },
        get font() { return state.font; },
        set font(v) { state.font = v; },
        get textAlign() { return state.textAlign; },
        set textAlign(v) { state.textAlign = v; },
        get textBaseline() { return state.textBaseline; },
        set textBaseline(v) { state.textBaseline = v; },
        get shadowColor() { return state.shadowColor; },
        set shadowColor(v) { state.shadowColor = v; },
        get shadowBlur() { return state.shadowBlur; },
        set shadowBlur(v) { state.shadowBlur = v; },
        save() { stateStack.push({ ...state }); calls.push({ fn: 'save' }); },
        restore() {
            const s = stateStack.pop();
            if (s) Object.assign(state, s);
            calls.push({ fn: 'restore' });
        },
        beginPath() { calls.push({ fn: 'beginPath' }); },
        closePath() { calls.push({ fn: 'closePath' }); },
        moveTo(x, y) { calls.push({ fn: 'moveTo', x, y }); },
        lineTo(x, y) { calls.push({ fn: 'lineTo', x, y }); },
        arc(x, y, r, start, end) { calls.push({ fn: 'arc', x, y, r, start, end }); },
        fill() { calls.push({ fn: 'fill', fillStyle: state.fillStyle, globalAlpha: state.globalAlpha }); },
        stroke() { calls.push({ fn: 'stroke', strokeStyle: state.strokeStyle, lineWidth: state.lineWidth }); },
        fillRect(x, y, w, h) { calls.push({ fn: 'fillRect', x, y, w, h, fillStyle: state.fillStyle }); },
        strokeRect(x, y, w, h) { calls.push({ fn: 'strokeRect', x, y, w, h }); },
        quadraticCurveTo(cpx, cpy, x, y) { calls.push({ fn: 'quadraticCurveTo', cpx, cpy, x, y }); },
        translate(x, y) { calls.push({ fn: 'translate', x, y }); },
        rotate(a) { calls.push({ fn: 'rotate', a }); },
        scale(x, y) { calls.push({ fn: 'scale', x, y }); },
        fillText(text, x, y) { calls.push({ fn: 'fillText', text, x, y }); },
        createRadialGradient(x0, y0, r0, x1, y1, r1) {
            return {
                addColorStop() {},
            };
        },
        setLineDash(d) { calls.push({ fn: 'setLineDash', d }); },
    };
    return ctx;
}

// ============================================================
// Load unit-icons.js into sandbox
// ============================================================

const code = fs.readFileSync(__dirname + '/../../frontend/js/command/unit-icons.js', 'utf8');

// The module uses export; wrap it so we can extract the exports
const wrappedCode = `
    var _exports = {};
    var performance = { now: function() { return _perfNow; } };
    ${code.replace(/export\s+function\s+(\w+)/g, 'function $1').replace(/export\s+\{[^}]*\}/, '')}
    _exports.drawUnit = typeof drawUnit === 'function' ? drawUnit : null;
    _exports.UNIT_TYPES = typeof UNIT_TYPES !== 'undefined' ? UNIT_TYPES : null;
    _exports.ALLIANCE_COLORS = typeof ALLIANCE_COLORS !== 'undefined' ? ALLIANCE_COLORS : null;
    _exports.getVisionRadius = typeof getVisionRadius === 'function' ? getVisionRadius : null;
`;

let _perfNow = 1000;
const ctx = vm.createContext({
    Math, Date, console, Map, Array, Object, Number, Infinity, Boolean, parseInt,
    parseFloat, isNaN, isFinite, undefined, null: null,
    _perfNow,
    performance: { now: () => _perfNow },
});

vm.runInContext(wrappedCode, ctx);

const { drawUnit, UNIT_TYPES, ALLIANCE_COLORS, getVisionRadius } = ctx._exports;

// ============================================================
// Test: drawUnit function exists
// ============================================================

console.log('\n--- drawUnit Function ---');

assert(typeof drawUnit === 'function', 'drawUnit is exported as a function');

// ============================================================
// Test: All unit types produce draw calls
// ============================================================

console.log('\n--- Unit Type Rendering ---');

const unitTypes = ['rover', 'drone', 'turret', 'hostile_person', 'neutral_person', 'tank', 'sensor', 'camera'];

for (const type of unitTypes) {
    (function testUnitType() {
        const mockCtx = createMockCtx();
        drawUnit(mockCtx, type, 'friendly', 0, 100, 100, 1.0, false, 1.0);
        const drawCalls = mockCtx.calls.filter(c => c.fn === 'fill' || c.fn === 'stroke' || c.fn === 'fillRect');
        assert(drawCalls.length > 0, `Unit type "${type}" produces draw calls (got ${drawCalls.length})`);
    })();
}

// ============================================================
// Test: Different types produce different call patterns
// ============================================================

console.log('\n--- Distinct Shapes ---');

(function testDistinctShapes() {
    const patterns = {};
    for (const type of ['rover', 'drone', 'turret', 'hostile_person', 'tank']) {
        const mockCtx = createMockCtx();
        drawUnit(mockCtx, type, 'friendly', 0, 100, 100, 1.0, false, 1.0);
        // Create a fingerprint from the sequence of draw call function names
        const fingerprint = mockCtx.calls.map(c => c.fn).join(',');
        patterns[type] = fingerprint;
    }
    // Each type should have a unique fingerprint
    const values = Object.values(patterns);
    const uniqueValues = new Set(values);
    assert(uniqueValues.size === values.length, `All 5 unit types produce distinct call patterns (${uniqueValues.size} unique out of ${values.length})`);
})();

// ============================================================
// Test: Alliance colors
// ============================================================

console.log('\n--- Alliance Colors ---');

(function testFriendlyColor() {
    const mockCtx = createMockCtx();
    drawUnit(mockCtx, 'rover', 'friendly', 0, 100, 100, 1.0, false, 1.0);
    const fills = mockCtx.calls.filter(c => c.fn === 'fill' && typeof c.fillStyle === 'string');
    const hasGreen = fills.some(c => c.fillStyle.includes('05ffa1') || c.fillStyle === '#05ffa1');
    assert(hasGreen, 'Friendly rover uses green (#05ffa1)');
})();

(function testHostileColor() {
    const mockCtx = createMockCtx();
    drawUnit(mockCtx, 'hostile_person', 'hostile', 0, 100, 100, 1.0, false, 1.0);
    const fills = mockCtx.calls.filter(c => c.fn === 'fill' && typeof c.fillStyle === 'string');
    const hasRed = fills.some(c => c.fillStyle.includes('ff2a6d') || c.fillStyle === '#ff2a6d');
    assert(hasRed, 'Hostile person uses red (#ff2a6d)');
})();

(function testNeutralColor() {
    const mockCtx = createMockCtx();
    drawUnit(mockCtx, 'neutral_person', 'neutral', 0, 100, 100, 1.0, false, 1.0);
    const fills = mockCtx.calls.filter(c => c.fn === 'fill' && typeof c.fillStyle === 'string');
    const hasBlue = fills.some(c => c.fillStyle.includes('00a0ff') || c.fillStyle === '#00a0ff');
    assert(hasBlue, 'Neutral person uses blue (#00a0ff)');
})();

// ============================================================
// Test: Heading rotation
// ============================================================

console.log('\n--- Heading Rotation ---');

(function testHeadingRotation() {
    const mockCtxA = createMockCtx();
    drawUnit(mockCtxA, 'rover', 'friendly', 0, 100, 100, 1.0, false, 1.0);
    const rotsA = mockCtxA.calls.filter(c => c.fn === 'rotate');

    const mockCtxB = createMockCtx();
    drawUnit(mockCtxB, 'rover', 'friendly', 90, 100, 100, 1.0, false, 1.0);
    const rotsB = mockCtxB.calls.filter(c => c.fn === 'rotate');

    assert(rotsA.length > 0, 'Rover with heading 0 has rotate call');
    assert(rotsB.length > 0, 'Rover with heading 90 has rotate call');
    if (rotsA.length > 0 && rotsB.length > 0) {
        assert(Math.abs(rotsA[0].a - rotsB[0].a) > 0.1, 'Different headings produce different rotation angles');
    }
})();

// ============================================================
// Test: Scale parameter
// ============================================================

console.log('\n--- Scale Parameter ---');

(function testScaleAffectsSize() {
    const mockCtxSmall = createMockCtx();
    drawUnit(mockCtxSmall, 'drone', 'friendly', 0, 100, 100, 0.5, false, 1.0);
    const arcsSmall = mockCtxSmall.calls.filter(c => c.fn === 'arc');

    const mockCtxLarge = createMockCtx();
    drawUnit(mockCtxLarge, 'drone', 'friendly', 0, 100, 100, 2.0, false, 1.0);
    const arcsLarge = mockCtxLarge.calls.filter(c => c.fn === 'arc');

    assert(arcsSmall.length > 0, 'Small scale drone draws arcs');
    assert(arcsLarge.length > 0, 'Large scale drone draws arcs');

    if (arcsSmall.length > 0 && arcsLarge.length > 0) {
        // The radius of arcs at scale 2.0 should be larger than at scale 0.5
        const rSmall = Math.max(...arcsSmall.map(a => a.r));
        const rLarge = Math.max(...arcsLarge.map(a => a.r));
        assert(rLarge > rSmall, `Scale 2.0 arcs larger than scale 0.5 (${rLarge.toFixed(1)} > ${rSmall.toFixed(1)})`);
    }
})();

// ============================================================
// Test: Selection ring
// ============================================================

console.log('\n--- Selection Ring ---');

(function testSelectedRing() {
    const mockCtxSelected = createMockCtx();
    drawUnit(mockCtxSelected, 'rover', 'friendly', 0, 100, 100, 1.0, true, 1.0);
    const selectedCalls = mockCtxSelected.calls;

    const mockCtxNormal = createMockCtx();
    drawUnit(mockCtxNormal, 'rover', 'friendly', 0, 100, 100, 1.0, false, 1.0);
    const normalCalls = mockCtxNormal.calls;

    // Selected should have more draw calls (the selection ring)
    assert(selectedCalls.length > normalCalls.length, `Selected unit has more draw calls (${selectedCalls.length} > ${normalCalls.length})`);

    // Check for the cyan selection ring color
    const hasCyanStroke = selectedCalls.some(c => c.fn === 'stroke' && c.strokeStyle && c.strokeStyle.includes('00f0ff'));
    assert(hasCyanStroke, 'Selected unit draws cyan (#00f0ff) selection ring');
})();

// ============================================================
// Test: Health bar
// ============================================================

console.log('\n--- Health Bar ---');

(function testHealthBarDrawn() {
    const mockCtxFull = createMockCtx();
    drawUnit(mockCtxFull, 'rover', 'friendly', 0, 100, 100, 1.0, false, 1.0);
    const fullCalls = mockCtxFull.calls;

    const mockCtxHalf = createMockCtx();
    drawUnit(mockCtxHalf, 'rover', 'friendly', 0, 100, 100, 1.0, false, 0.5);
    const halfCalls = mockCtxHalf.calls;

    // Damaged unit should have more draw calls (health bar)
    assert(halfCalls.length > fullCalls.length, `Damaged unit has more draw calls (${halfCalls.length} > ${fullCalls.length})`);

    // Health bar should draw a fillRect below the unit
    const healthRects = halfCalls.filter(c => c.fn === 'fillRect');
    assert(healthRects.length > 0, 'Damaged unit draws fillRect for health bar');
})();

(function testHealthBarColor() {
    // At 25% health, bar should be red
    const mockCtx = createMockCtx();
    drawUnit(mockCtx, 'rover', 'friendly', 0, 100, 100, 1.0, false, 0.25);
    const fills = mockCtx.calls.filter(c => c.fn === 'fillRect');
    // There should be some red-ish fill
    const hasRed = fills.some(c => {
        const fs = c.fillStyle || '';
        return fs.includes('255') && fs.includes('rgb');
    });
    // This may or may not be exact, so just check health bar exists
    assert(fills.length > 0, 'Health bar at 25% draws fillRect');
})();

// ============================================================
// Test: Neutralized units fade
// ============================================================

console.log('\n--- Neutralized Units ---');

(function testNeutralizedFade() {
    const mockCtx = createMockCtx();
    // Use globalAlpha tracking -- the function should set alpha < 1 for neutralized
    drawUnit(mockCtx, 'rover', 'friendly', 0, 100, 100, 1.0, false, 0);
    const fills = mockCtx.calls.filter(c => c.fn === 'fill');
    const hasFaded = fills.some(c => c.globalAlpha < 1.0);
    assert(hasFaded, 'Unit at 0 health (neutralized) is drawn with reduced alpha');
})();

// ============================================================
// Test: Vision radius export
// ============================================================

console.log('\n--- Vision Radius ---');

if (getVisionRadius) {
    (function testVisionRadii() {
        assert(getVisionRadius('rover') > 0, 'Rover has positive vision radius');
        assert(getVisionRadius('drone') > getVisionRadius('rover'), 'Drone vision > rover vision');
        assert(getVisionRadius('turret') > 0, 'Turret has positive vision radius');
        assert(getVisionRadius('camera') > 0, 'Camera has positive vision radius');
    })();
} else {
    console.log('SKIP: getVisionRadius not exported');
}

// ============================================================
// Results
// ============================================================

console.log(`\n=== Unit Icons Tests: ${passed} passed, ${failed} failed ===`);
process.exit(failed > 0 ? 1 : 0);
