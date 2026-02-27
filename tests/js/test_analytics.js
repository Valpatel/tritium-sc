/**
 * TRITIUM-SC Analytics View Tests
 * Tests all exported functions (initAnalyticsView, loadAnalytics,
 * filterByHour, filterByChannel, viewTargetFromAnalytics) and internal
 * helpers (notify, renderAnalytics, renderDailyChart, renderHourlyChart,
 * renderRecentTargets, renderChannelBreakdown, analyticsState).
 * Run: node tests/js/test_analytics.js
 */

const fs = require('fs');
const vm = require('vm');

// Simple test runner
let passed = 0, failed = 0;
function assert(cond, msg) {
    if (!cond) { console.error('FAIL:', msg); failed++; }
    else { console.log('PASS:', msg); passed++; }
}
function assertContains(str, sub, msg) {
    assert(typeof str === 'string' && str.includes(sub), msg + ` (expected "${sub}" in output)`);
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
        set innerHTML(val) { _innerHTML = val; },
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
        querySelector(sel) { return null; },
        querySelectorAll(sel) { return []; },
        closest(sel) { return null; },
        _eventListeners: eventListeners,
        _classList: classList,
    };
    return el;
}

// Track which element IDs are created/accessed and their textContent/innerHTML
const domElements = {};

function resetDom() {
    for (const key of Object.keys(domElements)) {
        delete domElements[key];
    }
}

function getOrCreateElement(id) {
    if (!domElements[id]) {
        domElements[id] = createMockElement('div');
        domElements[id]._id = id;
    }
    return domElements[id];
}

// Track fetch calls
let fetchCalls = [];
let fetchResponse = { ok: true, status: 200, json: () => Promise.resolve({}) };

// Track console.log and console.error
let consoleLogs = [];
let consoleErrors = [];

// Track sessionStorage
const sessionStore = {};

// Track setTimeout calls
let timeoutCallbacks = [];

const sandbox = {
    Math, Date, console: {
        log(...args) { consoleLogs.push(args.join(' ')); },
        error(...args) { consoleErrors.push(args.join(' ')); },
        warn(...args) {},
    },
    Map, Set, Array, Object, Number, String, Boolean,
    Infinity, NaN, undefined, parseInt, parseFloat, isNaN, isFinite, JSON,
    Promise, clearTimeout, setInterval, clearInterval, Error,
    RegExp, Symbol,
    setTimeout: (fn, ms) => { timeoutCallbacks.push({ fn, ms }); return timeoutCallbacks.length; },
    document: {
        createElement(tag) { return createMockElement(tag); },
        getElementById(id) { return getOrCreateElement(id); },
        querySelector(sel) { return null; },
        addEventListener() {},
        removeEventListener() {},
        head: createMockElement('head'),
    },
    window: {},
    sessionStorage: {
        _store: sessionStore,
        setItem(k, v) { sessionStore[k] = String(v); },
        getItem(k) { return sessionStore[k] || null; },
        removeItem(k) { delete sessionStore[k]; },
    },
    fetch: (...args) => {
        fetchCalls.push(args);
        return Promise.resolve(fetchResponse);
    },
    performance: { now: () => Date.now() },
    showNotification: null,
};

sandbox.window = sandbox;
const ctx = vm.createContext(sandbox);

// Load analytics.js
const analyticsCode = fs.readFileSync(
    __dirname + '/../../frontend/js/analytics.js', 'utf8'
);
vm.runInContext(analyticsCode, ctx);

// ============================================================
// Helper to reset state between tests
// ============================================================
function resetState() {
    resetDom();
    fetchCalls = [];
    consoleLogs = [];
    consoleErrors = [];
    timeoutCallbacks = [];
    for (const k of Object.keys(sessionStore)) delete sessionStore[k];
    // Reset analyticsState
    vm.runInContext('analyticsState.data = null; analyticsState.days = 7;', ctx);
    // Reset window.TRITIUM
    vm.runInContext('window.TRITIUM = null;', ctx);
}

// ============================================================
// 1. Module loaded — window exports exist
// ============================================================

console.log('\n--- Module exports ---');

(function testInitAnalyticsViewExported() {
    const t = vm.runInContext('typeof window.initAnalyticsView', ctx);
    assert(t === 'function', 'window.initAnalyticsView is a function');
})();

(function testLoadAnalyticsExported() {
    const t = vm.runInContext('typeof window.loadAnalytics', ctx);
    assert(t === 'function', 'window.loadAnalytics is a function');
})();

(function testFilterByHourExported() {
    const t = vm.runInContext('typeof window.filterByHour', ctx);
    assert(t === 'function', 'window.filterByHour is a function');
})();

(function testFilterByChannelExported() {
    const t = vm.runInContext('typeof window.filterByChannel', ctx);
    assert(t === 'function', 'window.filterByChannel is a function');
})();

(function testViewTargetFromAnalyticsExported() {
    const t = vm.runInContext('typeof window.viewTargetFromAnalytics', ctx);
    assert(t === 'function', 'window.viewTargetFromAnalytics is a function');
})();

// ============================================================
// 2. Internal functions exist
// ============================================================

console.log('\n--- Internal functions ---');

