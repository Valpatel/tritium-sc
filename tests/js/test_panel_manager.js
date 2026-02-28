// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
/**
 * TRITIUM-SC Panel Manager tests
 * Tests Panel class, PanelManager lifecycle, bounds clamping, serialization,
 * resize handler, presets, and z-index management.
 * Run: node tests/js/test_panel_manager.js
 */

const fs = require('fs');
const vm = require('vm');

// Simple test runner
let passed = 0, failed = 0;
function assert(cond, msg) {
    if (!cond) { console.error('FAIL:', msg); failed++; }
    else { console.log('PASS:', msg); passed++; }
}
function assertClose(a, b, eps, msg) {
    assert(Math.abs(a - b) < (eps || 0.001), msg + ` (got ${a}, expected ${b})`);
}

// ============================================================
// DOM + browser mocks
// ============================================================

// Track event listeners on window for resize handler tests
const _windowListeners = {};

function createMockElement(tag, attrs) {
    const children = [];
    const classList = new Set();
    const eventListeners = {};
    const dataset = {};
    const style = {};

    const el = {
        tagName: tag || 'DIV',
        className: '',
        innerHTML: '',
        textContent: '',
        style,
        dataset,
        children,
        childNodes: children,
        parentNode: null,
        clientWidth: 0,
        clientHeight: 0,
        get classList() {
            return {
                add(cls) { classList.add(cls); },
                remove(cls) { classList.delete(cls); },
                contains(cls) { return classList.has(cls); },
                toggle(cls) {
                    if (classList.has(cls)) classList.delete(cls);
                    else classList.add(cls);
                },
            };
        },
        appendChild(child) {
            children.push(child);
            if (child && typeof child === 'object') child.parentNode = el;
            return child;
        },
        remove() {
            if (el.parentNode) {
                const idx = el.parentNode.children.indexOf(el);
                if (idx >= 0) el.parentNode.children.splice(idx, 1);
            }
        },
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
            // Simplified querySelector for panel internals
            if (sel === '.panel-body') return el._panelBody || null;
            if (sel === '.panel-minimize') return el._panelMinimize || null;
            if (sel === '.panel-close') return el._panelClose || null;
            if (sel === '[data-drag-handle]') return el._dragHandle || null;
            if (sel === '[data-resize-handle]') return el._resizeHandle || null;
            return null;
        },
        querySelectorAll() { return []; },
        closest() { return null; },
        _eventListeners: eventListeners,
    };
    return el;
}

// Build a mock document.createElement that produces panel-compatible elements
function mockCreateElement(tag) {
    const el = createMockElement(tag);

    // When innerHTML is set on a panel element, create child query targets
    const origInnerHTMLDesc = Object.getOwnPropertyDescriptor(el, 'innerHTML') || {};
    let _innerHTML = '';
    Object.defineProperty(el, 'innerHTML', {
        get() { return _innerHTML; },
        set(val) {
            _innerHTML = val;
            // Create mock sub-elements for panel structure
            if (val.includes('panel-header')) {
                el._dragHandle = createMockElement('div');
                el._panelBody = createMockElement('div');
                el._resizeHandle = createMockElement('div');
                el._panelMinimize = createMockElement('button');
                el._panelClose = createMockElement('button');
            }
        },
    });

    return el;
}

// localStorage mock
const _storage = {};
const mockLocalStorage = {
    getItem(key) { return _storage[key] || null; },
    setItem(key, val) { _storage[key] = val; },
    removeItem(key) { delete _storage[key]; },
    clear() { Object.keys(_storage).forEach(k => delete _storage[k]); },
};

// requestAnimationFrame mock (executes synchronously for testing)
const _rafCallbacks = [];
function mockRAF(cb) {
    _rafCallbacks.push(cb);
    return _rafCallbacks.length;
}
function flushRAF() {
    while (_rafCallbacks.length > 0) {
        const cb = _rafCallbacks.shift();
        cb(performance.now());
    }
}

// Create the sandbox context
const sandbox = {
    Math, Date, console, Map, Set, Array, Object, Number, String, Boolean,
    Infinity, NaN, undefined, parseInt, parseFloat, isNaN, isFinite, JSON,
    Promise, setTimeout, clearTimeout, setInterval, clearInterval,
    HTMLElement: function HTMLElement() {},
    document: {
        createElement: mockCreateElement,
        addEventListener() {},
        removeEventListener() {},
    },
    localStorage: null, // set below after sandbox creation
    requestAnimationFrame: mockRAF,
    window: null,  // set below
    performance: { now: () => Date.now() },
};

