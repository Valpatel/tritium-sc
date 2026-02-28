// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
/**
 * TRITIUM-SC Unit Command Panel Tests
 * Tests the enhanced unit detail panel with send-command feature,
 * squad display, and friendly-only command input.
 * Run: node tests/js/test_unit_command.js
 */

const fs = require('fs');
const vm = require('vm');

let passed = 0, failed = 0;
function assert(cond, msg) {
    if (!cond) { console.error('FAIL:', msg); failed++; }
    else { console.log('PASS:', msg); passed++; }
}

// ============================================================
// DOM mock
// ============================================================

function createMockElement(tag) {
    const children = [];
    const classList = new Set();
    const eventListeners = {};
    const dataset = {};
    const style = {};
    let _innerHTML = '';
    let _textContent = '';

    const el = {
        tagName: (tag || 'DIV').toUpperCase(),
        className: '',
        get innerHTML() { return _innerHTML; },
        set innerHTML(val) { _innerHTML = val; },
        get textContent() { return _textContent; },
        set textContent(val) {
            _textContent = String(val);
            _innerHTML = String(val).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
        },
        style, dataset, children, childNodes: children, parentNode: null,
        hidden: false, value: 'all', disabled: false,
        get classList() {
            return {
                add(cls) { classList.add(cls); },
                remove(cls) { classList.delete(cls); },
                contains(cls) { return classList.has(cls); },
                toggle(cls, force) {
                    if (force === undefined) {
                        if (classList.has(cls)) classList.delete(cls);
                        else classList.add(cls);
                    } else if (force) classList.add(cls);
                    else classList.delete(cls);
                },
            };
        },
        appendChild(child) { children.push(child); if (child) child.parentNode = el; return child; },
        remove() {}, focus() {},
        addEventListener(evt, fn) {
            if (!eventListeners[evt]) eventListeners[evt] = [];
            eventListeners[evt].push(fn);
        },
        removeEventListener(evt, fn) {
            if (eventListeners[evt]) eventListeners[evt] = eventListeners[evt].filter(f => f !== fn);
        },
        _childCache: {},
        querySelector(sel) {
            if (el._childCache[sel]) return el._childCache[sel];
            const bindMatch = sel.match(/\[data-bind="([^"]+)"\]/);
            if (bindMatch) {
                const mock = createMockElement(bindMatch[1] === 'filter' ? 'select' : 'div');
                mock._bindName = bindMatch[1];
                if (bindMatch[1] === 'filter') mock.value = 'all';
                el._childCache[sel] = mock;
                return mock;
            }
            const classMatch = sel.match(/\.([a-zA-Z0-9_-]+)/);
            if (classMatch) {
                const mock = createMockElement(classMatch[1].includes('input') ? 'input' : 'div');
                mock.className = classMatch[1];
                el._childCache[sel] = mock;
                return mock;
            }
            return null;
        },
        querySelectorAll() { return []; },
        closest() { return null; },
        _eventListeners: eventListeners,
        _classList: classList,
    };
    return el;
}

let fetchCalls = [];
const sandbox = {
    Math, Date, console, Map, Set, Array, Object, Number, String, Boolean,
    Infinity, NaN, undefined, parseInt, parseFloat, isNaN, isFinite, JSON,
    Promise, setTimeout, clearTimeout, setInterval, clearInterval, Error,
    document: {
        createElement: createMockElement,
        getElementById: () => null,
        querySelector: () => null,
        addEventListener() {}, removeEventListener() {},
    },
    window: {},
    fetch(url, opts) {
        fetchCalls.push({ url, opts });
        return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    },
    performance: { now: () => Date.now() },
};

const ctx = vm.createContext(sandbox);

// Load EventBus
const eventsCode = fs.readFileSync(__dirname + '/../../frontend/js/command/events.js', 'utf8')
    .replace(/^export\s+/gm, '').replace(/^import\s+.*$/gm, '');
vm.runInContext(eventsCode, ctx);

// Load TritiumStore
const storeCode = fs.readFileSync(__dirname + '/../../frontend/js/command/store.js', 'utf8')
    .replace(/^export\s+/gm, '').replace(/^import\s+.*$/gm, '');
vm.runInContext(storeCode, ctx);

// Load units.js panel
const unitsCode = fs.readFileSync(__dirname + '/../../frontend/js/command/panels/units.js', 'utf8')
    .replace(/^export\s+const\s+/gm, 'var ').replace(/^export\s+/gm, '').replace(/^import\s+.*$/gm, '');
vm.runInContext(unitsCode, ctx);

const UnitsPanelDef = ctx.UnitsPanelDef;
const TritiumStore = vm.runInContext('TritiumStore', ctx);

function getDetailHtml(unitData) {
    TritiumStore.units.clear();
    fetchCalls = [];
    const bodyEl = UnitsPanelDef.create({});
    const panel = { def: UnitsPanelDef, _unsubs: [] };
    TritiumStore.updateUnit(unitData.id, unitData);
    TritiumStore.set('map.selectedUnitId', unitData.id);
    UnitsPanelDef.mount(bodyEl, panel);
    const detailEl = bodyEl.querySelector('[data-bind="detail"]');
    return detailEl ? detailEl.innerHTML : '';
}

// ============================================================
// 1. Friendly units show command input
// ============================================================

console.log('\n--- Friendly unit command input ---');