(function testNotifyExists() {
    const t = vm.runInContext('typeof notify', ctx);
    assert(t === 'function', 'notify() function exists');
})();

(function testRenderAnalyticsExists() {
    const t = vm.runInContext('typeof renderAnalytics', ctx);
    assert(t === 'function', 'renderAnalytics() function exists');
})();

(function testRenderDailyChartExists() {
    const t = vm.runInContext('typeof renderDailyChart', ctx);
    assert(t === 'function', 'renderDailyChart() function exists');
})();

(function testRenderHourlyChartExists() {
    const t = vm.runInContext('typeof renderHourlyChart', ctx);
    assert(t === 'function', 'renderHourlyChart() function exists');
})();

(function testRenderRecentTargetsExists() {
    const t = vm.runInContext('typeof renderRecentTargets', ctx);
    assert(t === 'function', 'renderRecentTargets() function exists');
})();

(function testRenderChannelBreakdownExists() {
    const t = vm.runInContext('typeof renderChannelBreakdown', ctx);
    assert(t === 'function', 'renderChannelBreakdown() function exists');
})();

// ============================================================
// 3. analyticsState
// ============================================================

console.log('\n--- analyticsState ---');

(function testAnalyticsStateExists() {
    const t = vm.runInContext('typeof analyticsState', ctx);
    assert(t === 'object', 'analyticsState exists and is an object');
})();

(function testAnalyticsStateDefaultData() {
    const val = vm.runInContext('analyticsState.data', ctx);
    assert(val === null, 'analyticsState.data defaults to null');
})();

(function testAnalyticsStateDefaultDays() {
    const val = vm.runInContext('analyticsState.days', ctx);
    assert(val === 7, 'analyticsState.days defaults to 7');
})();

// ============================================================
// 4. notify() helper
// ============================================================

console.log('\n--- notify() ---');

(function testNotifyFallsBackToConsoleLog() {
    resetState();
    vm.runInContext('notify("ALERT", "test message", "info")', ctx);
    const found = consoleLogs.some(l => l.includes('[INFO] ALERT: test message'));
    assert(found, 'notify() falls back to console.log when no showNotification');
})();

(function testNotifyWithTypeError() {
    resetState();
    vm.runInContext('notify("ERR", "broken", "error")', ctx);
    const found = consoleLogs.some(l => l.includes('[ERROR] ERR: broken'));
    assert(found, 'notify() formats error type correctly in fallback');
})();

(function testNotifyDefaultTypeIsInfo() {
    resetState();
    vm.runInContext('notify("TEST", "msg")', ctx);
    const found = consoleLogs.some(l => l.includes('[INFO]'));
    assert(found, 'notify() defaults to info type');
})();

(function testNotifyUsesShowNotificationIfAvailable() {
    resetState();
    let called = false;
    sandbox.showNotification = (t, m, ty) => { called = true; };
    vm.runInContext('notify("X", "Y", "warn")', ctx);
    assert(called, 'notify() calls showNotification when it exists');
    sandbox.showNotification = null;
})();

(function testNotifyUsesTritiumShowNotification() {
    resetState();
    sandbox.showNotification = null;
    let called = false;
    vm.runInContext('window.TRITIUM = { showNotification: function(t, m, ty) { window._notifyCalled = true; } }', ctx);
    vm.runInContext('notify("A", "B", "info")', ctx);
    const val = vm.runInContext('window._notifyCalled', ctx);
    assert(val === true, 'notify() uses window.TRITIUM.showNotification as second fallback');
})();

// ============================================================
// 5. renderDailyChart()
// ============================================================

console.log('\n--- renderDailyChart() ---');

(function testRenderDailyChartNull() {
    resetState();
    vm.runInContext('renderDailyChart(null)', ctx);
    const container = getOrCreateElement('analytics-daily-chart');
    assertContains(container.innerHTML, 'No data available',
        'renderDailyChart(null) shows "No data available"');
})();

(function testRenderDailyChartEmptyObject() {
    resetState();
    vm.runInContext('renderDailyChart({})', ctx);
    const container = getOrCreateElement('analytics-daily-chart');
    assertContains(container.innerHTML, 'No data available',
        'renderDailyChart({}) shows "No data available"');
})();

(function testRenderDailyChartClearsLabelsOnEmpty() {
    resetState();
    const labels = getOrCreateElement('analytics-daily-labels');
    labels.innerHTML = 'previous content';
    vm.runInContext('renderDailyChart(null)', ctx);
    assert(labels.innerHTML === '', 'renderDailyChart(null) clears labels');
})();

(function testRenderDailyChartWithData() {
    resetState();
    vm.runInContext(`renderDailyChart({
        '2026-02-20': { person: 10, vehicle: 5, total: 15 },
        '2026-02-21': { person: 20, vehicle: 8, total: 28 }
    })`, ctx);
    const container = getOrCreateElement('analytics-daily-chart');
    assertContains(container.innerHTML, 'daily-bar-group',
        'renderDailyChart() generates bar group elements');
})();

