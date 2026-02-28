// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
/**
 * TRITIUM-SC Patrol Routes Panel tests
 * Tests PatrolPanelDef structure, DOM creation, summary, list,
 * action buttons, and mount wiring.
 * Run: node tests/js/test_patrol_panel.js
 */

const fs = require('fs');
const vm = require('vm');

let passed = 0, failed = 0;
function assert(cond, msg) {
    if (!cond) { console.error('FAIL:', msg); failed++; }
    else { console.log('PASS:', msg); passed++; }
}

function createMockElement(tag) {
    const children = [];
    const classList = new Set();
    const eventListeners = {};
    const dataset = {};
    const style = {};
    let _innerHTML = '';
    let _textContent = '';
    const el = {
        tagName: (tag || 'DIV').toUpperCase(), className: '',
        get innerHTML() { return _innerHTML; },
        set innerHTML(val) { _innerHTML = val; },
        get textContent() { return _textContent; },
        set textContent(val) { _textContent = String(val); _innerHTML = String(val).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); },
        style, dataset, children, childNodes: children, parentNode: null, hidden: false, value: '', disabled: false,
        get classList() {
            return { add(cls) { classList.add(cls); }, remove(cls) { classList.delete(cls); }, contains(cls) { return classList.has(cls); },
                toggle(cls, force) { if (force === undefined) { if (classList.has(cls)) classList.delete(cls); else classList.add(cls); } else if (force) classList.add(cls); else classList.delete(cls); } };
        },
        appendChild(child) { children.push(child); if (child && typeof child === 'object') child.parentNode = el; return child; },
        remove() {}, focus() {},
        addEventListener(evt, fn) { if (!eventListeners[evt]) eventListeners[evt] = []; eventListeners[evt].push(fn); },
        removeEventListener(evt, fn) { if (eventListeners[evt]) eventListeners[evt] = eventListeners[evt].filter(f => f !== fn); },
        querySelector(sel) {
            const bindMatch = sel.match(/\[data-bind="([^"]+)"\]/);
            if (bindMatch) { const mock = createMockElement('div'); mock._bindName = bindMatch[1]; return mock; }
            const actionMatch = sel.match(/\[data-action="([^"]+)"\]/);
            if (actionMatch) { const mock = createMockElement('button'); mock._actionName = actionMatch[1]; return mock; }
            return null;
        },
        querySelectorAll(sel) { return []; }, closest(sel) { return null; },
        _eventListeners: eventListeners, _classList: classList,
    };
    return el;
}

const sandbox = {
    Math, Date, console, Map, Set, Array, Object, Number, String, Boolean,
    Infinity, NaN, undefined, parseInt, parseFloat, isNaN, isFinite, JSON,
    Promise, setTimeout, clearTimeout, setInterval, clearInterval, Error,
    document: { createElement: createMockElement, getElementById: () => null, querySelector: () => null, addEventListener() {}, removeEventListener() {} },
    window: {},
    fetch: () => Promise.resolve({ ok: true, json: () => Promise.resolve({}) }),
    performance: { now: () => Date.now() },
};

const ctx = vm.createContext(sandbox);

vm.runInContext(fs.readFileSync(__dirname + '/../../frontend/js/command/events.js', 'utf8').replace(/^export\s+/gm, '').replace(/^import\s+.*$/gm, ''), ctx);
vm.runInContext(fs.readFileSync(__dirname + '/../../frontend/js/command/store.js', 'utf8').replace(/^export\s+/gm, '').replace(/^import\s+.*$/gm, ''), ctx);

const patrolCode = fs.readFileSync(__dirname + '/../../frontend/js/command/panels/patrol.js', 'utf8');
vm.runInContext(patrolCode.replace(/^export\s+const\s+/gm, 'var ').replace(/^export\s+/gm, '').replace(/^import\s+.*$/gm, ''), ctx);

const PatrolPanelDef = ctx.PatrolPanelDef;

// ============================================================
// 1. Structure
// ============================================================
console.log('\n--- PatrolPanelDef structure ---');

