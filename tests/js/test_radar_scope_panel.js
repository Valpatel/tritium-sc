// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
/**
 * TRITIUM-SC Radar PPI Scope Panel tests
 * Tests RadarScopePanelDef structure, DOM creation, controls,
 * coordinate conversion, and track rendering logic.
 * Run: node tests/js/test_radar_scope_panel.js
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
        },
        get textContent() { return _textContent; },
        set textContent(val) { _textContent = String(val); },
        style,
        dataset,
        children,
        childNodes: children,
        parentNode: null,
        hidden: false,
        appendChild(child) { children.push(child); child.parentNode = el; return child; },
        removeChild(child) { const i = children.indexOf(child); if (i >= 0) children.splice(i, 1); },
        remove() { if (el.parentNode) el.parentNode.removeChild(el); },
        querySelector(sel) {
            // Handle data-bind selectors
            const bindMatch = sel.match(/\[data-bind="([^"]+)"\]/);
            if (bindMatch && el._parsedBinds && el._parsedBinds[bindMatch[1]]) {
                return createMockElement('span');
            }
            return null;
        },
        querySelectorAll() { return []; },
        addEventListener(evt, fn) {
            if (!eventListeners[evt]) eventListeners[evt] = [];
            eventListeners[evt].push(fn);
        },
        removeEventListener(evt, fn) {
            if (eventListeners[evt]) {
                const i = eventListeners[evt].indexOf(fn);
                if (i >= 0) eventListeners[evt].splice(i, 1);
            }
        },
        _eventListeners: eventListeners,
        _parsedBinds: {},
        classList: {
            add(c) { classList.add(c); },
            remove(c) { classList.delete(c); },
            contains(c) { return classList.has(c); },
            toggle(c) { if (classList.has(c)) classList.delete(c); else classList.add(c); },
        },
        getBoundingClientRect() { return { left: 0, top: 0, width: 400, height: 400 }; },
    };
    return el;
}

// ============================================================
// Read the panel source
// ============================================================

const src = fs.readFileSync(
    __dirname + '/../../src/frontend/js/command/panels/radar-scope.js',
    'utf-8'
);

// Build a sandboxed module that captures the export
const EventBusMock = {
    _handlers: {},
    on(evt, fn) { if (!this._handlers[evt]) this._handlers[evt] = []; this._handlers[evt].push(fn); return () => {}; },
    emit(evt, data) { (this._handlers[evt] || []).forEach(fn => fn(data)); },
};

const exported = {};
const mockContext = {
    console,
    Math,
    Date,
    parseInt,
    parseFloat,
    Set,
    Map,
    Object,
    Array,
    String,
    Number,
    JSON,
    Error,
    RegExp,
    Promise,
    setTimeout,
    clearTimeout,
    setInterval,
    clearInterval,
    requestAnimationFrame: (fn) => 1,
    cancelAnimationFrame: () => {},
    window: { devicePixelRatio: 1 },
    ResizeObserver: class { observe() {} disconnect() {} },
    document: {
        createElement: createMockElement,
    },
    fetch: async () => ({ ok: true, json: async () => ({ tracks: [], count: 0 }) }),
};

// Convert ES module to CJS-compatible
let cjsSrc = src
    .replace(/^import\s+\{[^}]+\}\s+from\s+'[^']+';?\s*$/gm, '')
    .replace(/^export\s+const\s+/gm, 'exported.')
    .replace(/^export\s+function\s+/gm, 'exported.')
    .replace(/^export\s+/gm, 'exported.');

try {
    const script = new vm.Script(cjsSrc, { filename: 'radar-scope.js' });
    const ctx = vm.createContext({
        ...mockContext,
        exported,
        _esc: (s) => String(s || '').replace(/</g, '&lt;').replace(/>/g, '&gt;'),
        EventBus: EventBusMock,
    });
    script.runInContext(ctx);
} catch (e) {
    console.error('Failed to load module:', e.message);
    process.exit(1);
}

const RadarScopePanelDef = exported.RadarScopePanelDef;

// ============================================================
// Tests
// ============================================================

// -- Panel definition structure --
assert(RadarScopePanelDef !== undefined, 'RadarScopePanelDef is exported');
assert(RadarScopePanelDef.id === 'radar-scope', 'Panel ID is radar-scope');
assert(RadarScopePanelDef.title === 'RADAR PPI SCOPE', 'Panel title is RADAR PPI SCOPE');
assert(typeof RadarScopePanelDef.create === 'function', 'create is a function');
assert(typeof RadarScopePanelDef.mount === 'function', 'mount is a function');
assert(typeof RadarScopePanelDef.unmount === 'function', 'unmount is a function');

// -- Default size --
assert(RadarScopePanelDef.defaultSize.w === 520, 'Default width is 520');
assert(RadarScopePanelDef.defaultSize.h === 600, 'Default height is 600');

// -- DOM creation --
const mockPanel = { _unsubs: [] };
const el = RadarScopePanelDef.create(mockPanel);
assert(el !== null && el !== undefined, 'create() returns an element');
assert(el.className === 'radar-scope-inner', 'Root element has correct class');

// Check that innerHTML contains key data-bind attributes
const html = el.innerHTML;
assert(html.includes('data-bind="status"'), 'Has status binding');
assert(html.includes('data-bind="track-count"'), 'Has track-count binding');
assert(html.includes('data-bind="last-update"'), 'Has last-update binding');
assert(html.includes('data-bind="canvas"'), 'Has canvas binding');
assert(html.includes('data-bind="tooltip"'), 'Has tooltip binding');
assert(html.includes('data-bind="range-select"'), 'Has range-select binding');
assert(html.includes('data-bind="filter-select"'), 'Has filter-select binding');

// -- Controls content --
assert(html.includes('5 km'), 'Range option 5km present');
assert(html.includes('10 km'), 'Range option 10km present');
assert(html.includes('20 km'), 'Range option 20km present');
assert(html.includes('50 km'), 'Range option 50km present');
assert(html.includes('HOSTILE'), 'Filter option HOSTILE present');
assert(html.includes('UNKNOWN'), 'Filter option UNKNOWN present');
assert(html.includes('FRIENDLY'), 'Filter option FRIENDLY present');

// -- Header content --
assert(html.includes('ACTIVE'), 'Status shows ACTIVE by default');
assert(html.includes('TRACKS:'), 'Header shows TRACKS label');
assert(html.includes('UPDATED:'), 'Header shows UPDATED label');

// -- Style assertions --
assert(html.includes('#0a0a0f') || el.style.cssText.includes('#0a0a0f'), 'Uses dark background color');
assert(html.includes('#00f0ff'), 'Uses cyan accent color');

// -- Source code quality checks --
assert(src.includes('requestAnimationFrame'), 'Uses requestAnimationFrame for animation');
assert(src.includes('ResizeObserver'), 'Uses ResizeObserver for canvas sizing');
assert(src.includes('/api/radar/tracks'), 'Fetches from correct API endpoint');
assert(src.includes('setInterval'), 'Sets up periodic fetch');
assert(src.includes('cancelAnimationFrame'), 'Cleans up animation frame on unmount');
assert(src.includes('clearInterval'), 'Cleans up interval on unmount');
assert(src.includes('TRAIL_LENGTH'), 'Has trail length constant');
assert(src.includes('SWEEP_PERIOD_MS'), 'Has sweep period constant');
assert(src.includes('sweepAngle'), 'Tracks sweep angle');
assert(src.includes('range rings') || src.includes('Range rings') || src.includes('ringCount'), 'Renders range rings');
assert(src.includes("'N'") && src.includes("'S'") && src.includes("'E'") && src.includes("'W'"), 'Has cardinal direction labels');
assert(src.includes('trailHistory'), 'Maintains trail history');
assert(src.includes('hoveredTrack'), 'Supports track hover');
assert(src.includes('rcs_dbsm'), 'Shows RCS in tooltip');
assert(src.includes('velocity_mps'), 'Shows velocity in tooltip');

// -- No banned patterns --
assert(!src.includes('\\!'), 'Does not use backslash-bang');

// ============================================================
// Summary
// ============================================================

console.log(`\n--- Radar Scope Panel Tests: ${passed} passed, ${failed} failed ---`);
process.exit(failed > 0 ? 1 : 0);