// window.addEventListener/removeEventListener for resize tracking
sandbox.window = {
    addEventListener(evt, fn) {
        if (!_windowListeners[evt]) _windowListeners[evt] = [];
        _windowListeners[evt].push(fn);
    },
    removeEventListener(evt, fn) {
        if (_windowListeners[evt]) {
            _windowListeners[evt] = _windowListeners[evt].filter(f => f !== fn);
        }
    },
};

// Set localStorage on sandbox BEFORE createContext so the VM sees it
sandbox.localStorage = mockLocalStorage;

const ctx = vm.createContext(sandbox);

// Load EventBus first (panel-manager.js imports it)
const eventsCode = fs.readFileSync(__dirname + '/../../frontend/js/command/events.js', 'utf8');
// Strip ES module import/export syntax for Node.js vm
const eventsPlain = eventsCode
    .replace(/^export\s+/gm, '')
    .replace(/^import\s+.*$/gm, '');
vm.runInContext(eventsPlain, ctx);

// Load panel-manager.js, stripping ES module syntax and exposing classes on globalThis
const panelCode = fs.readFileSync(__dirname + '/../../frontend/js/command/panel-manager.js', 'utf8');
const panelPlain = panelCode
    .replace(/^import\s+.*$/gm, '')
    .replace(/^export\s+class/gm, 'class')
    .replace(/^export\s+/gm, '');
// Append assignments to make classes accessible on the sandbox
const panelWithExports = panelPlain + '\nPanel; PanelManager;';
// We need a different approach: run in context, then extract via eval
vm.runInContext(panelPlain + '\nvar _Panel = Panel; var _PanelManager = PanelManager;', ctx);

const Panel = ctx._Panel;
const PanelManager = ctx._PanelManager;

// ============================================================
// Helper: create a container with given dimensions
// ============================================================

function makeContainer(w, h) {
    const el = createMockElement('div');
    el.clientWidth = w !== undefined ? w : 1200;
    el.clientHeight = h !== undefined ? h : 700;
    return el;
}

function makeDef(overrides) {
    return Object.assign({
        id: 'test-panel',
        title: 'Test Panel',
        defaultPosition: { x: 50, y: 50 },
        defaultSize: { w: 300, h: 250 },
    }, overrides || {});
}

function makePM(containerW, containerH) {
    const container = makeContainer(containerW, containerH);
    const pm = new PanelManager(container);
    return pm;
}

// ============================================================
// 1. Panel constructor creates DOM elements
// ============================================================

console.log('\n--- Panel Constructor ---');

(function testPanelConstructorCreatesEl() {
    const pm = makePM(1200, 700);
    const def = makeDef();
    pm.register(def);
    const panel = pm.open('test-panel');
    assert(panel !== null, 'Panel created by open()');
    assert(panel.el !== null && panel.el !== undefined, 'Panel has .el DOM element');
    assert(panel.id === 'test-panel', 'Panel id matches definition');
    assert(panel.title === 'Test Panel', 'Panel title matches definition');
    pm.destroyAll();
})();

(function testPanelConstructorDefaultPosition() {
    const pm = makePM(1200, 700);
    pm.register(makeDef());
    const panel = pm.open('test-panel');
    assertClose(panel.x, 50, 0.1, 'Panel x from defaultPosition');
    assertClose(panel.y, 50, 0.1, 'Panel y from defaultPosition');
    pm.destroyAll();
})();

(function testPanelConstructorDefaultSize() {
    const pm = makePM(1200, 700);
    pm.register(makeDef());
    const panel = pm.open('test-panel');
    assertClose(panel.w, 300, 0.1, 'Panel w from defaultSize');
    assertClose(panel.h, 250, 0.1, 'Panel h from defaultSize');
    pm.destroyAll();
})();

(function testPanelConstructorFallbackDefaults() {
    const pm = makePM(1200, 700);
    pm.register({ id: 'bare', title: 'Bare' });
    const panel = pm.open('bare');
    assertClose(panel.x, 16, 0.1, 'Panel x defaults to 16 when no defaultPosition');
    assertClose(panel.y, 16, 0.1, 'Panel y defaults to 16 when no defaultPosition');
    assertClose(panel.w, 300, 0.1, 'Panel w defaults to 300 when no defaultSize');
    assertClose(panel.h, 250, 0.1, 'Panel h defaults to 250 when no defaultSize');
    pm.destroyAll();
})();

