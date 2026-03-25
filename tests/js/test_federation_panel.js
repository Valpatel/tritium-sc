// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
/**
 * TRITIUM-SC Federation Panel tests
 * Tests FederationPanelDef: identity, size, create, destroy, cleanup.
 * Run: node tests/js/test_federation_panel.js
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
            const fieldMatch = sel.match(/\[data-field="([^"]+)"\]/);
            if (fieldMatch) {
                const mock = createMockElement('input');
                mock._fieldName = fieldMatch[1];
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
    confirm: () => true,
    document: {
        createElement: createMockElement,
        getElementById: () => null,
        querySelector: () => null,
        addEventListener() {},
        removeEventListener() {},
    },
    window: {},
    fetch: () => Promise.resolve({ ok: true, json: () => Promise.resolve({ sites: [], total_sites: 0 }) }),
    performance: { now: () => Date.now() },
};

const ctx = vm.createContext(sandbox);

// Load events.js (EventBus)
const eventsCode = fs.readFileSync(__dirname + '/../../../tritium-lib/web/events.js', 'utf8');
const eventsPlain = eventsCode
    .replace(/^export\s+/gm, '')
    .replace(/^import\s+.*$/gm, '');
vm.runInContext(eventsPlain, ctx);

// Load panel-utils.js (shared helpers)
const panelUtilsCode = fs.readFileSync(__dirname + '/../../src/frontend/js/command/panel-utils.js', 'utf8');
const panelUtilsPlain = panelUtilsCode
    .replace(/^export\s+/gm, '')
    .replace(/^import\s+.*$/gm, '');
vm.runInContext(panelUtilsPlain, ctx);

// Load federation.js panel
const fedCode = fs.readFileSync(__dirname + '/../../src/frontend/js/command/panels/federation.js', 'utf8');
const fedPlain = fedCode
    .replace(/^export\s+const\s+/gm, 'var ')
    .replace(/^export\s+/gm, '')
    .replace(/^import\s+.*$/gm, '');
vm.runInContext(fedPlain, ctx);

const FederationPanelDef = ctx.FederationPanelDef;

// ============================================================
// 1. Panel identity
// ============================================================

console.log('\n--- FederationPanelDef identity ---');

assert(FederationPanelDef.id === 'federation', 'id is "federation"');
assert(FederationPanelDef.title === 'FEDERATION SITES', 'title is "FEDERATION SITES"');

// ============================================================
// 2. Default size
// ============================================================

console.log('\n--- Default size ---');

assert(FederationPanelDef.defaultSize.w === 560, 'defaultSize.w is 560');
assert(FederationPanelDef.defaultSize.h === 640, 'defaultSize.h is 640');

// ============================================================
// 3. create() returns panel element
// ============================================================

console.log('\n--- create() ---');

(function testCreateReturnsDomElement() {
    const panel = {};
    const el = FederationPanelDef.create(panel);
    assert(el !== null && el !== undefined, 'create() returns an element');
    assert(el.className === 'fed-panel-inner', 'create() element has className "fed-panel-inner"');
})();

// ============================================================
// 4. destroy method
// ============================================================

console.log('\n--- destroy ---');

assert(typeof FederationPanelDef.destroy === 'function', 'destroy is a function');

// ============================================================
// 5. cleanup timer on destroy
// ============================================================

console.log('\n--- lifecycle ---');

(function testCleanupTimerOnDestroy() {
    const panel = {};
    FederationPanelDef.create(panel);
    assert(panel._fedCleanup !== undefined, 'create() sets panel._fedCleanup');
    let threw = false;
    try {
        FederationPanelDef.destroy(panel);
    } catch (e) {
        threw = true;
    }
    assert(!threw, 'destroy() does not throw');
})();

// ============================================================
// 6. DOM structure checks
// ============================================================

console.log('\n--- DOM structure ---');

(function testDomHasSummary() {
    const panel = {};
    const el = FederationPanelDef.create(panel);
    const html = el.innerHTML;
    assert(html.includes('data-bind="summary"'), 'DOM contains summary data-bind');
})();

(function testDomHasSiteList() {
    const panel = {};
    const el = FederationPanelDef.create(panel);
    const html = el.innerHTML;
    assert(html.includes('data-bind="site-list"'), 'DOM contains site-list data-bind');
})();

(function testDomHasAddForm() {
    const panel = {};
    const el = FederationPanelDef.create(panel);
    const html = el.innerHTML;
    assert(html.includes('data-bind="add-form"'), 'DOM contains add-form data-bind');
})();

(function testDomHasAddSiteButton() {
    const panel = {};
    const el = FederationPanelDef.create(panel);
    const html = el.innerHTML;
    assert(html.includes('data-action="add-site"'), 'DOM contains add-site action button');
})();

(function testDomHasRefreshButton() {
    const panel = {};
    const el = FederationPanelDef.create(panel);
    const html = el.innerHTML;
    assert(html.includes('data-action="refresh"'), 'DOM contains refresh action button');
})();

(function testDomHasHealthGrid() {
    const panel = {};
    const el = FederationPanelDef.create(panel);
    const html = el.innerHTML;
    assert(html.includes('data-bind="health-grid"'), 'DOM contains health-grid data-bind');
})();

(function testDomHasThreatsList() {
    const panel = {};
    const el = FederationPanelDef.create(panel);
    const html = el.innerHTML;
    assert(html.includes('data-bind="threats-list"'), 'DOM contains threats-list data-bind');
})();

// ============================================================
// Summary
// ============================================================

console.log('\n' + '='.repeat(40));
console.log(`Results: ${passed} passed, ${failed} failed`);
console.log('='.repeat(40));
process.exit(failed > 0 ? 1 : 0);
