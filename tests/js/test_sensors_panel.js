// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
/**
 * TRITIUM-SC Sensor Net Panel tests
 * Tests SensorNetPanelDef structure, DOM creation, event handling,
 * log management, and cleanup.
 * Run: node tests/js/test_sensors_panel.js
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

// Load EventBus
vm.runInContext(fs.readFileSync(__dirname + '/../../src/frontend/js/command/events.js', 'utf8').replace(/^export\s+/gm, '').replace(/^import\s+.*$/gm, ''), ctx);
// Load store
vm.runInContext(fs.readFileSync(__dirname + '/../../src/frontend/js/command/store.js', 'utf8').replace(/^export\s+/gm, '').replace(/^import\s+.*$/gm, ''), ctx);

// Load sensors panel
const sensorCode = fs.readFileSync(__dirname + '/../../src/frontend/js/command/panels/sensors.js', 'utf8');
vm.runInContext(sensorCode.replace(/^export\s+const\s+/gm, 'var ').replace(/^export\s+/gm, '').replace(/^import\s+.*$/gm, ''), ctx);

const SensorNetPanelDef = ctx.SensorNetPanelDef;

// ============================================================
// 1. Structure
// ============================================================
console.log('\n--- SensorNetPanelDef structure ---');

(function() { assert(SensorNetPanelDef !== undefined, 'SensorNetPanelDef is defined'); })();
(function() { assert(SensorNetPanelDef.id === 'sensors', 'id is "sensors"'); })();
(function() { assert(SensorNetPanelDef.title === 'SENSOR NET', 'title is "SENSOR NET"'); })();
(function() { assert(typeof SensorNetPanelDef.create === 'function', 'create is a function'); })();
(function() { assert(typeof SensorNetPanelDef.mount === 'function', 'mount is a function'); })();
(function() { assert(typeof SensorNetPanelDef.unmount === 'function', 'unmount is a function'); })();
(function() { assert(SensorNetPanelDef.defaultSize.w > 0, 'defaultSize.w is positive'); })();
(function() { assert(SensorNetPanelDef.defaultSize.h > 0, 'defaultSize.h is positive'); })();

// ============================================================
// 2. create() DOM
// ============================================================
console.log('\n--- create() DOM ---');

(function() {
    const el = SensorNetPanelDef.create({});
    assert(el.className === 'sensor-panel-inner', 'className is sensor-panel-inner');
})();

(function() {
    const html = SensorNetPanelDef.create({}).innerHTML;
    assert(html.includes('data-bind="active-count"'), 'Has active count display');
})();

(function() {
    const html = SensorNetPanelDef.create({}).innerHTML;
    assert(html.includes('data-bind="log"'), 'Has event log container');
})();

(function() {
    const html = SensorNetPanelDef.create({}).innerHTML;
    assert(html.includes('data-action="clear"'), 'Has CLEAR button');
})();

(function() {
    const html = SensorNetPanelDef.create({}).innerHTML;
    assert(html.includes('Waiting for sensor data'), 'Has empty state message');
})();

(function() {
    const html = SensorNetPanelDef.create({}).innerHTML;
    assert(html.includes('role="log"'), 'Log has role=log for accessibility');
})();

// ============================================================
// 3. mount() subscribes to events
// ============================================================
console.log('\n--- mount() event subscriptions ---');

(function() {
    const bodyEl = createMockElement('div');
    const panel = { def: SensorNetPanelDef, w: 280, x: 0, y: 0, manager: { container: createMockElement('div') }, _unsubs: [], _applyTransform() {} };
    panel.manager.container.clientWidth = 1200;
    let threw = false;
    try { SensorNetPanelDef.mount(bodyEl, panel); } catch (e) { threw = true; console.error(e); }
    assert(!threw, 'mount() does not crash');
})();

(function() {
    const bodyEl = createMockElement('div');
    const panel = { def: SensorNetPanelDef, w: 280, x: 0, y: 0, manager: { container: createMockElement('div') }, _unsubs: [], _applyTransform() {} };
    panel.manager.container.clientWidth = 1200;
    SensorNetPanelDef.mount(bodyEl, panel);
    // Should subscribe to sensor:triggered and sensor:cleared (at minimum 2)
    assert(panel._unsubs.length >= 2, 'mount() registers at least 2 subscriptions, got ' + panel._unsubs.length);
})();

// ============================================================
// 4. sensor:triggered adds entry to log
// ============================================================
console.log('\n--- sensor:triggered event handling ---');

(function() {
    // Clear EventBus handlers
    vm.runInContext('EventBus._handlers = new Map()', ctx);

    const bodyEl = createMockElement('div');
    const panel = { def: SensorNetPanelDef, w: 280, x: 0, y: 0, manager: { container: createMockElement('div') }, _unsubs: [], _applyTransform() {} };
    panel.manager.container.clientWidth = 1200;
    SensorNetPanelDef.mount(bodyEl, panel);

    // Emit a sensor triggered event
    vm.runInContext(`EventBus.emit('sensor:triggered', {
        sensor_id: 'motion-01',
        name: 'Front Door Motion',
        type: 'motion',
        triggered_by: 'hostile-03',
        target_id: 'h-03',
        position: { x: 10, z: 20 },
    })`, ctx);

    // The panel should have stored this event in its internal state
    // We access the helpers via window
    const helpers = sandbox.window.SensorNetHelpers;
    assert(helpers !== undefined, 'SensorNetHelpers exposed on window');
    assert(typeof helpers.getActiveCount === 'function', 'getActiveCount helper exists');
    assert(helpers.getActiveCount() === 1, 'Active sensor count is 1 after trigger');
})();

(function() {
    vm.runInContext('EventBus._handlers = new Map()', ctx);

    const bodyEl = createMockElement('div');
    const panel = { def: SensorNetPanelDef, w: 280, x: 0, y: 0, manager: { container: createMockElement('div') }, _unsubs: [], _applyTransform() {} };
    panel.manager.container.clientWidth = 1200;
    SensorNetPanelDef.mount(bodyEl, panel);

    vm.runInContext(`EventBus.emit('sensor:triggered', {
        sensor_id: 'motion-01',
        name: 'Front Door Motion',
        type: 'motion',
        triggered_by: 'hostile-03',
    })`, ctx);

    const helpers = sandbox.window.SensorNetHelpers;
    assert(helpers.getLogLength() === 1, 'Log has 1 entry after trigger');
})();

(function() {
    vm.runInContext('EventBus._handlers = new Map()', ctx);

    const bodyEl = createMockElement('div');
    const panel = { def: SensorNetPanelDef, w: 280, x: 0, y: 0, manager: { container: createMockElement('div') }, _unsubs: [], _applyTransform() {} };
    panel.manager.container.clientWidth = 1200;
    SensorNetPanelDef.mount(bodyEl, panel);

    vm.runInContext(`EventBus.emit('sensor:triggered', {
        sensor_id: 'tripwire-01',
        name: 'Back Yard Tripwire',
        type: 'tripwire',
        triggered_by: 'hostile-05',
    })`, ctx);

    const helpers = sandbox.window.SensorNetHelpers;
    const lastEntry = helpers.getLastLogEntry();
    assert(lastEntry !== null, 'Last log entry exists');
    assert(lastEntry.sensor_id === 'tripwire-01', 'Log entry has correct sensor_id');
    assert(lastEntry.action === 'triggered', 'Log entry action is triggered');
    assert(lastEntry.sensor_type === 'tripwire', 'Log entry has correct sensor type');
    assert(lastEntry.triggered_by === 'hostile-05', 'Log entry has trigger source');
})();

// ============================================================
// 5. sensor:cleared updates state
// ============================================================
console.log('\n--- sensor:cleared event handling ---');

(function() {
    vm.runInContext('EventBus._handlers = new Map()', ctx);

    const bodyEl = createMockElement('div');
    const panel = { def: SensorNetPanelDef, w: 280, x: 0, y: 0, manager: { container: createMockElement('div') }, _unsubs: [], _applyTransform() {} };
    panel.manager.container.clientWidth = 1200;
    SensorNetPanelDef.mount(bodyEl, panel);

    // Trigger then clear
    vm.runInContext(`EventBus.emit('sensor:triggered', {
        sensor_id: 'motion-01',
        name: 'Front Door Motion',
        type: 'motion',
        triggered_by: 'hostile-03',
    })`, ctx);

    vm.runInContext(`EventBus.emit('sensor:cleared', {
        sensor_id: 'motion-01',
        name: 'Front Door Motion',
        type: 'motion',
    })`, ctx);

    const helpers = sandbox.window.SensorNetHelpers;
    assert(helpers.getActiveCount() === 0, 'Active count drops to 0 after clear');
})();

(function() {
    vm.runInContext('EventBus._handlers = new Map()', ctx);

    const bodyEl = createMockElement('div');
    const panel = { def: SensorNetPanelDef, w: 280, x: 0, y: 0, manager: { container: createMockElement('div') }, _unsubs: [], _applyTransform() {} };
    panel.manager.container.clientWidth = 1200;
    SensorNetPanelDef.mount(bodyEl, panel);

    vm.runInContext(`EventBus.emit('sensor:triggered', { sensor_id: 's1', name: 'S1', type: 'motion', triggered_by: 'h1' })`, ctx);
    vm.runInContext(`EventBus.emit('sensor:cleared', { sensor_id: 's1', name: 'S1', type: 'motion' })`, ctx);

    const helpers = sandbox.window.SensorNetHelpers;
    assert(helpers.getLogLength() === 2, 'Log has 2 entries (trigger + clear)');
    const last = helpers.getLastLogEntry();
    assert(last.action === 'cleared', 'Last log entry action is cleared');
})();

// ============================================================
// 6. Log max 50 entries
// ============================================================
console.log('\n--- Log max 50 entries ---');

(function() {
    vm.runInContext('EventBus._handlers = new Map()', ctx);

    const bodyEl = createMockElement('div');
    const panel = { def: SensorNetPanelDef, w: 280, x: 0, y: 0, manager: { container: createMockElement('div') }, _unsubs: [], _applyTransform() {} };
    panel.manager.container.clientWidth = 1200;
    SensorNetPanelDef.mount(bodyEl, panel);

    const helpers = sandbox.window.SensorNetHelpers;

    // Add 55 events
    for (let i = 0; i < 55; i++) {
        vm.runInContext(`EventBus.emit('sensor:triggered', {
            sensor_id: 'sensor-${i}',
            name: 'Sensor ${i}',
            type: 'motion',
            triggered_by: 'target-${i}',
        })`, ctx);
    }

    assert(helpers.getLogLength() <= 50, 'Log is capped at 50 entries, got ' + helpers.getLogLength());
})();

// ============================================================
// 7. Sensor type labels
// ============================================================
console.log('\n--- Sensor type labels ---');

(function() {
    const helpers = sandbox.window.SensorNetHelpers;
    assert(typeof helpers.getSensorIcon === 'function', 'getSensorIcon helper exists');
    assert(helpers.getSensorIcon('motion') !== '', 'motion type has an icon');
    assert(helpers.getSensorIcon('door') !== '', 'door type has an icon');
    assert(helpers.getSensorIcon('tripwire') !== '', 'tripwire type has an icon');
    assert(helpers.getSensorIcon('unknown_type') !== '', 'unknown type still returns a fallback icon');
})();

(function() {
    const helpers = sandbox.window.SensorNetHelpers;
    assert(typeof helpers.getSensorLabel === 'function', 'getSensorLabel helper exists');
    assert(helpers.getSensorLabel('motion') === 'MOTION', 'motion label is MOTION');
    assert(helpers.getSensorLabel('door') === 'DOOR', 'door label is DOOR');
    assert(helpers.getSensorLabel('tripwire') === 'TRIPWIRE', 'tripwire label is TRIPWIRE');
})();

// ============================================================
// 8. Multiple sensors active simultaneously
// ============================================================
console.log('\n--- Multiple sensors ---');

(function() {
    vm.runInContext('EventBus._handlers = new Map()', ctx);

    const bodyEl = createMockElement('div');
    const panel = { def: SensorNetPanelDef, w: 280, x: 0, y: 0, manager: { container: createMockElement('div') }, _unsubs: [], _applyTransform() {} };
    panel.manager.container.clientWidth = 1200;
    SensorNetPanelDef.mount(bodyEl, panel);

    vm.runInContext(`EventBus.emit('sensor:triggered', { sensor_id: 's1', name: 'S1', type: 'motion', triggered_by: 'h1' })`, ctx);
    vm.runInContext(`EventBus.emit('sensor:triggered', { sensor_id: 's2', name: 'S2', type: 'door', triggered_by: 'h2' })`, ctx);
    vm.runInContext(`EventBus.emit('sensor:triggered', { sensor_id: 's3', name: 'S3', type: 'tripwire', triggered_by: 'h3' })`, ctx);

    const helpers = sandbox.window.SensorNetHelpers;
    assert(helpers.getActiveCount() === 3, 'Three sensors active simultaneously');

    // Clear one
    vm.runInContext(`EventBus.emit('sensor:cleared', { sensor_id: 's2', name: 'S2', type: 'door' })`, ctx);
    assert(helpers.getActiveCount() === 2, 'Two sensors active after one cleared');
})();

// ============================================================
// 9. Cleanup on destroy
// ============================================================
console.log('\n--- Cleanup ---');

(function() {
    vm.runInContext('EventBus._handlers = new Map()', ctx);

    const bodyEl = createMockElement('div');
    const panel = { def: SensorNetPanelDef, w: 280, x: 0, y: 0, manager: { container: createMockElement('div') }, _unsubs: [], _applyTransform() {} };
    panel.manager.container.clientWidth = 1200;
    SensorNetPanelDef.mount(bodyEl, panel);

    // Verify handlers exist
    const triggeredHandlers = vm.runInContext('EventBus._handlers.get("sensor:triggered")', ctx);
    const clearedHandlers = vm.runInContext('EventBus._handlers.get("sensor:cleared")', ctx);
    assert(triggeredHandlers && triggeredHandlers.size > 0, 'sensor:triggered handler registered');
    assert(clearedHandlers && clearedHandlers.size > 0, 'sensor:cleared handler registered');

    // Run all unsubs (simulating Panel base class cleanup)
    for (const unsub of panel._unsubs) {
        if (typeof unsub === 'function') unsub();
    }

    // Handlers should be removed
    const afterTriggered = vm.runInContext('EventBus._handlers.get("sensor:triggered")', ctx);
    const afterCleared = vm.runInContext('EventBus._handlers.get("sensor:cleared")', ctx);
    assert(!afterTriggered || afterTriggered.size === 0, 'sensor:triggered handler removed after cleanup');
    assert(!afterCleared || afterCleared.size === 0, 'sensor:cleared handler removed after cleanup');
})();

// ============================================================
// 10. unmount() does not throw
// ============================================================
console.log('\n--- unmount() ---');

(function() {
    let threw = false;
    try { SensorNetPanelDef.unmount(createMockElement('div')); } catch (e) { threw = true; }
    assert(!threw, 'unmount() does not throw');
})();

// ============================================================
// 11. Re-triggering same sensor updates state
// ============================================================
console.log('\n--- Re-trigger same sensor ---');

(function() {
    vm.runInContext('EventBus._handlers = new Map()', ctx);

    const bodyEl = createMockElement('div');
    const panel = { def: SensorNetPanelDef, w: 280, x: 0, y: 0, manager: { container: createMockElement('div') }, _unsubs: [], _applyTransform() {} };
    panel.manager.container.clientWidth = 1200;
    SensorNetPanelDef.mount(bodyEl, panel);

    const helpers = sandbox.window.SensorNetHelpers;

    // Trigger same sensor twice (e.g., different target enters)
    vm.runInContext(`EventBus.emit('sensor:triggered', { sensor_id: 's1', name: 'S1', type: 'motion', triggered_by: 'h1' })`, ctx);
    vm.runInContext(`EventBus.emit('sensor:triggered', { sensor_id: 's1', name: 'S1', type: 'motion', triggered_by: 'h2' })`, ctx);

    // Should still count as 1 active sensor (same sensor_id)
    assert(helpers.getActiveCount() === 1, 'Re-triggering same sensor keeps active count at 1');
    // But log should have 2 entries
    assert(helpers.getLogLength() === 2, 'Log has 2 entries for re-trigger');
})();

// ============================================================
// Summary
// ============================================================
console.log('\n' + '='.repeat(40));
console.log(`Results: ${passed} passed, ${failed} failed`);
console.log('='.repeat(40));
process.exit(failed > 0 ? 1 : 0);