// ============================================================
// 2. setPosition / setSize clamp to minimum sizes
// ============================================================

console.log('\n--- setPosition / setSize ---');

(function testSetPositionUpdatesXY() {
    const pm = makePM(1200, 700);
    pm.register(makeDef());
    const panel = pm.open('test-panel');
    panel.setPosition(100, 200);
    assertClose(panel.x, 100, 0.1, 'setPosition updates x');
    assertClose(panel.y, 200, 0.1, 'setPosition updates y');
    pm.destroyAll();
})();

(function testSetSizeClampsToMinW() {
    const pm = makePM(1200, 700);
    pm.register(makeDef());
    const panel = pm.open('test-panel');
    panel.setSize(50, 300);
    assert(panel.w >= 200, 'setSize clamps w to MIN_PANEL_W (200), got ' + panel.w);
    pm.destroyAll();
})();

(function testSetSizeClampsToMinH() {
    const pm = makePM(1200, 700);
    pm.register(makeDef());
    const panel = pm.open('test-panel');
    panel.setSize(400, 30);
    assert(panel.h >= 120, 'setSize clamps h to MIN_PANEL_H (120), got ' + panel.h);
    pm.destroyAll();
})();

(function testSetSizeAllowsLargeValues() {
    const pm = makePM(1200, 700);
    pm.register(makeDef());
    const panel = pm.open('test-panel');
    panel.setSize(800, 600);
    assertClose(panel.w, 800, 0.1, 'setSize accepts w=800');
    assertClose(panel.h, 600, 0.1, 'setSize accepts h=600');
    pm.destroyAll();
})();

// ============================================================
// 3. serialize / deserialize round-trip
// ============================================================

console.log('\n--- Serialize / Deserialize ---');

(function testSerializeRoundTrip() {
    const pm = makePM(1200, 700);
    pm.register(makeDef());
    const panel = pm.open('test-panel');
    panel.setPosition(100, 200);
    panel.setSize(400, 350);

    const data = panel.serialize();
    assert(data.id === 'test-panel', 'serialize includes id');
    assertClose(data.x, 100, 0.1, 'serialize includes x');
    assertClose(data.y, 200, 0.1, 'serialize includes y');
    assertClose(data.w, 400, 0.1, 'serialize includes w');
    assertClose(data.h, 350, 0.1, 'serialize includes h');
    assert(data.minimized === false, 'serialize includes minimized=false');
    assert(data.visible === true, 'serialize includes visible=true');
    pm.destroyAll();
})();

(function testDeserializeRestoresState() {
    const pm = makePM(1200, 700);
    pm.register(makeDef());
    const panel = pm.open('test-panel');

    panel.deserialize({ x: 150, y: 250, w: 500, h: 400 });
    assertClose(panel.x, 150, 0.1, 'deserialize restores x');
    assertClose(panel.y, 250, 0.1, 'deserialize restores y');
    assertClose(panel.w, 500, 0.1, 'deserialize restores w');
    assertClose(panel.h, 400, 0.1, 'deserialize restores h');
    pm.destroyAll();
})();

(function testDeserializeClampsMinSize() {
    const pm = makePM(1200, 700);
    pm.register(makeDef());
    const panel = pm.open('test-panel');

    panel.deserialize({ w: 10, h: 5 });
    assert(panel.w >= 200, 'deserialize clamps w to MIN_PANEL_W, got ' + panel.w);
    assert(panel.h >= 120, 'deserialize clamps h to MIN_PANEL_H, got ' + panel.h);
    pm.destroyAll();
})();

(function testDeserializeWithMinimized() {
    const pm = makePM(1200, 700);
    pm.register(makeDef());
    const panel = pm.open('test-panel');

    panel.deserialize({ x: 100, y: 100, w: 300, h: 250, minimized: true });
    assert(panel.minimized === true, 'deserialize restores minimized state');
    pm.destroyAll();
})();

// ============================================================
// 4. _clampToBounds clamps position within container
// ============================================================

console.log('\n--- _clampToBounds ---');

(function testClampNegativeXKeepsHeaderGrabbable() {
    const pm = makePM(1200, 700);
    pm.register(makeDef());
    const panel = pm.open('test-panel');
    flushRAF();
    panel.x = -50;
    panel._clampToBounds();
    // Free movement: panel can go negative, but at least 40px must be visible
    assert(panel.x + panel.w >= 40, '_clampToBounds keeps 40px header visible when x<0 (x=' + panel.x + ', w=' + panel.w + ')');
    pm.destroyAll();
})();

