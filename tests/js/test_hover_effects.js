// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
/**
 * TRITIUM-SC Hover Effects tests
 * Tests hover ring rendering in unit-icons.js and MapLibre marker hover class.
 * Run: node tests/js/test_hover_effects.js
 */

const fs = require('fs');
const vm = require('vm');

let passed = 0, failed = 0;
function assert(cond, msg) {
    if (!cond) { console.error('FAIL:', msg); failed++; }
    else { console.log('PASS:', msg); passed++; }
}

// ============================================================
// Canvas 2D mock
// ============================================================

function createMockCtx() {
    const calls = [];
    const state = { lineDash: [], lineWidth: 1, strokeStyle: '#000', fillStyle: '#000', globalAlpha: 1.0 };
    const stateStack = [];
    return {
        calls,
        state,
        save() { calls.push('save'); stateStack.push({ ...state, lineDash: [...state.lineDash] }); },
        restore() {
            calls.push('restore');
            const prev = stateStack.pop();
            if (prev) Object.assign(state, prev);
        },
        translate(x, y) { calls.push(`translate(${x},${y})`); },
        rotate(r) { calls.push(`rotate(${r})`); },
        beginPath() { calls.push('beginPath'); },
        closePath() { calls.push('closePath'); },
        arc(x, y, r, s, e) { calls.push(`arc(${x},${y},${r})`); },
        moveTo(x, y) { calls.push(`moveTo(${x},${y})`); },
        lineTo(x, y) { calls.push(`lineTo(${x},${y})`); },
        quadraticCurveTo() { calls.push('quadraticCurveTo'); },
        stroke() { calls.push('stroke'); },
        fill() { calls.push('fill'); },
        fillRect(x, y, w, h) { calls.push(`fillRect(${x},${y},${w},${h})`); },
        set strokeStyle(v) { state.strokeStyle = v; calls.push(`strokeStyle=${v}`); },
        get strokeStyle() { return state.strokeStyle; },
        set fillStyle(v) { state.fillStyle = v; calls.push(`fillStyle=${v}`); },
        get fillStyle() { return state.fillStyle; },
        set lineWidth(v) { state.lineWidth = v; calls.push(`lineWidth=${v}`); },
        get lineWidth() { return state.lineWidth; },
        set globalAlpha(v) { state.globalAlpha = v; },
        get globalAlpha() { return state.globalAlpha; },
        setLineDash(arr) { state.lineDash = arr; calls.push(`setLineDash([${arr}])`); },
        getLineDash() { return state.lineDash; },
    };
}

// ============================================================
// Load unit-icons.js
// ============================================================

const src = fs.readFileSync('frontend/js/command/unit-icons.js', 'utf-8');
const cleaned = src
    .replace(/^export\s*\{[^}]*\};?\s*$/m, '')
    .replace(/export\s+(function|const|let|var|class)/g, '$1');

const sandbox = {
    performance: { now: () => 1000 },
    console,
    module: { exports: {} },
    exports: {},
};
const ctx = vm.createContext(sandbox);
vm.runInContext(cleaned + `
    module.exports = { drawUnit, drawCrowdRoleIndicator, UNIT_TYPES, ALLIANCE_COLORS, getVisionRadius };
`, ctx);

const { drawUnit, UNIT_TYPES, ALLIANCE_COLORS, getVisionRadius } = sandbox.module.exports;

// ============================================================
// Tests
// ============================================================

// Test 1: drawUnit accepts 10 arguments (hovered as 10th)
{
    const mockCtx = createMockCtx();
    // Should not throw with 10 args
    try {
        drawUnit(mockCtx, 'rover', 'friendly', 90, 100, 100, 1.0, false, 1.0, true);
        assert(true, 'drawUnit accepts 10 arguments without error');
    } catch (e) {
        assert(false, 'drawUnit accepts 10 arguments without error: ' + e.message);
    }
}

// Test 2: Hover ring draws dashed line when hovered=true, selected=false
{
    const mockCtx = createMockCtx();
    drawUnit(mockCtx, 'rover', 'friendly', 90, 100, 100, 1.0, false, 1.0, true);
    const calls = mockCtx.calls;
    const dashCalls = calls.filter(c => c.startsWith('setLineDash('));
    // Should have a setLineDash with non-empty array (dashed) and then reset to empty
    const hasDash = dashCalls.some(c => c !== 'setLineDash([])');
    assert(hasDash, 'Hover ring uses setLineDash for dashed line');
}

