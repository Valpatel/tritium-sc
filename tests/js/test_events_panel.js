// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
/**
 * TRITIUM-SC Events Timeline Panel tests
 * Tests EventsPanelDef structure, DOM creation, filter options, event types,
 * constants, and mount wiring.
 * Run: node tests/js/test_events_panel.js
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
        style, dataset, children, childNodes: children, parentNode: null, hidden: false, value: 'all', disabled: false,
        scrollHeight: 100, scrollTop: 0,
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
            if (bindMatch) { const mock = createMockElement(bindMatch[1] === 'filter' ? 'select' : 'div'); mock._bindName = bindMatch[1]; if (bindMatch[1] === 'filter') mock.value = 'all'; return mock; }
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

const evtCode = fs.readFileSync(__dirname + '/../../frontend/js/command/panels/events.js', 'utf8');
vm.runInContext(evtCode.replace(/^export\s+const\s+/gm, 'var ').replace(/^export\s+/gm, '').replace(/^import\s+.*$/gm, ''), ctx);

const EventsPanelDef = ctx.EventsPanelDef;

// ============================================================
// 1. Structure
// ============================================================
console.log('\n--- EventsPanelDef structure ---');

(function() { assert(EventsPanelDef.id === 'events', 'id is "events"'); })();
(function() { assert(EventsPanelDef.title === 'EVENTS TIMELINE', 'title is "EVENTS TIMELINE"'); })();
(function() { assert(typeof EventsPanelDef.create === 'function', 'create is a function'); })();
(function() { assert(typeof EventsPanelDef.mount === 'function', 'mount is a function'); })();
(function() { assert(typeof EventsPanelDef.unmount === 'function', 'unmount is a function'); })();
(function() { assert(EventsPanelDef.defaultSize.w === 300, 'defaultSize.w is 300'); })();
(function() { assert(EventsPanelDef.defaultSize.h === 400, 'defaultSize.h is 400'); })();

// ============================================================
// 2. create() DOM
// ============================================================
console.log('\n--- create() DOM ---');

(function() { assert(EventsPanelDef.create({}).className === 'events-panel-inner', 'className is events-panel-inner'); })();
(function() { const html = EventsPanelDef.create({}).innerHTML; assert(html.includes('data-bind="filter"'), 'Has filter select'); })();
(function() { const html = EventsPanelDef.create({}).innerHTML; assert(html.includes('data-bind="count"'), 'Has event count'); })();
(function() { const html = EventsPanelDef.create({}).innerHTML; assert(html.includes('data-action="clear"'), 'Has CLEAR button'); })();
(function() { const html = EventsPanelDef.create({}).innerHTML; assert(html.includes('data-bind="list"'), 'Has event list'); })();
(function() { const html = EventsPanelDef.create({}).innerHTML; assert(html.includes('Waiting for events...'), 'Has empty state'); })();
(function() { const html = EventsPanelDef.create({}).innerHTML; assert(html.includes('0 events'), 'Count defaults to 0'); })();

// ============================================================
// 3. Filter options
// ============================================================
console.log('\n--- Filter options ---');

(function() { const html = EventsPanelDef.create({}).innerHTML; assert(html.includes('value="all"'), 'Has ALL filter'); })();
(function() { const html = EventsPanelDef.create({}).innerHTML; assert(html.includes('value="combat"'), 'Has COMBAT filter'); })();
(function() { const html = EventsPanelDef.create({}).innerHTML; assert(html.includes('value="game"'), 'Has GAME filter'); })();
(function() { const html = EventsPanelDef.create({}).innerHTML; assert(html.includes('value="amy"'), 'Has AMY filter'); })();
(function() { const html = EventsPanelDef.create({}).innerHTML; assert(html.includes('value="alert"'), 'Has ALERTS filter'); })();
(function() { const html = EventsPanelDef.create({}).innerHTML; assert(html.includes('>ALL<'), 'ALL filter has label'); })();
(function() { const html = EventsPanelDef.create({}).innerHTML; assert(html.includes('>COMBAT<'), 'COMBAT filter has label'); })();
(function() { const html = EventsPanelDef.create({}).innerHTML; assert(html.includes('>GAME<'), 'GAME filter has label'); })();
(function() { const html = EventsPanelDef.create({}).innerHTML; assert(html.includes('>AMY<'), 'AMY filter has label'); })();
(function() { const html = EventsPanelDef.create({}).innerHTML; assert(html.includes('>ALERTS<'), 'ALERTS filter has label'); })();

// ============================================================
// 4. Accessibility
// ============================================================
console.log('\n--- Accessibility ---');

(function() { const html = EventsPanelDef.create({}).innerHTML; assert(html.includes('role="log"'), 'Event list has role=log'); })();
(function() { const html = EventsPanelDef.create({}).innerHTML; assert(html.includes('aria-label="Events timeline"'), 'Event list has aria-label'); })();

// ============================================================
// 5. EVENT_TYPES constant
// ============================================================
console.log('\n--- EVENT_TYPES ---');

(function() { const types = vm.runInContext('EVENT_TYPES', ctx); assert(typeof types === 'object' && types !== null, 'EVENT_TYPES exists'); })();
(function() { const types = vm.runInContext('EVENT_TYPES', ctx); assert(types['alert:new'] !== undefined, 'Has alert:new type'); })();
(function() { const types = vm.runInContext('EVENT_TYPES', ctx); assert(types['game:elimination'] !== undefined, 'Has game:elimination type'); })();
(function() { const types = vm.runInContext('EVENT_TYPES', ctx); assert(types['combat:hit'] !== undefined, 'Has combat:hit type'); })();
(function() { const types = vm.runInContext('EVENT_TYPES', ctx); assert(types['game:wave_start'] !== undefined, 'Has game:wave_start type'); })();
(function() { const types = vm.runInContext('EVENT_TYPES', ctx); assert(types['amy:thought'] !== undefined, 'Has amy:thought type'); })();
(function() { const types = vm.runInContext('EVENT_TYPES', ctx); assert(types['alert:new'].label === 'ALERT', 'alert:new label is ALERT'); })();
(function() { const types = vm.runInContext('EVENT_TYPES', ctx); assert(types['game:elimination'].icon === 'X', 'game:elimination icon is X'); })();
(function() { const types = vm.runInContext('Object.keys(EVENT_TYPES).length', ctx); assert(vm.runInContext('Object.keys(EVENT_TYPES).length', ctx) === 12, 'EVENT_TYPES has 12 entries'); })();

// ============================================================
// 6. FILTER_OPTIONS constant
// ============================================================
console.log('\n--- FILTER_OPTIONS ---');

(function() { const opts = vm.runInContext('FILTER_OPTIONS', ctx); assert(Array.isArray(opts), 'FILTER_OPTIONS is an array'); })();
(function() { const opts = vm.runInContext('FILTER_OPTIONS', ctx); assert(opts.length === 5, 'FILTER_OPTIONS has 5 entries'); })();

// ============================================================
// 7. Event set constants
// ============================================================
console.log('\n--- Event sets ---');

(function() { const s = vm.runInContext('COMBAT_EVENTS', ctx); assert(s instanceof Set, 'COMBAT_EVENTS is a Set'); })();
(function() { const s = vm.runInContext('COMBAT_EVENTS', ctx); assert(s.has('game:elimination'), 'COMBAT_EVENTS has game:elimination'); })();
(function() { const s = vm.runInContext('GAME_EVENTS', ctx); assert(s.has('game:wave_start'), 'GAME_EVENTS has game:wave_start'); })();
(function() { const s = vm.runInContext('AMY_EVENTS', ctx); assert(s.has('amy:thought'), 'AMY_EVENTS has amy:thought'); })();
(function() { const s = vm.runInContext('ALERT_EVENTS', ctx); assert(s.has('alert:new'), 'ALERT_EVENTS has alert:new'); })();

// ============================================================
// 8. mount()
// ============================================================
console.log('\n--- mount() ---');

(function() {
    const bodyEl = createMockElement('div');
    const panel = { def: EventsPanelDef, w: 300, x: 0, y: 0, manager: { container: createMockElement('div') }, _unsubs: [], _applyTransform() {} };
    panel.manager.container.clientWidth = 1200;
    EventsPanelDef.mount(bodyEl, panel);
    // Should subscribe to all 12 event types
    assert(panel._unsubs.length >= 12, 'mount() registers at least 12 event subscriptions, got ' + panel._unsubs.length);
})();

(function() {
    const bodyEl = createMockElement('div');
    const panel = { def: EventsPanelDef, w: 300, x: 0, y: 0, manager: { container: createMockElement('div') }, _unsubs: [], _applyTransform() {} };
    panel.manager.container.clientWidth = 1200;
    let threw = false;
    try { EventsPanelDef.mount(bodyEl, panel); } catch (e) { threw = true; }
    assert(!threw, 'mount() does not crash');
})();

// ============================================================
// 9. unmount()
// ============================================================
console.log('\n--- unmount() ---');

(function() { let threw = false; try { EventsPanelDef.unmount(createMockElement('div')); } catch (e) { threw = true; } assert(!threw, 'unmount() does not throw'); })();

// ============================================================
// Summary
// ============================================================
console.log('\n' + '='.repeat(40));
console.log(`Results: ${passed} passed, ${failed} failed`);
console.log('='.repeat(40));
process.exit(failed > 0 ? 1 : 0);