(function() { assert(PatrolPanelDef.id === 'patrol', 'id is "patrol"'); })();
(function() { assert(PatrolPanelDef.title === 'PATROL ROUTES', 'title is "PATROL ROUTES"'); })();
(function() { assert(typeof PatrolPanelDef.create === 'function', 'create is a function'); })();
(function() { assert(typeof PatrolPanelDef.mount === 'function', 'mount is a function'); })();
(function() { assert(typeof PatrolPanelDef.unmount === 'function', 'unmount is a function'); })();
(function() { assert(PatrolPanelDef.defaultPosition.x === 8, 'defaultPosition.x is 8'); })();
(function() { assert(PatrolPanelDef.defaultPosition.y === 200, 'defaultPosition.y is 200'); })();
(function() { assert(PatrolPanelDef.defaultSize.w === 280, 'defaultSize.w is 280'); })();
(function() { assert(PatrolPanelDef.defaultSize.h === 320, 'defaultSize.h is 320'); })();

// ============================================================
// 2. create() DOM
// ============================================================
console.log('\n--- create() DOM ---');

(function() { assert(PatrolPanelDef.create({}).className === 'patrol-panel-inner', 'className correct'); })();
(function() { const html = PatrolPanelDef.create({}).innerHTML; assert(html.includes('data-bind="summary"'), 'Has summary area'); })();
(function() { const html = PatrolPanelDef.create({}).innerHTML; assert(html.includes('data-bind="list"'), 'Has list area'); })();
(function() { const html = PatrolPanelDef.create({}).innerHTML; assert(html.includes('Loading...'), 'Has loading state'); })();

// ============================================================
// 3. Action buttons
// ============================================================
console.log('\n--- Action buttons ---');

(function() { const html = PatrolPanelDef.create({}).innerHTML; assert(html.includes('data-action="patrol-all"'), 'Has PATROL ALL button'); })();
(function() { const html = PatrolPanelDef.create({}).innerHTML; assert(html.includes('data-action="recall-all"'), 'Has RECALL ALL button'); })();
(function() { const html = PatrolPanelDef.create({}).innerHTML; assert(html.includes('PATROL ALL'), 'PATROL ALL label'); })();
(function() { const html = PatrolPanelDef.create({}).innerHTML; assert(html.includes('RECALL ALL'), 'RECALL ALL label'); })();

// ============================================================
// 4. Empty state
// ============================================================
console.log('\n--- Empty state ---');

(function() { const html = PatrolPanelDef.create({}).innerHTML; assert(html.includes('No patrol routes'), 'Has empty state text'); })();

// ============================================================
// 5. Layout classes
// ============================================================
console.log('\n--- Layout classes ---');

(function() { const html = PatrolPanelDef.create({}).innerHTML; assert(html.includes('patrol-summary'), 'Has patrol-summary class'); })();
(function() { const html = PatrolPanelDef.create({}).innerHTML; assert(html.includes('patrol-list'), 'Has patrol-list class'); })();
(function() { const html = PatrolPanelDef.create({}).innerHTML; assert(html.includes('patrol-actions'), 'Has patrol-actions class'); })();

// ============================================================
// 6. mount()
// ============================================================
console.log('\n--- mount() ---');

(function() {
    const bodyEl = createMockElement('div');
    const panel = { def: PatrolPanelDef, _unsubs: [] };
    PatrolPanelDef.mount(bodyEl, panel);
    // Subscribes to 'units' and 'game.phase'
    assert(panel._unsubs.length >= 2, 'mount() registers at least 2 subscriptions, got ' + panel._unsubs.length);
})();

(function() {
    const bodyEl = createMockElement('div');
    const panel = { def: PatrolPanelDef, _unsubs: [] };
    let threw = false;
    try { PatrolPanelDef.mount(bodyEl, panel); } catch (e) { threw = true; }
    assert(!threw, 'mount() does not crash');
})();

(function() {
    // Test that mount triggers initial render without crash
    const bodyEl = createMockElement('div');
    const panel = { def: PatrolPanelDef, _unsubs: [] };
    const TritiumStore = vm.runInContext('TritiumStore', ctx);
    // Ensure units map is empty
    TritiumStore.units = new Map();
    let threw = false;
    try { PatrolPanelDef.mount(bodyEl, panel); } catch (e) { threw = true; }
    assert(!threw, 'mount() with empty units does not crash');
})();

// ============================================================
// 7. unmount()
// ============================================================
console.log('\n--- unmount() ---');

(function() { let threw = false; try { PatrolPanelDef.unmount(createMockElement('div')); } catch (e) { threw = true; } assert(!threw, 'unmount() does not throw'); })();

// ============================================================
// Summary
// ============================================================
console.log('\n' + '='.repeat(40));
console.log(`Results: ${passed} passed, ${failed} failed`);
console.log('='.repeat(40));
process.exit(failed > 0 ? 1 : 0);
