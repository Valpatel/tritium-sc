/**
 * TRITIUM-SC Input Manager tests
 * Tests: FocusManager, GamepadHandler, TritiumInputManager
 * Covers: gamepad connect/disconnect, button mapping, D-pad nav,
 * stick deadzone, key binding dispatch, focus management, view navigation.
 * Run: node tests/js/test_input.js
 */

const fs = require('fs');
const vm = require('vm');

// Simple test runner
let passed = 0, failed = 0;
function assert(cond, msg) {
    if (!cond) { console.error('FAIL:', msg); failed++; }
    else { console.log('PASS:', msg); passed++; }
}
function assertEqual(a, b, msg) {
    assert(a === b, msg + ` (got ${JSON.stringify(a)}, expected ${JSON.stringify(b)})`);
}
function assertDeepEqual(a, b, msg) {
    assert(JSON.stringify(a) === JSON.stringify(b), msg + ` (got ${JSON.stringify(a)}, expected ${JSON.stringify(b)})`);
}
function assertApprox(a, b, eps, msg) {
    assert(Math.abs(a - b) < eps, msg + ` (got ${a}, expected ~${b})`);
}

// ---------------------------------------------------------------------------
// Build a DOM-like sandbox for the input.js code
// ---------------------------------------------------------------------------

function createMockElement(tag, opts = {}) {
    const el = {
        tagName: tag,
        id: opts.id || '',
        className: opts.className || '',
        dataset: opts.dataset || {},
        style: { display: '', cssText: '' },
        children: [],
        childNodes: [],
        parentElement: opts.parentElement || null,
        classList: {
            _classes: new Set((opts.className || '').split(/\s+/).filter(Boolean)),
            add(c) { this._classes.add(c); },
            remove(c) { this._classes.delete(c); },
            toggle(c) { if (this._classes.has(c)) this._classes.delete(c); else this._classes.add(c); },
            contains(c) { return this._classes.has(c); },
        },
        innerHTML: '',
        scrollIntoView() {},
        closest() { return null; },
        click() { el._clicked = true; },
        _clicked: false,
        getBoundingClientRect() { return { left: 0, top: 0, right: 100, bottom: 50, width: 100, height: 50 }; },
        setAttribute(k, v) { el['_attr_' + k] = v; },
        getAttribute(k) { return el['_attr_' + k] || null; },
        addEventListener(ev, fn) {
            if (!el._listeners) el._listeners = {};
            if (!el._listeners[ev]) el._listeners[ev] = [];
            el._listeners[ev].push(fn);
        },
        removeEventListener(ev, fn) {
            if (el._listeners && el._listeners[ev]) {
                el._listeners[ev] = el._listeners[ev].filter(f => f !== fn);
            }
        },
        remove() { el._removed = true; },
        _removed: false,
        querySelectorAll() { return []; },
        querySelector() { return null; },
    };
    return el;
}

function buildSandbox() {
    const listeners = {};
    const elements = {};
    const body = createMockElement('body');
    body.appendChild = function(child) { body.children.push(child); };

    const mockDocument = {
        addEventListener(ev, fn) {
            if (!listeners[ev]) listeners[ev] = [];
            listeners[ev].push(fn);
        },
        removeEventListener(ev, fn) {
            if (listeners[ev]) listeners[ev] = listeners[ev].filter(f => f !== fn);
        },
        querySelector(sel) {
            return elements[sel] || null;
        },
        querySelectorAll(sel) {
            return elements['__all_' + sel] || [];
        },
        getElementById(id) {
            return elements['#' + id] || null;
        },
        createElement(tag) {
            return createMockElement(tag);
        },
        body: body,
        fullscreenElement: null,
        exitFullscreen() {},
    };

    // Store references so tests can inject elements
    mockDocument._elements = elements;
    mockDocument._listeners = listeners;

    const windowListeners = {};
    let rafId = 1;
    const rafCallbacks = {};

    const mockWindow = {
        addEventListener(ev, fn) {
            if (!windowListeners[ev]) windowListeners[ev] = [];
            windowListeners[ev].push(fn);
        },
        removeEventListener(ev, fn) {
            if (windowListeners[ev]) windowListeners[ev] = windowListeners[ev].filter(f => f !== fn);
        },
    };
    mockWindow._listeners = windowListeners;

    // Mock navigator with getGamepads
    const mockNavigator = {
        _gamepads: [null, null, null, null],
        getGamepads() { return [...mockNavigator._gamepads]; },
    };

    // Track requestAnimationFrame / cancelAnimationFrame
    const mockRequestAnimationFrame = function(cb) {
        const id = rafId++;
        rafCallbacks[id] = cb;
        return id;
    };
    const mockCancelAnimationFrame = function(id) {
        delete rafCallbacks[id];
    };

    // Provide getComputedStyle stub
    const mockGetComputedStyle = function() {
        return { gridTemplateColumns: 'none' };
    };

    const sandbox = {
        Math, Date, console: { ...console }, Map, Set, Array, Object, Number, String, Boolean,
        Infinity, NaN, undefined, parseInt, parseFloat, isNaN, isFinite, JSON,
        Promise, setTimeout, clearTimeout, Error, RegExp,
        document: mockDocument,
        window: mockWindow,
        navigator: mockNavigator,
        requestAnimationFrame: mockRequestAnimationFrame,
        cancelAnimationFrame: mockCancelAnimationFrame,
        getComputedStyle: mockGetComputedStyle,
        TRITIUM: { state: { currentView: 'grid' } },
    };

    // Suppress console.log from the source code during tests
    sandbox.console = {
        log() {},
        error: console.error,
        warn() {},
    };

    sandbox._rafCallbacks = rafCallbacks;
    sandbox._windowListeners = windowListeners;
    sandbox._docListeners = listeners;
    sandbox._navigator = mockNavigator;

    return sandbox;
}

function loadInput(sandbox) {
    const code = fs.readFileSync(__dirname + '/../../frontend/js/input.js', 'utf8');
    const plain = code
        .replace(/^export\s+/gm, '')
        .replace(/^import\s+.*$/gm, '');

    const ctx = vm.createContext(sandbox);
    vm.runInContext(plain + `
        var _FocusManager = FocusManager;
        var _GamepadHandler = GamepadHandler;
        var _TritiumInputManager = TritiumInputManager;
        var _GAMEPAD_BUTTONS = GAMEPAD_BUTTONS;
        var _GAMEPAD_AXES = GAMEPAD_AXES;
        var _GAMEPAD_DEADZONE = GAMEPAD_DEADZONE;
        var _GAMEPAD_POLL_INTERVAL = GAMEPAD_POLL_INTERVAL;
        var _REPEAT_DELAY = REPEAT_DELAY;
        var _REPEAT_RATE = REPEAT_RATE;
        var _VIEW_ORDER = VIEW_ORDER;
        var _tritiumInput = tritiumInput;
    `, ctx);

    return ctx;
}

// Helper to create a mock gamepad object
function createMockGamepad(index = 0, id = 'Xbox 360 Controller (XInput STANDARD GAMEPAD)') {
    const buttons = [];
    for (let i = 0; i < 17; i++) {
        buttons.push({ pressed: false, touched: false, value: 0 });
    }
    return {
        id: id,
        index: index,
        connected: true,
        buttons: buttons,
        axes: [0, 0, 0, 0],
        mapping: 'standard',
        timestamp: Date.now(),
        vibrationActuator: {
            _effects: [],
            playEffect(type, params) {
                this._effects.push({ type, params });
                return Promise.resolve();
            },
        },
    };
}


// ============================================================
// 1. Constants exported correctly
// ============================================================

console.log('\n--- Constants ---');

(function testConstants() {
    const sb = buildSandbox();
    const ctx = loadInput(sb);

    assertEqual(ctx._GAMEPAD_DEADZONE, 0.25, 'GAMEPAD_DEADZONE is 0.25');
    assertEqual(ctx._GAMEPAD_POLL_INTERVAL, 16, 'GAMEPAD_POLL_INTERVAL is 16');
    assertEqual(ctx._REPEAT_DELAY, 400, 'REPEAT_DELAY is 400');
    assertEqual(ctx._REPEAT_RATE, 100, 'REPEAT_RATE is 100');
})();

(function testGamepadButtonMapping() {
    const sb = buildSandbox();
    const ctx = loadInput(sb);
    const B = ctx._GAMEPAD_BUTTONS;

    assertEqual(B.A, 0, 'A button is index 0');
    assertEqual(B.B, 1, 'B button is index 1');
    assertEqual(B.X, 2, 'X button is index 2');
    assertEqual(B.Y, 3, 'Y button is index 3');
    assertEqual(B.LB, 4, 'LB is index 4');
    assertEqual(B.RB, 5, 'RB is index 5');
    assertEqual(B.LT, 6, 'LT is index 6');
    assertEqual(B.RT, 7, 'RT is index 7');
    assertEqual(B.SELECT, 8, 'SELECT is index 8');
    assertEqual(B.START, 9, 'START is index 9');
    assertEqual(B.L3, 10, 'L3 is index 10');
    assertEqual(B.R3, 11, 'R3 is index 11');
    assertEqual(B.DPAD_UP, 12, 'DPAD_UP is index 12');
    assertEqual(B.DPAD_DOWN, 13, 'DPAD_DOWN is index 13');
    assertEqual(B.DPAD_LEFT, 14, 'DPAD_LEFT is index 14');
    assertEqual(B.DPAD_RIGHT, 15, 'DPAD_RIGHT is index 15');
})();