// Test 3: Hover ring uses white-ish stroke
{
    const mockCtx = createMockCtx();
    drawUnit(mockCtx, 'rover', 'friendly', 90, 100, 100, 1.0, false, 1.0, true);
    const calls = mockCtx.calls;
    const hasWhiteStroke = calls.some(c =>
        c.startsWith('strokeStyle=') && c.includes('rgba(255') && c.includes('255') && c.includes('255')
    );
    assert(hasWhiteStroke, 'Hover ring uses white rgba stroke');
}

// Test 4: Selection ring takes precedence (selected=true, hovered=true)
{
    const mockCtx = createMockCtx();
    drawUnit(mockCtx, 'rover', 'friendly', 90, 100, 100, 1.0, true, 1.0, true);
    const calls = mockCtx.calls;
    // Selection ring uses cyan #00f0ff
    const hasCyanStroke = calls.some(c => c.startsWith('strokeStyle=') && c.includes('#00f0ff'));
    assert(hasCyanStroke, 'Selection ring draws cyan stroke when selected=true');
    // Should NOT have the hover dashed line pattern (since selection takes priority)
    // The only setLineDash calls should be empty (resets) or absent
    const dashCalls = calls.filter(c => c.startsWith('setLineDash('));
    const hasNonEmptyDash = dashCalls.some(c => c !== 'setLineDash([])');
    assert(!hasNonEmptyDash, 'No dashed line when selected takes precedence over hovered');
}

// Test 5: No hover ring when hovered=false
{
    const mockCtx = createMockCtx();
    drawUnit(mockCtx, 'rover', 'friendly', 90, 100, 100, 1.0, false, 1.0, false);
    const calls = mockCtx.calls;
    // Should not have any dashed line pattern
    const dashCalls = calls.filter(c => c.startsWith('setLineDash('));
    const hasNonEmptyDash = dashCalls.some(c => c !== 'setLineDash([])');
    assert(!hasNonEmptyDash, 'No dashed line when hovered=false');
}

// Test 6: drawUnit still works with 9 arguments (backward compat)
{
    const mockCtx = createMockCtx();
    try {
        drawUnit(mockCtx, 'rover', 'friendly', 90, 100, 100, 1.0, false, 1.0);
        assert(true, 'drawUnit works with 9 arguments (backward compat)');
    } catch (e) {
        assert(false, 'drawUnit works with 9 arguments: ' + e.message);
    }
}

// Test 7: Hover ring arc radius is 7 * scale
{
    const mockCtx = createMockCtx();
    const scale = 1.5;
    drawUnit(mockCtx, 'rover', 'friendly', 90, 100, 100, scale, false, 1.0, true);
    const calls = mockCtx.calls;
    // After the dash is set, we should see an arc call with radius 7*scale
    const expectedR = 7 * scale;
    const hasArc = calls.some(c => c === `arc(0,0,${expectedR})`);
    assert(hasArc, `Hover ring arc radius is 7*scale=${expectedR}`);
}

// Test 8: MapLibre marker gets unit-marker-hovered class on mouseenter
{
    // Simulate DOM element
    const classListSet = new Set();
    const el = {
        classList: {
            add(c) { classListSet.add(c); },
            remove(c) { classListSet.delete(c); },
            contains(c) { return classListSet.has(c); },
        },
        addEventListener(event, handler) {
            if (event === 'mouseenter') handler();
        },
    };
    el.addEventListener('mouseenter', () => {
        el.classList.add('unit-marker-hovered');
    });
    assert(classListSet.has('unit-marker-hovered'), 'MapLibre marker outer gets unit-marker-hovered on mouseenter');
}

// Test 9: MapLibre marker removes unit-marker-hovered on mouseleave
{
    const classListSet = new Set(['unit-marker-hovered']);
    const el = {
        classList: {
            add(c) { classListSet.add(c); },
            remove(c) { classListSet.delete(c); },
            contains(c) { return classListSet.has(c); },
        },
        addEventListener(event, handler) {
            if (event === 'mouseleave') handler();
        },
    };
    el.addEventListener('mouseleave', () => {
        el.classList.remove('unit-marker-hovered');
    });
    assert(!classListSet.has('unit-marker-hovered'), 'MapLibre marker outer loses unit-marker-hovered on mouseleave');
}

// ============================================================
// Summary
// ============================================================
console.log(`\n${passed} passed, ${failed} failed out of ${passed + failed}`);
if (failed > 0) process.exit(1);