(function testClampNegativeYKeepsHeaderVisible() {
    const pm = makePM(1200, 700);
    pm.register(makeDef());
    const panel = pm.open('test-panel');
    flushRAF();
    panel.y = -30;
    panel._clampToBounds();
    // Free movement: y can go as low as -HEADER_HEIGHT (28px)
    assert(panel.y >= -28, '_clampToBounds keeps header reachable when y<0 (y=' + panel.y + ')');
    pm.destroyAll();
})();

(function testClampPanelOverflowRightKeepsGrabbable() {
    const pm = makePM(800, 600);
    pm.register(makeDef({ defaultSize: { w: 300, h: 250 } }));
    const panel = pm.open('test-panel');
    flushRAF();
    panel.x = 700;  // 700 + 300 = 1000 > 800
    panel._clampToBounds();
    // Free movement: x can go past container edge, but at least 40px of header visible
    assert(panel.x <= 800 - 40, '_clampToBounds keeps 40px on-screen at right (x=' + panel.x + ')');
    pm.destroyAll();
})();

(function testClampPanelOverflowBottom() {
    const pm = makePM(800, 600);
    pm.register(makeDef());
    const panel = pm.open('test-panel');
    flushRAF();
    panel.y = 590;  // 590 + 28 (HEADER_HEIGHT) > 600
    panel._clampToBounds();
    // At least header (28px) must be visible
    assert(panel.y + 28 <= 600, '_clampToBounds ensures header visible at bottom (y=' + panel.y + ')');
    pm.destroyAll();
})();

(function testClampDoesNothingWhenInBounds() {
    const pm = makePM(1200, 700);
    pm.register(makeDef());
    const panel = pm.open('test-panel');
    flushRAF();
    panel.setPosition(100, 100);
    panel.setSize(300, 250);
    const origX = panel.x, origY = panel.y, origW = panel.w, origH = panel.h;
    panel._clampToBounds();
    assertClose(panel.x, origX, 0.1, '_clampToBounds leaves x unchanged when in bounds');
    assertClose(panel.y, origY, 0.1, '_clampToBounds leaves y unchanged when in bounds');
    assertClose(panel.w, origW, 0.1, '_clampToBounds leaves w unchanged when in bounds');
    assertClose(panel.h, origH, 0.1, '_clampToBounds leaves h unchanged when in bounds');
    pm.destroyAll();
})();

(function testClampWithZeroContainer() {
    flushRAF(); // drain any stale RAF from earlier tests
    const pm = makePM(0, 0);
    pm.register(makeDef());
    const panel = pm.open('test-panel');
    flushRAF(); // drain RAF from open() -- early returns since cw=0
    panel.x = -50;
    panel.y = -30;
    panel._clampToBounds();
    // Should not crash, and should skip clamping when container has no dimensions
    assertClose(panel.x, -50, 0.1, '_clampToBounds skips x when container width is 0');
    assertClose(panel.y, -30, 0.1, '_clampToBounds skips y when container height is 0');
    pm.destroyAll();
})();

// ============================================================
// 5. _clampToBounds handles panel larger than container
// ============================================================

console.log('\n--- _clampToBounds large panel ---');

(function testClampWidthExceedsContainer() {
    const pm = makePM(400, 300);
    pm.register(makeDef({ defaultSize: { w: 600, h: 200 } }));
    const panel = pm.open('test-panel');
    flushRAF();
    panel._clampToBounds();
    assert(panel.w <= 400, '_clampToBounds clamps w to container width (got ' + panel.w + ')');
    assert(panel.x >= 0, '_clampToBounds keeps x non-negative after width clamp');
    pm.destroyAll();
})();

(function testClampHeightExceedsContainer() {
    const pm = makePM(400, 200);
    pm.register(makeDef({ defaultSize: { w: 300, h: 500 } }));
    const panel = pm.open('test-panel');
    flushRAF();
    panel._clampToBounds();
    assert(panel.h <= 200, '_clampToBounds clamps h to container height (got ' + panel.h + ')');
    pm.destroyAll();
})();

(function testClampBothDimensionsExceedContainer() {
    const pm = makePM(250, 150);
    pm.register(makeDef({ defaultSize: { w: 500, h: 400 } }));
    const panel = pm.open('test-panel');
    flushRAF();
    panel._clampToBounds();
    assert(panel.w <= 250, '_clampToBounds clamps oversized w (got ' + panel.w + ')');
    assert(panel.h <= 150, '_clampToBounds clamps oversized h (got ' + panel.h + ')');
    // With free movement, panel at default x=50 stays put since 250-50=200 > MIN_GRAB (40)
    assert(panel.x <= 250 - 40, '_clampToBounds keeps header grabbable for full-width panel (x=' + panel.x + ')');
    pm.destroyAll();
})();