(function testRenderDailyChartBarHeightsPersonVehicle() {
    resetState();
    vm.runInContext(`renderDailyChart({
        '2026-02-20': { person: 10, vehicle: 5, total: 15 },
        '2026-02-21': { person: 20, vehicle: 8, total: 28 }
    })`, ctx);
    const container = getOrCreateElement('analytics-daily-chart');
    // The max total is 28, so the second day should have full-height person bar
    assertContains(container.innerHTML, 'title="20 people"',
        'renderDailyChart() includes person count in title');
    assertContains(container.innerHTML, 'title="8 vehicles"',
        'renderDailyChart() includes vehicle count in title');
})();

(function testRenderDailyChartSortsByDate() {
    resetState();
    vm.runInContext(`renderDailyChart({
        '2026-02-22': { person: 3, vehicle: 1, total: 4 },
        '2026-02-20': { person: 10, vehicle: 5, total: 15 }
    })`, ctx);
    const container = getOrCreateElement('analytics-daily-chart');
    const html = container.innerHTML;
    // Check that 20 appears before 22 in the output
    const idx20 = html.indexOf('title="10 people"');
    const idx22 = html.indexOf('title="3 people"');
    assert(idx20 < idx22, 'renderDailyChart() sorts entries by date ascending');
})();

(function testRenderDailyChartLabelsShowDayNumbers() {
    resetState();
    vm.runInContext(`renderDailyChart({
        '2026-02-20': { person: 10, vehicle: 5, total: 15 }
    })`, ctx);
    const labels = getOrCreateElement('analytics-daily-labels');
    assertContains(labels.innerHTML, '20',
        'renderDailyChart() labels contain day number');
})();

(function testRenderDailyChartZeroCounts() {
    resetState();
    vm.runInContext(`renderDailyChart({
        '2026-02-20': { person: 0, vehicle: 0, total: 0 }
    })`, ctx);
    const container = getOrCreateElement('analytics-daily-chart');
    assertContains(container.innerHTML, 'daily-bar-group',
        'renderDailyChart() handles zero counts without error');
})();

(function testRenderDailyChartMagentaForPeople() {
    resetState();
    vm.runInContext(`renderDailyChart({
        '2026-02-20': { person: 5, vehicle: 2, total: 7 }
    })`, ctx);
    const container = getOrCreateElement('analytics-daily-chart');
    assertContains(container.innerHTML, 'var(--magenta)',
        'renderDailyChart() uses magenta for people bars');
})();

(function testRenderDailyChartYellowForVehicles() {
    resetState();
    vm.runInContext(`renderDailyChart({
        '2026-02-20': { person: 5, vehicle: 2, total: 7 }
    })`, ctx);
    const container = getOrCreateElement('analytics-daily-chart');
    assertContains(container.innerHTML, 'var(--yellow)',
        'renderDailyChart() uses yellow for vehicle bars');
})();

// ============================================================
// 6. renderHourlyChart()
// ============================================================

console.log('\n--- renderHourlyChart() ---');

(function testRenderHourlyChartNull() {
    resetState();
    vm.runInContext('renderHourlyChart(null)', ctx);
    const container = getOrCreateElement('analytics-hourly-chart');
    assertContains(container.innerHTML, 'No data available',
        'renderHourlyChart(null) shows "No data available"');
})();

(function testRenderHourlyChartNonArray() {
    resetState();
    vm.runInContext('renderHourlyChart("not an array")', ctx);
    const container = getOrCreateElement('analytics-hourly-chart');
    assertContains(container.innerHTML, 'No data available',
        'renderHourlyChart(non-array) shows "No data available"');
})();

(function testRenderHourlyChartUndefined() {
    resetState();
    vm.runInContext('renderHourlyChart(undefined)', ctx);
    const container = getOrCreateElement('analytics-hourly-chart');
    assertContains(container.innerHTML, 'No data available',
        'renderHourlyChart(undefined) shows "No data available"');
})();

(function testRenderHourlyChartWithData() {
    resetState();
    const hourlyData = new Array(24).fill(0);
    hourlyData[8] = 15;
    hourlyData[12] = 30;
    hourlyData[18] = 10;
    vm.runInContext(`renderHourlyChart(${JSON.stringify(hourlyData)})`, ctx);
    const container = getOrCreateElement('analytics-hourly-chart');
    assertContains(container.innerHTML, 'hour-bar-analytics',
        'renderHourlyChart() generates bar elements');
})();

(function testRenderHourlyChartTitlesIncludeHourAndCount() {
    resetState();
    const hourlyData = new Array(24).fill(0);
    hourlyData[14] = 42;
    vm.runInContext(`renderHourlyChart(${JSON.stringify(hourlyData)})`, ctx);
    const container = getOrCreateElement('analytics-hourly-chart');
    assertContains(container.innerHTML, '14:00 - 42 detections',
        'renderHourlyChart() includes formatted hour and count in title');
})();

(function testRenderHourlyChartUseCyan() {
    resetState();
    const hourlyData = new Array(24).fill(0);
    hourlyData[0] = 5;
    vm.runInContext(`renderHourlyChart(${JSON.stringify(hourlyData)})`, ctx);
    const container = getOrCreateElement('analytics-hourly-chart');
    assertContains(container.innerHTML, 'var(--cyan)',
        'renderHourlyChart() uses cyan for bars');
})();

