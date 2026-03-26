// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
/**
 * TRITIUM-SC Threat Feeds Panel tests
 * Tests ThreatFeedsPanelDef structure, DOM creation, feed list, stat rendering,
 * filter controls, accessibility, _esc utility, and mount/unmount lifecycle.
 * Run: node tests/js/test_threat_feeds_panel.js
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
            el._parsedFilters = {};
            const filterMatches = val.matchAll(/data-filter="([^"]+)"/g);
            for (const m of filterMatches) el._parsedFilters[m[1]] = true;
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
            const filterMatch = sel.match(/\[data-filter="([^"]+)"\]/);
            if (filterMatch) {
                const mock = createMockElement('select');
                mock._filterName = filterMatch[1];
                mock.value = '';
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
    fetch: () => Promise.resolve({ ok: true, json: () => Promise.resolve({}) }),
    performance: { now: () => Date.now() },
};

const ctx = vm.createContext(sandbox);

// Load events.js (EventBus)
const eventsCode = fs.readFileSync(__dirname + '/../../../tritium-lib/web/events.js', 'utf8');
const eventsPlain = eventsCode
    .replace(/^export\s+/gm, '')
    .replace(/^import\s+.*$/gm, '');
vm.runInContext(eventsPlain, ctx);

// Load utils.js (_esc, _timeAgo)
const utilsCode = fs.readFileSync(__dirname + '/../../../tritium-lib/web/utils.js', 'utf8');
const utilsPlain = utilsCode
    .replace(/^export\s+/gm, '')
    .replace(/^import\s+.*$/gm, '');
vm.runInContext(utilsPlain, ctx);

// Load the threat-feeds-panel.js
const panelCode = fs.readFileSync(__dirname + '/../../src/frontend/js/command/panels/threat-feeds-panel.js', 'utf8');
const panelPlain = panelCode
    .replace(/^export\s+const\s+/gm, 'var ')
    .replace(/^export\s+/gm, '')
    .replace(/^import\s+.*$/gm, '');
vm.runInContext(panelPlain, ctx);

const ThreatFeedsPanelDef = ctx.ThreatFeedsPanelDef;

// ============================================================
// 1. ThreatFeedsPanelDef has required properties
// ============================================================

console.log('\n--- ThreatFeedsPanelDef structure ---');

(function testHasId() {
    assert(ThreatFeedsPanelDef.id === 'threat-feeds', 'ThreatFeedsPanelDef.id is "threat-feeds"');
})();

(function testHasTitle() {
    assert(ThreatFeedsPanelDef.title === 'THREAT FEEDS', 'ThreatFeedsPanelDef.title is "THREAT FEEDS"');
})();

(function testHasCreate() {
    assert(typeof ThreatFeedsPanelDef.create === 'function', 'ThreatFeedsPanelDef.create is a function');
})();

(function testHasMount() {
    assert(typeof ThreatFeedsPanelDef.mount === 'function', 'ThreatFeedsPanelDef.mount is a function');
})();

(function testHasUnmount() {
    assert(typeof ThreatFeedsPanelDef.unmount === 'function', 'ThreatFeedsPanelDef.unmount is a function');
})();

(function testHasDefaultPosition() {
    assert(ThreatFeedsPanelDef.defaultPosition !== undefined, 'ThreatFeedsPanelDef has defaultPosition');
    assert(typeof ThreatFeedsPanelDef.defaultPosition.x === 'number', 'defaultPosition.x is a number');
    assert(typeof ThreatFeedsPanelDef.defaultPosition.y === 'number', 'defaultPosition.y is a number');
})();

(function testHasDefaultSize() {
    assert(ThreatFeedsPanelDef.defaultSize !== undefined, 'ThreatFeedsPanelDef has defaultSize');
    assert(ThreatFeedsPanelDef.defaultSize.w === 400, 'defaultSize.w is 400');
    assert(ThreatFeedsPanelDef.defaultSize.h === 520, 'defaultSize.h is 520');
})();

// ============================================================
// 2. create() returns DOM element with expected structure
// ============================================================

console.log('\n--- create() DOM structure ---');

(function testCreateReturnsDomElement() {
    const el = ThreatFeedsPanelDef.create({});
    assert(el !== null && el !== undefined, 'create() returns an element');
    assert(el.className === 'tf-panel-inner', 'create() element has correct className');
})();

(function testCreateHasCountBinding() {
    const el = ThreatFeedsPanelDef.create({});
    const html = el.innerHTML;
    assert(html.includes('data-bind="count-total"'), 'DOM contains count-total data-bind');
    assert(html.includes('indicators'), 'DOM contains "indicators" text');
})();

(function testCreateHasStatsBinding() {
    const el = ThreatFeedsPanelDef.create({});
    const html = el.innerHTML;
    assert(html.includes('data-bind="stats"'), 'DOM contains stats data-bind');
})();

(function testCreateHasFeedList() {
    const el = ThreatFeedsPanelDef.create({});
    const html = el.innerHTML;
    assert(html.includes('data-bind="feed"'), 'DOM contains feed list data-bind');
    assert(html.includes('panel-list'), 'Feed list has panel-list class');
})();

(function testCreateHasFilterControls() {
    const el = ThreatFeedsPanelDef.create({});
    const html = el.innerHTML;
    assert(html.includes('data-filter="type"'), 'DOM contains type filter');
    assert(html.includes('data-filter="level"'), 'DOM contains level filter');
})();

(function testCreateHasRefreshButton() {
    const el = ThreatFeedsPanelDef.create({});
    const html = el.innerHTML;
    assert(html.includes('data-action="refresh"'), 'DOM contains refresh action button');
})();

(function testCreateHasAddButton() {
    const el = ThreatFeedsPanelDef.create({});
    const html = el.innerHTML;
    assert(html.includes('data-action="add"'), 'DOM contains add indicator button');
})();

(function testCreateHasStatusDot() {
    const el = ThreatFeedsPanelDef.create({});
    const html = el.innerHTML;
    assert(html.includes('data-bind="status-dot"'), 'DOM contains status-dot data-bind');
})();

// ============================================================
// 3. Accessibility attributes
// ============================================================

console.log('\n--- Accessibility ---');

(function testFeedHasLogRole() {
    const el = ThreatFeedsPanelDef.create({});
    const html = el.innerHTML;
    assert(html.includes('role="log"'), 'Feed list has role="log"');
})();

(function testFeedHasAriaLabel() {
    const el = ThreatFeedsPanelDef.create({});
    const html = el.innerHTML;
    assert(html.includes('aria-label="Threat indicator feed"'), 'Feed list has aria-label');
})();

(function testFeedHasAriaLive() {
    const el = ThreatFeedsPanelDef.create({});
    const html = el.innerHTML;
    assert(html.includes('aria-live="polite"'), 'Feed list has aria-live="polite"');
})();

// ============================================================
// 4. Filter options
// ============================================================

console.log('\n--- Filter options ---');

(function testTypeFilterHasOptions() {
    const el = ThreatFeedsPanelDef.create({});
    const html = el.innerHTML;
    assert(html.includes('ALL TYPES'), 'Type filter has ALL TYPES option');
    assert(html.includes('"mac"'), 'Type filter has MAC option');
    assert(html.includes('"ssid"'), 'Type filter has SSID option');
    assert(html.includes('"ip"'), 'Type filter has IP option');
    assert(html.includes('"device_name"'), 'Type filter has device_name option');
})();

(function testLevelFilterHasOptions() {
    const el = ThreatFeedsPanelDef.create({});
    const html = el.innerHTML;
    assert(html.includes('ALL LEVELS'), 'Level filter has ALL LEVELS option');
    assert(html.includes('"hostile"'), 'Level filter has hostile option');
    assert(html.includes('"suspicious"'), 'Level filter has suspicious option');
})();

// ============================================================
// 5. _esc is used for XSS safety
// ============================================================

console.log('\n--- XSS prevention ---');

(function testEscFunction() {
    const fn = vm.runInContext('typeof _esc', ctx);
    assert(fn === 'function', '_esc function is available');
})();

(function testEscEscapesHtml() {
    const result = vm.runInContext('_esc("<script>alert(1)</script>")', ctx);
    assert(!result.includes('<script>'), '_esc escapes script tags');
    assert(result.includes('&lt;'), '_esc converts < to &lt;');
})();

(function testEscHandlesNull() {
    const result = vm.runInContext('_esc(null)', ctx);
    assert(result === '', '_esc(null) returns empty string');
})();

// ============================================================
// 6. Render helper functions
// ============================================================

console.log('\n--- Render helpers ---');

(function testLevelBadgeFunction() {
    const fn = vm.runInContext('typeof _levelBadge', ctx);
    assert(fn === 'function', '_levelBadge function exists');
})();

(function testLevelBadgeHostile() {
    const result = vm.runInContext('_levelBadge("hostile")', ctx);
    assert(result.includes('#ff2a6d'), '_levelBadge hostile uses magenta color');
    assert(result.includes('HOSTILE'), '_levelBadge hostile shows label');
})();

(function testLevelBadgeSuspicious() {
    const result = vm.runInContext('_levelBadge("suspicious")', ctx);
    assert(result.includes('#fcee0a'), '_levelBadge suspicious uses yellow color');
    assert(result.includes('SUSPICIOUS'), '_levelBadge suspicious shows label');
})();

(function testTypeBadgeFunction() {
    const fn = vm.runInContext('typeof _typeBadge', ctx);
    assert(fn === 'function', '_typeBadge function exists');
})();

(function testTypeBadgeMac() {
    const result = vm.runInContext('_typeBadge("mac")', ctx);
    assert(result.includes('MAC'), '_typeBadge mac shows label');
})();

(function testRenderStatsBar() {
    const fn = vm.runInContext('typeof _renderStatsBar', ctx);
    assert(fn === 'function', '_renderStatsBar function exists');
})();

(function testRenderStatsBarOutput() {
    const result = vm.runInContext('_renderStatsBar({ total: 10, by_level: { hostile: 5, suspicious: 5 } })', ctx);
    assert(result.includes('10'), '_renderStatsBar shows total count');
    assert(result.includes('5'), '_renderStatsBar shows hostile count');
})();

(function testRenderStatsBarEmpty() {
    const result = vm.runInContext('_renderStatsBar(null)', ctx);
    assert(result === '', '_renderStatsBar returns empty for null');
})();

(function testRenderIndicatorList() {
    const fn = vm.runInContext('typeof _renderIndicatorList', ctx);
    assert(fn === 'function', '_renderIndicatorList function exists');
})();

(function testRenderIndicatorListWithData() {
    const result = vm.runInContext(`_renderIndicatorList([
        { indicator_type: "mac", value: "DE:AD:BE:EF:00:01", threat_level: "hostile", description: "test", source: "test", last_seen: 1700000000 }
    ], "", "")`, ctx);
    assert(result.includes('DE:AD:BE:EF:00:01'), '_renderIndicatorList shows MAC value');
    assert(result.includes('#ff2a6d'), '_renderIndicatorList uses hostile color');
    assert(result.includes('tf-indicator-item'), '_renderIndicatorList has item class');
})();

(function testRenderIndicatorListEmpty() {
    const result = vm.runInContext('_renderIndicatorList([], "", "")', ctx);
    assert(result.includes('No indicators matching filters'), '_renderIndicatorList shows empty state');
    assert(result.includes('panel-empty'), '_renderIndicatorList empty has panel-empty class');
})();

(function testRenderIndicatorListFilterByType() {
    const result = vm.runInContext(`_renderIndicatorList([
        { indicator_type: "mac", value: "AA:BB:CC:DD:EE:FF", threat_level: "hostile", description: "", source: "test" },
        { indicator_type: "ssid", value: "EvilNet", threat_level: "suspicious", description: "", source: "test" }
    ], "mac", "")`, ctx);
    assert(result.includes('AA:BB:CC:DD:EE:FF'), 'Filter shows matching MAC');
    assert(!result.includes('EvilNet'), 'Filter excludes non-matching SSID');
})();

(function testRenderIndicatorListFilterByLevel() {
    const result = vm.runInContext(`_renderIndicatorList([
        { indicator_type: "mac", value: "AA:BB:CC:DD:EE:FF", threat_level: "hostile", description: "", source: "test" },
        { indicator_type: "ssid", value: "EvilNet", threat_level: "suspicious", description: "", source: "test" }
    ], "", "suspicious")`, ctx);
    assert(!result.includes('AA:BB:CC:DD:EE:FF'), 'Level filter excludes hostile');
    assert(result.includes('EvilNet'), 'Level filter shows suspicious');
})();

(function testRenderTypeDistribution() {
    const fn = vm.runInContext('typeof _renderTypeDistribution', ctx);
    assert(fn === 'function', '_renderTypeDistribution function exists');
})();

(function testRenderTypeDistributionOutput() {
    const result = vm.runInContext('_renderTypeDistribution({ total: 10, by_type: { mac: 5, ssid: 3, ip: 2 } })', ctx);
    assert(result.includes('Type Distribution'), '_renderTypeDistribution shows title');
    assert(result.includes('MAC'), '_renderTypeDistribution shows MAC label');
})();

(function testRenderSourceBreakdown() {
    const fn = vm.runInContext('typeof _renderSourceBreakdown', ctx);
    assert(fn === 'function', '_renderSourceBreakdown function exists');
})();

(function testRenderSourceBreakdownOutput() {
    const result = vm.runInContext('_renderSourceBreakdown({ by_source: { "tritium-intel": 5, "community": 3 } })', ctx);
    assert(result.includes('Feed Sources'), '_renderSourceBreakdown shows title');
    assert(result.includes('tritium-intel'), '_renderSourceBreakdown shows source name');
})();

// ============================================================
// 7. mount() wiring
// ============================================================

console.log('\n--- mount() ---');

(function testMountDoesNotCrash() {
    const bodyEl = createMockElement('div');
    const panel = {
        def: ThreatFeedsPanelDef,
        w: 400,
        x: 0,
        el: createMockElement('div'),
        manager: { container: createMockElement('div') },
        _tfTimer: null,
    };

    let threw = false;
    try {
        ThreatFeedsPanelDef.mount(bodyEl, panel);
    } catch (e) {
        threw = true;
        console.error('mount() error:', e);
    }
    assert(!threw, 'mount() does not crash');
})();

(function testMountSetsTimer() {
    const bodyEl = createMockElement('div');
    const panel = {
        def: ThreatFeedsPanelDef,
        w: 400,
        x: 0,
        el: createMockElement('div'),
        manager: { container: createMockElement('div') },
        _tfTimer: null,
    };

    ThreatFeedsPanelDef.mount(bodyEl, panel);
    assert(panel._tfTimer !== null, 'mount() sets auto-refresh timer');
    clearInterval(panel._tfTimer); // cleanup
})();

// ============================================================
// 8. unmount() cleanup
// ============================================================

console.log('\n--- unmount() ---');

(function testUnmountDoesNotCrash() {
    const bodyEl = createMockElement('div');
    let threw = false;
    try {
        ThreatFeedsPanelDef.unmount(bodyEl, {});
    } catch (e) {
        threw = true;
    }
    assert(!threw, 'unmount() does not throw');
})();

(function testUnmountClearsTimer() {
    const bodyEl = createMockElement('div');
    const panel = {
        def: ThreatFeedsPanelDef,
        w: 400,
        x: 0,
        el: createMockElement('div'),
        manager: { container: createMockElement('div') },
        _tfTimer: null,
    };

    ThreatFeedsPanelDef.mount(bodyEl, panel);
    assert(panel._tfTimer !== null, 'Timer was set by mount');
    ThreatFeedsPanelDef.unmount(bodyEl, panel);
    assert(panel._tfTimer === null, 'unmount() clears timer');
})();

// ============================================================
// 9. Cyberpunk color constants
// ============================================================

console.log('\n--- Cyberpunk theme ---');

(function testHostileColorIsMagenta() {
    const color = vm.runInContext('LEVEL_COLORS.hostile', ctx);
    assert(color === '#ff2a6d', 'Hostile color is magenta #ff2a6d');
})();

(function testSuspiciousColorIsYellow() {
    const color = vm.runInContext('LEVEL_COLORS.suspicious', ctx);
    assert(color === '#fcee0a', 'Suspicious color is yellow #fcee0a');
})();

(function testPollInterval() {
    const interval = vm.runInContext('POLL_INTERVAL', ctx);
    assert(interval === 10000, 'POLL_INTERVAL is 10000ms (10s)');
})();

// ============================================================
// 10. XSS in indicator rendering
// ============================================================

console.log('\n--- XSS in rendered indicators ---');

(function testRenderEscapesValue() {
    const result = vm.runInContext(`_renderIndicatorList([
        { indicator_type: "ssid", value: "<script>alert(1)</script>", threat_level: "hostile", description: "xss test", source: "test" }
    ], "", "")`, ctx);
    assert(!result.includes('<script>'), 'Rendered indicator value escapes script tags');
    assert(result.includes('&lt;script&gt;'), 'Rendered indicator value uses HTML entities');
})();

(function testRenderEscapesDescription() {
    const result = vm.runInContext(`_renderIndicatorList([
        { indicator_type: "mac", value: "AA:BB:CC:DD:EE:FF", threat_level: "suspicious", description: '<img onerror="alert(1)">', source: "test" }
    ], "", "")`, ctx);
    assert(!result.includes('<img'), 'Rendered description escapes img tags');
})();

// ============================================================
// Summary
// ============================================================

console.log('\n' + '='.repeat(40));
console.log(`Results: ${passed} passed, ${failed} failed`);
console.log('='.repeat(40));
process.exit(failed > 0 ? 1 : 0);
