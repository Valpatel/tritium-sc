// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
/**
 * TRITIUM-SC Bonus Objectives HUD Tests
 *
 * Tests the bonus objectives tracker in the war HUD:
 * - warHudSetBonusObjectives() stores objectives in HUD state
 * - warHudDrawBonusObjectives() renders a checklist on the canvas
 * - Objective names, rewards, and completion state are displayed
 * - Objectives only render during active game state
 *
 * Run: node tests/js/test_bonus_objectives.js
 */

const fs = require('fs');
const vm = require('vm');

let passed = 0, failed = 0;
function assert(cond, msg) {
    if (!cond) { console.error('FAIL:', msg); failed++; }
    else { console.log('PASS:', msg); passed++; }
}

function assertEq(a, b, msg) {
    if (a === b) { console.log('PASS:', msg); passed++; }
    else { console.error(`FAIL: ${msg} (expected ${JSON.stringify(b)}, got ${JSON.stringify(a)})`); failed++; }
}

let hudCode = fs.readFileSync(__dirname + '/../../src/frontend/js/war-hud.js', 'utf8');

// Expose internal state for testing
hudCode += `
window._hudState = _hudState;
`;

// Mock DOM
const mockElements = {};
let timeouts = [];

const ctx = vm.createContext({
    Math, console, Array, Object, Number, Boolean, parseInt, parseFloat, Infinity, String,
    Date: { now: () => 10000 },
    setTimeout: (fn, ms) => { timeouts.push({ fn, ms }); return timeouts.length; },
    clearTimeout: () => {},
    setInterval: () => 1,
    clearInterval: () => {},
    fetch: () => Promise.resolve({ ok: true, json: () => Promise.resolve({}) }),
    window: {},
    warState: {
        audioCtx: null,
        targets: [],
        selectedTargets: [],
        effects: [],
        dispatchArrows: [],
        stats: { eliminations: 0, breaches: 0, dispatches: 0 },
    },
    warCombatReset: () => {},
    document: {
        getElementById(id) {
            if (!mockElements[id]) {
                mockElements[id] = {
                    style: { display: '', opacity: '' },
                    textContent: '',
                    innerHTML: '',
                    className: '',
                    classList: {
                        _classes: [],
                        add(cls) { this._classes.push(cls); },
                        remove(cls) { this._classes = this._classes.filter(c => c !== cls); },
                    },
                    onclick: null,
                    offsetWidth: 100,
                };
            }
            return mockElements[id];
        },
        createElement(tag) {
            const el = { _text: '' };
            Object.defineProperty(el, 'textContent', {
                get() { return el._text; },
                set(v) { el._text = String(v); },
            });
            Object.defineProperty(el, 'innerHTML', {
                get() { return el._text; },
                set(v) { el._text = String(v); },
            });
            return el;
        },
    },
});

vm.runInContext(hudCode, ctx);

const w = ctx.window;
const st = w._hudState;

// ============================================================
// warHudSetBonusObjectives function exists
// ============================================================

console.log('\n--- warHudSetBonusObjectives function ---');

{
    assert(typeof w.warHudSetBonusObjectives === 'function',
        'warHudSetBonusObjectives is exposed on window');
}

// ============================================================
// Setting bonus objectives
// ============================================================

console.log('\n--- Setting objectives ---');

{
    w.warHudSetBonusObjectives([
        { name: 'No casualties', description: 'Complete without losing any defenders', reward: 1000 },
        { name: 'Speed run', description: 'Complete in under 5 minutes', reward: 500 },
    ]);

    assert(Array.isArray(st.bonusObjectives), 'bonusObjectives stored as array');
    assertEq(st.bonusObjectives.length, 2, 'two objectives stored');
    assertEq(st.bonusObjectives[0].name, 'No casualties', 'first objective name correct');
    assertEq(st.bonusObjectives[0].reward, 1000, 'first objective reward correct');
    assertEq(st.bonusObjectives[1].name, 'Speed run', 'second objective name correct');
}

{
    // Each objective should have a completed flag defaulting to false
    assert(st.bonusObjectives[0].completed === false, 'objectives default to not completed');
    assert(st.bonusObjectives[1].completed === false, 'second objective default to not completed');
}

// ============================================================
// Completing objectives
// ============================================================

console.log('\n--- Completing objectives ---');

{
    assert(typeof w.warHudCompleteBonusObjective === 'function',
        'warHudCompleteBonusObjective is exposed on window');
}

{
    w.warHudCompleteBonusObjective('No casualties');
    assert(st.bonusObjectives[0].completed === true, 'first objective marked completed');
    assert(st.bonusObjectives[1].completed === false, 'second objective still incomplete');
}

{
    // Completing a non-existent objective does not crash
    w.warHudCompleteBonusObjective('nonexistent');
    assertEq(st.bonusObjectives.length, 2, 'no crash on nonexistent objective');
}

// ============================================================
// warHudDrawBonusObjectives canvas rendering
// ============================================================

console.log('\n--- Canvas rendering ---');

{
    assert(typeof w.warHudDrawBonusObjectives === 'function',
        'warHudDrawBonusObjectives is exposed on window');
}

