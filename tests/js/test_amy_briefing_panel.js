// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
/**
 * TRITIUM-SC Amy Daily Briefing Panel tests
 * Tests AmyBriefingPanelDef structure, DOM creation, data-bind elements,
 * action buttons, _renderBriefing output, _esc usage, mount timer, and unmount cleanup.
 * Run: node tests/js/test_amy_briefing_panel.js
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
                const mock = createMockElement('span');
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
        getBoundingClientRect() { return { top: 0, left: 0, width: 100, height: 100 }; },
        setAttribute(k, v) { el[k] = v; },
        getAttribute(k) { return el[k]; },
        get offsetWidth() { return 100; },
        get offsetHeight() { return 700; },
        get offsetTop() { return 0; },
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

// Load amy-briefing-panel.js
const panelCode = fs.readFileSync(__dirname + '/../../src/frontend/js/command/panels/amy-briefing-panel.js', 'utf8');
const panelPlain = panelCode
    .replace(/^export\s+const\s+/gm, 'var ')
    .replace(/^export\s+/gm, '')
    .replace(/^import\s+.*$/gm, '');
vm.runInContext(panelPlain, ctx);

const AmyBriefingPanelDef = ctx.AmyBriefingPanelDef;

// ============================================================
// 1. AmyBriefingPanelDef has required properties
// ============================================================

console.log('\n--- AmyBriefingPanelDef structure ---');

(function testHasId() {
    assert(AmyBriefingPanelDef.id === 'amy-briefing', 'AmyBriefingPanelDef.id is "amy-briefing"');
})();

(function testHasTitle() {
    assert(AmyBriefingPanelDef.title === 'AMY DAILY BRIEFING', 'AmyBriefingPanelDef.title is "AMY DAILY BRIEFING"');
})();

(function testHasCreate() {
    assert(typeof AmyBriefingPanelDef.create === 'function', 'AmyBriefingPanelDef.create is a function');
})();

(function testHasMount() {
    assert(typeof AmyBriefingPanelDef.mount === 'function', 'AmyBriefingPanelDef.mount is a function');
})();

(function testHasUnmount() {
    assert(typeof AmyBriefingPanelDef.unmount === 'function', 'AmyBriefingPanelDef.unmount is a function');
})();

(function testHasDefaultSize() {
    assert(AmyBriefingPanelDef.defaultSize !== undefined, 'AmyBriefingPanelDef has defaultSize');
    assert(AmyBriefingPanelDef.defaultSize.w === 420, 'defaultSize.w is 420');
    assert(AmyBriefingPanelDef.defaultSize.h === 520, 'defaultSize.h is 520');
})();

// ============================================================
// 2. create() returns DOM element with expected structure
// ============================================================

console.log('\n--- create() DOM structure ---');

(function testCreateReturnsDomElement() {
    const el = AmyBriefingPanelDef.create({});
    assert(el !== null && el !== undefined, 'create() returns an element');
    assert(el.className === 'ab-panel-inner', 'create() element has className ab-panel-inner');
})();

(function testCreateHasGenerateButton() {
    const el = AmyBriefingPanelDef.create({});
    const html = el.innerHTML;
    assert(html.includes('data-action="generate-briefing"'), 'DOM has GENERATE BRIEFING action button');
    assert(html.includes('GENERATE BRIEFING'), 'DOM has "GENERATE BRIEFING" label');
})();

(function testCreateHasRefreshButton() {
    const el = AmyBriefingPanelDef.create({});
    const html = el.innerHTML;
    assert(html.includes('data-action="refresh-briefing"'), 'DOM has REFRESH action button');
    assert(html.includes('REFRESH'), 'DOM has "REFRESH" label');
})();

(function testCreateHasContentBinding() {
    const el = AmyBriefingPanelDef.create({});
    const html = el.innerHTML;
    assert(html.includes('data-bind="ab-content"'), 'DOM has ab-content data-bind');
})();

(function testCreateHasStatusBinding() {
    const el = AmyBriefingPanelDef.create({});
    const html = el.innerHTML;
    assert(html.includes('data-bind="ab-status"'), 'DOM has ab-status data-bind');
})();

(function testCreateHasLoadingMessage() {
    const el = AmyBriefingPanelDef.create({});
    const html = el.innerHTML;
    assert(html.includes('Loading briefing...'), 'DOM shows loading message initially');
})();

// ============================================================
// 3. _renderBriefing function
// ============================================================

console.log('\n--- _renderBriefing ---');

(function testRenderBriefingWithNull() {
    const result = vm.runInContext('_renderBriefing(null)', ctx);
    assert(result.includes('No briefing available'), '_renderBriefing(null) shows no-briefing message');
})();

(function testRenderBriefingWithEmptyText() {
    const result = vm.runInContext('_renderBriefing({ text: "" })', ctx);
    assert(result.includes('No briefing available'), '_renderBriefing with empty text shows no-briefing message');
})();

(function testRenderBriefingShowsThreatLevel() {
    const result = vm.runInContext(`_renderBriefing({
        text: "DAILY BRIEFING test",
        briefing_id: "AMY-BRIEF-TEST",
        generated_at: "2026-03-25T08:00:00Z",
        source: "template",
        context_summary: { threat_level: "LOW", total_targets: 5, new_targets_24h: 2 }
    })`, ctx);
    assert(result.includes('THREAT LEVEL'), '_renderBriefing shows THREAT LEVEL label');
    assert(result.includes('LOW'), '_renderBriefing shows threat level value');
})();

(function testRenderBriefingShowsTargetCount() {
    const result = vm.runInContext(`_renderBriefing({
        text: "DAILY BRIEFING test",
        briefing_id: "AMY-BRIEF-TEST",
        generated_at: "2026-03-25T08:00:00Z",
        source: "template",
        context_summary: { threat_level: "LOW", total_targets: 42, new_targets_24h: 7 }
    })`, ctx);
    assert(result.includes('TOTAL TARGETS'), '_renderBriefing shows TOTAL TARGETS label');
    assert(result.includes('42'), '_renderBriefing shows target count');
    assert(result.includes('NEW (24H)'), '_renderBriefing shows NEW (24H) label');
    assert(result.includes('7'), '_renderBriefing shows new targets count');
})();

(function testRenderBriefingShowsSource() {
    const result = vm.runInContext(`_renderBriefing({
        text: "DAILY BRIEFING test",
        briefing_id: "AMY-BRIEF-123",
        generated_at: "2026-03-25T08:00:00Z",
        source: "template",
        context_summary: { threat_level: "UNKNOWN", total_targets: 0, new_targets_24h: 0 }
    })`, ctx);
    assert(result.includes('template'), '_renderBriefing shows source type');
    assert(result.includes('AMY-BRIEF-123'), '_renderBriefing shows briefing ID');
})();

(function testRenderBriefingShowsText() {
    const result = vm.runInContext(`_renderBriefing({
        text: "DAILY BRIEFING 2026-03-25\\nTHREAT ASSESSMENT: LOW\\nAll clear.",
        briefing_id: "AMY-BRIEF-TEST",
        generated_at: "2026-03-25T08:00:00Z",
        source: "ollama",
        context_summary: { threat_level: "LOW", total_targets: 0, new_targets_24h: 0 }
    })`, ctx);
    assert(result.includes('DAILY BRIEFING 2026-03-25'), '_renderBriefing preserves briefing text');
    assert(result.includes('THREAT ASSESSMENT: LOW'), '_renderBriefing shows multi-line text');
    assert(result.includes('All clear.'), '_renderBriefing shows all lines');
})();

(function testRenderBriefingEscapesXss() {
    const result = vm.runInContext(`_renderBriefing({
        text: "<script>alert(1)</script>",
        briefing_id: "XSS-TEST",
        generated_at: "2026-03-25T08:00:00Z",
        source: "template",
        context_summary: { threat_level: "LOW", total_targets: 0, new_targets_24h: 0 }
    })`, ctx);
    assert(!result.includes('<script>alert'), '_renderBriefing escapes XSS in text');
    assert(result.includes('&lt;script&gt;'), '_renderBriefing converts < to &lt;');
})();

// ============================================================
// 4. Threat color mapping
// ============================================================

console.log('\n--- Threat colors ---');

(function testThreatColorMapping() {
    const colors = vm.runInContext('THREAT_COLORS', ctx);
    assert(colors.LOW === '#05ffa1', 'LOW threat is green');
    assert(colors.MODERATE === '#fcee0a', 'MODERATE threat is yellow');
    assert(colors.HIGH === '#ff2a6d', 'HIGH threat is magenta');
    assert(colors.CRITICAL === '#ff2a6d', 'CRITICAL threat is magenta');
    assert(colors.UNKNOWN === '#666', 'UNKNOWN threat is gray');
})();

// ============================================================
// 5. mount() sets up timer and fetch
// ============================================================

console.log('\n--- mount() wiring ---');

(function testMountCallsFetch() {
    let fetchCalled = false;
    let fetchUrl = '';
    const origFetch = ctx.fetch;
    ctx.fetch = (url, opts) => {
        fetchCalled = true;
        fetchUrl = url;
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ text: 'test', context_summary: {} }) });
    };

    const bodyEl = createMockElement('div');
    const panel = { _abTimer: null };

    AmyBriefingPanelDef.mount(bodyEl, panel);
    assert(fetchCalled, 'mount() triggers fetch on init');
    assert(fetchUrl === '/api/amy/briefing', 'mount() fetches /api/amy/briefing');

    ctx.fetch = origFetch;
})();

(function testMountSetsTimer() {
    let intervalSet = false;
    const origSetInterval = ctx.setInterval;
    ctx.setInterval = (fn, ms) => {
        intervalSet = true;
        assert(ms === 60000, 'Auto-refresh interval is 60000ms (60s)');
        return 42;
    };

    const bodyEl = createMockElement('div');
    const panel = { _abTimer: null };

    ctx.fetch = () => Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    AmyBriefingPanelDef.mount(bodyEl, panel);
    assert(intervalSet, 'mount() sets up auto-refresh interval');
    assert(panel._abTimer === 42, 'mount() stores timer on panel._abTimer');

    ctx.setInterval = origSetInterval;
})();

// ============================================================
// 6. unmount() clears timer
// ============================================================

console.log('\n--- unmount() ---');

(function testUnmountClearsTimer() {
    let clearCalled = false;
    const origClear = ctx.clearInterval;
    ctx.clearInterval = (id) => {
        clearCalled = true;
        assert(id === 99, 'clearInterval called with correct timer ID');
    };

    const panel = { _abTimer: 99 };
    AmyBriefingPanelDef.unmount(createMockElement('div'), panel);
    assert(clearCalled, 'unmount() calls clearInterval');
    assert(panel._abTimer === null, 'unmount() sets _abTimer to null');

    ctx.clearInterval = origClear;
})();

(function testUnmountDoesNotCrashWithNoTimer() {
    let threw = false;
    try {
        AmyBriefingPanelDef.unmount(createMockElement('div'), {});
        AmyBriefingPanelDef.unmount(createMockElement('div'), null);
    } catch (e) {
        threw = true;
    }
    assert(!threw, 'unmount() does not crash with no timer or null panel');
})();

// ============================================================
// 7. _fmtTime utility
// ============================================================

console.log('\n--- _fmtTime utility ---');

(function testFmtTimeNull() {
    const result = vm.runInContext('_fmtTime(null)', ctx);
    assert(result === '--', '_fmtTime(null) returns "--"');
})();

(function testFmtTimeValid() {
    const result = vm.runInContext('_fmtTime("2026-03-25T08:00:00Z")', ctx);
    assert(result !== '--' && result.length > 0, '_fmtTime with valid ISO returns formatted string');
})();

// ============================================================
// Summary
// ============================================================

console.log('\n' + '='.repeat(40));
console.log(`Results: ${passed} passed, ${failed} failed`);
console.log('='.repeat(40));
process.exit(failed > 0 ? 1 : 0);
