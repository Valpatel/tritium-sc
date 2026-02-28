/**
 * TRITIUM-SC Menu Bar tests
 * Tests createMenuBar, focusSaveInput, DOM structure, menu triggers,
 * dropdown creation, quick-access panel buttons, save input, ESC close,
 * EventBus panel:opened/closed sync, menu items (checkable, shortcuts,
 * separators, delete buttons).
 * Run: node tests/js/test_menu_bar.js
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
    let _hidden = false;

    const el = {
        tagName: (tag || 'DIV').toUpperCase(),
        className: '',
        get innerHTML() { return _innerHTML; },
        set innerHTML(val) {
            _innerHTML = val;
            children.length = 0;
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
        parentElement: null,
        get hidden() { return _hidden; },
        set hidden(val) { _hidden = !!val; },
        value: '',
        type: '',
        accept: '',
        placeholder: '',
        maxLength: -1,
        title: '',
        disabled: false,
        href: '',
        download: '',
        files: null,
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
                    return classList.has(cls);
                },
            };
        },
        appendChild(child) {
            children.push(child);
            if (child && typeof child === 'object') {
                child.parentNode = el;
                child.parentElement = el;
            }
            return child;
        },
        remove() {
            if (el.parentNode) {
                const idx = el.parentNode.children.indexOf(el);
                if (idx >= 0) el.parentNode.children.splice(idx, 1);
            }
        },
        _focusCalled: false,
        focus() { el._focusCalled = true; },
        click() {
            // Dispatch click event listeners
            if (eventListeners['click']) {
                const fakeEvt = { stopPropagation() {}, preventDefault() {}, target: el };
                for (const fn of eventListeners['click']) fn(fakeEvt);
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
            // Search children recursively
            return _querySelector(el, sel);
        },
        querySelectorAll(sel) {
            return _querySelectorAll(el, sel);
        },
        closest(sel) { return null; },
        getBoundingClientRect() { return { top: 0, left: 0, width: 100, height: 30 }; },
        setAttribute(k, v) { el[k] = v; },
        getAttribute(k) { return el[k]; },
        contains(other) {
            if (other === el) return true;
            for (const child of children) {
                if (child === other) return true;
                if (child.contains && child.contains(other)) return true;
            }
            return false;
        },
        get offsetWidth() { return 100; },
        get offsetHeight() { return 30; },
        get offsetTop() { return 0; },
        _eventListeners: eventListeners,
        _classList: classList,
    };
    return el;
}

// Recursive querySelector helper matching class selectors and compound selectors
function _matchesSelector(el, sel) {
    // .class-name
    const classMatch = sel.match(/^\.([a-zA-Z0-9_-]+)$/);
    if (classMatch) {
        return el.className === classMatch[1] || el._classList?.has(classMatch[1]);
    }
    // tag.class-name
    const tagClassMatch = sel.match(/^([a-z]+)\.([a-zA-Z0-9_-]+)$/);
    if (tagClassMatch) {
        return el.tagName === tagClassMatch[1].toUpperCase() &&
               (el.className === tagClassMatch[2] || el._classList?.has(tagClassMatch[2]));
    }
    return false;
}

function _querySelector(parent, sel) {
    if (!parent || !parent.children) return null;
    for (const child of parent.children) {
        if (_matchesSelector(child, sel)) return child;
        const found = _querySelector(child, sel);
        if (found) return found;
    }
    return null;
}

function _querySelectorAll(parent, sel) {
    const results = [];
    if (!parent || !parent.children) return results;
    for (const child of parent.children) {
        if (_matchesSelector(child, sel)) results.push(child);
        results.push(..._querySelectorAll(child, sel));
    }
    return results;
}

// Global document-level listeners for ESC and click-outside
const _docListeners = {};

const mockDocument = {
    createElement: createMockElement,
    getElementById(id) {
        if (id === 'help-overlay') {
            const el = createMockElement('div');
            el.hidden = true;
            return el;
        }
        return null;
    },
    querySelector: () => null,
    addEventListener(evt, fn) {
        if (!_docListeners[evt]) _docListeners[evt] = [];
        _docListeners[evt].push(fn);
    },
    removeEventListener(evt, fn) {
        if (_docListeners[evt]) {
            _docListeners[evt] = _docListeners[evt].filter(f => f !== fn);
        }
    },
    body: createMockElement('body'),
    documentElement: {
        requestFullscreen() { return Promise.resolve(); },
    },
    fullscreenElement: null,
    exitFullscreen() { return Promise.resolve(); },
};

const sandbox = {
    Math, Date, console, Map, Set, Array, Object, Number, String, Boolean,
    Infinity, NaN, undefined, parseInt, parseFloat, isNaN, isFinite, JSON,
    Promise, setTimeout, clearTimeout, setInterval, clearInterval, Error,
    RegExp, Symbol,
    Blob: function Blob(parts, opts) { this.parts = parts; this.type = opts?.type; },
    URL: {
        createObjectURL() { return 'blob:mock'; },
        revokeObjectURL() {},
    },
    FileReader: function FileReader() {
        this.onload = null;
        this.result = null;
        this.readAsText = function(f) {
            this.result = f._text || '{}';
            if (this.onload) this.onload();
        };
    },
    document: mockDocument,
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

// Load menu-bar.js
const menuBarCode = fs.readFileSync(__dirname + '/../../frontend/js/command/menu-bar.js', 'utf8');
const menuBarPlain = menuBarCode
    .replace(/^export\s+function\s+/gm, 'function ')
    .replace(/^export\s+/gm, '')
    .replace(/^import\s+.*$/gm, '');
vm.runInContext(menuBarPlain, ctx);

// ============================================================
// Mock factory helpers
// ============================================================

function makeMockPanelManager(panels) {
    const openState = {};
    for (const p of panels) openState[p.id] = !!p.isOpen;
    return {
        getRegisteredPanels() {
            return panels.map(p => ({
                id: p.id,
                title: p.title,
                isOpen: openState[p.id],
            }));
        },
        isOpen(id) { return !!openState[id]; },
        toggle(id) { openState[id] = !openState[id]; },
        open(id) { openState[id] = true; },
        close(id) { openState[id] = false; },
        _openState: openState,
    };
}

function makeMockLayoutManager() {
    const layouts = [
        { name: 'commander', builtin: true },
        { name: 'tactical', builtin: true },
        { name: 'observer', builtin: true },
    ];
    let userLayouts = [
        { name: 'my-layout', builtin: false },
    ];
    return {
        currentName: 'commander',
        listAll() { return [...layouts, ...userLayouts]; },
        apply(name) { this.currentName = name; this._lastApplied = name; },
        saveCurrent(name) { this._lastSaved = name; },
        delete(name) {
            userLayouts = userLayouts.filter(l => l.name !== name);
            this._lastDeleted = name;
        },
        exportJSON(name) {
            return JSON.stringify({ name, panels: [] });
        },
        importJSON(json) {
            try { const d = JSON.parse(json); return d.name || null; } catch { return null; }
        },
        _lastApplied: null,
        _lastSaved: null,
        _lastDeleted: null,
    };
}

function makeMockMapActions() {
    const state = {
        showSatellite: true, showRoads: false, showBuildings: true,
        showWaterways: false, showParks: false, showGrid: false,
        showModels3d: false, showLabels: true, showMesh: true, showThoughts: true, showFog: false,
        showTerrain: false, tiltMode: 'flat',
        showTracers: true, showExplosions: true, showParticles: true,
        showHitFlashes: true, showFloatingText: true,
        showKillFeed: true, showScreenFx: true, showBanners: true,
        showLayerHud: true, showHealthBars: true, showSelectionFx: true,
    };
    const calls = [];
    return {
        getMapState() { return state; },
        toggleSatellite() { state.showSatellite = !state.showSatellite; calls.push('toggleSatellite'); },
        toggleRoads() { state.showRoads = !state.showRoads; calls.push('toggleRoads'); },
        toggleBuildings() { state.showBuildings = !state.showBuildings; calls.push('toggleBuildings'); },
        toggleWaterways() { state.showWaterways = !state.showWaterways; calls.push('toggleWaterways'); },
        toggleParks() { state.showParks = !state.showParks; calls.push('toggleParks'); },
        toggleGrid() { state.showGrid = !state.showGrid; calls.push('toggleGrid'); },
        toggleModels() { state.showModels3d = !state.showModels3d; calls.push('toggleModels'); },
        toggleLabels() { state.showLabels = !state.showLabels; calls.push('toggleLabels'); },
        toggleMesh() { state.showMesh = !state.showMesh; calls.push('toggleMesh'); },
        toggleThoughts() { state.showThoughts = !state.showThoughts; calls.push('toggleThoughts'); },
        toggleFog() { state.showFog = !state.showFog; calls.push('toggleFog'); },
        toggleTerrain() { state.showTerrain = !state.showTerrain; calls.push('toggleTerrain'); },
        toggleTilt() { state.tiltMode = state.tiltMode === 'flat' ? 'tilted' : 'flat'; calls.push('toggleTilt'); },
        toggleTracers() { state.showTracers = !state.showTracers; calls.push('toggleTracers'); },
        toggleExplosions() { state.showExplosions = !state.showExplosions; calls.push('toggleExplosions'); },
        toggleParticles() { state.showParticles = !state.showParticles; calls.push('toggleParticles'); },
        toggleHitFlashes() { state.showHitFlashes = !state.showHitFlashes; calls.push('toggleHitFlashes'); },
        toggleFloatingText() { state.showFloatingText = !state.showFloatingText; calls.push('toggleFloatingText'); },
        toggleKillFeed() { state.showKillFeed = !state.showKillFeed; calls.push('toggleKillFeed'); },
        toggleScreenFx() { state.showScreenFx = !state.showScreenFx; calls.push('toggleScreenFx'); },
        toggleBanners() { state.showBanners = !state.showBanners; calls.push('toggleBanners'); },
        toggleLayerHud() { state.showLayerHud = !state.showLayerHud; calls.push('toggleLayerHud'); },
        toggleHealthBars() { state.showHealthBars = !state.showHealthBars; calls.push('toggleHealthBars'); },
        toggleSelectionFx() { state.showSelectionFx = !state.showSelectionFx; calls.push('toggleSelectionFx'); },
        toggleAllLayers() { calls.push('toggleAllLayers'); },
        centerOnAction() { calls.push('centerOnAction'); },
        resetCamera() { calls.push('resetCamera'); },
        zoomIn() { calls.push('zoomIn'); },
        zoomOut() { calls.push('zoomOut'); },
        _calls: calls,
        _state: state,
    };
}

const defaultPanels = [
    { id: 'amy', title: 'AMY COMMANDER', isOpen: true },
    { id: 'units', title: 'UNITS', isOpen: false },
    { id: 'alerts', title: 'ALERTS', isOpen: true },
    { id: 'game', title: 'GAME HUD', isOpen: false },
];

// Helper: clear doc listeners between groups that depend on them
function clearDocListeners() {
    for (const key of Object.keys(_docListeners)) {
        _docListeners[key] = [];
    }
}

// Helper: clear EventBus handlers between tests
function clearEventBus() {
    vm.runInContext('EventBus._handlers.clear()', ctx);
}

// ============================================================
// 1. createMenuBar is a function
// ============================================================

console.log('\n--- createMenuBar export ---');

(function testCreateMenuBarExists() {
    const fn = vm.runInContext('typeof createMenuBar', ctx);
    assert(fn === 'function', 'createMenuBar is a function');
})();

(function testFocusSaveInputExists() {
    const fn = vm.runInContext('typeof focusSaveInput', ctx);
    assert(fn === 'function', 'focusSaveInput is a function');
})();

// ============================================================
// 2. DOM structure: command-bar > command-bar-left + command-bar-right
// ============================================================

console.log('\n--- DOM structure ---');

(function testReturnsElement() {
    clearDocListeners(); clearEventBus();
    const container = createMockElement('div');
    const pm = makeMockPanelManager(defaultPanels);
    const lm = makeMockLayoutManager();
    const ma = makeMockMapActions();
    ctx.container = container; ctx.pm = pm; ctx.lm = lm; ctx.ma = ma;
    const bar = vm.runInContext('createMenuBar(container, pm, lm, ma)', ctx);
    assert(bar !== null && bar !== undefined, 'createMenuBar returns an element');
})();

(function testBarClassName() {
    clearDocListeners(); clearEventBus();
    const container = createMockElement('div');
    const pm = makeMockPanelManager(defaultPanels);
    const lm = makeMockLayoutManager();
    const ma = makeMockMapActions();
    ctx.container = container; ctx.pm = pm; ctx.lm = lm; ctx.ma = ma;
    const bar = vm.runInContext('createMenuBar(container, pm, lm, ma)', ctx);
    assert(bar.className === 'command-bar', 'bar has className "command-bar"');
})();

(function testBarAppendedToContainer() {
    clearDocListeners(); clearEventBus();
    const container = createMockElement('div');
    const pm = makeMockPanelManager(defaultPanels);
    const lm = makeMockLayoutManager();
    const ma = makeMockMapActions();
    ctx.container = container; ctx.pm = pm; ctx.lm = lm; ctx.ma = ma;
    vm.runInContext('createMenuBar(container, pm, lm, ma)', ctx);
    assert(container.children.length === 1, 'bar is appended to container');
})();

(function testBarHasTwoChildren() {
    clearDocListeners(); clearEventBus();
    const container = createMockElement('div');
    const pm = makeMockPanelManager(defaultPanels);
    const lm = makeMockLayoutManager();
    const ma = makeMockMapActions();
    ctx.container = container; ctx.pm = pm; ctx.lm = lm; ctx.ma = ma;
    const bar = vm.runInContext('createMenuBar(container, pm, lm, ma)', ctx);
    assert(bar.children.length === 2, 'bar has 2 children (left + right), got ' + bar.children.length);
})();

(function testLeftChild() {
    clearDocListeners(); clearEventBus();
    const container = createMockElement('div');
    const pm = makeMockPanelManager(defaultPanels);
    const lm = makeMockLayoutManager();
    const ma = makeMockMapActions();
    ctx.container = container; ctx.pm = pm; ctx.lm = lm; ctx.ma = ma;
    const bar = vm.runInContext('createMenuBar(container, pm, lm, ma)', ctx);
    assert(bar.children[0].className === 'command-bar-left', 'first child is command-bar-left');
})();

(function testRightChild() {
    clearDocListeners(); clearEventBus();
    const container = createMockElement('div');
    const pm = makeMockPanelManager(defaultPanels);
    const lm = makeMockLayoutManager();
    const ma = makeMockMapActions();
    ctx.container = container; ctx.pm = pm; ctx.lm = lm; ctx.ma = ma;
    const bar = vm.runInContext('createMenuBar(container, pm, lm, ma)', ctx);
    assert(bar.children[1].className === 'command-bar-right', 'second child is command-bar-right');
})();

// ============================================================
// 3. Menu trigger buttons: FILE, VIEW, LAYOUT, MAP, HELP
// ============================================================

console.log('\n--- Menu trigger buttons ---');

(function testLeftHasFiveMenuWraps() {
    clearDocListeners(); clearEventBus();
    const container = createMockElement('div');
    const pm = makeMockPanelManager(defaultPanels);
    const lm = makeMockLayoutManager();
    const ma = makeMockMapActions();
    ctx.container = container; ctx.pm = pm; ctx.lm = lm; ctx.ma = ma;
    const bar = vm.runInContext('createMenuBar(container, pm, lm, ma)', ctx);
    const left = bar.children[0];
    assert(left.children.length === 6, 'left has 6 menu-trigger-wrap children, got ' + left.children.length);
})();

(function testMenuTriggerLabels() {
    clearDocListeners(); clearEventBus();
    const container = createMockElement('div');
    const pm = makeMockPanelManager(defaultPanels);
    const lm = makeMockLayoutManager();
    const ma = makeMockMapActions();
    ctx.container = container; ctx.pm = pm; ctx.lm = lm; ctx.ma = ma;
    const bar = vm.runInContext('createMenuBar(container, pm, lm, ma)', ctx);
    const left = bar.children[0];
    const expectedLabels = ['FILE', 'VIEW', 'LAYOUT', 'MAP', 'GAME', 'HELP'];
    for (let i = 0; i < 6; i++) {
        const wrap = left.children[i];
        assert(wrap.className === 'menu-trigger-wrap', 'wrap ' + i + ' has correct className');
        // First child of wrap is the trigger button
        const trigger = wrap.children[0];
        assert(trigger.className === 'menu-trigger', 'trigger ' + i + ' has className menu-trigger');
        assert(trigger.textContent === expectedLabels[i],
            'trigger ' + i + ' text is "' + expectedLabels[i] + '", got "' + trigger.textContent + '"');
    }
})();

(function testMenuTriggerWrapsHaveDropdowns() {
    clearDocListeners(); clearEventBus();
    const container = createMockElement('div');
    const pm = makeMockPanelManager(defaultPanels);
    const lm = makeMockLayoutManager();
    const ma = makeMockMapActions();
    ctx.container = container; ctx.pm = pm; ctx.lm = lm; ctx.ma = ma;
    const bar = vm.runInContext('createMenuBar(container, pm, lm, ma)', ctx);
    const left = bar.children[0];
    for (let i = 0; i < 6; i++) {
        const wrap = left.children[i];
        assert(wrap.children.length === 2, 'wrap ' + i + ' has 2 children (trigger + dropdown)');
        const dropdown = wrap.children[1];
        assert(dropdown.className === 'menu-dropdown', 'wrap ' + i + ' second child is menu-dropdown');
    }
})();

// ============================================================
// 4. Menu dropdown creation and visibility
// ============================================================

console.log('\n--- Dropdown visibility ---');

(function testDropdownsStartHidden() {
    clearDocListeners(); clearEventBus();
    const container = createMockElement('div');
    const pm = makeMockPanelManager(defaultPanels);
    const lm = makeMockLayoutManager();
    const ma = makeMockMapActions();
    ctx.container = container; ctx.pm = pm; ctx.lm = lm; ctx.ma = ma;
    const bar = vm.runInContext('createMenuBar(container, pm, lm, ma)', ctx);
    const left = bar.children[0];
    for (let i = 0; i < 6; i++) {
        const dropdown = left.children[i].children[1];
        assert(dropdown.hidden === true, 'dropdown ' + i + ' starts hidden');
    }
})();

(function testTriggerClickOpensDropdown() {
    clearDocListeners(); clearEventBus();
    const container = createMockElement('div');
    const pm = makeMockPanelManager(defaultPanels);
    const lm = makeMockLayoutManager();
    const ma = makeMockMapActions();
    ctx.container = container; ctx.pm = pm; ctx.lm = lm; ctx.ma = ma;
    const bar = vm.runInContext('createMenuBar(container, pm, lm, ma)', ctx);
    const left = bar.children[0];
    const trigger = left.children[0].children[0]; // FILE trigger
    const dropdown = left.children[0].children[1]; // FILE dropdown

    // Simulate click
    trigger.click();
    assert(dropdown.hidden === false, 'clicking FILE trigger opens its dropdown');
    assert(trigger._classList.has('active'), 'clicking FILE trigger adds active class');
})();

(function testClickSameTriggerClosesDropdown() {
    clearDocListeners(); clearEventBus();
    const container = createMockElement('div');
    const pm = makeMockPanelManager(defaultPanels);
    const lm = makeMockLayoutManager();
    const ma = makeMockMapActions();
    ctx.container = container; ctx.pm = pm; ctx.lm = lm; ctx.ma = ma;
    const bar = vm.runInContext('createMenuBar(container, pm, lm, ma)', ctx);
    const left = bar.children[0];
    const trigger = left.children[0].children[0]; // FILE trigger
    const dropdown = left.children[0].children[1];

    trigger.click(); // Open
    trigger.click(); // Close (toggle)
    assert(dropdown.hidden === true, 'clicking same trigger again closes its dropdown');
    assert(!trigger._classList.has('active'), 'trigger loses active class after close');
})();

(function testClickDifferentTriggerSwitchesDropdown() {
    clearDocListeners(); clearEventBus();
    const container = createMockElement('div');
    const pm = makeMockPanelManager(defaultPanels);
    const lm = makeMockLayoutManager();
    const ma = makeMockMapActions();
    ctx.container = container; ctx.pm = pm; ctx.lm = lm; ctx.ma = ma;
    const bar = vm.runInContext('createMenuBar(container, pm, lm, ma)', ctx);
    const left = bar.children[0];

    const fileTrigger = left.children[0].children[0];
    const fileDropdown = left.children[0].children[1];
    const viewTrigger = left.children[1].children[0];
    const viewDropdown = left.children[1].children[1];

    fileTrigger.click(); // open FILE
    assert(fileDropdown.hidden === false, 'FILE dropdown is open');

    viewTrigger.click(); // open VIEW (should close FILE)
    assert(viewDropdown.hidden === false, 'VIEW dropdown opens');
    assert(fileDropdown.hidden === true, 'FILE dropdown closes when VIEW opens');
    assert(!fileTrigger._classList.has('active'), 'FILE trigger loses active class');
    assert(viewTrigger._classList.has('active'), 'VIEW trigger gains active class');
})();

// ============================================================
// 5. Quick-access panel buttons on right side
// ============================================================

console.log('\n--- Quick-access panel buttons ---');

(function testRightHasPanelButtons() {
    clearDocListeners(); clearEventBus();
    const container = createMockElement('div');
    const pm = makeMockPanelManager(defaultPanels);
    const lm = makeMockLayoutManager();
    const ma = makeMockMapActions();
    ctx.container = container; ctx.pm = pm; ctx.lm = lm; ctx.ma = ma;
    const bar = vm.runInContext('createMenuBar(container, pm, lm, ma)', ctx);
    const right = bar.children[1];
    // 4 panel buttons + 1 save input = 5 children
    assert(right.children.length === 5, 'right has 5 children (4 panel buttons + save input), got ' + right.children.length);
})();

(function testPanelButtonLabels() {
    clearDocListeners(); clearEventBus();
    const container = createMockElement('div');
    const pm = makeMockPanelManager(defaultPanels);
    const lm = makeMockLayoutManager();
    const ma = makeMockMapActions();
    ctx.container = container; ctx.pm = pm; ctx.lm = lm; ctx.ma = ma;
    const bar = vm.runInContext('createMenuBar(container, pm, lm, ma)', ctx);
    const right = bar.children[1];
    // _shortLabel takes first word of title and uppercases it
    const expected = ['AMY', 'UNITS', 'ALERTS', 'GAME'];
    for (let i = 0; i < 4; i++) {
        const btn = right.children[i];
        assert(btn.textContent === expected[i],
            'panel button ' + i + ' text is "' + expected[i] + '", got "' + btn.textContent + '"');
    }
})();

(function testPanelButtonClassName() {
    clearDocListeners(); clearEventBus();
    const container = createMockElement('div');
    const pm = makeMockPanelManager(defaultPanels);
    const lm = makeMockLayoutManager();
    const ma = makeMockMapActions();
    ctx.container = container; ctx.pm = pm; ctx.lm = lm; ctx.ma = ma;
    const bar = vm.runInContext('createMenuBar(container, pm, lm, ma)', ctx);
    const right = bar.children[1];
    for (let i = 0; i < 4; i++) {
        const btn = right.children[i];
        assert(btn.className === 'command-bar-btn', 'panel button ' + i + ' has className command-bar-btn');
    }
})();

(function testPanelButtonDataPanel() {
    clearDocListeners(); clearEventBus();
    const container = createMockElement('div');
    const pm = makeMockPanelManager(defaultPanels);
    const lm = makeMockLayoutManager();
    const ma = makeMockMapActions();
    ctx.container = container; ctx.pm = pm; ctx.lm = lm; ctx.ma = ma;
    const bar = vm.runInContext('createMenuBar(container, pm, lm, ma)', ctx);
    const right = bar.children[1];
    const expectedIds = ['amy', 'units', 'alerts', 'game'];
    for (let i = 0; i < 4; i++) {
        const btn = right.children[i];
        assert(btn.dataset.panel === expectedIds[i],
            'panel button ' + i + ' data-panel is "' + expectedIds[i] + '", got "' + btn.dataset.panel + '"');
    }
})();

(function testOpenPanelButtonHasActiveClass() {
    clearDocListeners(); clearEventBus();
    const container = createMockElement('div');
    // amy and alerts are open
    const pm = makeMockPanelManager(defaultPanels);
    const lm = makeMockLayoutManager();
    const ma = makeMockMapActions();
    ctx.container = container; ctx.pm = pm; ctx.lm = lm; ctx.ma = ma;
    const bar = vm.runInContext('createMenuBar(container, pm, lm, ma)', ctx);
    const right = bar.children[1];
    // amy (index 0) is open
    assert(right.children[0]._classList.has('active'), 'AMY button has active class (panel is open)');
    // units (index 1) is closed
    assert(!right.children[1]._classList.has('active'), 'UNITS button does NOT have active class (panel is closed)');
    // alerts (index 2) is open
    assert(right.children[2]._classList.has('active'), 'ALERTS button has active class (panel is open)');
    // game (index 3) is closed
    assert(!right.children[3]._classList.has('active'), 'GAME button does NOT have active class (panel is closed)');
})();

(function testPanelButtonTitle() {
    clearDocListeners(); clearEventBus();
    const container = createMockElement('div');
    const pm = makeMockPanelManager(defaultPanels);
    const lm = makeMockLayoutManager();
    const ma = makeMockMapActions();
    ctx.container = container; ctx.pm = pm; ctx.lm = lm; ctx.ma = ma;
    const bar = vm.runInContext('createMenuBar(container, pm, lm, ma)', ctx);
    const right = bar.children[1];
    // Amy should have key "1"
    assert(right.children[0].title.includes('1'), 'AMY button title includes shortcut key "1"');
    assert(right.children[0].title.includes('AMY COMMANDER'), 'AMY button title includes panel title');
})();

(function testPanelButtonClickTogglesPanel() {
    clearDocListeners(); clearEventBus();
    const container = createMockElement('div');
    const pm = makeMockPanelManager(defaultPanels);
    const lm = makeMockLayoutManager();
    const ma = makeMockMapActions();
    ctx.container = container; ctx.pm = pm; ctx.lm = lm; ctx.ma = ma;
    const bar = vm.runInContext('createMenuBar(container, pm, lm, ma)', ctx);
    const right = bar.children[1];
    const unitsBtn = right.children[1]; // units, initially closed
    assert(!pm._openState['units'], 'units is initially closed');
    unitsBtn.click();
    assert(pm._openState['units'], 'clicking UNITS button toggles panel open');
})();

// ============================================================
// 6. Save input element creation
// ============================================================

console.log('\n--- Save input ---');

(function testSaveInputExists() {
    clearDocListeners(); clearEventBus();
    const container = createMockElement('div');
    const pm = makeMockPanelManager(defaultPanels);
    const lm = makeMockLayoutManager();
    const ma = makeMockMapActions();
    ctx.container = container; ctx.pm = pm; ctx.lm = lm; ctx.ma = ma;
    const bar = vm.runInContext('createMenuBar(container, pm, lm, ma)', ctx);
    const right = bar.children[1];
    const saveInput = right.children[4]; // last child
    assert(saveInput.className === 'command-bar-save-input', 'save input has correct className');
})();

(function testSaveInputStartsHidden() {
    clearDocListeners(); clearEventBus();
    const container = createMockElement('div');
    const pm = makeMockPanelManager(defaultPanels);
    const lm = makeMockLayoutManager();
    const ma = makeMockMapActions();
    ctx.container = container; ctx.pm = pm; ctx.lm = lm; ctx.ma = ma;
    const bar = vm.runInContext('createMenuBar(container, pm, lm, ma)', ctx);
    const right = bar.children[1];
    const saveInput = right.children[4];
    assert(saveInput.hidden === true, 'save input starts hidden');
})();

(function testSaveInputType() {
    clearDocListeners(); clearEventBus();
    const container = createMockElement('div');
    const pm = makeMockPanelManager(defaultPanels);
    const lm = makeMockLayoutManager();
    const ma = makeMockMapActions();
    ctx.container = container; ctx.pm = pm; ctx.lm = lm; ctx.ma = ma;
    const bar = vm.runInContext('createMenuBar(container, pm, lm, ma)', ctx);
    const right = bar.children[1];
    const saveInput = right.children[4];
    assert(saveInput.type === 'text', 'save input type is "text"');
})();

(function testSaveInputPlaceholder() {
    clearDocListeners(); clearEventBus();
    const container = createMockElement('div');
    const pm = makeMockPanelManager(defaultPanels);
    const lm = makeMockLayoutManager();
    const ma = makeMockMapActions();
    ctx.container = container; ctx.pm = pm; ctx.lm = lm; ctx.ma = ma;
    const bar = vm.runInContext('createMenuBar(container, pm, lm, ma)', ctx);
    const right = bar.children[1];
    const saveInput = right.children[4];
    assert(saveInput.placeholder === 'Layout name...', 'save input has correct placeholder');
})();

(function testSaveInputMaxLength() {
    clearDocListeners(); clearEventBus();
    const container = createMockElement('div');
    const pm = makeMockPanelManager(defaultPanels);
    const lm = makeMockLayoutManager();
    const ma = makeMockMapActions();
    ctx.container = container; ctx.pm = pm; ctx.lm = lm; ctx.ma = ma;
    const bar = vm.runInContext('createMenuBar(container, pm, lm, ma)', ctx);
    const right = bar.children[1];
    const saveInput = right.children[4];
    assert(saveInput.maxLength === 24, 'save input maxLength is 24');
})();

(function testSaveInputEnterKey() {
    clearDocListeners(); clearEventBus();
    const container = createMockElement('div');
    const pm = makeMockPanelManager(defaultPanels);
    const lm = makeMockLayoutManager();
    const ma = makeMockMapActions();
    ctx.container = container; ctx.pm = pm; ctx.lm = lm; ctx.ma = ma;
    const bar = vm.runInContext('createMenuBar(container, pm, lm, ma)', ctx);
    const right = bar.children[1];
    const saveInput = right.children[4];
    saveInput.hidden = false;
    saveInput.value = 'test-layout';
    // Simulate Enter keydown
    const handlers = saveInput._eventListeners['keydown'];
    assert(handlers && handlers.length > 0, 'save input has keydown handler');
    if (handlers && handlers.length > 0) {
        handlers[0]({ key: 'Enter', stopPropagation() {} });
        assert(lm._lastSaved === 'test-layout', 'Enter key saves layout with correct name');
        assert(saveInput.hidden === true, 'Enter key hides save input');
    }
})();

(function testSaveInputEscapeKey() {
    clearDocListeners(); clearEventBus();
    const container = createMockElement('div');
    const pm = makeMockPanelManager(defaultPanels);
    const lm = makeMockLayoutManager();
    const ma = makeMockMapActions();
    ctx.container = container; ctx.pm = pm; ctx.lm = lm; ctx.ma = ma;
    const bar = vm.runInContext('createMenuBar(container, pm, lm, ma)', ctx);
    const right = bar.children[1];
    const saveInput = right.children[4];
    saveInput.hidden = false;
    const handlers = saveInput._eventListeners['keydown'];
    if (handlers && handlers.length > 0) {
        handlers[0]({ key: 'Escape', stopPropagation() {} });
        assert(saveInput.hidden === true, 'Escape key hides save input');
    }
})();

(function testSaveInputEnterEmptyDoesNotSave() {
    clearDocListeners(); clearEventBus();
    const container = createMockElement('div');
    const pm = makeMockPanelManager(defaultPanels);
    const lm = makeMockLayoutManager();
    const ma = makeMockMapActions();
    ctx.container = container; ctx.pm = pm; ctx.lm = lm; ctx.ma = ma;
    const bar = vm.runInContext('createMenuBar(container, pm, lm, ma)', ctx);
    const right = bar.children[1];
    const saveInput = right.children[4];
    saveInput.hidden = false;
    saveInput.value = '   '; // whitespace only
    const handlers = saveInput._eventListeners['keydown'];
    if (handlers && handlers.length > 0) {
        handlers[0]({ key: 'Enter', stopPropagation() {} });
        assert(lm._lastSaved === null, 'Enter with empty/whitespace name does not save');
    }
})();

// ============================================================
// 7. focusSaveInput export and behavior
// ============================================================

console.log('\n--- focusSaveInput ---');

(function testFocusSaveInputShowsAndFocuses() {
    clearDocListeners(); clearEventBus();
    const container = createMockElement('div');
    const pm = makeMockPanelManager(defaultPanels);
    const lm = makeMockLayoutManager();
    const ma = makeMockMapActions();
    ctx.container = container; ctx.pm = pm; ctx.lm = lm; ctx.ma = ma;
    const bar = vm.runInContext('createMenuBar(container, pm, lm, ma)', ctx);
    const right = bar.children[1];
    const saveInput = right.children[4];
    saveInput.value = 'old-value';

    ctx._bar = bar;
    vm.runInContext('focusSaveInput(_bar)', ctx);

    assert(saveInput.hidden === false, 'focusSaveInput shows the input');
    assert(saveInput.value === '', 'focusSaveInput clears the value');
    assert(saveInput._focusCalled === true, 'focusSaveInput calls focus()');
})();

(function testFocusSaveInputNoOpIfMissing() {
    clearDocListeners(); clearEventBus();
    // Create a bar element with no save input child
    const fakeBar = createMockElement('div');
    fakeBar.querySelector = () => null;
    ctx._fakeBar = fakeBar;
    let threw = false;
    try {
        vm.runInContext('focusSaveInput(_fakeBar)', ctx);
    } catch (e) {
        threw = true;
    }
    assert(!threw, 'focusSaveInput does not throw when input is missing');
})();

// ============================================================
// 8. ESC closes menus
// ============================================================

console.log('\n--- ESC close ---');

(function testEscClosesOpenMenu() {
    clearDocListeners(); clearEventBus();
    const container = createMockElement('div');
    const pm = makeMockPanelManager(defaultPanels);
    const lm = makeMockLayoutManager();
    const ma = makeMockMapActions();
    ctx.container = container; ctx.pm = pm; ctx.lm = lm; ctx.ma = ma;
    const bar = vm.runInContext('createMenuBar(container, pm, lm, ma)', ctx);
    const left = bar.children[0];
    const trigger = left.children[0].children[0]; // FILE trigger
    const dropdown = left.children[0].children[1];

    // Open the FILE menu
    trigger.click();
    assert(dropdown.hidden === false, 'FILE dropdown is open before ESC');

    // Dispatch ESC via document keydown
    const keyHandlers = _docListeners['keydown'] || [];
    assert(keyHandlers.length > 0, 'document has keydown listener for ESC');
    if (keyHandlers.length > 0) {
        for (const handler of keyHandlers) {
            handler({ key: 'Escape' });
        }
        assert(dropdown.hidden === true, 'ESC closes the open dropdown');
        assert(!trigger._classList.has('active'), 'ESC removes active class from trigger');
    }
})();

(function testEscDoesNothingWhenNoMenuOpen() {
    clearDocListeners(); clearEventBus();
    const container = createMockElement('div');
    const pm = makeMockPanelManager(defaultPanels);
    const lm = makeMockLayoutManager();
    const ma = makeMockMapActions();
    ctx.container = container; ctx.pm = pm; ctx.lm = lm; ctx.ma = ma;
    const bar = vm.runInContext('createMenuBar(container, pm, lm, ma)', ctx);

    // No menu open -- just make sure ESC does not throw
    let threw = false;
    const keyHandlers = _docListeners['keydown'] || [];
    try {
        for (const handler of keyHandlers) {
            handler({ key: 'Escape' });
        }
    } catch (e) {
        threw = true;
    }
    assert(!threw, 'ESC does not throw when no menu is open');
})();

// ============================================================
// 9. Click outside closes menus
// ============================================================

console.log('\n--- Click outside ---');

(function testClickOutsideClosesMenu() {
    clearDocListeners(); clearEventBus();
    const container = createMockElement('div');
    const pm = makeMockPanelManager(defaultPanels);
    const lm = makeMockLayoutManager();
    const ma = makeMockMapActions();
    ctx.container = container; ctx.pm = pm; ctx.lm = lm; ctx.ma = ma;
    const bar = vm.runInContext('createMenuBar(container, pm, lm, ma)', ctx);
    const left = bar.children[0];
    const trigger = left.children[0].children[0];
    const dropdown = left.children[0].children[1];

    trigger.click(); // Open
    assert(dropdown.hidden === false, 'dropdown is open');

    // Simulate click on an element NOT inside the bar
    const outsideEl = createMockElement('div');
    const clickHandlers = _docListeners['click'] || [];
    for (const handler of clickHandlers) {
        handler({ target: outsideEl });
    }
    assert(dropdown.hidden === true, 'click outside closes dropdown');
})();

// ============================================================
// 10. EventBus panel:opened/panel:closed syncs button state
// ============================================================

console.log('\n--- EventBus panel sync ---');

(function testPanelOpenedAddsActiveClass() {
    clearDocListeners(); clearEventBus();
    const container = createMockElement('div');
    const pm = makeMockPanelManager(defaultPanels);
    const lm = makeMockLayoutManager();
    const ma = makeMockMapActions();
    ctx.container = container; ctx.pm = pm; ctx.lm = lm; ctx.ma = ma;
    const bar = vm.runInContext('createMenuBar(container, pm, lm, ma)', ctx);
    const right = bar.children[1];
    const unitsBtn = right.children[1]; // units, initially closed
    assert(!unitsBtn._classList.has('active'), 'UNITS button starts without active');

    // Emit panel:opened
    vm.runInContext('EventBus.emit("panel:opened", { id: "units" })', ctx);
    assert(unitsBtn._classList.has('active'), 'panel:opened adds active class to UNITS button');
})();

(function testPanelClosedRemovesActiveClass() {
    clearDocListeners(); clearEventBus();
    const container = createMockElement('div');
    const pm = makeMockPanelManager(defaultPanels);
    const lm = makeMockLayoutManager();
    const ma = makeMockMapActions();
    ctx.container = container; ctx.pm = pm; ctx.lm = lm; ctx.ma = ma;
    const bar = vm.runInContext('createMenuBar(container, pm, lm, ma)', ctx);
    const right = bar.children[1];
    const amyBtn = right.children[0]; // amy, initially open
    assert(amyBtn._classList.has('active'), 'AMY button starts with active');

    // Emit panel:closed
    vm.runInContext('EventBus.emit("panel:closed", { id: "amy" })', ctx);
    assert(!amyBtn._classList.has('active'), 'panel:closed removes active class from AMY button');
})();

(function testLayoutChangedSyncsAllButtons() {
    clearDocListeners(); clearEventBus();
    const container = createMockElement('div');
    const pm = makeMockPanelManager(defaultPanels);
    const lm = makeMockLayoutManager();
    const ma = makeMockMapActions();
    ctx.container = container; ctx.pm = pm; ctx.lm = lm; ctx.ma = ma;
    const bar = vm.runInContext('createMenuBar(container, pm, lm, ma)', ctx);
    const right = bar.children[1];

    // Change open state externally
    pm._openState['amy'] = false;
    pm._openState['units'] = true;

    vm.runInContext('EventBus.emit("layout:changed")', ctx);
    assert(!right.children[0]._classList.has('active'), 'layout:changed syncs AMY button to closed');
    assert(right.children[1]._classList.has('active'), 'layout:changed syncs UNITS button to open');
})();

(function testPanelOpenedIgnoresUnknownId() {
    clearDocListeners(); clearEventBus();
    const container = createMockElement('div');
    const pm = makeMockPanelManager(defaultPanels);
    const lm = makeMockLayoutManager();
    const ma = makeMockMapActions();
    ctx.container = container; ctx.pm = pm; ctx.lm = lm; ctx.ma = ma;
    vm.runInContext('createMenuBar(container, pm, lm, ma)', ctx);

    let threw = false;
    try {
        vm.runInContext('EventBus.emit("panel:opened", { id: "nonexistent" })', ctx);
    } catch (e) {
        threw = true;
    }
    assert(!threw, 'panel:opened with unknown id does not throw');
})();

// ============================================================
// 11. Menu items: checkable, shortcuts, separators, delete buttons
// ============================================================

console.log('\n--- Dropdown items structure ---');

(function testFileMenuDropdownItems() {
    clearDocListeners(); clearEventBus();
    const container = createMockElement('div');
    const pm = makeMockPanelManager(defaultPanels);
    const lm = makeMockLayoutManager();
    const ma = makeMockMapActions();
    ctx.container = container; ctx.pm = pm; ctx.lm = lm; ctx.ma = ma;
    const bar = vm.runInContext('createMenuBar(container, pm, lm, ma)', ctx);
    const left = bar.children[0];
    const fileTrigger = left.children[0].children[0];
    const fileDropdown = left.children[0].children[1];

    fileTrigger.click(); // Opens and builds dropdown items
    // FILE menu should have: Save Layout..., Export Layout JSON, Import Layout JSON
    assert(fileDropdown.children.length === 3, 'FILE dropdown has 3 items, got ' + fileDropdown.children.length);
})();

(function testFileMenuItemLabels() {
    clearDocListeners(); clearEventBus();
    const container = createMockElement('div');
    const pm = makeMockPanelManager(defaultPanels);
    const lm = makeMockLayoutManager();
    const ma = makeMockMapActions();
    ctx.container = container; ctx.pm = pm; ctx.lm = lm; ctx.ma = ma;
    const bar = vm.runInContext('createMenuBar(container, pm, lm, ma)', ctx);
    const left = bar.children[0];
    const fileTrigger = left.children[0].children[0];
    const fileDropdown = left.children[0].children[1];

    fileTrigger.click();
    // Each menu-item row has: check span, label span, spacer span, optional shortcut/delete
    const item0 = fileDropdown.children[0];
    assert(item0.className === 'menu-item', 'first FILE item is a menu-item');
    // Label is the second child
    const label0 = item0.children[1];
    assert(label0.className === 'menu-item-label', 'first item has menu-item-label');
    assert(label0.textContent === 'Save Layout...', 'first FILE item label is "Save Layout..."');
})();

(function testFileMenuItemShortcut() {
    clearDocListeners(); clearEventBus();
    const container = createMockElement('div');
    const pm = makeMockPanelManager(defaultPanels);
    const lm = makeMockLayoutManager();
    const ma = makeMockMapActions();
    ctx.container = container; ctx.pm = pm; ctx.lm = lm; ctx.ma = ma;
    const bar = vm.runInContext('createMenuBar(container, pm, lm, ma)', ctx);
    const left = bar.children[0];
    const fileTrigger = left.children[0].children[0];
    const fileDropdown = left.children[0].children[1];

    fileTrigger.click();
    const item0 = fileDropdown.children[0]; // Save Layout...
    // Has: check, label, spacer, shortcut
    const shortcutSpan = item0.children[3];
    assert(shortcutSpan.className === 'menu-item-shortcut', 'Save Layout item has shortcut span');
    assert(shortcutSpan.textContent === 'Ctrl+Shift+S', 'Save Layout shortcut is "Ctrl+Shift+S"');
})();

(function testViewMenuHasCheckableItems() {
    clearDocListeners(); clearEventBus();
    const container = createMockElement('div');
    const pm = makeMockPanelManager(defaultPanels);
    const lm = makeMockLayoutManager();
    const ma = makeMockMapActions();
    ctx.container = container; ctx.pm = pm; ctx.lm = lm; ctx.ma = ma;
    const bar = vm.runInContext('createMenuBar(container, pm, lm, ma)', ctx);
    const left = bar.children[0];
    const viewTrigger = left.children[1].children[0];
    const viewDropdown = left.children[1].children[1];

    viewTrigger.click();
    // VIEW menu: 4 panel items + separator + Show All + Hide All + separator + Fullscreen = 9
    assert(viewDropdown.children.length === 9,
        'VIEW dropdown has 9 items (4 panels + sep + show all + hide all + sep + fullscreen), got ' + viewDropdown.children.length);

    // First item (AMY COMMANDER) should be checkable with check indicator
    const amyItem = viewDropdown.children[0];
    assert(amyItem.className === 'menu-item', 'AMY COMMANDER item is a menu-item');
    // Check indicator is first child
    const check = amyItem.children[0];
    assert(check.className === 'menu-item-check', 'first child is menu-item-check');
    // AMY is open, so check should have bullet
    assert(check.textContent === '\u2022', 'check indicator shows bullet for open panel');
})();

(function testViewMenuUncheckedItem() {
    clearDocListeners(); clearEventBus();
    const container = createMockElement('div');
    const pm = makeMockPanelManager(defaultPanels);
    const lm = makeMockLayoutManager();
    const ma = makeMockMapActions();
    ctx.container = container; ctx.pm = pm; ctx.lm = lm; ctx.ma = ma;
    const bar = vm.runInContext('createMenuBar(container, pm, lm, ma)', ctx);
    const left = bar.children[0];
    const viewTrigger = left.children[1].children[0];
    const viewDropdown = left.children[1].children[1];

    viewTrigger.click();
    // UNITS (index 1) is closed
    const unitsItem = viewDropdown.children[1];
    const check = unitsItem.children[0];
    assert(check.textContent === '', 'check indicator is empty for closed panel');
})();

(function testViewMenuSeparator() {
    clearDocListeners(); clearEventBus();
    const container = createMockElement('div');
    const pm = makeMockPanelManager(defaultPanels);
    const lm = makeMockLayoutManager();
    const ma = makeMockMapActions();
    ctx.container = container; ctx.pm = pm; ctx.lm = lm; ctx.ma = ma;
    const bar = vm.runInContext('createMenuBar(container, pm, lm, ma)', ctx);
    const left = bar.children[0];
    const viewTrigger = left.children[1].children[0];
    const viewDropdown = left.children[1].children[1];

    viewTrigger.click();
    // 5th item (index 4) should be a separator
    const sep = viewDropdown.children[4];
    assert(sep.className === 'menu-separator', 'item at index 4 is a separator');
})();

(function testViewMenuShortcuts() {
    clearDocListeners(); clearEventBus();
    const container = createMockElement('div');
    const pm = makeMockPanelManager(defaultPanels);
    const lm = makeMockLayoutManager();
    const ma = makeMockMapActions();
    ctx.container = container; ctx.pm = pm; ctx.lm = lm; ctx.ma = ma;
    const bar = vm.runInContext('createMenuBar(container, pm, lm, ma)', ctx);
    const left = bar.children[0];
    const viewTrigger = left.children[1].children[0];
    const viewDropdown = left.children[1].children[1];

    viewTrigger.click();
    // AMY item (index 0) has shortcut '1'
    const amyItem = viewDropdown.children[0];
    // Find shortcut span: check(0), label(1), spacer(2), shortcut(3)
    const shortcut = amyItem.children[3];
    assert(shortcut && shortcut.className === 'menu-item-shortcut', 'AMY item has shortcut span');
    assert(shortcut && shortcut.textContent === '1', 'AMY item shortcut is "1"');
})();

(function testLayoutMenuBuiltinItems() {
    clearDocListeners(); clearEventBus();
    const container = createMockElement('div');
    const pm = makeMockPanelManager(defaultPanels);
    const lm = makeMockLayoutManager();
    const ma = makeMockMapActions();
    ctx.container = container; ctx.pm = pm; ctx.lm = lm; ctx.ma = ma;
    const bar = vm.runInContext('createMenuBar(container, pm, lm, ma)', ctx);
    const left = bar.children[0];
    const layoutTrigger = left.children[2].children[0];
    const layoutDropdown = left.children[2].children[1];

    layoutTrigger.click();
    // Layout menu: 3 builtin + separator + 1 user + separator + Save Current... = 7
    assert(layoutDropdown.children.length === 7,
        'LAYOUT dropdown has 7 items (3 builtin + sep + 1 user + sep + save), got ' + layoutDropdown.children.length);

    // First builtin: Commander (capitalized)
    const first = layoutDropdown.children[0];
    const firstLabel = first.children[1];
    assert(firstLabel.textContent === 'Commander', 'first layout item is "Commander"');
})();

(function testLayoutMenuUserItemHasDeleteButton() {
    clearDocListeners(); clearEventBus();
    const container = createMockElement('div');
    const pm = makeMockPanelManager(defaultPanels);
    const lm = makeMockLayoutManager();
    const ma = makeMockMapActions();
    ctx.container = container; ctx.pm = pm; ctx.lm = lm; ctx.ma = ma;
    const bar = vm.runInContext('createMenuBar(container, pm, lm, ma)', ctx);
    const left = bar.children[0];
    const layoutTrigger = left.children[2].children[0];
    const layoutDropdown = left.children[2].children[1];

    layoutTrigger.click();
    // User layout is at index 4 (after 3 builtins + separator)
    const userItem = layoutDropdown.children[4];
    const userLabel = userItem.children[1];
    assert(userLabel.textContent === 'MY-LAYOUT', 'user layout label is "MY-LAYOUT" (uppercased)');

    // Delete button: check(0), label(1), spacer(2), delete(3)
    const deleteBtn = userItem.children[3];
    assert(deleteBtn.className === 'menu-item-delete', 'user item has delete button');
    assert(deleteBtn.textContent === '\u00d7', 'delete button shows multiplication sign');
})();

(function testLayoutMenuDeleteButtonAction() {
    clearDocListeners(); clearEventBus();
    const container = createMockElement('div');
    const pm = makeMockPanelManager(defaultPanels);
    const lm = makeMockLayoutManager();
    const ma = makeMockMapActions();
    ctx.container = container; ctx.pm = pm; ctx.lm = lm; ctx.ma = ma;
    const bar = vm.runInContext('createMenuBar(container, pm, lm, ma)', ctx);
    const left = bar.children[0];
    const layoutTrigger = left.children[2].children[0];
    const layoutDropdown = left.children[2].children[1];

    layoutTrigger.click();
    const userItem = layoutDropdown.children[4];
    const deleteBtn = userItem.children[3];

    // Click delete button
    deleteBtn.click();
    assert(lm._lastDeleted === 'my-layout', 'delete button calls layoutManager.delete with layout name');
})();

(function testLayoutMenuSaveCurrent() {
    clearDocListeners(); clearEventBus();
    const container = createMockElement('div');
    const pm = makeMockPanelManager(defaultPanels);
    const lm = makeMockLayoutManager();
    const ma = makeMockMapActions();
    ctx.container = container; ctx.pm = pm; ctx.lm = lm; ctx.ma = ma;
    const bar = vm.runInContext('createMenuBar(container, pm, lm, ma)', ctx);
    const left = bar.children[0];
    const layoutTrigger = left.children[2].children[0];
    const layoutDropdown = left.children[2].children[1];

    layoutTrigger.click();
    // Last item: "Save Current..."
    const lastItem = layoutDropdown.children[layoutDropdown.children.length - 1];
    const lastLabel = lastItem.children[1];
    assert(lastLabel.textContent === 'Save Current...', 'last LAYOUT item is "Save Current..."');
})();

(function testMapMenuItems() {
    clearDocListeners(); clearEventBus();
    const container = createMockElement('div');
    const pm = makeMockPanelManager(defaultPanels);
    const lm = makeMockLayoutManager();
    const ma = makeMockMapActions();
    ctx.container = container; ctx.pm = pm; ctx.lm = lm; ctx.ma = ma;
    const bar = vm.runInContext('createMenuBar(container, pm, lm, ma)', ctx);
    const left = bar.children[0];
    const mapTrigger = left.children[3].children[0];
    const mapDropdown = left.children[3].children[1];

    mapTrigger.click();
    // MAP menu: Toggle All, sep,
    //           Satellite, Roads, Buildings, Waterways, Parks, Grid, sep,
    //           3D Models, Labels, Mesh Network, sep,
    //           Tracers, Explosions, Particles, Hit Flashes, Floating Text, sep,
    //           Kill Feed, Screen FX, Banners, Layer HUD, sep,
    //           Fog, Terrain, 3D Mode, sep,
    //           Center on Action, Reset Camera, Zoom In, Zoom Out = 32
    //           + Thought Bubbles = 36
    assert(mapDropdown.children.length === 36,
        'MAP dropdown has 36 items, got ' + mapDropdown.children.length);

    // First item: Toggle All (action, not checkable)
    const toggleAllItem = mapDropdown.children[0];
    const toggleAllLabel = toggleAllItem.children[1];
    assert(toggleAllLabel.textContent === 'Toggle All', 'first MAP item is "Toggle All"');

    // Third item (index 2): Satellite (checkable, checked=true)
    const satItem = mapDropdown.children[2];
    const satCheck = satItem.children[0];
    assert(satCheck.textContent === '\u2022', 'Satellite is checked (showSatellite=true)');
    const satLabel = satItem.children[1];
    assert(satLabel.textContent === 'Satellite', 'third MAP item is "Satellite"');
})();

(function testMapMenuSatelliteShortcut() {
    clearDocListeners(); clearEventBus();
    const container = createMockElement('div');
    const pm = makeMockPanelManager(defaultPanels);
    const lm = makeMockLayoutManager();
    const ma = makeMockMapActions();
    ctx.container = container; ctx.pm = pm; ctx.lm = lm; ctx.ma = ma;
    const bar = vm.runInContext('createMenuBar(container, pm, lm, ma)', ctx);
    const left = bar.children[0];
    const mapTrigger = left.children[3].children[0];
    const mapDropdown = left.children[3].children[1];

    mapTrigger.click();
    const satItem = mapDropdown.children[2]; // index 2 (after Toggle All + sep)
    // check(0), label(1), spacer(2), shortcut(3)
    const shortcut = satItem.children[3];
    assert(shortcut.className === 'menu-item-shortcut', 'Satellite item has shortcut span');
    assert(shortcut.textContent === 'I', 'Satellite shortcut is "I"');
})();

(function testMapMenuUncheckedItem() {
    clearDocListeners(); clearEventBus();
    const container = createMockElement('div');
    const pm = makeMockPanelManager(defaultPanels);
    const lm = makeMockLayoutManager();
    const ma = makeMockMapActions();
    ctx.container = container; ctx.pm = pm; ctx.lm = lm; ctx.ma = ma;
    const bar = vm.runInContext('createMenuBar(container, pm, lm, ma)', ctx);
    const left = bar.children[0];
    const mapTrigger = left.children[3].children[0];
    const mapDropdown = left.children[3].children[1];

    mapTrigger.click();
    // Roads (index 3) is unchecked (showRoads=false)
    const roadsItem = mapDropdown.children[3];
    const roadsCheck = roadsItem.children[0];
    assert(roadsCheck.textContent === '', 'Roads check indicator is empty (unchecked)');
})();

(function testMapMenuSeparators() {
    clearDocListeners(); clearEventBus();
    const container = createMockElement('div');
    const pm = makeMockPanelManager(defaultPanels);
    const lm = makeMockLayoutManager();
    const ma = makeMockMapActions();
    ctx.container = container; ctx.pm = pm; ctx.lm = lm; ctx.ma = ma;
    const bar = vm.runInContext('createMenuBar(container, pm, lm, ma)', ctx);
    const left = bar.children[0];
    const mapTrigger = left.children[3].children[0];
    const mapDropdown = left.children[3].children[1];

    mapTrigger.click();
    // Separators at indices 1, 8, 12, 18, 23, 27 (shifted +2 from Toggle All + sep at top)
    assert(mapDropdown.children[1].className === 'menu-separator', 'MAP has separator at index 1 (after Toggle All)');
    assert(mapDropdown.children[8].className === 'menu-separator', 'MAP has separator at index 8');
    assert(mapDropdown.children[13].className === 'menu-separator', 'MAP has separator at index 13');
    assert(mapDropdown.children[19].className === 'menu-separator', 'MAP has separator at index 19');
    assert(mapDropdown.children[24].className === 'menu-separator', 'MAP has separator at index 24');
    assert(mapDropdown.children[27].className === 'menu-separator', 'MAP has separator at index 27 (after unit decorations)');
    assert(mapDropdown.children[31].className === 'menu-separator', 'MAP has separator at index 31');
})();

(function testHelpMenuItems() {
    clearDocListeners(); clearEventBus();
    const container = createMockElement('div');
    const pm = makeMockPanelManager(defaultPanels);
    const lm = makeMockLayoutManager();
    const ma = makeMockMapActions();
    ctx.container = container; ctx.pm = pm; ctx.lm = lm; ctx.ma = ma;
    const bar = vm.runInContext('createMenuBar(container, pm, lm, ma)', ctx);
    const left = bar.children[0];
    const helpTrigger = left.children[5].children[0];
    const helpDropdown = left.children[5].children[1];

    helpTrigger.click();
    assert(helpDropdown.children.length === 2, 'HELP dropdown has 2 items, got ' + helpDropdown.children.length);
    const kbItem = helpDropdown.children[0];
    const kbLabel = kbItem.children[1];
    assert(kbLabel.textContent === 'Keyboard Shortcuts', 'first HELP item is "Keyboard Shortcuts"');

    const aboutItem = helpDropdown.children[1];
    const aboutLabel = aboutItem.children[1];
    assert(aboutLabel.textContent === 'About TRITIUM-SC', 'second HELP item is "About TRITIUM-SC"');
})();

(function testHelpMenuKeyboardShortcut() {
    clearDocListeners(); clearEventBus();
    const container = createMockElement('div');
    const pm = makeMockPanelManager(defaultPanels);
    const lm = makeMockLayoutManager();
    const ma = makeMockMapActions();
    ctx.container = container; ctx.pm = pm; ctx.lm = lm; ctx.ma = ma;
    const bar = vm.runInContext('createMenuBar(container, pm, lm, ma)', ctx);
    const left = bar.children[0];
    const helpTrigger = left.children[5].children[0];
    const helpDropdown = left.children[5].children[1];

    helpTrigger.click();
    const kbItem = helpDropdown.children[0];
    const shortcut = kbItem.children[3];
    assert(shortcut.className === 'menu-item-shortcut', 'Keyboard Shortcuts has shortcut span');
    assert(shortcut.textContent === '?', 'Keyboard Shortcuts shortcut is "?"');
})();

// ============================================================
// 12. Clicking menu items triggers actions
// ============================================================

console.log('\n--- Menu item actions ---');

(function testClickingNonCheckableItemClosesMenu() {
    clearDocListeners(); clearEventBus();
    const container = createMockElement('div');
    const pm = makeMockPanelManager(defaultPanels);
    const lm = makeMockLayoutManager();
    const ma = makeMockMapActions();
    ctx.container = container; ctx.pm = pm; ctx.lm = lm; ctx.ma = ma;
    const bar = vm.runInContext('createMenuBar(container, pm, lm, ma)', ctx);
    const left = bar.children[0];
    const helpTrigger = left.children[5].children[0];
    const helpDropdown = left.children[5].children[1];

    helpTrigger.click(); // Open HELP
    assert(helpDropdown.hidden === false, 'HELP dropdown is open');

    // Click "About TRITIUM-SC" (non-checkable item)
    const aboutItem = helpDropdown.children[1];
    aboutItem.click();
    // Non-checkable items close the menu
    assert(helpDropdown.hidden === true, 'clicking non-checkable item closes the dropdown');
})();

(function testClickingCheckableItemKeepsMenuOpen() {
    clearDocListeners(); clearEventBus();
    const container = createMockElement('div');
    const pm = makeMockPanelManager(defaultPanels);
    const lm = makeMockLayoutManager();
    const ma = makeMockMapActions();
    ctx.container = container; ctx.pm = pm; ctx.lm = lm; ctx.ma = ma;
    const bar = vm.runInContext('createMenuBar(container, pm, lm, ma)', ctx);
    const left = bar.children[0];
    const mapTrigger = left.children[3].children[0];
    const mapDropdown = left.children[3].children[1];

    mapTrigger.click(); // Open MAP
    // Click "Satellite" (checkable) — now at index 2 (after Toggle All + separator)
    const satItem = mapDropdown.children[2];
    satItem.click();
    // Checkable items do NOT close the menu
    assert(mapDropdown.hidden === false, 'clicking checkable item keeps dropdown open');
})();

(function testClickingCheckableItemTogglesCheck() {
    clearDocListeners(); clearEventBus();
    const container = createMockElement('div');
    const pm = makeMockPanelManager(defaultPanels);
    const lm = makeMockLayoutManager();
    const ma = makeMockMapActions();
    ctx.container = container; ctx.pm = pm; ctx.lm = lm; ctx.ma = ma;
    const bar = vm.runInContext('createMenuBar(container, pm, lm, ma)', ctx);
    const left = bar.children[0];
    const mapTrigger = left.children[3].children[0];
    const mapDropdown = left.children[3].children[1];

    mapTrigger.click();
    const satItem = mapDropdown.children[2];
    const satCheck = satItem.children[0];
    assert(satCheck.textContent === '\u2022', 'Satellite starts checked');

    // Click toggles satellite (was true, now false)
    satItem.click();
    assert(ma._calls.includes('toggleSatellite'), 'clicking Satellite item calls toggleSatellite');
    // Check indicator should update
    assert(satCheck.textContent === '', 'check indicator updates to empty after unchecking');
})();

(function testClickingLayoutItemApplies() {
    clearDocListeners(); clearEventBus();
    const container = createMockElement('div');
    const pm = makeMockPanelManager(defaultPanels);
    const lm = makeMockLayoutManager();
    const ma = makeMockMapActions();
    ctx.container = container; ctx.pm = pm; ctx.lm = lm; ctx.ma = ma;
    const bar = vm.runInContext('createMenuBar(container, pm, lm, ma)', ctx);
    const left = bar.children[0];
    const layoutTrigger = left.children[2].children[0];
    const layoutDropdown = left.children[2].children[1];

    layoutTrigger.click();
    // Click "Tactical" (index 1, builtin)
    const tacticalItem = layoutDropdown.children[1];
    tacticalItem.click();
    assert(lm._lastApplied === 'tactical', 'clicking Tactical layout item applies "tactical"');
})();

(function testViewMenuPanelItemToggle() {
    clearDocListeners(); clearEventBus();
    const container = createMockElement('div');
    const pm = makeMockPanelManager(defaultPanels);
    const lm = makeMockLayoutManager();
    const ma = makeMockMapActions();
    ctx.container = container; ctx.pm = pm; ctx.lm = lm; ctx.ma = ma;
    const bar = vm.runInContext('createMenuBar(container, pm, lm, ma)', ctx);
    const left = bar.children[0];
    const viewTrigger = left.children[1].children[0];
    const viewDropdown = left.children[1].children[1];

    viewTrigger.click();
    // Click UNITS (index 1) -- currently closed, so toggle opens
    const unitsItem = viewDropdown.children[1];
    unitsItem.click();
    assert(pm._openState['units'] === true, 'clicking UNITS view item toggles panel open');
})();

// ============================================================
// 13. Hover mode (click one menu, hover switches to another)
// ============================================================

console.log('\n--- Hover mode ---');

(function testHoverBeforeClickDoesNothing() {
    clearDocListeners(); clearEventBus();
    const container = createMockElement('div');
    const pm = makeMockPanelManager(defaultPanels);
    const lm = makeMockLayoutManager();
    const ma = makeMockMapActions();
    ctx.container = container; ctx.pm = pm; ctx.lm = lm; ctx.ma = ma;
    const bar = vm.runInContext('createMenuBar(container, pm, lm, ma)', ctx);
    const left = bar.children[0];
    const viewTrigger = left.children[1].children[0];
    const viewDropdown = left.children[1].children[1];

    // Hover over VIEW without any menu open
    const hoverHandlers = viewTrigger._eventListeners['mouseenter'] || [];
    for (const h of hoverHandlers) h();
    assert(viewDropdown.hidden === true, 'hover before any click does not open dropdown');
})();

(function testHoverAfterClickSwitchesMenu() {
    clearDocListeners(); clearEventBus();
    const container = createMockElement('div');
    const pm = makeMockPanelManager(defaultPanels);
    const lm = makeMockLayoutManager();
    const ma = makeMockMapActions();
    ctx.container = container; ctx.pm = pm; ctx.lm = lm; ctx.ma = ma;
    const bar = vm.runInContext('createMenuBar(container, pm, lm, ma)', ctx);
    const left = bar.children[0];
    const fileTrigger = left.children[0].children[0];
    const fileDropdown = left.children[0].children[1];
    const viewTrigger = left.children[1].children[0];
    const viewDropdown = left.children[1].children[1];

    // Click FILE to open and activate hover mode
    fileTrigger.click();
    assert(fileDropdown.hidden === false, 'FILE dropdown opens on click');

    // Now hover over VIEW
    const hoverHandlers = viewTrigger._eventListeners['mouseenter'] || [];
    for (const h of hoverHandlers) h();
    assert(viewDropdown.hidden === false, 'hover switches to VIEW dropdown');
    assert(fileDropdown.hidden === true, 'hover closes FILE dropdown');
})();

// ============================================================
// 14. _shortLabel and _panelKey helpers
// ============================================================

console.log('\n--- Helper functions ---');

(function testShortLabel() {
    const result = vm.runInContext('_shortLabel("AMY COMMANDER")', ctx);
    assert(result === 'AMY', '_shortLabel("AMY COMMANDER") returns "AMY"');
})();

(function testShortLabelSingleWord() {
    const result = vm.runInContext('_shortLabel("UNITS")', ctx);
    assert(result === 'UNITS', '_shortLabel("UNITS") returns "UNITS"');
})();

(function testShortLabelEmpty() {
    const result = vm.runInContext('_shortLabel("")', ctx);
    assert(result === '', '_shortLabel("") returns ""');
})();

(function testShortLabelNull() {
    const result = vm.runInContext('_shortLabel(null)', ctx);
    assert(result === '', '_shortLabel(null) returns ""');
})();

(function testShortLabelUndefined() {
    const result = vm.runInContext('_shortLabel(undefined)', ctx);
    assert(result === '', '_shortLabel(undefined) returns ""');
})();

(function testPanelKeyAmy() {
    const result = vm.runInContext('_panelKey("amy")', ctx);
    assert(result === '1', '_panelKey("amy") returns "1"');
})();

(function testPanelKeyUnits() {
    const result = vm.runInContext('_panelKey("units")', ctx);
    assert(result === '2', '_panelKey("units") returns "2"');
})();

(function testPanelKeyAlerts() {
    const result = vm.runInContext('_panelKey("alerts")', ctx);
    assert(result === '3', '_panelKey("alerts") returns "3"');
})();

(function testPanelKeyGame() {
    const result = vm.runInContext('_panelKey("game")', ctx);
    assert(result === '4', '_panelKey("game") returns "4"');
})();

(function testPanelKeyUnknown() {
    const result = vm.runInContext('_panelKey("unknown-panel")', ctx);
    assert(result === '', '_panelKey("unknown-panel") returns ""');
})();

// ============================================================
// 15. Edge cases
// ============================================================

console.log('\n--- Edge cases ---');

(function testEmptyPanelManager() {
    clearDocListeners(); clearEventBus();
    const container = createMockElement('div');
    const pm = makeMockPanelManager([]); // No panels
    const lm = makeMockLayoutManager();
    const ma = makeMockMapActions();
    ctx.container = container; ctx.pm = pm; ctx.lm = lm; ctx.ma = ma;
    let threw = false;
    try {
        vm.runInContext('createMenuBar(container, pm, lm, ma)', ctx);
    } catch (e) {
        threw = true;
    }
    assert(!threw, 'createMenuBar works with empty panel manager (no panels)');
})();

(function testEmptyPanelManagerRightSide() {
    clearDocListeners(); clearEventBus();
    const container = createMockElement('div');
    const pm = makeMockPanelManager([]); // No panels
    const lm = makeMockLayoutManager();
    const ma = makeMockMapActions();
    ctx.container = container; ctx.pm = pm; ctx.lm = lm; ctx.ma = ma;
    const bar = vm.runInContext('createMenuBar(container, pm, lm, ma)', ctx);
    const right = bar.children[1];
    // Only the save input, no panel buttons
    assert(right.children.length === 1, 'right side has only save input when no panels, got ' + right.children.length);
})();

(function testLayoutManagerNoUserLayouts() {
    clearDocListeners(); clearEventBus();
    const container = createMockElement('div');
    const pm = makeMockPanelManager(defaultPanels);
    const lm = {
        currentName: 'commander',
        listAll() { return [{ name: 'commander', builtin: true }]; },
        apply(name) {},
        saveCurrent(name) {},
        delete(name) {},
        exportJSON(name) { return '{}'; },
        importJSON(json) { return null; },
    };
    const ma = makeMockMapActions();
    ctx.container = container; ctx.pm = pm; ctx.lm = lm; ctx.ma = ma;
    const bar = vm.runInContext('createMenuBar(container, pm, lm, ma)', ctx);
    const left = bar.children[0];
    const layoutTrigger = left.children[2].children[0];
    const layoutDropdown = left.children[2].children[1];

    layoutTrigger.click();
    // 1 builtin + separator + Save Current... = 3 (no user section)
    assert(layoutDropdown.children.length === 3,
        'LAYOUT with no user layouts has 3 items (1 builtin + sep + save), got ' + layoutDropdown.children.length);
})();

(function testMultipleCreateMenuBarCalls() {
    clearDocListeners(); clearEventBus();
    const container = createMockElement('div');
    const pm = makeMockPanelManager(defaultPanels);
    const lm = makeMockLayoutManager();
    const ma = makeMockMapActions();
    ctx.container = container; ctx.pm = pm; ctx.lm = lm; ctx.ma = ma;
    let threw = false;
    try {
        vm.runInContext('createMenuBar(container, pm, lm, ma)', ctx);
        vm.runInContext('createMenuBar(container, pm, lm, ma)', ctx);
    } catch (e) {
        threw = true;
    }
    assert(!threw, 'calling createMenuBar multiple times does not throw');
    assert(container.children.length === 2, 'each call appends a bar to container');
})();

// ============================================================
// 16. Menu item row structure details
// ============================================================

console.log('\n--- Menu item row structure ---');

(function testMenuItemHasCheckLabelSpacer() {
    clearDocListeners(); clearEventBus();
    const container = createMockElement('div');
    const pm = makeMockPanelManager(defaultPanels);
    const lm = makeMockLayoutManager();
    const ma = makeMockMapActions();
    ctx.container = container; ctx.pm = pm; ctx.lm = lm; ctx.ma = ma;
    const bar = vm.runInContext('createMenuBar(container, pm, lm, ma)', ctx);
    const left = bar.children[0];
    const helpTrigger = left.children[5].children[0];
    const helpDropdown = left.children[5].children[1];

    helpTrigger.click();
    const item = helpDropdown.children[0]; // "Keyboard Shortcuts"
    // check(0), label(1), spacer(2), shortcut(3)
    assert(item.children.length >= 3, 'menu item has at least check + label + spacer, got ' + item.children.length);
    assert(item.children[0].className === 'menu-item-check', 'first child is check');
    assert(item.children[1].className === 'menu-item-label', 'second child is label');
    assert(item.children[2].style.flex === '1', 'third child is spacer with flex=1');
})();

(function testMenuItemWithoutShortcutHasNoShortcutSpan() {
    clearDocListeners(); clearEventBus();
    const container = createMockElement('div');
    const pm = makeMockPanelManager(defaultPanels);
    const lm = makeMockLayoutManager();
    const ma = makeMockMapActions();
    ctx.container = container; ctx.pm = pm; ctx.lm = lm; ctx.ma = ma;
    const bar = vm.runInContext('createMenuBar(container, pm, lm, ma)', ctx);
    const left = bar.children[0];
    const helpTrigger = left.children[5].children[0];
    const helpDropdown = left.children[5].children[1];

    helpTrigger.click();
    // "About TRITIUM-SC" has no shortcut
    const aboutItem = helpDropdown.children[1];
    // check(0), label(1), spacer(2) -- no shortcut child at 3
    assert(aboutItem.children.length === 3, 'item without shortcut has 3 children, got ' + aboutItem.children.length);
})();

// ============================================================
// GAME Menu Tests (simplified -- no scenario radio buttons)
// ============================================================

console.log('\n--- GAME menu ---');

(function testGameMenuExists() {
    clearDocListeners(); clearEventBus();
    const container = createMockElement('div');
    const pm = makeMockPanelManager(defaultPanels);
    const lm = makeMockLayoutManager();
    const ma = makeMockMapActions();
    ctx.container = container; ctx.pm = pm; ctx.lm = lm; ctx.ma = ma;
    const bar = vm.runInContext('createMenuBar(container, pm, lm, ma)', ctx);
    const left = bar.children[0];
    // GAME menu is at index 4 (between MAP and HELP)
    const gameTrigger = left.children[4].children[0];
    assert(gameTrigger.textContent === 'GAME', 'GAME menu trigger exists at index 4');
})();

(function test_game_menu_has_new_mission_item() {
    clearDocListeners(); clearEventBus();
    const container = createMockElement('div');
    const pm = makeMockPanelManager(defaultPanels);
    const lm = makeMockLayoutManager();
    const ma = makeMockMapActions();
    ctx.container = container; ctx.pm = pm; ctx.lm = lm; ctx.ma = ma;
    const bar = vm.runInContext('createMenuBar(container, pm, lm, ma)', ctx);
    const left = bar.children[0];
    const gameTrigger = left.children[4].children[0];
    const gameDropdown = left.children[4].children[1];

    gameTrigger.click();
    // First item should be "New Mission" with shortcut "B"
    const firstItem = gameDropdown.children[0];
    const label = firstItem.children[1]; // check(0), label(1)
    assert(label.textContent === 'New Mission', 'First item is New Mission, got "' + label.textContent + '"');
    // Check shortcut
    let shortcutText = '';
    for (const child of firstItem.children) {
        if (child.className === 'menu-item-shortcut') shortcutText = child.textContent;
    }
    assert(shortcutText === 'B', 'New Mission shortcut is B, got "' + shortcutText + '"');
})();

(function test_game_menu_has_reset_item() {
    clearDocListeners(); clearEventBus();
    const container = createMockElement('div');
    const pm = makeMockPanelManager(defaultPanels);
    const lm = makeMockLayoutManager();
    const ma = makeMockMapActions();
    ctx.container = container; ctx.pm = pm; ctx.lm = lm; ctx.ma = ma;
    const bar = vm.runInContext('createMenuBar(container, pm, lm, ma)', ctx);
    const left = bar.children[0];
    const gameTrigger = left.children[4].children[0];
    const gameDropdown = left.children[4].children[1];

    gameTrigger.click();
    // Find Reset Game item and verify shortcut
    const labels = [];
    for (const child of gameDropdown.children) {
        if (child.className === 'menu-separator') continue;
        const lbl = child.children[1];
        if (lbl) labels.push(lbl.textContent);
    }
    assert(labels.includes('Reset Game'), 'GAME menu has Reset Game item');

    // Find Reset Game and check shortcut is R
    for (const child of gameDropdown.children) {
        if (child.className === 'menu-separator') continue;
        const lbl = child.children[1];
        if (lbl && lbl.textContent === 'Reset Game') {
            let sc = '';
            for (const c of child.children) {
                if (c.className === 'menu-item-shortcut') sc = c.textContent;
            }
            assert(sc === 'R', 'Reset Game shortcut is R, got "' + sc + '"');
        }
    }
})();

(function test_game_menu_no_scenario_radios() {
    clearDocListeners(); clearEventBus();
    const container = createMockElement('div');
    const pm = makeMockPanelManager(defaultPanels);
    const lm = makeMockLayoutManager();
    const ma = makeMockMapActions();
    ctx.container = container; ctx.pm = pm; ctx.lm = lm; ctx.ma = ma;
    const bar = vm.runInContext('createMenuBar(container, pm, lm, ma)', ctx);
    const left = bar.children[0];
    const gameTrigger = left.children[4].children[0];
    const gameDropdown = left.children[4].children[1];

    gameTrigger.click();
    // Collect all non-separator item labels
    const labels = [];
    for (const child of gameDropdown.children) {
        if (child.className === 'menu-separator') continue;
        const lbl = child.children[1];
        if (lbl) labels.push(lbl.textContent);
    }
    // Should NOT have any scenario radio items
    assert(!labels.includes('Classic 10-Wave'), 'GAME menu does NOT have Classic 10-Wave');
    assert(!labels.includes('Street Combat'), 'GAME menu does NOT have Street Combat');
    assert(!labels.includes('Riot'), 'GAME menu does NOT have Riot');
    // Should have exactly 2 items: New Mission and Reset Game
    assert(labels.length === 2, 'GAME menu has 2 items (New Mission + Reset Game), got ' + labels.length);
})();

(function test_getSelectedScenario_always_null() {
    clearDocListeners(); clearEventBus();
    const scenario = vm.runInContext('getSelectedScenario()', ctx);
    assert(scenario === null, 'getSelectedScenario always returns null, got "' + scenario + '"');
})();

(function testGameMenuNewMissionCallsMapActions() {
    clearDocListeners(); clearEventBus();
    const container = createMockElement('div');
    const pm = makeMockPanelManager(defaultPanels);
    const lm = makeMockLayoutManager();
    let beginCalled = false;
    const ma = makeMockMapActions();
    ma.beginWar = () => { beginCalled = true; };
    ctx.container = container; ctx.pm = pm; ctx.lm = lm; ctx.ma = ma;
    const bar = vm.runInContext('createMenuBar(container, pm, lm, ma)', ctx);
    const left = bar.children[0];
    const gameTrigger = left.children[4].children[0];
    const gameDropdown = left.children[4].children[1];

    gameTrigger.click();
    // Click New Mission (first non-separator item)
    const beginItem = gameDropdown.children[0];
    beginItem.click();
    assert(beginCalled, 'New Mission calls mapActions.beginWar()');
})();

(function testGameMenuHasOneSeparator() {
    clearDocListeners(); clearEventBus();
    const container = createMockElement('div');
    const pm = makeMockPanelManager(defaultPanels);
    const lm = makeMockLayoutManager();
    const ma = makeMockMapActions();
    ctx.container = container; ctx.pm = pm; ctx.lm = lm; ctx.ma = ma;
    const bar = vm.runInContext('createMenuBar(container, pm, lm, ma)', ctx);
    const left = bar.children[0];
    const gameTrigger = left.children[4].children[0];
    const gameDropdown = left.children[4].children[1];

    gameTrigger.click();
    let sepCount = 0;
    for (const child of gameDropdown.children) {
        if (child.className === 'menu-separator') sepCount++;
    }
    assert(sepCount === 1, 'GAME menu has 1 separator, got ' + sepCount);
})();

(function testGameMenuResetCallsMapActions() {
    clearDocListeners(); clearEventBus();
    const container = createMockElement('div');
    const pm = makeMockPanelManager(defaultPanels);
    const lm = makeMockLayoutManager();
    let resetCalled = false;
    const ma = makeMockMapActions();
    ma.resetGame = () => { resetCalled = true; };
    ctx.container = container; ctx.pm = pm; ctx.lm = lm; ctx.ma = ma;
    const bar = vm.runInContext('createMenuBar(container, pm, lm, ma)', ctx);
    const left = bar.children[0];
    const gameTrigger = left.children[4].children[0];
    const gameDropdown = left.children[4].children[1];

    gameTrigger.click();
    // Find and click Reset Game (after separator)
    for (const child of gameDropdown.children) {
        if (child.className === 'menu-separator') continue;
        const lbl = child.children[1];
        if (lbl && lbl.textContent === 'Reset Game') {
            child.click();
            break;
        }
    }
    assert(resetCalled, 'Reset Game calls mapActions.resetGame()');
})();

// ============================================================
// MAP menu — Toggle All button
// ============================================================

console.log('\n--- MAP menu — Toggle All button ---');

(function testToggleAllIsFirstItem() {
    clearDocListeners(); clearEventBus();
    const container = createMockElement('div');
    const pm = makeMockPanelManager(defaultPanels);
    const lm = makeMockLayoutManager();
    const ma = makeMockMapActions();
    ctx.container = container; ctx.pm = pm; ctx.lm = lm; ctx.ma = ma;
    const bar = vm.runInContext('createMenuBar(container, pm, lm, ma)', ctx);
    const left = bar.children[0];
    const mapTrigger = left.children[3].children[0];
    const mapDropdown = left.children[3].children[1];

    mapTrigger.click();
    const item = mapDropdown.children[0];
    assert(item && item.className === 'menu-item',
        'Toggle All is first item in MAP menu (index 0)');
    const label = item.children[1];
    assert(label.textContent === 'Toggle All',
        'First MAP item label is "Toggle All", got "' + label.textContent + '"');
})();

(function testToggleAllCallsAction() {
    clearDocListeners(); clearEventBus();
    const container = createMockElement('div');
    const pm = makeMockPanelManager(defaultPanels);
    const lm = makeMockLayoutManager();
    const ma = makeMockMapActions();
    ctx.container = container; ctx.pm = pm; ctx.lm = lm; ctx.ma = ma;
    const bar = vm.runInContext('createMenuBar(container, pm, lm, ma)', ctx);
    const left = bar.children[0];
    const mapTrigger = left.children[3].children[0];
    const mapDropdown = left.children[3].children[1];

    mapTrigger.click();
    ma._calls.length = 0;
    mapDropdown.children[0].click();
    assert(ma._calls.includes('toggleAllLayers'),
        'Clicking Toggle All calls toggleAllLayers');
})();

(function testToggleAllFollowedBySeparator() {
    clearDocListeners(); clearEventBus();
    const container = createMockElement('div');
    const pm = makeMockPanelManager(defaultPanels);
    const lm = makeMockLayoutManager();
    const ma = makeMockMapActions();
    ctx.container = container; ctx.pm = pm; ctx.lm = lm; ctx.ma = ma;
    const bar = vm.runInContext('createMenuBar(container, pm, lm, ma)', ctx);
    const left = bar.children[0];
    const mapTrigger = left.children[3].children[0];
    const mapDropdown = left.children[3].children[1];

    mapTrigger.click();
    const sep = mapDropdown.children[1];
    assert(sep && sep.className === 'menu-separator',
        'Separator follows Toggle All at index 1');
})();

// ============================================================
// MAP menu — Combat FX layer toggles
// ============================================================

console.log('\n--- MAP menu — Combat FX layer toggles ---');

// Verify each new toggle item exists and calls the right action
const _fxToggleTests = [
    { label: 'Tracers', stateKey: 'showTracers', action: 'toggleTracers', index: 14 },
    { label: 'Explosions', stateKey: 'showExplosions', action: 'toggleExplosions', index: 15 },
    { label: 'Particles', stateKey: 'showParticles', action: 'toggleParticles', index: 16 },
    { label: 'Hit Flashes', stateKey: 'showHitFlashes', action: 'toggleHitFlashes', index: 17 },
    { label: 'Floating Text', stateKey: 'showFloatingText', action: 'toggleFloatingText', index: 18 },
    { label: 'Kill Feed', stateKey: 'showKillFeed', action: 'toggleKillFeed', index: 20 },
    { label: 'Screen FX', stateKey: 'showScreenFx', action: 'toggleScreenFx', index: 21 },
    { label: 'Banners', stateKey: 'showBanners', action: 'toggleBanners', index: 22 },
    { label: 'Layer HUD', stateKey: 'showLayerHud', action: 'toggleLayerHud', index: 23 },
    { label: 'Health Bars', stateKey: 'showHealthBars', action: 'toggleHealthBars', index: 25 },
    { label: 'Selection FX', stateKey: 'showSelectionFx', action: 'toggleSelectionFx', index: 26 },
];

for (const tt of _fxToggleTests) {
    (function testFxTogglePresent() {
        clearDocListeners(); clearEventBus();
        const container = createMockElement('div');
        const pm = makeMockPanelManager(defaultPanels);
        const lm = makeMockLayoutManager();
        const ma = makeMockMapActions();
        ctx.container = container; ctx.pm = pm; ctx.lm = lm; ctx.ma = ma;
        const bar = vm.runInContext('createMenuBar(container, pm, lm, ma)', ctx);
        const left = bar.children[0];
        const mapTrigger = left.children[3].children[0];
        const mapDropdown = left.children[3].children[1];

        mapTrigger.click();
        const item = mapDropdown.children[tt.index];
        assert(item && item.className === 'menu-item',
            tt.label + ' menu item exists at index ' + tt.index);

        const label = item.children[1];
        assert(label.textContent === tt.label,
            tt.label + ' has correct label, got "' + label.textContent + '"');
    })();

    (function testFxToggleChecked() {
        clearDocListeners(); clearEventBus();
        const container = createMockElement('div');
        const pm = makeMockPanelManager(defaultPanels);
        const lm = makeMockLayoutManager();
        const ma = makeMockMapActions();
        ctx.container = container; ctx.pm = pm; ctx.lm = lm; ctx.ma = ma;
        const bar = vm.runInContext('createMenuBar(container, pm, lm, ma)', ctx);
        const left = bar.children[0];
        const mapTrigger = left.children[3].children[0];
        const mapDropdown = left.children[3].children[1];

        mapTrigger.click();
        const item = mapDropdown.children[tt.index];
        const check = item.children[0];
        assert(check.textContent === '\u2022',
            tt.label + ' is checked when ' + tt.stateKey + '=true');
    })();

    (function testFxToggleCallsAction() {
        clearDocListeners(); clearEventBus();
        const container = createMockElement('div');
        const pm = makeMockPanelManager(defaultPanels);
        const lm = makeMockLayoutManager();
        const ma = makeMockMapActions();
        ctx.container = container; ctx.pm = pm; ctx.lm = lm; ctx.ma = ma;
        const bar = vm.runInContext('createMenuBar(container, pm, lm, ma)', ctx);
        const left = bar.children[0];
        const mapTrigger = left.children[3].children[0];
        const mapDropdown = left.children[3].children[1];

        mapTrigger.click();
        ma._calls.length = 0;
        mapDropdown.children[tt.index].click();
        assert(ma._calls.includes(tt.action),
            'Clicking ' + tt.label + ' calls ' + tt.action);
    })();

    (function testFxToggleUncheckedAfterClick() {
        clearDocListeners(); clearEventBus();
        const container = createMockElement('div');
        const pm = makeMockPanelManager(defaultPanels);
        const lm = makeMockLayoutManager();
        const ma = makeMockMapActions();
        ctx.container = container; ctx.pm = pm; ctx.lm = lm; ctx.ma = ma;
        const bar = vm.runInContext('createMenuBar(container, pm, lm, ma)', ctx);
        const left = bar.children[0];
        const mapTrigger = left.children[3].children[0];
        const mapDropdown = left.children[3].children[1];

        // Click to open, then click item to toggle off
        mapTrigger.click();
        mapDropdown.children[tt.index].click();

        // State should now be false
        assert(ma._state[tt.stateKey] === false,
            tt.label + ' state is false after clicking');
    })();
}

// ============================================================
// Summary
// ============================================================

console.log('\n' + '='.repeat(40));
console.log(`Results: ${passed} passed, ${failed} failed`);
console.log('='.repeat(40));
process.exit(failed > 0 ? 1 : 0);