(function testRenderHourlyChartFilterByHourOnclick() {
    resetState();
    const hourlyData = new Array(24).fill(0);
    hourlyData[9] = 7;
    vm.runInContext(`renderHourlyChart(${JSON.stringify(hourlyData)})`, ctx);
    const container = getOrCreateElement('analytics-hourly-chart');
    assertContains(container.innerHTML, 'filterByHour(9)',
        'renderHourlyChart() wires onclick to filterByHour');
})();

(function testRenderHourlyChartAllZeros() {
    resetState();
    const hourlyData = new Array(24).fill(0);
    vm.runInContext(`renderHourlyChart(${JSON.stringify(hourlyData)})`, ctx);
    const container = getOrCreateElement('analytics-hourly-chart');
    assertContains(container.innerHTML, 'hour-bar-analytics',
        'renderHourlyChart() renders bars even with all zeros');
})();

(function testRenderHourlyChartPadsHour() {
    resetState();
    const hourlyData = new Array(24).fill(0);
    hourlyData[3] = 1;
    vm.runInContext(`renderHourlyChart(${JSON.stringify(hourlyData)})`, ctx);
    const container = getOrCreateElement('analytics-hourly-chart');
    assertContains(container.innerHTML, '03:00',
        'renderHourlyChart() pads single-digit hours with leading zero');
})();

(function testRenderHourlyChartMinHeight2Percent() {
    resetState();
    const hourlyData = new Array(24).fill(0);
    hourlyData[0] = 1;
    hourlyData[12] = 100;
    vm.runInContext(`renderHourlyChart(${JSON.stringify(hourlyData)})`, ctx);
    const container = getOrCreateElement('analytics-hourly-chart');
    // The minimum bar height should be 2%
    assertContains(container.innerHTML, 'height: 2%',
        'renderHourlyChart() enforces minimum 2% bar height');
})();

// ============================================================
// 7. renderRecentTargets()
// ============================================================

console.log('\n--- renderRecentTargets() ---');

(function testRenderRecentTargetsNull() {
    resetState();
    vm.runInContext('renderRecentTargets(null)', ctx);
    const container = getOrCreateElement('analytics-recent-targets');
    assertContains(container.innerHTML, 'No recent targets today',
        'renderRecentTargets(null) shows empty state');
})();

(function testRenderRecentTargetsEmptyArray() {
    resetState();
    vm.runInContext('renderRecentTargets([])', ctx);
    const container = getOrCreateElement('analytics-recent-targets');
    assertContains(container.innerHTML, 'No recent targets today',
        'renderRecentTargets([]) shows empty state');
})();

(function testRenderRecentTargetsUndefined() {
    resetState();
    vm.runInContext('renderRecentTargets(undefined)', ctx);
    const container = getOrCreateElement('analytics-recent-targets');
    assertContains(container.innerHTML, 'No recent targets today',
        'renderRecentTargets(undefined) shows empty state');
})();

(function testRenderRecentTargetsWithPerson() {
    resetState();
    vm.runInContext(`renderRecentTargets([
        { thumbnail_id: 'abc123', target_type: 'person', channel: 1, label: null }
    ])`, ctx);
    const container = getOrCreateElement('analytics-recent-targets');
    assertContains(container.innerHTML, 'recent-target-card',
        'renderRecentTargets() generates target card');
    assertContains(container.innerHTML, '/api/search/thumbnail/abc123',
        'renderRecentTargets() generates correct thumbnail URL');
})();

(function testRenderRecentTargetsWithVehicle() {
    resetState();
    vm.runInContext(`renderRecentTargets([
        { thumbnail_id: 'v001', target_type: 'vehicle', channel: 3 }
    ])`, ctx);
    const container = getOrCreateElement('analytics-recent-targets');
    assertContains(container.innerHTML, 'recent-target-card',
        'renderRecentTargets() renders vehicle target card');
})();

(function testRenderRecentTargetsWithLabel() {
    resetState();
    vm.runInContext(`renderRecentTargets([
        { thumbnail_id: 'l1', target_type: 'person', channel: 2, label: 'John Doe' }
    ])`, ctx);
    const container = getOrCreateElement('analytics-recent-targets');
    assertContains(container.innerHTML, 'recent-target-label',
        'renderRecentTargets() renders label element when label exists');
    assertContains(container.innerHTML, 'John Doe',
        'renderRecentTargets() includes label text');
})();

(function testRenderRecentTargetsWithoutLabel() {
    resetState();
    vm.runInContext(`renderRecentTargets([
        { thumbnail_id: 'l2', target_type: 'person', channel: 2 }
    ])`, ctx);
    const container = getOrCreateElement('analytics-recent-targets');
    assert(!container.innerHTML.includes('recent-target-label'),
        'renderRecentTargets() omits label element when no label');
})();

(function testRenderRecentTargetsChannelFallback() {
    resetState();
    vm.runInContext(`renderRecentTargets([
        { thumbnail_id: 'c1', target_type: 'person' }
    ])`, ctx);
    const container = getOrCreateElement('analytics-recent-targets');
    assertContains(container.innerHTML, 'CH?',
        'renderRecentTargets() shows "CH?" when channel is missing');
})();

