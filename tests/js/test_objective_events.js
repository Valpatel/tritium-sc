// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
/**
 * TRITIUM-SC Objective Events -- WebSocket handler tests
 * Tests that bonus_objective_completed messages are correctly routed
 * to warHudCompleteBonusObjective and the frontend EventBus.
 * Run: node tests/js/test_objective_events.js
 */

const fs = require('fs');
const vm = require('vm');

let passed = 0, failed = 0;
function assert(cond, msg) {
    if (!cond) { console.error('FAIL:', msg); failed++; }
    else { console.log('PASS:', msg); passed++; }
}
function assertEqual(a, b, msg) {
    assert(a === b, msg + ` (got ${JSON.stringify(a)}, expected ${JSON.stringify(b)})`);
}

// ============================================================
// Mock WebSocket
// ============================================================

const createdSockets = [];

class MockWebSocket {
    static CONNECTING = 0;
    static OPEN = 1;
    static CLOSING = 2;
    static CLOSED = 3;

    constructor(url) {
        this.url = url;
        this.readyState = MockWebSocket.CONNECTING;
        this.onopen = null;
        this.onclose = null;
        this.onerror = null;
        this.onmessage = null;
        this._sent = [];
        createdSockets.push(this);
    }

    send(data) { this._sent.push(data); }
    close() { this.readyState = MockWebSocket.CLOSED; }

    _simulateOpen() {
        this.readyState = MockWebSocket.OPEN;
        if (this.onopen) this.onopen({});
    }

    _simulateMessage(data) {
        if (this.onmessage) {
            this.onmessage({ data: JSON.stringify(data) });
        }
    }
}

// ============================================================
// Load source files
// ============================================================

const storeCode = fs.readFileSync(__dirname + '/../../src/frontend/js/command/store.js', 'utf8');
const eventsCode = fs.readFileSync(__dirname + '/../../../tritium-lib/web/events.js', 'utf8');
const libWsCode = fs.readFileSync(__dirname + '/../../../tritium-lib/web/websocket.js', 'utf8');
const wsCode = fs.readFileSync(__dirname + '/../../src/frontend/js/command/websocket.js', 'utf8');
const hudCode = fs.readFileSync(__dirname + '/../../src/frontend/js/war-hud.js', 'utf8');

// Bridge object for capturing EventBus emissions
let _bridge = {};

function createFreshContext() {
    createdSockets.length = 0;
    _bridge = {};

    const ctx = vm.createContext({
        Math, Date, console, Map, Set, Array, Object, Number, String, JSON,
        Infinity, undefined, Error, TypeError,
        setTimeout: (fn, ms) => 999,
        clearTimeout: () => {},
        setInterval: (fn, ms) => 999,
        clearInterval: () => {},
        fetch: () => Promise.resolve({ ok: true, json: () => Promise.resolve({}) }),
        WebSocket: MockWebSocket,
        _bridge,
        window: {
            location: { protocol: 'http:', host: 'localhost:8000' },
        },
        document: {
            getElementById(id) {
                return {
                    style: { display: '', opacity: '' },
                    textContent: '', innerHTML: '', className: '',
                    classList: { _classes: [], add() {}, remove() {} },
                    onclick: null, offsetWidth: 100,
                };
            },
            createElement(tag) {
                const el = { _text: '' };
                Object.defineProperty(el, 'textContent', {
                    get() { return el._text; },
                    set(v) { el._text = String(v); }
                });
                Object.defineProperty(el, 'innerHTML', {
                    get() { return el._text; }
                });
                return el;
            },
        },
        warState: {
            audioCtx: null, targets: [], selectedTargets: [], effects: [],
            dispatchArrows: [], stats: { eliminations: 0, breaches: 0, dispatches: 0 },
        },
        warCombatReset: () => {},
        warCombatAddEliminationEffect: () => {},
        warCombatAddProjectile: () => {},
        warCombatAddHitEffect: () => {},
        warCombatAddEliminationStreakEffect: () => {},
    });

    // Load war-hud.js (defines warHudCompleteBonusObjective, etc.)
    const hudStripped = hudCode + '\nwindow._hudState = _hudState;\n';
    vm.runInContext(hudStripped, ctx);

    // Load store.js (defines TritiumStore)
    vm.runInContext(storeCode.replace(/^export\s+/gm, '').replace(/^import\s+.*$/gm, ''), ctx);

    // Load events.js (defines EventBus)
    vm.runInContext(eventsCode.replace(/^export\s+/gm, ''), ctx);

    // Load lib websocket base class (strip export)
    vm.runInContext(libWsCode.replace(/^export\s+/gm, ''), ctx);

    // Load websocket.js (defines WebSocketManager — extends TritiumWebSocket)
    const wsStripped = wsCode
        .replace(/^import\s+.*$/gm, '')
        .replace(/^export\s+/gm, '');
    vm.runInContext(wsStripped, ctx);

    return ctx;
}

