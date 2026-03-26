// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
/**
 * TRITIUM-SC Zone Manager Panel tests
 * Tests ZoneManagerPanelDef structure, DOM creation, toolbar, zone list,
 * edit form, activity tab, summary counters, accessibility, and mount wiring.
 * Run: node tests/js/test_zone_manager_panel.js
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
        style, dataset, children, childNodes: children, parentNode: null, hidden: false, value: '', disabled: false, checked: false,
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
            if (sel.includes('.zone-mgr-tab')) { return createMockElement('button'); }
            if (sel.includes('select')) { const mock = createMockElement('select'); mock.value = ''; return mock; }
            if (sel.includes('input[type="checkbox"]')) { const mock = createMockElement('input'); mock.checked = false; return mock; }
            if (sel.includes('input')) { const mock = createMockElement('input'); mock.value = ''; return mock; }
            return null;
        },
        querySelectorAll(sel) {
            if (sel.includes('.zone-mgr-tab')) return [createMockElement('button'), createMockElement('button')];
            return [];
        },
        closest(sel) { return null; },
        _eventListeners: eventListeners, _classList: classList,
    };
    return el;
}

const sandbox = {
    Math, Date, console, Map, Set, Array, Object, Number, String, Boolean,
    Infinity, NaN, undefined, parseInt, parseFloat, isNaN, isFinite, JSON,
    Promise, setTimeout, clearTimeout, setInterval, clearInterval, Error,
    encodeURIComponent,
    document: { createElement: createMockElement, getElementById: () => null, querySelector: () => null, addEventListener() {}, removeEventListener() {} },
    window: {},
    fetch: () => Promise.resolve({ ok: true, json: () => Promise.resolve([]) }),
    performance: { now: () => Date.now() },
};

const ctx = vm.createContext(sandbox);

vm.runInContext(fs.readFileSync(__dirname + '/../../../tritium-lib/web/events.js', 'utf8').replace(/^export\s+/gm, '').replace(/^import\s+.*$/gm, ''), ctx);

const panelCode = fs.readFileSync(__dirname + '/../../src/frontend/js/command/panels/zone-manager-panel.js', 'utf8');
vm.runInContext(panelCode.replace(/^export\s+const\s+/gm, 'var ').replace(/^export\s+/gm, '').replace(/^import\s+.*$/gm, ''), ctx);

const ZoneManagerPanelDef = ctx.ZoneManagerPanelDef;

// ============================================================
// 1. Structure
// ============================================================
console.log('\n--- ZoneManagerPanelDef structure ---');

(function() { assert(ZoneManagerPanelDef.id === 'zone-manager', 'id is "zone-manager"'); })();
(function() { assert(ZoneManagerPanelDef.title === 'ZONE MANAGER', 'title is "ZONE MANAGER"'); })();
(function() { assert(typeof ZoneManagerPanelDef.create === 'function', 'create is a function'); })();
(function() { assert(typeof ZoneManagerPanelDef.mount === 'function', 'mount is a function'); })();
(function() { assert(typeof ZoneManagerPanelDef.unmount === 'function', 'unmount is a function'); })();
(function() { assert(ZoneManagerPanelDef.defaultPosition.x === 8, 'defaultPosition.x is 8'); })();
(function() { assert(ZoneManagerPanelDef.defaultPosition.y === 120, 'defaultPosition.y is 120'); })();
(function() { assert(ZoneManagerPanelDef.defaultSize.w === 340, 'defaultSize.w is 340'); })();
(function() { assert(ZoneManagerPanelDef.defaultSize.h === 520, 'defaultSize.h is 520'); })();

// ============================================================
// 2. create() DOM
// ============================================================
console.log('\n--- create() DOM ---');

(function() { assert(ZoneManagerPanelDef.create({}).className === 'zone-manager-panel-inner', 'className correct'); })();

// ============================================================
// 3. Toolbar
// ============================================================
console.log('\n--- Toolbar ---');

(function() { const html = ZoneManagerPanelDef.create({}).innerHTML; assert(html.includes('data-action="refresh"'), 'Has REFRESH button'); })();
(function() { const html = ZoneManagerPanelDef.create({}).innerHTML; assert(html.includes('data-action="draw-zone"'), 'Has DRAW ZONE button'); })();
(function() { const html = ZoneManagerPanelDef.create({}).innerHTML; assert(html.includes('REFRESH'), 'REFRESH label'); })();
(function() { const html = ZoneManagerPanelDef.create({}).innerHTML; assert(html.includes('+ DRAW ZONE'), 'DRAW ZONE label'); })();
(function() { const html = ZoneManagerPanelDef.create({}).innerHTML; assert(html.includes('panel-action-btn-primary'), 'REFRESH is primary'); })();

// ============================================================
// 4. Tab bar
// ============================================================
console.log('\n--- Tab bar ---');

(function() { const html = ZoneManagerPanelDef.create({}).innerHTML; assert(html.includes('data-tab="zones"'), 'Has zones tab'); })();
(function() { const html = ZoneManagerPanelDef.create({}).innerHTML; assert(html.includes('data-tab="activity"'), 'Has activity tab'); })();
(function() { const html = ZoneManagerPanelDef.create({}).innerHTML; assert(html.includes('zone-mgr-tab'), 'Has tab class'); })();

// ============================================================
// 5. Summary counters
// ============================================================
console.log('\n--- Summary counters ---');

(function() { const html = ZoneManagerPanelDef.create({}).innerHTML; assert(html.includes('data-bind="count-restricted"'), 'Has restricted counter'); })();
(function() { const html = ZoneManagerPanelDef.create({}).innerHTML; assert(html.includes('data-bind="count-monitored"'), 'Has monitored counter'); })();
(function() { const html = ZoneManagerPanelDef.create({}).innerHTML; assert(html.includes('data-bind="count-safe"'), 'Has safe counter'); })();
(function() { const html = ZoneManagerPanelDef.create({}).innerHTML; assert(html.includes('RESTRICTED'), 'Shows RESTRICTED label'); })();
(function() { const html = ZoneManagerPanelDef.create({}).innerHTML; assert(html.includes('MONITORED'), 'Shows MONITORED label'); })();
(function() { const html = ZoneManagerPanelDef.create({}).innerHTML; assert(html.includes('PUBLIC'), 'Shows PUBLIC label'); })();

// ============================================================
// 6. Zone list
// ============================================================
console.log('\n--- Zone list ---');

(function() { const html = ZoneManagerPanelDef.create({}).innerHTML; assert(html.includes('data-bind="zone-list"'), 'Has zone list'); })();
(function() { const html = ZoneManagerPanelDef.create({}).innerHTML; assert(html.includes('Loading zones...'), 'Has loading state'); })();
(function() { const html = ZoneManagerPanelDef.create({}).innerHTML; assert(html.includes('zone-toolbar'), 'Has zone-toolbar class'); })();

// ============================================================
// 7. Activity section
// ============================================================
console.log('\n--- Activity section ---');

(function() { const html = ZoneManagerPanelDef.create({}).innerHTML; assert(html.includes('data-bind="activity-list"'), 'Has activity list'); })();
(function() { const html = ZoneManagerPanelDef.create({}).innerHTML; assert(html.includes('data-bind="event-items"'), 'Has event items list'); })();
(function() { const html = ZoneManagerPanelDef.create({}).innerHTML; assert(html.includes('data-bind="event-type-filter"'), 'Has event type filter'); })();

// ============================================================
// 8. Edit form
// ============================================================
console.log('\n--- Edit form ---');

(function() { const html = ZoneManagerPanelDef.create({}).innerHTML; assert(html.includes('data-bind="edit-form"'), 'Has edit form'); })();
(function() { const html = ZoneManagerPanelDef.create({}).innerHTML; assert(html.includes('data-bind="edit-name"'), 'Has name input'); })();
(function() { const html = ZoneManagerPanelDef.create({}).innerHTML; assert(html.includes('data-bind="edit-type"'), 'Has type select'); })();
(function() { const html = ZoneManagerPanelDef.create({}).innerHTML; assert(html.includes('data-bind="edit-enter"'), 'Has enter alert checkbox'); })();
(function() { const html = ZoneManagerPanelDef.create({}).innerHTML; assert(html.includes('data-bind="edit-exit"'), 'Has exit alert checkbox'); })();
(function() { const html = ZoneManagerPanelDef.create({}).innerHTML; assert(html.includes('data-action="save-edit"'), 'Has SAVE button'); })();
(function() { const html = ZoneManagerPanelDef.create({}).innerHTML; assert(html.includes('data-action="cancel-edit"'), 'Has CANCEL button'); })();
(function() { const html = ZoneManagerPanelDef.create({}).innerHTML; assert(html.includes('EDIT ZONE'), 'Has EDIT ZONE label'); })();

// ============================================================
// 9. Accessibility
// ============================================================
console.log('\n--- Accessibility ---');

(function() { const html = ZoneManagerPanelDef.create({}).innerHTML; assert(html.includes('role="listbox"'), 'Zone list has role=listbox'); })();
(function() { const html = ZoneManagerPanelDef.create({}).innerHTML; assert(html.includes('aria-label="Geofence zones"'), 'Zone list has aria-label'); })();
(function() { const html = ZoneManagerPanelDef.create({}).innerHTML; assert(html.includes('role="list"'), 'Event list has role=list'); })();
(function() { const html = ZoneManagerPanelDef.create({}).innerHTML; assert(html.includes('aria-label="Zone activity timeline"'), 'Event list has aria-label'); })();

// ============================================================
// 10. Color codes
// ============================================================
console.log('\n--- Color codes ---');

(function() { const src = panelCode; assert(src.includes("restricted: '#ff2a6d'"), 'Restricted is magenta/red'); })();
(function() { const src = panelCode; assert(src.includes("monitored: '#00f0ff'"), 'Monitored is cyan'); })();
(function() { const src = panelCode; assert(src.includes("safe: '#05ffa1'"), 'Safe/public is green'); })();

// ============================================================
// 11. API usage
// ============================================================
console.log('\n--- API usage ---');

(function() { const src = panelCode; assert(src.includes('/api/geofence/zones'), 'Uses /api/geofence/zones'); })();
(function() { const src = panelCode; assert(src.includes('/api/geofence/events'), 'Uses /api/geofence/events'); })();
(function() { const src = panelCode; assert(src.includes('/api/geofence/occupancy'), 'Uses /api/geofence/occupancy'); })();
(function() { const src = panelCode; assert(src.includes("method: 'PUT'"), 'Edit uses PUT method'); })();
(function() { const src = panelCode; assert(src.includes("method: 'DELETE'"), 'Delete uses DELETE method'); })();
(function() { const src = panelCode; assert(src.includes("method: 'POST'"), 'Create uses POST method'); })();

// ============================================================
// 12. EventBus events
// ============================================================
console.log('\n--- EventBus events ---');

(function() { const src = panelCode; assert(src.includes("geofence:drawZone"), 'Emits geofence:drawZone for drawing'); })();
(function() { const src = panelCode; assert(src.includes("zone:selected"), 'Emits zone:selected on click'); })();
(function() { const src = panelCode; assert(src.includes("geofence:zoneDrawn"), 'Listens for geofence:zoneDrawn'); })();
(function() { const src = panelCode; assert(src.includes("geofence:drawEnd"), 'Listens for geofence:drawEnd'); })();
(function() { const src = panelCode; assert(src.includes("geofence:enter"), 'Listens for geofence:enter'); })();
(function() { const src = panelCode; assert(src.includes("geofence:exit"), 'Listens for geofence:exit'); })();
(function() { const src = panelCode; assert(src.includes("toast:show"), 'Shows toast notifications'); })();

// ============================================================
// 13. mount()
// ============================================================
console.log('\n--- mount() ---');

(function() {
    let fetchCalled = false;
    const origFetch = ctx.fetch;
    ctx.fetch = (url) => {
        if (typeof url === 'string' && url.includes('/api/geofence/zones')) fetchCalled = true;
        return Promise.resolve({ ok: true, json: () => Promise.resolve([]) });
    };
    const bodyEl = createMockElement('div');
    const panel = { def: ZoneManagerPanelDef, _unsubs: [], minimize() {}, restore() {} };
    ZoneManagerPanelDef.mount(bodyEl, panel);
    assert(fetchCalled, 'mount() fetches /api/geofence/zones');
    ctx.fetch = origFetch;
})();

(function() {
    const bodyEl = createMockElement('div');
    const panel = { def: ZoneManagerPanelDef, _unsubs: [], minimize() {}, restore() {} };
    ZoneManagerPanelDef.mount(bodyEl, panel);
    // At least: refresh interval cleanup + drawEnd + zoneDrawn + enter + exit = 5
    assert(panel._unsubs.length >= 5, 'mount() registers at least 5 cleanup fns, got ' + panel._unsubs.length);
})();

(function() {
    const bodyEl = createMockElement('div');
    const panel = { def: ZoneManagerPanelDef, _unsubs: [], minimize() {}, restore() {} };
    let threw = false;
    try { ZoneManagerPanelDef.mount(bodyEl, panel); } catch (e) { threw = true; console.error(e); }
    assert(!threw, 'mount() does not crash');
})();

// ============================================================
// 14. unmount()
// ============================================================
console.log('\n--- unmount() ---');

(function() { let threw = false; try { ZoneManagerPanelDef.unmount(createMockElement('div')); } catch (e) { threw = true; } assert(!threw, 'unmount() does not throw'); })();

// ============================================================
// 15. Zone type constants
// ============================================================
console.log('\n--- Zone type constants ---');

(function() { const src = panelCode; assert(src.includes("'restricted', 'monitored', 'safe'"), 'VALID_TYPES has 3 zone types'); })();

// ============================================================
// Summary
// ============================================================
console.log('\n' + '='.repeat(40));
console.log(`Results: ${passed} passed, ${failed} failed`);
console.log('='.repeat(40));
process.exit(failed > 0 ? 1 : 0);