(function testFriendlyUnitHasCommandInput() {
    const html = getDetailHtml({
        id: 'rover-01', name: 'Rover Alpha', type: 'rover',
        alliance: 'friendly', position: { x: 10, y: 20 },
        health: 100, maxHealth: 100,
    });
    assert(html.includes('SEND COMMAND'), 'Friendly unit detail shows SEND COMMAND section');
})();

(function testFriendlyUnitHasInputField() {
    const html = getDetailHtml({
        id: 'turret-01', name: 'Turret-1', type: 'turret',
        alliance: 'friendly', position: { x: 0, y: 0 },
        health: 200, maxHealth: 200,
    });
    assert(html.includes('panel-cmd-input'), 'Friendly unit detail has command input');
    assert(html.includes('panel-cmd-send'), 'Friendly unit detail has send button');
})();

(function testFriendlyUnitHasStatusArea() {
    const html = getDetailHtml({
        id: 'drone-01', name: 'Drone-1', type: 'drone',
        alliance: 'friendly', position: { x: 5, y: 5 },
        health: 60, maxHealth: 60,
    });
    assert(html.includes('panel-cmd-status'), 'Friendly unit detail has status area');
})();

// ============================================================
// 2. Hostile units do NOT show command input
// ============================================================

console.log('\n--- Hostile unit no command ---');

(function testHostileUnitNoCommandInput() {
    const html = getDetailHtml({
        id: 'hostile-01', name: 'Bad Guy', type: 'person',
        alliance: 'hostile', position: { x: 50, y: 50 },
        health: 100, maxHealth: 100,
    });
    assert(!html.includes('SEND COMMAND'), 'Hostile unit detail has no SEND COMMAND section');
    assert(!html.includes('panel-cmd-input'), 'Hostile unit detail has no command input');
})();

(function testNeutralUnitNoCommandInput() {
    const html = getDetailHtml({
        id: 'neutral-01', name: 'Bystander', type: 'person',
        alliance: 'neutral', position: { x: 30, y: 30 },
        health: 50, maxHealth: 50,
    });
    assert(!html.includes('SEND COMMAND'), 'Neutral unit detail has no SEND COMMAND section');
})();

// ============================================================
// 3. Squad info displayed when present
// ============================================================

console.log('\n--- Squad info ---');

(function testSquadIdDisplayed() {
    const html = getDetailHtml({
        id: 'rover-02', name: 'Rover Beta', type: 'rover',
        alliance: 'friendly', position: { x: 10, y: 20 },
        health: 100, maxHealth: 100, squadId: 'alpha-squad',
    });
    assert(html.includes('SQUAD'), 'Detail panel shows SQUAD label when squadId present');
    assert(html.includes('alpha-squad'), 'Detail panel shows squad name');
})();

(function testNoSquadWhenAbsent() {
    const html = getDetailHtml({
        id: 'rover-03', name: 'Rover Gamma', type: 'rover',
        alliance: 'friendly', position: { x: 10, y: 20 },
        health: 100, maxHealth: 100,
    });
    assert(!html.includes('SQUAD'), 'Detail panel hides SQUAD when no squadId');
})();

// ============================================================
// 4. Detail panel still shows all existing fields
// ============================================================

console.log('\n--- Existing fields intact ---');

(function testDetailStillShowsType() {
    const html = getDetailHtml({
        id: 'rover-04', name: 'Rover Delta', type: 'rover',
        alliance: 'friendly', position: { x: 0, y: 0 },
        health: 100, maxHealth: 100,
    });
    assert(html.includes('TYPE'), 'Detail panel still shows TYPE');
    assert(html.includes('ALLIANCE'), 'Detail panel still shows ALLIANCE');
    assert(html.includes('HEALTH'), 'Detail panel still shows HEALTH');
    assert(html.includes('HEADING'), 'Detail panel still shows HEADING');
    assert(html.includes('POSITION'), 'Detail panel still shows POSITION');
})();

(function testDetailShowsBattery() {
    const html = getDetailHtml({
        id: 'drone-02', name: 'Drone-2', type: 'drone',
        alliance: 'friendly', position: { x: 0, y: 0 },
        health: 60, maxHealth: 60, battery: 85,
    });
    assert(html.includes('BATTERY'), 'Detail panel still shows BATTERY');
    assert(html.includes('85'), 'Detail panel shows battery value');
})();

// ============================================================
// 5. Command input placeholder text
// ============================================================

console.log('\n--- Command input styling ---');

(function testInputHasPlaceholder() {
    const html = getDetailHtml({
        id: 'rover-05', name: 'Rover Echo', type: 'rover',
        alliance: 'friendly', position: { x: 0, y: 0 },
        health: 100, maxHealth: 100,
    });
    assert(html.includes('Lua command'), 'Command input has Lua command placeholder');
})();

(function testSendButtonText() {
    const html = getDetailHtml({
        id: 'rover-06', name: 'Rover Foxtrot', type: 'rover',
        alliance: 'friendly', position: { x: 0, y: 0 },
        health: 100, maxHealth: 100,
    });
    assert(html.includes('>SEND<'), 'Send button shows SEND text');
})();

// ============================================================
// Summary
// ============================================================

console.log('\n' + '='.repeat(40));
console.log(`Results: ${passed} passed, ${failed} failed`);
console.log('='.repeat(40));
process.exit(failed > 0 ? 1 : 0);