function listenEvent(ctx, eventName) {
    vm.runInContext(
        `EventBus.on("${eventName}", function(d) {
            if (!_bridge["${eventName}"]) _bridge["${eventName}"] = [];
            _bridge["${eventName}"].push(d);
        })`,
        ctx
    );
}

// ============================================================
// Tests
// ============================================================

console.log('\n--- Objective Event Routing ---');

// Test 1: amy_bonus_objective_completed calls warHudCompleteBonusObjective
(function testAmyPrefixedCompletion() {
    const ctx = createFreshContext();
    listenEvent(ctx, 'objective:completed');

    // Set up objectives in HUD
    vm.runInContext(`
        warHudSetBonusObjectives([
            { name: 'No casualties', description: 'test', reward: 1000 },
        ]);
    `, ctx);

    const ws = vm.runInContext('new WebSocketManager()', ctx);
    ws.connect();
    const sock = createdSockets[createdSockets.length - 1];
    sock._simulateOpen();

    sock._simulateMessage({
        type: 'amy_bonus_objective_completed',
        data: { name: 'No casualties', reward: 1000 },
    });

    // Check HUD state
    const completed = vm.runInContext(
        '_hudState.bonusObjectives.find(o => o.name === "No casualties").completed',
        ctx
    );
    assert(completed === true, 'amy_bonus_objective_completed marks HUD objective completed');

    // Check EventBus emission
    const events = _bridge['objective:completed'];
    assert(events && events.length >= 1, 'objective:completed emitted on EventBus');
    if (events && events.length > 0) {
        assertEqual(events[0].name, 'No casualties', 'objective:completed has correct name');
        assertEqual(events[0].reward, 1000, 'objective:completed has correct reward');
    }
})();

// Test 2: Non-prefixed bonus_objective_completed also works
(function testNonPrefixedCompletion() {
    const ctx = createFreshContext();
    listenEvent(ctx, 'objective:completed');

    vm.runInContext(`
        warHudSetBonusObjectives([
            { name: 'EMP Master', description: 'test', reward: 500 },
        ]);
    `, ctx);

    const ws = vm.runInContext('new WebSocketManager()', ctx);
    ws.connect();
    const sock = createdSockets[createdSockets.length - 1];
    sock._simulateOpen();

    sock._simulateMessage({
        type: 'bonus_objective_completed',
        data: { name: 'EMP Master', reward: 500 },
    });

    const completed = vm.runInContext(
        '_hudState.bonusObjectives.find(o => o.name === "EMP Master").completed',
        ctx
    );
    assert(completed === true, 'non-prefixed bonus_objective_completed marks HUD objective');

    const events = _bridge['objective:completed'];
    assert(events && events.length >= 1, 'objective:completed emitted for non-prefixed event');
})();

// Test 3: Multiple objective completions
(function testMultipleCompletions() {
    const ctx = createFreshContext();
    listenEvent(ctx, 'objective:completed');

    vm.runInContext(`
        warHudSetBonusObjectives([
            { name: 'Perfect Defense', description: 'test', reward: 2000 },
            { name: 'Flawless AA', description: 'test', reward: 1000 },
            { name: 'No Bombers Through', description: 'test', reward: 1000 },
        ]);
    `, ctx);

    const ws = vm.runInContext('new WebSocketManager()', ctx);
    ws.connect();
    const sock = createdSockets[createdSockets.length - 1];
    sock._simulateOpen();

    sock._simulateMessage({
        type: 'amy_bonus_objective_completed',
        data: { name: 'Perfect Defense', reward: 2000 },
    });
    sock._simulateMessage({
        type: 'amy_bonus_objective_completed',
        data: { name: 'Flawless AA', reward: 1000 },
    });

    const pdCompleted = vm.runInContext(
        '_hudState.bonusObjectives.find(o => o.name === "Perfect Defense").completed',
        ctx
    );
    const aaCompleted = vm.runInContext(
        '_hudState.bonusObjectives.find(o => o.name === "Flawless AA").completed',
        ctx
    );
    const nbCompleted = vm.runInContext(
        '_hudState.bonusObjectives.find(o => o.name === "No Bombers Through").completed',
        ctx
    );

    assert(pdCompleted === true, 'Perfect Defense marked completed');
    assert(aaCompleted === true, 'Flawless AA marked completed');
    assert(nbCompleted === false, 'No Bombers Through still not completed');

    const events = _bridge['objective:completed'];
    assertEqual(events ? events.length : 0, 2, 'Two objective:completed events emitted');
})();

