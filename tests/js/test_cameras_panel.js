/**
 * TRITIUM-SC Camera Feeds Panel tests
 * Tests CamerasPanelDef structure, DOM creation, feed list, preview area,
 * scene select, action buttons, and mount wiring.
 * Run: node tests/js/test_cameras_panel.js
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
        tagName: (tag || 'DIV').toUpperCase(),
        className: '',
        get innerHTML() { return _innerHTML; },
        set innerHTML(val) { _innerHTML = val; },
        get textContent() { return _textContent; },
        set textContent(val) { _textContent = String(val); _innerHTML = String(val).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); },
        style, dataset, children, childNodes: children, parentNode: null, hidden: false, value: 'bird_eye', disabled: false, src: '',
        get classList() {
            return {
                add(cls) { classList.add(cls); }, remove(cls) { classList.delete(cls); },
                contains(cls) { return classList.has(cls); },
                toggle(cls, force) { if (force === undefined) { if (classList.has(cls)) classList.delete(cls); else classList.add(cls); } else if (force) classList.add(cls); else classList.delete(cls); },
            };
        },
        appendChild(child) { children.push(child); if (child && typeof child === 'object') child.parentNode = el; return child; },
        remove() {}, focus() {},
        addEventListener(evt, fn) { if (!eventListeners[evt]) eventListeners[evt] = []; eventListeners[evt].push(fn); },
        removeEventListener(evt, fn) { if (eventListeners[evt]) eventListeners[evt] = eventListeners[evt].filter(f => f !== fn); },
        querySelector(sel) {
            const bindMatch = sel.match(/\[data-bind="([^"]+)"\]/);
            if (bindMatch) { const mock = createMockElement('div'); mock._bindName = bindMatch[1]; if (bindMatch[1] === 'scene-select') mock.value = 'bird_eye'; if (bindMatch[1] === 'preview-img') mock.src = ''; return mock; }
            const actionMatch = sel.match(/\[data-action="([^"]+)"\]/);
            if (actionMatch) { const mock = createMockElement('button'); mock._actionName = actionMatch[1]; return mock; }
            return null;
        },
        querySelectorAll(sel) { return []; },
        closest(sel) { return null; },
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

const camCode = fs.readFileSync(__dirname + '/../../frontend/js/command/panels/cameras.js', 'utf8');
vm.runInContext(camCode.replace(/^export\s+const\s+/gm, 'var ').replace(/^export\s+/gm, '').replace(/^import\s+.*$/gm, ''), ctx);

const CamerasPanelDef = ctx.CamerasPanelDef;

// ============================================================
// 1. Structure
// ============================================================
console.log('\n--- CamerasPanelDef structure ---');

(function() { assert(CamerasPanelDef.id === 'cameras', 'id is "cameras"'); })();
(function() { assert(CamerasPanelDef.title === 'CAMERA FEEDS', 'title is "CAMERA FEEDS"'); })();
(function() { assert(typeof CamerasPanelDef.create === 'function', 'create is a function'); })();
(function() { assert(typeof CamerasPanelDef.mount === 'function', 'mount is a function'); })();
(function() { assert(typeof CamerasPanelDef.unmount === 'function', 'unmount is a function'); })();
(function() { assert(CamerasPanelDef.defaultPosition.x === null, 'defaultPosition.x is null'); })();
(function() { assert(CamerasPanelDef.defaultPosition.y === 8, 'defaultPosition.y is 8'); })();
(function() { assert(CamerasPanelDef.defaultSize.w === 320, 'defaultSize.w is 320'); })();
(function() { assert(CamerasPanelDef.defaultSize.h === 360, 'defaultSize.h is 360'); })();

// ============================================================
// 2. create() DOM structure
// ============================================================
console.log('\n--- create() DOM structure ---');

(function() { const el = CamerasPanelDef.create({}); assert(el.className === 'cameras-panel-inner', 'className is cameras-panel-inner'); })();
(function() { const html = CamerasPanelDef.create({}).innerHTML; assert(html.includes('data-action="refresh"'), 'Has REFRESH button'); })();
(function() { const html = CamerasPanelDef.create({}).innerHTML; assert(html.includes('data-bind="scene-select"'), 'Has scene select'); })();
(function() { const html = CamerasPanelDef.create({}).innerHTML; assert(html.includes('data-action="create-feed"'), 'Has NEW button'); })();
(function() { const html = CamerasPanelDef.create({}).innerHTML; assert(html.includes('data-bind="feed-list"'), 'Has feed list'); })();
(function() { const html = CamerasPanelDef.create({}).innerHTML; assert(html.includes('data-bind="preview"'), 'Has preview area'); })();
(function() { const html = CamerasPanelDef.create({}).innerHTML; assert(html.includes('data-bind="preview-img"'), 'Has preview image'); })();
(function() { const html = CamerasPanelDef.create({}).innerHTML; assert(html.includes('data-bind="preview-name"'), 'Has preview name'); })();
(function() { const html = CamerasPanelDef.create({}).innerHTML; assert(html.includes('data-action="close-preview"'), 'Has close preview button'); })();
(function() { const html = CamerasPanelDef.create({}).innerHTML; assert(html.includes('Loading feeds...'), 'Has loading state'); })();

// ============================================================
// 3. Scene select options
// ============================================================
console.log('\n--- Scene select ---');

(function() { const html = CamerasPanelDef.create({}).innerHTML; assert(html.includes('value="bird_eye"'), 'Has bird eye option'); })();
(function() { const html = CamerasPanelDef.create({}).innerHTML; assert(html.includes('value="street_cam"'), 'Has street cam option'); })();
(function() { const html = CamerasPanelDef.create({}).innerHTML; assert(html.includes('value="battle"'), 'Has battle option'); })();
(function() { const html = CamerasPanelDef.create({}).innerHTML; assert(html.includes('value="neighborhood"'), 'Has neighborhood option'); })();

// ============================================================
// 4. Accessibility
// ============================================================
console.log('\n--- Accessibility ---');

(function() { const html = CamerasPanelDef.create({}).innerHTML; assert(html.includes('role="listbox"'), 'Feed list has role=listbox'); })();
(function() { const html = CamerasPanelDef.create({}).innerHTML; assert(html.includes('aria-label="Camera feeds"'), 'Feed list has aria-label'); })();
(function() { const html = CamerasPanelDef.create({}).innerHTML; assert(html.includes('alt="Camera feed"'), 'Preview image has alt text'); })();

// ============================================================
// 5. Preview hidden by default
// ============================================================
console.log('\n--- Preview state ---');

(function() { const html = CamerasPanelDef.create({}).innerHTML; assert(html.includes('display:none'), 'Preview is hidden by default'); })();

// ============================================================
// 6. mount()
// ============================================================
console.log('\n--- mount() ---');

(function() {
    const bodyEl = createMockElement('div');
    const panel = { def: CamerasPanelDef, w: 320, x: 0, y: 0, manager: { container: createMockElement('div') }, _unsubs: [], _applyTransform() {} };
    panel.manager.container.clientWidth = 1200;
    CamerasPanelDef.mount(bodyEl, panel);
    assert(panel._unsubs.length >= 2, 'mount() registers at least 2 cleanup fns (interval + img), got ' + panel._unsubs.length);
})();

(function() {
    let fetchCalled = false;
    const origFetch = ctx.fetch;
    ctx.fetch = (url) => { if (typeof url === 'string' && url.includes('/api/synthetic/cameras')) fetchCalled = true; return Promise.resolve({ ok: true, json: () => Promise.resolve([]) }); };
    const bodyEl = createMockElement('div');
    const panel = { def: CamerasPanelDef, w: 320, x: 0, y: 0, manager: { container: createMockElement('div') }, _unsubs: [], _applyTransform() {} };
    panel.manager.container.clientWidth = 1200;
    CamerasPanelDef.mount(bodyEl, panel);
    assert(fetchCalled, 'mount() fetches /api/synthetic/cameras');
    ctx.fetch = origFetch;
})();

(function() {
    const bodyEl = createMockElement('div');
    const panel = { def: CamerasPanelDef, w: 320, x: 0, y: 0, manager: { container: createMockElement('div') }, _unsubs: [], _applyTransform() {} };
    panel.manager.container.clientWidth = 1200;
    let threw = false;
    try { CamerasPanelDef.mount(bodyEl, panel); } catch (e) { threw = true; }
    assert(!threw, 'mount() does not crash');
})();

(function() {
    const bodyEl = createMockElement('div');
    const panel = { def: CamerasPanelDef, w: 320, x: 0, y: 0, manager: { container: createMockElement('div') }, _unsubs: [], _applyTransform() {} };
    panel.manager.container.clientWidth = 1200;
    CamerasPanelDef.mount(bodyEl, panel);
    // x = 1200 - 320 - 8 = 872
    assert(panel.x === 872, 'mount() positions at right side (expected 872, got ' + panel.x + ')');
})();

// ============================================================
// 7. unmount()
// ============================================================
console.log('\n--- unmount() ---');

(function() { let threw = false; try { CamerasPanelDef.unmount(createMockElement('div')); } catch (e) { threw = true; } assert(!threw, 'unmount() does not throw'); })();

// ============================================================
// 8. Toolbar structure
// ============================================================
console.log('\n--- Toolbar ---');

(function() { const html = CamerasPanelDef.create({}).innerHTML; assert(html.includes('cam-toolbar'), 'Has cam-toolbar class'); })();
(function() { const html = CamerasPanelDef.create({}).innerHTML; assert(html.includes('panel-action-btn-primary'), 'REFRESH button is primary'); })();
(function() { const html = CamerasPanelDef.create({}).innerHTML; assert(html.includes('+ NEW'), 'NEW button has correct label'); })();

// ============================================================
// Summary
// ============================================================
console.log('\n' + '='.repeat(40));
console.log(`Results: ${passed} passed, ${failed} failed`);
console.log('='.repeat(40));
process.exit(failed > 0 ? 1 : 0);
