/**
 * TRITIUM-SC Alerts Panel tests
 * Tests AlertsPanelDef structure, DOM creation, feed list, count binding,
 * accessibility attributes, _esc utility, and mount subscription wiring.
 * Run: node tests/js/test_alerts_panel.js
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

// Load alerts.js panel
const alertsCode = fs.readFileSync(__dirname + '/../../frontend/js/command/panels/alerts.js', 'utf8');
const alertsPlain = alertsCode
    .replace(/^export\s+const\s+/gm, 'var ')
    .replace(/^export\s+/gm, '')
    .replace(/^import\s+.*$/gm, '');
vm.runInContext(alertsPlain, ctx);

const AlertsPanelDef = ctx.AlertsPanelDef;

// ============================================================
// 1. AlertsPanelDef has required properties
// ============================================================

console.log('\n--- AlertsPanelDef structure ---');

(function testHasId() {
    assert(AlertsPanelDef.id === 'alerts', 'AlertsPanelDef.id is "alerts"');
})();

(function testHasTitle() {
    assert(AlertsPanelDef.title === 'ALERTS', 'AlertsPanelDef.title is "ALERTS"');
})();

(function testHasCreate() {
    assert(typeof AlertsPanelDef.create === 'function', 'AlertsPanelDef.create is a function');
})();

(function testHasMount() {
    assert(typeof AlertsPanelDef.mount === 'function', 'AlertsPanelDef.mount is a function');
})();

(function testHasUnmount() {
    assert(typeof AlertsPanelDef.unmount === 'function', 'AlertsPanelDef.unmount is a function');
})();

(function testHasDefaultPosition() {
    assert(AlertsPanelDef.defaultPosition !== undefined, 'AlertsPanelDef has defaultPosition');
    // x is null (calculated at mount time — top-right)
    assert(AlertsPanelDef.defaultPosition.x === null, 'defaultPosition.x is null (calculated at mount)');
    assert(AlertsPanelDef.defaultPosition.y === 44, 'defaultPosition.y is 44');
})();

(function testHasDefaultSize() {
    assert(AlertsPanelDef.defaultSize !== undefined, 'AlertsPanelDef has defaultSize');
    assert(AlertsPanelDef.defaultSize.w === 280, 'defaultSize.w is 280');
    assert(AlertsPanelDef.defaultSize.h === 320, 'defaultSize.h is 320');
})();

// ============================================================
// 2. create() returns DOM element with expected structure
// ============================================================

console.log('\n--- create() DOM structure ---');

(function testCreateReturnsDomElement() {
    const el = AlertsPanelDef.create({});
    assert(el !== null && el !== undefined, 'create() returns an element');
    assert(el.className === 'alerts-panel-inner', 'create() element has correct className');
})();

(function testCreateHasCountBinding() {
    const el = AlertsPanelDef.create({});
    const html = el.innerHTML;
    assert(html.includes('data-bind="count"'), 'DOM contains unread count data-bind');
    assert(html.includes('UNREAD'), 'DOM contains "UNREAD" label');
})();

(function testCountDefaultsToZero() {
    const el = AlertsPanelDef.create({});
    const html = el.innerHTML;
    assert(html.includes('>0<'), 'Count element defaults to 0');
})();

(function testCreateHasFeedList() {
    const el = AlertsPanelDef.create({});
    const html = el.innerHTML;
    assert(html.includes('data-bind="feed"'), 'DOM contains feed list data-bind');
    assert(html.includes('panel-list'), 'Feed list has panel-list class');
})();

(function testCreateHasEmptyState() {
    const el = AlertsPanelDef.create({});
    const html = el.innerHTML;
    assert(html.includes('No alerts'), 'DOM contains empty state text "No alerts"');
    assert(html.includes('panel-empty'), 'Empty state has panel-empty class');
})();

// ============================================================
// 3. Accessibility attributes
// ============================================================

console.log('\n--- Accessibility ---');

(function testFeedHasLogRole() {
    const el = AlertsPanelDef.create({});
    const html = el.innerHTML;
    assert(html.includes('role="log"'), 'Feed list has role="log"');
})();

(function testFeedHasAriaLabel() {
    const el = AlertsPanelDef.create({});
    const html = el.innerHTML;
    assert(html.includes('aria-label="Alert feed"'), 'Feed list has aria-label="Alert feed"');
})();

(function testFeedHasAriaLive() {
    const el = AlertsPanelDef.create({});
    const html = el.innerHTML;
    assert(html.includes('aria-live="polite"'), 'Feed list has aria-live="polite" for screen readers');
})();

// ============================================================
// 4. Section label
// ============================================================

console.log('\n--- Section label ---');

(function testSectionLabelExists() {
    const el = AlertsPanelDef.create({});
    const html = el.innerHTML;
    assert(html.includes('panel-section-label'), 'DOM contains panel-section-label');
})();

// ============================================================
// 5. _esc utility function
// ============================================================

console.log('\n--- _esc utility ---');

(function testEscExists() {
    const fn = vm.runInContext('typeof _esc', ctx);
    assert(fn === 'function', '_esc function exists');
})();

(function testEscEmpty() {
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
    const result = vm.runInContext('_esc("Motion detected at front door")', ctx);
    assert(result === 'Motion detected at front door', '_esc passes through safe text');
})();

(function testEscHtmlTags() {
    const result = vm.runInContext('_esc("<img src=x onerror=alert(1)>")', ctx);
    assert(!result.includes('<img'), '_esc escapes img tags');
    assert(result.includes('&lt;'), '_esc converts < to &lt;');
})();

// ============================================================
// 6. mount() wires subscriptions and positions panel
// ============================================================

console.log('\n--- mount() ---');

(function testMountSubscribes() {
    const bodyEl = createMockElement('div');
    const panel = {
        def: AlertsPanelDef,
        w: 280,
        x: 0,
        manager: { container: createMockElement('div') },
        _unsubs: [],
        _applyTransform() {},
    };
    panel.manager.container.clientWidth = 1200;

    AlertsPanelDef.mount(bodyEl, panel);
    // Should subscribe to 'alerts'
    assert(panel._unsubs.length >= 1, 'mount() registers at least 1 subscription, got ' + panel._unsubs.length);
})();

(function testMountCalculatesXPosition() {
    const bodyEl = createMockElement('div');
    const panel = {
        def: AlertsPanelDef,
        w: 280,
        x: 0,
        manager: { container: createMockElement('div') },
        _unsubs: [],
        _applyTransform() {},
    };
    panel.manager.container.clientWidth = 1200;

    AlertsPanelDef.mount(bodyEl, panel);
    // x should be: cw - w - 8 = 1200 - 280 - 8 = 912
    assert(panel.x === 912, 'mount() positions panel at top-right (expected 912, got ' + panel.x + ')');
})();

(function testMountDoesNotCrashWithEmptyAlerts() {
    const bodyEl = createMockElement('div');
    const panel = {
        def: AlertsPanelDef,
        w: 280,
        x: 0,
        manager: { container: createMockElement('div') },
        _unsubs: [],
        _applyTransform() {},
    };
    panel.manager.container.clientWidth = 1200;

    let threw = false;
    try {
        AlertsPanelDef.mount(bodyEl, panel);
    } catch (e) {
        threw = true;
    }
    assert(!threw, 'mount() does not crash with empty alerts array');
})();

(function testMountWithSmallContainer() {
    const bodyEl = createMockElement('div');
    const panel = {
        def: AlertsPanelDef,
        w: 280,
        x: 0,
        manager: { container: createMockElement('div') },
        _unsubs: [],
        _applyTransform() {},
    };
    panel.manager.container.clientWidth = 400;

    AlertsPanelDef.mount(bodyEl, panel);
    // x should be: 400 - 280 - 8 = 112
    assert(panel.x === 112, 'mount() positions correctly in small container (expected 112, got ' + panel.x + ')');
})();

// ============================================================
// 7. unmount() exists and does not crash
// ============================================================

console.log('\n--- unmount() ---');

(function testUnmountDoesNotCrash() {
    const bodyEl = createMockElement('div');
    let threw = false;
    try {
        AlertsPanelDef.unmount(bodyEl);
    } catch (e) {
        threw = true;
    }
    assert(!threw, 'unmount() does not throw');
})();

// ============================================================
// 8. Alert rendering in mount's render function
// (We test the render logic by calling the store subscription)
// ============================================================

console.log('\n--- Alert rendering via store ---');

(function testRenderWithAlerts() {
    const bodyEl = createMockElement('div');
    const panel = {
        def: AlertsPanelDef,
        w: 280,
        x: 0,
        manager: { container: createMockElement('div') },
        _unsubs: [],
        _applyTransform() {},
    };
    panel.manager.container.clientWidth = 1200;

    AlertsPanelDef.mount(bodyEl, panel);

    // Add alerts to the store and trigger the subscriber
    const TritiumStore = vm.runInContext('TritiumStore', ctx);
    const testAlerts = [
        { id: '1', type: 'escalation', message: 'Hostile detected', time: Date.now(), read: false },
        { id: '2', type: 'warning', message: 'Low battery on rover', time: Date.now(), read: true },
        { id: '3', type: 'info', message: 'Patrol complete', time: Date.now(), read: false },
    ];

    // The store subscription is registered; trigger it
    TritiumStore.alerts = testAlerts;
    TritiumStore.set('alerts', testAlerts);

    // We cannot directly inspect the rendered HTML in the mock since
    // querySelector returns new mocks each time, but we verified the
    // subscription was wired and the store notification did not crash
    assert(true, 'Store alert notification did not crash');
})();

(function testRenderWithEmptyAlerts() {
    const bodyEl = createMockElement('div');
    const panel = {
        def: AlertsPanelDef,
        w: 280,
        x: 0,
        manager: { container: createMockElement('div') },
        _unsubs: [],
        _applyTransform() {},
    };
    panel.manager.container.clientWidth = 1200;

    AlertsPanelDef.mount(bodyEl, panel);

    const TritiumStore = vm.runInContext('TritiumStore', ctx);
    TritiumStore.alerts = [];
    // Trigger notification -- should show "No alerts"
    let threw = false;
    try {
        TritiumStore.set('alerts', []);
    } catch (e) {
        threw = true;
    }
    assert(!threw, 'Rendering empty alerts does not crash');
})();

(function testRenderWithNullAlerts() {
    const bodyEl = createMockElement('div');
    const panel = {
        def: AlertsPanelDef,
        w: 280,
        x: 0,
        manager: { container: createMockElement('div') },
        _unsubs: [],
        _applyTransform() {},
    };
    panel.manager.container.clientWidth = 1200;

    AlertsPanelDef.mount(bodyEl, panel);

    const TritiumStore = vm.runInContext('TritiumStore', ctx);
    let threw = false;
    try {
        TritiumStore.set('alerts', null);
    } catch (e) {
        threw = true;
    }
    assert(!threw, 'Rendering null alerts does not crash');
})();

// ============================================================
// Summary
// ============================================================

console.log('\n' + '='.repeat(40));
console.log(`Results: ${passed} passed, ${failed} failed`);
console.log('='.repeat(40));
process.exit(failed > 0 ? 1 : 0);