// ============================================================
// 6. PanelManager register / open / close lifecycle
// ============================================================

console.log('\n--- PanelManager lifecycle ---');

(function testRegisterStoresDefinition() {
    const pm = makePM();
    pm.register(makeDef({ id: 'amy', title: 'AMY' }));
    const ids = pm.registeredIds();
    assert(ids.includes('amy'), 'registeredIds includes registered panel');
    pm.destroyAll();
})();

(function testRegisterRejectsNoId() {
    const pm = makePM();
    pm.register({ title: 'Missing ID' });
    assert(pm.registeredIds().length === 0, 'register rejects definition without id');
    pm.destroyAll();
})();

(function testRegisterRejectsNoTitle() {
    const pm = makePM();
    pm.register({ id: 'foo' });
    assert(pm.registeredIds().length === 0, 'register rejects definition without title');
    pm.destroyAll();
})();

(function testOpenCreatesPanel() {
    const pm = makePM();
    pm.register(makeDef({ id: 'p1', title: 'P1' }));
    const panel = pm.open('p1');
    assert(panel !== null, 'open returns panel');
    assert(pm.isOpen('p1'), 'isOpen returns true after open');
    pm.destroyAll();
})();

(function testOpenUnregisteredReturnsNull() {
    const pm = makePM();
    const panel = pm.open('nonexistent');
    assert(panel === null, 'open returns null for unregistered panel');
    pm.destroyAll();
})();

(function testOpenAlreadyOpenBringsToFront() {
    const pm = makePM();
    pm.register(makeDef({ id: 'p1', title: 'P1' }));
    const panel1 = pm.open('p1');
    const z1 = panel1.el.style.zIndex;
    const panel2 = pm.open('p1');
    assert(panel1 === panel2, 'open returns same panel instance');
    // zIndex should have incremented
    assert(Number(panel2.el.style.zIndex) > Number(z1), 'open brings existing panel to front');
    pm.destroyAll();
})();

(function testCloseDestroysPanel() {
    const pm = makePM();
    pm.register(makeDef({ id: 'p1', title: 'P1' }));
    pm.open('p1');
    pm.close('p1');
    assert(!pm.isOpen('p1'), 'isOpen returns false after close');
    assert(pm.getPanel('p1') !== undefined, 'getPanel returns hidden panel after close (hide, not destroy)');
    pm.destroyAll();
})();

(function testCloseNonexistentDoesNotCrash() {
    const pm = makePM();
    pm.close('nonexistent');
    assert(true, 'close on nonexistent panel does not crash');
    pm.destroyAll();
})();

// ============================================================
// 7. PanelManager.toggle opens and closes
// ============================================================

console.log('\n--- PanelManager toggle ---');

(function testToggleOpensPanel() {
    const pm = makePM();
    pm.register(makeDef({ id: 'tog', title: 'Toggle' }));
    pm.toggle('tog');
    assert(pm.isOpen('tog'), 'toggle opens closed panel');
    pm.destroyAll();
})();

(function testToggleClosesPanel() {
    const pm = makePM();
    pm.register(makeDef({ id: 'tog', title: 'Toggle' }));
    pm.toggle('tog');
    assert(pm.isOpen('tog'), 'panel is open after first toggle');
    pm.toggle('tog');
    assert(!pm.isOpen('tog'), 'panel is closed after second toggle');
    pm.destroyAll();
})();

// ============================================================
// 8. Z-index increments on bringToFront
// ============================================================

console.log('\n--- Z-index ---');

(function testZIndexIncrements() {
    const pm = makePM();
    pm.register(makeDef({ id: 'a', title: 'A' }));
    pm.register(makeDef({ id: 'b', title: 'B' }));
    const panelA = pm.open('a');
    const panelB = pm.open('b');
    const zA = Number(panelA.el.style.zIndex);
    const zB = Number(panelB.el.style.zIndex);
    assert(zB > zA, 'Second panel has higher z-index than first (zA=' + zA + ', zB=' + zB + ')');
    pm.destroyAll();
})();

