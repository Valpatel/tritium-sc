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
    assert(GameHudPanelDef.defaultSize.w === 260, 'defaultSize.w is 260');
    assert(GameHudPanelDef.defaultSize.h === 360, 'defaultSize.h is 360');
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
// 12. Combat status event wiring (orphan events now subscribed)
// ============================================================

console.log('\n--- Combat status event wiring ---');

// The game-hud now subscribes to combat:ammo_low, combat:ammo_depleted,
// combat:weapon_jam, combat:neutralized, ability:activated, ability:expired,
// npc:thought, npc:alliance_change — emitting toast:show for each.

(function testGameHudSourceHasCombatStatusEvents() {
    const source = fs.readFileSync(__dirname + '/../../frontend/js/command/panels/game-hud.js', 'utf8');
    const events = [
        'combat:ammo_low',
        'combat:ammo_depleted',
        'combat:weapon_jam',
        'combat:neutralized',
        'ability:activated',
        'ability:expired',
        'npc:thought',
        'npc:alliance_change',
    ];
    for (const evt of events) {
        assert(source.includes(`'${evt}'`), `game-hud subscribes to ${evt}`);
    }
})();

(function testCombatStatusEventsEmitToast() {
    const source = fs.readFileSync(__dirname + '/../../frontend/js/command/panels/game-hud.js', 'utf8');
    // Each combat status event handler should emit toast:show
    // Count EventBus.on calls that also contain EventBus.emit('toast:show'
    const blocks = source.split("EventBus.on('combat:ammo_low'");
    assert(blocks.length >= 2, 'combat:ammo_low subscription exists');
    // The subscription block should contain toast:show
    if (blocks.length >= 2) {
        assert(blocks[1].includes("toast:show"), 'combat:ammo_low emits toast:show');
    }
})();

(function testAmmoLowToastContainsUnitName() {
    const source = fs.readFileSync(__dirname + '/../../frontend/js/command/panels/game-hud.js', 'utf8');
    // The ammo_low handler should use d.unit_name
    const block = source.split("combat:ammo_low")[1] || '';
    assert(block.includes('unit_name'), 'combat:ammo_low handler uses unit_name');
    assert(block.includes('AMMO LOW'), 'combat:ammo_low handler shows AMMO LOW message');
})();

(function testAbilityActivatedToastFormat() {
    const source = fs.readFileSync(__dirname + '/../../frontend/js/command/panels/game-hud.js', 'utf8');
    const block = source.split("ability:activated")[1] || '';
    assert(block.includes('ability_name'), 'ability:activated handler uses ability_name');
    assert(block.includes('ACTIVATED'), 'ability:activated handler shows ACTIVATED message');
})();

(function testNpcThoughtToastFormat() {
    const source = fs.readFileSync(__dirname + '/../../frontend/js/command/panels/game-hud.js', 'utf8');
    const block = source.split("npc:thought")[1] || '';
    assert(block.includes('d.thought'), 'npc:thought handler uses d.thought');
    assert(block.includes('d.name'), 'npc:thought handler uses d.name');
})();

(function testAllianceChangeToastFormat() {
    const source = fs.readFileSync(__dirname + '/../../frontend/js/command/panels/game-hud.js', 'utf8');
    const block = source.split("npc:alliance_change")[1] || '';
    assert(block.includes('new_alliance'), 'alliance_change handler uses new_alliance');
})();

(function testMountSubscriptionCount() {
    // Re-mount and verify subscriptions increased
    const bodyEl = createMockElement('div');
    const panel = {
        def: GameHudPanelDef,
        w: 400,
        h: 600,
        x: 0,
        y: 0,
        manager: {
            container: createMockElement('div'),
            getPanel: () => null,
        },
        _unsubs: [],
        _applyTransform() {},
    };
    panel.manager.container.clientHeight = 800;

    GameHudPanelDef.mount(bodyEl, panel);
    // Should have many subscriptions: store listeners + combat events + mission events + combat status events + dashboard interval
    // Original: ~12 (store + combat + mission + interval)
    // New: +8 combat status event handlers
    assert(panel._unsubs.length >= 15, 'mount() registers at least 15 subscriptions (got ' + panel._unsubs.length + ')');
})();


// ============================================================
// Mission-mode-specific metrics rendering
// ============================================================

// Test: game-hud.js contains mission-metrics section
(() => {
    const source = fs.readFileSync('frontend/js/command/panels/game-hud.js', 'utf8');
    assert(source.includes('data-section="mission-metrics"'),
        'game-hud.js contains mission-metrics section element');
})();

