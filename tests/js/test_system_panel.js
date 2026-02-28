// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
/**
 * TRITIUM-SC System Panel tests
 * Tests SystemPanelDef structure, DOM creation, tabs (cameras, discovery,
 * telemetry, perf, ai), data bindings, and mount wiring.
 * Run: node tests/js/test_system_panel.js
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
        width: 280, height: 40,
        getContext() { return { clearRect(){}, beginPath(){}, moveTo(){}, lineTo(){}, stroke(){}, strokeStyle:'', lineWidth:0, setLineDash(){} }; },
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
            if (bindMatch) { const mock = createMockElement(bindMatch[1] === 'fps-sparkline' ? 'canvas' : 'div'); mock._bindName = bindMatch[1]; if (bindMatch[1] === 'fps-sparkline') { mock.width = 280; mock.height = 40; } return mock; }
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
    document: {
        createElement: createMockElement,
        getElementById: () => null,
        querySelector: () => null,
        querySelectorAll: () => [],
        addEventListener() {}, removeEventListener() {},
    },
    window: { TritiumStore: null },
    fetch: () => Promise.resolve({ ok: true, json: () => Promise.resolve({}) }),
    performance: { now: () => Date.now(), memory: null },
};

const ctx = vm.createContext(sandbox);

vm.runInContext(fs.readFileSync(__dirname + '/../../frontend/js/command/events.js', 'utf8').replace(/^export\s+/gm, '').replace(/^import\s+.*$/gm, ''), ctx);
vm.runInContext(fs.readFileSync(__dirname + '/../../frontend/js/command/store.js', 'utf8').replace(/^export\s+/gm, '').replace(/^import\s+.*$/gm, ''), ctx);

const sysCode = fs.readFileSync(__dirname + '/../../frontend/js/command/panels/system.js', 'utf8');
vm.runInContext(sysCode.replace(/^export\s+const\s+/gm, 'var ').replace(/^export\s+/gm, '').replace(/^import\s+.*$/gm, ''), ctx);

const SystemPanelDef = ctx.SystemPanelDef;

// ============================================================
// 1. Structure
// ============================================================
console.log('\n--- SystemPanelDef structure ---');

(function() { assert(SystemPanelDef.id === 'system', 'id is "system"'); })();
(function() { assert(SystemPanelDef.title === 'SYSTEM', 'title is "SYSTEM"'); })();
(function() { assert(typeof SystemPanelDef.create === 'function', 'create is a function'); })();
(function() { assert(typeof SystemPanelDef.mount === 'function', 'mount is a function'); })();
(function() { assert(typeof SystemPanelDef.unmount === 'function', 'unmount is a function'); })();
(function() { assert(SystemPanelDef.defaultSize.w === 320, 'defaultSize.w is 320'); })();
(function() { assert(SystemPanelDef.defaultSize.h === 420, 'defaultSize.h is 420'); })();

// ============================================================
// 2. create() DOM
// ============================================================
console.log('\n--- create() DOM ---');

(function() { assert(SystemPanelDef.create({}).className === 'system-panel-inner', 'className correct'); })();

// ============================================================
// 3. Tabs
// ============================================================
console.log('\n--- Tabs ---');

(function() { const html = SystemPanelDef.create({}).innerHTML; assert(html.includes('data-tab="cameras"'), 'Has CAMERAS tab'); })();
(function() { const html = SystemPanelDef.create({}).innerHTML; assert(html.includes('data-tab="discovery"'), 'Has DISCOVERY tab'); })();
(function() { const html = SystemPanelDef.create({}).innerHTML; assert(html.includes('data-tab="telemetry"'), 'Has TELEMETRY tab'); })();
(function() { const html = SystemPanelDef.create({}).innerHTML; assert(html.includes('data-tab="perf"'), 'Has PERF tab'); })();
(function() { const html = SystemPanelDef.create({}).innerHTML; assert(html.includes('data-tab="ai"'), 'Has AI tab'); })();
(function() { const html = SystemPanelDef.create({}).innerHTML; assert(html.includes('>CAMERAS<'), 'CAMERAS tab label'); })();
(function() { const html = SystemPanelDef.create({}).innerHTML; assert(html.includes('>DISCOVERY<'), 'DISCOVERY tab label'); })();
(function() { const html = SystemPanelDef.create({}).innerHTML; assert(html.includes('>TELEMETRY<'), 'TELEMETRY tab label'); })();
(function() { const html = SystemPanelDef.create({}).innerHTML; assert(html.includes('>PERF<'), 'PERF tab label'); })();
(function() { const html = SystemPanelDef.create({}).innerHTML; assert(html.includes('>AI<'), 'AI tab label'); })();

// ============================================================
// 4. Tab panes
// ============================================================
console.log('\n--- Tab panes ---');

(function() { const html = SystemPanelDef.create({}).innerHTML; assert(html.includes('data-pane="cameras"'), 'Has cameras pane'); })();
(function() { const html = SystemPanelDef.create({}).innerHTML; assert(html.includes('data-pane="discovery"'), 'Has discovery pane'); })();
(function() { const html = SystemPanelDef.create({}).innerHTML; assert(html.includes('data-pane="telemetry"'), 'Has telemetry pane'); })();
(function() { const html = SystemPanelDef.create({}).innerHTML; assert(html.includes('data-pane="perf"'), 'Has perf pane'); })();
(function() { const html = SystemPanelDef.create({}).innerHTML; assert(html.includes('data-pane="ai"'), 'Has ai pane'); })();

// ============================================================
// 5. Cameras tab
// ============================================================
console.log('\n--- Cameras tab ---');

(function() { const html = SystemPanelDef.create({}).innerHTML; assert(html.includes('data-action="refresh-cameras"'), 'Has refresh cameras button'); })();
(function() { const html = SystemPanelDef.create({}).innerHTML; assert(html.includes('data-bind="camera-list"'), 'Has camera list'); })();
(function() { const html = SystemPanelDef.create({}).innerHTML; assert(html.includes('Loading cameras...'), 'Has loading state'); })();

// ============================================================
// 6. Discovery tab
// ============================================================
console.log('\n--- Discovery tab ---');

(function() { const html = SystemPanelDef.create({}).innerHTML; assert(html.includes('data-action="scan-nvr"'), 'Has SCAN NVR button'); })();
(function() { const html = SystemPanelDef.create({}).innerHTML; assert(html.includes('data-action="auto-register"'), 'Has AUTO-REGISTER button'); })();
(function() { const html = SystemPanelDef.create({}).innerHTML; assert(html.includes('data-bind="nvr-status"'), 'Has NVR status area'); })();
(function() { const html = SystemPanelDef.create({}).innerHTML; assert(html.includes('data-bind="discovery-list"'), 'Has discovery list'); })();

// ============================================================
// 7. Telemetry tab
// ============================================================
console.log('\n--- Telemetry tab ---');

(function() { const html = SystemPanelDef.create({}).innerHTML; assert(html.includes('data-action="refresh-telemetry"'), 'Has refresh telemetry button'); })();
(function() { const html = SystemPanelDef.create({}).innerHTML; assert(html.includes('data-bind="telemetry-content"'), 'Has telemetry content area'); })();

// ============================================================
// 8. Perf tab
// ============================================================
console.log('\n--- Perf tab ---');

(function() { const html = SystemPanelDef.create({}).innerHTML; assert(html.includes('data-bind="fps-sparkline"'), 'Has FPS sparkline canvas'); })();
(function() { const html = SystemPanelDef.create({}).innerHTML; assert(html.includes('data-bind="perf-fps"'), 'Has FPS display'); })();
(function() { const html = SystemPanelDef.create({}).innerHTML; assert(html.includes('data-bind="perf-units"'), 'Has units count'); })();
(function() { const html = SystemPanelDef.create({}).innerHTML; assert(html.includes('data-bind="perf-panels"'), 'Has panels count'); })();
(function() { const html = SystemPanelDef.create({}).innerHTML; assert(html.includes('data-bind="perf-ws-latency"'), 'Has WS latency'); })();
(function() { const html = SystemPanelDef.create({}).innerHTML; assert(html.includes('data-bind="perf-memory"'), 'Has memory display'); })();

// ============================================================
// 9. AI tab
// ============================================================
console.log('\n--- AI tab ---');

(function() { const html = SystemPanelDef.create({}).innerHTML; assert(html.includes('data-action="refresh-ai"'), 'Has refresh AI button'); })();
(function() { const html = SystemPanelDef.create({}).innerHTML; assert(html.includes('data-bind="ai-content"'), 'Has AI content area'); })();

// ============================================================
// 10. mount()
// ============================================================
console.log('\n--- mount() ---');

(function() {
    const bodyEl = createMockElement('div');
    const panel = { def: SystemPanelDef, _unsubs: [] };
    SystemPanelDef.mount(bodyEl, panel);
    assert(panel._unsubs.length >= 2, 'mount() registers at least 2 cleanup fns (perf interval + camera refresh), got ' + panel._unsubs.length);
})();

(function() {
    const bodyEl = createMockElement('div');
    const panel = { def: SystemPanelDef, _unsubs: [] };
    let threw = false;
    try { SystemPanelDef.mount(bodyEl, panel); } catch (e) { threw = true; }
    assert(!threw, 'mount() does not crash');
})();

// ============================================================
// 11. unmount()
// ============================================================
console.log('\n--- unmount() ---');

(function() { let threw = false; try { SystemPanelDef.unmount(createMockElement('div')); } catch (e) { threw = true; } assert(!threw, 'unmount() does not throw'); })();

// ============================================================
// Summary
// ============================================================
console.log('\n' + '='.repeat(40));
console.log(`Results: ${passed} passed, ${failed} failed`);
console.log('='.repeat(40));
process.exit(failed > 0 ? 1 : 0);
