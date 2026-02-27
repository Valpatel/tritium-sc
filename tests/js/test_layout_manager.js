/**
 * TRITIUM-SC LayoutManager tests
 * Tests built-in layout listing, apply, save, delete, list, export/import,
 * name validation, relative positioning, current name tracking, and
 * localStorage persistence.
 * Run: node tests/js/test_layout_manager.js
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
function assertEq(a, b, msg) {
    assert(a === b, msg + ` (got ${JSON.stringify(a)}, expected ${JSON.stringify(b)})`);
}

// ============================================================
// DOM + browser mocks (matching test_panel_manager.js patterns)
// ============================================================

const _windowListeners = {};

function createMockElement(tag) {
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

function mockCreateElement(tag) {
    const el = createMockElement(tag);
    let _innerHTML = '';
    Object.defineProperty(el, 'innerHTML', {
        get() { return _innerHTML; },
        set(val) {
            _innerHTML = val;
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

// localStorage mock with tracking
let _storage = {};
const mockLocalStorage = {
    getItem(key) { return _storage[key] || null; },
    setItem(key, val) { _storage[key] = String(val); },
    removeItem(key) { delete _storage[key]; },
    clear() { _storage = {}; },
};

// requestAnimationFrame mock
const _rafCallbacks = [];
function mockRAF(cb) {
    _rafCallbacks.push(cb);
    return _rafCallbacks.length;
}
function flushRAF() {
    while (_rafCallbacks.length > 0) {
        const cb = _rafCallbacks.shift();
        cb(Date.now());
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
    localStorage: mockLocalStorage,
    requestAnimationFrame: mockRAF,
    window: {
        addEventListener(evt, fn) {
            if (!_windowListeners[evt]) _windowListeners[evt] = [];
            _windowListeners[evt].push(fn);
        },
        removeEventListener(evt, fn) {
            if (_windowListeners[evt]) {
                _windowListeners[evt] = _windowListeners[evt].filter(f => f !== fn);
            }
        },
    },
    performance: { now: () => Date.now() },
};

const ctx = vm.createContext(sandbox);

// Load EventBus
const eventsCode = fs.readFileSync(__dirname + '/../../frontend/js/command/events.js', 'utf8');
const eventsPlain = eventsCode
    .replace(/^export\s+/gm, '')
    .replace(/^import\s+.*$/gm, '');
vm.runInContext(eventsPlain, ctx);

// Load PanelManager (needed by LayoutManager)
const panelCode = fs.readFileSync(__dirname + '/../../frontend/js/command/panel-manager.js', 'utf8');
const panelPlain = panelCode
    .replace(/^import\s+.*$/gm, '')
    .replace(/^export\s+class/gm, 'class')
    .replace(/^export\s+/gm, '');
vm.runInContext(panelPlain + '\nvar _Panel = Panel; var _PanelManager = PanelManager;', ctx);

// Load LayoutManager
const layoutCode = fs.readFileSync(__dirname + '/../../frontend/js/command/layout-manager.js', 'utf8');
const layoutPlain = layoutCode
    .replace(/^import\s+.*$/gm, '')
    .replace(/^export\s+class/gm, 'class')
    .replace(/^export\s+/gm, '')
    // Rename STORAGE_KEY to avoid const collision with panel-manager.js in same VM context
    .replace(/\bSTORAGE_KEY\b/g, 'LM_STORAGE_KEY');
vm.runInContext(layoutPlain + '\nvar _LayoutManager = LayoutManager;', ctx);

const PanelManager = ctx._PanelManager;
const LayoutManager = ctx._LayoutManager;

// ============================================================
// Helpers
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
    return new PanelManager(container);
}

/** Create a PanelManager with standard panels registered (amy, units, alerts, game) */
function makePMWithPanels(containerW, containerH) {
    const pm = makePM(containerW || 1200, containerH || 700);
    pm.register(makeDef({ id: 'amy', title: 'AMY', defaultPosition: { x: 10, y: 10 }, defaultSize: { w: 320, h: 200 } }));
    pm.register(makeDef({ id: 'units', title: 'UNITS', defaultPosition: { x: 10, y: 10 }, defaultSize: { w: 260, h: 400 } }));
    pm.register(makeDef({ id: 'alerts', title: 'ALERTS', defaultPosition: { x: 10, y: 10 }, defaultSize: { w: 280, h: 320 } }));
    pm.register(makeDef({ id: 'game', title: 'GAME', defaultPosition: { x: 10, y: 10 }, defaultSize: { w: 280, h: 250 } }));
    return pm;
}

function makeLM(pm) {
    return new LayoutManager(pm);
}

// ============================================================
// 1. Built-in layout listing
// ============================================================

console.log('\n--- Built-in Layout Listing ---');

(function testBuiltinLayoutsExist() {
    const builtins = LayoutManager.BUILTIN_LAYOUTS;
    assert(builtins.commander !== undefined, 'BUILTIN_LAYOUTS has commander');
    assert(builtins.observer !== undefined, 'BUILTIN_LAYOUTS has observer');
    assert(builtins.tactical !== undefined, 'BUILTIN_LAYOUTS has tactical');
    assert(builtins.battle !== undefined, 'BUILTIN_LAYOUTS has battle');
})();

(function testBuiltinLayoutsHavePanels() {
    const builtins = LayoutManager.BUILTIN_LAYOUTS;
    assert(builtins.commander.panels !== undefined, 'commander layout has panels');
    assert(builtins.observer.panels !== undefined, 'observer layout has panels');
    assert(builtins.tactical.panels !== undefined, 'tactical layout has panels');
    assert(builtins.battle.panels !== undefined, 'battle layout has panels');
})();

(function testCommanderLayoutPanels() {
    const panels = LayoutManager.BUILTIN_LAYOUTS.commander.panels;
    assert(panels.amy !== undefined, 'commander layout has amy panel');
    assert(panels.units !== undefined, 'commander layout has units panel');
    assert(panels.alerts !== undefined, 'commander layout has alerts panel');
})();