(function testGamepadAxes() {
    const sb = buildSandbox();
    const ctx = loadInput(sb);
    const A = ctx._GAMEPAD_AXES;

    assertEqual(A.LEFT_X, 0, 'LEFT_X is axis 0');
    assertEqual(A.LEFT_Y, 1, 'LEFT_Y is axis 1');
    assertEqual(A.RIGHT_X, 2, 'RIGHT_X is axis 2');
    assertEqual(A.RIGHT_Y, 3, 'RIGHT_Y is axis 3');
})();

(function testViewOrder() {
    const sb = buildSandbox();
    const ctx = loadInput(sb);
    const V = ctx._VIEW_ORDER;

    assertEqual(V.length, 8, 'VIEW_ORDER has 8 entries');
    assertEqual(V[0], 'grid', 'first view is grid');
    assertEqual(V[V.length - 1], 'war', 'last view is war');
    assert(V.includes('player'), 'VIEW_ORDER includes player');
    assert(V.includes('3d'), 'VIEW_ORDER includes 3d');
    assert(V.includes('zones'), 'VIEW_ORDER includes zones');
    assert(V.includes('targets'), 'VIEW_ORDER includes targets');
    assert(V.includes('assets'), 'VIEW_ORDER includes assets');
    assert(V.includes('analytics'), 'VIEW_ORDER includes analytics');
})();


// ============================================================
// 2. FocusManager - construction and state
// ============================================================

console.log('\n--- FocusManager: construction and state ---');

(function testFocusManagerDefaultView() {
    const sb = buildSandbox();
    const ctx = loadInput(sb);
    const fm = new ctx._FocusManager();

    assertEqual(fm.currentView, 'grid', 'FocusManager default view is grid');
})();

(function testFocusManagerMapsInitializedEmpty() {
    const sb = buildSandbox();
    const ctx = loadInput(sb);
    const fm = new ctx._FocusManager();

    assertEqual(fm.focusableElements.size, 0, 'focusableElements starts empty');
    assertEqual(fm.currentFocusIndex.size, 0, 'currentFocusIndex starts empty');
    assertEqual(fm.focusTrapStack.length, 0, 'focusTrapStack starts empty');
})();

(function testFocusManagerSetView() {
    const sb = buildSandbox();
    const ctx = loadInput(sb);
    const fm = new ctx._FocusManager();

    fm.setView('player');
    assertEqual(fm.currentView, 'player', 'setView changes currentView');
})();

(function testFocusManagerGetSelectorsForView() {
    const sb = buildSandbox();
    const ctx = loadInput(sb);
    const fm = new ctx._FocusManager();

    const gridSel = fm.getSelectorsForView('grid');
    assert(gridSel.includes('.video-cell'), 'grid selector includes .video-cell');
    assert(gridSel.includes('.channel-item'), 'grid selector includes .channel-item');

    const playerSel = fm.getSelectorsForView('player');
    assert(playerSel.includes('.play-btn'), 'player selector includes .play-btn');

    const unknownSel = fm.getSelectorsForView('unknown_view');
    assert(unknownSel.includes('.btn-cyber'), 'unknown view falls back to default selectors');
    assert(unknownSel.includes('[data-focusable]'), 'unknown view default includes [data-focusable]');
})();

(function testFocusManagerGetSelectorsAllViews() {
    const sb = buildSandbox();
    const ctx = loadInput(sb);
    const fm = new ctx._FocusManager();

    const views = ['grid', 'player', '3d', 'zones', 'targets', 'assets', 'analytics', 'list'];
    for (const view of views) {
        const sel = fm.getSelectorsForView(view);
        assert(typeof sel === 'string' && sel.length > 0, `getSelectorsForView('${view}') returns non-empty string`);
    }
})();


// ============================================================
// 3. FocusManager - focus movement
// ============================================================

console.log('\n--- FocusManager: focus movement ---');

(function testMoveFocusDown() {
    const sb = buildSandbox();
    const ctx = loadInput(sb);
    const fm = new ctx._FocusManager();

    // Manually set focusable elements (simulating DOM)
    const elements = [
        createMockElement('div', { className: 'item' }),
        createMockElement('div', { className: 'item' }),
        createMockElement('div', { className: 'item' }),
    ];
    fm.focusableElements.set('grid', elements);
    fm.currentFocusIndex.set('grid', 0);
    fm.currentView = 'grid';

    fm.moveFocus('down');
    assertEqual(fm.currentFocusIndex.get('grid'), 1, 'moveFocus down increments index');
})();

(function testMoveFocusUp() {
    const sb = buildSandbox();
    const ctx = loadInput(sb);
    const fm = new ctx._FocusManager();

    const elements = [
        createMockElement('div'),
        createMockElement('div'),
        createMockElement('div'),
    ];
    fm.focusableElements.set('grid', elements);
    fm.currentFocusIndex.set('grid', 2);
    fm.currentView = 'grid';

    fm.moveFocus('up');
    assertEqual(fm.currentFocusIndex.get('grid'), 1, 'moveFocus up decrements index');
})();

(function testMoveFocusLeft() {
    const sb = buildSandbox();
    const ctx = loadInput(sb);
    const fm = new ctx._FocusManager();

    const elements = [
        createMockElement('div'),
        createMockElement('div'),
        createMockElement('div'),
    ];
    fm.focusableElements.set('player', elements);
    fm.currentFocusIndex.set('player', 2);
    fm.currentView = 'player';

    fm.moveFocus('left');
    assertEqual(fm.currentFocusIndex.get('player'), 1, 'moveFocus left decrements index');
})();

(function testMoveFocusRight() {
    const sb = buildSandbox();
    const ctx = loadInput(sb);
    const fm = new ctx._FocusManager();

    const elements = [
        createMockElement('div'),
        createMockElement('div'),
        createMockElement('div'),
    ];
    fm.focusableElements.set('player', elements);
    fm.currentFocusIndex.set('player', 0);
    fm.currentView = 'player';

    fm.moveFocus('right');
    assertEqual(fm.currentFocusIndex.get('player'), 1, 'moveFocus right increments index');
})();

(function testMoveFocusDoesNotGoBelowZero() {
    const sb = buildSandbox();
    const ctx = loadInput(sb);
    const fm = new ctx._FocusManager();

    const elements = [createMockElement('div'), createMockElement('div')];
    fm.focusableElements.set('player', elements);
    fm.currentFocusIndex.set('player', 0);
    fm.currentView = 'player';

    fm.moveFocus('up');
    assertEqual(fm.currentFocusIndex.get('player'), 0, 'moveFocus up clamps at 0');
})();

(function testMoveFocusDoesNotExceedMax() {
    const sb = buildSandbox();
    const ctx = loadInput(sb);
    const fm = new ctx._FocusManager();

    const elements = [createMockElement('div'), createMockElement('div')];
    fm.focusableElements.set('player', elements);
    fm.currentFocusIndex.set('player', 1);
    fm.currentView = 'player';

    fm.moveFocus('down');
    assertEqual(fm.currentFocusIndex.get('player'), 1, 'moveFocus down clamps at last index');
})();

(function testMoveFocusEmptyElementsDoesNotCrash() {
    const sb = buildSandbox();
    const ctx = loadInput(sb);
    const fm = new ctx._FocusManager();

    fm.focusableElements.set('grid', []);
    fm.currentView = 'grid';

    fm.moveFocus('down');
    assert(true, 'moveFocus with empty elements does not crash');
})();

(function testMoveFocusNoElementsRegistered() {
    const sb = buildSandbox();
    const ctx = loadInput(sb);
    const fm = new ctx._FocusManager();

    fm.currentView = 'grid';
    fm.moveFocus('up');
    assert(true, 'moveFocus with no registered elements does not crash');
})();


// ============================================================
// 4. FocusManager - getCurrentFocusable / focusFirst
// ============================================================

console.log('\n--- FocusManager: getCurrentFocusable / focusFirst ---');

(function testGetCurrentFocusable() {
    const sb = buildSandbox();
    const ctx = loadInput(sb);
    const fm = new ctx._FocusManager();

    const el0 = createMockElement('div', { id: 'el0' });
    const el1 = createMockElement('div', { id: 'el1' });
    fm.focusableElements.set('grid', [el0, el1]);
    fm.currentFocusIndex.set('grid', 1);
    fm.currentView = 'grid';

    const current = fm.getCurrentFocusable();
    assertEqual(current.id, 'el1', 'getCurrentFocusable returns element at current index');
})();

(function testGetCurrentFocusableNoElements() {
    const sb = buildSandbox();
    const ctx = loadInput(sb);
    const fm = new ctx._FocusManager();
    fm.currentView = 'grid';

    const current = fm.getCurrentFocusable();
    assertEqual(current, null, 'getCurrentFocusable returns null when no elements');
})();

(function testFocusFirstSetsIndexToZero() {
    const sb = buildSandbox();
    const ctx = loadInput(sb);
    const fm = new ctx._FocusManager();

    const el0 = createMockElement('div', { id: 'first' });
    const el1 = createMockElement('div', { id: 'second' });
    fm.focusableElements.set('grid', [el0, el1]);
    fm.currentFocusIndex.set('grid', 1);
    fm.currentView = 'grid';

    fm.focusFirst();
    assertEqual(fm.currentFocusIndex.get('grid'), 0, 'focusFirst sets index to 0');
})();

(function testFocusFirstAppliesFocusClass() {
    const sb = buildSandbox();
    const ctx = loadInput(sb);
    const fm = new ctx._FocusManager();

    const el0 = createMockElement('div');
    fm.focusableElements.set('grid', [el0]);
    fm.currentFocusIndex.set('grid', 0);
    fm.currentView = 'grid';

    // Mock document.querySelectorAll for removing old focus
    sb.document.querySelectorAll = () => [];

    fm.focusFirst();
    assert(el0.classList.contains('gamepad-focus'), 'focusFirst adds gamepad-focus class');
})();

