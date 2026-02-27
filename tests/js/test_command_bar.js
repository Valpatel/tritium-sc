/**
 * TRITIUM-SC Command Bar tests
 * Tests createCommandBar, focusSaveInput, DOM structure, panel toggle buttons,
 * layout dropdown, save input, EventBus panel:opened/closed/layout:changed sync,
 * helper functions (_shortLabel, _panelKey, _updateLayoutLabel, _syncPanelButtons),
 * and edge cases.
 * Run: node tests/js/test_command_bar.js
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
        placeholder: '',
        maxLength: -1,
        title: '',
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
            return _querySelector(el, sel);
        },
        querySelectorAll(sel) {
            return _querySelectorAll(el, sel);
        },
        closest(sel) { return null; },
        getBoundingClientRect() { return { top: 0, left: 0, width: 100, height: 28 }; },
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
        get offsetHeight() { return 28; },
        _eventListeners: eventListeners,
        _classList: classList,
    };
    return el;
}

function _matchesSelector(el, sel) {
    const classMatch = sel.match(/^\.([a-zA-Z0-9_-]+)$/);
    if (classMatch) {
        return el.className === classMatch[1] || el._classList?.has(classMatch[1]);
    }
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

// Global document-level listeners
const _docListeners = {};

// Track help-overlay element so getElementById returns a persistent reference
const _helpOverlay = createMockElement('div');
_helpOverlay.hidden = true;

const mockDocument = {
    createElement: createMockElement,
    getElementById(id) {
        if (id === 'help-overlay') return _helpOverlay;
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
};

const sandbox = {
    Math, Date, console, Map, Set, Array, Object, Number, String, Boolean,
    Infinity, NaN, undefined, parseInt, parseFloat, isNaN, isFinite, JSON,
    Promise, setTimeout, clearTimeout, setInterval, clearInterval, Error,
    RegExp, Symbol,
    document: mockDocument,
    window: {},
    performance: { now: () => Date.now() },
};

const ctx = vm.createContext(sandbox);

// Load events.js (EventBus)
const eventsCode = fs.readFileSync(__dirname + '/../../frontend/js/command/events.js', 'utf8');
const eventsPlain = eventsCode
    .replace(/^export\s+/gm, '')
    .replace(/^import\s+.*$/gm, '');
vm.runInContext(eventsPlain, ctx);

// Load command-bar.js
const commandBarCode = fs.readFileSync(__dirname + '/../../frontend/js/command/command-bar.js', 'utf8');
const commandBarPlain = commandBarCode
    .replace(/^export\s+function\s+/gm, 'function ')
    .replace(/^export\s+/gm, '')
    .replace(/^import\s+.*$/gm, '');
vm.runInContext(commandBarPlain, ctx);

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
        _toggleCalls: [],
    };
}

function makeMockLayoutManager(overrides) {
    const layouts = [
        { name: 'commander', builtin: true },
        { name: 'tactical', builtin: true },
        { name: 'observer', builtin: true },
    ];
    let userLayouts = [
        { name: 'my-layout', builtin: false },
    ];
    return Object.assign({
        currentName: 'commander',
        listAll() { return [...layouts, ...userLayouts]; },
        apply(name) { this.currentName = name; this._lastApplied = name; },
        saveCurrent(name) { this.currentName = name; this._lastSaved = name; },
        delete(name) {
            userLayouts = userLayouts.filter(l => l.name !== name);
            this._lastDeleted = name;
        },
        _lastApplied: null,
        _lastSaved: null,
        _lastDeleted: null,
    }, overrides || {});
}

const defaultPanels = [
    { id: 'amy', title: 'AMY COMMANDER', isOpen: true },
    { id: 'units', title: 'UNITS', isOpen: false },
    { id: 'alerts', title: 'ALERTS', isOpen: true },
    { id: 'game', title: 'GAME HUD', isOpen: false },
];

function clearDocListeners() {
    for (const key of Object.keys(_docListeners)) {
        _docListeners[key] = [];
    }
}

function clearEventBus() {
    vm.runInContext('EventBus._handlers.clear()', ctx);
}

// Helper to create a bar from defaults
function makeBar(panels, lmOverrides) {
    clearDocListeners();
    clearEventBus();
    const container = createMockElement('div');
    const pm = makeMockPanelManager(panels || defaultPanels);
    const lm = makeMockLayoutManager(lmOverrides);
    ctx.container = container;
    ctx.pm = pm;
    ctx.lm = lm;
    const bar = vm.runInContext('createCommandBar(container, pm, lm)', ctx);
    return { bar, container, pm, lm };
}

// ============================================================
// 1. createCommandBar and focusSaveInput are functions
// ============================================================

console.log('\n--- Exports ---');

(function testCreateCommandBarExists() {
    const fn = vm.runInContext('typeof createCommandBar', ctx);
    assert(fn === 'function', 'createCommandBar is a function');
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
    const { bar } = makeBar();
    assert(bar !== null && bar !== undefined, 'createCommandBar returns an element');
})();

(function testBarClassName() {
    const { bar } = makeBar();
    assert(bar.className === 'command-bar', 'bar has className "command-bar"');
})();

(function testBarAppendedToContainer() {
    const { container } = makeBar();
    assert(container.children.length === 1, 'bar is appended to container');
})();

(function testBarHasTwoChildren() {
    const { bar } = makeBar();
    assert(bar.children.length === 2, 'bar has 2 children (left + right), got ' + bar.children.length);
})();

(function testLeftChildClassName() {
    const { bar } = makeBar();
    assert(bar.children[0].className === 'command-bar-left', 'first child is command-bar-left');
})();

(function testRightChildClassName() {
    const { bar } = makeBar();
    assert(bar.children[1].className === 'command-bar-right', 'second child is command-bar-right');
})();

// ============================================================
// 3. Panel toggle buttons (left side)
// ============================================================

console.log('\n--- Panel toggle buttons ---');

(function testLeftHasFourButtons() {
    const { bar } = makeBar();
    const left = bar.children[0];
    assert(left.children.length === 4, 'left has 4 panel buttons for 4 panels, got ' + left.children.length);
})();

(function testPanelButtonLabels() {
    const { bar } = makeBar();
    const left = bar.children[0];
    const expected = ['AMY', 'UNITS', 'ALERTS', 'GAME'];
    for (let i = 0; i < 4; i++) {
        const btn = left.children[i];
        assert(btn.textContent === expected[i],
            'panel button ' + i + ' text is "' + expected[i] + '", got "' + btn.textContent + '"');
    }
})();

(function testPanelButtonClassName() {
    const { bar } = makeBar();
    const left = bar.children[0];
    for (let i = 0; i < 4; i++) {
        const btn = left.children[i];
        assert(btn.className === 'command-bar-btn', 'panel button ' + i + ' has className command-bar-btn');
    }
})();

(function testPanelButtonDataPanel() {
    const { bar } = makeBar();
    const left = bar.children[0];
    const expectedIds = ['amy', 'units', 'alerts', 'game'];
    for (let i = 0; i < 4; i++) {
        const btn = left.children[i];
        assert(btn.dataset.panel === expectedIds[i],
            'panel button ' + i + ' data-panel is "' + expectedIds[i] + '", got "' + btn.dataset.panel + '"');
    }
})();

(function testOpenPanelButtonHasActiveClass() {
    const { bar } = makeBar();
    const left = bar.children[0];
    // amy (0) is open, units (1) is closed, alerts (2) is open, game (3) is closed
    assert(left.children[0]._classList.has('active'), 'AMY button has active class (panel is open)');
    assert(!left.children[1]._classList.has('active'), 'UNITS button does NOT have active class');
    assert(left.children[2]._classList.has('active'), 'ALERTS button has active class (panel is open)');
    assert(!left.children[3]._classList.has('active'), 'GAME button does NOT have active class');
})();

(function testPanelButtonTitleIncludesShortcut() {
    const { bar } = makeBar();
    const left = bar.children[0];
    assert(left.children[0].title.includes('1'), 'AMY button title includes shortcut key "1"');
    assert(left.children[0].title.includes('AMY COMMANDER'), 'AMY button title includes panel title');
    assert(left.children[1].title.includes('2'), 'UNITS button title includes shortcut key "2"');
    assert(left.children[2].title.includes('3'), 'ALERTS button title includes shortcut key "3"');
    assert(left.children[3].title.includes('4'), 'GAME button title includes shortcut key "4"');
})();

(function testPanelButtonClickCallsToggle() {
    const { bar, pm } = makeBar();
    const left = bar.children[0];
    const unitsBtn = left.children[1]; // units, initially closed
    assert(!pm._openState['units'], 'units is initially closed');
    unitsBtn.click();
    assert(pm._openState['units'], 'clicking UNITS button toggles panel open');
})();

(function testPanelButtonClickTogglesClosed() {
    const { bar, pm } = makeBar();
    const left = bar.children[0];
    const amyBtn = left.children[0]; // amy, initially open
    assert(pm._openState['amy'], 'amy is initially open');
    amyBtn.click();
    assert(!pm._openState['amy'], 'clicking AMY button toggles panel closed');
})();

// ============================================================
// 4. Right side: layout dropdown + save wrap + help button
// ============================================================

console.log('\n--- Right side structure ---');

(function testRightHasThreeChildren() {
    const { bar } = makeBar();
    const right = bar.children[1];
    // layout-wrap, save-wrap, help button
    assert(right.children.length === 3, 'right has 3 children (layout-wrap + save-wrap + help), got ' + right.children.length);
})();

(function testLayoutWrapClassName() {
    const { bar } = makeBar();
    const right = bar.children[1];
    const layoutWrap = right.children[0];
    assert(layoutWrap.className === 'command-bar-layout', 'first right child is command-bar-layout');
})();

(function testSaveWrapClassName() {
    const { bar } = makeBar();
    const right = bar.children[1];
    const saveWrap = right.children[1];
    assert(saveWrap.className === 'command-bar-save-wrap', 'second right child is command-bar-save-wrap');
})();

(function testHelpButtonClassName() {
    const { bar } = makeBar();
    const right = bar.children[1];
    const helpBtn = right.children[2];
    assert(helpBtn.className === 'command-bar-btn', 'help button has className command-bar-btn');
    assert(helpBtn.textContent === '?', 'help button text is "?"');
    assert(helpBtn.dataset.action === 'help', 'help button data-action is "help"');
})();

// ============================================================
// 5. Layout dropdown trigger and visibility
// ============================================================

console.log('\n--- Layout dropdown ---');

(function testLayoutTriggerLabel() {
    const { bar } = makeBar();
    const right = bar.children[1];
    const layoutWrap = right.children[0];
    const trigger = layoutWrap.children[0];
    assert(trigger.textContent === 'LAYOUT: COMMANDER', 'layout trigger text is "LAYOUT: COMMANDER", got "' + trigger.textContent + '"');
})();

(function testLayoutDropdownStartsHidden() {
    const { bar } = makeBar();
    const right = bar.children[1];
    const layoutWrap = right.children[0];
    const dropdown = layoutWrap.children[1];
    assert(dropdown.hidden === true, 'layout dropdown starts hidden');
})();

(function testLayoutTriggerClickOpensDropdown() {
    const { bar } = makeBar();
    const right = bar.children[1];
    const layoutWrap = right.children[0];
    const trigger = layoutWrap.children[0];
    const dropdown = layoutWrap.children[1];
    trigger.click();
    assert(dropdown.hidden === false, 'clicking layout trigger opens dropdown');
})();

(function testLayoutTriggerClickTogglesDropdown() {
    const { bar } = makeBar();
    const right = bar.children[1];
    const layoutWrap = right.children[0];
    const trigger = layoutWrap.children[0];
    const dropdown = layoutWrap.children[1];
    trigger.click(); // open
    trigger.click(); // close
    assert(dropdown.hidden === true, 'clicking layout trigger again closes dropdown');
})();

(function testLayoutDropdownHasItems() {
    const { bar } = makeBar();
    const right = bar.children[1];
    const layoutWrap = right.children[0];
    const trigger = layoutWrap.children[0];
    const dropdown = layoutWrap.children[1];
    trigger.click(); // opens and rebuilds
    // 3 builtin + 1 user = 4 items
    assert(dropdown.children.length === 4, 'dropdown has 4 items (3 builtin + 1 user), got ' + dropdown.children.length);
})();

(function testLayoutDropdownItemLabels() {
    const { bar } = makeBar();
    const right = bar.children[1];
    const layoutWrap = right.children[0];
    const trigger = layoutWrap.children[0];
    const dropdown = layoutWrap.children[1];
    trigger.click();
    // Each row has a label span as first child
    const label0 = dropdown.children[0].children[0];
    assert(label0.textContent === 'COMMANDER', 'first dropdown item label is "COMMANDER", got "' + label0.textContent + '"');
})();

(function testLayoutDropdownActiveItem() {
    const { bar } = makeBar();
    const right = bar.children[1];
    const layoutWrap = right.children[0];
    const trigger = layoutWrap.children[0];
    const dropdown = layoutWrap.children[1];
    trigger.click();
    // currentName is 'commander', so first item should have 'active' class
    assert(dropdown.children[0]._classList.has('active'), 'current layout item has active class');
    assert(!dropdown.children[1]._classList.has('active'), 'non-current layout item does not have active class');
})();

(function testLayoutDropdownBuiltinTag() {
    const { bar } = makeBar();
    const right = bar.children[1];
    const layoutWrap = right.children[0];
    const trigger = layoutWrap.children[0];
    const dropdown = layoutWrap.children[1];
    trigger.click();
    // First item (commander, builtin=true) label should contain a tag child
    const label0 = dropdown.children[0].children[0];
    assert(label0.children.length === 1, 'builtin item label has 1 child (tag), got ' + label0.children.length);
    assert(label0.children[0].className === 'command-bar-dropdown-tag', 'builtin item has tag with correct className');
    assert(label0.children[0].textContent === 'BUILT-IN', 'builtin tag text is "BUILT-IN"');
})();

(function testLayoutDropdownUserItemHasDeleteButton() {
    const { bar } = makeBar();
    const right = bar.children[1];
    const layoutWrap = right.children[0];
    const trigger = layoutWrap.children[0];
    const dropdown = layoutWrap.children[1];
    trigger.click();
    // User layout is at index 3 (after 3 builtins)
    const userRow = dropdown.children[3];
    // User row has: label + delete button
    assert(userRow.children.length === 2, 'user item has 2 children (label + delete), got ' + userRow.children.length);
    const del = userRow.children[1];
    assert(del.className === 'command-bar-dropdown-delete', 'user item has delete button with correct className');
    assert(del.textContent === 'x', 'delete button text is "x"');
})();

(function testLayoutDropdownClickAppliesLayout() {
    const { bar, lm } = makeBar();
    const right = bar.children[1];
    const layoutWrap = right.children[0];
    const trigger = layoutWrap.children[0];
    const dropdown = layoutWrap.children[1];
    trigger.click();
    // Click on 'tactical' (index 1)
    dropdown.children[1].click();
    assert(lm._lastApplied === 'tactical', 'clicking tactical item calls layoutManager.apply("tactical")');
    assert(dropdown.hidden === true, 'clicking layout item hides dropdown');
})();

(function testLayoutDropdownClickUpdatesLabel() {
    const { bar, lm } = makeBar();
    const right = bar.children[1];
    const layoutWrap = right.children[0];
    const trigger = layoutWrap.children[0];
    const dropdown = layoutWrap.children[1];
    trigger.click();
    dropdown.children[1].click(); // apply 'tactical'
    assert(trigger.textContent === 'LAYOUT: TACTICAL', 'trigger label updates to "LAYOUT: TACTICAL", got "' + trigger.textContent + '"');
})();

(function testLayoutDropdownDeleteCallsDelete() {
    const { bar, lm } = makeBar();
    const right = bar.children[1];
    const layoutWrap = right.children[0];
    const trigger = layoutWrap.children[0];
    const dropdown = layoutWrap.children[1];
    trigger.click();
    const userRow = dropdown.children[3];
    const delBtn = userRow.children[1];
    delBtn.click();
    assert(lm._lastDeleted === 'my-layout', 'delete button calls layoutManager.delete("my-layout")');
})();

(function testClickOutsideClosesDropdown() {
    const { bar } = makeBar();
    const right = bar.children[1];
    const layoutWrap = right.children[0];
    const trigger = layoutWrap.children[0];
    const dropdown = layoutWrap.children[1];
    trigger.click();
    assert(dropdown.hidden === false, 'dropdown is open');
    // Simulate click outside
    const outsideEl = createMockElement('div');
    const clickHandlers = _docListeners['click'] || [];
    for (const handler of clickHandlers) {
        handler({ target: outsideEl });
    }
    assert(dropdown.hidden === true, 'click outside closes layout dropdown');
})();

// ============================================================
// 6. Save button and save input
// ============================================================

console.log('\n--- Save input ---');

(function testSaveButtonExists() {
    const { bar } = makeBar();
    const right = bar.children[1];
    const saveWrap = right.children[1];
    const saveBtn = saveWrap.children[0];
    assert(saveBtn.className === 'command-bar-btn command-bar-save-btn', 'save button has correct className');
    assert(saveBtn.textContent === 'SAVE', 'save button text is "SAVE"');
})();

(function testSaveInputStartsHidden() {
    const { bar } = makeBar();
    const right = bar.children[1];
    const saveWrap = right.children[1];
    const saveInput = saveWrap.children[1];
    assert(saveInput.hidden === true, 'save input starts hidden');
})();

(function testSaveInputProperties() {
    const { bar } = makeBar();
    const right = bar.children[1];
    const saveWrap = right.children[1];
    const saveInput = saveWrap.children[1];
    assert(saveInput.type === 'text', 'save input type is "text"');
    assert(saveInput.placeholder === 'Layout name...', 'save input has correct placeholder');
    assert(saveInput.maxLength === 24, 'save input maxLength is 24');
})();

(function testSaveButtonClickShowsInput() {
    const { bar } = makeBar();
    const right = bar.children[1];
    const saveWrap = right.children[1];
    const saveBtn = saveWrap.children[0];
    const saveInput = saveWrap.children[1];
    saveBtn.click();
    assert(saveInput.hidden === false, 'clicking SAVE shows the input');
    assert(saveInput._focusCalled === true, 'clicking SAVE focuses the input');
})();

(function testSaveButtonClickTogglesInput() {
    const { bar } = makeBar();
    const right = bar.children[1];
    const saveWrap = right.children[1];
    const saveBtn = saveWrap.children[0];
    const saveInput = saveWrap.children[1];
    saveBtn.click(); // show
    saveBtn.click(); // hide
    assert(saveInput.hidden === true, 'clicking SAVE again hides the input');
})();

(function testSaveInputEnterKeySaves() {
    const { bar, lm } = makeBar();
    const right = bar.children[1];
    const saveWrap = right.children[1];
    const saveInput = saveWrap.children[1];
    saveInput.hidden = false;
    saveInput.value = 'test-layout';
    const handlers = saveInput._eventListeners['keydown'];
    assert(handlers && handlers.length > 0, 'save input has keydown handler');
    if (handlers && handlers.length > 0) {
        handlers[0]({ key: 'Enter', stopPropagation() {} });
        assert(lm._lastSaved === 'test-layout', 'Enter key saves layout with correct name');
        assert(saveInput.hidden === true, 'Enter key hides save input');
    }
})();

(function testSaveInputEnterEmptyDoesNotSave() {
    const { bar, lm } = makeBar();
    const right = bar.children[1];
    const saveWrap = right.children[1];
    const saveInput = saveWrap.children[1];
    saveInput.hidden = false;
    saveInput.value = '   ';
    const handlers = saveInput._eventListeners['keydown'];
    if (handlers && handlers.length > 0) {
        handlers[0]({ key: 'Enter', stopPropagation() {} });
        assert(lm._lastSaved === null, 'Enter with whitespace-only name does not save');
    }
})();

(function testSaveInputEscapeHides() {
    const { bar } = makeBar();
    const right = bar.children[1];
    const saveWrap = right.children[1];
    const saveInput = saveWrap.children[1];
    saveInput.hidden = false;
    const handlers = saveInput._eventListeners['keydown'];
    if (handlers && handlers.length > 0) {
        handlers[0]({ key: 'Escape', stopPropagation() {} });
        assert(saveInput.hidden === true, 'Escape key hides save input');
    }
})();

(function testSaveInputStopsPropagation() {
    const { bar } = makeBar();
    const right = bar.children[1];
    const saveWrap = right.children[1];
    const saveInput = saveWrap.children[1];
    saveInput.hidden = false;
    saveInput.value = 'x';
    const handlers = saveInput._eventListeners['keydown'];
    let propagationStopped = false;
    if (handlers && handlers.length > 0) {
        handlers[0]({ key: 'a', stopPropagation() { propagationStopped = true; } });
        assert(propagationStopped, 'keydown handler calls stopPropagation to prevent global shortcuts');
    }
})();

(function testSaveInputEnterEmitsToast() {
    const { bar, lm } = makeBar();
    const right = bar.children[1];
    const saveWrap = right.children[1];
    const saveInput = saveWrap.children[1];
    saveInput.hidden = false;
    saveInput.value = 'my-new-layout';

    // Listen for toast:show event
    let toastData = null;
    vm.runInContext('EventBus.on("toast:show", function(d) { _toastData = d; })', ctx);
    ctx._toastData = null;

    const handlers = saveInput._eventListeners['keydown'];
    if (handlers && handlers.length > 0) {
        handlers[0]({ key: 'Enter', stopPropagation() {} });
        toastData = ctx._toastData;
        assert(toastData !== null, 'save emits toast:show event');
        assert(toastData.message.includes('my-new-layout'), 'toast message includes layout name');
        assert(toastData.type === 'info', 'toast type is "info"');
    }
})();

// ============================================================
// 7. Help button
// ============================================================

console.log('\n--- Help button ---');

(function testHelpButtonTogglesOverlay() {
    const { bar } = makeBar();
    const right = bar.children[1];
    const helpBtn = right.children[2];
    _helpOverlay.hidden = true;
    helpBtn.click();
    assert(_helpOverlay.hidden === false, 'clicking help button shows overlay');
    helpBtn.click();
    assert(_helpOverlay.hidden === true, 'clicking help button again hides overlay');
})();

(function testHelpButtonTitle() {
    const { bar } = makeBar();
    const right = bar.children[1];
    const helpBtn = right.children[2];
    assert(helpBtn.title === 'Show keyboard shortcuts', 'help button has correct title');
})();

// ============================================================
// 8. EventBus panel:opened/panel:closed sync
// ============================================================

console.log('\n--- EventBus panel sync ---');

(function testPanelOpenedAddsActiveClass() {
    const { bar } = makeBar();
    const left = bar.children[0];
    const unitsBtn = left.children[1]; // units, initially closed
    assert(!unitsBtn._classList.has('active'), 'UNITS button starts without active');
    vm.runInContext('EventBus.emit("panel:opened", { id: "units" })', ctx);
    assert(unitsBtn._classList.has('active'), 'panel:opened adds active class to UNITS button');
})();

(function testPanelClosedRemovesActiveClass() {
    const { bar } = makeBar();
    const left = bar.children[0];
    const amyBtn = left.children[0]; // amy, initially open
    assert(amyBtn._classList.has('active'), 'AMY button starts with active');
    vm.runInContext('EventBus.emit("panel:closed", { id: "amy" })', ctx);
    assert(!amyBtn._classList.has('active'), 'panel:closed removes active class from AMY button');
})();

(function testLayoutChangedSyncsAllButtons() {
    const { bar, pm } = makeBar();
    const left = bar.children[0];
    // Change open state externally
    pm._openState['amy'] = false;
    pm._openState['units'] = true;
    vm.runInContext('EventBus.emit("layout:changed")', ctx);
    assert(!left.children[0]._classList.has('active'), 'layout:changed syncs AMY button to closed');
    assert(left.children[1]._classList.has('active'), 'layout:changed syncs UNITS button to open');
})();

(function testPanelOpenedIgnoresUnknownId() {
    makeBar();
    let threw = false;
    try {
        vm.runInContext('EventBus.emit("panel:opened", { id: "nonexistent" })', ctx);
    } catch (e) {
        threw = true;
    }
    assert(!threw, 'panel:opened with unknown id does not throw');
})();

(function testPanelClosedIgnoresUnknownId() {
    makeBar();
    let threw = false;
    try {
        vm.runInContext('EventBus.emit("panel:closed", { id: "nonexistent" })', ctx);
    } catch (e) {
        threw = true;
    }
    assert(!threw, 'panel:closed with unknown id does not throw');
})();

// ============================================================
// 9. Layout label update on layout:changed
// ============================================================

console.log('\n--- Layout label update ---');

(function testLayoutChangedUpdatesLabel() {
    const { bar, lm } = makeBar();
    const right = bar.children[1];
    const layoutWrap = right.children[0];
    const trigger = layoutWrap.children[0];
    assert(trigger.textContent === 'LAYOUT: COMMANDER', 'trigger starts as COMMANDER');
    lm.currentName = 'tactical';
    vm.runInContext('EventBus.emit("layout:changed")', ctx);
    assert(trigger.textContent === 'LAYOUT: TACTICAL', 'layout:changed updates trigger label to TACTICAL');
})();

// ============================================================
// 10. Helper functions
// ============================================================

console.log('\n--- Helper functions ---');

(function testShortLabelMultiWord() {
    const result = vm.runInContext('_shortLabel("AMY COMMANDER")', ctx);
    assert(result === 'AMY', '_shortLabel("AMY COMMANDER") returns "AMY"');
})();

(function testShortLabelSingleWord() {
    const result = vm.runInContext('_shortLabel("UNITS")', ctx);
    assert(result === 'UNITS', '_shortLabel("UNITS") returns "UNITS"');
})();

(function testShortLabelGameHud() {
    const result = vm.runInContext('_shortLabel("GAME HUD")', ctx);
    assert(result === 'GAME', '_shortLabel("GAME HUD") returns "GAME"');
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

(function testShortLabelLowercase() {
    const result = vm.runInContext('_shortLabel("hello world")', ctx);
    assert(result === 'HELLO', '_shortLabel("hello world") returns "HELLO" (uppercased)');
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
// 11. focusSaveInput export function
// ============================================================

console.log('\n--- focusSaveInput ---');

(function testFocusSaveInputShowsAndFocuses() {
    const { bar } = makeBar();
    const right = bar.children[1];
    const saveWrap = right.children[1];
    const saveInput = saveWrap.children[1];
    saveInput.value = 'old-value';
    saveInput._focusCalled = false;

    ctx._bar = bar;
    vm.runInContext('focusSaveInput(_bar)', ctx);

    assert(saveInput.hidden === false, 'focusSaveInput shows the input');
    assert(saveInput.value === '', 'focusSaveInput clears the value');
    assert(saveInput._focusCalled === true, 'focusSaveInput calls focus()');
})();

(function testFocusSaveInputNoOpIfMissing() {
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
// 12. Edge cases
// ============================================================

console.log('\n--- Edge cases ---');

(function testEmptyPanelManager() {
    let threw = false;
    try {
        makeBar([]);
    } catch (e) {
        threw = true;
    }
    assert(!threw, 'createCommandBar works with empty panel manager (no panels)');
})();

(function testEmptyPanelManagerLeftSide() {
    const { bar } = makeBar([]);
    const left = bar.children[0];
    assert(left.children.length === 0, 'left side has 0 buttons when no panels');
})();

(function testLayoutManagerNullCurrentName() {
    const { bar } = makeBar(defaultPanels, { currentName: null });
    const right = bar.children[1];
    const layoutWrap = right.children[0];
    const trigger = layoutWrap.children[0];
    assert(trigger.textContent === 'LAYOUT: DEFAULT', 'null currentName shows "LAYOUT: DEFAULT"');
})();

(function testMultipleCreateCommandBarCalls() {
    clearDocListeners();
    clearEventBus();
    const container = createMockElement('div');
    const pm = makeMockPanelManager(defaultPanels);
    const lm = makeMockLayoutManager();
    ctx.container = container;
    ctx.pm = pm;
    ctx.lm = lm;
    let threw = false;
    try {
        vm.runInContext('createCommandBar(container, pm, lm)', ctx);
        vm.runInContext('createCommandBar(container, pm, lm)', ctx);
    } catch (e) {
        threw = true;
    }
    assert(!threw, 'calling createCommandBar multiple times does not throw');
    assert(container.children.length === 2, 'each call appends a bar to container');
})();

(function testSinglePanelWorks() {
    const { bar } = makeBar([{ id: 'solo', title: 'SOLO PANEL', isOpen: true }]);
    const left = bar.children[0];
    assert(left.children.length === 1, 'left has 1 button for 1 panel');
    assert(left.children[0].textContent === 'SOLO', 'single panel button text is "SOLO"');
    assert(left.children[0]._classList.has('active'), 'single open panel button has active class');
})();

(function testLayoutDropdownRebuildOnReopen() {
    const { bar, lm } = makeBar();
    const right = bar.children[1];
    const layoutWrap = right.children[0];
    const trigger = layoutWrap.children[0];
    const dropdown = layoutWrap.children[1];
    // Open dropdown
    trigger.click();
    const countBefore = dropdown.children.length;
    // Close and reopen
    trigger.click();
    trigger.click();
    const countAfter = dropdown.children.length;
    assert(countBefore === countAfter, 'dropdown rebuilds correctly on reopen (count: ' + countBefore + ' -> ' + countAfter + ')');
})();

(function testSaveInputClearsOnShow() {
    const { bar } = makeBar();
    const right = bar.children[1];
    const saveWrap = right.children[1];
    const saveBtn = saveWrap.children[0];
    const saveInput = saveWrap.children[1];
    saveInput.value = 'leftover';
    saveBtn.click(); // show
    assert(saveInput.value === '', 'save input value is cleared when shown');
})();

(function testPanelButtonTitleForUnknownPanelKey() {
    const { bar } = makeBar([{ id: 'custom', title: 'CUSTOM PANEL', isOpen: false }]);
    const left = bar.children[0];
    const btn = left.children[0];
    // _panelKey('custom') returns '', so title should include Toggle CUSTOM PANEL ()
    assert(btn.title.includes('Toggle'), 'custom panel button title includes "Toggle"');
    assert(btn.title.includes('CUSTOM PANEL'), 'custom panel button title includes panel title');
})();

(function testLayoutDropdownSyncsPanelButtonsAfterApply() {
    const { bar, pm, lm } = makeBar();
    const left = bar.children[0];
    const right = bar.children[1];
    const layoutWrap = right.children[0];
    const trigger = layoutWrap.children[0];
    const dropdown = layoutWrap.children[1];

    // Externally change panel states as a layout apply would
    pm._openState['amy'] = false;
    pm._openState['units'] = true;

    trigger.click(); // open dropdown
    dropdown.children[1].click(); // click 'tactical' which calls _syncPanelButtons

    // After apply, _syncPanelButtons is called so buttons should match new state
    assert(!left.children[0]._classList.has('active'), 'after layout apply, AMY button synced to closed');
    assert(left.children[1]._classList.has('active'), 'after layout apply, UNITS button synced to open');
})();

// ============================================================
// Summary
// ============================================================

console.log('\n' + '='.repeat(40));
console.log(`Results: ${passed} passed, ${failed} failed`);
console.log('='.repeat(40));
process.exit(failed > 0 ? 1 : 0);