(function testRenderRecentTargetsLimitsTo20() {
    resetState();
    const targets = [];
    for (let i = 0; i < 30; i++) {
        targets.push({ thumbnail_id: `t${i}`, target_type: 'person', channel: 1 });
    }
    vm.runInContext(`renderRecentTargets(${JSON.stringify(targets)})`, ctx);
    const container = getOrCreateElement('analytics-recent-targets');
    const cardCount = (container.innerHTML.match(/recent-target-card/g) || []).length;
    assert(cardCount === 20, 'renderRecentTargets() limits output to 20 cards (got ' + cardCount + ')');
})();

(function testRenderRecentTargetsViewTargetOnclick() {
    resetState();
    vm.runInContext(`renderRecentTargets([
        { thumbnail_id: 'click-test', target_type: 'person', channel: 1 }
    ])`, ctx);
    const container = getOrCreateElement('analytics-recent-targets');
    assertContains(container.innerHTML, "viewTargetFromAnalytics('click-test')",
        'renderRecentTargets() wires onclick to viewTargetFromAnalytics');
})();

(function testRenderRecentTargetsImgFallback() {
    resetState();
    vm.runInContext(`renderRecentTargets([
        { thumbnail_id: 'img1', target_type: 'person', channel: 1 }
    ])`, ctx);
    const container = getOrCreateElement('analytics-recent-targets');
    assertContains(container.innerHTML, 'onerror=',
        'renderRecentTargets() includes onerror fallback for broken images');
})();

// ============================================================
// 8. renderChannelBreakdown()
// ============================================================

console.log('\n--- renderChannelBreakdown() ---');

(function testRenderChannelBreakdownNull() {
    resetState();
    vm.runInContext('renderChannelBreakdown(null)', ctx);
    const container = getOrCreateElement('analytics-channels');
    assertContains(container.innerHTML, 'No channel data available',
        'renderChannelBreakdown(null) shows empty state');
})();

(function testRenderChannelBreakdownEmptyObject() {
    resetState();
    vm.runInContext('renderChannelBreakdown({})', ctx);
    const container = getOrCreateElement('analytics-channels');
    assertContains(container.innerHTML, 'No channel data available',
        'renderChannelBreakdown({}) shows empty state');
})();

(function testRenderChannelBreakdownUndefined() {
    resetState();
    vm.runInContext('renderChannelBreakdown(undefined)', ctx);
    const container = getOrCreateElement('analytics-channels');
    assertContains(container.innerHTML, 'No channel data available',
        'renderChannelBreakdown(undefined) shows empty state');
})();

(function testRenderChannelBreakdownWithData() {
    resetState();
    vm.runInContext(`renderChannelBreakdown({ 1: 50, 3: 30, 5: 20 })`, ctx);
    const container = getOrCreateElement('analytics-channels');
    assertContains(container.innerHTML, 'channel-stat-box',
        'renderChannelBreakdown() generates stat box elements');
})();

(function testRenderChannelBreakdownShowsChannelName() {
    resetState();
    vm.runInContext(`renderChannelBreakdown({ 1: 50 })`, ctx);
    const container = getOrCreateElement('analytics-channels');
    assertContains(container.innerHTML, 'CH01',
        'renderChannelBreakdown() pads channel number (CH01)');
})();

(function testRenderChannelBreakdownShowsCount() {
    resetState();
    vm.runInContext(`renderChannelBreakdown({ 1: 50, 3: 30 })`, ctx);
    const container = getOrCreateElement('analytics-channels');
    assertContains(container.innerHTML, '>50<',
        'renderChannelBreakdown() shows count value');
})();

(function testRenderChannelBreakdownPercentage() {
    resetState();
    vm.runInContext(`renderChannelBreakdown({ 1: 50, 3: 50 })`, ctx);
    const container = getOrCreateElement('analytics-channels');
    assertContains(container.innerHTML, '50.0%',
        'renderChannelBreakdown() calculates percentage correctly (50/100 = 50.0%)');
})();

(function testRenderChannelBreakdownSortsByCountDesc() {
    resetState();
    vm.runInContext(`renderChannelBreakdown({ 1: 10, 3: 50, 5: 30 })`, ctx);
    const container = getOrCreateElement('analytics-channels');
    const html = container.innerHTML;
    const idx50 = html.indexOf('>50<');
    const idx30 = html.indexOf('>30<');
    const idx10 = html.indexOf('>10<');
    assert(idx50 < idx30 && idx30 < idx10,
        'renderChannelBreakdown() sorts channels by count descending');
})();

(function testRenderChannelBreakdownFilterOnclick() {
    resetState();
    vm.runInContext(`renderChannelBreakdown({ 7: 10 })`, ctx);
    const container = getOrCreateElement('analytics-channels');
    assertContains(container.innerHTML, 'filterByChannel(7)',
        'renderChannelBreakdown() wires onclick to filterByChannel');
})();

(function testRenderChannelBreakdownFillBar() {
    resetState();
    vm.runInContext(`renderChannelBreakdown({ 1: 100 })`, ctx);
    const container = getOrCreateElement('analytics-channels');
    assertContains(container.innerHTML, 'channel-stat-fill',
        'renderChannelBreakdown() renders fill bar');
    assertContains(container.innerHTML, 'width: 100.0%',
        'renderChannelBreakdown() single channel gets 100% fill');
})();

// ============================================================
// 9. renderAnalytics() orchestration
// ============================================================

console.log('\n--- renderAnalytics() ---');

