// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
/**
 * TRITIUM-SC Assets Panel tests
 * Tests AssetsPanelDef structure, DOM creation, 3D sensor placement fields,
 * form defaults, accessibility attributes, and event wiring.
 * Run: node tests/js/test_assets_panel.js
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

const sandbox = {
    Math, Date, console, Map, Set, Array, Object, Number, String, Boolean,
    Infinity, NaN, undefined, parseInt, parseFloat, isNaN, isFinite, JSON,
    Promise, setTimeout, clearTimeout, setInterval, clearInterval, Error,
    document: {
        createElement: createMockElement,
        getElementById: () => null,
        querySelector: () => null,
        addEventListener() {},
        removeEventListener() {},
    },
    window: {},
    fetch: () => Promise.resolve({ ok: true, json: () => Promise.resolve([]) }),
    performance: { now: () => Date.now() },
};

const ctx = vm.createContext(sandbox);

// Load events.js (EventBus)
const eventsCode = fs.readFileSync(__dirname + '/../../../tritium-lib/web/events.js', 'utf8');
const eventsPlain = eventsCode
    .replace(/^export\s+/gm, '')
    .replace(/^import\s+.*$/gm, '');
vm.runInContext(eventsPlain, ctx);

// Load assets.js panel
const assetsCode = fs.readFileSync(__dirname + '/../../src/frontend/js/command/panels/assets.js', 'utf8');
const assetsPlain = assetsCode
    .replace(/^export\s+const\s+/gm, 'var ')
    .replace(/^export\s+/gm, '')
    .replace(/^import\s+.*$/gm, '');
vm.runInContext(assetsPlain, ctx);

// ============================================================
// Tests
// ============================================================

console.log('\n=== Assets Panel Tests ===\n');

// -- Panel definition structure
const def = vm.runInContext('AssetsPanelDef', ctx);
assert(def !== undefined, 'AssetsPanelDef is defined');
assert(def.id === 'assets', 'Panel id is "assets"');
assert(def.title === 'ASSETS', 'Panel title is "ASSETS"');
assert(typeof def.create === 'function', 'create() is a function');
assert(typeof def.mount === 'function', 'mount() is a function');
assert(typeof def.unmount === 'function', 'unmount() is a function');
assert(def.defaultSize.w === 300, 'Default width is 300');
assert(def.defaultSize.h === 420, 'Default height is 420');

// -- DOM creation
const fakePanel = { _unsubs: [] };
const el = def.create(fakePanel);
assert(el !== null && el !== undefined, 'create() returns an element');
assert(el.className === 'assets-panel-inner', 'Root element has correct className');

const html = el.innerHTML;

// -- Toolbar buttons
assert(html.includes('data-action="refresh"'), 'Has REFRESH button');
assert(html.includes('data-action="add-asset"'), 'Has ADD ASSET button');

// -- Asset list with accessibility
assert(html.includes('data-bind="asset-list"'), 'Has asset list container');
assert(html.includes('role="listbox"'), 'Asset list has listbox role');
assert(html.includes('aria-label="Placed assets"'), 'Asset list has aria-label');

// -- Editor with 3D placement fields
assert(html.includes('data-bind="asset-editor"'), 'Has editor container');
assert(html.includes('data-bind="name"'), 'Editor has name input');
assert(html.includes('data-bind="type"'), 'Editor has type select');
assert(html.includes('data-bind="height"'), 'Editor has height input');
assert(html.includes('data-bind="floor"'), 'Editor has floor level input');
assert(html.includes('data-bind="mounting"'), 'Editor has mounting type select');
assert(html.includes('data-bind="coverage_radius"'), 'Editor has coverage radius input');
assert(html.includes('data-bind="fov"'), 'Editor has FOV input');
assert(html.includes('data-bind="rotation"'), 'Editor has rotation input');
assert(html.includes('data-bind="position"'), 'Editor has position display');

// -- Mounting type options
assert(html.includes('value="wall"'), 'Has wall mounting option');
assert(html.includes('value="ceiling"'), 'Has ceiling mounting option');
assert(html.includes('value="pole"'), 'Has pole mounting option');
assert(html.includes('value="ground"'), 'Has ground mounting option');

// -- Height input attributes
assert(html.includes('id="asset-height"'), 'Height input has correct id');
assert(html.includes('min="0"') && html.includes('max="100"'), 'Height has min/max bounds');

// -- Floor level input attributes
assert(html.includes('id="asset-floor"'), 'Floor input has correct id');

// -- Coverage radius input
assert(html.includes('id="asset-coverage-radius"'), 'Coverage radius input has correct id');
assert(html.includes('RANGE (m)'), 'Coverage radius labeled as RANGE');

// -- Editor action buttons
assert(html.includes('data-action="place-on-map"'), 'Has place-on-map button');
assert(html.includes('data-action="save-asset"'), 'Has save button');
assert(html.includes('data-action="cancel-edit"'), 'Has cancel button');

// -- Asset type definitions
const types = vm.runInContext('ASSET_TYPES', ctx);
assert(Array.isArray(types), 'ASSET_TYPES is an array');
assert(types.length === 4, 'ASSET_TYPES has 4 entries');
assert(types.some(t => t.value === 'camera'), 'Has camera type');
assert(types.some(t => t.value === 'sensor'), 'Has sensor type');
assert(types.some(t => t.value === 'mesh_radio'), 'Has mesh_radio type');
assert(types.some(t => t.value === 'gateway'), 'Has gateway type');

// Verify colors match cyberpunk theme
const cameraType = types.find(t => t.value === 'camera');
assert(cameraType.color === '#00f0ff', 'Camera color is cyan');
const sensorType = types.find(t => t.value === 'sensor');
assert(sensorType.color === '#05ffa1', 'Sensor color is green');
const meshType = types.find(t => t.value === 'mesh_radio');
assert(meshType.color === '#fcee0a', 'Mesh radio color is yellow');
const gatewayType = types.find(t => t.value === 'gateway');
assert(gatewayType.color === '#ff2a6d', 'Gateway color is magenta');

// -- Mount wiring (verify no crash)
const mockPanel = { _unsubs: [] };
const bodyEl = el;
try {
    def.mount(bodyEl, mockPanel);
    assert(true, 'mount() executes without error');
} catch (e) {
    assert(false, 'mount() threw: ' + e.message);
}

// Check that mount registered cleanup callbacks
assert(mockPanel._unsubs.length > 0, 'mount() registers cleanup callbacks');

// -- Unmount (verify no crash)
try {
    def.unmount(bodyEl);
    assert(true, 'unmount() executes without error');
} catch (e) {
    assert(false, 'unmount() threw: ' + e.message);
}

// ============================================================
// Summary
// ============================================================

console.log(`\n${passed} passed, ${failed} failed (${passed + failed} total)\n`);
process.exit(failed > 0 ? 1 : 0);
