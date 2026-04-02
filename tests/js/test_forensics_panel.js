// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
/**
 * TRITIUM-SC Forensics Panel tests
 * Tests ForensicsPanelDef structure, DOM creation, render functions,
 * reconstruction list, detail view, report view, duration formatting,
 * timestamp formatting, XSS prevention, mount/unmount lifecycle,
 * and cyberpunk theme.
 * Run: node tests/js/test_forensics_panel.js
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
    encodeURIComponent,
    document: {
        createElement: createMockElement,
        getElementById: () => null,
        querySelector: () => null,
        addEventListener() {},
        removeEventListener() {},
    },
    window: {},
    fetch: () => Promise.resolve({ ok: true, json: () => Promise.resolve({}) }),
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

// Load the forensics-panel.js
const panelCode = fs.readFileSync(__dirname + '/../../src/frontend/js/command/panels/forensics-panel.js', 'utf8');
const panelPlain = panelCode
    .replace(/^export\s+const\s+/gm, 'var ')
    .replace(/^export\s+/gm, '')
    .replace(/^import\s+.*$/gm, '');
vm.runInContext(panelPlain, ctx);

const ForensicsPanelDef = ctx.ForensicsPanelDef;

// ============================================================
// 1. PanelDef structure
// ============================================================

console.log('\n--- ForensicsPanelDef structure ---');

(function testHasId() {
    assert(ForensicsPanelDef.id === 'forensics', 'id is "forensics"');
})();

(function testHasTitle() {
    assert(ForensicsPanelDef.title === 'FORENSICS', 'title is "FORENSICS"');
})();

(function testHasCreate() {
    assert(typeof ForensicsPanelDef.create === 'function', 'create is a function');
})();

(function testHasMount() {
    assert(typeof ForensicsPanelDef.mount === 'function', 'mount is a function');
})();

(function testHasUnmount() {
    assert(typeof ForensicsPanelDef.unmount === 'function', 'unmount is a function');
})();

(function testDefaultPosition() {
    assert(ForensicsPanelDef.defaultPosition !== undefined, 'has defaultPosition');
    assert(typeof ForensicsPanelDef.defaultPosition.x === 'number', 'defaultPosition.x is a number');
    assert(typeof ForensicsPanelDef.defaultPosition.y === 'number', 'defaultPosition.y is a number');
})();

(function testDefaultSize() {
    assert(ForensicsPanelDef.defaultSize !== undefined, 'has defaultSize');
    assert(ForensicsPanelDef.defaultSize.w === 520, 'defaultSize.w is 520');
    assert(ForensicsPanelDef.defaultSize.h === 600, 'defaultSize.h is 600');
})();

// ============================================================
// 2. create() DOM structure
// ============================================================

console.log('\n--- create() DOM structure ---');

(function testCreateReturnsElement() {
    const el = ForensicsPanelDef.create({});
    assert(el !== null && el !== undefined, 'create() returns an element');
    assert(el.className === 'forensics-panel', 'className is "forensics-panel"');
})();

(function testCreateHasContentBinding() {
    const el = ForensicsPanelDef.create({});
    assert(el.innerHTML.includes('data-bind="forensics-content"'), 'DOM has forensics-content data-bind');
})();

(function testCreateHasDetailBinding() {
    const el = ForensicsPanelDef.create({});
    assert(el.innerHTML.includes('data-bind="forensics-detail"'), 'DOM has forensics-detail data-bind');
})();

(function testCreateHasTimestampBinding() {
    const el = ForensicsPanelDef.create({});
    assert(el.innerHTML.includes('data-bind="forensics-timestamp"'), 'DOM has forensics-timestamp data-bind');
})();

(function testCreateHasRefreshButton() {
    const el = ForensicsPanelDef.create({});
    assert(el.innerHTML.includes('data-action="refresh-forensics"'), 'DOM has refresh action button');
})();

(function testCreateHasCreateButton() {
    const el = ForensicsPanelDef.create({});
    assert(el.innerHTML.includes('data-action="create-recon"'), 'DOM has create-recon action button');
})();

(function testCreateHasTimeInputs() {
    const el = ForensicsPanelDef.create({});
    assert(el.innerHTML.includes('data-bind="recon-start"'), 'DOM has recon-start input');
    assert(el.innerHTML.includes('data-bind="recon-end"'), 'DOM has recon-end input');
})();

(function testCreateHasBoundsInputs() {
    const el = ForensicsPanelDef.create({});
    assert(el.innerHTML.includes('data-bind="recon-north"'), 'DOM has recon-north input');
    assert(el.innerHTML.includes('data-bind="recon-south"'), 'DOM has recon-south input');
    assert(el.innerHTML.includes('data-bind="recon-east"'), 'DOM has recon-east input');
    assert(el.innerHTML.includes('data-bind="recon-west"'), 'DOM has recon-west input');
})();

(function testCreateHasLoadingText() {
    const el = ForensicsPanelDef.create({});
    assert(el.innerHTML.includes('Loading forensic reconstructions'), 'DOM has loading placeholder');
})();

// ============================================================
// 3. Render helper functions
// ============================================================

console.log('\n--- Render helpers ---');

(function testFormatDurationFunction() {
    const fn = vm.runInContext('typeof _formatDuration', ctx);
    assert(fn === 'function', '_formatDuration function exists');
})();

(function testFormatDurationSeconds() {
    const result = vm.runInContext('_formatDuration(45)', ctx);
    assert(result === '45s', '_formatDuration(45) returns "45s"');
})();

(function testFormatDurationMinutes() {
    const result = vm.runInContext('_formatDuration(185)', ctx);
    assert(result === '3m 5s', '_formatDuration(185) returns "3m 5s"');
})();

(function testFormatDurationHours() {
    const result = vm.runInContext('_formatDuration(7320)', ctx);
    assert(result === '2h 2m', '_formatDuration(7320) returns "2h 2m"');
})();

(function testFormatDurationZero() {
    const result = vm.runInContext('_formatDuration(0)', ctx);
    assert(result === '0s', '_formatDuration(0) returns "0s"');
})();

(function testFormatDurationNull() {
    const result = vm.runInContext('_formatDuration(null)', ctx);
    assert(result === '--', '_formatDuration(null) returns "--"');
})();

(function testStatCardFunction() {
    const fn = vm.runInContext('typeof _statCard', ctx);
    assert(fn === 'function', '_statCard function exists');
})();

(function testStatCardOutput() {
    const result = vm.runInContext('_statCard("Events", "42", "#00f0ff")', ctx);
    assert(result.includes('Events'), '_statCard shows label');
    assert(result.includes('42'), '_statCard shows value');
    assert(result.includes('#00f0ff'), '_statCard uses provided color');
})();

(function testFormatTimestampFunction() {
    const fn = vm.runInContext('typeof _formatTimestamp', ctx);
    assert(fn === 'function', '_formatTimestamp function exists');
})();

(function testFormatTimestampNull() {
    const result = vm.runInContext('_formatTimestamp(null)', ctx);
    assert(result === '--', '_formatTimestamp(null) returns "--"');
})();

// ============================================================
// 4. Reconstruction list rendering
// ============================================================

console.log('\n--- Reconstruction list ---');

(function testReconstructionListFunction() {
    const fn = vm.runInContext('typeof _reconstructionList', ctx);
    assert(fn === 'function', '_reconstructionList function exists');
})();

(function testReconstructionListEmpty() {
    const result = vm.runInContext('_reconstructionList([])', ctx);
    assert(result.includes('No reconstructions'), '_reconstructionList shows empty state');
})();

(function testReconstructionListWithData() {
    const result = vm.runInContext(`_reconstructionList([
        { id: "recon_abc123", start: 1711929600, end: 1711933200, event_count: 50, target_count: 5, status: "complete" }
    ])`, ctx);
    assert(result.includes('recon_abc12'), '_reconstructionList shows reconstruction ID');
    assert(result.includes('50 events'), '_reconstructionList shows event count');
    assert(result.includes('5 targets'), '_reconstructionList shows target count');
    assert(result.includes('COMPLETE'), '_reconstructionList shows status');
})();

// ============================================================
// 5. Reconstruction detail rendering
// ============================================================

console.log('\n--- Reconstruction detail ---');

(function testReconstructionDetailFunction() {
    const fn = vm.runInContext('typeof _reconstructionDetail', ctx);
    assert(fn === 'function', '_reconstructionDetail function exists');
})();

(function testReconstructionDetailNull() {
    const result = vm.runInContext('_reconstructionDetail(null)', ctx);
    assert(result.includes('Select a reconstruction'), '_reconstructionDetail shows null state');
})();

(function testReconstructionDetailError() {
    const result = vm.runInContext('_reconstructionDetail({ error: "Not found" })', ctx);
    assert(result.includes('Not found'), '_reconstructionDetail shows error');
})();

(function testReconstructionDetailWithData() {
    const result = vm.runInContext(`_reconstructionDetail({
        id: "recon_xyz",
        events: [{ type: "sighting", timestamp: 1711929600 }],
        targets: [{ target_id: "ble_aabb", name: "Phone A", alliance: "unknown" }],
        timeline: [{ timestamp: 1711929600, event_type: "SIGHTING", description: "BLE device detected" }],
        duration_s: 3600,
    })`, ctx);
    assert(result.includes('recon_xy'), '_reconstructionDetail shows ID');
    assert(result.includes('GENERATE REPORT'), '_reconstructionDetail has report button');
    assert(result.includes('BACK'), '_reconstructionDetail has back button');
    assert(result.includes('ble_aabb'), '_reconstructionDetail shows target ID');
    assert(result.includes('BLE device detected'), '_reconstructionDetail shows timeline event');
})();

// ============================================================
// 6. Report rendering
// ============================================================

console.log('\n--- Report view ---');

(function testReportViewFunction() {
    const fn = vm.runInContext('typeof _reportView', ctx);
    assert(fn === 'function', '_reportView function exists');
})();

(function testReportViewNull() {
    const result = vm.runInContext('_reportView(null)', ctx);
    assert(result === '', '_reportView(null) returns empty string');
})();

(function testReportViewError() {
    const result = vm.runInContext('_reportView({ error: "Generation failed" })', ctx);
    assert(result.includes('Generation failed'), '_reportView shows error');
})();

(function testReportViewWithData() {
    const result = vm.runInContext(`_reportView({
        title: "Test Incident",
        created_by: "operator",
        created_at: 1711929600,
        classification: "confidential",
        findings: ["Hostile target detected at gate", "BLE device correlated with camera"],
        recommendations: ["Increase patrol frequency"],
    })`, ctx);
    assert(result.includes('Test Incident'), '_reportView shows title');
    assert(result.includes('CONFIDENTIAL'), '_reportView shows classification');
    assert(result.includes('Hostile target detected'), '_reportView shows finding');
    assert(result.includes('Increase patrol'), '_reportView shows recommendation');
})();

// ============================================================
// 7. XSS prevention
// ============================================================

console.log('\n--- XSS prevention ---');

(function testReconstructionListXss() {
    const result = vm.runInContext(`_reconstructionList([
        { id: "<script>alert(1)</script>", start: 0, end: 1, event_count: 0, status: "complete" }
    ])`, ctx);
    assert(!result.includes('<script>'), 'Reconstruction list escapes script tags');
})();

(function testReconstructionDetailXss() {
    const result = vm.runInContext(`_reconstructionDetail({
        id: "safe",
        events: [],
        targets: [{ target_id: "<img onerror=x>", name: "<b>bad</b>", alliance: "hostile" }],
        timeline: [{ timestamp: 0, event_type: "x", description: "<script>x</script>" }],
        duration_s: 0,
    })`, ctx);
    assert(!result.includes('<img onerror'), '_reconstructionDetail escapes img injection');
    assert(!result.includes('<script>'), '_reconstructionDetail escapes script tags');
})();

(function testReportViewXss() {
    const result = vm.runInContext(`_reportView({
        title: "<script>alert(1)</script>",
        created_by: "op",
        findings: ["<img src=x onerror=alert(1)>"],
        recommendations: [],
    })`, ctx);
    assert(!result.includes('<script>'), '_reportView escapes script in title');
    assert(!result.includes('<img src=x'), '_reportView escapes img in findings');
})();

(function testStatCardXss() {
    const result = vm.runInContext('_statCard("<script>x</script>", "1", "#fff")', ctx);
    assert(!result.includes('<script>'), '_statCard escapes HTML in label');
})();

// ============================================================
// 8. mount() wiring
// ============================================================

console.log('\n--- mount() ---');

(function testMountDoesNotCrash() {
    const bodyEl = createMockElement('div');
    const panel = { _forensicsTimer: null };

    let threw = false;
    try {
        ForensicsPanelDef.mount(bodyEl, panel);
    } catch (e) {
        threw = true;
        console.error('mount() error:', e);
    }
    assert(!threw, 'mount() does not crash');
    if (panel._forensicsTimer) clearInterval(panel._forensicsTimer);
})();

(function testMountSetsTimer() {
    const bodyEl = createMockElement('div');
    const panel = { _forensicsTimer: null };

    ForensicsPanelDef.mount(bodyEl, panel);
    assert(panel._forensicsTimer !== null, 'mount() sets auto-refresh timer');
    clearInterval(panel._forensicsTimer);
})();

// ============================================================
// 9. unmount() cleanup
// ============================================================

console.log('\n--- unmount() ---');

(function testUnmountDoesNotCrash() {
    let threw = false;
    try {
        ForensicsPanelDef.unmount(createMockElement('div'), {});
    } catch (e) {
        threw = true;
    }
    assert(!threw, 'unmount() does not throw');
})();

(function testUnmountClearsTimer() {
    const bodyEl = createMockElement('div');
    const panel = { _forensicsTimer: null };

    ForensicsPanelDef.mount(bodyEl, panel);
    assert(panel._forensicsTimer !== null, 'Timer was set by mount');
    ForensicsPanelDef.unmount(bodyEl, panel);
    assert(panel._forensicsTimer === null, 'unmount() clears timer');
})();

// ============================================================
// 10. Cyberpunk theme
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
    assert(val === 15000, 'REFRESH_MS is 15000 (15s)');
})();

// ============================================================
// Summary
// ============================================================

console.log('\n' + '='.repeat(50));
console.log(`Results: ${passed} passed, ${failed} failed`);
console.log('='.repeat(50));
process.exit(failed > 0 ? 1 : 0);
