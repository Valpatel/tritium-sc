// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
/**
 * TRITIUM-SC Correlation Dashboard Panel tests
 * Tests CorrelationDashboardPanelDef structure, DOM creation, render functions,
 * stat cards, sparkline, strategy bars, confidence distribution, correlation list,
 * XSS prevention, mount/unmount lifecycle, and cyberpunk theme.
 * Run: node tests/js/test_correlation_dashboard_panel.js
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

// Load the correlation-dashboard-panel.js
const panelCode = fs.readFileSync(__dirname + '/../../src/frontend/js/command/panels/correlation-dashboard-panel.js', 'utf8');
const panelPlain = panelCode
    .replace(/^export\s+const\s+/gm, 'var ')
    .replace(/^export\s+/gm, '')
    .replace(/^import\s+.*$/gm, '');
vm.runInContext(panelPlain, ctx);

const CorrelationDashboardPanelDef = ctx.CorrelationDashboardPanelDef;

// ============================================================
// 1. PanelDef structure
// ============================================================

console.log('\n--- CorrelationDashboardPanelDef structure ---');

(function testHasId() {
    assert(CorrelationDashboardPanelDef.id === 'correlation-dashboard', 'id is "correlation-dashboard"');
})();

(function testHasTitle() {
    assert(CorrelationDashboardPanelDef.title === 'CORRELATION ENGINE', 'title is "CORRELATION ENGINE"');
})();

(function testHasCreate() {
    assert(typeof CorrelationDashboardPanelDef.create === 'function', 'create is a function');
})();

(function testHasMount() {
    assert(typeof CorrelationDashboardPanelDef.mount === 'function', 'mount is a function');
})();

(function testHasUnmount() {
    assert(typeof CorrelationDashboardPanelDef.unmount === 'function', 'unmount is a function');
})();

(function testDefaultPosition() {
    assert(CorrelationDashboardPanelDef.defaultPosition !== undefined, 'has defaultPosition');
    assert(typeof CorrelationDashboardPanelDef.defaultPosition.x === 'number', 'defaultPosition.x is a number');
    assert(typeof CorrelationDashboardPanelDef.defaultPosition.y === 'number', 'defaultPosition.y is a number');
})();

(function testDefaultSize() {
    assert(CorrelationDashboardPanelDef.defaultSize !== undefined, 'has defaultSize');
    assert(CorrelationDashboardPanelDef.defaultSize.w === 480, 'defaultSize.w is 480');
    assert(CorrelationDashboardPanelDef.defaultSize.h === 560, 'defaultSize.h is 560');
})();

// ============================================================
// 2. create() returns DOM element with expected structure
// ============================================================

console.log('\n--- create() DOM structure ---');

(function testCreateReturnsElement() {
    const el = CorrelationDashboardPanelDef.create({});
    assert(el !== null && el !== undefined, 'create() returns an element');
    assert(el.className === 'correlation-dashboard', 'className is "correlation-dashboard"');
})();

(function testCreateHasContentBinding() {
    const el = CorrelationDashboardPanelDef.create({});
    const html = el.innerHTML;
    assert(html.includes('data-bind="corr-content"'), 'DOM has corr-content data-bind');
})();

(function testCreateHasTimestampBinding() {
    const el = CorrelationDashboardPanelDef.create({});
    const html = el.innerHTML;
    assert(html.includes('data-bind="corr-timestamp"'), 'DOM has corr-timestamp data-bind');
})();

(function testCreateHasRefreshButton() {
    const el = CorrelationDashboardPanelDef.create({});
    const html = el.innerHTML;
    assert(html.includes('data-action="refresh-corr"'), 'DOM has refresh action button');
})();

(function testCreateHasLoadingText() {
    const el = CorrelationDashboardPanelDef.create({});
    const html = el.innerHTML;
    assert(html.includes('Loading correlation engine'), 'DOM has loading placeholder');
})();

// ============================================================
// 3. Render helper functions
// ============================================================

console.log('\n--- Render helpers ---');

(function testStatCardFunction() {
    const fn = vm.runInContext('typeof _statCard', ctx);
    assert(fn === 'function', '_statCard function exists');
})();

(function testStatCardOutput() {
    const result = vm.runInContext('_statCard("Test Label", "42", "#00f0ff")', ctx);
    assert(result.includes('Test Label'), '_statCard shows label');
    assert(result.includes('42'), '_statCard shows value');
    assert(result.includes('#00f0ff'), '_statCard uses provided color');
})();

(function testStrategyBarsFunction() {
    const fn = vm.runInContext('typeof _strategyBars', ctx);
    assert(fn === 'function', '_strategyBars function exists');
})();

(function testStrategyBarsOutput() {
    const result = vm.runInContext('_strategyBars({ proximity: 10, temporal: 5, signal: 3 })', ctx);
    assert(result.includes('proximity'), '_strategyBars shows strategy name');
    assert(result.includes('10'), '_strategyBars shows count');
})();

(function testStrategyBarsEmpty() {
    const result = vm.runInContext('_strategyBars({})', ctx);
    assert(result.includes('No strategy data'), '_strategyBars shows empty message');
})();

(function testConfidenceDistributionFunction() {
    const fn = vm.runInContext('typeof _confidenceDistribution', ctx);
    assert(fn === 'function', '_confidenceDistribution function exists');
})();

(function testConfidenceDistributionOutput() {
    const result = vm.runInContext('_confidenceDistribution([{ confidence: 0.9 }, { confidence: 0.3 }, { confidence: 0.5 }])', ctx);
    assert(result.includes('80-100%'), '_confidenceDistribution shows bucket labels');
})();

(function testConfidenceDistributionEmpty() {
    const result = vm.runInContext('_confidenceDistribution([])', ctx);
    assert(result.includes('No correlations'), '_confidenceDistribution shows empty message');
})();

(function testCorrelationListFunction() {
    const fn = vm.runInContext('typeof _correlationList', ctx);
    assert(fn === 'function', '_correlationList function exists');
})();

(function testCorrelationListOutput() {
    const result = vm.runInContext(`_correlationList([
        { primary_id: "ble_aa:bb", secondary_id: "det_person_1", confidence: 0.85, reason: "co-located", strategies: [{ name: "proximity", score: 0.9 }] }
    ], 10)`, ctx);
    assert(result.includes('ble_aa:bb'), '_correlationList shows primary ID');
    assert(result.includes('det_person_1'), '_correlationList shows secondary ID');
    assert(result.includes('85.0%'), '_correlationList shows confidence %');
})();

(function testCorrelationListEmpty() {
    const result = vm.runInContext('_correlationList([], 10)', ctx);
    assert(result.includes('No active correlations'), '_correlationList shows empty state');
})();

(function testSvgSparklineFunction() {
    const fn = vm.runInContext('typeof _svgSparkline', ctx);
    assert(fn === 'function', '_svgSparkline function exists');
})();

(function testSvgSparklineOutput() {
    const result = vm.runInContext('_svgSparkline([0.5, 0.7, 0.6, 0.8], 200, 30, "#00f0ff")', ctx);
    assert(result.includes('<svg'), '_svgSparkline returns SVG');
    assert(result.includes('polyline'), '_svgSparkline has polyline');
})();

(function testSvgSparklineNoData() {
    const result = vm.runInContext('_svgSparkline([], 200, 30, "#00f0ff")', ctx);
    assert(result.includes('NO DATA'), '_svgSparkline shows NO DATA for empty');
})();

// ============================================================
// 4. XSS prevention
// ============================================================

console.log('\n--- XSS prevention ---');

(function testEscFunction() {
    const fn = vm.runInContext('typeof _esc', ctx);
    assert(fn === 'function', '_esc function is available');
})();

(function testEscEscapesHtml() {
    const result = vm.runInContext('_esc("<script>alert(1)</script>")', ctx);
    assert(!result.includes('<script>'), '_esc escapes script tags');
})();

(function testCorrelationListXss() {
    const result = vm.runInContext(`_correlationList([
        { primary_id: "<img onerror=alert(1)>", secondary_id: "safe", confidence: 0.5, strategies: [] }
    ], 10)`, ctx);
    assert(!result.includes('<img'), 'Correlation list escapes HTML in primary_id');
})();

(function testStatCardXss() {
    const result = vm.runInContext('_statCard("<script>x</script>", "1", "#fff")', ctx);
    assert(!result.includes('<script>'), '_statCard escapes HTML in label');
})();

// ============================================================
// 5. mount() wiring
// ============================================================

console.log('\n--- mount() ---');

(function testMountDoesNotCrash() {
    const bodyEl = createMockElement('div');
    const panel = { _corrTimer: null };

    let threw = false;
    try {
        CorrelationDashboardPanelDef.mount(bodyEl, panel);
    } catch (e) {
        threw = true;
        console.error('mount() error:', e);
    }
    assert(!threw, 'mount() does not crash');
    if (panel._corrTimer) clearInterval(panel._corrTimer);
})();

(function testMountSetsTimer() {
    const bodyEl = createMockElement('div');
    const panel = { _corrTimer: null };

    CorrelationDashboardPanelDef.mount(bodyEl, panel);
    assert(panel._corrTimer !== null, 'mount() sets auto-refresh timer');
    clearInterval(panel._corrTimer);
})();

// ============================================================
// 6. unmount() cleanup
// ============================================================

console.log('\n--- unmount() ---');

(function testUnmountDoesNotCrash() {
    let threw = false;
    try {
        CorrelationDashboardPanelDef.unmount(createMockElement('div'), {});
    } catch (e) {
        threw = true;
    }
    assert(!threw, 'unmount() does not throw');
})();

(function testUnmountClearsTimer() {
    const bodyEl = createMockElement('div');
    const panel = { _corrTimer: null };

    CorrelationDashboardPanelDef.mount(bodyEl, panel);
    assert(panel._corrTimer !== null, 'Timer was set by mount');
    CorrelationDashboardPanelDef.unmount(bodyEl, panel);
    assert(panel._corrTimer === null, 'unmount() clears timer');
})();

// ============================================================
// 7. Cyberpunk theme colors
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
// 8. _render function
// ============================================================

console.log('\n--- _render function ---');

(function testRenderFunction() {
    const fn = vm.runInContext('typeof _render', ctx);
    assert(fn === 'function', '_render function exists');
})();

(function testRenderWithUnavailableEngine() {
    const contentEl = createMockElement('div');
    vm.runInContext(`(function(el) {
        _render(el, { status: { available: false, status: 'stopped' }, list: null, summary: null });
    })`, ctx)(contentEl);
    assert(contentEl.innerHTML.includes('not initialized'), '_render shows unavailable banner when engine stopped');
})();

(function testRenderWithActiveData() {
    const contentEl = createMockElement('div');
    vm.runInContext(`(function(el) {
        _render(el, {
            status: { available: true, status: 'running', total_correlations: 5, high_confidence: 3, avg_confidence: 0.72, strategy_counts: { proximity: 4, temporal: 2 } },
            list: { correlations: [{ primary_id: 'a', secondary_id: 'b', confidence: 0.8, strategies: [{ name: 'proximity', score: 0.8 }] }], count: 1 },
            summary: { total: 5, high_confidence: 3, avg_confidence: 0.72, strategy_counts: { proximity: 4, temporal: 2 } },
        });
    })`, ctx)(contentEl);
    assert(contentEl.innerHTML.includes('RUNNING'), '_render shows RUNNING status');
    assert(contentEl.innerHTML.includes('proximity'), '_render shows strategy names');
})();

// ============================================================
// Summary
// ============================================================

console.log('\n' + '='.repeat(50));
console.log(`Results: ${passed} passed, ${failed} failed`);
console.log('='.repeat(50));
process.exit(failed > 0 ? 1 : 0);
