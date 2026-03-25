// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
/**
 * TRITIUM-SC Target Timeline Panel tests
 * Tests TimelinePanelDef structure, DOM creation, filter options,
 * event type config, helper functions, mount wiring, and unmount.
 * Run: node tests/js/test_timeline_panel.js
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
            if (bindMatch) {
                const mock = createMockElement(bindMatch[1] === 'filter' ? 'select' : 'div');
                mock._bindName = bindMatch[1];
                if (bindMatch[1] === 'filter') mock.value = 'all';
                return mock;
            }
            const actionMatch = sel.match(/\[data-action="([^"]+)"\]/);
            if (actionMatch) { const mock = createMockElement('button'); mock._actionName = actionMatch[1]; return mock; }
            return null;
        },
        querySelectorAll(sel) { return []; },
        closest(sel) { return null; },
        _eventListeners: eventListeners, _classList: classList,
    };
    return el;
}

// Mock AbortController
class MockAbortController {
    constructor() { this.signal = { aborted: false }; }
    abort() { this.signal.aborted = true; }
}

const sandbox = {
    Math, Date, console, Map, Set, Array, Object, Number, String, Boolean,
    Infinity, NaN, undefined, parseInt, parseFloat, isNaN, isFinite, JSON,
    Promise, setTimeout, clearTimeout, setInterval, clearInterval, Error,
    AbortController: MockAbortController,
    document: { createElement: createMockElement, getElementById: () => null, querySelector: () => null, addEventListener() {}, removeEventListener() {} },
    window: {},
    fetch: () => Promise.resolve({ ok: true, json: () => Promise.resolve({ events: [], target: {} }) }),
    performance: { now: () => Date.now() },
    encodeURIComponent: encodeURIComponent,
};

const ctx = vm.createContext(sandbox);

// Load dependencies
vm.runInContext(fs.readFileSync(__dirname + '/../../../tritium-lib/web/events.js', 'utf8').replace(/^export\s+/gm, '').replace(/^import\s+.*$/gm, ''), ctx);
vm.runInContext(fs.readFileSync(__dirname + '/../../src/frontend/js/command/store.js', 'utf8').replace(/^export\s+/gm, '').replace(/^import\s+.*$/gm, ''), ctx);
vm.runInContext(fs.readFileSync(__dirname + '/../../src/frontend/js/command/panel-utils.js', 'utf8').replace(/^export\s+/gm, '').replace(/^import\s+.*$/gm, ''), ctx);

// Load timeline panel
const tlCode = fs.readFileSync(__dirname + '/../../src/frontend/js/command/panels/timeline.js', 'utf8');
vm.runInContext(tlCode.replace(/^export\s+const\s+/gm, 'var ').replace(/^export\s+/gm, '').replace(/^import\s+.*$/gm, ''), ctx);

const TimelinePanelDef = ctx.TimelinePanelDef;

// ============================================================
// 1. Structure
// ============================================================
console.log('\n--- TimelinePanelDef structure ---');

(function() { assert(TimelinePanelDef.id === 'timeline', 'id is "timeline"'); })();
(function() { assert(TimelinePanelDef.title === 'TARGET TIMELINE', 'title is "TARGET TIMELINE"'); })();
(function() { assert(typeof TimelinePanelDef.create === 'function', 'create is a function'); })();
(function() { assert(typeof TimelinePanelDef.mount === 'function', 'mount is a function'); })();
(function() { assert(typeof TimelinePanelDef.unmount === 'function', 'unmount is a function'); })();
(function() { assert(TimelinePanelDef.defaultSize.w === 340, 'defaultSize.w is 340'); })();
(function() { assert(TimelinePanelDef.defaultSize.h === 500, 'defaultSize.h is 500'); })();

// ============================================================
// 2. create() DOM
// ============================================================
console.log('\n--- create() DOM ---');

(function() { assert(TimelinePanelDef.create({}).className === 'timeline-panel-inner', 'className is timeline-panel-inner'); })();
(function() { const html = TimelinePanelDef.create({}).innerHTML; assert(html.includes('data-bind="filter"'), 'Has filter select'); })();
(function() { const html = TimelinePanelDef.create({}).innerHTML; assert(html.includes('data-bind="target-label"'), 'Has target label'); })();
(function() { const html = TimelinePanelDef.create({}).innerHTML; assert(html.includes('data-bind="list"'), 'Has event list'); })();
(function() { const html = TimelinePanelDef.create({}).innerHTML; assert(html.includes('data-bind="status"'), 'Has status bar'); })();
(function() { const html = TimelinePanelDef.create({}).innerHTML; assert(html.includes('data-action="refresh"'), 'Has REFRESH button'); })();
(function() { const html = TimelinePanelDef.create({}).innerHTML; assert(html.includes('Select a target to view timeline'), 'Has empty state'); })();
(function() { const html = TimelinePanelDef.create({}).innerHTML; assert(html.includes('0 events'), 'Status defaults to 0 events'); })();

// ============================================================
// 3. Filter options
// ============================================================
console.log('\n--- Filter options ---');

(function() { const html = TimelinePanelDef.create({}).innerHTML; assert(html.includes('value="all"'), 'Has ALL filter'); })();
(function() { const html = TimelinePanelDef.create({}).innerHTML; assert(html.includes('value="ble"'), 'Has BLE filter'); })();
(function() { const html = TimelinePanelDef.create({}).innerHTML; assert(html.includes('value="camera"'), 'Has CAMERA filter'); })();
(function() { const html = TimelinePanelDef.create({}).innerHTML; assert(html.includes('value="geofence"'), 'Has GEOFENCE filter'); })();
(function() { const html = TimelinePanelDef.create({}).innerHTML; assert(html.includes('value="enrichment"'), 'Has ENRICHMENT filter'); })();
(function() { const html = TimelinePanelDef.create({}).innerHTML; assert(html.includes('value="correlation"'), 'Has CORRELATION filter'); })();

// ============================================================
// 4. Accessibility
// ============================================================
console.log('\n--- Accessibility ---');

(function() { const html = TimelinePanelDef.create({}).innerHTML; assert(html.includes('role="log"'), 'Event list has role=log'); })();
(function() { const html = TimelinePanelDef.create({}).innerHTML; assert(html.includes('aria-label="Target timeline"'), 'Event list has aria-label'); })();

// ============================================================
// 5. EVENT_TYPE_CONFIG constant
// ============================================================
console.log('\n--- EVENT_TYPE_CONFIG ---');

(function() { const cfg = vm.runInContext('EVENT_TYPE_CONFIG', ctx); assert(typeof cfg === 'object' && cfg !== null, 'EVENT_TYPE_CONFIG exists'); })();
(function() { const cfg = vm.runInContext('EVENT_TYPE_CONFIG', ctx); assert(cfg['sighting'] !== undefined, 'Has sighting type'); })();
(function() { const cfg = vm.runInContext('EVENT_TYPE_CONFIG', ctx); assert(cfg['detection'] !== undefined, 'Has detection type'); })();
(function() { const cfg = vm.runInContext('EVENT_TYPE_CONFIG', ctx); assert(cfg['geofence_enter'] !== undefined, 'Has geofence_enter type'); })();
(function() { const cfg = vm.runInContext('EVENT_TYPE_CONFIG', ctx); assert(cfg['geofence_exit'] !== undefined, 'Has geofence_exit type'); })();
(function() { const cfg = vm.runInContext('EVENT_TYPE_CONFIG', ctx); assert(cfg['enrichment'] !== undefined, 'Has enrichment type'); })();
(function() { const cfg = vm.runInContext('EVENT_TYPE_CONFIG', ctx); assert(cfg['classification'] !== undefined, 'Has classification type'); })();
(function() { const cfg = vm.runInContext('EVENT_TYPE_CONFIG', ctx); assert(cfg['correlation'] !== undefined, 'Has correlation type'); })();
(function() { const cfg = vm.runInContext('EVENT_TYPE_CONFIG', ctx); assert(cfg['sighting'].color === '#00f0ff', 'sighting color is cyan'); })();
(function() { const cfg = vm.runInContext('EVENT_TYPE_CONFIG', ctx); assert(cfg['detection'].color === '#05ffa1', 'detection color is green'); })();
(function() { const cfg = vm.runInContext('EVENT_TYPE_CONFIG', ctx); assert(cfg['geofence_enter'].color === '#ff2a6d', 'geofence color is magenta'); })();
(function() { const cfg = vm.runInContext('EVENT_TYPE_CONFIG', ctx); assert(cfg['enrichment'].color === '#fcee0a', 'enrichment color is yellow'); })();
(function() { const cfg = vm.runInContext('EVENT_TYPE_CONFIG', ctx); assert(cfg['sighting'].category === 'ble', 'sighting category is ble'); })();
(function() { const cfg = vm.runInContext('EVENT_TYPE_CONFIG', ctx); assert(cfg['detection'].category === 'camera', 'detection category is camera'); })();
(function() { const cfg = vm.runInContext('Object.keys(EVENT_TYPE_CONFIG).length', ctx); assert(vm.runInContext('Object.keys(EVENT_TYPE_CONFIG).length', ctx) === 8, 'EVENT_TYPE_CONFIG has 8 entries'); })();

// ============================================================
// 6. FILTER_OPTIONS constant
// ============================================================
console.log('\n--- FILTER_OPTIONS ---');

(function() { const opts = vm.runInContext('FILTER_OPTIONS', ctx); assert(Array.isArray(opts), 'FILTER_OPTIONS is an array'); })();
(function() { const opts = vm.runInContext('FILTER_OPTIONS', ctx); assert(opts.length === 6, 'FILTER_OPTIONS has 6 entries'); })();

// ============================================================
// 7. _formatTimestamp helper
// ============================================================
console.log('\n--- _formatTimestamp ---');

(function() { const fn = vm.runInContext('_formatTimestamp', ctx); assert(fn(0) === '--:--:--', 'Zero timestamp returns --:--:--'); })();
(function() { const fn = vm.runInContext('_formatTimestamp', ctx); assert(fn(null) === '--:--:--', 'Null timestamp returns --:--:--'); })();
(function() { const fn = vm.runInContext('_formatTimestamp', ctx); const result = fn(1700000000); assert(result.match(/^\d{2}:\d{2}:\d{2}$/), 'Valid timestamp formats as HH:MM:SS, got ' + result); })();

// ============================================================
// 8. _formatEventDetail helper
// ============================================================
console.log('\n--- _formatEventDetail ---');

(function() {
    const fn = vm.runInContext('_formatEventDetail', ctx);
    const result = fn({ event_type: 'sighting', data: { x: 5.5, y: 10.2, speed: 1.5 } });
    assert(result.includes('5.5'), 'Sighting detail includes x position');
    assert(result.includes('10.2'), 'Sighting detail includes y position');
    assert(result.includes('1.5'), 'Sighting detail includes speed');
})();

(function() {
    const fn = vm.runInContext('_formatEventDetail', ctx);
    const result = fn({ event_type: 'detection', data: { asset_type: 'person', confidence: 0.85, alliance: 'hostile' } });
    assert(result.includes('person'), 'Detection detail includes asset type');
    assert(result.includes('85%'), 'Detection detail includes confidence percentage');
})();

(function() {
    const fn = vm.runInContext('_formatEventDetail', ctx);
    const result = fn({ event_type: 'geofence_enter', data: { zone_name: 'Perimeter', zone_type: 'restricted' } });
    assert(result.includes('Perimeter'), 'Geofence detail includes zone name');
    assert(result.includes('restricted'), 'Geofence detail includes zone type');
})();

(function() {
    const fn = vm.runInContext('_formatEventDetail', ctx);
    const result = fn({ event_type: 'enrichment', data: { provider: 'oui', summary: 'Apple Inc' } });
    assert(result.includes('oui'), 'Enrichment detail includes provider');
    assert(result.includes('Apple Inc'), 'Enrichment detail includes summary');
})();

(function() {
    const fn = vm.runInContext('_formatEventDetail', ctx);
    const result = fn({ event_type: 'correlation', data: { other_target_id: 'target-42' } });
    assert(result.includes('target-42'), 'Correlation detail includes other target id');
})();

// ============================================================
// 9. mount()
// ============================================================
console.log('\n--- mount() ---');

(function() {
    const bodyEl = createMockElement('div');
    const panel = { def: TimelinePanelDef, w: 340, x: 0, y: 0, manager: { container: createMockElement('div') }, _unsubs: [], _applyTransform() {} };
    panel.manager.container.clientWidth = 1200;
    let threw = false;
    try { TimelinePanelDef.mount(bodyEl, panel); } catch (e) { threw = true; console.error('mount error:', e); }
    assert(!threw, 'mount() does not crash');
})();

(function() {
    const bodyEl = createMockElement('div');
    const panel = { def: TimelinePanelDef, w: 340, x: 0, y: 0, manager: { container: createMockElement('div') }, _unsubs: [], _applyTransform() {} };
    panel.manager.container.clientWidth = 1200;
    TimelinePanelDef.mount(bodyEl, panel);
    assert(panel._unsubs.length >= 2, 'mount() registers at least 2 cleanup handlers, got ' + panel._unsubs.length);
})();

// ============================================================
// 10. unmount()
// ============================================================
console.log('\n--- unmount() ---');

(function() { let threw = false; try { TimelinePanelDef.unmount(createMockElement('div')); } catch (e) { threw = true; } assert(!threw, 'unmount() does not throw'); })();

// ============================================================
// Summary
// ============================================================
console.log('\n' + '='.repeat(40));
console.log(`Results: ${passed} passed, ${failed} failed`);
console.log('='.repeat(40));
process.exit(failed > 0 ? 1 : 0);