(function testRenderAnalyticsSetsTotalDetections() {
    resetState();
    vm.runInContext(`renderAnalytics({
        total_detections: 42,
        total_people: 30,
        total_vehicles: 12,
        peak_hour: 14,
        daily_counts: {},
        hourly_distribution: null,
        recent_targets: [],
        by_channel: {}
    })`, ctx);
    const el = getOrCreateElement('analytics-total');
    assert(el.textContent === '42', 'renderAnalytics() sets total detections to 42');
})();

(function testRenderAnalyticsSetsPeople() {
    resetState();
    vm.runInContext(`renderAnalytics({
        total_detections: 42,
        total_people: 30,
        total_vehicles: 12,
        peak_hour: 14,
        daily_counts: {},
        hourly_distribution: null,
        recent_targets: [],
        by_channel: {}
    })`, ctx);
    const el = getOrCreateElement('analytics-people');
    assert(el.textContent === '30', 'renderAnalytics() sets people count to 30');
})();

(function testRenderAnalyticsSetsVehicles() {
    resetState();
    vm.runInContext(`renderAnalytics({
        total_detections: 42,
        total_people: 30,
        total_vehicles: 12,
        peak_hour: 14,
        daily_counts: {},
        hourly_distribution: null,
        recent_targets: [],
        by_channel: {}
    })`, ctx);
    const el = getOrCreateElement('analytics-vehicles');
    assert(el.textContent === '12', 'renderAnalytics() sets vehicles count to 12');
})();

(function testRenderAnalyticsPeakHourFormatted() {
    resetState();
    vm.runInContext(`renderAnalytics({
        total_detections: 0,
        total_people: 0,
        total_vehicles: 0,
        peak_hour: 8,
        daily_counts: {},
        hourly_distribution: null,
        recent_targets: [],
        by_channel: {}
    })`, ctx);
    const el = getOrCreateElement('analytics-peak');
    assert(el.textContent === '08:00', 'renderAnalytics() formats peak hour 8 as "08:00"');
})();

(function testRenderAnalyticsPeakHourNull() {
    resetState();
    vm.runInContext(`renderAnalytics({
        total_detections: 0,
        total_people: 0,
        total_vehicles: 0,
        peak_hour: null,
        daily_counts: {},
        hourly_distribution: null,
        recent_targets: [],
        by_channel: {}
    })`, ctx);
    const el = getOrCreateElement('analytics-peak');
    assert(el.textContent === '--', 'renderAnalytics() shows "--" when peak_hour is null');
})();

(function testRenderAnalyticsMissingFields() {
    resetState();
    vm.runInContext(`renderAnalytics({
        daily_counts: {},
        hourly_distribution: null,
        recent_targets: [],
        by_channel: {}
    })`, ctx);
    const el = getOrCreateElement('analytics-total');
    assert(el.textContent === '0', 'renderAnalytics() defaults total_detections to 0 when missing');
})();

(function testRenderAnalyticsPeakHourZero() {
    resetState();
    vm.runInContext(`renderAnalytics({
        total_detections: 5,
        total_people: 5,
        total_vehicles: 0,
        peak_hour: 0,
        daily_counts: {},
        hourly_distribution: null,
        recent_targets: [],
        by_channel: {}
    })`, ctx);
    const el = getOrCreateElement('analytics-peak');
    assert(el.textContent === '00:00', 'renderAnalytics() formats peak hour 0 as "00:00"');
})();

(function testRenderAnalyticsPeakHour23() {
    resetState();
    vm.runInContext(`renderAnalytics({
        total_detections: 5,
        total_people: 5,
        total_vehicles: 0,
        peak_hour: 23,
        daily_counts: {},
        hourly_distribution: null,
        recent_targets: [],
        by_channel: {}
    })`, ctx);
    const el = getOrCreateElement('analytics-peak');
    assert(el.textContent === '23:00', 'renderAnalytics() formats peak hour 23 as "23:00"');
})();

// ============================================================
// 10. filterByHour()
// ============================================================

console.log('\n--- filterByHour() ---');

(function testFilterByHourSetsSessionStorage() {
    resetState();
    vm.runInContext('filterByHour(14)', ctx);
    assert(sessionStore['tritium_hour_filter'] === '14',
        'filterByHour() stores hour in sessionStorage');
})();

(function testFilterByHourSwitchesViewWhenTritiumExists() {
    resetState();
    let switchedTo = null;
    vm.runInContext(`window.TRITIUM = { switchView: function(v) { window._switchedTo = v; } }`, ctx);
    vm.runInContext('filterByHour(8)', ctx);
    const val = vm.runInContext('window._switchedTo', ctx);
    assert(val === 'targets', 'filterByHour() switches to targets view');
})();

(function testFilterByHourNoTritiumNoCrash() {
    resetState();
    vm.runInContext('window.TRITIUM = null;', ctx);
    let threw = false;
    try {
        vm.runInContext('filterByHour(12)', ctx);
    } catch (e) {
        threw = true;
    }
    assert(!threw, 'filterByHour() does not crash when window.TRITIUM is null');
})();

(function testFilterByHourZero() {
    resetState();
    vm.runInContext('filterByHour(0)', ctx);
    assert(sessionStore['tritium_hour_filter'] === '0',
        'filterByHour(0) stores "0" in sessionStorage');
})();

