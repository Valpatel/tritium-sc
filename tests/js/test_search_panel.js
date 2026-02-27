/**
 * TRITIUM-SC Search/Intel Panel tests
 * Tests SearchPanelDef structure, DOM creation, tabs, search input,
 * tab panes, detail area, and mount wiring.
 * Run: node tests/js/test_search_panel.js
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
    fetch: () => Promise.resolve({ ok: true, json: () => Promise.resolve({ items: [], total: 0 }) }),
    performance: { now: () => Date.now() },
};

const ctx = vm.createContext(sandbox);

vm.runInContext(fs.readFileSync(__dirname + '/../../frontend/js/command/events.js', 'utf8').replace(/^export\s+/gm, '').replace(/^import\s+.*$/gm, ''), ctx);
vm.runInContext(fs.readFileSync(__dirname + '/../../frontend/js/command/store.js', 'utf8').replace(/^export\s+/gm, '').replace(/^import\s+.*$/gm, ''), ctx);

const searchCode = fs.readFileSync(__dirname + '/../../frontend/js/command/panels/search.js', 'utf8');
vm.runInContext(searchCode.replace(/^export\s+const\s+/gm, 'var ').replace(/^export\s+/gm, '').replace(/^import\s+.*$/gm, ''), ctx);

const SearchPanelDef = ctx.SearchPanelDef;

// ============================================================
// 1. Structure
// ============================================================
console.log('\n--- SearchPanelDef structure ---');

(function() { assert(SearchPanelDef.id === 'search', 'id is "search"'); })();
(function() { assert(SearchPanelDef.title === 'INTEL', 'title is "INTEL"'); })();
(function() { assert(typeof SearchPanelDef.create === 'function', 'create is a function'); })();
(function() { assert(typeof SearchPanelDef.mount === 'function', 'mount is a function'); })();
(function() { assert(typeof SearchPanelDef.unmount === 'function', 'unmount is a function'); })();
(function() { assert(SearchPanelDef.defaultSize.w === 360, 'defaultSize.w is 360'); })();
(function() { assert(SearchPanelDef.defaultSize.h === 480, 'defaultSize.h is 480'); })();

// ============================================================
// 2. create() DOM
// ============================================================
console.log('\n--- create() DOM ---');

(function() { assert(SearchPanelDef.create({}).className === 'search-panel-inner', 'className correct'); })();

// ============================================================
// 3. Tabs
// ============================================================
console.log('\n--- Tabs ---');

(function() { const html = SearchPanelDef.create({}).innerHTML; assert(html.includes('data-tab="people"'), 'Has PEOPLE tab'); })();
(function() { const html = SearchPanelDef.create({}).innerHTML; assert(html.includes('data-tab="vehicles"'), 'Has VEHICLES tab'); })();
(function() { const html = SearchPanelDef.create({}).innerHTML; assert(html.includes('data-tab="flagged"'), 'Has FLAGGED tab'); })();
(function() { const html = SearchPanelDef.create({}).innerHTML; assert(html.includes('data-tab="trends"'), 'Has TRENDS tab'); })();
(function() { const html = SearchPanelDef.create({}).innerHTML; assert(html.includes('>PEOPLE<'), 'PEOPLE tab label'); })();
(function() { const html = SearchPanelDef.create({}).innerHTML; assert(html.includes('>VEHICLES<'), 'VEHICLES tab label'); })();
(function() { const html = SearchPanelDef.create({}).innerHTML; assert(html.includes('>FLAGGED<'), 'FLAGGED tab label'); })();
(function() { const html = SearchPanelDef.create({}).innerHTML; assert(html.includes('>TRENDS<'), 'TRENDS tab label'); })();

// ============================================================
// 4. Tab panes
// ============================================================
console.log('\n--- Tab panes ---');

(function() { const html = SearchPanelDef.create({}).innerHTML; assert(html.includes('data-pane="people"'), 'Has people pane'); })();
(function() { const html = SearchPanelDef.create({}).innerHTML; assert(html.includes('data-pane="vehicles"'), 'Has vehicles pane'); })();
(function() { const html = SearchPanelDef.create({}).innerHTML; assert(html.includes('data-pane="flagged"'), 'Has flagged pane'); })();
(function() { const html = SearchPanelDef.create({}).innerHTML; assert(html.includes('data-pane="trends"'), 'Has trends pane'); })();

// ============================================================
// 5. Search input
// ============================================================
console.log('\n--- Search input ---');

(function() { const html = SearchPanelDef.create({}).innerHTML; assert(html.includes('data-bind="search-input"'), 'Has search input'); })();
(function() { const html = SearchPanelDef.create({}).innerHTML; assert(html.includes('data-action="text-search"'), 'Has search button'); })();
(function() { const html = SearchPanelDef.create({}).innerHTML; assert(html.includes('Search by description'), 'Has search placeholder'); })();

// ============================================================
// 6. Data bindings in panes
// ============================================================
console.log('\n--- Data bindings ---');

(function() { const html = SearchPanelDef.create({}).innerHTML; assert(html.includes('data-bind="people-list"'), 'Has people list'); })();
(function() { const html = SearchPanelDef.create({}).innerHTML; assert(html.includes('data-bind="vehicle-list"'), 'Has vehicle list'); })();
(function() { const html = SearchPanelDef.create({}).innerHTML; assert(html.includes('data-bind="flagged-list"'), 'Has flagged list'); })();
(function() { const html = SearchPanelDef.create({}).innerHTML; assert(html.includes('data-bind="trends-content"'), 'Has trends content'); })();
(function() { const html = SearchPanelDef.create({}).innerHTML; assert(html.includes('data-bind="people-stats"'), 'Has people stats'); })();
(function() { const html = SearchPanelDef.create({}).innerHTML; assert(html.includes('data-bind="vehicle-stats"'), 'Has vehicle stats'); })();
(function() { const html = SearchPanelDef.create({}).innerHTML; assert(html.includes('data-bind="detail"'), 'Has detail area'); })();

// ============================================================
// 7. Accessibility
// ============================================================
console.log('\n--- Accessibility ---');

(function() { const html = SearchPanelDef.create({}).innerHTML; assert(html.includes('role="tablist"'), 'Tab bar has role=tablist'); })();
(function() { const html = SearchPanelDef.create({}).innerHTML; assert(html.includes('role="tab"'), 'Tabs have role=tab'); })();
(function() { const html = SearchPanelDef.create({}).innerHTML; assert(html.includes('role="listbox"'), 'Lists have role=listbox'); })();
(function() { const html = SearchPanelDef.create({}).innerHTML; assert(html.includes('aria-label="Detected people"'), 'People list has aria-label'); })();
(function() { const html = SearchPanelDef.create({}).innerHTML; assert(html.includes('aria-label="Detected vehicles"'), 'Vehicle list has aria-label'); })();
(function() { const html = SearchPanelDef.create({}).innerHTML; assert(html.includes('aria-label="Text search"'), 'Search input has aria-label'); })();

// ============================================================
// 8. Detail hidden by default
// ============================================================
console.log('\n--- Detail state ---');

(function() { const html = SearchPanelDef.create({}).innerHTML; assert(html.match(/data-bind="detail"[^>]*style="display:none"/), 'Detail area is hidden by default'); })();

// ============================================================
// 9. mount()
// ============================================================
console.log('\n--- mount() ---');

(function() {
    const bodyEl = createMockElement('div');
    const panel = { def: SearchPanelDef, _unsubs: [] };
    let threw = false;
    try { SearchPanelDef.mount(bodyEl, panel); } catch (e) { threw = true; }
    assert(!threw, 'mount() does not crash');
})();

(function() {
    const bodyEl = createMockElement('div');
    const panel = { def: SearchPanelDef, _unsubs: [] };
    SearchPanelDef.mount(bodyEl, panel);
    assert(panel._unsubs.length >= 1, 'mount() registers at least 1 cleanup fn (refresh interval), got ' + panel._unsubs.length);
})();

// ============================================================
// 10. unmount()
// ============================================================
console.log('\n--- unmount() ---');

(function() { let threw = false; try { SearchPanelDef.unmount(createMockElement('div')); } catch (e) { threw = true; } assert(!threw, 'unmount() does not throw'); })();

// ============================================================
// Summary
// ============================================================
console.log('\n' + '='.repeat(40));
console.log(`Results: ${passed} passed, ${failed} failed`);
console.log('='.repeat(40));
process.exit(failed > 0 ? 1 : 0);