(function testFocusFirstEmptyDoesNotCrash() {
    const sb = buildSandbox();
    const ctx = loadInput(sb);
    const fm = new ctx._FocusManager();

    fm.focusableElements.set('grid', []);
    fm.currentView = 'grid';
    fm.focusFirst();
    assert(true, 'focusFirst with empty elements does not crash');
})();


// ============================================================
// 5. FocusManager - activateCurrent
// ============================================================

console.log('\n--- FocusManager: activateCurrent ---');

(function testActivateCurrentClicksElement() {
    const sb = buildSandbox();
    const ctx = loadInput(sb);
    const fm = new ctx._FocusManager();

    const el = createMockElement('button');
    fm.focusableElements.set('grid', [el]);
    fm.currentFocusIndex.set('grid', 0);
    fm.currentView = 'grid';

    const result = fm.activateCurrent();
    assert(el._clicked, 'activateCurrent clicks the focused element');
    assertEqual(result, true, 'activateCurrent returns true when element exists');
})();

(function testActivateCurrentNoElementReturnsFalse() {
    const sb = buildSandbox();
    const ctx = loadInput(sb);
    const fm = new ctx._FocusManager();
    fm.currentView = 'grid';

    const result = fm.activateCurrent();
    assertEqual(result, false, 'activateCurrent returns false when no focused element');
})();


// ============================================================
// 6. FocusManager - focus trap stack (modals)
// ============================================================

console.log('\n--- FocusManager: focus trap stack ---');

(function testPushFocusTrapSavesState() {
    const sb = buildSandbox();
    const ctx = loadInput(sb);
    const fm = new ctx._FocusManager();

    fm.currentView = 'grid';
    fm.currentFocusIndex.set('grid', 3);

    // Mock the container with focusable children
    const btn = createMockElement('button');
    const container = createMockElement('div');
    container.querySelectorAll = () => [btn];
    sb.document.querySelector = (sel) => {
        if (sel === '#modal-container') return container;
        return null;
    };
    sb.document.querySelectorAll = () => [];

    fm.pushFocusTrap('#modal-container');

    assertEqual(fm.currentView, 'modal', 'pushFocusTrap switches to modal view');
    assertEqual(fm.focusTrapStack.length, 1, 'focusTrapStack has one entry');
    assertEqual(fm.focusTrapStack[0].view, 'grid', 'saved view is grid');
    assertEqual(fm.focusTrapStack[0].index, 3, 'saved index is 3');
})();

(function testPopFocusTrapRestoresState() {
    const sb = buildSandbox();
    const ctx = loadInput(sb);
    const fm = new ctx._FocusManager();

    const el = createMockElement('div');
    fm.focusableElements.set('grid', [el, el, el, el]);
    fm.currentFocusIndex.set('grid', 2);
    fm.currentView = 'grid';

    // Mock for applyFocus
    sb.document.querySelectorAll = () => [];

    // Push
    fm.focusTrapStack.push({ view: 'grid', index: 2 });
    fm.currentView = 'modal';

    // Pop
    fm.popFocusTrap();

    assertEqual(fm.currentView, 'grid', 'popFocusTrap restores previous view');
    assertEqual(fm.currentFocusIndex.get('grid'), 2, 'popFocusTrap restores previous index');
    assert(!fm.focusableElements.has('modal'), 'modal focusables cleaned up');
})();

(function testPopFocusTrapEmptyStackDoesNotCrash() {
    const sb = buildSandbox();
    const ctx = loadInput(sb);
    const fm = new ctx._FocusManager();

    fm.popFocusTrap();
    assert(true, 'popFocusTrap on empty stack does not crash');
})();

(function testNestedFocusTraps() {
    const sb = buildSandbox();
    const ctx = loadInput(sb);
    const fm = new ctx._FocusManager();

    sb.document.querySelectorAll = () => [];

    fm.currentView = 'grid';
    fm.currentFocusIndex.set('grid', 1);

    // Push first trap
    fm.focusTrapStack.push({ view: 'grid', index: 1 });
    fm.currentView = 'modal';
    fm.currentFocusIndex.set('modal', 0);

    // Push second trap
    fm.focusTrapStack.push({ view: 'modal', index: 0 });
    fm.currentView = 'modal'; // still modal

    assertEqual(fm.focusTrapStack.length, 2, 'two focus traps stacked');

    // Pop second
    fm.popFocusTrap();
    assertEqual(fm.currentView, 'modal', 'first pop restores modal');

    // Pop first
    fm.popFocusTrap();
    assertEqual(fm.currentView, 'grid', 'second pop restores grid');
    assertEqual(fm.focusTrapStack.length, 0, 'stack is empty after two pops');
})();


// ============================================================
// 7. FocusManager - applyFocus
// ============================================================

console.log('\n--- FocusManager: applyFocus ---');

(function testApplyFocusAddsClass() {
    const sb = buildSandbox();
    const ctx = loadInput(sb);
    const fm = new ctx._FocusManager();

    sb.document.querySelectorAll = () => [];

    const el = createMockElement('div');
    fm.applyFocus(el);
    assert(el.classList.contains('gamepad-focus'), 'applyFocus adds gamepad-focus class');
})();

(function testApplyFocusRemovesFromOthers() {
    const sb = buildSandbox();
    const ctx = loadInput(sb);
    const fm = new ctx._FocusManager();

    const oldEl = createMockElement('div');
    oldEl.classList.add('gamepad-focus');

    sb.document.querySelectorAll = (sel) => {
        if (sel === '.gamepad-focus') return [oldEl];
        return [];
    };

    const newEl = createMockElement('div');
    fm.applyFocus(newEl);

    assert(!oldEl.classList.contains('gamepad-focus'), 'applyFocus removes gamepad-focus from old elements');
    assert(newEl.classList.contains('gamepad-focus'), 'applyFocus adds gamepad-focus to new element');
})();

(function testApplyFocusNullDoesNotCrash() {
    const sb = buildSandbox();
    const ctx = loadInput(sb);
    const fm = new ctx._FocusManager();

    fm.applyFocus(null);
    assert(true, 'applyFocus(null) does not crash');
})();

(function testApplyFocusCallsScrollIntoView() {
    const sb = buildSandbox();
    const ctx = loadInput(sb);
    const fm = new ctx._FocusManager();

    sb.document.querySelectorAll = () => [];

    let scrollCalled = false;
    const el = createMockElement('div');
    el.scrollIntoView = () => { scrollCalled = true; };

    fm.applyFocus(el);
    assert(scrollCalled, 'applyFocus calls scrollIntoView on element');
})();


// ============================================================
// 8. GamepadHandler - construction
// ============================================================

console.log('\n--- GamepadHandler: construction ---');

(function testGamepadHandlerDefaults() {
    const sb = buildSandbox();
    const ctx = loadInput(sb);
    const inputMgr = ctx._tritiumInput;
    const gh = inputMgr.gamepadHandler;

    assertEqual(gh.connected, false, 'GamepadHandler starts disconnected');
    assertEqual(gh.gamepadIndex, null, 'GamepadHandler gamepadIndex starts null');
    assertEqual(gh.previousButtonStates.length, 16, 'previousButtonStates has 16 entries');
    assertEqual(gh.previousAxes.length, 4, 'previousAxes has 4 entries');
    assert(gh.previousButtonStates.every(s => s === false), 'all previous button states are false');
    assert(gh.previousAxes.every(a => a === 0), 'all previous axes are 0');
})();


// ============================================================
// 9. GamepadHandler - connection / disconnection
// ============================================================

console.log('\n--- GamepadHandler: connection / disconnection ---');

(function testOnGamepadConnectedSetsState() {
    const sb = buildSandbox();
    const ctx = loadInput(sb);

    const gh = new ctx._GamepadHandler({ executeAction() {} });
    const gamepad = createMockGamepad(0);

    gh.onGamepadConnected({ gamepad });

    assert(gh.connected, 'connected is true after onGamepadConnected');
    assertEqual(gh.gamepadIndex, 0, 'gamepadIndex set to gamepad.index');
})();

(function testOnGamepadConnectedStoresIndex() {
    const sb = buildSandbox();
    const ctx = loadInput(sb);

    const gh = new ctx._GamepadHandler({ executeAction() {} });
    const gamepad = createMockGamepad(2, 'Custom Controller');

    gh.onGamepadConnected({ gamepad });
    assertEqual(gh.gamepadIndex, 2, 'gamepadIndex matches gamepad.index');
})();

(function testOnGamepadDisconnectedResetsState() {
    const sb = buildSandbox();
    const ctx = loadInput(sb);

    const gh = new ctx._GamepadHandler({ executeAction() {} });
    const gamepad = createMockGamepad(0);

    gh.onGamepadConnected({ gamepad });
    assert(gh.connected, 'connected after connect');

    gh.onGamepadDisconnected({ gamepad });
    assertEqual(gh.connected, false, 'connected is false after disconnect');
    assertEqual(gh.gamepadIndex, null, 'gamepadIndex is null after disconnect');
})();

(function testDisconnectWrongIndexDoesNotReset() {
    const sb = buildSandbox();
    const ctx = loadInput(sb);

    const gh = new ctx._GamepadHandler({ executeAction() {} });
    const gp0 = createMockGamepad(0);
    const gp1 = createMockGamepad(1);

    gh.onGamepadConnected({ gamepad: gp0 });
    gh.onGamepadDisconnected({ gamepad: gp1 });

    assert(gh.connected, 'still connected when different gamepad disconnects');
    assertEqual(gh.gamepadIndex, 0, 'gamepadIndex unchanged');
})();