(function testBringToFrontIncrementsZ() {
    const pm = makePM();
    pm.register(makeDef({ id: 'a', title: 'A' }));
    pm.register(makeDef({ id: 'b', title: 'B' }));
    const panelA = pm.open('a');
    const panelB = pm.open('b');
    const zBBefore = Number(panelB.el.style.zIndex);
    panelA.bringToFront();
    const zAAfter = Number(panelA.el.style.zIndex);
    assert(zAAfter > zBBefore, 'bringToFront gives higher z-index (zB=' + zBBefore + ', zA_after=' + zAAfter + ')');
    pm.destroyAll();
})();

(function testNextZMonotonicallyIncreases() {
    const pm = makePM();
    const z1 = pm._nextZ();
    const z2 = pm._nextZ();
    const z3 = pm._nextZ();
    assert(z2 > z1, '_nextZ increments (z1=' + z1 + ', z2=' + z2 + ')');
    assert(z3 > z2, '_nextZ increments (z2=' + z2 + ', z3=' + z3 + ')');
    pm.destroyAll();
})();

// ============================================================
// 9. saveLayout / loadLayout round-trip (mock localStorage)
// ============================================================

console.log('\n--- saveLayout / loadLayout ---');

(function testSaveAndLoadLayout() {
    mockLocalStorage.clear();
    const pm = makePM(1200, 700);
    pm.register(makeDef({ id: 'p1', title: 'P1' }));
    pm.register(makeDef({ id: 'p2', title: 'P2' }));
    const p1 = pm.open('p1');
    flushRAF();
    p1.setPosition(100, 200);
    p1.setSize(400, 300);
    const p2 = pm.open('p2');
    flushRAF();
    p2.setPosition(500, 50);
    pm.saveLayout();

    // Verify save worked
    const rawSaved = mockLocalStorage.getItem('tritium-panel-layout');
    assert(rawSaved !== null, 'saveLayout writes to localStorage');
    const parsed = JSON.parse(rawSaved);
    assert(parsed.p1 !== undefined, 'saved layout contains p1');
    assert(parsed.p1.visible === true, 'saved layout p1.visible is true');

    // NOTE: destroyAll calls close() which calls saveLayout() with empty layout,
    // overwriting our saved data. Skip destroyAll and discard the old PM.

    // Create new PM and load layout
    const pm2 = makePM(1200, 700);
    pm2.register(makeDef({ id: 'p1', title: 'P1' }));
    pm2.register(makeDef({ id: 'p2', title: 'P2' }));
    const loaded = pm2.loadLayout();
    flushRAF();
    assert(loaded === true, 'loadLayout returns true when layout exists');
    assert(pm2.isOpen('p1'), 'loadLayout opens saved panel p1');
    assert(pm2.isOpen('p2'), 'loadLayout opens saved panel p2');
    const lp1 = pm2.getPanel('p1');
    if (lp1) {
        assertClose(lp1.x, 100, 0.1, 'loadLayout restores p1.x');
        assertClose(lp1.y, 200, 0.1, 'loadLayout restores p1.y');
        assertClose(lp1.w, 400, 0.1, 'loadLayout restores p1.w');
        assertClose(lp1.h, 300, 0.1, 'loadLayout restores p1.h');
    }
    pm2.destroyAll();
    mockLocalStorage.clear();
})();

(function testLoadLayoutReturnsFalseWhenEmpty() {
    mockLocalStorage.clear();
    const pm = makePM();
    const loaded = pm.loadLayout();
    assert(loaded === false, 'loadLayout returns false when no saved layout');
    pm.destroyAll();
})();

(function testLoadLayoutSkipsUnregisteredPanels() {
    mockLocalStorage.clear();
    const pm = makePM(1200, 700);
    pm.register(makeDef({ id: 'known', title: 'Known' }));
    pm.open('known');
    pm.saveLayout();
    pm.destroyAll();

    // Load with a PM that does NOT have 'known' registered
    const pm2 = makePM();
    pm2.loadLayout();
    assert(!pm2.isOpen('known'), 'loadLayout skips panels not registered');
    pm2.destroyAll();
    mockLocalStorage.clear();
})();

// ============================================================
// 10. applyPreset closes existing panels and opens preset panels
// ============================================================

console.log('\n--- applyPreset ---');

