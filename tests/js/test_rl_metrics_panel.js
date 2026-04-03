// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
/**
 * TRITIUM-SC RL Metrics Panel tests
 * Tests RlMetricsPanelDef structure, DOM creation, data bindings,
 * chart canvases, and button wiring.
 * Run: node tests/js/test_rl_metrics_panel.js
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
            const re = /data-bind="([^"]+)"/g;
            let m;
            while ((m = re.exec(val)) !== null) {
                el._parsedBinds[m[1]] = true;
            }
        },
        get textContent() { return _textContent; },
        set textContent(val) { _textContent = val; },
        children,
        childNodes: children,
        classList: {
            add: (c) => classList.add(c),
            remove: (c) => classList.delete(c),
            contains: (c) => classList.has(c),
            toggle: (c) => classList.has(c) ? classList.delete(c) : classList.add(c),
        },
        style,
        dataset,
        appendChild: (child) => { children.push(child); return child; },
        removeChild: (child) => {
            const idx = children.indexOf(child);
            if (idx >= 0) children.splice(idx, 1);
            return child;
        },
        querySelector: (sel) => {
            const bindMatch = sel.match(/\[data-bind="([^"]+)"\]/);
            if (bindMatch) {
                const bindName = bindMatch[1];
                if (bindName === 'accuracy-chart' || bindName === 'pred-chart') {
                    return createMockCanvas();
                }
                return createMockElement('div');
            }
            const actionMatch = sel.match(/\[data-action="([^"]+)"\]/);
            if (actionMatch) {
                return createMockElement('button');
            }
            return createMockElement('div');
        },
        querySelectorAll: () => [],
        addEventListener: (type, fn) => {
            if (!eventListeners[type]) eventListeners[type] = [];
            eventListeners[type].push(fn);
        },
        removeEventListener: () => {},
        dispatchEvent: () => {},
        _eventListeners: eventListeners,
        _parsedBinds: {},
        prepend: (child) => { children.unshift(child); },
    };
    return el;
}

function createMockCanvas() {
    return {
        tagName: 'CANVAS',
        width: 480,
        height: 100,
        style: {},
        getContext: () => ({
            clearRect: () => {},
            fillRect: () => {},
            strokeRect: () => {},
            fillText: () => {},
            beginPath: () => {},
            moveTo: () => {},
            lineTo: () => {},
            stroke: () => {},
            arc: () => {},
            fill: () => {},
            font: '',
            fillStyle: '',
            strokeStyle: '',
            lineWidth: 1,
            textAlign: '',
        }),
    };
}

// Global mocks
const _globalMocks = {
    document: {
        createElement: (tag) => createMockElement(tag),
        querySelector: () => createMockElement('div'),
        querySelectorAll: () => [],
        addEventListener: () => {},
        body: createMockElement('body'),
    },
    window: {
        addEventListener: () => {},
        removeEventListener: () => {},
        setTimeout: (fn) => fn(),
        setInterval: () => 999,
        clearInterval: () => {},
        fetch: () => Promise.resolve({ ok: true, json: () => Promise.resolve({}) }),
    },
    console,
    fetch: () => Promise.resolve({ ok: true, json: () => Promise.resolve({}) }),
    setTimeout: (fn) => fn(),
    setInterval: () => 999,
    clearInterval: () => {},
};

// ============================================================
// Load module source
// ============================================================

const srcPath = __dirname + '/../../src/frontend/js/command/panels/rl-metrics.js';
const src = fs.readFileSync(srcPath, 'utf8');

// Convert ESM to CommonJS
const cjsSrc = src
    .replace(/export\s+const\s+/g, 'exports.')
    .replace(/export\s+function\s+/g, 'exports.');

const sandbox = vm.createContext({ ..._globalMocks, exports: {} });
vm.runInContext(cjsSrc, sandbox);

const PanelDef = sandbox.exports.RlMetricsPanelDef;

// ============================================================
// Tests
// ============================================================

// 1. Definition structure
assert(PanelDef !== undefined, 'RlMetricsPanelDef is exported');
assert(PanelDef.id === 'rl-metrics', 'Panel ID is rl-metrics');
assert(PanelDef.title === 'RL METRICS', 'Panel title is RL METRICS');
assert(typeof PanelDef.create === 'function', 'create() is a function');
assert(typeof PanelDef.mount === 'function', 'mount() is a function');

// 2. Default position and size
assert(PanelDef.defaultPosition.x === 300, 'Default X position');
assert(PanelDef.defaultPosition.y === 80, 'Default Y position');
assert(PanelDef.defaultSize.w === 520, 'Default width');
assert(PanelDef.defaultSize.h === 580, 'Default height');

// 3. DOM creation
const panel = {};
const el = PanelDef.create(panel);
assert(el !== null, 'create() returns an element');
assert(el.innerHTML.length > 100, 'create() produces substantial HTML');

// 4. Data bindings exist in HTML
const expectedBinds = [
    'status-badge',
    'overall-accuracy',
    'total-trainings',
    'total-predictions',
    'correct-rate',
    'accuracy-chart',
    'feature-bars',
    'pred-chart',
    'model-details',
];
for (const bind of expectedBinds) {
    assert(el.innerHTML.includes(`data-bind="${bind}"`), `Has data-bind="${bind}"`);
}

// 5. Buttons exist
assert(el.innerHTML.includes('data-action="refresh"'), 'Has refresh button');
assert(el.innerHTML.includes('data-action="retrain"'), 'Has retrain button');

// 6. Style block includes cyberpunk colors
assert(el.innerHTML.includes('#00f0ff'), 'Uses cyan color');
assert(el.innerHTML.includes('#05ffa1'), 'Uses green color');

// 7. Canvas elements for charts
assert(el.innerHTML.includes('accuracy-chart'), 'Has accuracy chart canvas');
assert(el.innerHTML.includes('pred-chart'), 'Has prediction distribution chart canvas');

// 8. Mount wires click handlers
const bodyEl = createMockElement('div');
bodyEl.innerHTML = el.innerHTML;
PanelDef.mount(bodyEl, panel);
assert(bodyEl._eventListeners['click'] !== undefined, 'Mount wires click handler');
assert(bodyEl._eventListeners['click'].length >= 1, 'At least one click handler');

// ============================================================
// Results
// ============================================================
console.log(`\n${passed} passed, ${failed} failed`);
process.exit(failed > 0 ? 1 : 0);