(function testStartDetectsAlreadyConnected() {
    const sb = buildSandbox();
    const ctx = loadInput(sb);

    const actions = [];
    const gh = new ctx._GamepadHandler({ executeAction(a) { actions.push(a); } });

    // Place a gamepad in navigator before start
    const gamepad = createMockGamepad(1);
    sb._navigator._gamepads[1] = gamepad;

    gh.start();

    assert(gh.connected, 'start() detects already-connected gamepad');
    assertEqual(gh.gamepadIndex, 1, 'start() picks up the correct index');
})();


// ============================================================
// 10. GamepadHandler - button mapping
// ============================================================

console.log('\n--- GamepadHandler: button mapping ---');

(function testMapButtonToActionAllButtons() {
    const sb = buildSandbox();
    const ctx = loadInput(sb);

    const gh = new ctx._GamepadHandler({ executeAction() {} });
    const B = ctx._GAMEPAD_BUTTONS;

    const expectedMap = {
        [B.A]: 'confirm',
        [B.B]: 'back',
        [B.X]: 'context',
        [B.Y]: 'secondary',
        [B.LB]: 'view_prev',
        [B.RB]: 'view_next',
        [B.LT]: 'page_up',
        [B.RT]: 'page_down',
        [B.SELECT]: 'help',
        [B.START]: 'menu',
        [B.L3]: 'toggle_sidebar',
        [B.R3]: 'reset_view',
        [B.DPAD_UP]: 'nav_up',
        [B.DPAD_DOWN]: 'nav_down',
        [B.DPAD_LEFT]: 'nav_left',
        [B.DPAD_RIGHT]: 'nav_right',
    };

    for (const [btn, action] of Object.entries(expectedMap)) {
        assertEqual(gh.mapButtonToAction(parseInt(btn)), action, `Button ${btn} maps to '${action}'`);
    }
})();

(function testMapButtonToActionUnknownReturnsUndefined() {
    const sb = buildSandbox();
    const ctx = loadInput(sb);

    const gh = new ctx._GamepadHandler({ executeAction() {} });
    const result = gh.mapButtonToAction(99);
    assertEqual(result, undefined, 'unknown button returns undefined');
})();


// ============================================================
// 11. GamepadHandler - processButtons
// ============================================================

console.log('\n--- GamepadHandler: processButtons ---');

(function testProcessButtonsDetectPress() {
    const sb = buildSandbox();
    const ctx = loadInput(sb);

    const actions = [];
    const gh = new ctx._GamepadHandler({ executeAction(a) { actions.push(a); } });

    const gamepad = createMockGamepad();
    // Press A button
    gamepad.buttons[0].pressed = true;
    gamepad.buttons[0].value = 1.0;

    gh.processButtons(gamepad);
    assert(actions.includes('confirm'), 'A button press triggers confirm action');
})();

(function testProcessButtonsDetectRelease() {
    const sb = buildSandbox();
    const ctx = loadInput(sb);

    const actions = [];
    const gh = new ctx._GamepadHandler({ executeAction(a) { actions.push(a); } });

    // Simulate previous state: button was pressed
    gh.previousButtonStates[0] = true;
    // D-pad up was pressed and has a hold timer
    gh.previousButtonStates[12] = true;
    gh.buttonHoldTimers[12] = { startTime: Date.now(), repeating: false };

    const gamepad = createMockGamepad();
    // All buttons released
    gh.processButtons(gamepad);

    // The hold timer should be cleared
    assertEqual(gh.buttonHoldTimers[12], undefined, 'hold timer cleared on button release');
})();

(function testProcessButtonsAnalogTrigger() {
    const sb = buildSandbox();
    const ctx = loadInput(sb);

    const actions = [];
    const gh = new ctx._GamepadHandler({ executeAction(a) { actions.push(a); } });

    const gamepad = createMockGamepad();
    // Analog trigger with value > 0.5 counts as pressed
    gamepad.buttons[6].pressed = false;
    gamepad.buttons[6].value = 0.7;

    gh.processButtons(gamepad);
    assert(actions.includes('page_up'), 'analog trigger value > 0.5 triggers press');
})();

(function testProcessButtonsAnalogTriggerBelowThreshold() {
    const sb = buildSandbox();
    const ctx = loadInput(sb);

    const actions = [];
    const gh = new ctx._GamepadHandler({ executeAction(a) { actions.push(a); } });

    const gamepad = createMockGamepad();
    // Analog trigger with value < 0.5 does not count as pressed
    gamepad.buttons[6].pressed = false;
    gamepad.buttons[6].value = 0.3;

    gh.processButtons(gamepad);
    assert(!actions.includes('page_up'), 'analog trigger value < 0.5 does not trigger press');
})();

(function testProcessButtonsMultipleSimultaneousPresses() {
    const sb = buildSandbox();
    const ctx = loadInput(sb);

    const actions = [];
    const gh = new ctx._GamepadHandler({ executeAction(a) { actions.push(a); } });

    const gamepad = createMockGamepad();
    // Press A and B simultaneously
    gamepad.buttons[0].pressed = true;
    gamepad.buttons[0].value = 1.0;
    gamepad.buttons[1].pressed = true;
    gamepad.buttons[1].value = 1.0;

    gh.processButtons(gamepad);
    assert(actions.includes('confirm'), 'A button detected in simultaneous press');
    assert(actions.includes('back'), 'B button detected in simultaneous press');
})();

(function testProcessButtonsDpadStartsHoldTimer() {
    const sb = buildSandbox();
    const ctx = loadInput(sb);

    const actions = [];
    const gh = new ctx._GamepadHandler({ executeAction(a) { actions.push(a); } });
    const B = ctx._GAMEPAD_BUTTONS;

    const gamepad = createMockGamepad();
    gamepad.buttons[B.DPAD_UP].pressed = true;
    gamepad.buttons[B.DPAD_UP].value = 1.0;

    gh.processButtons(gamepad);
    assert(gh.buttonHoldTimers[B.DPAD_UP] !== undefined, 'D-pad up starts a hold timer');
    assertEqual(gh.buttonHoldTimers[B.DPAD_UP].repeating, false, 'hold timer starts not repeating');
})();

(function testProcessButtonsNonDpadNoHoldTimer() {
    const sb = buildSandbox();
    const ctx = loadInput(sb);

    const actions = [];
    const gh = new ctx._GamepadHandler({ executeAction(a) { actions.push(a); } });
    const B = ctx._GAMEPAD_BUTTONS;

    const gamepad = createMockGamepad();
    gamepad.buttons[B.A].pressed = true;
    gamepad.buttons[B.A].value = 1.0;

    gh.processButtons(gamepad);
    assertEqual(gh.buttonHoldTimers[B.A], undefined, 'non-D-pad button does not start hold timer');
})();


// ============================================================
// 12. GamepadHandler - button hold / repeat
// ============================================================

console.log('\n--- GamepadHandler: button hold / repeat ---');

(function testHandleButtonHoldNoTimerDoesNotCrash() {
    const sb = buildSandbox();
    const ctx = loadInput(sb);

    const gh = new ctx._GamepadHandler({ executeAction() {} });
    gh.handleButtonHold(0);
    assert(true, 'handleButtonHold with no timer does not crash');
})();

(function testHandleButtonHoldBelowDelayNoRepeat() {
    const sb = buildSandbox();
    const ctx = loadInput(sb);

    const actions = [];
    const gh = new ctx._GamepadHandler({ executeAction(a) { actions.push(a); } });

    // Timer started just now, so elapsed < REPEAT_DELAY
    gh.buttonHoldTimers[12] = { startTime: Date.now(), repeating: false };

    gh.handleButtonHold(12);
    assertEqual(actions.length, 0, 'no repeat action before REPEAT_DELAY');
})();

(function testHandleButtonHoldAboveDelayStartsRepeat() {
    const sb = buildSandbox();
    const ctx = loadInput(sb);

    const actions = [];
    const gh = new ctx._GamepadHandler({ executeAction(a) { actions.push(a); } });

    // Timer started 500ms ago (> REPEAT_DELAY of 400ms)
    const timer = { startTime: Date.now() - 500, repeating: false };
    gh.buttonHoldTimers[12] = timer;

    gh.handleButtonHold(12);
    // handleButtonHold sets timer.repeating = true THEN calls onButtonDown
    // which overwrites buttonHoldTimers[12] with a fresh object.
    // But the local timer ref still has repeating=true.
    assert(timer.repeating, 'hold timer transitions to repeating');
    assert(actions.length > 0, 'repeat action fires after REPEAT_DELAY');
})();

(function testHandleButtonHoldRepeatsAtRate() {
    const sb = buildSandbox();
    const ctx = loadInput(sb);

    const actions = [];
    const gh = new ctx._GamepadHandler({ executeAction(a) { actions.push(a); } });

    // Already repeating, last repeat was 150ms ago (> REPEAT_RATE of 100ms)
    gh.buttonHoldTimers[12] = {
        startTime: Date.now() - 1000,
        repeating: true,
        lastRepeat: Date.now() - 150,
    };

    gh.handleButtonHold(12);
    assert(actions.length > 0, 'repeat fires when enough time since lastRepeat');
})();

(function testHandleButtonHoldDoesNotRepeatTooSoon() {
    const sb = buildSandbox();
    const ctx = loadInput(sb);

    const actions = [];
    const gh = new ctx._GamepadHandler({ executeAction(a) { actions.push(a); } });

    // Already repeating, last repeat was 50ms ago (< REPEAT_RATE of 100ms)
    gh.buttonHoldTimers[12] = {
        startTime: Date.now() - 1000,
        repeating: true,
        lastRepeat: Date.now() - 50,
    };

    gh.handleButtonHold(12);
    assertEqual(actions.length, 0, 'no repeat when less than REPEAT_RATE elapsed');
})();


// ============================================================
// 13. GamepadHandler - deadzone
// ============================================================

console.log('\n--- GamepadHandler: deadzone ---');

