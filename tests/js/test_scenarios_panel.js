/**
 * TRITIUM-SC Scenarios Panel tests
 * Tests ScenariosPanelDef structure, DOM creation, toolbar, progress bar,
 * scenario list, stats area, and mount wiring.
 * Run: node tests/js/test_scenarios_panel.js
 */

const fs = require('fs');
const vm = require('vm');

let passed = 0, failed = 0;
function assert(cond, msg) {
    if (!cond) { console.error('FAIL:', msg); failed++; }
    else { console.log('PASS:', msg); passed++; }
}

function createMockElement(tag) {
    const children = [];
    const classList = new Set();
    const eventListeners = {};
    const dataset = {};
    const style = {};
    let _innerHTML = '';
    let _textContent = '';
    const el = {
        tagName: (tag || 'DIV').toUpperCase(), className: '',
        get innerHTML() { return _innerHTML; },
        set innerHTML(val) { _innerHTML = val; },
        get textContent() { return _textContent; },
        set textContent(val) { _textContent = String(val); _innerHTML = String(val).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); },
        style, dataset, children, childNodes: children, parentNode: null, hidden: false, value: '', disabled: false,
        get classList() {
            return { add(cls) { classList.add(cls); }, remove(cls) { classList.delete(cls); }, contains(cls) { return classList.has(cls); },
                toggle(cls, force) { if (force === undefined) { if (classList.has(cls)) classList.delete(cls); else classList.add(cls); } else if (force) classList.add(cls); else classList.delete(cls); } };
        },
        appendChild(child) { children.push(child); if (child && typeof child === 'object') child.parentNode = el; return child; },
        remove() {}, focus() {},
        addEventListener(evt, fn) { if (!eventListeners[evt]) eventListeners[evt] = []; eventListeners[evt].push(fn); },
        removeEventListener(evt, fn) { if (eventListeners[evt]) eventListeners[evt] = eventListeners[evt].filter(f => f !== fn); },
        querySelector(sel) {
            const bindMatch = sel.match(/\[data-bind="([^"]+)"\]/);
            if (bindMatch) { const mock = createMockElement('div'); mock._bindName = bindMatch[1]; return mock; }
            const actionMatch = sel.match(/\[data-action="([^"]+)"\]/);
            if (actionMatch) { const mock = createMockElement('button'); mock._actionName = actionMatch[1]; return mock; }
            return null;
        },
        querySelectorAll(sel) { return []; }, closest(sel) { return null; },
        _eventListeners: eventListeners, _classList: classList,
    };
    return el;
}

const sandbox = {
    Math, Date, console, Map, Set, Array, Object, Number, String, Boolean,
    Infinity, NaN, undefined, parseInt, parseFloat, isNaN, isFinite, JSON,
    Promise, setTimeout, clearTimeout, setInterval, clearInterval, Error,
    document: { createElement: createMockElement, getElementById: () => null, querySelector: () => null, addEventListener() {}, removeEventListener() {} },
    window: {},
    fetch: () => Promise.resolve({ ok: true, json: () => Promise.resolve([]) }),
    performance: { now: () => Date.now() },
};

const ctx = vm.createContext(sandbox);

vm.runInContext(fs.readFileSync(__dirname + '/../../frontend/js/command/events.js', 'utf8').replace(/^export\s+/gm, '').replace(/^import\s+.*$/gm, ''), ctx);
vm.runInContext(fs.readFileSync(__dirname + '/../../frontend/js/command/store.js', 'utf8').replace(/^export\s+/gm, '').replace(/^import\s+.*$/gm, ''), ctx);

const scnCode = fs.readFileSync(__dirname + '/../../frontend/js/command/panels/scenarios.js', 'utf8');
vm.runInContext(scnCode.replace(/^export\s+const\s+/gm, 'var ').replace(/^export\s+/gm, '').replace(/^import\s+.*$/gm, ''), ctx);

const ScenariosPanelDef = ctx.ScenariosPanelDef;

// ============================================================
// 1. Structure
// ============================================================
console.log('\n--- ScenariosPanelDef structure ---');

(function() { assert(ScenariosPanelDef.id === 'scenarios', 'id is "scenarios"'); })();
(function() { assert(ScenariosPanelDef.title === 'SCENARIOS', 'title is "SCENARIOS"'); })();
(function() { assert(typeof ScenariosPanelDef.create === 'function', 'create is a function'); })();
(function() { assert(typeof ScenariosPanelDef.mount === 'function', 'mount is a function'); })();
(function() { assert(typeof ScenariosPanelDef.unmount === 'function', 'unmount is a function'); })();
(function() { assert(ScenariosPanelDef.defaultPosition.x === 8, 'defaultPosition.x is 8'); })();
(function() { assert(ScenariosPanelDef.defaultPosition.y === 8, 'defaultPosition.y is 8'); })();
(function() { assert(ScenariosPanelDef.defaultSize.w === 320, 'defaultSize.w is 320'); })();
(function() { assert(ScenariosPanelDef.defaultSize.h === 400, 'defaultSize.h is 400'); })();

// ============================================================
// 2. create() DOM
// ============================================================
console.log('\n--- create() DOM ---');