// Test: game-hud.js reads modeType from store
(() => {
    const source = fs.readFileSync('frontend/js/command/panels/game-hud.js', 'utf8');
    assert(source.includes("TritiumStore.get('game.modeType')"),
        'game-hud.js reads game.modeType from store');
})();

// Test: game-hud.js reads civil_unrest-specific store keys
(() => {
    const source = fs.readFileSync('frontend/js/command/panels/game-hud.js', 'utf8');
    assert(source.includes("TritiumStore.get('game.deEscalationScore')"),
        'game-hud.js reads deEscalationScore');
    assert(source.includes("TritiumStore.get('game.civilianHarmCount')"),
        'game-hud.js reads civilianHarmCount');
    assert(source.includes("TritiumStore.get('game.civilianHarmLimit')"),
        'game-hud.js reads civilianHarmLimit');
})();

// Test: game-hud.js reads infrastructure health store keys
(() => {
    const source = fs.readFileSync('frontend/js/command/panels/game-hud.js', 'utf8');
    assert(source.includes("TritiumStore.get('game.infrastructureHealth')"),
        'game-hud.js reads infrastructureHealth');
    assert(source.includes("TritiumStore.get('game.infrastructureMax')"),
        'game-hud.js reads infrastructureMax');
})();

// Test: game-hud.js renders drone_swarm mode
(() => {
    const source = fs.readFileSync('frontend/js/command/panels/game-hud.js', 'utf8');
    assert(source.includes("modeType === 'drone_swarm'"),
        'game-hud.js has drone_swarm mode rendering');
})();

// Test: game-hud.js renders civil_unrest mode
(() => {
    const source = fs.readFileSync('frontend/js/command/panels/game-hud.js', 'utf8');
    assert(source.includes("modeType === 'civil_unrest'"),
        'game-hud.js has civil_unrest mode rendering');
})();

// Test: _renderMissionMetrics is called in refreshDashboard
(() => {
    const source = fs.readFileSync('frontend/js/command/panels/game-hud.js', 'utf8');
    assert(source.includes('_renderMissionMetrics()'),
        'refreshDashboard calls _renderMissionMetrics');
})();


// ============================================================
// Headless bridge event whitelist
// ============================================================

// Test: ws.py headless bridge includes instigator_identified
(() => {
    const source = fs.readFileSync('src/app/routers/ws.py', 'utf8');
    assert(source.includes('"instigator_identified"'),
        'ws.py headless bridge whitelists instigator_identified');
})();

// Test: ws.py headless bridge includes emp_activated
(() => {
    const source = fs.readFileSync('src/app/routers/ws.py', 'utf8');
    assert(source.includes('"emp_activated"'),
        'ws.py headless bridge whitelists emp_activated');
})();


// ============================================================
// Game HUD: difficulty multiplier + wave name display
// ============================================================

(function testGameHudHasDifficultyDisplay() {
    const src = fs.readFileSync(__dirname + '/../../frontend/js/command/panels/game-hud.js', 'utf8');
    assert(
        src.includes('data-bind="difficulty"'),
        'Game HUD has a data-bind="difficulty" element for difficulty multiplier'
    );
    assert(
        src.includes("game.difficultyMultiplier"),
        'Game HUD subscribes to game.difficultyMultiplier store changes'
    );
})();

(function testGameHudHasWaveNameDisplay() {
    const src = fs.readFileSync(__dirname + '/../../frontend/js/command/panels/game-hud.js', 'utf8');
    assert(
        src.includes('data-bind="waveName"'),
        'Game HUD has a data-bind="waveName" element for wave name'
    );
    assert(
        src.includes("game.waveName"),
        'Game HUD subscribes to game.waveName store changes'
    );
})();

(function testDifficultyDisplayColorCoding() {
    const src = fs.readFileSync(__dirname + '/../../frontend/js/command/panels/game-hud.js', 'utf8');
    // Difficulty display should color-code: green for easy, yellow for normal, red for hard
    const diffIdx = src.indexOf("game.difficultyMultiplier");
    assert(diffIdx >= 0, 'difficulty subscriber exists');
    const diffBlock = src.slice(diffIdx, diffIdx + 500);
    assert(diffBlock.includes('#05ffa1'), 'difficulty display uses green for easy (<0.8)');
    assert(diffBlock.includes('#ff2a6d'), 'difficulty display uses red for hard (>1.3)');
})();

// ============================================================
// Event handler wiring tests
// ============================================================
console.log('\n--- Event handler wiring (static analysis) ---');