(function testObserverLayoutPanels() {
    const panels = LayoutManager.BUILTIN_LAYOUTS.observer.panels;
    assert(panels.alerts !== undefined, 'observer layout has alerts panel');
    assert(panels.amy === undefined, 'observer layout does not have amy panel');
    assert(panels.units === undefined, 'observer layout does not have units panel');
})();

(function testTacticalLayoutPanels() {
    const panels = LayoutManager.BUILTIN_LAYOUTS.tactical.panels;
    assert(panels.units !== undefined, 'tactical layout has units panel');
    assert(panels.alerts !== undefined, 'tactical layout has alerts panel');
    assert(panels.amy === undefined, 'tactical layout does not have amy panel');
})();

(function testBattleLayoutPanels() {
    const panels = LayoutManager.BUILTIN_LAYOUTS.battle.panels;
    assert(panels.amy !== undefined, 'battle layout has amy panel');
    assert(panels.units !== undefined, 'battle layout has units panel');
    assert(panels.alerts !== undefined, 'battle layout has alerts panel');
    assert(panels.game !== undefined, 'battle layout has game panel');
})();

(function testBuiltinLayoutPanelFields() {
    const pos = LayoutManager.BUILTIN_LAYOUTS.commander.panels.amy;
    assert(pos.x !== undefined, 'panel position has x');
    assert(pos.y !== undefined, 'panel position has y');
    assert(pos.w !== undefined, 'panel position has w');
    assert(pos.h !== undefined, 'panel position has h');
    assert(pos.visible !== undefined, 'panel position has visible');
    assert(pos.minimized !== undefined, 'panel position has minimized');
})();

// ============================================================
// 2. Apply layout (panel positioning)
// ============================================================

console.log('\n--- Apply Layout ---');

(function testApplyCommanderOpensCorrectPanels() {
    mockLocalStorage.clear();
    const pm = makePMWithPanels(1200, 700);
    const lm = makeLM(pm);
    lm.apply('commander');
    flushRAF();
    assert(pm.isOpen('amy'), 'apply commander opens amy');
    assert(pm.isOpen('units'), 'apply commander opens units');
    assert(pm.isOpen('alerts'), 'apply commander opens alerts');
    assert(!pm.isOpen('game'), 'apply commander does not open game');
    pm.destroyAll();
})();

(function testApplyObserverOpensOnlyAlerts() {
    mockLocalStorage.clear();
    const pm = makePMWithPanels(1200, 700);
    const lm = makeLM(pm);
    // Open amy first so we can verify it gets closed
    pm.open('amy');
    lm.apply('observer');
    flushRAF();
    assert(!pm.isOpen('amy'), 'apply observer closes amy');
    assert(pm.isOpen('alerts'), 'apply observer opens alerts');
    assert(!pm.isOpen('units'), 'apply observer does not open units');
    pm.destroyAll();
})();

(function testApplyTacticalOpensUnitsAndAlerts() {
    mockLocalStorage.clear();
    const pm = makePMWithPanels(1200, 700);
    const lm = makeLM(pm);
    lm.apply('tactical');
    flushRAF();
    assert(pm.isOpen('units'), 'apply tactical opens units');
    assert(pm.isOpen('alerts'), 'apply tactical opens alerts');
    assert(!pm.isOpen('amy'), 'apply tactical does not open amy');
    pm.destroyAll();
})();

(function testApplyBattleOpensFourPanels() {
    mockLocalStorage.clear();
    const pm = makePMWithPanels(1200, 700);
    const lm = makeLM(pm);
    lm.apply('battle');
    flushRAF();
    assert(pm.isOpen('amy'), 'apply battle opens amy');
    assert(pm.isOpen('units'), 'apply battle opens units');
    assert(pm.isOpen('alerts'), 'apply battle opens alerts');
    assert(pm.isOpen('game'), 'apply battle opens game');
    pm.destroyAll();
})();

(function testApplyClosesExistingPanelsFirst() {
    mockLocalStorage.clear();
    const pm = makePMWithPanels(1200, 700);
    const lm = makeLM(pm);
    // Open all four panels
    pm.open('amy');
    pm.open('units');
    pm.open('alerts');
    pm.open('game');
    // Apply observer -- should close all except alerts
    lm.apply('observer');
    flushRAF();
    assert(!pm.isOpen('amy'), 'apply observer closes previously open amy');
    assert(!pm.isOpen('units'), 'apply observer closes previously open units');
    assert(!pm.isOpen('game'), 'apply observer closes previously open game');
    assert(pm.isOpen('alerts'), 'apply observer keeps alerts open');
    pm.destroyAll();
})();

(function testApplyUnknownLayoutDoesNothing() {
    mockLocalStorage.clear();
    const pm = makePMWithPanels(1200, 700);
    const lm = makeLM(pm);
    pm.open('amy');
    lm.apply('nonexistent');
    flushRAF();
    // Panel should still be open since apply bails out for unknown layouts
    assert(pm.isOpen('amy'), 'apply unknown layout does not close existing panels');
    pm.destroyAll();
})();

(function testApplyPositionsPanelsCorrectly() {
    mockLocalStorage.clear();
    const pm = makePMWithPanels(1200, 700);
    const lm = makeLM(pm);
    lm.apply('commander');
    flushRAF();
    // Commander amy: { x: 8, y: -210, w: 320, h: 200 }
    // y: -210 => 700 + (-210) = 490
    const amy = pm.getPanel('amy');
    assertClose(amy.x, 8, 1, 'commander amy x positioned at 8');
    assertClose(amy.y, 490, 1, 'commander amy y resolved from -210 to 490');
    pm.destroyAll();
})();

(function testApplySetsCurrentName() {
    mockLocalStorage.clear();
    const pm = makePMWithPanels(1200, 700);
    const lm = makeLM(pm);
    assertEq(lm.currentName, null, 'currentName is null initially');
    lm.apply('commander');
    flushRAF();
    assertEq(lm.currentName, 'commander', 'currentName is commander after apply');
    pm.destroyAll();
})();

