// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
/**
 * TRITIUM-SC Behavior Analysis Panel tests
 * Tests BehaviorAnalysisPanelDef structure, DOM creation, render functions,
 * pattern list, anomaly list, severity bars, type bars, activity heatmap,
 * sparkline, XSS prevention, mount/unmount lifecycle, and cyberpunk theme.
 * Run: node tests/js/test_behavior_analysis_panel.js
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

// Load the behavior-analysis-panel.js
const panelCode = fs.readFileSync(__dirname + '/../../src/frontend/js/command/panels/behavior-analysis-panel.js', 'utf8');
const panelPlain = panelCode
    .replace(/^export\s+const\s+/gm, 'var ')
    .replace(/^export\s+/gm, '')
    .replace(/^import\s+.*$/gm, '');
vm.runInContext(panelPlain, ctx);

const BehaviorAnalysisPanelDef = ctx.BehaviorAnalysisPanelDef;

// ============================================================
// 1. PanelDef structure
// ============================================================

console.log('\n--- BehaviorAnalysisPanelDef structure ---');

(function testHasId() {
    assert(BehaviorAnalysisPanelDef.id === 'behavior-analysis', 'id is "behavior-analysis"');
})();

(function testHasTitle() {
    assert(BehaviorAnalysisPanelDef.title === 'BEHAVIOR ANALYSIS', 'title is "BEHAVIOR ANALYSIS"');
})();

(function testHasCreate() {
    assert(typeof BehaviorAnalysisPanelDef.create === 'function', 'create is a function');
})();

(function testHasMount() {
    assert(typeof BehaviorAnalysisPanelDef.mount === 'function', 'mount is a function');
})();

(function testHasUnmount() {
    assert(typeof BehaviorAnalysisPanelDef.unmount === 'function', 'unmount is a function');
})();

(function testDefaultPosition() {
    assert(BehaviorAnalysisPanelDef.defaultPosition !== undefined, 'has defaultPosition');
    assert(typeof BehaviorAnalysisPanelDef.defaultPosition.x === 'number', 'defaultPosition.x is a number');
    assert(typeof BehaviorAnalysisPanelDef.defaultPosition.y === 'number', 'defaultPosition.y is a number');
})();

(function testDefaultSize() {
    assert(BehaviorAnalysisPanelDef.defaultSize !== undefined, 'has defaultSize');
    assert(BehaviorAnalysisPanelDef.defaultSize.w === 480, 'defaultSize.w is 480');
    assert(BehaviorAnalysisPanelDef.defaultSize.h === 620, 'defaultSize.h is 620');
})();

// ============================================================
// 2. create() DOM structure
// ============================================================

console.log('\n--- create() DOM structure ---');

(function testCreateReturnsElement() {
    const el = BehaviorAnalysisPanelDef.create({});
    assert(el !== null && el !== undefined, 'create() returns an element');
    assert(el.className === 'behavior-analysis', 'className is "behavior-analysis"');
})();

(function testCreateHasContentBinding() {
    const el = BehaviorAnalysisPanelDef.create({});
    assert(el.innerHTML.includes('data-bind="behav-content"'), 'DOM has behav-content data-bind');
})();

(function testCreateHasTimestampBinding() {
    const el = BehaviorAnalysisPanelDef.create({});
    assert(el.innerHTML.includes('data-bind="behav-timestamp"'), 'DOM has behav-timestamp data-bind');
})();

(function testCreateHasRefreshButton() {
    const el = BehaviorAnalysisPanelDef.create({});
    assert(el.innerHTML.includes('data-action="refresh-behavior"'), 'DOM has refresh action button');
})();

(function testCreateHasLoadingText() {
    const el = BehaviorAnalysisPanelDef.create({});
    assert(el.innerHTML.includes('Loading behavior analysis'), 'DOM has loading placeholder');
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
    const result = vm.runInContext('_statCard("Patterns", "12", "#00f0ff")', ctx);
    assert(result.includes('Patterns'), '_statCard shows label');
    assert(result.includes('12'), '_statCard shows value');
})();

(function testTypeBarsFunction() {
    const fn = vm.runInContext('typeof _typeBars', ctx);
    assert(fn === 'function', '_typeBars function exists');
})();

(function testTypeBarsOutput() {
    const result = vm.runInContext('_typeBars({ loitering: 5, transit: 3, patrol: 2 })', ctx);
    assert(result.includes('loitering'), '_typeBars shows type name');
    assert(result.includes('5'), '_typeBars shows count');
})();

(function testTypeBarsEmpty() {
    const result = vm.runInContext('_typeBars({})', ctx);
    assert(result.includes('No pattern types'), '_typeBars shows empty message');
})();

(function testSeverityBarsFunction() {
    const fn = vm.runInContext('typeof _severityBars', ctx);
    assert(fn === 'function', '_severityBars function exists');
})();

(function testSeverityBarsOutput() {
    const result = vm.runInContext('_severityBars({ critical: 2, warning: 5, info: 10 })', ctx);
    assert(result.includes('critical'), '_severityBars shows severity name');
    assert(result.includes('2'), '_severityBars shows count');
})();

(function testSeverityBarsEmpty() {
    const result = vm.runInContext('_severityBars({})', ctx);
    assert(result.includes('No anomalies'), '_severityBars shows empty message');
})();

(function testPatternListFunction() {
    const fn = vm.runInContext('typeof _patternList', ctx);
    assert(fn === 'function', '_patternList function exists');
})();

(function testPatternListOutput() {
    const result = vm.runInContext(`_patternList([
        { target_id: "ble_aa:bb", behavior_type: "loitering", confidence: 0.85, samples: 10, duration_s: 300 }
    ], 10)`, ctx);
    assert(result.includes('ble_aa:bb'), '_patternList shows target ID');
    assert(result.includes('loitering'), '_patternList shows behavior type');
    assert(result.includes('85%'), '_patternList shows confidence');
})();

(function testPatternListEmpty() {
    const result = vm.runInContext('_patternList([], 10)', ctx);
    assert(result.includes('No patterns detected'), '_patternList shows empty state');
})();

(function testAnomalyListFunction() {
    const fn = vm.runInContext('typeof _anomalyList', ctx);
    assert(fn === 'function', '_anomalyList function exists');
})();

(function testAnomalyListOutput() {
    const result = vm.runInContext(`_anomalyList([
        { target_id: "wifi_test", anomaly_type: "speed_change", severity: "warning", description: "Moved faster than usual" }
    ], 10)`, ctx);
    assert(result.includes('wifi_test'), '_anomalyList shows target ID');
    assert(result.includes('speed_change'), '_anomalyList shows anomaly type');
    assert(result.includes('WARNING'), '_anomalyList shows severity badge');
})();

(function testAnomalyListEmpty() {
    const result = vm.runInContext('_anomalyList([], 10)', ctx);
    assert(result.includes('No anomalies detected'), '_anomalyList shows empty state');
})();

(function testActivityHeatmapFunction() {
    const fn = vm.runInContext('typeof _activityHeatmap', ctx);
    assert(fn === 'function', '_activityHeatmap function exists');
})();

(function testActivityHeatmapOutput() {
    // Create a pattern with a known timestamp (2026-03-25 14:00 UTC is a Wednesday)
    const result = vm.runInContext(`_activityHeatmap([
        { timestamp: 1774710000 },
        { timestamp: 1774713600 },
    ])`, ctx);
    assert(result.includes('Mon'), '_activityHeatmap shows day labels');
    assert(result.includes('grid'), '_activityHeatmap uses CSS grid');
})();

(function testActivityHeatmapEmpty() {
    const result = vm.runInContext('_activityHeatmap([])', ctx);
    assert(result.includes('No activity data'), '_activityHeatmap shows empty message');
})();

(function testSvgSparklineFunction() {
    const fn = vm.runInContext('typeof _svgSparkline', ctx);
    assert(fn === 'function', '_svgSparkline function exists');
})();

(function testSvgSparklineOutput() {
    const result = vm.runInContext('_svgSparkline([3, 5, 2, 7], 200, 30, "#fcee0a")', ctx);
    assert(result.includes('<svg'), '_svgSparkline returns SVG');
    assert(result.includes('polyline'), '_svgSparkline has polyline');
})();

// ============================================================
// 4. XSS prevention
// ============================================================

console.log('\n--- XSS prevention ---');

(function testEscFunction() {
    const fn = vm.runInContext('typeof _esc', ctx);
    assert(fn === 'function', '_esc function is available');
})();

(function testPatternListXss() {
    const result = vm.runInContext(`_patternList([
        { target_id: "<script>alert(1)</script>", behavior_type: "loitering", confidence: 0.5 }
    ], 10)`, ctx);
    assert(!result.includes('<script>'), 'Pattern list escapes HTML in target_id');
})();

(function testAnomalyListXss() {
    const result = vm.runInContext(`_anomalyList([
        { target_id: "safe", anomaly_type: "<img onerror=x>", severity: "info", description: "<b>bold</b>" }
    ], 10)`, ctx);
    assert(!result.includes('<img'), 'Anomaly list escapes HTML in anomaly_type');
    assert(!result.includes('<b>'), 'Anomaly list escapes HTML in description');
})();

// ============================================================
// 5. mount() wiring
// ============================================================

console.log('\n--- mount() ---');

(function testMountDoesNotCrash() {
    const bodyEl = createMockElement('div');
    const panel = { _behavTimer: null };

    let threw = false;
    try {
        BehaviorAnalysisPanelDef.mount(bodyEl, panel);
    } catch (e) {
        threw = true;
        console.error('mount() error:', e);
    }
    assert(!threw, 'mount() does not crash');
    if (panel._behavTimer) clearInterval(panel._behavTimer);
})();

(function testMountSetsTimer() {
    const bodyEl = createMockElement('div');
    const panel = { _behavTimer: null };

    BehaviorAnalysisPanelDef.mount(bodyEl, panel);
    assert(panel._behavTimer !== null, 'mount() sets auto-refresh timer');
    clearInterval(panel._behavTimer);
})();

// ============================================================
// 6. unmount() cleanup
// ============================================================

console.log('\n--- unmount() ---');

(function testUnmountDoesNotCrash() {
    let threw = false;
    try {
        BehaviorAnalysisPanelDef.unmount(createMockElement('div'), {});
    } catch (e) {
        threw = true;
    }
    assert(!threw, 'unmount() does not throw');
})();

(function testUnmountClearsTimer() {
    const bodyEl = createMockElement('div');
    const panel = { _behavTimer: null };

    BehaviorAnalysisPanelDef.mount(bodyEl, panel);
    assert(panel._behavTimer !== null, 'Timer was set by mount');
    BehaviorAnalysisPanelDef.unmount(bodyEl, panel);
    assert(panel._behavTimer === null, 'unmount() clears timer');
})();

// ============================================================
// 7. Cyberpunk theme
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
// 8. _renderBehavior function
// ============================================================

console.log('\n--- _renderBehavior function ---');

(function testRenderFunction() {
    const fn = vm.runInContext('typeof _renderBehavior', ctx);
    assert(fn === 'function', '_renderBehavior function exists');
})();

(function testRenderWithEmptyData() {
    const contentEl = createMockElement('div');
    vm.runInContext(`(function(el) {
        _renderBehavior(el, { patterns: [], anomalies: [], stats: {} });
    })`, ctx)(contentEl);
    assert(contentEl.innerHTML.includes('No patterns detected'), '_renderBehavior shows empty patterns state');
    assert(contentEl.innerHTML.includes('No anomalies detected'), '_renderBehavior shows empty anomalies state');
})();

(function testRenderWithData() {
    const contentEl = createMockElement('div');
    vm.runInContext(`(function(el) {
        _renderBehavior(el, {
            patterns: [{ target_id: 'target_1', behavior_type: 'patrol', confidence: 0.9, samples: 5 }],
            anomalies: [{ target_id: 'target_2', anomaly_type: 'speed', severity: 'warning' }],
            stats: { total_patterns: 1, targets_with_patterns: 1, total_anomalies: 1, pattern_types: { patrol: 1 }, anomaly_severities: { warning: 1 } },
        });
    })`, ctx)(contentEl);
    assert(contentEl.innerHTML.includes('target_1'), '_renderBehavior shows pattern target ID');
    assert(contentEl.innerHTML.includes('patrol'), '_renderBehavior shows behavior type in bars');
})();

// ============================================================
// Summary
// ============================================================

console.log('\n' + '='.repeat(50));
console.log(`Results: ${passed} passed, ${failed} failed`);
console.log('='.repeat(50));
process.exit(failed > 0 ? 1 : 0);