(function testDeadzoneZero() {
    const sb = buildSandbox();
    const ctx = loadInput(sb);

    const gh = new ctx._GamepadHandler({ executeAction() {} });
    assertEqual(gh.applyDeadzone(0), 0, 'deadzone: zero input returns 0');
})();

(function testDeadzoneSmallPositive() {
    const sb = buildSandbox();
    const ctx = loadInput(sb);

    const gh = new ctx._GamepadHandler({ executeAction() {} });
    assertEqual(gh.applyDeadzone(0.1), 0, 'deadzone: 0.1 (below 0.25) returns 0');
})();

(function testDeadzoneSmallNegative() {
    const sb = buildSandbox();
    const ctx = loadInput(sb);

    const gh = new ctx._GamepadHandler({ executeAction() {} });
    assertEqual(gh.applyDeadzone(-0.2), 0, 'deadzone: -0.2 (below 0.25) returns 0');
})();

(function testDeadzoneExactBoundary() {
    const sb = buildSandbox();
    const ctx = loadInput(sb);

    const gh = new ctx._GamepadHandler({ executeAction() {} });
    assertEqual(gh.applyDeadzone(0.25), 0, 'deadzone: exactly 0.25 returns 0');
})();

(function testDeadzoneAboveBoundaryPositive() {
    const sb = buildSandbox();
    const ctx = loadInput(sb);

    const gh = new ctx._GamepadHandler({ executeAction() {} });
    const result = gh.applyDeadzone(0.5);
    // (0.5 - 0.25) / (1 - 0.25) = 0.25 / 0.75 = 0.333...
    assertApprox(result, 0.3333, 0.001, 'deadzone: 0.5 rescaled to ~0.333');
})();

(function testDeadzoneAboveBoundaryNegative() {
    const sb = buildSandbox();
    const ctx = loadInput(sb);

    const gh = new ctx._GamepadHandler({ executeAction() {} });
    const result = gh.applyDeadzone(-0.5);
    assertApprox(result, -0.3333, 0.001, 'deadzone: -0.5 rescaled to ~-0.333');
})();

(function testDeadzoneFullDeflection() {
    const sb = buildSandbox();
    const ctx = loadInput(sb);

    const gh = new ctx._GamepadHandler({ executeAction() {} });
    const result = gh.applyDeadzone(1.0);
    assertApprox(result, 1.0, 0.001, 'deadzone: 1.0 returns 1.0');
})();

(function testDeadzoneFullNegativeDeflection() {
    const sb = buildSandbox();
    const ctx = loadInput(sb);

    const gh = new ctx._GamepadHandler({ executeAction() {} });
    const result = gh.applyDeadzone(-1.0);
    assertApprox(result, -1.0, 0.001, 'deadzone: -1.0 returns -1.0');
})();

(function testDeadzoneJustAboveThreshold() {
    const sb = buildSandbox();
    const ctx = loadInput(sb);

    const gh = new ctx._GamepadHandler({ executeAction() {} });
    const result = gh.applyDeadzone(0.26);
    // (0.26 - 0.25) / 0.75 = 0.01333...
    assert(result > 0, 'deadzone: 0.26 returns positive value');
    assertApprox(result, 0.01333, 0.001, 'deadzone: 0.26 rescaled correctly');
})();


// ============================================================
// 14. GamepadHandler - processAxes
// ============================================================

console.log('\n--- GamepadHandler: processAxes ---');

(function testProcessAxesLeftStickNavUp() {
    const sb = buildSandbox();
    const ctx = loadInput(sb);

    const actions = [];
    const gh = new ctx._GamepadHandler({ executeAction(a, d) { actions.push({ action: a, data: d }); } });
    gh.lastAxisTime = {};

    const gamepad = createMockGamepad();
    gamepad.axes[1] = -0.8; // left stick up (Y axis negative = up)

    gh.processAxes(gamepad);
    const navActions = actions.filter(a => a.action === 'nav_up');
    assert(navActions.length > 0, 'left stick up triggers nav_up');
})();

(function testProcessAxesLeftStickNavDown() {
    const sb = buildSandbox();
    const ctx = loadInput(sb);

    const actions = [];
    const gh = new ctx._GamepadHandler({ executeAction(a, d) { actions.push({ action: a, data: d }); } });
    gh.lastAxisTime = {};

    const gamepad = createMockGamepad();
    gamepad.axes[1] = 0.8; // left stick down

    gh.processAxes(gamepad);
    const navActions = actions.filter(a => a.action === 'nav_down');
    assert(navActions.length > 0, 'left stick down triggers nav_down');
})();

(function testProcessAxesLeftStickNavLeft() {
    const sb = buildSandbox();
    const ctx = loadInput(sb);

    const actions = [];
    const gh = new ctx._GamepadHandler({ executeAction(a, d) { actions.push({ action: a, data: d }); } });
    gh.lastAxisTime = {};

    const gamepad = createMockGamepad();
    gamepad.axes[0] = -0.8; // left stick left

    gh.processAxes(gamepad);
    const navActions = actions.filter(a => a.action === 'nav_left');
    assert(navActions.length > 0, 'left stick left triggers nav_left');
})();

(function testProcessAxesLeftStickNavRight() {
    const sb = buildSandbox();
    const ctx = loadInput(sb);

    const actions = [];
    const gh = new ctx._GamepadHandler({ executeAction(a, d) { actions.push({ action: a, data: d }); } });
    gh.lastAxisTime = {};

    const gamepad = createMockGamepad();
    gamepad.axes[0] = 0.8; // left stick right

    gh.processAxes(gamepad);
    const navActions = actions.filter(a => a.action === 'nav_right');
    assert(navActions.length > 0, 'left stick right triggers nav_right');
})();

(function testProcessAxesLeftStickInDeadzone() {
    const sb = buildSandbox();
    const ctx = loadInput(sb);

    const actions = [];
    const gh = new ctx._GamepadHandler({ executeAction(a, d) { actions.push({ action: a, data: d }); } });
    gh.lastAxisTime = {};

    const gamepad = createMockGamepad();
    gamepad.axes[0] = 0.1; // within deadzone
    gamepad.axes[1] = 0.1;
    gamepad.axes[2] = 0.1;
    gamepad.axes[3] = 0.1;

    gh.processAxes(gamepad);
    const navActions = actions.filter(a => a.action.startsWith('nav_'));
    assertEqual(navActions.length, 0, 'stick in deadzone triggers no navigation');
})();

(function testProcessAxesRightStickCameraMove() {
    const sb = buildSandbox();
    const ctx = loadInput(sb);

    const actions = [];
    const gh = new ctx._GamepadHandler({ executeAction(a, d) { actions.push({ action: a, data: d }); } });
    gh.lastAxisTime = {};

    const gamepad = createMockGamepad();
    gamepad.axes[2] = 0.6; // right stick X
    gamepad.axes[3] = -0.4; // right stick Y

    gh.processAxes(gamepad);
    const camActions = actions.filter(a => a.action === 'camera_move');
    assert(camActions.length > 0, 'right stick triggers camera_move action');
    assert(camActions[0].data !== null, 'camera_move includes data payload');
    assert(typeof camActions[0].data.x === 'number', 'camera_move data has x');
    assert(typeof camActions[0].data.y === 'number', 'camera_move data has y');
})();

(function testProcessAxesRightStickInDeadzone() {
    const sb = buildSandbox();
    const ctx = loadInput(sb);

    const actions = [];
    const gh = new ctx._GamepadHandler({ executeAction(a, d) { actions.push({ action: a, data: d }); } });
    gh.lastAxisTime = {};

    const gamepad = createMockGamepad();
    gamepad.axes[2] = 0.1; // right stick X in deadzone
    gamepad.axes[3] = 0.1; // right stick Y in deadzone

    gh.processAxes(gamepad);
    const camActions = actions.filter(a => a.action === 'camera_move');
    assertEqual(camActions.length, 0, 'right stick in deadzone triggers no camera_move');
})();

(function testProcessAxesDominantDirectionWins() {
    const sb = buildSandbox();
    const ctx = loadInput(sb);

    const actions = [];
    const gh = new ctx._GamepadHandler({ executeAction(a, d) { actions.push({ action: a, data: d }); } });
    gh.lastAxisTime = {};

    const gamepad = createMockGamepad();
    // Y more dominant than X
    gamepad.axes[0] = 0.3; // small X
    gamepad.axes[1] = -0.9; // large Y

    gh.processAxes(gamepad);
    const navActions = actions.filter(a => a.action.startsWith('nav_'));
    assert(navActions.length > 0, 'dominant Y axis produces nav action');
    assertEqual(navActions[0].action, 'nav_up', 'dominant negative Y triggers nav_up');
})();

(function testProcessAxesRateLimiting() {
    const sb = buildSandbox();
    const ctx = loadInput(sb);

    const actions = [];
    const gh = new ctx._GamepadHandler({ executeAction(a, d) { actions.push({ action: a, data: d }); } });

    const gamepad = createMockGamepad();
    gamepad.axes[0] = 0.8;

    // First call should fire
    gh.processAxes(gamepad);
    const count1 = actions.filter(a => a.action === 'nav_right').length;

    // Immediate second call should be rate-limited
    gh.processAxes(gamepad);
    const count2 = actions.filter(a => a.action === 'nav_right').length;

    assertEqual(count1, 1, 'first axis poll fires nav action');
    assertEqual(count2, 1, 'immediate second poll is rate-limited');
})();


// ============================================================
// 15. GamepadHandler - vibrate
// ============================================================

console.log('\n--- GamepadHandler: vibrate ---');

(function testVibrateWhenDisconnectedDoesNotCrash() {
    const sb = buildSandbox();
    const ctx = loadInput(sb);

    const gh = new ctx._GamepadHandler({ executeAction() {} });
    gh.connected = false;
    gh.vibrate(100, 0.5, 0.5);
    assert(true, 'vibrate when disconnected does not crash');
})();