(function testApplyEmitsEvent() {
    mockLocalStorage.clear();
    const pm = makePMWithPanels(1200, 700);
    const lm = makeLM(pm);
    let emittedName = null;
    // Subscribe via the context's EventBus
    vm.runInContext('var _lastLayoutEvent = null; EventBus.on("layout:changed", function(d) { _lastLayoutEvent = d; });', ctx);
    lm.apply('tactical');
    flushRAF();
    const evt = ctx._lastLayoutEvent;
    assert(evt !== null, 'layout:changed event emitted');
    assertEq(evt.name, 'tactical', 'layout:changed event has correct name');
    pm.destroyAll();
})();

(function testApplyHandlesCaseInsensitivity() {
    mockLocalStorage.clear();
    const pm = makePMWithPanels(1200, 700);
    const lm = makeLM(pm);
    lm.apply('COMMANDER');
    flushRAF();
    assert(pm.isOpen('amy'), 'apply COMMANDER (uppercase) opens amy');
    assertEq(lm.currentName, 'commander', 'currentName normalized to lowercase');
    pm.destroyAll();
})();

(function testApplySkipsInvisiblePanels() {
    mockLocalStorage.clear();
    const pm = makePMWithPanels(1200, 700);
    const lm = makeLM(pm);
    // Save a user layout with visible: false
    lm.importJSON(JSON.stringify({
        name: 'skip-test',
        layout: {
            panels: {
                amy: { x: 10, y: 10, w: 300, h: 200, visible: false },
                units: { x: 10, y: 10, w: 260, h: 400, visible: true },
            },
        },
    }));
    lm.apply('skip-test');
    flushRAF();
    assert(!pm.isOpen('amy'), 'apply skips panels with visible: false');
    assert(pm.isOpen('units'), 'apply opens panels with visible: true');
    pm.destroyAll();
})();

// ============================================================
// 3. Save current layout to name
// ============================================================

console.log('\n--- Save Current Layout ---');

(function testSaveCurrentCreatesUserLayout() {
    mockLocalStorage.clear();
    const pm = makePMWithPanels(1200, 700);
    const lm = makeLM(pm);
    pm.open('amy');
    pm.open('units');
    lm.saveCurrent('my-layout');
    const list = lm.listAll();
    const found = list.find(l => l.name === 'my-layout');
    assert(found !== undefined, 'saveCurrent creates user layout');
    assert(found.builtin === false, 'saved layout is not builtin');
    pm.destroyAll();
})();

(function testSaveCurrentCapturescPanelPositions() {
    mockLocalStorage.clear();
    const pm = makePMWithPanels(1200, 700);
    const lm = makeLM(pm);
    const amy = pm.open('amy');
    amy.setPosition(100, 200);
    amy.setSize(400, 350);
    lm.saveCurrent('positioned');
    // Export and inspect
    const json = lm.exportJSON('positioned');
    const data = JSON.parse(json);
    assertClose(data.layout.panels.amy.x, 100, 1, 'saved layout captures amy x');
    assertClose(data.layout.panels.amy.y, 200, 1, 'saved layout captures amy y');
    assertClose(data.layout.panels.amy.w, 400, 1, 'saved layout captures amy w');
    assertClose(data.layout.panels.amy.h, 350, 1, 'saved layout captures amy h');
    pm.destroyAll();
})();

(function testSaveCurrentSetsCurrentName() {
    mockLocalStorage.clear();
    const pm = makePMWithPanels(1200, 700);
    const lm = makeLM(pm);
    pm.open('amy');
    lm.saveCurrent('tracking-test');
    assertEq(lm.currentName, 'tracking-test', 'saveCurrent sets currentName');
    pm.destroyAll();
})();

(function testSaveCurrentNormalizesName() {
    mockLocalStorage.clear();
    const pm = makePMWithPanels(1200, 700);
    const lm = makeLM(pm);
    pm.open('amy');
    lm.saveCurrent('  My Layout  ');
    assertEq(lm.currentName, 'my layout', 'saveCurrent normalizes name (trim + lowercase)');
    const list = lm.listAll();
    const found = list.find(l => l.name === 'my layout');
    assert(found !== undefined, 'saved layout found with normalized name');
    pm.destroyAll();
})();

(function testSaveCurrentPersistsToLocalStorage() {
    mockLocalStorage.clear();
    const pm = makePMWithPanels(1200, 700);
    const lm = makeLM(pm);
    pm.open('amy');
    lm.saveCurrent('persist-test');
    const raw = mockLocalStorage.getItem('tritium-user-layouts');
    assert(raw !== null, 'saveCurrent writes to localStorage');
    const parsed = JSON.parse(raw);
    assert(parsed['persist-test'] !== undefined, 'localStorage contains saved layout');
    pm.destroyAll();
})();

(function testSaveCurrentRecordsUnopenedPanelsAsInvisible() {
    mockLocalStorage.clear();
    const pm = makePMWithPanels(1200, 700);
    const lm = makeLM(pm);
    // Only open amy, not units/alerts/game
    pm.open('amy');
    lm.saveCurrent('partial');
    const json = lm.exportJSON('partial');
    const data = JSON.parse(json);
    // amy should be visible
    assertEq(data.layout.panels.amy.visible, true, 'open panel saved as visible');
    // units should be visible: false (registered but not opened => getPanel returns undefined)
    assertEq(data.layout.panels.units.visible, false, 'unopened panel saved with visible: false');
    pm.destroyAll();
})();

(function testSaveCurrentOverwritesExistingName() {
    mockLocalStorage.clear();
    const pm = makePMWithPanels(1200, 700);
    const lm = makeLM(pm);
    pm.open('amy');
    lm.saveCurrent('overwrite-me');
    // Change position and save again
    const amy = pm.getPanel('amy');
    amy.setPosition(999, 999);
    lm.saveCurrent('overwrite-me');
    const json = lm.exportJSON('overwrite-me');
    const data = JSON.parse(json);
    assertClose(data.layout.panels.amy.x, 999, 1, 'overwritten layout has updated x');
    pm.destroyAll();
})();

// ============================================================
// 4. Delete user layout
// ============================================================

console.log('\n--- Delete Layout ---');

