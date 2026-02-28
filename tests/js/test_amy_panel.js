// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
/**
 * TRITIUM-SC Amy Commander Panel tests
 * Tests AmyPanelDef structure, DOM creation, data-bind elements,
 * action buttons, _esc utility, and mount subscription wiring.
 * Run: node tests/js/test_amy_panel.js
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
            // Parse data-bind and data-action attributes for querySelector
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
            // Simulate browser: textContent sets innerHTML to escaped text
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

// Load events.js (EventBus)
const eventsCode = fs.readFileSync(__dirname + '/../../frontend/js/command/events.js', 'utf8');
const eventsPlain = eventsCode
    .replace(/^export\s+/gm, '')
    .replace(/^import\s+.*$/gm, '');
vm.runInContext(eventsPlain, ctx);

// Load store.js (TritiumStore)
const storeCode = fs.readFileSync(__dirname + '/../../frontend/js/command/store.js', 'utf8');
const storePlain = storeCode
    .replace(/^export\s+/gm, '')
    .replace(/^import\s+.*$/gm, '');
vm.runInContext(storePlain, ctx);

// Load amy.js panel
const amyCode = fs.readFileSync(__dirname + '/../../frontend/js/command/panels/amy.js', 'utf8');
const amyPlain = amyCode
    .replace(/^export\s+const\s+/gm, 'var ')
    .replace(/^export\s+/gm, '')
    .replace(/^import\s+.*$/gm, '');
vm.runInContext(amyPlain, ctx);

const AmyPanelDef = ctx.AmyPanelDef;

// ============================================================
// 1. AmyPanelDef has required properties
// ============================================================

console.log('\n--- AmyPanelDef structure ---');

(function testHasId() {
    assert(AmyPanelDef.id === 'amy', 'AmyPanelDef.id is "amy"');
})();

(function testHasTitle() {
    assert(AmyPanelDef.title === 'AMY COMMANDER', 'AmyPanelDef.title is "AMY COMMANDER"');
})();

(function testHasCreate() {
    assert(typeof AmyPanelDef.create === 'function', 'AmyPanelDef.create is a function');
})();

(function testHasMount() {
    assert(typeof AmyPanelDef.mount === 'function', 'AmyPanelDef.mount is a function');
})();

(function testHasUnmount() {
    assert(typeof AmyPanelDef.unmount === 'function', 'AmyPanelDef.unmount is a function');
})();

(function testHasDefaultPosition() {
    assert(AmyPanelDef.defaultPosition !== undefined, 'AmyPanelDef has defaultPosition');
    assert(AmyPanelDef.defaultPosition.x === 8, 'defaultPosition.x is 8');
    // y is null (calculated at mount time)
    assert(AmyPanelDef.defaultPosition.y === null, 'defaultPosition.y is null (calculated at mount)');
})();

(function testHasDefaultSize() {
    assert(AmyPanelDef.defaultSize !== undefined, 'AmyPanelDef has defaultSize');
    assert(AmyPanelDef.defaultSize.w === 320, 'defaultSize.w is 320');
    assert(AmyPanelDef.defaultSize.h === 200, 'defaultSize.h is 200');
})();

// ============================================================
// 2. create() returns DOM element with expected structure
// ============================================================

console.log('\n--- create() DOM structure ---');

(function testCreateReturnsDomElement() {
    const el = AmyPanelDef.create({});
    assert(el !== null && el !== undefined, 'create() returns an element');
    assert(el.className === 'amy-panel-inner', 'create() element has correct className');
})();

(function testCreateHasPortrait() {
    const el = AmyPanelDef.create({});
    const html = el.innerHTML;
    assert(html.includes('amy-p-portrait'), 'DOM contains portrait element');
    assert(html.includes('amy-p-avatar'), 'DOM contains avatar element');
    assert(html.includes('amy-p-speaking-ring'), 'DOM contains speaking ring indicator');
})();

(function testCreateHasInfoSection() {
    const el = AmyPanelDef.create({});
    const html = el.innerHTML;
    assert(html.includes('amy-p-name'), 'DOM contains name element');
    assert(html.includes('AMY'), 'DOM contains "AMY" name text');
})();

(function testCreateHasStateBinding() {
    const el = AmyPanelDef.create({});
    const html = el.innerHTML;
    assert(html.includes('data-bind="state"'), 'DOM contains state data-bind');
    assert(html.includes('IDLE'), 'DOM contains default state "IDLE"');
})();

(function testCreateHasMoodBinding() {
    const el = AmyPanelDef.create({});
    const html = el.innerHTML;
    assert(html.includes('data-bind="mood"'), 'DOM contains mood data-bind');
    assert(html.includes('data-bind="mood-label"'), 'DOM contains mood-label data-bind');
    assert(html.includes('CALM'), 'DOM contains default mood "CALM"');
})();

(function testCreateHasMoodDot() {
    const el = AmyPanelDef.create({});
    const html = el.innerHTML;
    assert(html.includes('panel-dot'), 'DOM contains mood dot indicator');
    assert(html.includes('panel-dot-neutral'), 'DOM mood dot defaults to neutral');
})();

(function testCreateHasThoughtBinding() {
    const el = AmyPanelDef.create({});
    const html = el.innerHTML;
    assert(html.includes('data-bind="thought"'), 'DOM contains thought data-bind');
    assert(html.includes('Awaiting initialization...'), 'DOM contains default thought text');
})();

(function testCreateHasSvgAvatar() {
    const el = AmyPanelDef.create({});
    const html = el.innerHTML;
    assert(html.includes('<svg'), 'DOM contains SVG avatar');
    assert(html.includes('viewBox="0 0 40 40"'), 'SVG has correct viewBox');
})();

// ============================================================
// 3. Action buttons
// ============================================================

console.log('\n--- Action buttons ---');

(function testCreateHasChatButton() {
    const el = AmyPanelDef.create({});
    const html = el.innerHTML;
    assert(html.includes('data-action="chat"'), 'DOM contains CHAT action button');
    assert(html.includes('>CHAT<'), 'CHAT button has correct label');
})();

(function testCreateHasAttendButton() {
    const el = AmyPanelDef.create({});
    const html = el.innerHTML;
    assert(html.includes('data-action="attend"'), 'DOM contains ATTEND action button');
    assert(html.includes('>ATTEND<'), 'ATTEND button has correct label');
})();

(function testChatButtonIsPrimary() {
    const el = AmyPanelDef.create({});
    const html = el.innerHTML;
    assert(html.includes('panel-action-btn-primary'), 'CHAT button has primary styling');
})();

(function testActionsContainer() {
    const el = AmyPanelDef.create({});
    const html = el.innerHTML;
    assert(html.includes('amy-p-actions'), 'DOM contains actions container');
})();

// ============================================================
// 4. _esc utility function
// ============================================================

console.log('\n--- _esc utility ---');

(function testEscExists() {
    const fn = vm.runInContext('typeof _esc', ctx);
    assert(fn === 'function', '_esc function exists in context');
})();

(function testEscEmptyString() {
    const result = vm.runInContext('_esc("")', ctx);
    assert(result === '', '_esc("") returns empty string');
})();

(function testEscNull() {
    const result = vm.runInContext('_esc(null)', ctx);
    assert(result === '', '_esc(null) returns empty string');
})();

(function testEscUndefined() {
    const result = vm.runInContext('_esc(undefined)', ctx);
    assert(result === '', '_esc(undefined) returns empty string');
})();

(function testEscPlainText() {
    const result = vm.runInContext('_esc("hello")', ctx);
    assert(result === 'hello', '_esc("hello") returns "hello"');
})();

(function testEscHtmlEntities() {
    const result = vm.runInContext('_esc("<script>alert(1)</script>")', ctx);
    assert(!result.includes('<script>'), '_esc escapes HTML tags');
    assert(result.includes('&lt;'), '_esc converts < to &lt;');
})();

(function testEscAmpersand() {
    const result = vm.runInContext('_esc("a&b")', ctx);
    assert(result.includes('&amp;'), '_esc converts & to &amp;');
})();

(function testEscQuotes() {
    const result = vm.runInContext('_esc(\'a"b\')', ctx);
    // textContent + innerHTML in browsers does NOT escape quotes,
    // but our mock does. The real point is: it does not return raw HTML.
    assert(typeof result === 'string' && result.length > 0, '_esc handles quotes without crashing');
})();

// ============================================================
// 5. mount() wires subscriptions
// ============================================================

console.log('\n--- mount() subscription wiring ---');

(function testMountSubscribesToAmyState() {
    const bodyEl = createMockElement('div');
    const panel = {
        def: AmyPanelDef,
        h: 200,
        y: 0,
        manager: { container: createMockElement('div') },
        _unsubs: [],
        _applyTransform() {},
    };
    panel.manager.container.clientHeight = 700;

    AmyPanelDef.mount(bodyEl, panel);
    // mount should have pushed subscriptions to _unsubs
    assert(panel._unsubs.length >= 4, 'mount() registers at least 4 subscriptions (state, mood, lastThought, speaking), got ' + panel._unsubs.length);
})();

(function testMountCalculatesYPosition() {
    const bodyEl = createMockElement('div');
    const panel = {
        def: AmyPanelDef,
        h: 200,
        y: 0,
        manager: { container: createMockElement('div') },
        _unsubs: [],
        _applyTransform() {},
    };
    panel.manager.container.clientHeight = 700;

    AmyPanelDef.mount(bodyEl, panel);
    // y should be calculated: ch - h - 28 = 700 - 200 - 28 = 472
    assert(panel.y === 472, 'mount() calculates y position from container height (expected 472, got ' + panel.y + ')');
})();

(function testMountFetchesInitialStatus() {
    let fetchCalled = false;
    const origFetch = ctx.fetch;
    ctx.fetch = (url) => {
        if (typeof url === 'string' && url.includes('/api/amy/status')) fetchCalled = true;
        return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    };

    const bodyEl = createMockElement('div');
    const panel = {
        def: AmyPanelDef,
        h: 200,
        y: 0,
        manager: { container: createMockElement('div') },
        _unsubs: [],
        _applyTransform() {},
    };
    panel.manager.container.clientHeight = 700;

    AmyPanelDef.mount(bodyEl, panel);
    assert(fetchCalled, 'mount() fetches /api/amy/status on init');
    ctx.fetch = origFetch;
})();

// ============================================================
// 6. unmount() exists and does not crash
// ============================================================

console.log('\n--- unmount() ---');

(function testUnmountDoesNotCrash() {
    const bodyEl = createMockElement('div');
    let threw = false;
    try {
        AmyPanelDef.unmount(bodyEl);
    } catch (e) {
        threw = true;
    }
    assert(!threw, 'unmount() does not throw');
})();

// ============================================================
// 7. Panel layout row structure
// ============================================================

console.log('\n--- Layout structure ---');

(function testHasMainRow() {
    const el = AmyPanelDef.create({});
    const html = el.innerHTML;
    assert(html.includes('amy-p-row'), 'DOM has main layout row');
})();

(function testHasInfoBlock() {
    const el = AmyPanelDef.create({});
    const html = el.innerHTML;
    assert(html.includes('amy-p-info'), 'DOM has info block');
})();

(function testHasNameRow() {
    const el = AmyPanelDef.create({});
    const html = el.innerHTML;
    assert(html.includes('amy-p-name-row'), 'DOM has name row');
})();

(function testHasThoughtSection() {
    const el = AmyPanelDef.create({});
    const html = el.innerHTML;
    assert(html.includes('amy-p-thought'), 'DOM has thought section');
})();

(function testStateIsMonospaced() {
    const el = AmyPanelDef.create({});
    const html = el.innerHTML;
    assert(html.includes('class="amy-p-state mono"'), 'State element uses mono class for monospace font');
})();

// ============================================================
// Summary
// ============================================================

console.log('\n' + '='.repeat(40));
console.log(`Results: ${passed} passed, ${failed} failed`);
console.log('='.repeat(40));
process.exit(failed > 0 ? 1 : 0);
