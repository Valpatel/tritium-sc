// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
/**
 * TRITIUM-SC Zones Panel tests
 * Tests ZonesPanelDef structure, DOM creation, toolbar, zone list,
 * detail area, accessibility, and mount wiring.
 * Run: node tests/js/test_zones_panel.js
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
    fetch: () => Promise.resolve({ ok: true, json: () => Promise.resolve([]) }),
    performance: { now: () => Date.now() },
};

const ctx = vm.createContext(sandbox);

vm.runInContext(fs.readFileSync(__dirname + '/../../frontend/js/command/events.js', 'utf8').replace(/^export\s+/gm, '').replace(/^import\s+.*$/gm, ''), ctx);
vm.runInContext(fs.readFileSync(__dirname + '/../../frontend/js/command/store.js', 'utf8').replace(/^export\s+/gm, '').replace(/^import\s+.*$/gm, ''), ctx);

const zoneCode = fs.readFileSync(__dirname + '/../../frontend/js/command/panels/zones.js', 'utf8');
vm.runInContext(zoneCode.replace(/^export\s+const\s+/gm, 'var ').replace(/^export\s+/gm, '').replace(/^import\s+.*$/gm, ''), ctx);

const ZonesPanelDef = ctx.ZonesPanelDef;

// ============================================================
// 1. Structure
// ============================================================
console.log('\n--- ZonesPanelDef structure ---');

(function() { assert(ZonesPanelDef.id === 'zones', 'id is "zones"'); })();
(function() { assert(ZonesPanelDef.title === 'ZONES', 'title is "ZONES"'); })();
(function() { assert(typeof ZonesPanelDef.create === 'function', 'create is a function'); })();
(function() { assert(typeof ZonesPanelDef.mount === 'function', 'mount is a function'); })();
(function() { assert(typeof ZonesPanelDef.unmount === 'function', 'unmount is a function'); })();
(function() { assert(ZonesPanelDef.defaultPosition.x === 8, 'defaultPosition.x is 8'); })();
(function() { assert(ZonesPanelDef.defaultPosition.y === 8, 'defaultPosition.y is 8'); })();
(function() { assert(ZonesPanelDef.defaultSize.w === 280, 'defaultSize.w is 280'); })();
(function() { assert(ZonesPanelDef.defaultSize.h === 340, 'defaultSize.h is 340'); })();

// ============================================================
// 2. create() DOM
// ============================================================
console.log('\n--- create() DOM ---');

(function() { assert(ZonesPanelDef.create({}).className === 'zones-panel-inner', 'className correct'); })();

// ============================================================
// 3. Toolbar
// ============================================================
console.log('\n--- Toolbar ---');

(function() { const html = ZonesPanelDef.create({}).innerHTML; assert(html.includes('data-action="refresh"'), 'Has REFRESH button'); })();
(function() { const html = ZonesPanelDef.create({}).innerHTML; assert(html.includes('data-action="create-zone"'), 'Has NEW ZONE button'); })();
(function() { const html = ZonesPanelDef.create({}).innerHTML; assert(html.includes('REFRESH'), 'REFRESH label'); })();
(function() { const html = ZonesPanelDef.create({}).innerHTML; assert(html.includes('+ NEW ZONE'), 'NEW ZONE label'); })();
(function() { const html = ZonesPanelDef.create({}).innerHTML; assert(html.includes('panel-action-btn-primary'), 'REFRESH is primary'); })();

// ============================================================
// 4. Zone list
// ============================================================
console.log('\n--- Zone list ---');

(function() { const html = ZonesPanelDef.create({}).innerHTML; assert(html.includes('data-bind="zone-list"'), 'Has zone list'); })();
(function() { const html = ZonesPanelDef.create({}).innerHTML; assert(html.includes('Loading zones...'), 'Has loading state'); })();
(function() { const html = ZonesPanelDef.create({}).innerHTML; assert(html.includes('zone-toolbar'), 'Has zone-toolbar class'); })();

// ============================================================
// 5. Detail area
// ============================================================
console.log('\n--- Detail area ---');

(function() { const html = ZonesPanelDef.create({}).innerHTML; assert(html.includes('data-bind="zone-detail"'), 'Has zone detail area'); })();
(function() { const html = ZonesPanelDef.create({}).innerHTML; assert(html.includes('display:none'), 'Detail is hidden by default'); })();

// ============================================================
// 6. Accessibility
// ============================================================
console.log('\n--- Accessibility ---');

(function() { const html = ZonesPanelDef.create({}).innerHTML; assert(html.includes('role="listbox"'), 'Zone list has role=listbox'); })();
(function() { const html = ZonesPanelDef.create({}).innerHTML; assert(html.includes('aria-label="Security zones"'), 'Zone list has aria-label'); })();

// ============================================================
// 7. mount()
// ============================================================
console.log('\n--- mount() ---');

(function() {
    let fetchCalled = false;
    const origFetch = ctx.fetch;
    ctx.fetch = (url) => { if (typeof url === 'string' && url.includes('/api/zones')) fetchCalled = true; return Promise.resolve({ ok: true, json: () => Promise.resolve([]) }); };
    const bodyEl = createMockElement('div');
    const panel = { def: ZonesPanelDef, _unsubs: [] };
    ZonesPanelDef.mount(bodyEl, panel);
    assert(fetchCalled, 'mount() fetches /api/zones');
    ctx.fetch = origFetch;
})();

(function() {
    const bodyEl = createMockElement('div');
    const panel = { def: ZonesPanelDef, _unsubs: [] };
    ZonesPanelDef.mount(bodyEl, panel);
    // At least: refresh interval cleanup
    assert(panel._unsubs.length >= 1, 'mount() registers at least 1 cleanup fn, got ' + panel._unsubs.length);
})();

(function() {
    const bodyEl = createMockElement('div');
    const panel = { def: ZonesPanelDef, _unsubs: [] };
    let threw = false;
    try { ZonesPanelDef.mount(bodyEl, panel); } catch (e) { threw = true; }
    assert(!threw, 'mount() does not crash');
})();

// ============================================================
// 8. unmount()
// ============================================================
console.log('\n--- unmount() ---');

(function() { let threw = false; try { ZonesPanelDef.unmount(createMockElement('div')); } catch (e) { threw = true; } assert(!threw, 'unmount() does not throw'); })();

// ============================================================
// Summary
// ============================================================
console.log('\n' + '='.repeat(40));
console.log(`Results: ${passed} passed, ${failed} failed`);
console.log('='.repeat(40));
process.exit(failed > 0 ? 1 : 0);