(function testDeleteUserLayout() {
    mockLocalStorage.clear();
    const pm = makePMWithPanels(1200, 700);
    const lm = makeLM(pm);
    pm.open('amy');
    lm.saveCurrent('to-delete');
    const deleted = lm.delete('to-delete');
    assertEq(deleted, true, 'delete returns true for user layout');
    const list = lm.listAll();
    const found = list.find(l => l.name === 'to-delete');
    assert(found === undefined, 'deleted layout no longer in listAll');
    pm.destroyAll();
})();

(function testDeleteBuiltinReturnsFalse() {
    mockLocalStorage.clear();
    const pm = makePMWithPanels(1200, 700);
    const lm = makeLM(pm);
    const deleted = lm.delete('commander');
    assertEq(deleted, false, 'delete returns false for builtin layout');
    const list = lm.listAll();
    const found = list.find(l => l.name === 'commander');
    assert(found !== undefined, 'builtin commander still exists after delete attempt');
    pm.destroyAll();
})();

(function testDeleteNonexistentReturnsFalse() {
    mockLocalStorage.clear();
    const pm = makePMWithPanels(1200, 700);
    const lm = makeLM(pm);
    const deleted = lm.delete('does-not-exist');
    assertEq(deleted, false, 'delete returns false for nonexistent layout');
    pm.destroyAll();
})();

(function testDeleteClearsCurrentNameIfMatching() {
    mockLocalStorage.clear();
    const pm = makePMWithPanels(1200, 700);
    const lm = makeLM(pm);
    pm.open('amy');
    lm.saveCurrent('active-layout');
    assertEq(lm.currentName, 'active-layout', 'currentName set before delete');
    lm.delete('active-layout');
    assertEq(lm.currentName, null, 'currentName cleared after deleting current layout');
    pm.destroyAll();
})();

(function testDeleteDoesNotClearCurrentNameForOtherLayout() {
    mockLocalStorage.clear();
    const pm = makePMWithPanels(1200, 700);
    const lm = makeLM(pm);
    pm.open('amy');
    lm.saveCurrent('layout-a');
    lm.saveCurrent('layout-b');
    assertEq(lm.currentName, 'layout-b', 'currentName is layout-b');
    lm.delete('layout-a');
    assertEq(lm.currentName, 'layout-b', 'currentName unchanged after deleting different layout');
    pm.destroyAll();
})();

(function testDeletePersistsToLocalStorage() {
    mockLocalStorage.clear();
    const pm = makePMWithPanels(1200, 700);
    const lm = makeLM(pm);
    pm.open('amy');
    lm.saveCurrent('to-purge');
    lm.delete('to-purge');
    const raw = mockLocalStorage.getItem('tritium-user-layouts');
    const parsed = JSON.parse(raw);
    assert(parsed['to-purge'] === undefined, 'deleted layout removed from localStorage');
    pm.destroyAll();
})();

(function testDeleteNormalizesName() {
    mockLocalStorage.clear();
    const pm = makePMWithPanels(1200, 700);
    const lm = makeLM(pm);
    pm.open('amy');
    lm.saveCurrent('casesensitive');
    const deleted = lm.delete('  CaseSensitive  ');
    assertEq(deleted, true, 'delete normalizes name (trim + lowercase)');
    pm.destroyAll();
})();

// ============================================================
// 5. List all layouts (builtin + user)
// ============================================================

console.log('\n--- List All Layouts ---');

(function testListAllIncludesBuiltins() {
    mockLocalStorage.clear();
    const pm = makePMWithPanels(1200, 700);
    const lm = makeLM(pm);
    const list = lm.listAll();
    const builtinNames = list.filter(l => l.builtin).map(l => l.name);
    assert(builtinNames.includes('commander'), 'listAll includes builtin commander');
    assert(builtinNames.includes('observer'), 'listAll includes builtin observer');
    assert(builtinNames.includes('tactical'), 'listAll includes builtin tactical');
    assert(builtinNames.includes('battle'), 'listAll includes builtin battle');
    pm.destroyAll();
})();

(function testListAllIncludesUserLayouts() {
    mockLocalStorage.clear();
    const pm = makePMWithPanels(1200, 700);
    const lm = makeLM(pm);
    pm.open('amy');
    lm.saveCurrent('user-layout-1');
    lm.saveCurrent('user-layout-2');
    const list = lm.listAll();
    const userNames = list.filter(l => !l.builtin).map(l => l.name);
    assert(userNames.includes('user-layout-1'), 'listAll includes user-layout-1');
    assert(userNames.includes('user-layout-2'), 'listAll includes user-layout-2');
    pm.destroyAll();
})();

(function testListAllBuiltinsFirst() {
    mockLocalStorage.clear();
    const pm = makePMWithPanels(1200, 700);
    const lm = makeLM(pm);
    pm.open('amy');
    lm.saveCurrent('aaa-user-layout');
    const list = lm.listAll();
    // All builtins should come before user layouts
    const firstUserIdx = list.findIndex(l => !l.builtin);
    const lastBuiltinIdx = list.length - 1 - [...list].reverse().findIndex(l => l.builtin);
    assert(lastBuiltinIdx < firstUserIdx, 'all builtins listed before user layouts');
    pm.destroyAll();
})();

(function testListAllWithNoUserLayouts() {
    mockLocalStorage.clear();
    const pm = makePMWithPanels(1200, 700);
    const lm = makeLM(pm);
    const list = lm.listAll();
    assertEq(list.length, 4, 'listAll returns 4 builtins when no user layouts');
    assert(list.every(l => l.builtin), 'all entries are builtin');
    pm.destroyAll();
})();

(function testListAllReturnsArrayOfObjects() {
    mockLocalStorage.clear();
    const pm = makePMWithPanels(1200, 700);
    const lm = makeLM(pm);
    const list = lm.listAll();
    assert(Array.isArray(list), 'listAll returns an array');
    for (const item of list) {
        assert(typeof item.name === 'string', 'list item has string name');
        assert(typeof item.builtin === 'boolean', 'list item has boolean builtin');
    }
    pm.destroyAll();
})();

// ============================================================
// 6. Export/import JSON
// ============================================================

console.log('\n--- Export/Import JSON ---');