(function testApplyPresetClosesExisting() {
    const pm = makePM(1200, 700);
    pm.register(makeDef({ id: 'amy', title: 'AMY' }));
    pm.register(makeDef({ id: 'units', title: 'UNITS' }));
    pm.register(makeDef({ id: 'alerts', title: 'ALERTS' }));

    pm.open('amy');
    pm.open('units');
    pm.open('alerts');
    assert(pm.isOpen('amy') && pm.isOpen('units') && pm.isOpen('alerts'), 'All 3 panels open before preset');

    pm.applyPreset('observer');
    // observer preset only has 'alerts'
    assert(!pm.isOpen('amy'), 'applyPreset(observer) closes amy');
    assert(!pm.isOpen('units'), 'applyPreset(observer) closes units');
    assert(pm.isOpen('alerts'), 'applyPreset(observer) opens alerts');
    pm.destroyAll();
})();

(function testApplyPresetCommanderOpensThree() {
    const pm = makePM(1200, 700);
    pm.register(makeDef({ id: 'amy', title: 'AMY' }));
    pm.register(makeDef({ id: 'units', title: 'UNITS' }));
    pm.register(makeDef({ id: 'alerts', title: 'ALERTS' }));

    pm.applyPreset('commander');
    assert(pm.isOpen('amy'), 'commander preset opens amy');
    assert(pm.isOpen('units'), 'commander preset opens units');
    assert(pm.isOpen('alerts'), 'commander preset opens alerts');
    pm.destroyAll();
})();

(function testApplyPresetClampsPositions() {
    const pm = makePM(400, 300);
    pm.register(makeDef({ id: 'amy', title: 'AMY' }));
    pm.register(makeDef({ id: 'units', title: 'UNITS' }));
    pm.register(makeDef({ id: 'alerts', title: 'ALERTS' }));

    pm.applyPreset('commander');
    // Check that panels got clamped to 400x300 container
    for (const panel of pm._panels.values()) {
        assert(panel.x >= 0, 'Preset panel x >= 0 after clamp (id=' + panel.id + ', x=' + panel.x + ')');
        assert(panel.y >= 0, 'Preset panel y >= 0 after clamp (id=' + panel.id + ', y=' + panel.y + ')');
        assert(panel.x + panel.w <= 400 || panel.w <= 400,
            'Preset panel fits in container width (id=' + panel.id + ', x=' + panel.x + ', w=' + panel.w + ')');
    }
    pm.destroyAll();
})();

(function testApplyUnknownPresetDoesNothing() {
    const pm = makePM();
    pm.register(makeDef({ id: 'amy', title: 'AMY' }));
    pm.open('amy');
    pm.applyPreset('nonexistent');
    // All panels closed by applyPreset, then unknown config is empty
    assert(!pm.isOpen('amy'), 'applyPreset(nonexistent) still closes existing panels');
    pm.destroyAll();
})();

// ============================================================
// 11. Minimized panels use HEADER_HEIGHT
// ============================================================

console.log('\n--- Minimize / Restore ---');

(function testMinimizeSetsHeight() {
    const pm = makePM(1200, 700);
    pm.register(makeDef());
    const panel = pm.open('test-panel');
    panel.minimize();
    assert(panel.minimized === true, 'panel.minimized is true after minimize()');
    assert(panel.el.style.height === '28px', 'minimized panel height is HEADER_HEIGHT (28px), got ' + panel.el.style.height);
    pm.destroyAll();
})();

(function testRestoreRestoresHeight() {
    const pm = makePM(1200, 700);
    pm.register(makeDef({ defaultSize: { w: 300, h: 250 } }));
    const panel = pm.open('test-panel');
    panel.minimize();
    panel.restore();
    assert(panel.minimized === false, 'panel.minimized is false after restore()');
    assert(panel.el.style.height === '250px', 'restored panel height is original (250px), got ' + panel.el.style.height);
    pm.destroyAll();
})();

(function testOpenMinimizedPanelRestores() {
    const pm = makePM(1200, 700);
    pm.register(makeDef({ id: 'min', title: 'Minimized' }));
    const panel = pm.open('min');
    panel.minimize();
    assert(panel.minimized === true, 'panel is minimized');
    // Opening the same panel again should restore it
    const panel2 = pm.open('min');
    assert(panel2 === panel, 'open returns same panel instance');
    assert(panel2.minimized === false, 'opening already-open minimized panel restores it');
    pm.destroyAll();
})();

// ============================================================
// 12. Resize handler clamps all panels on window resize
// ============================================================

console.log('\n--- Resize handler ---');

(function testResizeHandlerRegistered() {
    // Clear listeners before test
    _windowListeners['resize'] = [];
    const pm = makePM(1200, 700);
    assert(_windowListeners['resize'] && _windowListeners['resize'].length > 0,
        'PanelManager registers resize listener on window');
    pm.destroyAll();
})();