(function testCombatEventSubscriptions() {
    const src = fs.readFileSync(__dirname + '/../../frontend/js/command/panels/game-hud.js', 'utf8');

    // Combat events
    assert(src.includes("'combat:projectile'"), 'mount subscribes to combat:projectile');
    assert(src.includes("'combat:hit'"), 'mount subscribes to combat:hit');
    assert(src.includes("'combat:elimination'"), 'mount subscribes to combat:elimination');
    assert(src.includes("'game:wave_start'"), 'mount subscribes to game:wave_start');
    assert(src.includes("'game:state'"), 'mount subscribes to game:state');

    // Combat status events
    assert(src.includes("'combat:ammo_low'"), 'mount subscribes to combat:ammo_low');
    assert(src.includes("'combat:ammo_depleted'"), 'mount subscribes to combat:ammo_depleted');
    assert(src.includes("'combat:weapon_jam'"), 'mount subscribes to combat:weapon_jam');
    assert(src.includes("'combat:neutralized'"), 'mount subscribes to combat:neutralized');
    assert(src.includes("'ability:activated'"), 'mount subscribes to ability:activated');
    assert(src.includes("'ability:expired'"), 'mount subscribes to ability:expired');
    assert(src.includes("'npc:thought'"), 'mount subscribes to npc:thought');
    assert(src.includes("'npc:alliance_change'"), 'mount subscribes to npc:alliance_change');

    // Mission events
    assert(src.includes("'mission:bomber_detonation'"), 'mount subscribes to mission:bomber_detonation');
    assert(src.includes("'mission:emp_activated'"), 'mount subscribes to mission:emp_activated');
    assert(src.includes("'mission:instigator_identified'"), 'mount subscribes to mission:instigator_identified');
    assert(src.includes("'mission:infrastructure_overwhelmed'"), 'mount subscribes to mission:infrastructure_overwhelmed');
})();

// ============================================================
// Event handler behavior tests (functional via mount)
// ============================================================
console.log('\n--- Event handler behavior ---');

(function testCombatEventsUpdateTracker() {
    // Mount the panel and trigger events through EventBus
    const bodyEl = GameHudPanelDef.create({ def: GameHudPanelDef });
    const panel = {
        def: GameHudPanelDef,
        _unsubs: [],
        w: 260,
        x: 0,
        _applyTransform() {},
        manager: {
            container: { clientWidth: 1200 },
            getPanel() { return null; },
        },
    };

    // Get EventBus reference
    const EB = vm.runInContext('EventBus', ctx);
    const Store = vm.runInContext('TritiumStore', ctx);

    // Set phase to idle (before mount) so dashboard refresh doesn't crash
    Store.game.phase = 'idle';
    Store.game.wave = 0;
    Store.game.totalWaves = 10;
    Store.game.score = 0;
    Store.game.eliminations = 0;

    GameHudPanelDef.mount(bodyEl, panel);

    // Verify unsubs were registered
    assert(panel._unsubs.length > 0, 'mount registers unsub callbacks');

    // Fire combat events
    EB.emit('combat:projectile', {});
    EB.emit('combat:projectile', {});
    EB.emit('combat:hit', { damage: 25 });
    EB.emit('combat:elimination', {});

    // These should have been recorded by the CombatStatsTracker
    // We can't directly access the tracker, but we verified the wiring above

    // Fire combat status events that emit toasts
    let toastEvents = [];
    const origOn = EB.on;
    EB.on('toast:show', (d) => { toastEvents.push(d); });

    EB.emit('combat:ammo_low', { unit_name: 'Alpha Turret' });
    assert(toastEvents.length >= 1, 'combat:ammo_low emits toast:show');
    assert(toastEvents[0].message.includes('AMMO LOW'), 'ammo_low toast has correct message');
    assert(toastEvents[0].message.includes('Alpha Turret'), 'ammo_low toast includes unit name');

    toastEvents = [];
    EB.emit('combat:ammo_depleted', { unit_name: 'Bravo Rover' });
    assert(toastEvents.length >= 1, 'combat:ammo_depleted emits toast:show');
    assert(toastEvents[0].message.includes('AMMO DEPLETED'), 'ammo_depleted toast message correct');

    toastEvents = [];
    EB.emit('combat:weapon_jam', {});
    assert(toastEvents.length >= 1, 'combat:weapon_jam emits toast:show');
    assert(toastEvents[0].message.includes('WEAPON JAM'), 'weapon_jam toast message correct');
    assert(toastEvents[0].message.includes('Unit'), 'weapon_jam defaults to "Unit" when no name');

    toastEvents = [];
    EB.emit('combat:neutralized', { target_name: 'Hostile-01' });
    assert(toastEvents.length >= 1, 'combat:neutralized emits toast:show');
    assert(toastEvents[0].message.includes('NEUTRALIZED'), 'neutralized toast message correct');

    toastEvents = [];
    EB.emit('ability:activated', { ability_name: 'speed_boost', unit_name: 'Alpha' });
    assert(toastEvents.length >= 1, 'ability:activated emits toast:show');
    assert(toastEvents[0].message.includes('SPEED BOOST'), 'ability name uppercased with underscores replaced');
    assert(toastEvents[0].message.includes('Alpha'), 'ability toast includes unit name');

    toastEvents = [];
    EB.emit('ability:expired', { ability_name: 'shield' });
    assert(toastEvents.length >= 1, 'ability:expired emits toast:show');
    assert(toastEvents[0].message.includes('SHIELD'), 'expired ability name uppercased');
    assert(toastEvents[0].message.includes('expired'), 'expired toast says expired');

    toastEvents = [];
    EB.emit('npc:thought', { name: 'Civilian Bob', thought: 'This is scary' });
    assert(toastEvents.length >= 1, 'npc:thought emits toast:show');
    assert(toastEvents[0].message.includes('Civilian Bob'), 'npc thought includes name');
    assert(toastEvents[0].message.includes('This is scary'), 'npc thought includes text');

    toastEvents = [];
    EB.emit('npc:thought', {}); // No name/thought — should not emit
    assert(toastEvents.length === 0, 'npc:thought with missing data does NOT emit toast');

    toastEvents = [];
    EB.emit('npc:alliance_change', { unit_name: 'Villager', new_alliance: 'hostile' });
    assert(toastEvents.length >= 1, 'npc:alliance_change emits toast:show');
    assert(toastEvents[0].message.includes('Villager'), 'alliance change includes unit name');
    assert(toastEvents[0].message.includes('hostile'), 'alliance change includes new alliance');

    // Cleanup
    panel._unsubs.forEach(fn => { if (typeof fn === 'function') fn(); });
})();