(function testExportBuiltinLayout() {
    mockLocalStorage.clear();
    const pm = makePMWithPanels(1200, 700);
    const lm = makeLM(pm);
    const json = lm.exportJSON('commander');
    assert(json !== null, 'exportJSON returns non-null for builtin');
    const data = JSON.parse(json);
    assertEq(data.name, 'commander', 'exported JSON has name');
    assert(data.layout !== undefined, 'exported JSON has layout');
    assert(data.layout.panels !== undefined, 'exported JSON has panels');
    pm.destroyAll();
})();

(function testExportUserLayout() {
    mockLocalStorage.clear();
    const pm = makePMWithPanels(1200, 700);
    const lm = makeLM(pm);
    pm.open('amy');
    lm.saveCurrent('export-me');
    const json = lm.exportJSON('export-me');
    assert(json !== null, 'exportJSON returns non-null for user layout');
    const data = JSON.parse(json);
    assertEq(data.name, 'export-me', 'exported JSON has correct name');
    assert(data.layout.panels.amy !== undefined, 'exported JSON has amy panel');
    pm.destroyAll();
})();

(function testExportUnknownLayoutReturnsNull() {
    mockLocalStorage.clear();
    const pm = makePMWithPanels(1200, 700);
    const lm = makeLM(pm);
    const json = lm.exportJSON('nonexistent');
    assertEq(json, null, 'exportJSON returns null for unknown layout');
    pm.destroyAll();
})();

(function testExportNormalizesName() {
    mockLocalStorage.clear();
    const pm = makePMWithPanels(1200, 700);
    const lm = makeLM(pm);
    const json = lm.exportJSON('  Commander  ');
    assert(json !== null, 'exportJSON normalizes name (trim + lowercase)');
    pm.destroyAll();
})();

(function testImportValidJSON() {
    mockLocalStorage.clear();
    const pm = makePMWithPanels(1200, 700);
    const lm = makeLM(pm);
    const json = JSON.stringify({
        name: 'imported-layout',
        layout: {
            panels: {
                amy: { x: 50, y: 50, w: 300, h: 200, visible: true },
            },
        },
    });
    const result = lm.importJSON(json);
    assertEq(result, 'imported-layout', 'importJSON returns layout name');
    const list = lm.listAll();
    const found = list.find(l => l.name === 'imported-layout');
    assert(found !== undefined, 'imported layout appears in listAll');
    assert(found.builtin === false, 'imported layout is not builtin');
    pm.destroyAll();
})();

(function testImportJSONPersistsToLocalStorage() {
    mockLocalStorage.clear();
    const pm = makePMWithPanels(1200, 700);
    const lm = makeLM(pm);
    const json = JSON.stringify({
        name: 'persist-import',
        layout: {
            panels: {
                amy: { x: 10, y: 10, w: 300, h: 200, visible: true },
            },
        },
    });
    lm.importJSON(json);
    const raw = mockLocalStorage.getItem('tritium-user-layouts');
    const parsed = JSON.parse(raw);
    assert(parsed['persist-import'] !== undefined, 'imported layout persisted to localStorage');
    pm.destroyAll();
})();

(function testImportInvalidJSONReturnsNull() {
    mockLocalStorage.clear();
    const pm = makePMWithPanels(1200, 700);
    const lm = makeLM(pm);
    const result = lm.importJSON('not valid json!!!');
    assertEq(result, null, 'importJSON returns null for invalid JSON');
    pm.destroyAll();
})();

(function testImportMissingNameReturnsNull() {
    mockLocalStorage.clear();
    const pm = makePMWithPanels(1200, 700);
    const lm = makeLM(pm);
    const result = lm.importJSON(JSON.stringify({ layout: { panels: {} } }));
    assertEq(result, null, 'importJSON returns null when name is missing');
    pm.destroyAll();
})();

(function testImportMissingLayoutReturnsNull() {
    mockLocalStorage.clear();
    const pm = makePMWithPanels(1200, 700);
    const lm = makeLM(pm);
    const result = lm.importJSON(JSON.stringify({ name: 'bad' }));
    assertEq(result, null, 'importJSON returns null when layout is missing');
    pm.destroyAll();
})();

(function testImportMissingPanelsReturnsNull() {
    mockLocalStorage.clear();
    const pm = makePMWithPanels(1200, 700);
    const lm = makeLM(pm);
    const result = lm.importJSON(JSON.stringify({ name: 'bad', layout: {} }));
    assertEq(result, null, 'importJSON returns null when layout.panels is missing');
    pm.destroyAll();
})();

(function testExportImportRoundTrip() {
    mockLocalStorage.clear();
    const pm = makePMWithPanels(1200, 700);
    const lm = makeLM(pm);
    // Export a builtin
    const exported = lm.exportJSON('battle');
    // Import it as user layout (it will use the same name)
    const name = lm.importJSON(exported);
    assertEq(name, 'battle', 'round-trip preserves name');
    // Now export the user copy
    const reExported = lm.exportJSON('battle');
    // They should produce equivalent layout data
    const orig = JSON.parse(exported);
    const reimp = JSON.parse(reExported);
    // Since user layout overrides builtin in lookup, check panels match
    assert(JSON.stringify(reimp.layout.panels) === JSON.stringify(orig.layout.panels),
        'round-trip export/import preserves panel data');
    pm.destroyAll();
})();

(function testImportNormalizesName() {
    mockLocalStorage.clear();
    const pm = makePMWithPanels(1200, 700);
    const lm = makeLM(pm);
    const json = JSON.stringify({
        name: '  UPPERCASE  ',
        layout: {
            panels: {
                amy: { x: 10, y: 10, w: 300, h: 200, visible: true },
            },
        },
    });
    const result = lm.importJSON(json);
    assertEq(result, 'uppercase', 'importJSON normalizes name');
    pm.destroyAll();
})();

// ============================================================
// 7. Layout name validation
// ============================================================

console.log('\n--- Name Validation ---');

(function testSaveCurrentRejectsNull() {
    mockLocalStorage.clear();
    const pm = makePMWithPanels(1200, 700);
    const lm = makeLM(pm);
    pm.open('amy');
    lm.saveCurrent(null);
    assertEq(lm.currentName, null, 'saveCurrent(null) does not set currentName');
    const userLayouts = lm.listAll().filter(l => !l.builtin);
    assertEq(userLayouts.length, 0, 'saveCurrent(null) does not create layout');
    pm.destroyAll();
})();