(function testResizeHandlerClampsAllPanels() {
    const pm = makePM(1200, 700);
    pm.register(makeDef({ id: 'a', title: 'A' }));
    pm.register(makeDef({ id: 'b', title: 'B' }));
    const pA = pm.open('a');
    const pB = pm.open('b');
    flushRAF();

    // Place panels at far right edge of 1200px container
    pA.setPosition(900, 50);
    pA.setSize(300, 250);
    pB.setPosition(850, 400);
    pB.setSize(300, 250);

    // Simulate container shrinking
    pm.container.clientWidth = 600;
    pm.container.clientHeight = 400;

    // Call _clampAllPanels directly (the resize handler would do this after debounce)
    pm._clampAllPanels();

    // Free movement: panels only need 40px visible on-screen
    assert(pA.x <= 600 - 40, 'Panel A header grabbable after container shrink (x=' + pA.x + ')');
    assert(pB.x <= 600 - 40, 'Panel B header grabbable after container shrink (x=' + pB.x + ')');
    pm.destroyAll();
})();

// ============================================================
// 13. destroyAll removes resize listener
// ============================================================

console.log('\n--- destroyAll cleanup ---');

(function testDestroyAllRemovesResizeListener() {
    _windowListeners['resize'] = [];
    const pm = makePM(1200, 700);
    const countBefore = _windowListeners['resize'].length;
    assert(countBefore > 0, 'resize listener exists before destroyAll');

    pm.destroyAll();
    const countAfter = _windowListeners['resize'].length;
    assert(countAfter < countBefore, 'destroyAll removes resize listener (before=' + countBefore + ', after=' + countAfter + ')');
    assert(pm._resizeHandler === null, '_resizeHandler set to null after destroyAll');
})();

(function testDestroyAllClosesAllPanels() {
    const pm = makePM();
    pm.register(makeDef({ id: 'a', title: 'A' }));
    pm.register(makeDef({ id: 'b', title: 'B' }));
    pm.open('a');
    pm.open('b');
    assert(pm.isOpen('a') && pm.isOpen('b'), 'Both panels open before destroyAll');
    pm.destroyAll();
    assert(!pm.isOpen('a') && !pm.isOpen('b'), 'destroyAll closes all panels');
})();

// ============================================================
// Additional edge case tests
// ============================================================

console.log('\n--- Edge cases ---');

(function testMountCallsCreateHook() {
    const pm = makePM();
    let createCalled = false;
    pm.register(makeDef({
        id: 'hook',
        title: 'Hook',
        create(panel) { createCalled = true; return 'content'; },
    }));
    pm.open('hook');
    assert(createCalled, 'mount() calls create hook');
    pm.destroyAll();
})();

(function testMountCallsMountHook() {
    const pm = makePM();
    let mountCalled = false;
    pm.register(makeDef({
        id: 'hook2',
        title: 'Hook2',
        mount(bodyEl, panel) { mountCalled = true; },
    }));
    pm.open('hook2');
    assert(mountCalled, 'mount() calls mount hook');
    pm.destroyAll();
})();

(function testGetPanelReturnsPanel() {
    const pm = makePM();
    pm.register(makeDef({ id: 'gp', title: 'GP' }));
    pm.open('gp');
    const panel = pm.getPanel('gp');
    assert(panel !== undefined, 'getPanel returns panel when open');
    assert(panel.id === 'gp', 'getPanel returns correct panel');
    pm.destroyAll();
})();

(function testMultiplePanelsIndependent() {
    const pm = makePM(1200, 700);
    pm.register(makeDef({ id: 'x', title: 'X', defaultPosition: { x: 10, y: 10 } }));
    pm.register(makeDef({ id: 'y', title: 'Y', defaultPosition: { x: 400, y: 200 } }));
    const px = pm.open('x');
    const py = pm.open('y');
    assertClose(px.x, 10, 0.1, 'Panel x has its own position');
    assertClose(py.x, 400, 0.1, 'Panel y has its own position');
    px.setPosition(50, 50);
    assertClose(py.x, 400, 0.1, 'Moving panel x does not affect panel y');
    pm.destroyAll();
})();

// ============================================================
// Summary
// ============================================================

console.log('\n' + '='.repeat(40));
console.log(`Results: ${passed} passed, ${failed} failed`);
console.log('='.repeat(40));
process.exit(failed > 0 ? 1 : 0);