// ============================================================
// Button handlers — static verification
// ============================================================
console.log('\n--- Button handlers ---');

(function testBeginButtonWiring() {
    const src = fs.readFileSync(__dirname + '/../../frontend/js/command/panels/game-hud.js', 'utf8');
    assert(src.includes("'/api/game/begin'"), 'BEGIN button calls /api/game/begin');
    assert(src.includes("method: 'POST'"), 'BEGIN button uses POST method');
})();

(function testSpawnButtonWiring() {
    const src = fs.readFileSync(__dirname + '/../../frontend/js/command/panels/game-hud.js', 'utf8');
    assert(src.includes("'/api/amy/simulation/spawn'"), 'SPAWN button calls /api/amy/simulation/spawn');
    assert(src.includes("'Hostile spawned'"), 'SPAWN success shows Hostile spawned toast');
    assert(src.includes("'Spawn failed: network error'"), 'SPAWN catch shows network error toast');
})();

(function testResetButtonWiring() {
    const src = fs.readFileSync(__dirname + '/../../frontend/js/command/panels/game-hud.js', 'utf8');
    assert(src.includes("'/api/game/reset'"), 'RESET button calls /api/game/reset');
    assert(src.includes('warCombatReset'), 'RESET calls warCombatReset if available');
    assert(src.includes('tracker.reset()'), 'RESET resets combat tracker');
})();

// ============================================================
// Store subscription behavior
// ============================================================
console.log('\n--- Store subscriptions ---');

(function testStorePhaseSubscription() {
    const src = fs.readFileSync(__dirname + '/../../frontend/js/command/panels/game-hud.js', 'utf8');
    assert(src.includes("'game.phase'"), 'subscribes to game.phase');
    assert(src.includes("'game.wave'"), 'subscribes to game.wave');
    assert(src.includes("'game.waveName'"), 'subscribes to game.waveName');
    assert(src.includes("'game.score'"), 'subscribes to game.score');
    assert(src.includes("'game.eliminations'"), 'subscribes to game.eliminations');
    assert(src.includes("'game.difficultyMultiplier'"), 'subscribes to game.difficultyMultiplier');
})();

// ============================================================
// Dashboard refresh interval
// ============================================================
console.log('\n--- Dashboard refresh interval ---');

(function testDashboardInterval() {
    const src = fs.readFileSync(__dirname + '/../../frontend/js/command/panels/game-hud.js', 'utf8');
    assert(src.includes('setInterval(refreshDashboard, 2000)'), 'dashboard refreshes every 2000ms');
    assert(src.includes('clearInterval(dashboardInterval)'), 'dashboard interval cleaned up on unmount');
})();

