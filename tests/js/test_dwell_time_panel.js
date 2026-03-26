// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
/**
 * TRITIUM-SC Dwell Time Panel tests
 * Tests DwellTimePanelDef structure, DOM creation, render functions,
 * active dwell list, history list, zone occupancy, severity distribution,
 * duration formatting, sparkline, XSS prevention, mount/unmount lifecycle,
 * and cyberpunk theme.
 * Run: node tests/js/test_dwell_time_panel.js
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
};

const ctx = vm.createContext(sandbox);

// Load utils.js (_esc)
const utilsCode = fs.readFileSync(__dirname + '/../../../tritium-lib/web/utils.js', 'utf8');
const utilsPlain = utilsCode
    .replace(/^export\s+/gm, '')
    .replace(/^import\s+.*$/gm, '');
vm.runInContext(utilsPlain, ctx);

// Load the dwell-time-panel.js
const panelCode = fs.readFileSync(__dirname + '/../../src/frontend/js/command/panels/dwell-time-panel.js', 'utf8');
const panelPlain = panelCode
    .replace(/^export\s+const\s+/gm, 'var ')
    .replace(/^export\s+/gm, '')
    .replace(/^import\s+.*$/gm, '');
vm.runInContext(panelPlain, ctx);

const DwellTimePanelDef = ctx.DwellTimePanelDef;

// ============================================================
// 1. PanelDef structure
// ============================================================

console.log('\n--- DwellTimePanelDef structure ---');

(function testHasId() {
    assert(DwellTimePanelDef.id === 'dwell-time', 'id is "dwell-time"');
})();

(function testHasTitle() {
    assert(DwellTimePanelDef.title === 'DWELL TIME', 'title is "DWELL TIME"');
})();

(function testHasCreate() {
    assert(typeof DwellTimePanelDef.create === 'function', 'create is a function');
})();

(function testHasMount() {
    assert(typeof DwellTimePanelDef.mount === 'function', 'mount is a function');
})();

(function testHasUnmount() {
    assert(typeof DwellTimePanelDef.unmount === 'function', 'unmount is a function');
})();

(function testDefaultPosition() {
    assert(DwellTimePanelDef.defaultPosition !== undefined, 'has defaultPosition');
    assert(typeof DwellTimePanelDef.defaultPosition.x === 'number', 'defaultPosition.x is a number');
    assert(typeof DwellTimePanelDef.defaultPosition.y === 'number', 'defaultPosition.y is a number');
})();

(function testDefaultSize() {
    assert(DwellTimePanelDef.defaultSize !== undefined, 'has defaultSize');
    assert(DwellTimePanelDef.defaultSize.w === 480, 'defaultSize.w is 480');
    assert(DwellTimePanelDef.defaultSize.h === 580, 'defaultSize.h is 580');
})();

// ============================================================
// 2. create() DOM structure
// ============================================================

console.log('\n--- create() DOM structure ---');

(function testCreateReturnsElement() {
    const el = DwellTimePanelDef.create({});
    assert(el !== null && el !== undefined, 'create() returns an element');
    assert(el.className === 'dwell-time-panel', 'className is "dwell-time-panel"');
})();

(function testCreateHasContentBinding() {
    const el = DwellTimePanelDef.create({});
    assert(el.innerHTML.includes('data-bind="dwell-content"'), 'DOM has dwell-content data-bind');
})();

(function testCreateHasTimestampBinding() {
    const el = DwellTimePanelDef.create({});
    assert(el.innerHTML.includes('data-bind="dwell-timestamp"'), 'DOM has dwell-timestamp data-bind');
})();

(function testCreateHasRefreshButton() {
    const el = DwellTimePanelDef.create({});
    assert(el.innerHTML.includes('data-action="refresh-dwell"'), 'DOM has refresh action button');
})();

(function testCreateHasLoadingText() {
    const el = DwellTimePanelDef.create({});
    assert(el.innerHTML.includes('Loading dwell time data'), 'DOM has loading placeholder');
})();

// ============================================================
// 3. Duration formatting
// ============================================================

console.log('\n--- Duration formatting ---');

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

// ============================================================
// 4. Render helper functions
// ============================================================

console.log('\n--- Render helpers ---');

(function testStatCardFunction() {
    const fn = vm.runInContext('typeof _statCard', ctx);
    assert(fn === 'function', '_statCard function exists');
})();

(function testStatCardOutput() {
    const result = vm.runInContext('_statCard("Active", "3", "#00f0ff")', ctx);
    assert(result.includes('Active'), '_statCard shows label');
    assert(result.includes('3'), '_statCard shows value');
})();

(function testActiveDwellListFunction() {
    const fn = vm.runInContext('typeof _activeDwellList', ctx);
    assert(fn === 'function', '_activeDwellList function exists');
})();

(function testActiveDwellListOutput() {
    const result = vm.runInContext(`_activeDwellList([
        { target_id: "ble_aa:bb", target_name: "Phone A", duration_s: 600, severity: "extended", target_type: "phone" }
    ])`, ctx);
    assert(result.includes('Phone A'), '_activeDwellList shows target name');
    assert(result.includes('10m 0s'), '_activeDwellList shows formatted duration');
    assert(result.includes('EXTENDED'), '_activeDwellList shows severity badge');
})();

(function testActiveDwellListEmpty() {
    const result = vm.runInContext('_activeDwellList([])', ctx);
    assert(result.includes('No active dwells'), '_activeDwellList shows empty state');
})();

(function testHistoryDwellListFunction() {
    const fn = vm.runInContext('typeof _historyDwellList', ctx);
    assert(fn === 'function', '_historyDwellList function exists');
})();

(function testHistoryDwellListOutput() {
    const result = vm.runInContext(`_historyDwellList([
        { target_id: "wifi_test", duration_s: 300, severity: "normal" }
    ], 10)`, ctx);
    assert(result.includes('wifi_test'), '_historyDwellList shows target ID');
    assert(result.includes('5m 0s'), '_historyDwellList shows formatted duration');
})();

(function testHistoryDwellListEmpty() {
    const result = vm.runInContext('_historyDwellList([], 10)', ctx);
    assert(result.includes('No dwell history'), '_historyDwellList shows empty state');
})();

(function testZoneOccupancyFunction() {
    const fn = vm.runInContext('typeof _zoneOccupancy', ctx);
    assert(fn === 'function', '_zoneOccupancy function exists');
})();

(function testZoneOccupancyOutput() {
    const result = vm.runInContext(`_zoneOccupancy([
        { target_type: "phone", duration_s: 1200 },
        { target_type: "phone", duration_s: 600 },
        { target_type: "vehicle", duration_s: 300 },
    ])`, ctx);
    assert(result.includes('phone'), '_zoneOccupancy shows category');
    assert(result.includes('vehicle'), '_zoneOccupancy shows second category');
})();

(function testZoneOccupancyEmpty() {
    const result = vm.runInContext('_zoneOccupancy([])', ctx);
    assert(result.includes('No zone occupancy'), '_zoneOccupancy shows empty state');
})();

(function testSeverityDistributionFunction() {
    const fn = vm.runInContext('typeof _severityDistribution', ctx);
    assert(fn === 'function', '_severityDistribution function exists');
})();

(function testSeverityDistributionOutput() {
    const result = vm.runInContext(`_severityDistribution([
        { severity: "normal" },
        { severity: "normal" },
        { severity: "extended" },
        { severity: "critical" },
    ])`, ctx);
    assert(result.includes('normal'), '_severityDistribution shows severity names');
    assert(result.includes('critical'), '_severityDistribution shows critical');
    assert(result.includes('50%'), '_severityDistribution shows percentage');
})();

(function testSeverityDistributionEmpty() {
    const result = vm.runInContext('_severityDistribution([])', ctx);
    assert(result.includes('No severity data'), '_severityDistribution shows empty state');
})();

(function testSvgSparklineFunction() {
    const fn = vm.runInContext('typeof _svgSparkline', ctx);
    assert(fn === 'function', '_svgSparkline function exists');
})();

(function testSvgSparklineOutput() {
    const result = vm.runInContext('_svgSparkline([1, 3, 2, 5], 200, 30, "#00f0ff")', ctx);
    assert(result.includes('<svg'), '_svgSparkline returns SVG');
    assert(result.includes('polyline'), '_svgSparkline has polyline');
})();

(function testSeverityBadgeFunction() {
    const fn = vm.runInContext('typeof _severityBadge', ctx);
    assert(fn === 'function', '_severityBadge function exists');
})();

(function testSeverityBadgeOutput() {
    const result = vm.runInContext('_severityBadge("critical")', ctx);
    assert(result.includes('CRITICAL'), '_severityBadge shows label');
    assert(result.includes('#ff2a6d'), '_severityBadge uses magenta for critical');
})();

// ============================================================
// 5. XSS prevention
// ============================================================

console.log('\n--- XSS prevention ---');

(function testActiveDwellListXss() {
    const result = vm.runInContext(`_activeDwellList([
        { target_id: "<script>alert(1)</script>", target_name: "<img onerror=x>", duration_s: 100, severity: "normal" }
    ])`, ctx);
    assert(!result.includes('<script>'), 'Active dwell list escapes script tags');
    assert(!result.includes('<img'), 'Active dwell list escapes img tags');
})();

(function testHistoryDwellListXss() {
    const result = vm.runInContext(`_historyDwellList([
        { target_id: '"><svg onload=x>', duration_s: 60, severity: "normal" }
    ], 10)`, ctx);
    assert(!result.includes('<svg onload'), 'History dwell list escapes SVG injection');
})();

// ============================================================
// 6. mount() wiring
// ============================================================

console.log('\n--- mount() ---');

(function testMountDoesNotCrash() {
    const bodyEl = createMockElement('div');
    const panel = { _dwellTimer: null };

    let threw = false;
    try {
        DwellTimePanelDef.mount(bodyEl, panel);
    } catch (e) {
        threw = true;
        console.error('mount() error:', e);
    }
    assert(!threw, 'mount() does not crash');
    if (panel._dwellTimer) clearInterval(panel._dwellTimer);
})();

(function testMountSetsTimer() {
    const bodyEl = createMockElement('div');
    const panel = { _dwellTimer: null };

    DwellTimePanelDef.mount(bodyEl, panel);
    assert(panel._dwellTimer !== null, 'mount() sets auto-refresh timer');
    clearInterval(panel._dwellTimer);
})();

// ============================================================
// 7. unmount() cleanup
// ============================================================

console.log('\n--- unmount() ---');

(function testUnmountDoesNotCrash() {
    let threw = false;
    try {
        DwellTimePanelDef.unmount(createMockElement('div'), {});
    } catch (e) {
        threw = true;
    }
    assert(!threw, 'unmount() does not throw');
})();

(function testUnmountClearsTimer() {
    const bodyEl = createMockElement('div');
    const panel = { _dwellTimer: null };

    DwellTimePanelDef.mount(bodyEl, panel);
    assert(panel._dwellTimer !== null, 'Timer was set by mount');
    DwellTimePanelDef.unmount(bodyEl, panel);
    assert(panel._dwellTimer === null, 'unmount() clears timer');
})();

// ============================================================
// 8. Cyberpunk theme
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

(function testRefreshInterval() {
    const val = vm.runInContext('REFRESH_MS', ctx);
    assert(val === 10000, 'REFRESH_MS is 10000 (10s)');
})();

// ============================================================
// 9. _renderDwell function
// ============================================================

console.log('\n--- _renderDwell function ---');

(function testRenderFunction() {
    const fn = vm.runInContext('typeof _renderDwell', ctx);
    assert(fn === 'function', '_renderDwell function exists');
})();

(function testRenderWithUnavailable() {
    const contentEl = createMockElement('div');
    vm.runInContext(`(function(el) {
        _renderDwell(el, { active: { dwells: [], source: "unavailable" }, history: { dwells: [] } });
    })`, ctx)(contentEl);
    assert(contentEl.innerHTML.includes('not initialized'), '_renderDwell shows unavailable banner');
})();

(function testRenderWithActiveDwells() {
    const contentEl = createMockElement('div');
    vm.runInContext(`(function(el) {
        _renderDwell(el, {
            active: { dwells: [{ target_id: 'test_1', duration_s: 600, severity: 'extended' }], source: 'live' },
            history: { dwells: [{ target_id: 'test_2', duration_s: 300, severity: 'normal' }] },
        });
    })`, ctx)(contentEl);
    assert(contentEl.innerHTML.includes('test_1'), '_renderDwell shows active target');
    assert(contentEl.innerHTML.includes('test_2'), '_renderDwell shows history target');
})();

// ============================================================
// Summary
// ============================================================

console.log('\n' + '='.repeat(50));
console.log(`Results: ${passed} passed, ${failed} failed`);
console.log('='.repeat(50));
process.exit(failed > 0 ? 1 : 0);