// ============================================================
// 11. filterByChannel()
// ============================================================

console.log('\n--- filterByChannel() ---');

(function testFilterByChannelSwitchesView() {
    resetState();
    vm.runInContext(`window.TRITIUM = { switchView: function(v) { window._chSwitched = v; } }`, ctx);
    vm.runInContext('filterByChannel(3)', ctx);
    const val = vm.runInContext('window._chSwitched', ctx);
    assert(val === 'targets', 'filterByChannel() switches to targets view');
})();

(function testFilterByChannelNoTritiumNoCrash() {
    resetState();
    vm.runInContext('window.TRITIUM = null;', ctx);
    let threw = false;
    try {
        vm.runInContext('filterByChannel(5)', ctx);
    } catch (e) {
        threw = true;
    }
    assert(!threw, 'filterByChannel() does not crash when window.TRITIUM is null');
})();

(function testFilterByChannelSchedulesTimeout() {
    resetState();
    timeoutCallbacks = [];
    vm.runInContext(`window.TRITIUM = { switchView: function(v) {} }`, ctx);
    vm.runInContext('filterByChannel(7)', ctx);
    assert(timeoutCallbacks.length >= 1,
        'filterByChannel() schedules a setTimeout for DOM update');
    assert(timeoutCallbacks[0].ms === 100,
        'filterByChannel() setTimeout delay is 100ms');
})();

// ============================================================
// 12. viewTargetFromAnalytics()
// ============================================================

console.log('\n--- viewTargetFromAnalytics() ---');

(function testViewTargetSwitchesView() {
    resetState();
    vm.runInContext(`window.TRITIUM = { switchView: function(v) { window._vtSwitched = v; } }`, ctx);
    vm.runInContext('viewTargetFromAnalytics("thumb123")', ctx);
    const val = vm.runInContext('window._vtSwitched', ctx);
    assert(val === 'targets', 'viewTargetFromAnalytics() switches to targets view');
})();

(function testViewTargetNoTritiumNoCrash() {
    resetState();
    vm.runInContext('window.TRITIUM = null;', ctx);
    let threw = false;
    try {
        vm.runInContext('viewTargetFromAnalytics("t1")', ctx);
    } catch (e) {
        threw = true;
    }
    assert(!threw, 'viewTargetFromAnalytics() does not crash when window.TRITIUM is null');
})();

(function testViewTargetSchedulesTimeout() {
    resetState();
    timeoutCallbacks = [];
    vm.runInContext(`window.TRITIUM = { switchView: function(v) {} }`, ctx);
    vm.runInContext('viewTargetFromAnalytics("abc")', ctx);
    assert(timeoutCallbacks.length >= 1,
        'viewTargetFromAnalytics() schedules a setTimeout');
    assert(timeoutCallbacks[0].ms === 300,
        'viewTargetFromAnalytics() setTimeout delay is 300ms');
})();

// ============================================================
// 13. loadAnalytics() (async)
// ============================================================

console.log('\n--- loadAnalytics() ---');

(async function testLoadAnalyticsFetchesCorrectUrl() {
    resetState();
    fetchCalls = [];
    fetchResponse = {
        ok: true, status: 200,
        json: () => Promise.resolve({
            total_detections: 10, total_people: 5, total_vehicles: 5,
            peak_hour: 12, daily_counts: {}, hourly_distribution: null,
            recent_targets: [], by_channel: {}
        })
    };
    // Set the analytics-days element value
    const daysEl = getOrCreateElement('analytics-days');
    daysEl.value = '14';
    await vm.runInContext('loadAnalytics()', ctx);
    assert(fetchCalls.length >= 1, 'loadAnalytics() calls fetch');
    assert(fetchCalls[0][0] === '/api/search/trends?days=14',
        'loadAnalytics() fetches correct URL with days param (got ' + fetchCalls[0][0] + ')');
})();

(async function testLoadAnalyticsUpdatesState() {
    resetState();
    const mockData = {
        total_detections: 99, total_people: 60, total_vehicles: 39,
        peak_hour: 18, daily_counts: {}, hourly_distribution: null,
        recent_targets: [], by_channel: {}
    };
    fetchResponse = {
        ok: true, status: 200,
        json: () => Promise.resolve(mockData)
    };
    const daysEl = getOrCreateElement('analytics-days');
    daysEl.value = '7';
    await vm.runInContext('loadAnalytics()', ctx);
    const data = vm.runInContext('analyticsState.data', ctx);
    assert(data !== null, 'loadAnalytics() sets analyticsState.data');
    assert(data.total_detections === 99, 'loadAnalytics() stores fetched data');
})();

(async function testLoadAnalyticsUpdatesDays() {
    resetState();
    fetchResponse = {
        ok: true, status: 200,
        json: () => Promise.resolve({
            total_detections: 0, total_people: 0, total_vehicles: 0,
            peak_hour: null, daily_counts: {}, hourly_distribution: null,
            recent_targets: [], by_channel: {}
        })
    };
    const daysEl = getOrCreateElement('analytics-days');
    daysEl.value = '30';
    await vm.runInContext('loadAnalytics()', ctx);
    const days = vm.runInContext('analyticsState.days', ctx);
    assert(days === 30, 'loadAnalytics() updates analyticsState.days to 30');
})();