// ============================================================
// Upgrade picker flow verification
// ============================================================
console.log('\n--- Upgrade picker flow ---');

(function testUpgradePickerExists() {
    const src = fs.readFileSync(__dirname + '/../../frontend/js/command/panels/game-hud.js', 'utf8');
    assert(src.includes('function showUpgradePicker'), 'showUpgradePicker function exists');
    assert(src.includes('function hideUpgradePicker'), 'hideUpgradePicker function exists');
    assert(src.includes("'/api/game/upgrades'"), 'upgrade picker fetches from /api/game/upgrades');
    assert(src.includes("'/api/game/upgrade'"), 'upgrade picker POSTs to /api/game/upgrade');
    assert(src.includes('_selectedUpgradeId'), 'upgrade picker tracks selected upgrade');
    assert(src.includes('_cachedUpgrades'), 'upgrade picker caches upgrade list');
})();

// ============================================================
// Mission metric rendering
// ============================================================
console.log('\n--- Mission metrics ---');

(function testMissionMetricsExist() {
    const src = fs.readFileSync(__dirname + '/../../frontend/js/command/panels/game-hud.js', 'utf8');
    assert(src.includes('_renderMissionMetrics'), '_renderMissionMetrics function exists');
    assert(src.includes('civil_unrest'), 'mission metrics handle civil_unrest mode');
    assert(src.includes('drone_swarm'), 'mission metrics handle drone_swarm mode');
    assert(src.includes('de-escalation') || src.includes('deEscalation') || src.includes('de_escalation'),
        'civil unrest tracks de-escalation metric');
})();

// ============================================================
// Visibility logic
// ============================================================
console.log('\n--- Visibility logic ---');

(function testVisibilityLogic() {
    const src = fs.readFileSync(__dirname + '/../../frontend/js/command/panels/game-hud.js', 'utf8');
    assert(src.includes('function updateVisibility'), 'updateVisibility function exists');
    // BEGIN button visible in idle/setup
    assert(src.includes("'idle'") && src.includes("'setup'"), 'visibility checks idle and setup phases');
    // RESET button visible in victory/defeat
    assert(src.includes("'victory'") && src.includes("'defeat'"), 'visibility checks victory and defeat phases');
})();

// ============================================================
// Game state reset handler
// ============================================================
console.log('\n--- Game state reset ---');

(function testGameStateResetHandler() {
    const src = fs.readFileSync(__dirname + '/../../frontend/js/command/panels/game-hud.js', 'utf8');
    // On game:state active, wave 1 — tracker should reset
    const stateBlock = src.match(/game:state.*?tracker\.reset/s);
    assert(stateBlock !== null, 'game:state handler resets tracker on wave 1');
    assert(src.includes('_previousMorale = 1.0'), 'game:state resets _previousMorale');
})();

// ============================================================
// Wave start handler
// ============================================================
console.log('\n--- Wave start ---');

(function testWaveStartHandler() {
    const src = fs.readFileSync(__dirname + '/../../frontend/js/command/panels/game-hud.js', 'utf8');
    const waveBlock = src.match(/game:wave_start.*?_waveStartTime/s);
    assert(waveBlock !== null, 'wave_start handler sets _waveStartTime');
    assert(src.includes('_waveHostileTotal'), 'wave_start captures hostile count');
})();

// ============================================================
// Countdown display tests
// ============================================================
console.log('\n--- Countdown display ---');

(function testCountdownElementExists() {
    const src = fs.readFileSync(__dirname + '/../../frontend/js/command/panels/game-hud.js', 'utf8');
    assert(
        src.includes('data-bind="countdown"'),
        'Game HUD has a data-bind="countdown" element'
    );
})();

(function testCountdownStoreSubscription() {
    const src = fs.readFileSync(__dirname + '/../../frontend/js/command/panels/game-hud.js', 'utf8');
    assert(
        src.includes("game.countdown"),
        'Game HUD subscribes to game.countdown store key'
    );
})();

(function testCountdownShownDuringCountdownPhase() {
    const src = fs.readFileSync(__dirname + '/../../frontend/js/command/panels/game-hud.js', 'utf8');
    // Countdown element should be shown when phase === 'countdown'
    assert(
        src.includes("'countdown'") && src.includes('countdownEl'),
        'Countdown display is wired to countdown phase'
    );
})();

// ============================================================
// Summary
// ============================================================

console.log('\n' + '='.repeat(40));
console.log(`Results: ${passed} passed, ${failed} failed`);
console.log('='.repeat(40));
process.exit(failed > 0 ? 1 : 0);