(function testSaveCurrentRejectsUndefined() {
    mockLocalStorage.clear();
    const pm = makePMWithPanels(1200, 700);
    const lm = makeLM(pm);
    pm.open('amy');
    lm.saveCurrent(undefined);
    assertEq(lm.currentName, null, 'saveCurrent(undefined) does not set currentName');
    pm.destroyAll();
})();

(function testSaveCurrentRejectsEmptyString() {
    mockLocalStorage.clear();
    const pm = makePMWithPanels(1200, 700);
    const lm = makeLM(pm);
    pm.open('amy');
    lm.saveCurrent('');
    assertEq(lm.currentName, null, 'saveCurrent("") does not set currentName');
    pm.destroyAll();
})();

(function testSaveCurrentRejectsWhitespaceOnly() {
    mockLocalStorage.clear();
    const pm = makePMWithPanels(1200, 700);
    const lm = makeLM(pm);
    pm.open('amy');
    lm.saveCurrent('   ');
    assertEq(lm.currentName, null, 'saveCurrent("   ") does not set currentName');
    pm.destroyAll();
})();

(function testSaveCurrentRejectsNonString() {
    mockLocalStorage.clear();
    const pm = makePMWithPanels(1200, 700);
    const lm = makeLM(pm);
    pm.open('amy');
    lm.saveCurrent(42);
    assertEq(lm.currentName, null, 'saveCurrent(42) does not set currentName');
    pm.destroyAll();
})();

(function testSaveCurrentAcceptsValidName() {
    mockLocalStorage.clear();
    const pm = makePMWithPanels(1200, 700);
    const lm = makeLM(pm);
    pm.open('amy');
    lm.saveCurrent('valid-name');
    assertEq(lm.currentName, 'valid-name', 'saveCurrent accepts valid name');
    pm.destroyAll();
})();

// ============================================================
// 8. Relative positioning (negative coords)
// ============================================================

console.log('\n--- Relative Positioning ---');

(function testNegativeXResolvesFromRight() {
    mockLocalStorage.clear();
    const pm = makePMWithPanels(1200, 700);
    const lm = makeLM(pm);
    // Commander alerts: { x: -296, y: 8, w: 280, h: 320 }
    lm.apply('commander');
    flushRAF();
    const alerts = pm.getPanel('alerts');
    // x: -296 => 1200 + (-296) = 904
    assertClose(alerts.x, 904, 1, 'negative x resolves from right edge (1200 + (-296) = 904)');
    pm.destroyAll();
})();

(function testNegativeYResolvesFromBottom() {
    mockLocalStorage.clear();
    const pm = makePMWithPanels(1200, 700);
    const lm = makeLM(pm);
    // Commander amy: { x: 8, y: -210, w: 320, h: 200 }
    lm.apply('commander');
    flushRAF();
    const amy = pm.getPanel('amy');
    // y: -210 => 700 + (-210) = 490
    assertClose(amy.y, 490, 1, 'negative y resolves from bottom edge (700 + (-210) = 490)');
    pm.destroyAll();
})();

(function testNegativeHResolvesFromContainerHeight() {
    mockLocalStorage.clear();
    const pm = makePMWithPanels(1200, 700);
    const lm = makeLM(pm);
    // Commander units: { x: 8, y: 8, w: 260, h: -230 }
    lm.apply('commander');
    flushRAF();
    const units = pm.getPanel('units');
    // h: -230 => 700 + (-230) = 470
    assertClose(units.h, 470, 1, 'negative h resolves from container height (700 + (-230) = 470)');
    pm.destroyAll();
})();

(function testPositiveCoordinatesPassThrough() {
    mockLocalStorage.clear();
    const pm = makePMWithPanels(1200, 700);
    const lm = makeLM(pm);
    // Commander units: { x: 8, y: 8, w: 260, h: -230 }
    lm.apply('commander');
    flushRAF();
    const units = pm.getPanel('units');
    assertClose(units.x, 8, 1, 'positive x passes through unchanged');
    assertClose(units.y, 8, 1, 'positive y passes through unchanged');
    assertClose(units.w, 260, 1, 'positive w passes through unchanged');
    pm.destroyAll();
})();

(function testRelativePositioningWithSmallContainer() {
    mockLocalStorage.clear();
    const pm = makePMWithPanels(800, 500);
    const lm = makeLM(pm);
    lm.apply('commander');
    flushRAF();
    const alerts = pm.getPanel('alerts');
    // x: -296 => 800 + (-296) = 504
    assertClose(alerts.x, 504, 1, 'negative x resolves correctly for 800px container');
    const amy = pm.getPanel('amy');
    // y: -210 => 500 + (-210) = 290
    assertClose(amy.y, 290, 1, 'negative y resolves correctly for 500px container');
    pm.destroyAll();
})();

// ============================================================
// 9. Current layout name tracking
// ============================================================

console.log('\n--- Current Layout Name Tracking ---');

(function testCurrentNameStartsNull() {
    mockLocalStorage.clear();
    const pm = makePMWithPanels(1200, 700);
    const lm = makeLM(pm);
    assertEq(lm.currentName, null, 'currentName starts as null');
    pm.destroyAll();
})();

(function testCurrentNameUpdatedByApply() {
    mockLocalStorage.clear();
    const pm = makePMWithPanels(1200, 700);
    const lm = makeLM(pm);
    lm.apply('observer');
    assertEq(lm.currentName, 'observer', 'currentName set by apply');
    lm.apply('tactical');
    assertEq(lm.currentName, 'tactical', 'currentName updated by subsequent apply');
    pm.destroyAll();
})();

(function testCurrentNameUpdatedBySave() {
    mockLocalStorage.clear();
    const pm = makePMWithPanels(1200, 700);
    const lm = makeLM(pm);
    pm.open('amy');
    lm.saveCurrent('saved-layout');
    assertEq(lm.currentName, 'saved-layout', 'currentName set by saveCurrent');
    pm.destroyAll();
})();