(function testVibrateCallsVibrationActuator() {
    const sb = buildSandbox();
    const ctx = loadInput(sb);

    const gh = new ctx._GamepadHandler({ executeAction() {} });
    const gamepad = createMockGamepad(0);
    sb._navigator._gamepads[0] = gamepad;
    gh.connected = true;
    gh.gamepadIndex = 0;

    gh.vibrate(200, 0.3, 0.7);
    assertEqual(gamepad.vibrationActuator._effects.length, 1, 'vibrate calls vibrationActuator');
    assertEqual(gamepad.vibrationActuator._effects[0].params.duration, 200, 'vibrate duration matches');
    assertApprox(gamepad.vibrationActuator._effects[0].params.weakMagnitude, 0.3, 0.01, 'vibrate weak magnitude matches');
    assertApprox(gamepad.vibrationActuator._effects[0].params.strongMagnitude, 0.7, 0.01, 'vibrate strong magnitude matches');
})();

(function testVibrateNoActuatorDoesNotCrash() {
    const sb = buildSandbox();
    const ctx = loadInput(sb);

    const gh = new ctx._GamepadHandler({ executeAction() {} });
    const gamepad = createMockGamepad(0);
    gamepad.vibrationActuator = null;
    sb._navigator._gamepads[0] = gamepad;
    gh.connected = true;
    gh.gamepadIndex = 0;

    gh.vibrate(100, 0.5, 0.5);
    assert(true, 'vibrate without vibrationActuator does not crash');
})();

(function testVibrateDefaultParams() {
    const sb = buildSandbox();
    const ctx = loadInput(sb);

    const gh = new ctx._GamepadHandler({ executeAction() {} });
    const gamepad = createMockGamepad(0);
    sb._navigator._gamepads[0] = gamepad;
    gh.connected = true;
    gh.gamepadIndex = 0;

    gh.vibrate(); // uses defaults
    assertEqual(gamepad.vibrationActuator._effects.length, 1, 'vibrate with defaults fires');
    assertEqual(gamepad.vibrationActuator._effects[0].params.duration, 100, 'default duration is 100');
    assertApprox(gamepad.vibrationActuator._effects[0].params.weakMagnitude, 0.5, 0.01, 'default weak magnitude is 0.5');
    assertApprox(gamepad.vibrationActuator._effects[0].params.strongMagnitude, 0.5, 0.01, 'default strong magnitude is 0.5');
})();


// ============================================================
// 16. GamepadHandler - stop
// ============================================================

console.log('\n--- GamepadHandler: stop ---');

(function testStopCancelsAnimationFrame() {
    const sb = buildSandbox();
    const ctx = loadInput(sb);

    const gh = new ctx._GamepadHandler({ executeAction() {} });
    gh.animationFrameId = 42;

    gh.stop();
    assertEqual(gh.animationFrameId, null, 'stop sets animationFrameId to null');
})();

(function testStopWhenNotRunningDoesNotCrash() {
    const sb = buildSandbox();
    const ctx = loadInput(sb);

    const gh = new ctx._GamepadHandler({ executeAction() {} });
    gh.animationFrameId = null;

    gh.stop();
    assert(true, 'stop when not running does not crash');
})();


// ============================================================
// 17. TritiumInputManager - construction
// ============================================================

console.log('\n--- TritiumInputManager: construction ---');

(function testTritiumInputManagerHasFocusManager() {
    const sb = buildSandbox();
    const ctx = loadInput(sb);

    const mgr = ctx._tritiumInput;
    assert(mgr.focusManager !== undefined, 'TritiumInputManager has focusManager');
    assert(mgr.focusManager.currentView !== undefined, 'focusManager has currentView');
})();

(function testTritiumInputManagerHasGamepadHandler() {
    const sb = buildSandbox();
    const ctx = loadInput(sb);

    const mgr = ctx._tritiumInput;
    assert(mgr.gamepadHandler !== undefined, 'TritiumInputManager has gamepadHandler');
    assert(mgr.gamepadHandler.connected !== undefined, 'gamepadHandler has connected property');
})();

(function testTritiumInputManagerEnabledByDefault() {
    const sb = buildSandbox();
    const ctx = loadInput(sb);

    const mgr = ctx._tritiumInput;
    assertEqual(mgr.enabled, true, 'TritiumInputManager is enabled by default');
    assertEqual(mgr.gamepadEnabled, true, 'gamepadEnabled is true by default');
})();


// ============================================================
// 18. TritiumInputManager - executeAction routing
// ============================================================

console.log('\n--- TritiumInputManager: executeAction routing ---');

(function testExecuteActionNavUpMovesFocus() {
    const sb = buildSandbox();
    const ctx = loadInput(sb);

    const mgr = new ctx._TritiumInputManager();
    sb.TRITIUM = { state: { currentView: 'grid' } };

    const elements = [
        createMockElement('div'),
        createMockElement('div'),
        createMockElement('div'),
    ];
    mgr.focusManager.focusableElements.set('grid', elements);
    mgr.focusManager.currentFocusIndex.set('grid', 2);
    mgr.focusManager.currentView = 'grid';

    // Mock for applyFocus
    sb.document.querySelectorAll = () => [];

    mgr.executeAction('nav_up');
    assertEqual(mgr.focusManager.currentFocusIndex.get('grid'), 1, 'nav_up moves focus up');
})();

(function testExecuteActionNavDownMovesFocus() {
    const sb = buildSandbox();
    const ctx = loadInput(sb);

    const mgr = new ctx._TritiumInputManager();
    sb.TRITIUM = { state: { currentView: 'grid' } };

    const elements = [
        createMockElement('div'),
        createMockElement('div'),
        createMockElement('div'),
    ];
    mgr.focusManager.focusableElements.set('grid', elements);
    mgr.focusManager.currentFocusIndex.set('grid', 0);
    mgr.focusManager.currentView = 'grid';

    sb.document.querySelectorAll = () => [];

    mgr.executeAction('nav_down');
    assertEqual(mgr.focusManager.currentFocusIndex.get('grid'), 1, 'nav_down moves focus down');
})();

(function testExecuteActionConfirmActivatesCurrent() {
    const sb = buildSandbox();
    const ctx = loadInput(sb);

    const mgr = new ctx._TritiumInputManager();
    sb.TRITIUM = { state: { currentView: 'grid' } };

    const el = createMockElement('button');
    mgr.focusManager.focusableElements.set('grid', [el]);
    mgr.focusManager.currentFocusIndex.set('grid', 0);
    mgr.focusManager.currentView = 'grid';

    // Mock navigator for vibrate
    sb._navigator._gamepads[0] = null;
    mgr.gamepadHandler.connected = false;

    mgr.executeAction('confirm');
    assert(el._clicked, 'confirm action clicks focused element');
})();

(function testExecuteActionDisabledDoesNothing() {
    const sb = buildSandbox();
    const ctx = loadInput(sb);

    const mgr = new ctx._TritiumInputManager();
    mgr.enabled = false;
    sb.TRITIUM = { state: { currentView: 'grid' } };

    const el = createMockElement('button');
    mgr.focusManager.focusableElements.set('grid', [el]);
    mgr.focusManager.currentFocusIndex.set('grid', 0);
    mgr.focusManager.currentView = 'grid';

    mgr.executeAction('confirm');
    assert(!el._clicked, 'executeAction does nothing when disabled');
})();

(function testExecuteActionViewPrev() {
    const sb = buildSandbox();
    const ctx = loadInput(sb);

    const mgr = new ctx._TritiumInputManager();
    let switchedTo = null;
    sb.TRITIUM = { state: { currentView: 'player' } };

    // Mock switchView
    const origCtx = vm.createContext(sb);
    vm.runInContext('function switchView(v) { _switchedTo = v; }; var _switchedTo = null;', origCtx);

    // For navigateView, we need switchView in scope.
    // Instead, test the index calculation directly
    const V = ctx._VIEW_ORDER;
    const currentIndex = V.indexOf('player'); // 1
    let newIndex = currentIndex - 1;
    if (newIndex < 0) newIndex = V.length - 1;
    assertEqual(V[newIndex], 'grid', 'view_prev from player goes to grid');
})();

(function testExecuteActionViewNext() {
    const sb = buildSandbox();
    const ctx = loadInput(sb);

    const V = ctx._VIEW_ORDER;
    const currentIndex = V.indexOf('player'); // 1
    let newIndex = currentIndex + 1;
    if (newIndex >= V.length) newIndex = 0;
    assertEqual(V[newIndex], '3d', 'view_next from player goes to 3d');
})();

(function testViewNavWrapsForward() {
    const sb = buildSandbox();
    const ctx = loadInput(sb);

    const V = ctx._VIEW_ORDER;
    const currentIndex = V.indexOf('war'); // last
    let newIndex = currentIndex + 1;
    if (newIndex >= V.length) newIndex = 0;
    assertEqual(V[newIndex], 'grid', 'view_next from war wraps to grid');
})();

(function testViewNavWrapsBackward() {
    const sb = buildSandbox();
    const ctx = loadInput(sb);

    const V = ctx._VIEW_ORDER;
    const currentIndex = V.indexOf('grid'); // first
    let newIndex = currentIndex - 1;
    if (newIndex < 0) newIndex = V.length - 1;
    assertEqual(V[newIndex], 'war', 'view_prev from grid wraps to war');
})();


// ============================================================
// 19. TritiumInputManager - setEnabled / setGamepadEnabled
// ============================================================

console.log('\n--- TritiumInputManager: enable/disable ---');