// Mock canvas context for rendering tests
function mockCtx() {
    const calls = [];
    return {
        calls,
        save() { calls.push('save'); },
        restore() { calls.push('restore'); },
        fillText(text, x, y) { calls.push({ op: 'fillText', text, x, y }); },
        fillRect(x, y, w, h) { calls.push({ op: 'fillRect', x, y, w, h }); },
        strokeRect(x, y, w, h) { calls.push({ op: 'strokeRect', x, y, w, h }); },
        beginPath() { calls.push('beginPath'); },
        arc() { calls.push('arc'); },
        fill() { calls.push('fill'); },
        stroke() { calls.push('stroke'); },
        moveTo() {},
        lineTo() {},
        closePath() {},
        set fillStyle(v) { calls.push({ op: 'fillStyle', value: v }); },
        get fillStyle() { return '#000'; },
        set strokeStyle(v) { calls.push({ op: 'strokeStyle', value: v }); },
        get strokeStyle() { return '#000'; },
        set font(v) { calls.push({ op: 'font', value: v }); },
        get font() { return '10px monospace'; },
        set textAlign(v) { calls.push({ op: 'textAlign', value: v }); },
        get textAlign() { return 'left'; },
        set textBaseline(v) { calls.push({ op: 'textBaseline', value: v }); },
        get textBaseline() { return 'top'; },
        set globalAlpha(v) { calls.push({ op: 'globalAlpha', value: v }); },
        get globalAlpha() { return 1; },
        set lineWidth(v) {},
        get lineWidth() { return 1; },
    };
}

{
    // Only render when game is active
    st.gameState = 'idle';
    const c = mockCtx();
    w.warHudDrawBonusObjectives(c, 800, 600);
    const textCalls = c.calls.filter(c => c.op === 'fillText');
    assertEq(textCalls.length, 0, 'no rendering when game is idle');
}

{
    // Render when game is active
    st.gameState = 'active';
    const c = mockCtx();
    w.warHudDrawBonusObjectives(c, 800, 600);
    const textCalls = c.calls.filter(c => c.op === 'fillText');
    assert(textCalls.length > 0, 'renders text when game is active');
}

{
    // Renders objective names
    st.gameState = 'active';
    const c = mockCtx();
    w.warHudDrawBonusObjectives(c, 800, 600);
    const textCalls = c.calls.filter(c => c.op === 'fillText');
    const texts = textCalls.map(c => c.text);
    assert(texts.some(t => t.includes('No casualties')), 'renders first objective name');
    assert(texts.some(t => t.includes('Speed run')), 'renders second objective name');
}

{
    // Renders reward amounts
    st.gameState = 'active';
    const c = mockCtx();
    w.warHudDrawBonusObjectives(c, 800, 600);
    const texts = c.calls.filter(c => c.op === 'fillText').map(c => String(c.text));
    assert(texts.some(t => t.includes('1000') || t.includes('1,000')), 'renders reward amount for completed objective');
}

{
    // Completed objective uses green color
    st.gameState = 'active';
    const c = mockCtx();
    w.warHudDrawBonusObjectives(c, 800, 600);
    const styles = c.calls.filter(c => c.op === 'fillStyle').map(c => c.value);
    assert(styles.some(s => s === '#05ffa1'), 'uses green for completed objective');
}

// ============================================================
// Game over screen includes bonus objectives
// ============================================================

console.log('\n--- Game over bonus display ---');

{
    // Setup objectives and complete one
    w.warHudSetBonusObjectives([
        { name: 'No casualties', description: 'Keep all units alive', reward: 1000 },
        { name: 'Speed run', description: 'Complete under 5 min', reward: 500 },
    ]);
    w.warHudCompleteBonusObjective('No casualties');

    // Call game over
    w.warHudShowGameOver('victory', 5000, 10, 15, {});

    // Check that the game over screen HTML includes the objectives
    const el = ctx.document.getElementById('war-game-over');
    const html = el.innerHTML;
    assert(html.includes('No casualties'), 'game over shows "No casualties" objective');
    assert(html.includes('Speed run'), 'game over shows "Speed run" objective');
    assert(html.includes('#05ffa1'), 'completed objective has green color');
    assert(html.includes('#666666'), 'incomplete objective has grey color');
}

{
    // Reset for further tests
    w.warHudSetBonusObjectives([]);
    w.warHudPlayAgain();
    assertEq(st.bonusObjectives.length, 0, 'bonusObjectives cleared on play again');
}

// ============================================================
// Reset on game state change to idle
// ============================================================

console.log('\n--- Reset ---');

{
    // Setting empty objectives clears the list
    w.warHudSetBonusObjectives([]);
    assertEq(st.bonusObjectives.length, 0, 'setting empty array clears objectives');
}

{
    // Null/undefined gracefully handled
    w.warHudSetBonusObjectives(null);
    assertEq(st.bonusObjectives.length, 0, 'null objectives handled gracefully');
}

{
    w.warHudSetBonusObjectives(undefined);
    assertEq(st.bonusObjectives.length, 0, 'undefined objectives handled gracefully');
}

// ============================================================
// Summary
// ============================================================

console.log(`\n--- Bonus Objectives: ${passed} passed, ${failed} failed ---`);
if (failed > 0) process.exit(1);