(function testCurrentNameClearedByDeleteCurrentLayout() {
    mockLocalStorage.clear();
    const pm = makePMWithPanels(1200, 700);
    const lm = makeLM(pm);
    pm.open('amy');
    lm.saveCurrent('temp');
    lm.delete('temp');
    assertEq(lm.currentName, null, 'currentName cleared when current layout is deleted');
    pm.destroyAll();
})();

(function testCurrentNameNotAffectedByUnknownApply() {
    mockLocalStorage.clear();
    const pm = makePMWithPanels(1200, 700);
    const lm = makeLM(pm);
    lm.apply('commander');
    assertEq(lm.currentName, 'commander', 'currentName is commander');
    lm.apply('nonexistent');
    assertEq(lm.currentName, 'commander', 'currentName unchanged after applying unknown layout');
    pm.destroyAll();
})();

(function testCurrentNameTracksUserLayoutApply() {
    mockLocalStorage.clear();
    const pm = makePMWithPanels(1200, 700);
    const lm = makeLM(pm);
    pm.open('amy');
    lm.saveCurrent('user-custom');
    lm.apply('commander');
    assertEq(lm.currentName, 'commander', 'currentName switched to commander');
    lm.apply('user-custom');
    assertEq(lm.currentName, 'user-custom', 'currentName switched to user layout');
    pm.destroyAll();
})();

// ============================================================
// 10. localStorage persistence (mock localStorage)
// ============================================================

console.log('\n--- localStorage Persistence ---');

(function testUserLayoutsPersistAcrossInstances() {
    mockLocalStorage.clear();
    const pm1 = makePMWithPanels(1200, 700);
    const lm1 = makeLM(pm1);
    pm1.open('amy');
    pm1.open('units');
    lm1.saveCurrent('across-instances');
    pm1.destroyAll();

    // Create new instance -- should load from localStorage
    const pm2 = makePMWithPanels(1200, 700);
    const lm2 = makeLM(pm2);
    const list = lm2.listAll();
    const found = list.find(l => l.name === 'across-instances');
    assert(found !== undefined, 'user layout persists across LayoutManager instances');
    assert(found.builtin === false, 'persisted layout is user layout');
    pm2.destroyAll();
})();

(function testUserLayoutsLoadedFromLocalStorageOnConstruction() {
    mockLocalStorage.clear();
    // Pre-populate localStorage
    mockLocalStorage.setItem('tritium-user-layouts', JSON.stringify({
        'preloaded': {
            panels: {
                amy: { x: 10, y: 10, w: 300, h: 200, visible: true },
            },
        },
    }));
    const pm = makePMWithPanels(1200, 700);
    const lm = makeLM(pm);
    const list = lm.listAll();
    const found = list.find(l => l.name === 'preloaded');
    assert(found !== undefined, 'constructor loads user layouts from localStorage');
    pm.destroyAll();
})();

(function testCorruptedLocalStorageHandledGracefully() {
    mockLocalStorage.clear();
    mockLocalStorage.setItem('tritium-user-layouts', 'not valid json!!!');
    const pm = makePMWithPanels(1200, 700);
    const lm = makeLM(pm);
    const list = lm.listAll();
    const userLayouts = list.filter(l => !l.builtin);
    assertEq(userLayouts.length, 0, 'corrupted localStorage results in empty user layouts');
    pm.destroyAll();
})();

(function testEmptyLocalStorageHandledGracefully() {
    mockLocalStorage.clear();
    const pm = makePMWithPanels(1200, 700);
    const lm = makeLM(pm);
    const list = lm.listAll();
    assertEq(list.length, 4, 'empty localStorage returns only builtins');
    pm.destroyAll();
})();

(function testMultipleUserLayoutsPersist() {
    mockLocalStorage.clear();
    const pm = makePMWithPanels(1200, 700);
    const lm = makeLM(pm);
    pm.open('amy');
    lm.saveCurrent('layout-a');
    lm.saveCurrent('layout-b');
    lm.saveCurrent('layout-c');
    pm.destroyAll();

    const pm2 = makePMWithPanels(1200, 700);
    const lm2 = makeLM(pm2);
    const userNames = lm2.listAll().filter(l => !l.builtin).map(l => l.name);
    assert(userNames.includes('layout-a'), 'layout-a persists');
    assert(userNames.includes('layout-b'), 'layout-b persists');
    assert(userNames.includes('layout-c'), 'layout-c persists');
    pm2.destroyAll();
})();

(function testDeletePersistsRemoval() {
    mockLocalStorage.clear();
    const pm = makePMWithPanels(1200, 700);
    const lm = makeLM(pm);
    pm.open('amy');
    lm.saveCurrent('to-remove');
    lm.delete('to-remove');
    pm.destroyAll();

    const pm2 = makePMWithPanels(1200, 700);
    const lm2 = makeLM(pm2);
    const found = lm2.listAll().find(l => l.name === 'to-remove');
    assert(found === undefined, 'deleted layout not present in new instance');
    pm2.destroyAll();
})();

(function testImportPersists() {
    mockLocalStorage.clear();
    const pm = makePMWithPanels(1200, 700);
    const lm = makeLM(pm);
    lm.importJSON(JSON.stringify({
        name: 'imported-persist',
        layout: {
            panels: {
                amy: { x: 10, y: 10, w: 300, h: 200, visible: true },
            },
        },
    }));
    pm.destroyAll();

    const pm2 = makePMWithPanels(1200, 700);
    const lm2 = makeLM(pm2);
    const found = lm2.listAll().find(l => l.name === 'imported-persist');
    assert(found !== undefined, 'imported layout persists across instances');
    pm2.destroyAll();
})();

// ============================================================
// Edge Cases
// ============================================================

console.log('\n--- Edge Cases ---');