// Test 4: warHudCompleteBonusObjective called with correct data
(function testHudFunctionReceivesData() {
    const ctx = createFreshContext();

    vm.runInContext(`
        warHudSetBonusObjectives([
            { name: 'Speed run', description: 'Under 5 min', reward: 500 },
        ]);
    `, ctx);

    const ws = vm.runInContext('new WebSocketManager()', ctx);
    ws.connect();
    const sock = createdSockets[createdSockets.length - 1];
    sock._simulateOpen();

    sock._simulateMessage({
        type: 'amy_bonus_objective_completed',
        data: { name: 'Speed run', reward: 500 },
    });

    const completed = vm.runInContext(
        '_hudState.bonusObjectives.find(o => o.name === "Speed run").completed',
        ctx
    );
    assert(completed === true, 'warHudCompleteBonusObjective called with correct name');
})();

// Test 5: Unknown objective name does not crash
(function testUnknownObjectiveName() {
    const ctx = createFreshContext();

    vm.runInContext(`
        warHudSetBonusObjectives([
            { name: 'No casualties', description: 'test', reward: 1000 },
        ]);
    `, ctx);

    const ws = vm.runInContext('new WebSocketManager()', ctx);
    ws.connect();
    const sock = createdSockets[createdSockets.length - 1];
    sock._simulateOpen();

    // Send completion for nonexistent objective -- should not crash
    sock._simulateMessage({
        type: 'amy_bonus_objective_completed',
        data: { name: 'Nonexistent', reward: 999 },
    });

    const ncCompleted = vm.runInContext(
        '_hudState.bonusObjectives.find(o => o.name === "No casualties").completed',
        ctx
    );
    assert(ncCompleted === false, 'Existing objective unaffected by unknown completion');
    assert(true, 'Unknown objective name does not crash');
})();

// Test 6: warHudSetBonusObjectives initializes correctly
(function testSetBonusObjectives() {
    const ctx = createFreshContext();

    vm.runInContext(`
        warHudSetBonusObjectives([
            { name: 'A', description: 'desc A', reward: 100 },
            { name: 'B', reward: 200 },
        ]);
    `, ctx);

    const count = vm.runInContext('_hudState.bonusObjectives.length', ctx);
    assertEqual(count, 2, 'warHudSetBonusObjectives stores correct count');

    const aCompleted = vm.runInContext(
        '_hudState.bonusObjectives.find(o => o.name === "A").completed', ctx
    );
    assert(aCompleted === false, 'Objectives start as not completed');

    const bReward = vm.runInContext(
        '_hudState.bonusObjectives.find(o => o.name === "B").reward', ctx
    );
    assertEqual(bReward, 200, 'Objective reward stored correctly');
})();

// Test 7: warHudSetBonusObjectives with null/empty clears
(function testSetBonusObjectivesEmpty() {
    const ctx = createFreshContext();

    vm.runInContext('warHudSetBonusObjectives(null);', ctx);
    const count1 = vm.runInContext('_hudState.bonusObjectives.length', ctx);
    assertEqual(count1, 0, 'null clears bonus objectives');

    vm.runInContext('warHudSetBonusObjectives([]);', ctx);
    const count2 = vm.runInContext('_hudState.bonusObjectives.length', ctx);
    assertEqual(count2, 0, 'empty array clears bonus objectives');
})();

// ============================================================
// Summary
// ============================================================

console.log(`\n--- Results: ${passed} passed, ${failed} failed ---`);
process.exit(failed > 0 ? 1 : 0);
