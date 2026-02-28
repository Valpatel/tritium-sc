// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
/**
 * TRITIUM-SC Game HUD Panel Definition tests
 * Tests GameHudPanelDef structure, DOM creation, data-bind elements,
 * action buttons, mount subscription wiring, and unmount.
 * (This tests the panel def object, NOT the helpers which are in test_game_hud.js)
 * Run: node tests/js/test_game_panel.js
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

// Load game-hud.js panel
const gameCode = fs.readFileSync(__dirname + '/../../frontend/js/command/panels/game-hud.js', 'utf8');
const gamePlain = gameCode
    .replace(/^export\s+const\s+/gm, 'var ')
    .replace(/^export\s+/gm, '')
    .replace(/^import\s+.*$/gm, '');
vm.runInContext(gamePlain, ctx);

const GameHudPanelDef = ctx.GameHudPanelDef;

// ============================================================
// 1. GameHudPanelDef has required properties
// ============================================================

console.log('\n--- GameHudPanelDef structure ---');

(function testHasId() {
    assert(GameHudPanelDef.id === 'game', 'GameHudPanelDef.id is "game"');
})();

(function testHasTitle() {
    assert(GameHudPanelDef.title === 'GAME STATUS', 'GameHudPanelDef.title is "GAME STATUS"');
})();

(function testHasCreate() {
    assert(typeof GameHudPanelDef.create === 'function', 'GameHudPanelDef.create is a function');
})();

(function testHasMount() {
    assert(typeof GameHudPanelDef.mount === 'function', 'GameHudPanelDef.mount is a function');
})();

(function testHasUnmount() {
    assert(typeof GameHudPanelDef.unmount === 'function', 'GameHudPanelDef.unmount is a function');
})();

(function testHasDefaultPosition() {
    assert(GameHudPanelDef.defaultPosition !== undefined, 'GameHudPanelDef has defaultPosition');
    assert(GameHudPanelDef.defaultPosition.x === null, 'defaultPosition.x is null (calculated at mount)');
    assert(GameHudPanelDef.defaultPosition.y === 8, 'defaultPosition.y is 8');
})();

(function testHasDefaultSize() {
    assert(GameHudPanelDef.defaultSize !== undefined, 'GameHudPanelDef has defaultSize');
    assert(GameHudPanelDef.defaultSize.w === 240, 'defaultSize.w is 240');
    assert(GameHudPanelDef.defaultSize.h === 180, 'defaultSize.h is 180');
})();

// ============================================================
// 2. create() returns DOM element with expected structure
// ============================================================

console.log('\n--- create() DOM structure ---');

(function testCreateReturnsDomElement() {
    const el = GameHudPanelDef.create({});
    assert(el !== null && el !== undefined, 'create() returns an element');
    assert(el.className === 'game-hud-panel-inner', 'create() element has correct className');
})();

(function testCreateHasPhaseBinding() {
    const el = GameHudPanelDef.create({});
    const html = el.innerHTML;
    assert(html.includes('data-bind="phase"'), 'DOM contains phase data-bind');
    assert(html.includes('IDLE'), 'DOM contains default phase "IDLE"');
})();

(function testCreateHasWaveBinding() {
    const el = GameHudPanelDef.create({});
    const html = el.innerHTML;
    assert(html.includes('data-bind="wave"'), 'DOM contains wave data-bind');
    assert(html.includes('0/10'), 'DOM contains default wave "0/10"');
})();

(function testCreateHasScoreBinding() {
    const el = GameHudPanelDef.create({});
    const html = el.innerHTML;
    assert(html.includes('data-bind="score"'), 'DOM contains score data-bind');
})();

(function testCreateHasElimsBinding() {
    const el = GameHudPanelDef.create({});
    const html = el.innerHTML;
    assert(html.includes('data-bind="elims"'), 'DOM contains elims data-bind');
})();

(function testScoreDefaultsToZero() {
    const el = GameHudPanelDef.create({});
    const html = el.innerHTML;
    assert(html.includes('>0<'), 'Score element defaults to 0');
})();

// ============================================================
// 3. Action buttons
// ============================================================

console.log('\n--- Action buttons ---');

(function testCreateHasBeginWarButton() {
    const el = GameHudPanelDef.create({});
    const html = el.innerHTML;
    assert(html.includes('data-action="begin-war"'), 'DOM contains BEGIN WAR action button');
    assert(html.includes('BEGIN WAR'), 'BEGIN WAR button has correct label');
})();

(function testCreateHasSpawnHostileButton() {
    const el = GameHudPanelDef.create({});
    const html = el.innerHTML;
    assert(html.includes('data-action="spawn-hostile"'), 'DOM contains SPAWN HOSTILE action button');
    assert(html.includes('SPAWN HOSTILE'), 'SPAWN HOSTILE button has correct label');
})();

(function testCreateHasResetButton() {
    const el = GameHudPanelDef.create({});
    const html = el.innerHTML;
    assert(html.includes('data-action="reset-game"'), 'DOM contains RESET action button');
    assert(html.includes('RESET'), 'RESET button has correct label');
})();

(function testBeginWarIsPrimary() {
    const el = GameHudPanelDef.create({});
    const html = el.innerHTML;
    assert(html.includes('panel-action-btn-primary'), 'BEGIN WAR button has primary styling');
})();

(function testActionsContainer() {
    const el = GameHudPanelDef.create({});
    const html = el.innerHTML;
    assert(html.includes('ghud-actions'), 'DOM contains actions container');
})();

// ============================================================
// 4. Labels
// ============================================================

console.log('\n--- Labels ---');

(function testPhaseLabel() {
    const el = GameHudPanelDef.create({});
    const html = el.innerHTML;
    assert(html.includes('PHASE'), 'DOM contains PHASE label');
})();

(function testWaveLabel() {
    const el = GameHudPanelDef.create({});
    const html = el.innerHTML;
    assert(html.includes('WAVE'), 'DOM contains WAVE label');
})();

(function testScoreLabel() {
    const el = GameHudPanelDef.create({});
    const html = el.innerHTML;
    assert(html.includes('SCORE'), 'DOM contains SCORE label');
})();

(function testElimsLabel() {
    const el = GameHudPanelDef.create({});
    const html = el.innerHTML;
    assert(html.includes('ELIMS'), 'DOM contains ELIMS label');
})();

// ============================================================
// 5. Layout structure
// ============================================================

console.log('\n--- Layout structure ---');

(function testHasStatusSection() {
    const el = GameHudPanelDef.create({});
    const html = el.innerHTML;
    assert(html.includes('ghud-status'), 'DOM has ghud-status section');
})();

(function testHasRowStructure() {
    const el = GameHudPanelDef.create({});
    const html = el.innerHTML;
    assert(html.includes('ghud-row'), 'DOM has ghud-row elements');
})();

(function testHasMonoClass() {
    const el = GameHudPanelDef.create({});
    const html = el.innerHTML;
    assert(html.includes('ghud-label mono'), 'Labels use mono class');
})();

(function testHasValueClass() {
    const el = GameHudPanelDef.create({});
    const html = el.innerHTML;
    assert(html.includes('ghud-value mono'), 'Values use mono class');
})();

// ============================================================
// 6. mount() wires subscriptions
// ============================================================

console.log('\n--- mount() ---');

(function testMountSubscribes() {
    const bodyEl = createMockElement('div');
    const panel = {
        def: GameHudPanelDef,
        w: 240,
        x: 0,
        manager: {
            container: createMockElement('div'),
            getPanel: () => null,
        },
        _unsubs: [],
        _applyTransform() {},
    };
    panel.manager.container.clientWidth = 1200;

    GameHudPanelDef.mount(bodyEl, panel);
    assert(panel._unsubs.length >= 4, 'mount() registers at least 4 subscriptions (phase, wave, score, elims), got ' + panel._unsubs.length);
})();

(function testMountCalculatesXPosition() {
    const bodyEl = createMockElement('div');
    const panel = {
        def: GameHudPanelDef,
        w: 240,
        x: 0,
        manager: {
            container: createMockElement('div'),
            getPanel: () => null,
        },
        _unsubs: [],
        _applyTransform() {},
    };
    panel.manager.container.clientWidth = 1200;

    GameHudPanelDef.mount(bodyEl, panel);
    // x = cw - w - 8 - offset(0) = 1200 - 240 - 8 - 0 = 952
    assert(panel.x === 952, 'mount() positions panel at top-right (expected 952, got ' + panel.x + ')');
})();

(function testMountDoesNotCrash() {
    const bodyEl = createMockElement('div');
    const panel = {
        def: GameHudPanelDef,
        w: 240,
        x: 0,
        manager: {
            container: createMockElement('div'),
            getPanel: () => null,
        },
        _unsubs: [],
        _applyTransform() {},
    };
    panel.manager.container.clientWidth = 1200;

    let threw = false;
    try {
        GameHudPanelDef.mount(bodyEl, panel);
    } catch (e) {
        threw = true;
    }
    assert(!threw, 'mount() does not crash');
})();

(function testMountWithAlertsPanel() {
    const bodyEl = createMockElement('div');
    const panel = {
        def: GameHudPanelDef,
        w: 240,
        x: 0,
        manager: {
            container: createMockElement('div'),
            getPanel: (id) => {
                if (id === 'alerts') return { _visible: true, w: 280 };
                return null;
            },
        },
        _unsubs: [],
        _applyTransform() {},
    };
    panel.manager.container.clientWidth = 1200;

    GameHudPanelDef.mount(bodyEl, panel);
    // x = 1200 - 240 - 8 - (280 + 8) = 664
    assert(panel.x === 664, 'mount() offsets for visible alerts panel (expected 664, got ' + panel.x + ')');
})();

// ============================================================
// 7. unmount() exists and does not crash
// ============================================================

console.log('\n--- unmount() ---');

(function testUnmountDoesNotCrash() {
    const bodyEl = createMockElement('div');
    let threw = false;
    try {
        GameHudPanelDef.unmount(bodyEl);
    } catch (e) {
        threw = true;
    }
    assert(!threw, 'unmount() does not throw');
})();

// ============================================================
// 8. Store notification does not crash
// ============================================================

console.log('\n--- Store notification ---');

(function testStorePhaseNotification() {
    const bodyEl = createMockElement('div');
    const panel = {
        def: GameHudPanelDef,
        w: 240,
        x: 0,
        manager: {
            container: createMockElement('div'),
            getPanel: () => null,
        },
        _unsubs: [],
        _applyTransform() {},
    };
    panel.manager.container.clientWidth = 1200;

    GameHudPanelDef.mount(bodyEl, panel);

    const TritiumStore = vm.runInContext('TritiumStore', ctx);
    let threw = false;
    try {
        TritiumStore.set('game.phase', 'active');
    } catch (e) {
        threw = true;
    }
    assert(!threw, 'Store game.phase notification does not crash');
})();

(function testStoreWaveNotification() {
    const bodyEl = createMockElement('div');
    const panel = {
        def: GameHudPanelDef,
        w: 240,
        x: 0,
        manager: {
            container: createMockElement('div'),
            getPanel: () => null,
        },
        _unsubs: [],
        _applyTransform() {},
    };
    panel.manager.container.clientWidth = 1200;

    GameHudPanelDef.mount(bodyEl, panel);

    const TritiumStore = vm.runInContext('TritiumStore', ctx);
    let threw = false;
    try {
        TritiumStore.set('game.wave', 5);
    } catch (e) {
        threw = true;
    }
    assert(!threw, 'Store game.wave notification does not crash');
})();

(function testStoreScoreNotification() {
    const bodyEl = createMockElement('div');
    const panel = {
        def: GameHudPanelDef,
        w: 240,
        x: 0,
        manager: {
            container: createMockElement('div'),
            getPanel: () => null,
        },
        _unsubs: [],
        _applyTransform() {},
    };
    panel.manager.container.clientWidth = 1200;

    GameHudPanelDef.mount(bodyEl, panel);

    const TritiumStore = vm.runInContext('TritiumStore', ctx);
    let threw = false;
    try {
        TritiumStore.set('game.score', 1500);
    } catch (e) {
        threw = true;
    }
    assert(!threw, 'Store game.score notification does not crash');
})();

// ============================================================
// Summary
// ============================================================

console.log('\n' + '='.repeat(40));
console.log(`Results: ${passed} passed, ${failed} failed`);
console.log('='.repeat(40));
process.exit(failed > 0 ? 1 : 0);