(function testApplyUserLayout() {
    mockLocalStorage.clear();
    const pm = makePMWithPanels(1200, 700);
    const lm = makeLM(pm);
    // Import a user layout and apply it
    lm.importJSON(JSON.stringify({
        name: 'custom-user',
        layout: {
            panels: {
                amy: { x: 100, y: 100, w: 350, h: 250, visible: true },
                game: { x: 500, y: 300, w: 280, h: 200, visible: true },
            },
        },
    }));
    lm.apply('custom-user');
    flushRAF();
    assert(pm.isOpen('amy'), 'apply user layout opens amy');
    assert(pm.isOpen('game'), 'apply user layout opens game');
    assert(!pm.isOpen('units'), 'apply user layout does not open units');
    const amy = pm.getPanel('amy');
    assertClose(amy.x, 100, 1, 'user layout positions amy at x=100');
    assertClose(amy.y, 100, 1, 'user layout positions amy at y=100');
    pm.destroyAll();
})();

(function testApplyLayoutWithMinimizedPanel() {
    mockLocalStorage.clear();
    const pm = makePMWithPanels(1200, 700);
    const lm = makeLM(pm);
    lm.importJSON(JSON.stringify({
        name: 'minimized-test',
        layout: {
            panels: {
                amy: { x: 10, y: 10, w: 300, h: 200, visible: true, minimized: true },
                units: { x: 300, y: 10, w: 260, h: 400, visible: true, minimized: false },
            },
        },
    }));
    lm.apply('minimized-test');
    flushRAF();
    const amy = pm.getPanel('amy');
    assert(amy.minimized === true, 'apply restores minimized state');
    const units = pm.getPanel('units');
    assert(units.minimized === false, 'apply non-minimized panel stays restored');
    pm.destroyAll();
})();

(function testApplyLayoutSkipsUnregisteredPanelIds() {
    mockLocalStorage.clear();
    const pm = makePMWithPanels(1200, 700);
    const lm = makeLM(pm);
    // Import layout with panel id not registered in pm
    lm.importJSON(JSON.stringify({
        name: 'unknown-panels',
        layout: {
            panels: {
                amy: { x: 10, y: 10, w: 300, h: 200, visible: true },
                nonexistent_panel: { x: 500, y: 500, w: 300, h: 200, visible: true },
            },
        },
    }));
    // Should not crash
    lm.apply('unknown-panels');
    flushRAF();
    assert(pm.isOpen('amy'), 'known panel opens');
    assert(!pm.isOpen('nonexistent_panel'), 'unknown panel id is skipped');
    pm.destroyAll();
})();

(function testExportProducesValidJSON() {
    mockLocalStorage.clear();
    const pm = makePMWithPanels(1200, 700);
    const lm = makeLM(pm);
    const json = lm.exportJSON('battle');
    // Validate it parses without error
    let parsed;
    try {
        parsed = JSON.parse(json);
        assert(true, 'exportJSON produces valid JSON');
    } catch (e) {
        assert(false, 'exportJSON produces valid JSON (parse error: ' + e.message + ')');
    }
    // Validate structure
    assert(typeof parsed.name === 'string', 'export has string name');
    assert(typeof parsed.layout === 'object', 'export has object layout');
    assert(typeof parsed.layout.panels === 'object', 'export has object panels');
    pm.destroyAll();
})();

(function testSaveCurrentWithMinimizedPanel() {
    mockLocalStorage.clear();
    const pm = makePMWithPanels(1200, 700);
    const lm = makeLM(pm);
    const amy = pm.open('amy');
    amy.minimize();
    lm.saveCurrent('minimized-save');
    const json = lm.exportJSON('minimized-save');
    const data = JSON.parse(json);
    assertEq(data.layout.panels.amy.minimized, true, 'save captures minimized state');
    pm.destroyAll();
})();

(function testConstructorWithNoContainer() {
    mockLocalStorage.clear();
    // PanelManager with null-ish container (no clientWidth/clientHeight)
    const pm = makePM(undefined, undefined);
    pm.register(makeDef({ id: 'amy', title: 'AMY' }));
    const lm = makeLM(pm);
    // Should not crash
    assert(lm.currentName === null, 'LayoutManager works with undefined container dimensions');
    pm.destroyAll();
})();

(function testApplyCallesSaveLayout() {
    mockLocalStorage.clear();
    const pm = makePMWithPanels(1200, 700);
    const lm = makeLM(pm);
    // Clear localStorage to verify apply triggers saveLayout
    mockLocalStorage.clear();
    lm.apply('observer');
    flushRAF();
    const raw = mockLocalStorage.getItem('tritium-panel-layout');
    assert(raw !== null, 'apply calls panelManager.saveLayout() which writes to localStorage');
    pm.destroyAll();
})();

(function testBattleLayoutHasAllFourPanelDefinitions() {
    const battle = LayoutManager.BUILTIN_LAYOUTS.battle;
    const panelIds = Object.keys(battle.panels);
    assertEq(panelIds.length, 4, 'battle layout defines exactly 4 panels');
    assert(panelIds.includes('amy'), 'battle has amy');
    assert(panelIds.includes('units'), 'battle has units');
    assert(panelIds.includes('alerts'), 'battle has alerts');
    assert(panelIds.includes('game'), 'battle has game');
})();

(function testObserverLayoutHasOnlyOnePanel() {
    const observer = LayoutManager.BUILTIN_LAYOUTS.observer;
    const panelIds = Object.keys(observer.panels);
    assertEq(panelIds.length, 1, 'observer layout defines exactly 1 panel');
    assert(panelIds.includes('alerts'), 'observer has only alerts');
})();

(function testSaveCurrentCapturesClosedPanelState() {
    mockLocalStorage.clear();
    const pm = makePMWithPanels(1200, 700);
    const lm = makeLM(pm);
    const amy = pm.open('amy');
    pm.close('amy');
    lm.saveCurrent('closed-panel');
    const json = lm.exportJSON('closed-panel');
    const data = JSON.parse(json);
    // Panel was opened then closed (hidden), so _visible = false
    assertEq(data.layout.panels.amy.visible, false, 'closed panel saved as visible: false');
    pm.destroyAll();
})();

// ============================================================
// Summary
// ============================================================

console.log('\n' + '='.repeat(40));
console.log(`Results: ${passed} passed, ${failed} failed`);
console.log('='.repeat(40));
process.exit(failed > 0 ? 1 : 0);