(function() { assert(ScenariosPanelDef.create({}).className === 'scenarios-panel-inner', 'className correct'); })();
(function() { const html = ScenariosPanelDef.create({}).innerHTML; assert(html.includes('data-action="refresh"'), 'Has REFRESH button'); })();
(function() { const html = ScenariosPanelDef.create({}).innerHTML; assert(html.includes('data-action="run-all"'), 'Has RUN ALL button'); })();
(function() { const html = ScenariosPanelDef.create({}).innerHTML; assert(html.includes('data-bind="stats"'), 'Has stats area'); })();
(function() { const html = ScenariosPanelDef.create({}).innerHTML; assert(html.includes('data-bind="scenario-list"'), 'Has scenario list'); })();
(function() { const html = ScenariosPanelDef.create({}).innerHTML; assert(html.includes('data-bind="run-progress"'), 'Has run progress area'); })();
(function() { const html = ScenariosPanelDef.create({}).innerHTML; assert(html.includes('data-bind="progress-fill"'), 'Has progress bar fill'); })();
(function() { const html = ScenariosPanelDef.create({}).innerHTML; assert(html.includes('data-bind="progress-label"'), 'Has progress label'); })();
(function() { const html = ScenariosPanelDef.create({}).innerHTML; assert(html.includes('data-bind="progress-status"'), 'Has progress status'); })();
(function() { const html = ScenariosPanelDef.create({}).innerHTML; assert(html.includes('Loading scenarios...'), 'Has loading state'); })();

// ============================================================
// 3. Progress hidden by default
// ============================================================
console.log('\n--- Progress state ---');

(function() { const html = ScenariosPanelDef.create({}).innerHTML; assert(html.includes('display:none'), 'Progress is hidden by default'); })();

// ============================================================
// 4. Toolbar
// ============================================================
console.log('\n--- Toolbar ---');

(function() { const html = ScenariosPanelDef.create({}).innerHTML; assert(html.includes('scn-toolbar'), 'Has scn-toolbar class'); })();
(function() { const html = ScenariosPanelDef.create({}).innerHTML; assert(html.includes('REFRESH'), 'REFRESH button label'); })();
(function() { const html = ScenariosPanelDef.create({}).innerHTML; assert(html.includes('RUN ALL'), 'RUN ALL button label'); })();
(function() { const html = ScenariosPanelDef.create({}).innerHTML; assert(html.includes('panel-action-btn-primary'), 'REFRESH is primary'); })();

// ============================================================
// 5. Accessibility
// ============================================================
console.log('\n--- Accessibility ---');

(function() { const html = ScenariosPanelDef.create({}).innerHTML; assert(html.includes('role="listbox"'), 'Scenario list has role=listbox'); })();
(function() { const html = ScenariosPanelDef.create({}).innerHTML; assert(html.includes('aria-label="Behavioral scenarios"'), 'Scenario list has aria-label'); })();

// ============================================================
// 6. Progress bar structure
// ============================================================
console.log('\n--- Progress bar ---');

(function() { const html = ScenariosPanelDef.create({}).innerHTML; assert(html.includes('panel-bar'), 'Has panel-bar class'); })();
(function() { const html = ScenariosPanelDef.create({}).innerHTML; assert(html.includes('panel-bar-fill'), 'Has panel-bar-fill class'); })();
(function() { const html = ScenariosPanelDef.create({}).innerHTML; assert(html.includes('RUNNING'), 'Has RUNNING label'); })();
(function() { const html = ScenariosPanelDef.create({}).innerHTML; assert(html.includes('0%'), 'Progress starts at 0%'); })();

// ============================================================
// 7. mount()
// ============================================================
console.log('\n--- mount() ---');

(function() {
    let fetchCalled = false;
    const origFetch = ctx.fetch;
    ctx.fetch = (url) => { if (typeof url === 'string' && url.includes('/api/scenarios')) fetchCalled = true; return Promise.resolve({ ok: true, json: () => Promise.resolve([]) }); };
    const bodyEl = createMockElement('div');
    const panel = { def: ScenariosPanelDef, _unsubs: [] };
    ScenariosPanelDef.mount(bodyEl, panel);
    assert(fetchCalled, 'mount() fetches /api/scenarios');
    ctx.fetch = origFetch;
})();

(function() {
    const bodyEl = createMockElement('div');
    const panel = { def: ScenariosPanelDef, _unsubs: [] };
    let threw = false;
    try { ScenariosPanelDef.mount(bodyEl, panel); } catch (e) { threw = true; }
    assert(!threw, 'mount() does not crash');
})();

// ============================================================
// 8. unmount()
// ============================================================
console.log('\n--- unmount() ---');

(function() { let threw = false; try { ScenariosPanelDef.unmount(createMockElement('div')); } catch (e) { threw = true; } assert(!threw, 'unmount() does not throw'); })();

// ============================================================
// Summary
// ============================================================
console.log('\n' + '='.repeat(40));
console.log(`Results: ${passed} passed, ${failed} failed`);
console.log('='.repeat(40));
process.exit(failed > 0 ? 1 : 0);
