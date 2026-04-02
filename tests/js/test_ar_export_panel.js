// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
/**
 * TRITIUM-SC AR Export Panel tests
 * Tests ArExportPanelDef structure, DOM creation, render functions,
 * target list, alliance colors, stat cards, filter controls,
 * XSS prevention, mount/unmount lifecycle, and cyberpunk theme.
 * Run: node tests/js/test_ar_export_panel.js
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
        checked: false,
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
        select() {},
        click() {},
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
    URLSearchParams,
    document: {
        createElement: createMockElement,
        getElementById: () => null,
        querySelector: () => null,
        addEventListener() {},
        removeEventListener() {},
        body: { appendChild() {}, removeChild() {} },
        execCommand() {},
    },
    window: {},
    fetch: () => Promise.resolve({ ok: true, json: () => Promise.resolve({ version: '1.0', target_count: 0, targets: [] }) }),
    performance: { now: () => Date.now() },
    navigator: { clipboard: { writeText: () => Promise.resolve() } },
    URL: { createObjectURL: () => 'blob://test', revokeObjectURL: () => {} },
    Blob: function(data, opts) { this.data = data; this.type = opts?.type; },
};

const ctx = vm.createContext(sandbox);

// Load utils.js (_esc)
const utilsCode = fs.readFileSync(__dirname + '/../../../tritium-lib/web/utils.js', 'utf8');
const utilsPlain = utilsCode
    .replace(/^export\s+/gm, '')
    .replace(/^import\s+.*$/gm, '');
vm.runInContext(utilsPlain, ctx);

// Load the ar-export-panel.js
const panelCode = fs.readFileSync(__dirname + '/../../src/frontend/js/command/panels/ar-export-panel.js', 'utf8');
const panelPlain = panelCode
    .replace(/^export\s+const\s+/gm, 'var ')
    .replace(/^export\s+/gm, '')
    .replace(/^import\s+.*$/gm, '');
vm.runInContext(panelPlain, ctx);

const ArExportPanelDef = ctx.ArExportPanelDef;

// ============================================================
// 1. PanelDef structure
// ============================================================

console.log('\n--- ArExportPanelDef structure ---');

(function testHasId() {
    assert(ArExportPanelDef.id === 'ar-export', 'id is "ar-export"');
})();

(function testHasTitle() {
    assert(ArExportPanelDef.title === 'AR EXPORT', 'title is "AR EXPORT"');
})();

(function testHasCreate() {
    assert(typeof ArExportPanelDef.create === 'function', 'create is a function');
})();

(function testHasMount() {
    assert(typeof ArExportPanelDef.mount === 'function', 'mount is a function');
})();

(function testHasUnmount() {
    assert(typeof ArExportPanelDef.unmount === 'function', 'unmount is a function');
})();

(function testDefaultPosition() {
    assert(ArExportPanelDef.defaultPosition !== undefined, 'has defaultPosition');
    assert(typeof ArExportPanelDef.defaultPosition.x === 'number', 'defaultPosition.x is a number');
    assert(typeof ArExportPanelDef.defaultPosition.y === 'number', 'defaultPosition.y is a number');
})();

(function testDefaultSize() {
    assert(ArExportPanelDef.defaultSize !== undefined, 'has defaultSize');
    assert(ArExportPanelDef.defaultSize.w === 480, 'defaultSize.w is 480');
    assert(ArExportPanelDef.defaultSize.h === 500, 'defaultSize.h is 500');
})();

// ============================================================
// 2. create() DOM structure
// ============================================================

console.log('\n--- create() DOM structure ---');

(function testCreateReturnsElement() {
    const el = ArExportPanelDef.create({});
    assert(el !== null && el !== undefined, 'create() returns an element');
    assert(el.className === 'ar-export-panel', 'className is "ar-export-panel"');
})();

(function testCreateHasContentBinding() {
    const el = ArExportPanelDef.create({});
    assert(el.innerHTML.includes('data-bind="ar-content"'), 'DOM has ar-content data-bind');
})();

(function testCreateHasTimestampBinding() {
    const el = ArExportPanelDef.create({});
    assert(el.innerHTML.includes('data-bind="ar-timestamp"'), 'DOM has ar-timestamp data-bind');
})();

(function testCreateHasRefreshButton() {
    const el = ArExportPanelDef.create({});
    assert(el.innerHTML.includes('data-action="refresh-ar"'), 'DOM has refresh action button');
})();

(function testCreateHasCopyButton() {
    const el = ArExportPanelDef.create({});
    assert(el.innerHTML.includes('data-action="copy-ar-json"'), 'DOM has copy JSON action button');
})();

(function testCreateHasDownloadButton() {
    const el = ArExportPanelDef.create({});
    assert(el.innerHTML.includes('data-action="download-ar-json"'), 'DOM has download JSON action button');
})();

(function testCreateHasAllianceFilter() {
    const el = ArExportPanelDef.create({});
    assert(el.innerHTML.includes('data-bind="ar-alliance"'), 'DOM has alliance filter select');
})();

(function testCreateHasConfidenceSlider() {
    const el = ArExportPanelDef.create({});
    assert(el.innerHTML.includes('data-bind="ar-confidence"'), 'DOM has confidence slider');
})();

(function testCreateHasAutoRefreshCheckbox() {
    const el = ArExportPanelDef.create({});
    assert(el.innerHTML.includes('data-bind="ar-auto-refresh"'), 'DOM has auto-refresh checkbox');
})();

(function testCreateHasMaxInput() {
    const el = ArExportPanelDef.create({});
    assert(el.innerHTML.includes('data-bind="ar-max"'), 'DOM has max targets input');
})();

(function testCreateHasLoadingText() {
    const el = ArExportPanelDef.create({});
    assert(el.innerHTML.includes('Loading AR export data'), 'DOM has loading placeholder');
})();

// ============================================================
// 3. Render helper functions
// ============================================================

console.log('\n--- Render helpers ---');

(function testAllianceColorFunction() {
    const fn = vm.runInContext('typeof _allianceColor', ctx);
    assert(fn === 'function', '_allianceColor function exists');
})();

(function testAllianceColorFriendly() {
    const result = vm.runInContext('_allianceColor("friendly")', ctx);
    assert(result === '#05ffa1', '_allianceColor("friendly") returns green');
})();

(function testAllianceColorHostile() {
    const result = vm.runInContext('_allianceColor("hostile")', ctx);
    assert(result === '#ff2a6d', '_allianceColor("hostile") returns magenta');
})();

(function testAllianceColorUnknown() {
    const result = vm.runInContext('_allianceColor("unknown")', ctx);
    assert(result === '#666', '_allianceColor("unknown") returns dim');
})();

(function testStatCardFunction() {
    const fn = vm.runInContext('typeof _statCard', ctx);
    assert(fn === 'function', '_statCard function exists');
})();

(function testStatCardOutput() {
    const result = vm.runInContext('_statCard("Total", "42", "#00f0ff")', ctx);
    assert(result.includes('Total'), '_statCard shows label');
    assert(result.includes('42'), '_statCard shows value');
})();

// ============================================================
// 4. Target list rendering
// ============================================================

console.log('\n--- AR target list ---');

(function testArTargetListFunction() {
    const fn = vm.runInContext('typeof _arTargetList', ctx);
    assert(fn === 'function', '_arTargetList function exists');
})();

(function testArTargetListEmpty() {
    const result = vm.runInContext('_arTargetList([])', ctx);
    assert(result.includes('No targets available'), '_arTargetList shows empty state');
})();

(function testArTargetListWithData() {
    const result = vm.runInContext(`_arTargetList([
        { id: "t_abc123", name: "Unit Alpha", type: "person", alliance: "friendly", confidence: 0.9, speed: 1.5, heading: 90, lat: 30.12345, lng: -97.54321, alt: 1.7 }
    ])`, ctx);
    assert(result.includes('t_abc123'), '_arTargetList shows target ID');
    assert(result.includes('Unit Alpha'), '_arTargetList shows name');
    assert(result.includes('person'), '_arTargetList shows type');
    assert(result.includes('FRIENDLY'), '_arTargetList shows alliance');
    assert(result.includes('90'), '_arTargetList shows heading');
    assert(result.includes('1.5'), '_arTargetList shows speed');
})();

// ============================================================
// 5. Full render function
// ============================================================

console.log('\n--- _renderArExport ---');

(function testRenderFunction() {
    const fn = vm.runInContext('typeof _renderArExport', ctx);
    assert(fn === 'function', '_renderArExport function exists');
})();

(function testRenderWithNull() {
    const contentEl = createMockElement('div');
    vm.runInContext(`(function(el) {
        _renderArExport(el, null);
    })`, ctx)(contentEl);
    assert(contentEl.innerHTML.includes('No data'), '_renderArExport shows null state');
})();

(function testRenderWithError() {
    const contentEl = createMockElement('div');
    vm.runInContext(`(function(el) {
        _renderArExport(el, { error: "Connection failed", targets: [], target_count: 0 });
    })`, ctx)(contentEl);
    assert(contentEl.innerHTML.includes('Connection failed'), '_renderArExport shows error');
})();

(function testRenderWithTargets() {
    const contentEl = createMockElement('div');
    vm.runInContext(`(function(el) {
        _renderArExport(el, {
            version: "1.0",
            target_count: 2,
            targets: [
                { id: "t1", name: "Alpha", type: "person", alliance: "friendly", confidence: 0.9, speed: 0, heading: 0, lat: 30.0, lng: -97.0, alt: 1.7 },
                { id: "t2", name: "Bravo", type: "vehicle", alliance: "hostile", confidence: 0.5, speed: 10.0, heading: 180, lat: 30.1, lng: -97.1, alt: 1.5 },
            ],
        });
    })`, ctx)(contentEl);
    assert(contentEl.innerHTML.includes('t1'), '_renderArExport shows first target');
    assert(contentEl.innerHTML.includes('t2'), '_renderArExport shows second target');
    assert(contentEl.innerHTML.includes('AR TARGETS (2)'), '_renderArExport shows count header');
})();

(function testRenderAllianceCounts() {
    const contentEl = createMockElement('div');
    vm.runInContext(`(function(el) {
        _renderArExport(el, {
            version: "1.0",
            target_count: 3,
            targets: [
                { id: "a", alliance: "friendly", confidence: 0.9 },
                { id: "b", alliance: "hostile", confidence: 0.5 },
                { id: "c", alliance: "unknown", confidence: 0.3 },
            ],
        });
    })`, ctx)(contentEl);
    // Stats cards should show Friendly: 1, Hostile: 1, Unknown: 1
    assert(contentEl.innerHTML.includes('Friendly'), '_renderArExport shows friendly stat card');
    assert(contentEl.innerHTML.includes('Hostile'), '_renderArExport shows hostile stat card');
})();

// ============================================================
// 6. XSS prevention
// ============================================================

console.log('\n--- XSS prevention ---');

(function testArTargetListXss() {
    const result = vm.runInContext(`_arTargetList([
        { id: "<script>alert(1)</script>", name: "<img onerror=x>", type: "x", alliance: "x", confidence: 0, speed: 0, heading: 0, lat: 0, lng: 0, alt: 0 }
    ])`, ctx);
    assert(!result.includes('<script>'), 'AR target list escapes script tags');
    assert(!result.includes('<img onerror'), 'AR target list escapes img injection');
})();

(function testStatCardXss() {
    const result = vm.runInContext('_statCard("<script>x</script>", "1", "#fff")', ctx);
    assert(!result.includes('<script>'), '_statCard escapes HTML in label');
})();

// ============================================================
// 7. mount() wiring
// ============================================================

console.log('\n--- mount() ---');

(function testMountDoesNotCrash() {
    const bodyEl = createMockElement('div');
    const panel = { _arTimer: null };

    let threw = false;
    try {
        ArExportPanelDef.mount(bodyEl, panel);
    } catch (e) {
        threw = true;
        console.error('mount() error:', e);
    }
    assert(!threw, 'mount() does not crash');
    if (panel._arTimer) clearInterval(panel._arTimer);
})();

// ============================================================
// 8. unmount() cleanup
// ============================================================

console.log('\n--- unmount() ---');

(function testUnmountDoesNotCrash() {
    let threw = false;
    try {
        ArExportPanelDef.unmount(createMockElement('div'), {});
    } catch (e) {
        threw = true;
    }
    assert(!threw, 'unmount() does not throw');
})();

(function testUnmountClearsTimer() {
    const panel = { _arTimer: setInterval(() => {}, 10000) };
    ArExportPanelDef.unmount(createMockElement('div'), panel);
    assert(panel._arTimer === null, 'unmount() clears timer');
})();

// ============================================================
// 9. Cyberpunk theme
// ============================================================

console.log('\n--- Cyberpunk theme ---');

(function testCyanConst() {
    const val = vm.runInContext('CYAN', ctx);
    assert(val === '#00f0ff', 'CYAN is #00f0ff');
})();

(function testMagentaConst() {
    const val = vm.runInContext('MAGENTA', ctx);
    assert(val === '#ff2a6d', 'MAGENTA is #ff2a6d');
})();

(function testGreenConst() {
    const val = vm.runInContext('GREEN', ctx);
    assert(val === '#05ffa1', 'GREEN is #05ffa1');
})();

(function testYellowConst() {
    const val = vm.runInContext('YELLOW', ctx);
    assert(val === '#fcee0a', 'YELLOW is #fcee0a');
})();

(function testRefreshInterval() {
    const val = vm.runInContext('REFRESH_MS', ctx);
    assert(val === 5000, 'REFRESH_MS is 5000 (5s)');
})();

// ============================================================
// Summary
// ============================================================

console.log('\n' + '='.repeat(50));
console.log(`Results: ${passed} passed, ${failed} failed`);
console.log('='.repeat(50));
process.exit(failed > 0 ? 1 : 0);
