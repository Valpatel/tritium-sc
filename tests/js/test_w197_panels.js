// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
/**
 * TRITIUM-SC Wave 197 Panel tests
 * Tests MovementAnalyticsPanelDef, SimEngineStatusPanelDef, SystemInventoryPanelDef
 * Validates: structure, DOM creation, data-bind elements, mount/unmount lifecycle.
 * Run: node tests/js/test_w197_panels.js
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
        set innerHTML(val) {
            _innerHTML = val;
            el._parsedBinds = {};
            const bindMatches = val.matchAll(/data-bind="([^"]+)"/g);
            for (const m of bindMatches) el._parsedBinds[m[1]] = true;
            el._parsedActions = {};
            const actionMatches = val.matchAll(/data-action="([^"]+)"/g);
            for (const m of actionMatches) el._parsedActions[m[1]] = true;
        },
        get textContent() { return _textContent; },
        set textContent(val) {
            _textContent = String(val);
            _innerHTML = String(val)
                .replace(/&/g, '&amp;')
                .replace(/</g, '&lt;')
                .replace(/>/g, '&gt;');
        },
        style,
        dataset,
        children,
        childNodes: children,
        parentNode: null,
        hidden: false,
        value: '',
        selectedIndex: 0,
        disabled: false,
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
        appendChild(child) {
            children.push(child);
            if (child && typeof child === 'object') child.parentNode = el;
            return child;
        },
        remove() {},
        focus() {},
        addEventListener(evt, fn) {
            if (!eventListeners[evt]) eventListeners[evt] = [];
            eventListeners[evt].push(fn);
        },
        removeEventListener(evt, fn) {
            if (eventListeners[evt]) {
                eventListeners[evt] = eventListeners[evt].filter(f => f !== fn);
            }
        },
        querySelector(sel) {
            const bindMatch = sel.match(/\[data-bind="([^"]+)"\]/);
            if (bindMatch) {
                const mock = createMockElement('div');
                mock._bindName = bindMatch[1];
                return mock;
            }
            const actionMatch = sel.match(/\[data-action="([^"]+)"\]/);
            if (actionMatch) {
                const mock = createMockElement('button');
                mock._actionName = actionMatch[1];
                return mock;
            }
            const classMatch = sel.match(/\.([a-zA-Z0-9_-]+)/);
            if (classMatch) {
                const mock = createMockElement('div');
                mock.className = classMatch[1];
                return mock;
            }
            return null;
        },
        querySelectorAll(sel) { return []; },
        closest(sel) { return null; },
        _eventListeners: eventListeners,
        _classList: classList,
    };
    return el;
}

// Mock fetch that returns appropriate mock data per endpoint
function mockFetch(url) {
    if (typeof url === 'string' && url.includes('/api/analytics/movement')) {
        return Promise.resolve({
            ok: true,
            json: () => Promise.resolve({
                total_targets: 5,
                moving_targets: 3,
                stationary_targets: 2,
                avg_fleet_speed_mps: 2.5,
                max_fleet_speed_mps: 8.1,
                total_fleet_distance_m: 1234.5,
                dominant_direction: 'N',
                per_target: [
                    { target_id: 't1', name: 'Alpha', speed: 3.0, heading: 45, distance: 200, stationary: false, type: 'car' },
                    { target_id: 't2', name: 'Beta', speed: 0, heading: 0, distance: 0, stationary: true, type: 'person' },
                ],
                analysis_window_s: 3600,
            }),
        });
    }
    if (typeof url === 'string' && url.includes('/api/sim/status')) {
        return Promise.resolve({
            ok: true,
            json: () => Promise.resolve({
                status: 'running',
                available: true,
                running: true,
                target_count: 12,
                alliance_counts: { friendly: 4, hostile: 6, neutral: 2 },
                game_state: 'active',
                wave: 3,
                score: 1500,
            }),
        });
    }
    if (typeof url === 'string' && url.includes('/api/system/inventory')) {
        return Promise.resolve({
            ok: true,
            json: () => Promise.resolve({
                panels: { file_count: 125 },
                routers: { file_count: 100, registered_routes: 250 },
                plugins: { directory_count: 26 },
                models: { sqlalchemy: 8 },
                unit_types: 17,
                tests: { file_count: 1840 },
                fleet: { device_count: 2, online_count: 1, mqtt_connected: true },
                intelligence: {
                    correlation_model: { trained: true, accuracy: 0.82, training_count: 150 },
                    training_data: { total_records: 5000 },
                },
                tracker: { target_count: 42, by_source: { simulation: 30, ble: 8, camera: 4 } },
                simulation: { enabled: true, running: true, sim_target_count: 30 },
            }),
        });
    }
    return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
}

const _timers = [];

const sandbox = {
    Math, Date, console, Map, Set, Array, Object, Number, String, Boolean,
    Infinity, NaN, undefined, parseInt, parseFloat, isNaN, isFinite, JSON,
    Promise, setTimeout, clearTimeout,
    setInterval: (fn, ms) => { const id = _timers.length + 1; _timers.push({ fn, ms, id }); return id; },
    clearInterval: (id) => { const idx = _timers.findIndex(t => t.id === id); if (idx >= 0) _timers.splice(idx, 1); },
    Error, RegExp, Symbol,
    document: {
        createElement: createMockElement,
        getElementById: () => null,
        querySelector: () => null,
        addEventListener() {},
        removeEventListener() {},
    },
    window: {},
    fetch: mockFetch,
    performance: { now: () => Date.now() },
    confirm: () => true,
};

const ctx = vm.createContext(sandbox);

// Load events.js (EventBus)
const eventsCode = fs.readFileSync(__dirname + '/../../../tritium-lib/web/events.js', 'utf8');
const eventsPlain = eventsCode.replace(/^export\s+/gm, '').replace(/^import\s+.*$/gm, '');
vm.runInContext(eventsPlain, ctx);

// Load utils.js (_esc, _timeAgo)
const utilsCode = fs.readFileSync(__dirname + '/../../../tritium-lib/web/utils.js', 'utf8');
const utilsPlain = utilsCode.replace(/^export\s+/gm, '').replace(/^import\s+.*$/gm, '');
vm.runInContext(utilsPlain, ctx);

// ============================================================
// Load panels
// ============================================================

function loadPanel(filename, varName) {
    const code = fs.readFileSync(__dirname + '/../../src/frontend/js/command/panels/' + filename, 'utf8');
    const plain = code
        .replace(/^export\s+const\s+/gm, 'var ')
        .replace(/^export\s+/gm, '')
        .replace(/^import\s+.*$/gm, '');
    // Wrap in IIFE to avoid const/let collisions between panels sharing a context
    vm.runInContext(`(function() { ${plain}\n  globalThis.${varName} = ${varName};\n})();`, ctx);
    return ctx[varName];
}

const MovementAnalyticsPanelDef = loadPanel('movement-analytics.js', 'MovementAnalyticsPanelDef');
const SimEngineStatusPanelDef = loadPanel('sim-engine-status.js', 'SimEngineStatusPanelDef');
const SystemInventoryPanelDef = loadPanel('system-inventory.js', 'SystemInventoryPanelDef');

// ============================================================
// Test: MovementAnalyticsPanelDef
// ============================================================

console.log('\n--- MovementAnalyticsPanelDef structure ---');

(function testMvHasId() {
    assert(MovementAnalyticsPanelDef.id === 'movement-analytics', 'MovementAnalyticsPanelDef.id is "movement-analytics"');
})();

(function testMvHasTitle() {
    assert(MovementAnalyticsPanelDef.title === 'MOVEMENT ANALYTICS', 'MovementAnalyticsPanelDef.title is "MOVEMENT ANALYTICS"');
})();

(function testMvHasCreate() {
    assert(typeof MovementAnalyticsPanelDef.create === 'function', 'create is a function');
})();

(function testMvHasMount() {
    assert(typeof MovementAnalyticsPanelDef.mount === 'function', 'mount is a function');
})();

(function testMvHasUnmount() {
    assert(typeof MovementAnalyticsPanelDef.unmount === 'function', 'unmount is a function');
})();

(function testMvHasDefaultPos() {
    assert(MovementAnalyticsPanelDef.defaultPosition !== undefined, 'has defaultPosition');
    assert(typeof MovementAnalyticsPanelDef.defaultPosition.x === 'number', 'defaultPosition.x is number');
})();

(function testMvHasDefaultSize() {
    assert(MovementAnalyticsPanelDef.defaultSize !== undefined, 'has defaultSize');
    assert(MovementAnalyticsPanelDef.defaultSize.w > 0, 'defaultSize.w > 0');
    assert(MovementAnalyticsPanelDef.defaultSize.h > 0, 'defaultSize.h > 0');
})();

console.log('\n--- MovementAnalyticsPanelDef DOM creation ---');

(function testMvCreate() {
    const panel = {};
    const el = MovementAnalyticsPanelDef.create(panel);
    assert(el !== null, 'create returns an element');
    assert(el.innerHTML.includes('data-bind="total-targets"'), 'has total-targets bind');
    assert(el.innerHTML.includes('data-bind="moving-targets"'), 'has moving-targets bind');
    assert(el.innerHTML.includes('data-bind="avg-speed"'), 'has avg-speed bind');
    assert(el.innerHTML.includes('data-bind="max-speed"'), 'has max-speed bind');
    assert(el.innerHTML.includes('data-bind="compass"'), 'has compass bind');
    assert(el.innerHTML.includes('data-bind="target-table"'), 'has target-table bind');
    assert(el.innerHTML.includes('data-bind="window-select"'), 'has window-select bind');
    assert(el.innerHTML.includes('data-action="refresh"'), 'has refresh action');
})();

console.log('\n--- MovementAnalyticsPanelDef mount/unmount ---');

(function testMvMountCreatesTimer() {
    const panel = {};
    const bodyEl = createMockElement('div');
    _timers.length = 0;
    MovementAnalyticsPanelDef.mount(bodyEl, panel);
    assert(panel._mvTimer !== undefined && panel._mvTimer !== null, 'mount sets _mvTimer');
    MovementAnalyticsPanelDef.unmount(bodyEl, panel);
    assert(panel._mvTimer === null, 'unmount clears _mvTimer');
})();

// ============================================================
// Test: SimEngineStatusPanelDef
// ============================================================

console.log('\n--- SimEngineStatusPanelDef structure ---');

(function testSeHasId() {
    assert(SimEngineStatusPanelDef.id === 'sim-engine-status', 'SimEngineStatusPanelDef.id is "sim-engine-status"');
})();

(function testSeHasTitle() {
    assert(SimEngineStatusPanelDef.title === 'SIM ENGINE', 'SimEngineStatusPanelDef.title is "SIM ENGINE"');
})();

(function testSeHasCreate() {
    assert(typeof SimEngineStatusPanelDef.create === 'function', 'create is a function');
})();

(function testSeHasMount() {
    assert(typeof SimEngineStatusPanelDef.mount === 'function', 'mount is a function');
})();

(function testSeHasUnmount() {
    assert(typeof SimEngineStatusPanelDef.unmount === 'function', 'unmount is a function');
})();

(function testSeHasDefaultSize() {
    assert(SimEngineStatusPanelDef.defaultSize.w > 0, 'defaultSize.w > 0');
    assert(SimEngineStatusPanelDef.defaultSize.h > 0, 'defaultSize.h > 0');
})();

console.log('\n--- SimEngineStatusPanelDef DOM creation ---');

(function testSeCreate() {
    const panel = {};
    const el = SimEngineStatusPanelDef.create(panel);
    assert(el !== null, 'create returns an element');
    assert(el.innerHTML.includes('data-bind="status-value"'), 'has status-value bind');
    assert(el.innerHTML.includes('data-bind="target-count"'), 'has target-count bind');
    assert(el.innerHTML.includes('data-bind="game-state"'), 'has game-state bind');
    assert(el.innerHTML.includes('data-bind="game-wave"'), 'has game-wave bind');
    assert(el.innerHTML.includes('data-bind="game-score"'), 'has game-score bind');
    assert(el.innerHTML.includes('data-bind="alliance-chart"'), 'has alliance-chart bind');
    assert(el.innerHTML.includes('data-bind="status-log"'), 'has status-log bind');
    assert(el.innerHTML.includes('data-action="refresh"'), 'has refresh action');
})();

console.log('\n--- SimEngineStatusPanelDef mount/unmount ---');

(function testSeMountCreatesTimer() {
    const panel = {};
    const bodyEl = createMockElement('div');
    _timers.length = 0;
    SimEngineStatusPanelDef.mount(bodyEl, panel);
    assert(panel._seTimer !== undefined && panel._seTimer !== null, 'mount sets _seTimer');
    SimEngineStatusPanelDef.unmount(bodyEl, panel);
    assert(panel._seTimer === null, 'unmount clears _seTimer');
})();

// ============================================================
// Test: SystemInventoryPanelDef
// ============================================================

console.log('\n--- SystemInventoryPanelDef structure ---');

(function testSiHasId() {
    assert(SystemInventoryPanelDef.id === 'system-inventory', 'SystemInventoryPanelDef.id is "system-inventory"');
})();

(function testSiHasTitle() {
    assert(SystemInventoryPanelDef.title === 'SYSTEM INVENTORY', 'SystemInventoryPanelDef.title is "SYSTEM INVENTORY"');
})();

(function testSiHasCreate() {
    assert(typeof SystemInventoryPanelDef.create === 'function', 'create is a function');
})();

(function testSiHasMount() {
    assert(typeof SystemInventoryPanelDef.mount === 'function', 'mount is a function');
})();

(function testSiHasUnmount() {
    assert(typeof SystemInventoryPanelDef.unmount === 'function', 'unmount is a function');
})();

(function testSiHasDefaultSize() {
    assert(SystemInventoryPanelDef.defaultSize.w > 0, 'defaultSize.w > 0');
    assert(SystemInventoryPanelDef.defaultSize.h > 0, 'defaultSize.h > 0');
})();

console.log('\n--- SystemInventoryPanelDef DOM creation ---');

(function testSiCreate() {
    const panel = {};
    const el = SystemInventoryPanelDef.create(panel);
    assert(el !== null, 'create returns an element');
    assert(el.innerHTML.includes('data-bind="counts-grid"'), 'has counts-grid bind');
    assert(el.innerHTML.includes('data-bind="subsystems"'), 'has subsystems bind');
    assert(el.innerHTML.includes('data-bind="intelligence"'), 'has intelligence bind');
    assert(el.innerHTML.includes('data-bind="targets-sources"'), 'has targets-sources bind');
    assert(el.innerHTML.includes('data-action="refresh"'), 'has refresh action');
})();

console.log('\n--- SystemInventoryPanelDef mount/unmount ---');

(function testSiMountCreatesTimer() {
    const panel = {};
    const bodyEl = createMockElement('div');
    _timers.length = 0;
    SystemInventoryPanelDef.mount(bodyEl, panel);
    assert(panel._siTimer !== undefined && panel._siTimer !== null, 'mount sets _siTimer');
    SystemInventoryPanelDef.unmount(bodyEl, panel);
    assert(panel._siTimer === null, 'unmount clears _siTimer');
})();

// ============================================================
// Summary
// ============================================================

console.log(`\n========================================`);
console.log(`  W197 Panel tests: ${passed} passed, ${failed} failed`);
console.log(`========================================\n`);
process.exit(failed > 0 ? 1 : 0);