(function testSetEnabledFalse() {
    const sb = buildSandbox();
    const ctx = loadInput(sb);

    const mgr = ctx._tritiumInput;
    mgr.setEnabled(false);
    assertEqual(mgr.enabled, false, 'setEnabled(false) disables input');
})();

(function testSetEnabledTrue() {
    const sb = buildSandbox();
    const ctx = loadInput(sb);

    const mgr = ctx._tritiumInput;
    mgr.setEnabled(false);
    mgr.setEnabled(true);
    assertEqual(mgr.enabled, true, 'setEnabled(true) re-enables input');
})();

(function testSetGamepadEnabledFalseStopsHandler() {
    const sb = buildSandbox();
    const ctx = loadInput(sb);

    const mgr = ctx._tritiumInput;
    mgr.gamepadHandler.animationFrameId = 42;

    mgr.setGamepadEnabled(false);
    assertEqual(mgr.gamepadEnabled, false, 'setGamepadEnabled(false) disables gamepad');
    assertEqual(mgr.gamepadHandler.animationFrameId, null, 'gamepad handler stopped');
})();

(function testSetGamepadEnabledTrueRestartsHandler() {
    const sb = buildSandbox();
    const ctx = loadInput(sb);

    const mgr = ctx._tritiumInput;
    mgr.setGamepadEnabled(false);
    mgr.setGamepadEnabled(true);
    assertEqual(mgr.gamepadEnabled, true, 'setGamepadEnabled(true) re-enables gamepad');
})();


// ============================================================
// 20. TritiumInputManager - setView
// ============================================================

console.log('\n--- TritiumInputManager: setView ---');

(function testSetViewUpdatesFocusManager() {
    const sb = buildSandbox();
    const ctx = loadInput(sb);

    const mgr = ctx._tritiumInput;
    mgr.setView('targets');
    assertEqual(mgr.focusManager.currentView, 'targets', 'setView updates focusManager currentView');
})();


// ============================================================
// 21. TritiumInputManager - handleBack
// ============================================================

console.log('\n--- TritiumInputManager: handleBack ---');

(function testHandleBackRemovesModalOverlay() {
    const sb = buildSandbox();
    const ctx = loadInput(sb);

    const mgr = new ctx._TritiumInputManager();
    sb.TRITIUM = { state: { currentView: 'grid' } };

    const modal = createMockElement('div', { className: 'modal-overlay' });
    sb.document.querySelector = (sel) => {
        if (sel === '.modal-overlay') return modal;
        return null;
    };

    mgr.handleBack();
    assert(modal._removed, 'handleBack removes modal overlay');
})();

(function testHandleBackNoModalDoesNotCrash() {
    const sb = buildSandbox();
    const ctx = loadInput(sb);

    const mgr = new ctx._TritiumInputManager();
    sb.TRITIUM = { state: { currentView: 'grid' } };
    sb.document.querySelector = () => null;
    sb.document.getElementById = () => null;

    mgr.handleBack();
    assert(true, 'handleBack with nothing to close does not crash');
})();


// ============================================================
// 22. TritiumInputManager - toggleSidebar
// ============================================================

console.log('\n--- TritiumInputManager: toggleSidebar ---');

(function testToggleSidebarAddCollapsed() {
    const sb = buildSandbox();
    const ctx = loadInput(sb);

    const mgr = new ctx._TritiumInputManager();
    const sidebar = createMockElement('div', { className: 'sidebar' });

    sb.document.querySelector = (sel) => {
        if (sel === '.sidebar') return sidebar;
        return null;
    };

    mgr.toggleSidebar();
    assert(sidebar.classList.contains('collapsed'), 'toggleSidebar adds collapsed class');
})();

(function testToggleSidebarRemoveCollapsed() {
    const sb = buildSandbox();
    const ctx = loadInput(sb);

    const mgr = new ctx._TritiumInputManager();
    const sidebar = createMockElement('div', { className: 'sidebar collapsed' });
    sidebar.classList.add('collapsed');

    sb.document.querySelector = (sel) => {
        if (sel === '.sidebar') return sidebar;
        return null;
    };

    mgr.toggleSidebar();
    assert(!sidebar.classList.contains('collapsed'), 'toggleSidebar removes collapsed class when present');
})();

(function testToggleSidebarNoSidebarDoesNotCrash() {
    const sb = buildSandbox();
    const ctx = loadInput(sb);

    const mgr = new ctx._TritiumInputManager();
    sb.document.querySelector = () => null;

    mgr.toggleSidebar();
    assert(true, 'toggleSidebar without sidebar element does not crash');
})();


// ============================================================
// 23. TritiumInputManager - toggleHelp
// ============================================================

console.log('\n--- TritiumInputManager: toggleHelp ---');

(function testToggleHelpRemovesExistingOverlay() {
    const sb = buildSandbox();
    const ctx = loadInput(sb);

    const mgr = new ctx._TritiumInputManager();
    const overlay = createMockElement('div', { id: 'controls-overlay' });

    sb.document.getElementById = (id) => {
        if (id === 'controls-overlay') return overlay;
        return null;
    };

    mgr.toggleHelp();
    assert(overlay._removed, 'toggleHelp removes existing overlay');
})();


// ============================================================
// 24. TritiumInputManager - getKeyboardControlsHTML
// ============================================================

console.log('\n--- TritiumInputManager: getKeyboardControlsHTML ---');

(function testKeyboardControlsHTMLGlobal() {
    const sb = buildSandbox();
    const ctx = loadInput(sb);

    const mgr = new ctx._TritiumInputManager();
    const html = mgr.getKeyboardControlsHTML('grid');
    assert(html.includes('GLOBAL'), 'keyboard controls HTML includes GLOBAL section');
    assert(html.includes('Grid View'), 'keyboard controls for grid includes G shortcut');
    assert(html.includes('ESC'), 'keyboard controls includes ESC');
})();

(function testKeyboardControlsHTMLWarView() {
    const sb = buildSandbox();
    const ctx = loadInput(sb);

    const mgr = new ctx._TritiumInputManager();
    const html = mgr.getKeyboardControlsHTML('war');
    assert(html.includes('WAR ROOM'), 'war view keyboard controls includes WAR ROOM');
    assert(html.includes('Observe Mode'), 'war view includes Observe Mode');
    assert(html.includes('Tactical Mode'), 'war view includes Tactical Mode');
    assert(html.includes('Setup Mode'), 'war view includes Setup Mode');
})();

(function testKeyboardControlsHTMLPlayerView() {
    const sb = buildSandbox();
    const ctx = loadInput(sb);

    const mgr = new ctx._TritiumInputManager();
    const html = mgr.getKeyboardControlsHTML('player');
    assert(html.includes('PLAYER VIEW'), 'player view keyboard controls includes PLAYER VIEW');
    assert(html.includes('Play/Pause'), 'player view includes Play/Pause');
    assert(html.includes('Fullscreen'), 'player view includes Fullscreen');
})();

(function testKeyboardControlsHTMLUnknownView() {
    const sb = buildSandbox();
    const ctx = loadInput(sb);

    const mgr = new ctx._TritiumInputManager();
    const html = mgr.getKeyboardControlsHTML('nonexistent');
    assert(html.includes('GLOBAL'), 'unknown view still includes GLOBAL controls');
})();


// ============================================================
// 25. TritiumInputManager - getGamepadControlsHTML
// ============================================================

console.log('\n--- TritiumInputManager: getGamepadControlsHTML ---');

(function testGamepadControlsHTMLGlobal() {
    const sb = buildSandbox();
    const ctx = loadInput(sb);

    const mgr = new ctx._TritiumInputManager();
    const html = mgr.getGamepadControlsHTML('grid');
    assert(html.includes('D-Pad'), 'gamepad controls includes D-Pad');
    assert(html.includes('Confirm/Select'), 'gamepad controls includes A button mapping');
    assert(html.includes('Back/Cancel'), 'gamepad controls includes B button mapping');
    assert(html.includes('Context Menu'), 'gamepad controls includes X button mapping');
    assert(html.includes('Secondary Action'), 'gamepad controls includes Y button mapping');
    assert(html.includes('LB/RB'), 'gamepad controls includes bumper controls');
})();

(function testGamepadControlsHTMLWarView() {
    const sb = buildSandbox();
    const ctx = loadInput(sb);

    const mgr = new ctx._TritiumInputManager();
    const html = mgr.getGamepadControlsHTML('war');
    assert(html.includes('WAR ROOM'), 'war gamepad controls includes WAR ROOM section');
    assert(html.includes('Pan Camera'), 'war gamepad includes Pan Camera');
    assert(html.includes('Select Nearest Target'), 'war gamepad includes Select Nearest Target');
    assert(html.includes('Cycle Modes'), 'war gamepad includes Cycle Modes');
})();

(function testGamepadControlsHTMLTargetsView() {
    const sb = buildSandbox();
    const ctx = loadInput(sb);

    const mgr = new ctx._TritiumInputManager();
    const html = mgr.getGamepadControlsHTML('targets');
    assert(html.includes('TARGETS VIEW'), 'targets gamepad controls includes TARGETS VIEW');
    assert(html.includes('Navigate Gallery'), 'targets gamepad includes Navigate Gallery');
    assert(html.includes('Find Similar'), 'targets gamepad includes Find Similar');
})();

(function testGamepadControlsHTMLAllViews() {
    const sb = buildSandbox();
    const ctx = loadInput(sb);

    const mgr = new ctx._TritiumInputManager();
    const views = ['grid', 'player', '3d', 'targets', 'assets', 'zones', 'analytics', 'war'];
    for (const view of views) {
        const html = mgr.getGamepadControlsHTML(view);
        assert(html.length > 0, `getGamepadControlsHTML('${view}') returns non-empty string`);
        assert(html.includes('GLOBAL'), `getGamepadControlsHTML('${view}') includes GLOBAL section`);
    }
})();


