// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
/**
 * TRITIUM-SC Enrichment Panel tests
 * Tests EnrichmentPanelDef structure, DOM creation, render functions,
 * target selector, enrichment results, source icons/colors,
 * confidence badges, XSS prevention, mount/unmount lifecycle,
 * and cyberpunk theme.
 * Run: node tests/js/test_enrichment_panel.js
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
        body: { appendChild: () => {}, removeChild: () => {} },
        execCommand: () => {},
    },
    window: {},
    fetch: () => Promise.resolve({ ok: true, json: () => Promise.resolve({}) }),
    performance: { now: () => Date.now() },
    navigator: { clipboard: { writeText: () => Promise.resolve() } },
};

const ctx = vm.createContext(sandbox);

// Load utils.js (_esc)
const utilsCode = fs.readFileSync(__dirname + '/../../../tritium-lib/web/utils.js', 'utf8');
const utilsPlain = utilsCode
    .replace(/^export\s+/gm, '')
    .replace(/^import\s+.*$/gm, '');
vm.runInContext(utilsPlain, ctx);

// Load the enrichment-panel.js
const panelCode = fs.readFileSync(__dirname + '/../../src/frontend/js/command/panels/enrichment-panel.js', 'utf8');
const panelPlain = panelCode
    .replace(/^export\s+const\s+/gm, 'var ')
    .replace(/^export\s+/gm, '')
    .replace(/^import\s+.*$/gm, '');
vm.runInContext(panelPlain, ctx);

const EnrichmentPanelDef = ctx.EnrichmentPanelDef;

// ============================================================
// 1. PanelDef structure
// ============================================================

console.log('\n--- EnrichmentPanelDef structure ---');

(function testHasId() {
    assert(EnrichmentPanelDef.id === 'enrichment', 'id is "enrichment"');
})();

(function testHasTitle() {
    assert(EnrichmentPanelDef.title === 'ENRICHMENT', 'title is "ENRICHMENT"');
})();

(function testHasCreate() {
    assert(typeof EnrichmentPanelDef.create === 'function', 'create is a function');
})();

(function testHasMount() {
    assert(typeof EnrichmentPanelDef.mount === 'function', 'mount is a function');
})();

(function testHasUnmount() {
    assert(typeof EnrichmentPanelDef.unmount === 'function', 'unmount is a function');
})();

(function testDefaultPosition() {
    assert(EnrichmentPanelDef.defaultPosition !== undefined, 'has defaultPosition');
    assert(typeof EnrichmentPanelDef.defaultPosition.x === 'number', 'defaultPosition.x is a number');
    assert(typeof EnrichmentPanelDef.defaultPosition.y === 'number', 'defaultPosition.y is a number');
})();

(function testDefaultSize() {
    assert(EnrichmentPanelDef.defaultSize !== undefined, 'has defaultSize');
    assert(EnrichmentPanelDef.defaultSize.w === 460, 'defaultSize.w is 460');
    assert(EnrichmentPanelDef.defaultSize.h === 520, 'defaultSize.h is 520');
})();

// ============================================================
// 2. create() DOM structure
// ============================================================

console.log('\n--- create() DOM structure ---');

(function testCreateReturnsElement() {
    const el = EnrichmentPanelDef.create({});
    assert(el !== null && el !== undefined, 'create() returns an element');
    assert(el.className === 'enrichment-panel', 'className is "enrichment-panel"');
})();

(function testCreateHasTargetIdInput() {
    const el = EnrichmentPanelDef.create({});
    assert(el.innerHTML.includes('data-bind="enrich-target-id"'), 'DOM has target ID input');
})();

(function testCreateHasResultsBinding() {
    const el = EnrichmentPanelDef.create({});
    assert(el.innerHTML.includes('data-bind="enrich-results"'), 'DOM has enrich-results data-bind');
})();

(function testCreateHasTargetListBinding() {
    const el = EnrichmentPanelDef.create({});
    assert(el.innerHTML.includes('data-bind="enrich-target-list"'), 'DOM has enrich-target-list data-bind');
})();

(function testCreateHasLookupButton() {
    const el = EnrichmentPanelDef.create({});
    assert(el.innerHTML.includes('data-action="lookup-enrichment"'), 'DOM has lookup action button');
})();

(function testCreateHasForceButton() {
    const el = EnrichmentPanelDef.create({});
    assert(el.innerHTML.includes('data-action="force-enrich"'), 'DOM has force-enrich action button');
})();

(function testCreateHasRefreshButton() {
    const el = EnrichmentPanelDef.create({});
    assert(el.innerHTML.includes('data-action="refresh-targets"'), 'DOM has refresh-targets action button');
})();

(function testCreateHasTimestampBinding() {
    const el = EnrichmentPanelDef.create({});
    assert(el.innerHTML.includes('data-bind="enrich-timestamp"'), 'DOM has enrich-timestamp data-bind');
})();

// ============================================================
// 3. Render helper functions
// ============================================================

console.log('\n--- Render helpers ---');

(function testSourceIconFunction() {
    const fn = vm.runInContext('typeof _sourceIcon', ctx);
    assert(fn === 'function', '_sourceIcon function exists');
})();

(function testSourceIconMac() {
    const result = vm.runInContext('_sourceIcon("mac_lookup")', ctx);
    assert(result === 'MAC', '_sourceIcon("mac_lookup") returns "MAC"');
})();

(function testSourceIconGeo() {
    const result = vm.runInContext('_sourceIcon("geo")', ctx);
    assert(result === 'GEO', '_sourceIcon("geo") returns "GEO"');
})();

(function testSourceIconUnknown() {
    const result = vm.runInContext('_sourceIcon("something_new")', ctx);
    assert(result === 'SOMET', '_sourceIcon truncates unknown sources to 5 chars');
})();

(function testSourceColorFunction() {
    const fn = vm.runInContext('typeof _sourceColor', ctx);
    assert(fn === 'function', '_sourceColor function exists');
})();

(function testSourceColorMac() {
    const result = vm.runInContext('_sourceColor("mac_lookup")', ctx);
    assert(result === '#00f0ff', '_sourceColor("mac_lookup") returns cyan');
})();

(function testSourceColorReputation() {
    const result = vm.runInContext('_sourceColor("reputation")', ctx);
    assert(result === '#ff2a6d', '_sourceColor("reputation") returns magenta');
})();

(function testConfidenceBadgeFunction() {
    const fn = vm.runInContext('typeof _confidenceBadge', ctx);
    assert(fn === 'function', '_confidenceBadge function exists');
})();

(function testConfidenceBadgeHigh() {
    const result = vm.runInContext('_confidenceBadge(0.85)', ctx);
    assert(result.includes('85%'), '_confidenceBadge shows percentage');
    assert(result.includes('#05ffa1'), '_confidenceBadge uses green for high confidence');
})();

(function testConfidenceBadgeLow() {
    const result = vm.runInContext('_confidenceBadge(0.2)', ctx);
    assert(result.includes('20%'), '_confidenceBadge shows low percentage');
    assert(result.includes('#ff2a6d'), '_confidenceBadge uses magenta for low confidence');
})();

// ============================================================
// 4. Target selector rendering
// ============================================================

console.log('\n--- Target selector ---');

(function testTargetSelectorFunction() {
    const fn = vm.runInContext('typeof _targetSelector', ctx);
    assert(fn === 'function', '_targetSelector function exists');
})();

(function testTargetSelectorEmpty() {
    const result = vm.runInContext('_targetSelector([])', ctx);
    assert(result.includes('No targets available'), '_targetSelector shows empty state');
})();

(function testTargetSelectorWithData() {
    const result = vm.runInContext(`_targetSelector([
        { target_id: "ble_aabbccddeeff", name: "Phone A", asset_type: "phone", alliance: "friendly" }
    ])`, ctx);
    assert(result.includes('ble_aabbccddeeff'), '_targetSelector shows target ID');
    assert(result.includes('Phone A'), '_targetSelector shows name');
    assert(result.includes('phone'), '_targetSelector shows asset type');
    assert(result.includes('friendly'), '_targetSelector shows alliance');
})();

// ============================================================
// 5. Enrichment results rendering
// ============================================================

console.log('\n--- Enrichment results ---');

(function testEnrichmentResultsFunction() {
    const fn = vm.runInContext('typeof _enrichmentResults', ctx);
    assert(fn === 'function', '_enrichmentResults function exists');
})();

(function testEnrichmentResultsNull() {
    const result = vm.runInContext('_enrichmentResults(null)', ctx);
    assert(result === '', '_enrichmentResults(null) returns empty');
})();

(function testEnrichmentResultsError() {
    const result = vm.runInContext('_enrichmentResults({ error: "Pipeline unavailable" })', ctx);
    assert(result.includes('Pipeline unavailable'), '_enrichmentResults shows error');
})();

(function testEnrichmentResultsEmpty() {
    const result = vm.runInContext('_enrichmentResults({ target_id: "test", enrichments: [], cached: false })', ctx);
    assert(result.includes('No enrichment data'), '_enrichmentResults shows empty state');
})();

(function testEnrichmentResultsWithData() {
    const result = vm.runInContext(`_enrichmentResults({
        target_id: "ble_test",
        enrichments: [
            { source: "mac_lookup", confidence: 0.9, data: { vendor: "Apple", model: "iPhone 15" } },
            { source: "geo", confidence: 0.7, data: { country: "US", city: "Austin" } },
        ],
        cached: true,
    })`, ctx);
    assert(result.includes('2 ENRICHMENTS'), '_enrichmentResults shows count');
    assert(result.includes('CACHED'), '_enrichmentResults shows cached badge');
    assert(result.includes('MAC'), '_enrichmentResults shows source icon');
    assert(result.includes('Apple'), '_enrichmentResults shows data value');
    assert(result.includes('vendor'), '_enrichmentResults shows data key');
})();

// ============================================================
// 6. XSS prevention
// ============================================================

console.log('\n--- XSS prevention ---');

(function testTargetSelectorXss() {
    const result = vm.runInContext(`_targetSelector([
        { target_id: "<script>alert(1)</script>", name: "<img onerror=x>", asset_type: "x", alliance: "x" }
    ])`, ctx);
    assert(!result.includes('<script>'), 'Target selector escapes script tags');
    assert(!result.includes('<img onerror'), 'Target selector escapes img injection');
})();

(function testEnrichmentResultsXss() {
    const result = vm.runInContext(`_enrichmentResults({
        target_id: "test",
        enrichments: [
            { source: "<script>x</script>", confidence: 0.5, data: { key: "<img onerror=x>" } }
        ],
        cached: false,
    })`, ctx);
    assert(!result.includes('<script>'), 'Enrichment results escapes script tags');
    assert(!result.includes('<img onerror'), 'Enrichment results escapes img injection');
})();

// ============================================================
// 7. mount() wiring
// ============================================================

console.log('\n--- mount() ---');

(function testMountDoesNotCrash() {
    const bodyEl = createMockElement('div');
    const panel = {};

    let threw = false;
    try {
        EnrichmentPanelDef.mount(bodyEl, panel);
    } catch (e) {
        threw = true;
        console.error('mount() error:', e);
    }
    assert(!threw, 'mount() does not crash');
})();

// ============================================================
// 8. unmount() cleanup
// ============================================================

console.log('\n--- unmount() ---');

(function testUnmountDoesNotCrash() {
    let threw = false;
    try {
        EnrichmentPanelDef.unmount(createMockElement('div'), {});
    } catch (e) {
        threw = true;
    }
    assert(!threw, 'unmount() does not throw');
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

// ============================================================
// Summary
// ============================================================

console.log('\n' + '='.repeat(50));
console.log(`Results: ${passed} passed, ${failed} failed`);
console.log('='.repeat(50));
process.exit(failed > 0 ? 1 : 0);