(async function testLoadAnalyticsHandlesHttpError() {
    resetState();
    consoleErrors = [];
    fetchResponse = {
        ok: false, status: 500,
        json: () => Promise.resolve({})
    };
    const daysEl = getOrCreateElement('analytics-days');
    daysEl.value = '7';
    await vm.runInContext('loadAnalytics()', ctx);
    const hasError = consoleErrors.some(e => e.includes('Failed to load analytics'));
    assert(hasError, 'loadAnalytics() logs error on HTTP failure');
})();

(async function testLoadAnalyticsHandlesFetchException() {
    resetState();
    consoleErrors = [];
    // Override fetch to throw
    const origFetch = sandbox.fetch;
    sandbox.fetch = () => Promise.reject(new Error('Network error'));
    const daysEl = getOrCreateElement('analytics-days');
    daysEl.value = '7';
    await vm.runInContext('loadAnalytics()', ctx);
    const hasError = consoleErrors.some(e => e.includes('Failed to load analytics'));
    assert(hasError, 'loadAnalytics() catches fetch exceptions');
    sandbox.fetch = origFetch;
})();

(async function testLoadAnalyticsDefaultDays() {
    resetState();
    fetchCalls = [];
    fetchResponse = {
        ok: true, status: 200,
        json: () => Promise.resolve({
            total_detections: 0, total_people: 0, total_vehicles: 0,
            peak_hour: null, daily_counts: {}, hourly_distribution: null,
            recent_targets: [], by_channel: {}
        })
    };
    // Return null for the days element to test default
    const origGetById = sandbox.document.getElementById;
    sandbox.document.getElementById = (id) => {
        if (id === 'analytics-days') return null;
        return getOrCreateElement(id);
    };
    await vm.runInContext('loadAnalytics()', ctx);
    assert(fetchCalls.length >= 1, 'loadAnalytics() calls fetch even without days element');
    assert(fetchCalls[0][0] === '/api/search/trends?days=7',
        'loadAnalytics() defaults to 7 days when element is missing');
    sandbox.document.getElementById = origGetById;
})();

// ============================================================
// 14. initAnalyticsView() (async)
// ============================================================

console.log('\n--- initAnalyticsView() ---');

(async function testInitAnalyticsViewCallsLoadAnalytics() {
    resetState();
    fetchCalls = [];
    fetchResponse = {
        ok: true, status: 200,
        json: () => Promise.resolve({
            total_detections: 0, total_people: 0, total_vehicles: 0,
            peak_hour: null, daily_counts: {}, hourly_distribution: null,
            recent_targets: [], by_channel: {}
        })
    };
    const daysEl = getOrCreateElement('analytics-days');
    daysEl.value = '7';
    await vm.runInContext('initAnalyticsView()', ctx);
    assert(fetchCalls.length >= 1, 'initAnalyticsView() triggers a fetch call (delegates to loadAnalytics)');
})();

// ============================================================
// 15. CSS styles injected
// ============================================================

console.log('\n--- CSS injection ---');

(function testStylesAppendedToHead() {
    const head = sandbox.document.head;
    const styleChild = head.children.find(
        c => c.tagName === 'STYLE' && c.textContent.includes('recent-target-card')
    );
    assert(styleChild !== undefined, 'analytics.js appends a <style> element to document.head');
})();

(function testStylesContainTargetCard() {
    const head = sandbox.document.head;
    const styleChild = head.children.find(c => c.tagName === 'STYLE');
    if (styleChild) {
        assertContains(styleChild.textContent, '.recent-target-card',
            'Injected CSS contains .recent-target-card');
    } else {
        assert(false, 'No style element found in head');
    }
})();

(function testStylesContainChannelStatBox() {
    const head = sandbox.document.head;
    const styleChild = head.children.find(c => c.tagName === 'STYLE');
    if (styleChild) {
        assertContains(styleChild.textContent, '.channel-stat-box',
            'Injected CSS contains .channel-stat-box');
    } else {
        assert(false, 'No style element found in head');
    }
})();

(function testStylesContainHourBarHover() {
    const head = sandbox.document.head;
    const styleChild = head.children.find(c => c.tagName === 'STYLE');
    if (styleChild) {
        assertContains(styleChild.textContent, '.hour-bar-analytics:hover',
            'Injected CSS contains .hour-bar-analytics:hover');
    } else {
        assert(false, 'No style element found in head');
    }
})();

(function testStylesContainDailyBarGroupHover() {
    const head = sandbox.document.head;
    const styleChild = head.children.find(c => c.tagName === 'STYLE');
    if (styleChild) {
        assertContains(styleChild.textContent, '.daily-bar-group:hover',
            'Injected CSS contains .daily-bar-group:hover');
    } else {
        assert(false, 'No style element found in head');
    }
})();

// ============================================================
// Summary
// ============================================================

// Allow async tests to settle
setTimeout(() => {
    console.log('\n' + '='.repeat(40));
    console.log(`Results: ${passed} passed, ${failed} failed`);
    console.log('='.repeat(40));
    process.exit(failed > 0 ? 1 : 0);
}, 500);