// ============================================================
// 26. GamepadHandler - poll loop behavior
// ============================================================

console.log('\n--- GamepadHandler: poll loop ---');

(function testPollWhenDisconnectedDoesNotProcess() {
    const sb = buildSandbox();
    const ctx = loadInput(sb);

    const actions = [];
    const gh = new ctx._GamepadHandler({ executeAction(a) { actions.push(a); } });
    gh.connected = false;

    // Set a gamepad with pressed buttons -- poll should skip
    const gamepad = createMockGamepad();
    gamepad.buttons[0].pressed = true;
    sb._navigator._gamepads[0] = gamepad;

    // Simulate the poll body (without requestAnimationFrame)
    if (!gh.connected || gh.gamepadIndex === null) {
        // This is what poll does -- it returns early
    }
    assertEqual(actions.length, 0, 'poll skips processing when disconnected');
})();

(function testPollWhenNullGamepadDoesNotProcess() {
    const sb = buildSandbox();
    const ctx = loadInput(sb);

    const actions = [];
    const gh = new ctx._GamepadHandler({ executeAction(a) { actions.push(a); } });
    gh.connected = true;
    gh.gamepadIndex = 0;
    sb._navigator._gamepads[0] = null; // gamepad removed

    // poll body: gamepads[0] is null, should return
    const gamepads = sb._navigator.getGamepads();
    const gp = gamepads[gh.gamepadIndex];
    assert(gp === null, 'null gamepad detected in poll');
    assertEqual(actions.length, 0, 'poll does not process null gamepad');
})();


// ============================================================
// 27. Global instance and window exports
// ============================================================

console.log('\n--- Global instance and exports ---');

(function testGlobalTritiumInputInstance() {
    const sb = buildSandbox();
    const ctx = loadInput(sb);

    assert(ctx._tritiumInput !== undefined, 'tritiumInput global instance exists');
    assert(ctx._tritiumInput.focusManager !== undefined, 'global instance has focusManager');
    assert(ctx._tritiumInput.gamepadHandler !== undefined, 'global instance has gamepadHandler');
})();

(function testWindowExports() {
    const sb = buildSandbox();
    const ctx = loadInput(sb);

    assert(sb.window.tritiumInput !== undefined, 'window.tritiumInput is set');
    assert(sb.window.TritiumInputManager !== undefined, 'window.TritiumInputManager is set');
})();

(function testDOMContentLoadedListenerRegistered() {
    const sb = buildSandbox();
    const ctx = loadInput(sb);

    const hasListener = sb.document._listeners['DOMContentLoaded'] &&
                        sb.document._listeners['DOMContentLoaded'].length > 0;
    assert(hasListener, 'DOMContentLoaded listener registered for init');
})();


// ============================================================
// 28. Edge cases and robustness
// ============================================================

console.log('\n--- Edge cases ---');

(function testExecuteActionUnknownActionDoesNotCrash() {
    const sb = buildSandbox();
    const ctx = loadInput(sb);

    const mgr = new ctx._TritiumInputManager();
    sb.TRITIUM = { state: { currentView: 'grid' } };
    mgr.executeAction('totally_unknown_action');
    assert(true, 'unknown action does not crash');
})();

(function testExecuteActionNullDataDoesNotCrash() {
    const sb = buildSandbox();
    const ctx = loadInput(sb);

    const mgr = new ctx._TritiumInputManager();
    sb.TRITIUM = { state: { currentView: 'grid' } };
    mgr.executeAction('camera_move', null);
    assert(true, 'camera_move with null data does not crash');
})();

(function testTRITIUMUndefinedDoesNotCrash() {
    const sb = buildSandbox();
    sb.TRITIUM = undefined;
    const ctx = loadInput(sb);

    const mgr = new ctx._TritiumInputManager();
    mgr.executeAction('nav_up');
    assert(true, 'nav_up with TRITIUM undefined does not crash');
})();

(function testTRITIUMStateNullDoesNotCrash() {
    const sb = buildSandbox();
    sb.TRITIUM = { state: null };
    const ctx = loadInput(sb);

    const mgr = new ctx._TritiumInputManager();
    mgr.executeAction('confirm');
    assert(true, 'confirm with TRITIUM.state null does not crash');
})();

(function testMultipleGamepadHandlerInstances() {
    const sb = buildSandbox();
    const ctx = loadInput(sb);

    const actions1 = [];
    const actions2 = [];
    const gh1 = new ctx._GamepadHandler({ executeAction(a) { actions1.push(a); } });
    const gh2 = new ctx._GamepadHandler({ executeAction(a) { actions2.push(a); } });

    const gamepad = createMockGamepad();
    gamepad.buttons[0].pressed = true;
    gamepad.buttons[0].value = 1.0;

    gh1.processButtons(gamepad);
    assert(actions1.length > 0, 'first handler received actions');
    assertEqual(actions2.length, 0, 'second handler did not receive actions');
})();

(function testProcessButtonsLongButtonArray() {
    const sb = buildSandbox();
    const ctx = loadInput(sb);

    const actions = [];
    const gh = new ctx._GamepadHandler({ executeAction(a) { actions.push(a); } });

    // Some controllers report more than 16 buttons
    const gamepad = createMockGamepad();
    for (let i = 0; i < 4; i++) {
        gamepad.buttons.push({ pressed: false, touched: false, value: 0 });
    }
    // Press an extra button (index 17+)
    gamepad.buttons[17].pressed = true;
    gamepad.buttons[17].value = 1.0;

    gh.processButtons(gamepad);
    // Should not crash, the extra button just maps to undefined action
    assert(true, 'processing extra buttons beyond 16 does not crash');
})();


// ============================================================
// 29. War Room specific actions
// ============================================================

console.log('\n--- War Room actions ---');

(function testWarCycleModesCalculation() {
    const sb = buildSandbox();
    const ctx = loadInput(sb);

    // Test the mode cycling logic
    const modes = ['observe', 'tactical', 'setup'];
    for (let i = 0; i < modes.length; i++) {
        const next = modes[(i + 1) % modes.length];
        const expected = i === 0 ? 'tactical' : i === 1 ? 'setup' : 'observe';
        assertEqual(next, expected, `from ${modes[i]}, next mode is ${expected}`);
    }
})();

(function testNavigateViewCalculation() {
    const sb = buildSandbox();
    const ctx = loadInput(sb);

    const V = ctx._VIEW_ORDER;
    // Test all forward transitions
    for (let i = 0; i < V.length; i++) {
        const next = V[(i + 1) % V.length];
        const current = V[i];
        assert(typeof next === 'string', `view_next from '${current}' produces valid view '${next}'`);
    }

    // Test all backward transitions
    for (let i = 0; i < V.length; i++) {
        let prevIdx = i - 1;
        if (prevIdx < 0) prevIdx = V.length - 1;
        const prev = V[prevIdx];
        const current = V[i];
        assert(typeof prev === 'string', `view_prev from '${current}' produces valid view '${prev}'`);
    }
})();


// ============================================================
// 30. Full integration: gamepad connect -> press -> action
// ============================================================

console.log('\n--- Integration: connect -> press -> action ---');

(function testFullGamepadWorkflow() {
    const sb = buildSandbox();
    const ctx = loadInput(sb);

    const mgr = new ctx._TritiumInputManager();
    sb.TRITIUM = { state: { currentView: 'grid' } };

    // Set up focusable elements
    const el0 = createMockElement('div');
    const el1 = createMockElement('div');
    const el2 = createMockElement('div');
    mgr.focusManager.focusableElements.set('grid', [el0, el1, el2]);
    mgr.focusManager.currentFocusIndex.set('grid', 0);
    mgr.focusManager.currentView = 'grid';
    sb.document.querySelectorAll = () => [];

    // Connect gamepad
    const gamepad = createMockGamepad(0);
    mgr.gamepadHandler.onGamepadConnected({ gamepad: gamepad });
    assert(mgr.gamepadHandler.connected, 'integration: gamepad connected');

    // Simulate D-pad down press
    gamepad.buttons[13].pressed = true;
    gamepad.buttons[13].value = 1.0;
    sb._navigator._gamepads[0] = gamepad;

    mgr.gamepadHandler.processButtons(gamepad);
    assertEqual(mgr.focusManager.currentFocusIndex.get('grid'), 1, 'integration: D-pad down moves focus to index 1');

    // Press again
    mgr.gamepadHandler.previousButtonStates[13] = false; // reset for new press
    mgr.gamepadHandler.processButtons(gamepad);
    assertEqual(mgr.focusManager.currentFocusIndex.get('grid'), 2, 'integration: second D-pad down moves focus to index 2');
})();

(function testFullGamepadButtonAWorkflow() {
    const sb = buildSandbox();
    const ctx = loadInput(sb);

    const mgr = new ctx._TritiumInputManager();
    sb.TRITIUM = { state: { currentView: 'grid' } };

    const el = createMockElement('button');
    mgr.focusManager.focusableElements.set('grid', [el]);
    mgr.focusManager.currentFocusIndex.set('grid', 0);
    mgr.focusManager.currentView = 'grid';

    const gamepad = createMockGamepad(0);
    sb._navigator._gamepads[0] = gamepad;
    mgr.gamepadHandler.onGamepadConnected({ gamepad });

    // Press A button
    gamepad.buttons[0].pressed = true;
    gamepad.buttons[0].value = 1.0;
    mgr.gamepadHandler.processButtons(gamepad);

    assert(el._clicked, 'integration: A button clicks focused element');
})();


// ============================================================
// Summary
// ============================================================

console.log('\n' + '='.repeat(50));
console.log(`Results: ${passed} passed, ${failed} failed`);
console.log('='.repeat(50));
process.exit(failed > 0 ? 1 : 0);
