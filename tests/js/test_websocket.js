// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
/**
 * TRITIUM-SC WebSocket Manager Tests
 * Tests connection establishment, auto-reconnect with exponential backoff,
 * message routing for all message types, parse error handling, store updates,
 * and edge cases (rapid reconnect, multiple close events, etc.).
 * Run: node tests/js/test_websocket.js
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
function assertClose(a, b, eps, msg) {
    assert(Math.abs(a - b) < (eps || 0.001), msg + ` (got ${a}, expected ${b})`);
}
function assertDefined(v, msg) {
    assert(v !== undefined && v !== null, msg + ` (got ${v})`);
}

// ============================================================
// Mock WebSocket API
// ============================================================

const createdSockets = [];
let socketConstructCount = 0;

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
        this._closed = false;
        socketConstructCount++;
        createdSockets.push(this);
    }

    send(data) {
        if (this.readyState !== MockWebSocket.OPEN) {
            throw new Error('WebSocket is not open');
        }
        this._sent.push(data);
    }

    close() {
        this._closed = true;
        this.readyState = MockWebSocket.CLOSED;
    }

    // Test helpers
    _simulateOpen() {
        this.readyState = MockWebSocket.OPEN;
        if (this.onopen) this.onopen({});
    }

    _simulateClose() {
        this.readyState = MockWebSocket.CLOSED;
        if (this.onclose) this.onclose({});
    }

    _simulateError(err) {
        if (this.onerror) this.onerror(err || new Error('mock error'));
    }

    _simulateMessage(data) {
        if (this.onmessage) {
            this.onmessage({ data: typeof data === 'string' ? data : JSON.stringify(data) });
        }
    }
}

// ============================================================
// Mock timer system (synchronous control of setTimeout/clearTimeout)
// ============================================================

let timerIdCounter = 0;
const pendingTimers = new Map();

function mockSetTimeout(fn, delay) {
    const id = ++timerIdCounter;
    pendingTimers.set(id, { fn, delay, id });
    return id;
}

function mockClearTimeout(id) {
    pendingTimers.delete(id);
}

function fireNextTimer() {
    if (pendingTimers.size === 0) return false;
    const first = pendingTimers.values().next().value;
    pendingTimers.delete(first.id);
    first.fn();
    return true;
}

function getNextTimerDelay() {
    if (pendingTimers.size === 0) return null;
    return pendingTimers.values().next().value.delay;
}

function clearAllTimers() {
    pendingTimers.clear();
}

// ============================================================
// Load store.js + events.js + websocket.js source
// ============================================================

const storeCode = fs.readFileSync(__dirname + '/../../frontend/js/command/store.js', 'utf8');
const eventsCode = fs.readFileSync(__dirname + '/../../frontend/js/command/events.js', 'utf8');
const wsCode = fs.readFileSync(__dirname + '/../../frontend/js/command/websocket.js', 'utf8');

// Shared bridge object for capturing EventBus emissions from inside the VM.
// We place this on the context so both host and VM code can access it.
let _bridge = {};

function createFreshContext() {
    // Reset mocks
    createdSockets.length = 0;
    socketConstructCount = 0;
    clearAllTimers();
    timerIdCounter = 0;
    _bridge = {};

    const ctx = vm.createContext({
        Math, Date, console, Map, Set, Array, Object, Number, String, JSON,
        Infinity, undefined, Error, TypeError,
        setTimeout: mockSetTimeout,
        clearTimeout: mockClearTimeout,
        WebSocket: MockWebSocket,
        _bridge,
        window: {
            location: {
                protocol: 'http:',
                host: 'localhost:8000',
            },
        },
    });

    // Load store (strip export)
    const storeStripped = storeCode.replace(/^export\s+/gm, '');
    vm.runInContext(storeStripped, ctx);

    // Load events (strip export)
    const eventsStripped = eventsCode.replace(/^export\s+/gm, '');
    vm.runInContext(eventsStripped, ctx);

    // Load websocket (strip import/export)
    const wsStripped = wsCode
        .replace(/^import\s+.*$/gm, '')
        .replace(/^export\s+/gm, '');
    vm.runInContext(wsStripped, ctx);

    return ctx;
}

/**
 * Register an EventBus listener inside the VM context that writes to _bridge.
 * @param {Object} ctx - VM context
 * @param {string} eventName - event to listen for
 */
function listenEvent(ctx, eventName) {
    vm.runInContext(
        `EventBus.on("${eventName}", function(d) { _bridge["${eventName}"] = d; })`,
        ctx
    );
}

// ============================================================
// 1. Connection establishment and URL construction
// ============================================================

console.log('\n--- Connection Establishment ---');

(function testConnectCreatesWebSocket() {
    const ctx = createFreshContext();
    const ws = vm.runInContext('new WebSocketManager()', ctx);
    ws.connect();
    assertEqual(createdSockets.length, 1, 'connect() creates one WebSocket');
})();

(function testHttpUrlUsesWsProtocol() {
    const ctx = createFreshContext();
    ctx.window.location.protocol = 'http:';
    ctx.window.location.host = 'localhost:8000';
    const ws = vm.runInContext('new WebSocketManager()', ctx);
    ws.connect();
    assertEqual(createdSockets[0].url, 'ws://localhost:8000/ws/live', 'HTTP uses ws: protocol');
})();

(function testHttpsUrlUsesWssProtocol() {
    const ctx = createFreshContext();
    ctx.window.location.protocol = 'https:';
    ctx.window.location.host = 'secure.example.com';
    const ws = vm.runInContext('new WebSocketManager()', ctx);
    ws.connect();
    assertEqual(createdSockets[0].url, 'wss://secure.example.com/ws/live', 'HTTPS uses wss: protocol');
})();

(function testOnOpenSetsConnectedStatus() {
    const ctx = createFreshContext();
    const ws = vm.runInContext('new WebSocketManager()', ctx);
    ws.connect();
    createdSockets[0]._simulateOpen();
    const status = vm.runInContext('TritiumStore.get("connection.status")', ctx);
    assertEqual(status, 'connected', 'onopen sets connection.status to connected');
})();

(function testOnOpenEmitsWsConnected() {
    const ctx = createFreshContext();
    listenEvent(ctx, 'ws:connected');
    const ws = vm.runInContext('new WebSocketManager()', ctx);
    ws.connect();
    createdSockets[0]._simulateOpen();
    // ws:connected is emitted with undefined data, so bridge key exists
    assert('ws:connected' in _bridge, 'onopen emits ws:connected event');
})();

(function testOnOpenResetsReconnectDelay() {
    const ctx = createFreshContext();
    const ws = vm.runInContext('new WebSocketManager()', ctx);
    ws.connect();
    // Simulate close to increase delay
    createdSockets[0]._simulateClose();
    // Fire reconnect timer
    fireNextTimer();
    // Open the new socket
    createdSockets[1]._simulateOpen();
    assertEqual(ws._reconnectDelay, 2000, 'onopen resets reconnect delay to 2000');
})();

(function testConnectedPropertyReflectsState() {
    const ctx = createFreshContext();
    const ws = vm.runInContext('new WebSocketManager()', ctx);
    assert(!ws.connected, 'connected is false before connect()');
    ws.connect();
    assert(!ws.connected, 'connected is false when CONNECTING');
    createdSockets[0]._simulateOpen();
    assert(ws.connected, 'connected is true when OPEN');
    createdSockets[0]._simulateClose();
    assert(!ws.connected, 'connected is false after close');
})();

// ============================================================
// 2. Auto-reconnect with exponential backoff
// ============================================================

console.log('\n--- Auto-Reconnect with Exponential Backoff ---');

(function testOnCloseSchedulesReconnect() {
    const ctx = createFreshContext();
    const ws = vm.runInContext('new WebSocketManager()', ctx);
    ws.connect();
    createdSockets[0]._simulateClose();
    assert(pendingTimers.size === 1, 'onclose schedules a reconnect timer');
})();

(function testOnCloseSetsDisconnectedStatus() {
    const ctx = createFreshContext();
    const ws = vm.runInContext('new WebSocketManager()', ctx);
    ws.connect();
    createdSockets[0]._simulateOpen();
    createdSockets[0]._simulateClose();
    const status = vm.runInContext('TritiumStore.get("connection.status")', ctx);
    assertEqual(status, 'disconnected', 'onclose sets connection.status to disconnected');
})();

(function testOnCloseEmitsWsDisconnected() {
    const ctx = createFreshContext();
    listenEvent(ctx, 'ws:disconnected');
    const ws = vm.runInContext('new WebSocketManager()', ctx);
    ws.connect();
    createdSockets[0]._simulateClose();
    assert('ws:disconnected' in _bridge, 'onclose emits ws:disconnected event');
})();

(function testInitialReconnectDelay() {
    const ctx = createFreshContext();
    const ws = vm.runInContext('new WebSocketManager()', ctx);
    ws.connect();
    createdSockets[0]._simulateClose();
    const delay = getNextTimerDelay();
    assertEqual(delay, 2000, 'First reconnect delay is 2000ms');
})();

(function testReconnectDelayGrowsExponentially() {
    const ctx = createFreshContext();
    const ws = vm.runInContext('new WebSocketManager()', ctx);

    // Connect and close to trigger first reconnect
    ws.connect();
    createdSockets[0]._simulateClose();
    const delay1 = getNextTimerDelay();
    assertEqual(delay1, 2000, 'First reconnect delay is 2000ms');

    // Fire timer to trigger reconnect attempt
    fireNextTimer();
    // After fire, delay should have grown: 2000 * 1.5 = 3000
    // Now the second socket closes
    createdSockets[1]._simulateClose();
    const delay2 = getNextTimerDelay();
    assertEqual(delay2, 3000, 'Second reconnect delay is 3000ms (2000 * 1.5)');

    // Third close
    fireNextTimer();
    createdSockets[2]._simulateClose();
    const delay3 = getNextTimerDelay();
    assertEqual(delay3, 4500, 'Third reconnect delay is 4500ms (3000 * 1.5)');
})();

(function testReconnectDelayCapsAtMax() {
    const ctx = createFreshContext();
    const ws = vm.runInContext('new WebSocketManager()', ctx);
    ws.connect();

    // Force delay very high
    ws._reconnectDelay = 25000;
    createdSockets[0]._simulateClose();
    fireNextTimer();
    // After firing, delay = min(25000 * 1.5, 30000) = 30000
    createdSockets[1]._simulateClose();
    const delay = getNextTimerDelay();
    assert(delay <= 30000, 'Reconnect delay capped at 30000ms (got ' + delay + ')');
})();

(function testReconnectActuallyCreatesNewSocket() {
    const ctx = createFreshContext();
    const ws = vm.runInContext('new WebSocketManager()', ctx);
    ws.connect();
    assertEqual(createdSockets.length, 1, 'One socket before reconnect');
    createdSockets[0]._simulateClose();
    fireNextTimer();
    assertEqual(createdSockets.length, 2, 'New socket created after reconnect');
})();

(function testSuccessfulReconnectResetsDelay() {
    const ctx = createFreshContext();
    const ws = vm.runInContext('new WebSocketManager()', ctx);
    ws.connect();

    // Grow the delay
    ws._reconnectDelay = 15000;
    createdSockets[0]._simulateClose();
    fireNextTimer();

    // Simulate successful connection on the new socket
    createdSockets[1]._simulateOpen();
    assertEqual(ws._reconnectDelay, 2000, 'Successful reconnect resets delay to 2000');
})();

// ============================================================
// 3. Send
// ============================================================

console.log('\n--- Send ---');

(function testSendWhenConnected() {
    const ctx = createFreshContext();
    const ws = vm.runInContext('new WebSocketManager()', ctx);
    ws.connect();
    createdSockets[0]._simulateOpen();
    ws.send({ type: 'ping' });
    assertEqual(createdSockets[0]._sent.length, 1, 'send() transmits when connected');
    assertEqual(createdSockets[0]._sent[0], '{"type":"ping"}', 'send() JSON-encodes data');
})();

(function testSendSilentlyDropsWhenNotConnected() {
    const ctx = createFreshContext();
    const ws = vm.runInContext('new WebSocketManager()', ctx);
    ws.connect();
    // Not yet open
    ws.send({ type: 'ping' });
    assertEqual(createdSockets[0]._sent.length, 0, 'send() drops when not OPEN');
})();

(function testSendSilentlyDropsWhenNoSocket() {
    const ctx = createFreshContext();
    const ws = vm.runInContext('new WebSocketManager()', ctx);
    // Never called connect()
    ws.send({ type: 'ping' });
    // Should not throw
    assert(true, 'send() with no socket does not throw');
})();

// ============================================================
// 4. Disconnect
// ============================================================

console.log('\n--- Disconnect ---');

(function testDisconnectClosesSocket() {
    const ctx = createFreshContext();
    const ws = vm.runInContext('new WebSocketManager()', ctx);
    ws.connect();
    createdSockets[0]._simulateOpen();
    ws.disconnect();
    assert(createdSockets[0]._closed, 'disconnect() closes the WebSocket');
    assertEqual(ws._ws, null, 'disconnect() nulls _ws');
})();

(function testDisconnectDoesNotAutoReconnect() {
    const ctx = createFreshContext();
    const ws = vm.runInContext('new WebSocketManager()', ctx);
    ws.connect();
    createdSockets[0]._simulateOpen();
    ws.disconnect();
    assertEqual(pendingTimers.size, 0, 'disconnect() cancels any pending reconnect timer');
})();

(function testDisconnectCancelsExistingReconnectTimer() {
    const ctx = createFreshContext();
    const ws = vm.runInContext('new WebSocketManager()', ctx);
    ws.connect();
    createdSockets[0]._simulateClose();
    assert(pendingTimers.size === 1, 'Reconnect timer scheduled after close');
    ws.disconnect();
    assertEqual(pendingTimers.size, 0, 'disconnect() clears pending reconnect timer');
})();

(function testDisconnectSetsDisconnectedStatus() {
    const ctx = createFreshContext();
    const ws = vm.runInContext('new WebSocketManager()', ctx);
    ws.connect();
    createdSockets[0]._simulateOpen();
    ws.disconnect();
    const status = vm.runInContext('TritiumStore.get("connection.status")', ctx);
    assertEqual(status, 'disconnected', 'disconnect() sets connection.status to disconnected');
})();

// ============================================================
// 5. onError callback
// ============================================================

console.log('\n--- Error Handling ---');

(function testOnErrorSetsErrorStatus() {
    const ctx = createFreshContext();
    const ws = vm.runInContext('new WebSocketManager()', ctx);
    ws.connect();
    createdSockets[0]._simulateError(new Error('connection refused'));
    const status = vm.runInContext('TritiumStore.get("connection.status")', ctx);
    assertEqual(status, 'error', 'onerror sets connection.status to error');
})();

(function testMalformedJsonDoesNotCrash() {
    const ctx = createFreshContext();
    const ws = vm.runInContext('new WebSocketManager()', ctx);
    ws.connect();
    createdSockets[0]._simulateOpen();
    // Send malformed JSON
    createdSockets[0]._simulateMessage('NOT VALID JSON {{{{');
    // Should not throw, just log
    assert(true, 'Malformed JSON does not crash the handler');
})();

(function testConnectionFailureSchedulesReconnect() {
    const ctx = createFreshContext();
    // Make WebSocket constructor throw
    ctx.WebSocket = function() { throw new Error('Network unreachable'); };
    const ws = vm.runInContext('new WebSocketManager()', ctx);
    ws.connect();
    assert(pendingTimers.size === 1, 'Connection failure schedules reconnect');
})();

// ============================================================
// 6. Message Routing: amy_thought
// ============================================================

console.log('\n--- Message Routing: amy_thought ---');

(function testAmyThought() {
    const ctx = createFreshContext();
    listenEvent(ctx, 'amy:thought');
    const ws = vm.runInContext('new WebSocketManager()', ctx);
    ws.connect();
    createdSockets[0]._simulateOpen();
    createdSockets[0]._simulateMessage({ type: 'amy_thought', text: 'I see movement' });
    const thought = vm.runInContext('TritiumStore.get("amy.lastThought")', ctx);
    assertEqual(thought, 'I see movement', 'amy_thought sets amy.lastThought');
    assertDefined(_bridge['amy:thought'], 'amy_thought emits amy:thought event');
})();

(function testAmyThoughtWithDataWrapper() {
    const ctx = createFreshContext();
    const ws = vm.runInContext('new WebSocketManager()', ctx);
    ws.connect();
    createdSockets[0]._simulateOpen();
    createdSockets[0]._simulateMessage({ type: 'amy_thought', data: { text: 'Nested text' } });
    const thought = vm.runInContext('TritiumStore.get("amy.lastThought")', ctx);
    assertEqual(thought, 'Nested text', 'amy_thought extracts text from data wrapper');
})();

// ============================================================
// 7. Message Routing: amy_speech
// ============================================================

console.log('\n--- Message Routing: amy_speech ---');

(function testAmySpeech() {
    const ctx = createFreshContext();
    listenEvent(ctx, 'amy:speech');
    const ws = vm.runInContext('new WebSocketManager()', ctx);
    ws.connect();
    createdSockets[0]._simulateOpen();
    createdSockets[0]._simulateMessage({ type: 'amy_speech', data: { text: 'Hello commander' } });
    const speaking = vm.runInContext('TritiumStore.get("amy.speaking")', ctx);
    assertEqual(speaking, true, 'amy_speech sets amy.speaking to true');
    assertDefined(_bridge['amy:speech'], 'amy_speech emits amy:speech event');
})();

// ============================================================
// 8. Message Routing: amy_state
// ============================================================

console.log('\n--- Message Routing: amy_state ---');

(function testAmyState() {
    const ctx = createFreshContext();
    listenEvent(ctx, 'amy:state');
    const ws = vm.runInContext('new WebSocketManager()', ctx);
    ws.connect();
    createdSockets[0]._simulateOpen();
    createdSockets[0]._simulateMessage({ type: 'amy_state', data: { state: 'thinking', mood: 'focused' } });
    assertEqual(vm.runInContext('TritiumStore.get("amy.state")', ctx), 'thinking', 'amy_state sets amy.state');
    assertEqual(vm.runInContext('TritiumStore.get("amy.mood")', ctx), 'focused', 'amy_state sets amy.mood');
    assertDefined(_bridge['amy:state'], 'amy_state emits amy:state event');
})();

// ============================================================
// 9. Message Routing: sim_telemetry (single target)
// ============================================================

console.log('\n--- Message Routing: sim_telemetry ---');

(function testSimTelemetrySingle() {
    const ctx = createFreshContext();
    listenEvent(ctx, 'units:updated');
    const ws = vm.runInContext('new WebSocketManager()', ctx);
    ws.connect();
    createdSockets[0]._simulateOpen();
    createdSockets[0]._simulateMessage({
        type: 'sim_telemetry',
        data: {
            target_id: 'rover-01',
            name: 'Rover Alpha',
            asset_type: 'rover',
            alliance: 'Friendly',
            position: { x: 10, y: 20 },
            heading: 90,
            health: 0.8,
            max_health: 1.0,
            battery: 0.75,
            status: 'active',
            kills: 3,
            speed: 5,
        }
    });
    const unit = vm.runInContext('TritiumStore.units.get("rover-01")', ctx);
    assertDefined(unit, 'sim_telemetry updates unit in store');
    assertEqual(unit.name, 'Rover Alpha', 'Unit name set correctly');
    assertEqual(unit.type, 'rover', 'Unit type set from asset_type');
    assertEqual(unit.alliance, 'Friendly', 'Unit alliance set correctly');
    assertEqual(unit.heading, 90, 'Unit heading set correctly');
    assertEqual(unit.battery, 75, 'Battery converted to percent (0.75 -> 75)');
    assertEqual(unit.eliminations, 3, 'Eliminations set from kills');
    assertEqual(unit.speed, 5, 'Speed set correctly');
    assertDefined(_bridge['units:updated'], 'sim_telemetry emits units:updated');
})();

(function testSimTelemetryAmyPrefix() {
    const ctx = createFreshContext();
    const ws = vm.runInContext('new WebSocketManager()', ctx);
    ws.connect();
    createdSockets[0]._simulateOpen();
    createdSockets[0]._simulateMessage({
        type: 'amy_sim_telemetry',
        data: { target_id: 'turret-01', name: 'Turret', asset_type: 'turret', alliance: 'Friendly' }
    });
    const unit = vm.runInContext('TritiumStore.units.get("turret-01")', ctx);
    assertDefined(unit, 'amy_sim_telemetry also routes through _updateUnit');
})();

(function testUpdateUnitExtendedCombatFields() {
    const ctx = createFreshContext();
    const ws = vm.runInContext('new WebSocketManager()', ctx);
    ws.connect();
    createdSockets[0]._simulateOpen();
    createdSockets[0]._simulateMessage({
        type: 'sim_telemetry',
        data: {
            target_id: 'drone-01',
            morale: 0.7,
            fsm_state: 'engaging',
            degradation: 0.2,
            weapon_range: 50,
            is_combatant: true,
        }
    });
    const unit = vm.runInContext('TritiumStore.units.get("drone-01")', ctx);
    assertDefined(unit, 'Extended combat fields: unit exists');
    assertEqual(unit.morale, 0.7, 'morale field propagated');
    assertEqual(unit.fsmState, 'engaging', 'fsm_state mapped to fsmState');
    assertEqual(unit.degradation, 0.2, 'degradation field propagated');
    assertEqual(unit.weaponRange, 50, 'weapon_range mapped to weaponRange');
    assertEqual(unit.isCombatant, true, 'is_combatant mapped to isCombatant');
})();

(function testUpdateUnitSkipsNullTargetId() {
    const ctx = createFreshContext();
    const ws = vm.runInContext('new WebSocketManager()', ctx);
    ws.connect();
    createdSockets[0]._simulateOpen();
    createdSockets[0]._simulateMessage({
        type: 'sim_telemetry',
        data: { name: 'No ID unit' }
    });
    const size = vm.runInContext('TritiumStore.units.size', ctx);
    assertEqual(size, 0, '_updateUnit skips target without target_id');
})();

(function testUpdateUnitFallbackPosition() {
    const ctx = createFreshContext();
    const ws = vm.runInContext('new WebSocketManager()', ctx);
    ws.connect();
    createdSockets[0]._simulateOpen();
    createdSockets[0]._simulateMessage({
        type: 'sim_telemetry',
        data: { target_id: 'unit-xy', x: 42, y: 99 }
    });
    const unit = vm.runInContext('TritiumStore.units.get("unit-xy")', ctx);
    assertEqual(unit.position.x, 42, 'Falls back to top-level x when no position object');
    assertEqual(unit.position.y, 99, 'Falls back to top-level y when no position object');
})();

// ============================================================
// 10. Message Routing: sim_telemetry_batch
// ============================================================

console.log('\n--- Message Routing: sim_telemetry_batch ---');

(function testSimTelemetryBatch() {
    const ctx = createFreshContext();
    listenEvent(ctx, 'units:updated');
    const ws = vm.runInContext('new WebSocketManager()', ctx);
    ws.connect();
    createdSockets[0]._simulateOpen();
    createdSockets[0]._simulateMessage({
        type: 'amy_sim_telemetry_batch',
        data: [
            { target_id: 'r1', name: 'R1', asset_type: 'rover' },
            { target_id: 'r2', name: 'R2', asset_type: 'drone' },
            { target_id: 'r3', name: 'R3', asset_type: 'turret' },
        ]
    });
    const size = vm.runInContext('TritiumStore.units.size', ctx);
    assertEqual(size, 3, 'Batch updates 3 units');
    assertDefined(_bridge['units:updated'], 'Batch emits units:updated');
    // The emitted data is the array of items
    assert(Array.isArray(_bridge['units:updated']), 'units:updated data is array');
    assertEqual(_bridge['units:updated'].length, 3, 'units:updated contains all batch items');
})();

(function testSimTelemetryBatchNonArray() {
    const ctx = createFreshContext();
    const ws = vm.runInContext('new WebSocketManager()', ctx);
    ws.connect();
    createdSockets[0]._simulateOpen();
    // Non-array data should not crash
    createdSockets[0]._simulateMessage({ type: 'amy_sim_telemetry_batch', data: 'not-an-array' });
    assert(true, 'Batch with non-array data does not crash');
})();

// ============================================================
// 11. Message Routing: game_state / amy_game_state_change
// ============================================================

console.log('\n--- Message Routing: game_state ---');

(function testGameStateChange() {
    const ctx = createFreshContext();
    listenEvent(ctx, 'game:state');
    const ws = vm.runInContext('new WebSocketManager()', ctx);
    ws.connect();
    createdSockets[0]._simulateOpen();
    createdSockets[0]._simulateMessage({
        type: 'game_state',
        data: { state: 'active', wave: 3, total_waves: 10, score: 500, total_eliminations: 7 }
    });
    assertEqual(vm.runInContext('TritiumStore.get("game.phase")', ctx), 'active', 'game_state sets game.phase');
    assertEqual(vm.runInContext('TritiumStore.get("game.wave")', ctx), 3, 'game_state sets game.wave');
    assertEqual(vm.runInContext('TritiumStore.get("game.totalWaves")', ctx), 10, 'game_state sets game.totalWaves');
    assertEqual(vm.runInContext('TritiumStore.get("game.score")', ctx), 500, 'game_state sets game.score');
    assertEqual(vm.runInContext('TritiumStore.get("game.eliminations")', ctx), 7, 'game_state sets game.eliminations');
    assertDefined(_bridge['game:state'], 'game_state emits game:state event');
})();

(function testAmyGameStateChange() {
    const ctx = createFreshContext();
    const ws = vm.runInContext('new WebSocketManager()', ctx);
    ws.connect();
    createdSockets[0]._simulateOpen();
    createdSockets[0]._simulateMessage({
        type: 'amy_game_state_change',
        data: { state: 'countdown', wave: 1, total_waves: 10, score: 0 }
    });
    assertEqual(vm.runInContext('TritiumStore.get("game.phase")', ctx), 'countdown', 'amy_game_state_change sets game.phase');
})();

(function testGameStateTotalKillsFallback() {
    const ctx = createFreshContext();
    const ws = vm.runInContext('new WebSocketManager()', ctx);
    ws.connect();
    createdSockets[0]._simulateOpen();
    createdSockets[0]._simulateMessage({
        type: 'game_state',
        data: { state: 'active', total_kills: 12 }
    });
    assertEqual(vm.runInContext('TritiumStore.get("game.eliminations")', ctx), 12, 'Falls back to total_kills when total_eliminations absent');
})();

// ============================================================
// 12. Message Routing: amy_game_over
// ============================================================

console.log('\n--- Message Routing: amy_game_over ---');

(function testGameOverVictory() {
    const ctx = createFreshContext();
    listenEvent(ctx, 'game:state');
    const ws = vm.runInContext('new WebSocketManager()', ctx);
    ws.connect();
    createdSockets[0]._simulateOpen();
    createdSockets[0]._simulateMessage({
        type: 'amy_game_over',
        data: { result: 'victory', score: 1200, total_eliminations: 20 }
    });
    assertEqual(vm.runInContext('TritiumStore.get("game.phase")', ctx), 'victory', 'Victory sets game.phase to victory');
    assertEqual(vm.runInContext('TritiumStore.get("game.score")', ctx), 1200, 'Victory sets game.score');
    assertEqual(vm.runInContext('TritiumStore.get("game.eliminations")', ctx), 20, 'Victory sets game.eliminations');
    assertDefined(_bridge['game:state'], 'game_over emits game:state event');
    assertEqual(_bridge['game:state'].state, 'victory', 'game:state event has state=victory');
})();

(function testGameOverDefeat() {
    const ctx = createFreshContext();
    const ws = vm.runInContext('new WebSocketManager()', ctx);
    ws.connect();
    createdSockets[0]._simulateOpen();
    createdSockets[0]._simulateMessage({
        type: 'amy_game_over',
        data: { result: 'defeat', score: 300 }
    });
    assertEqual(vm.runInContext('TritiumStore.get("game.phase")', ctx), 'defeat', 'Non-victory result sets game.phase to defeat');
})();

(function testGameOverTotalKillsFallback() {
    const ctx = createFreshContext();
    const ws = vm.runInContext('new WebSocketManager()', ctx);
    ws.connect();
    createdSockets[0]._simulateOpen();
    createdSockets[0]._simulateMessage({
        type: 'amy_game_over',
        data: { result: 'victory', total_kills: 15 }
    });
    assertEqual(vm.runInContext('TritiumStore.get("game.eliminations")', ctx), 15, 'game_over falls back to total_kills');
})();

// ============================================================
// 13. Message Routing: game_elimination / game_kill
// ============================================================

console.log('\n--- Message Routing: game_elimination ---');

(function testGameElimination() {
    const ctx = createFreshContext();
    listenEvent(ctx, 'game:elimination');
    const ws = vm.runInContext('new WebSocketManager()', ctx);
    ws.connect();
    createdSockets[0]._simulateOpen();
    createdSockets[0]._simulateMessage({
        type: 'game_elimination',
        data: { interceptor: 'turret-01', target: 'hostile-03', weapon: 'turret_cannon' }
    });
    assertDefined(_bridge['game:elimination'], 'game_elimination emits game:elimination');
    assertEqual(_bridge['game:elimination'].interceptor, 'turret-01', 'elimination data contains interceptor');
})();

(function testGameKillAlias() {
    const ctx = createFreshContext();
    listenEvent(ctx, 'game:elimination');
    const ws = vm.runInContext('new WebSocketManager()', ctx);
    ws.connect();
    createdSockets[0]._simulateOpen();
    createdSockets[0]._simulateMessage({
        type: 'game_kill',
        data: { interceptor: 'rover-01', target: 'hostile-05' }
    });
    assertDefined(_bridge['game:elimination'], 'game_kill also emits game:elimination');
})();

// ============================================================
// 14. Message Routing: announcer
// ============================================================

console.log('\n--- Message Routing: announcer ---');

(function testAnnouncer() {
    const ctx = createFreshContext();
    listenEvent(ctx, 'announcer');
    const ws = vm.runInContext('new WebSocketManager()', ctx);
    ws.connect();
    createdSockets[0]._simulateOpen();
    createdSockets[0]._simulateMessage({
        type: 'announcer',
        data: { text: 'TRIPLE KILL!', category: 'streak' }
    });
    assertDefined(_bridge['announcer'], 'announcer emits announcer event');
    assertEqual(_bridge['announcer'].text, 'TRIPLE KILL!', 'announcer data has text');
})();

// ============================================================
// 15. Message Routing: robot_thought
// ============================================================

console.log('\n--- Message Routing: robot_thought ---');

(function testRobotThought() {
    const ctx = createFreshContext();
    listenEvent(ctx, 'robot:thought');
    const ws = vm.runInContext('new WebSocketManager()', ctx);
    ws.connect();
    createdSockets[0]._simulateOpen();
    createdSockets[0]._simulateMessage({
        type: 'robot_thought',
        data: { robotId: 'rover-01', name: 'Rover Alpha', text: 'Scanning sector 4' }
    });
    assertDefined(_bridge['robot:thought'], 'robot_thought emits robot:thought');
    assertEqual(_bridge['robot:thought'].robotId, 'rover-01', 'robot_thought passes robotId');
})();

// ============================================================
// 16. Message Routing: escalation_change
// ============================================================

console.log('\n--- Message Routing: escalation_change ---');

(function testEscalationChange() {
    const ctx = createFreshContext();
    listenEvent(ctx, 'alert:new');
    const ws = vm.runInContext('new WebSocketManager()', ctx);
    ws.connect();
    createdSockets[0]._simulateOpen();
    createdSockets[0]._simulateMessage({
        type: 'escalation_change',
        data: { message: 'Threat level elevated to AMBER', level: 'amber' }
    });
    const alerts = vm.runInContext('TritiumStore.alerts', ctx);
    assert(alerts.length >= 1, 'escalation_change adds alert to store');
    assertEqual(alerts[0].type, 'escalation', 'Alert type is escalation');
    assertEqual(alerts[0].message, 'Threat level elevated to AMBER', 'Alert message from data');
    assertDefined(_bridge['alert:new'], 'escalation_change emits alert:new');
})();

(function testEscalationChangeDefaultMessage() {
    const ctx = createFreshContext();
    const ws = vm.runInContext('new WebSocketManager()', ctx);
    ws.connect();
    createdSockets[0]._simulateOpen();
    createdSockets[0]._simulateMessage({ type: 'escalation_change', data: {} });
    const alerts = vm.runInContext('TritiumStore.alerts', ctx);
    assertEqual(alerts[0].message, 'Threat level changed', 'Default message when data.message absent');
})();

// ============================================================
// 17. Message Routing: detection
// ============================================================

console.log('\n--- Message Routing: detection ---');

(function testDetection() {
    const ctx = createFreshContext();
    listenEvent(ctx, 'detection');
    const ws = vm.runInContext('new WebSocketManager()', ctx);
    ws.connect();
    createdSockets[0]._simulateOpen();
    createdSockets[0]._simulateMessage({
        type: 'detection',
        data: { cameraId: 'cam-01', boxes: [{ label: 'person', confidence: 0.92 }] }
    });
    assertDefined(_bridge['detection'], 'detection emits detection event');
    assertEqual(_bridge['detection'].cameraId, 'cam-01', 'detection data has cameraId');
})();

// ============================================================
// 18. Message Routing: projectile_fired / projectile_hit
// ============================================================

console.log('\n--- Message Routing: combat events ---');

(function testProjectileFired() {
    const ctx = createFreshContext();
    listenEvent(ctx, 'combat:projectile');
    const ws = vm.runInContext('new WebSocketManager()', ctx);
    ws.connect();
    createdSockets[0]._simulateOpen();
    createdSockets[0]._simulateMessage({
        type: 'projectile_fired',
        data: { shooter: 'turret-01', target: 'hostile-01', weapon: 'nerf_blaster' }
    });
    assertDefined(_bridge['combat:projectile'], 'projectile_fired emits combat:projectile');
})();

(function testAmyProjectileFired() {
    const ctx = createFreshContext();
    listenEvent(ctx, 'combat:projectile');
    const ws = vm.runInContext('new WebSocketManager()', ctx);
    ws.connect();
    createdSockets[0]._simulateOpen();
    createdSockets[0]._simulateMessage({
        type: 'amy_projectile_fired',
        data: { shooter: 'tank-01' }
    });
    assertDefined(_bridge['combat:projectile'], 'amy_projectile_fired also emits combat:projectile');
})();

(function testProjectileHit() {
    const ctx = createFreshContext();
    listenEvent(ctx, 'combat:hit');
    const ws = vm.runInContext('new WebSocketManager()', ctx);
    ws.connect();
    createdSockets[0]._simulateOpen();
    createdSockets[0]._simulateMessage({
        type: 'projectile_hit',
        data: { target: 'hostile-01', damage: 25 }
    });
    assertDefined(_bridge['combat:hit'], 'projectile_hit emits combat:hit');
})();

(function testAmyProjectileHit() {
    const ctx = createFreshContext();
    listenEvent(ctx, 'combat:hit');
    const ws = vm.runInContext('new WebSocketManager()', ctx);
    ws.connect();
    createdSockets[0]._simulateOpen();
    createdSockets[0]._simulateMessage({ type: 'amy_projectile_hit', data: { target: 'h-02' } });
    assertDefined(_bridge['combat:hit'], 'amy_projectile_hit also emits combat:hit');
})();

// ============================================================
// 19. Message Routing: target_eliminated
// ============================================================

console.log('\n--- Message Routing: target_eliminated ---');

(function testTargetEliminated() {
    const ctx = createFreshContext();
    listenEvent(ctx, 'combat:elimination');
    const ws = vm.runInContext('new WebSocketManager()', ctx);
    ws.connect();
    createdSockets[0]._simulateOpen();
    createdSockets[0]._simulateMessage({
        type: 'target_eliminated',
        data: { target_id: 'hostile-03', killer: 'rover-01' }
    });
    assertDefined(_bridge['combat:elimination'], 'target_eliminated emits combat:elimination');
})();

(function testAmyTargetEliminated() {
    const ctx = createFreshContext();
    listenEvent(ctx, 'combat:elimination');
    const ws = vm.runInContext('new WebSocketManager()', ctx);
    ws.connect();
    createdSockets[0]._simulateOpen();
    createdSockets[0]._simulateMessage({ type: 'amy_target_eliminated', data: { target_id: 'h-05' } });
    assertDefined(_bridge['combat:elimination'], 'amy_target_eliminated also emits combat:elimination');
})();

// ============================================================
// 20. Message Routing: elimination_streak / kill_streak
// ============================================================

console.log('\n--- Message Routing: streaks ---');

(function testEliminationStreak() {
    const ctx = createFreshContext();
    listenEvent(ctx, 'combat:streak');
    const ws = vm.runInContext('new WebSocketManager()', ctx);
    ws.connect();
    createdSockets[0]._simulateOpen();
    createdSockets[0]._simulateMessage({
        type: 'elimination_streak',
        data: { unit: 'turret-01', streak: 5, name: 'RAMPAGE' }
    });
    assertDefined(_bridge['combat:streak'], 'elimination_streak emits combat:streak');
    assertEqual(_bridge['combat:streak'].streak, 5, 'streak data passed through');
})();

(function testKillStreakAlias() {
    const ctx = createFreshContext();
    listenEvent(ctx, 'combat:streak');
    const ws = vm.runInContext('new WebSocketManager()', ctx);
    ws.connect();
    createdSockets[0]._simulateOpen();
    createdSockets[0]._simulateMessage({ type: 'kill_streak', data: { streak: 3 } });
    assertDefined(_bridge['combat:streak'], 'kill_streak also emits combat:streak');
})();

(function testAmyEliminationStreak() {
    const ctx = createFreshContext();
    listenEvent(ctx, 'combat:streak');
    const ws = vm.runInContext('new WebSocketManager()', ctx);
    ws.connect();
    createdSockets[0]._simulateOpen();
    createdSockets[0]._simulateMessage({ type: 'amy_elimination_streak', data: { streak: 7 } });
    assertDefined(_bridge['combat:streak'], 'amy_elimination_streak also emits combat:streak');
})();

// ============================================================
// 21. Message Routing: wave_start / wave_complete
// ============================================================

console.log('\n--- Message Routing: wave events ---');

(function testWaveStart() {
    const ctx = createFreshContext();
    listenEvent(ctx, 'game:wave_start');
    const ws = vm.runInContext('new WebSocketManager()', ctx);
    ws.connect();
    createdSockets[0]._simulateOpen();
    createdSockets[0]._simulateMessage({
        type: 'wave_start',
        data: { wave: 5, wave_name: 'FIRESTORM', hostile_count: 8 }
    });
    assertDefined(_bridge['game:wave_start'], 'wave_start emits game:wave_start');
    assertEqual(_bridge['game:wave_start'].wave, 5, 'wave_start data has wave number');
})();

(function testAmyWaveStart() {
    const ctx = createFreshContext();
    listenEvent(ctx, 'game:wave_start');
    const ws = vm.runInContext('new WebSocketManager()', ctx);
    ws.connect();
    createdSockets[0]._simulateOpen();
    createdSockets[0]._simulateMessage({ type: 'amy_wave_start', data: { wave_number: 2 } });
    assertDefined(_bridge['game:wave_start'], 'amy_wave_start also emits game:wave_start');
})();

(function testWaveComplete() {
    const ctx = createFreshContext();
    listenEvent(ctx, 'game:wave_complete');
    const ws = vm.runInContext('new WebSocketManager()', ctx);
    ws.connect();
    createdSockets[0]._simulateOpen();
    createdSockets[0]._simulateMessage({
        type: 'wave_complete',
        data: { wave: 3, eliminations: 6, score_bonus: 150 }
    });
    assertDefined(_bridge['game:wave_complete'], 'wave_complete emits game:wave_complete');
    assertEqual(_bridge['game:wave_complete'].eliminations, 6, 'wave_complete data has eliminations');
})();

(function testAmyWaveComplete() {
    const ctx = createFreshContext();
    listenEvent(ctx, 'game:wave_complete');
    const ws = vm.runInContext('new WebSocketManager()', ctx);
    ws.connect();
    createdSockets[0]._simulateOpen();
    createdSockets[0]._simulateMessage({ type: 'amy_wave_complete', data: { wave_number: 7 } });
    assertDefined(_bridge['game:wave_complete'], 'amy_wave_complete also emits game:wave_complete');
})();

// ============================================================
// 22. Message Routing: mesh events
// ============================================================

console.log('\n--- Message Routing: mesh events ---');

(function testMeshText() {
    const ctx = createFreshContext();
    listenEvent(ctx, 'mesh:text');
    const ws = vm.runInContext('new WebSocketManager()', ctx);
    ws.connect();
    createdSockets[0]._simulateOpen();
    createdSockets[0]._simulateMessage({ type: 'mesh_text', data: { text: 'hello' } });
    assertDefined(_bridge['mesh:text'], 'mesh_text emits mesh:text');
})();

(function testMeshPosition() {
    const ctx = createFreshContext();
    listenEvent(ctx, 'mesh:position');
    const ws = vm.runInContext('new WebSocketManager()', ctx);
    ws.connect();
    createdSockets[0]._simulateOpen();
    createdSockets[0]._simulateMessage({ type: 'mesh_position', data: { x: 1, y: 2 } });
    assertDefined(_bridge['mesh:position'], 'mesh_position emits mesh:position');
})();

(function testMeshTelemetry() {
    const ctx = createFreshContext();
    listenEvent(ctx, 'mesh:telemetry');
    const ws = vm.runInContext('new WebSocketManager()', ctx);
    ws.connect();
    createdSockets[0]._simulateOpen();
    createdSockets[0]._simulateMessage({ type: 'mesh_telemetry', data: { battery: 0.8 } });
    assertDefined(_bridge['mesh:telemetry'], 'mesh_telemetry emits mesh:telemetry');
})();

(function testMeshConnected() {
    const ctx = createFreshContext();
    listenEvent(ctx, 'mesh:connected');
    const ws = vm.runInContext('new WebSocketManager()', ctx);
    ws.connect();
    createdSockets[0]._simulateOpen();
    createdSockets[0]._simulateMessage({ type: 'mesh_connected', data: { nodes: 3 } });
    assertEqual(vm.runInContext('TritiumStore.get("mesh.connected")', ctx), true, 'mesh_connected sets mesh.connected to true');
    assertDefined(_bridge['mesh:connected'], 'mesh_connected emits mesh:connected');
})();

(function testMeshDisconnected() {
    const ctx = createFreshContext();
    // Pre-set mesh.connected to true
    vm.runInContext('TritiumStore.set("mesh.connected", true)', ctx);
    const ws = vm.runInContext('new WebSocketManager()', ctx);
    ws.connect();
    createdSockets[0]._simulateOpen();
    createdSockets[0]._simulateMessage({ type: 'mesh_disconnected', data: {} });
    assertEqual(vm.runInContext('TritiumStore.get("mesh.connected")', ctx), false, 'mesh_disconnected sets mesh.connected to false');
})();

// ============================================================
// 23. Message Routing: unknown/default
// ============================================================

console.log('\n--- Message Routing: unknown types ---');

(function testUnknownTypeForwarded() {
    const ctx = createFreshContext();
    listenEvent(ctx, 'ws:custom_event');
    const ws = vm.runInContext('new WebSocketManager()', ctx);
    ws.connect();
    createdSockets[0]._simulateOpen();
    createdSockets[0]._simulateMessage({
        type: 'custom_event',
        data: { foo: 'bar' }
    });
    assertDefined(_bridge['ws:custom_event'], 'Unknown type forwarded as ws:custom_event');
    assertEqual(_bridge['ws:custom_event'].foo, 'bar', 'Unknown type data passed through');
})();

(function testEventFieldUsedAsType() {
    const ctx = createFreshContext();
    listenEvent(ctx, 'amy:thought');
    const ws = vm.runInContext('new WebSocketManager()', ctx);
    ws.connect();
    createdSockets[0]._simulateOpen();
    // Use 'event' instead of 'type'
    createdSockets[0]._simulateMessage({ event: 'amy_thought', text: 'From event field' });
    assertEqual(vm.runInContext('TritiumStore.get("amy.lastThought")', ctx), 'From event field', 'msg.event used when msg.type is absent');
})();

// ============================================================
// 24. Message with direct properties (no data wrapper)
// ============================================================

console.log('\n--- Direct message properties (no data wrapper) ---');

(function testGameStateNoDataWrapper() {
    const ctx = createFreshContext();
    const ws = vm.runInContext('new WebSocketManager()', ctx);
    ws.connect();
    createdSockets[0]._simulateOpen();
    // Message with state directly on msg (no data wrapper)
    createdSockets[0]._simulateMessage({ type: 'game_state', state: 'active', wave: 7, score: 999 });
    assertEqual(vm.runInContext('TritiumStore.get("game.phase")', ctx), 'active', 'game_state works without data wrapper');
    assertEqual(vm.runInContext('TritiumStore.get("game.wave")', ctx), 7, 'wave read from top-level msg');
})();

(function testSimTelemetryNoDataWrapper() {
    const ctx = createFreshContext();
    const ws = vm.runInContext('new WebSocketManager()', ctx);
    ws.connect();
    createdSockets[0]._simulateOpen();
    createdSockets[0]._simulateMessage({
        type: 'sim_telemetry',
        target_id: 'direct-unit',
        name: 'Direct',
        asset_type: 'rover',
    });
    const unit = vm.runInContext('TritiumStore.units.get("direct-unit")', ctx);
    assertDefined(unit, 'sim_telemetry works with direct message properties');
    assertEqual(unit.name, 'Direct', 'Unit name from direct msg property');
})();

// ============================================================
// 25. Edge Cases
// ============================================================

console.log('\n--- Edge Cases ---');

(function testRapidReconnectClearsOldTimer() {
    const ctx = createFreshContext();
    const ws = vm.runInContext('new WebSocketManager()', ctx);
    ws.connect();
    createdSockets[0]._simulateClose();
    assert(pendingTimers.size === 1, 'First close schedules timer');
    // Fire timer to reconnect, then immediate close again
    fireNextTimer();
    createdSockets[1]._simulateClose();
    // Only one pending timer should exist
    assertEqual(pendingTimers.size, 1, 'Only one reconnect timer after rapid close/reconnect/close');
})();

(function testMultipleCloseEventsDoNotStackTimers() {
    const ctx = createFreshContext();
    const ws = vm.runInContext('new WebSocketManager()', ctx);
    ws.connect();

    // Manually call _scheduleReconnect multiple times
    ws._scheduleReconnect();
    ws._scheduleReconnect();
    ws._scheduleReconnect();
    // clearTimeout in _scheduleReconnect should ensure only one timer
    assertEqual(pendingTimers.size, 1, 'Multiple _scheduleReconnect calls result in only one timer');
})();

(function testDisconnectThenConnectWorks() {
    const ctx = createFreshContext();
    const ws = vm.runInContext('new WebSocketManager()', ctx);
    ws.connect();
    createdSockets[0]._simulateOpen();
    ws.disconnect();
    // Connect again
    ws.connect();
    assertEqual(createdSockets.length, 2, 'New socket created after disconnect + connect');
    createdSockets[1]._simulateOpen();
    assert(ws.connected, 'Reconnected after disconnect + connect');
})();

(function testSendMultipleMessages() {
    const ctx = createFreshContext();
    const ws = vm.runInContext('new WebSocketManager()', ctx);
    ws.connect();
    createdSockets[0]._simulateOpen();
    ws.send({ type: 'a' });
    ws.send({ type: 'b' });
    ws.send({ type: 'c' });
    assertEqual(createdSockets[0]._sent.length, 3, 'Multiple send() calls all transmit');
})();

(function testNullUpdateUnit() {
    const ctx = createFreshContext();
    const ws = vm.runInContext('new WebSocketManager()', ctx);
    // Call _updateUnit with null - should not crash
    ws._updateUnit(null);
    ws._updateUnit(undefined);
    ws._updateUnit({});
    ws._updateUnit({ target_id: null });
    assert(true, '_updateUnit handles null/undefined/empty gracefully');
})();

(function testUpdateUnitNameFallsBackToTargetId() {
    const ctx = createFreshContext();
    const ws = vm.runInContext('new WebSocketManager()', ctx);
    ws.connect();
    createdSockets[0]._simulateOpen();
    createdSockets[0]._simulateMessage({
        type: 'sim_telemetry',
        data: { target_id: 'unnamed-01' }
    });
    const unit = vm.runInContext('TritiumStore.units.get("unnamed-01")', ctx);
    assertEqual(unit.name, 'unnamed-01', 'Name falls back to target_id when no name provided');
})();

(function testUpdateUnitTypeFallbackChain() {
    const ctx = createFreshContext();
    const ws = vm.runInContext('new WebSocketManager()', ctx);
    // asset_type has priority
    ws._updateUnit({ target_id: 't1', asset_type: 'rover', type: 'drone' });
    let unit = vm.runInContext('TritiumStore.units.get("t1")', ctx);
    assertEqual(unit.type, 'rover', 'asset_type takes priority over type');

    // Falls back to type
    ws._updateUnit({ target_id: 't2', type: 'drone' });
    unit = vm.runInContext('TritiumStore.units.get("t2")', ctx);
    assertEqual(unit.type, 'drone', 'Falls back to type when no asset_type');

    // Falls back to unknown
    ws._updateUnit({ target_id: 't3' });
    unit = vm.runInContext('TritiumStore.units.get("t3")', ctx);
    assertEqual(unit.type, 'unknown', 'Falls back to unknown when neither asset_type nor type');
})();

(function testMergeDoesNotOverwriteExistingFields() {
    const ctx = createFreshContext();
    const ws = vm.runInContext('new WebSocketManager()', ctx);
    // First update with full data
    ws._updateUnit({ target_id: 'merge-test', name: 'Alpha', asset_type: 'rover', health: 1.0 });
    // Second update with partial data (only health changes)
    ws._updateUnit({ target_id: 'merge-test', name: 'Alpha', asset_type: 'rover', health: 0.5 });
    const unit = vm.runInContext('TritiumStore.units.get("merge-test")', ctx);
    assertEqual(unit.health, 0.5, 'Partial update merges correctly');
    assertEqual(unit.name, 'Alpha', 'Existing name preserved after merge');
})();

(function testBatteryUndefinedWhenNotNumber() {
    const ctx = createFreshContext();
    const ws = vm.runInContext('new WebSocketManager()', ctx);
    ws._updateUnit({ target_id: 'no-battery', battery: 'N/A' });
    const unit = vm.runInContext('TritiumStore.units.get("no-battery")', ctx);
    assertEqual(unit.battery, undefined, 'Non-number battery results in undefined');
})();

(function testConstructorInitialState() {
    const ctx = createFreshContext();
    const ws = vm.runInContext('new WebSocketManager()', ctx);
    assertEqual(ws._ws, null, 'Initial _ws is null');
    assertEqual(ws._reconnectTimer, null, 'Initial _reconnectTimer is null');
    assertEqual(ws._reconnectDelay, 2000, 'Initial _reconnectDelay is 2000');
    assertEqual(ws._maxDelay, 30000, 'Initial _maxDelay is 30000');
})();

(function testWarHudGlobalCallbacksSafelyAbsent() {
    // Tests that the code does not crash when global warHud* functions are missing
    const ctx = createFreshContext();
    const ws = vm.runInContext('new WebSocketManager()', ctx);
    ws.connect();
    createdSockets[0]._simulateOpen();

    // All these types reference typeof global functions -- should not crash
    createdSockets[0]._simulateMessage({ type: 'game_state', data: { state: 'active' } });
    createdSockets[0]._simulateMessage({ type: 'amy_game_over', data: { result: 'victory' } });
    createdSockets[0]._simulateMessage({ type: 'announcer', data: { text: 'test' } });
    createdSockets[0]._simulateMessage({ type: 'projectile_fired', data: {} });
    createdSockets[0]._simulateMessage({ type: 'projectile_hit', data: {} });
    createdSockets[0]._simulateMessage({ type: 'target_eliminated', data: {} });
    createdSockets[0]._simulateMessage({ type: 'elimination_streak', data: {} });
    createdSockets[0]._simulateMessage({ type: 'wave_start', data: { wave: 1 } });
    createdSockets[0]._simulateMessage({ type: 'wave_complete', data: { wave: 1 } });
    assert(true, 'All message types handled without global warHud* functions');
})();

(function testWarHudGlobalCallbacksCalledWhenPresent() {
    const ctx = createFreshContext();

    // Define global functions inside the VM context and track calls via _bridge
    vm.runInContext(`
        warHudUpdateGameState = function(d) { _bridge.gameStateCalled = true; };
        warHudShowGameOver = function(r, s, w, e) { _bridge.gameOverCalled = true; };
        warHudShowAmyAnnouncement = function(t, c) { _bridge.announcerCalled = true; };
        warHudShowWaveBanner = function(w, n, h) { _bridge.waveBannerCalled = true; };
        warHudShowWaveComplete = function(w, e, s) { _bridge.waveCompleteCalled = true; };
        warCombatAddProjectile = function(d) { _bridge.projectileCalled = true; };
        warCombatAddHitEffect = function(d) { _bridge.hitCalled = true; };
        warCombatAddEliminationEffect = function(d) { _bridge.elimCalled = true; };
        warCombatAddEliminationStreakEffect = function(d) { _bridge.streakCalled = true; };
        warHudAddKillFeedEntry = function(d) { _bridge.killFeedCalled = true; };
    `, ctx);

    const ws = vm.runInContext('new WebSocketManager()', ctx);
    ws.connect();
    createdSockets[0]._simulateOpen();

    createdSockets[0]._simulateMessage({ type: 'game_state', data: { state: 'active' } });
    assert(_bridge.gameStateCalled, 'warHudUpdateGameState called for game_state');

    createdSockets[0]._simulateMessage({ type: 'amy_game_over', data: { result: 'victory', score: 100, waves: 10, total_eliminations: 5 } });
    assert(_bridge.gameOverCalled, 'warHudShowGameOver called for amy_game_over');

    createdSockets[0]._simulateMessage({ type: 'announcer', data: { text: 'test', category: 'streak' } });
    assert(_bridge.announcerCalled, 'warHudShowAmyAnnouncement called for announcer');

    createdSockets[0]._simulateMessage({ type: 'wave_start', data: { wave: 1, wave_name: 'TEST', hostile_count: 5 } });
    assert(_bridge.waveBannerCalled, 'warHudShowWaveBanner called for wave_start');

    createdSockets[0]._simulateMessage({ type: 'wave_complete', data: { wave: 1, eliminations: 3, score_bonus: 50 } });
    assert(_bridge.waveCompleteCalled, 'warHudShowWaveComplete called for wave_complete');

    createdSockets[0]._simulateMessage({ type: 'projectile_fired', data: {} });
    assert(_bridge.projectileCalled, 'warCombatAddProjectile called for projectile_fired');

    createdSockets[0]._simulateMessage({ type: 'projectile_hit', data: {} });
    assert(_bridge.hitCalled, 'warCombatAddHitEffect called for projectile_hit');

    createdSockets[0]._simulateMessage({ type: 'target_eliminated', data: {} });
    assert(_bridge.elimCalled, 'warCombatAddEliminationEffect called for target_eliminated');
    assert(_bridge.killFeedCalled, 'warHudAddKillFeedEntry called for target_eliminated');

    createdSockets[0]._simulateMessage({ type: 'elimination_streak', data: {} });
    assert(_bridge.streakCalled, 'warCombatAddEliminationStreakEffect called for elimination_streak');
})();

// ============================================================
// 22. Missing telemetry fields: visible, squad_id, detected_by
// ============================================================

console.log('\n--- Missing Telemetry Fields ---');

(function testVisibleFieldForwardedToStore() {
    const ctx = createFreshContext();
    const ws = vm.runInContext('new WebSocketManager()', ctx);
    ws._updateUnit({
        target_id: 'h-01',
        alliance: 'hostile',
        visible: false,
    });
    const unit = vm.runInContext('TritiumStore.units.get("h-01")', ctx);
    assertEqual(unit.visible, false, 'visible=false forwarded to store');
})();

(function testVisibleTrueForwardedToStore() {
    const ctx = createFreshContext();
    const ws = vm.runInContext('new WebSocketManager()', ctx);
    ws._updateUnit({
        target_id: 'h-02',
        alliance: 'hostile',
        visible: true,
    });
    const unit = vm.runInContext('TritiumStore.units.get("h-02")', ctx);
    assertEqual(unit.visible, true, 'visible=true forwarded to store');
})();

(function testVisibleUndefinedNotSet() {
    const ctx = createFreshContext();
    const ws = vm.runInContext('new WebSocketManager()', ctx);
    ws._updateUnit({
        target_id: 'h-03',
        alliance: 'friendly',
    });
    const unit = vm.runInContext('TritiumStore.units.get("h-03")', ctx);
    assertEqual(unit.visible, undefined, 'visible not set when absent from telemetry');
})();

(function testSquadIdForwardedToStore() {
    const ctx = createFreshContext();
    const ws = vm.runInContext('new WebSocketManager()', ctx);
    ws._updateUnit({
        target_id: 'h-04',
        alliance: 'hostile',
        squad_id: 'squad-alpha',
    });
    const unit = vm.runInContext('TritiumStore.units.get("h-04")', ctx);
    assertEqual(unit.squadId, 'squad-alpha', 'squad_id forwarded as squadId');
})();

(function testSquadIdNullNotSet() {
    const ctx = createFreshContext();
    const ws = vm.runInContext('new WebSocketManager()', ctx);
    ws._updateUnit({
        target_id: 'h-05',
        alliance: 'hostile',
    });
    const unit = vm.runInContext('TritiumStore.units.get("h-05")', ctx);
    assertEqual(unit.squadId, undefined, 'squadId not set when squad_id absent');
})();

(function testDetectedByForwardedToStore() {
    const ctx = createFreshContext();
    const ws = vm.runInContext('new WebSocketManager()', ctx);
    ws._updateUnit({
        target_id: 'h-06',
        alliance: 'hostile',
        detected_by: ['turret-01', 'drone-01'],
    });
    const unit = vm.runInContext('TritiumStore.units.get("h-06")', ctx);
    assert(Array.isArray(unit.detectedBy), 'detectedBy is an array');
    assertEqual(unit.detectedBy.length, 2, 'detectedBy has 2 entries');
    assertEqual(unit.detectedBy[0], 'turret-01', 'detectedBy[0] is turret-01');
})();

(function testDetectedFieldForwarded() {
    const ctx = createFreshContext();
    const ws = vm.runInContext('new WebSocketManager()', ctx);
    ws._updateUnit({
        target_id: 'h-07',
        alliance: 'hostile',
        detected: true,
    });
    const unit = vm.runInContext('TritiumStore.units.get("h-07")', ctx);
    assertEqual(unit.detected, true, 'detected field forwarded to store');
})();

// ============================================================
// 18. Mission-specific WebSocket events
// ============================================================

console.log('\n--- Mission-specific events: crowd_density ---');

(function testCrowdDensityEvent() {
    const ctx = createFreshContext();
    const ws = vm.runInContext('new WebSocketManager()', ctx);
    ws.connect();
    const sock = createdSockets[createdSockets.length - 1];
    sock._simulateOpen();

    listenEvent(ctx, 'mission:crowd_density');
    sock._simulateMessage({
        type: 'crowd_density',
        data: { grid: [[0.1, 0.5], [0.3, 0.8]], resolution: 2 },
    });

    const stored = vm.runInContext('TritiumStore.get("game.crowdDensity")', ctx);
    assertDefined(stored, 'crowd_density stored in game.crowdDensity');
    assert(_bridge['mission:crowd_density'] !== undefined, 'crowd_density event emitted on EventBus');
})();

console.log('\n--- Mission-specific events: infrastructure_damage ---');

(function testInfrastructureDamageEvent() {
    const ctx = createFreshContext();
    const ws = vm.runInContext('new WebSocketManager()', ctx);
    ws.connect();
    const sock = createdSockets[createdSockets.length - 1];
    sock._simulateOpen();

    listenEvent(ctx, 'mission:infrastructure_damage');
    sock._simulateMessage({
        type: 'infrastructure_damage',
        data: { infrastructure_health: 750, infrastructure_max: 1000, poi_id: 'poi-1', damage: 50 },
    });

    const health = vm.runInContext('TritiumStore.get("game.infrastructureHealth")', ctx);
    assertEqual(health, 750, 'infrastructure_health stored');
    const max = vm.runInContext('TritiumStore.get("game.infrastructureMax")', ctx);
    assertEqual(max, 1000, 'infrastructure_max stored');
    assert(_bridge['mission:infrastructure_damage'] !== undefined, 'infrastructure_damage event emitted');
})();

console.log('\n--- Mission-specific events: civilian_harmed ---');

(function testCivilianHarmedEvent() {
    const ctx = createFreshContext();
    const ws = vm.runInContext('new WebSocketManager()', ctx);
    ws.connect();
    const sock = createdSockets[createdSockets.length - 1];
    sock._simulateOpen();

    listenEvent(ctx, 'mission:civilian_harmed');
    sock._simulateMessage({
        type: 'civilian_harmed',
        data: { civilian_harm_count: 3, civilian_harm_limit: 5, civilian_id: 'civ-1' },
    });

    const count = vm.runInContext('TritiumStore.get("game.civilianHarmCount")', ctx);
    assertEqual(count, 3, 'civilian_harm_count stored');
    const limit = vm.runInContext('TritiumStore.get("game.civilianHarmLimit")', ctx);
    assertEqual(limit, 5, 'civilian_harm_limit stored');
    assert(_bridge['mission:civilian_harmed'] !== undefined, 'civilian_harmed event emitted');
})();

console.log('\n--- Mission-specific events: bomber_detonation ---');

(function testBomberDetonationEvent() {
    const ctx = createFreshContext();
    const ws = vm.runInContext('new WebSocketManager()', ctx);
    ws.connect();
    const sock = createdSockets[createdSockets.length - 1];
    sock._simulateOpen();

    listenEvent(ctx, 'mission:bomber_detonation');
    sock._simulateMessage({
        type: 'bomber_detonation',
        data: { bomber_id: 'drone-b1', position: { x: 10, y: 20 }, damage: 100, radius: 15 },
    });

    assert(_bridge['mission:bomber_detonation'] !== undefined, 'bomber_detonation event emitted');
})();

console.log('\n--- Mission-specific events: de_escalation ---');

(function testDeEscalationEvent() {
    const ctx = createFreshContext();
    const ws = vm.runInContext('new WebSocketManager()', ctx);
    ws.connect();
    const sock = createdSockets[createdSockets.length - 1];
    sock._simulateOpen();

    listenEvent(ctx, 'mission:de_escalation');
    sock._simulateMessage({
        type: 'de_escalation',
        data: { de_escalation_score: 500, rioter_id: 'rioter-1', points: 100 },
    });

    const score = vm.runInContext('TritiumStore.get("game.deEscalationScore")', ctx);
    assertEqual(score, 500, 'de_escalation_score stored');
    assert(_bridge['mission:de_escalation'] !== undefined, 'de_escalation event emitted');
})();

console.log('\n--- Mission-specific events: game_state_change with game_mode_type ---');

(function testGameStateChangeWithModeType() {
    const ctx = createFreshContext();
    const ws = vm.runInContext('new WebSocketManager()', ctx);
    ws.connect();
    const sock = createdSockets[createdSockets.length - 1];
    sock._simulateOpen();

    // Inject warHudUpdateGameState mock
    vm.runInContext('var lastHudData = null; var warHudUpdateGameState = function(d) { lastHudData = d; };', ctx);

    sock._simulateMessage({
        type: 'game_state',
        data: {
            state: 'active',
            game_mode_type: 'drone_swarm',
            infrastructure_health: 900,
            infrastructure_max: 1000,
            wave: 2,
        },
    });

    const modeType = vm.runInContext('TritiumStore.get("game.modeType")', ctx);
    assertEqual(modeType, 'drone_swarm', 'game_mode_type stored in game.modeType');
})();

(function testGameStateChangeCivilUnrestFields() {
    const ctx = createFreshContext();
    const ws = vm.runInContext('new WebSocketManager()', ctx);
    ws.connect();
    const sock = createdSockets[createdSockets.length - 1];
    sock._simulateOpen();

    vm.runInContext('var warHudUpdateGameState = function(d) {};', ctx);

    sock._simulateMessage({
        type: 'game_state',
        data: {
            state: 'active',
            game_mode_type: 'civil_unrest',
            de_escalation_score: 300,
            civilian_harm_count: 1,
            civilian_harm_limit: 5,
            weighted_total_score: 800,
            wave: 1,
        },
    });

    const modeType = vm.runInContext('TritiumStore.get("game.modeType")', ctx);
    assertEqual(modeType, 'civil_unrest', 'civil_unrest game_mode_type stored');
    const deesc = vm.runInContext('TritiumStore.get("game.deEscalationScore")', ctx);
    assertEqual(deesc, 300, 'de_escalation_score from game_state stored');
    const harm = vm.runInContext('TritiumStore.get("game.civilianHarmCount")', ctx);
    assertEqual(harm, 1, 'civilian_harm_count from game_state stored');
})();

console.log('\n--- Mission-specific events: infrastructure_overwhelmed ---');

(function testInfrastructureOverwhelmedEvent() {
    const ctx = createFreshContext();
    const ws = vm.runInContext('new WebSocketManager()', ctx);
    ws.connect();
    const sock = createdSockets[createdSockets.length - 1];
    sock._simulateOpen();

    listenEvent(ctx, 'mission:infrastructure_overwhelmed');
    sock._simulateMessage({
        type: 'infrastructure_overwhelmed',
        data: { poi_id: 'poi-3', poi_name: 'Town Hall' },
    });

    assert(_bridge['mission:infrastructure_overwhelmed'] !== undefined, 'infrastructure_overwhelmed event emitted');
})();

console.log('\n--- Mission-specific events: _updateUnit with mission fields ---');

(function testUpdateUnitCrowdRole() {
    const ctx = createFreshContext();
    const ws = vm.runInContext('new WebSocketManager()', ctx);
    ws._updateUnit({
        target_id: 'civ-01',
        alliance: 'neutral',
        crowd_role: 'rioter',
    });
    const unit = vm.runInContext('TritiumStore.units.get("civ-01")', ctx);
    assertEqual(unit.crowdRole, 'rioter', 'crowd_role stored as crowdRole');
})();

(function testUpdateUnitDroneVariant() {
    const ctx = createFreshContext();
    const ws = vm.runInContext('new WebSocketManager()', ctx);
    ws._updateUnit({
        target_id: 'drone-01',
        alliance: 'hostile',
        drone_variant: 'bomber',
    });
    const unit = vm.runInContext('TritiumStore.units.get("drone-01")', ctx);
    assertEqual(unit.droneVariant, 'bomber', 'drone_variant stored as droneVariant');
})();

(function testUpdateUnitAmmoCount() {
    const ctx = createFreshContext();
    const ws = vm.runInContext('new WebSocketManager()', ctx);
    ws._updateUnit({
        target_id: 'turret-01',
        alliance: 'friendly',
        type: 'missile_turret',
        ammo_count: 12,
        ammo_max: 20,
    });
    const unit = vm.runInContext('TritiumStore.units.get("turret-01")', ctx);
    assertEqual(unit.ammoCount, 12, 'ammo_count stored as ammoCount');
    assertEqual(unit.ammoMax, 20, 'ammo_max stored as ammoMax');
})();

(function testUpdateUnitAltitude() {
    const ctx = createFreshContext();
    const ws = vm.runInContext('new WebSocketManager()', ctx);
    ws._updateUnit({
        target_id: 'drone-02',
        alliance: 'hostile',
        altitude: 35.5,
    });
    const unit = vm.runInContext('TritiumStore.units.get("drone-02")', ctx);
    assertEqual(unit.altitude, 35.5, 'altitude stored');
})();

(function testUpdateUnitInstigatorState() {
    const ctx = createFreshContext();
    const ws = vm.runInContext('new WebSocketManager()', ctx);
    ws._updateUnit({
        target_id: 'instigator-01',
        alliance: 'hostile',
        instigator_state: 'activating',
    });
    const unit = vm.runInContext('TritiumStore.units.get("instigator-01")', ctx);
    assertEqual(unit.instigatorState, 'activating', 'instigator_state stored as instigatorState');
})();

// ============================================================
// amy_ prefix: announcer
// ============================================================

console.log('\n--- amy_announcer prefix variant ---');

(function testAmyAnnouncerPrefix() {
    const ctx = createFreshContext();
    listenEvent(ctx, 'announcer');
    const ws = vm.runInContext('new WebSocketManager()', ctx);
    ws.connect();
    createdSockets[0]._simulateOpen();
    // Bridge sends with amy_ prefix — handler should still emit announcer event
    createdSockets[0]._simulateMessage({
        type: 'amy_announcer',
        data: { text: 'MEGA KILL!', category: 'streak' }
    });
    assertDefined(_bridge['announcer'], 'amy_announcer emits announcer event');
    assertEqual(_bridge['announcer'].text, 'MEGA KILL!', 'amy_announcer data.text');
})();

// ============================================================
// amy_ prefix: game_elimination
// ============================================================

console.log('\n--- amy_game_elimination prefix variant ---');

(function testAmyGameEliminationPrefix() {
    const ctx = createFreshContext();
    listenEvent(ctx, 'game:elimination');
    const ws = vm.runInContext('new WebSocketManager()', ctx);
    ws.connect();
    createdSockets[0]._simulateOpen();
    createdSockets[0]._simulateMessage({
        type: 'amy_game_elimination',
        data: { target_id: 'hostile-99', killer_id: 'turret-01' }
    });
    assertDefined(_bridge['game:elimination'], 'amy_game_elimination emits game:elimination');
})();

// ============================================================
// amy_ prefix: escalation_change
// ============================================================

console.log('\n--- amy_escalation_change prefix variant ---');

(function testAmyEscalationChangePrefix() {
    const ctx = createFreshContext();
    listenEvent(ctx, 'alert:new');
    const ws = vm.runInContext('new WebSocketManager()', ctx);
    ws.connect();
    createdSockets[0]._simulateOpen();
    createdSockets[0]._simulateMessage({
        type: 'amy_escalation_change',
        data: { message: 'DEFCON 2' }
    });
    assertDefined(_bridge['alert:new'], 'amy_escalation_change emits alert:new');
})();

// ============================================================
// amy_ prefix: robot_thought
// ============================================================

console.log('\n--- amy_robot_thought prefix variant ---');

(function testAmyRobotThoughtPrefix() {
    const ctx = createFreshContext();
    listenEvent(ctx, 'robot:thought');
    const ws = vm.runInContext('new WebSocketManager()', ctx);
    ws.connect();
    createdSockets[0]._simulateOpen();
    createdSockets[0]._simulateMessage({
        type: 'amy_robot_thought',
        data: { robotId: 'rover-02', text: 'Enemy spotted' }
    });
    assertDefined(_bridge['robot:thought'], 'amy_robot_thought emits robot:thought');
})();

// ============================================================
// amy_ prefix: detection
// ============================================================

console.log('\n--- amy_detection prefix variant ---');

(function testAmyDetectionPrefix() {
    const ctx = createFreshContext();
    listenEvent(ctx, 'detection');
    const ws = vm.runInContext('new WebSocketManager()', ctx);
    ws.connect();
    createdSockets[0]._simulateOpen();
    createdSockets[0]._simulateMessage({
        type: 'amy_detection',
        data: { camera_id: 'cam-01', class: 'person', confidence: 0.95 }
    });
    assertDefined(_bridge['detection'], 'amy_detection emits detection');
})();

// ============================================================
// amy_ prefix: upgrade_applied
// ============================================================

console.log('\n--- amy_upgrade_applied prefix variant ---');

(function testAmyUpgradeAppliedPrefix() {
    const ctx = createFreshContext();
    // Pre-create a unit so the upgrade handler can find it
    vm.runInContext('TritiumStore.updateUnit("tank-01", { name: "Tank" })', ctx);
    listenEvent(ctx, 'upgrade:applied');
    const ws = vm.runInContext('new WebSocketManager()', ctx);
    ws.connect();
    createdSockets[0]._simulateOpen();
    createdSockets[0]._simulateMessage({
        type: 'amy_upgrade_applied',
        data: { unit_id: 'tank-01', upgrade_id: 'armor_plating' }
    });
    assertDefined(_bridge['upgrade:applied'], 'amy_upgrade_applied emits upgrade:applied');
    const unit = vm.runInContext('TritiumStore.units.get("tank-01")', ctx);
    assert(unit.upgrades && unit.upgrades.includes('armor_plating'), 'amy_upgrade_applied adds to unit.upgrades');
})();

// ============================================================
// amy_ prefix: ability_activated / ability_expired
// ============================================================

console.log('\n--- amy_ability_activated / amy_ability_expired prefix variants ---');

(function testAmyAbilityActivatedPrefix() {
    const ctx = createFreshContext();
    vm.runInContext('TritiumStore.updateUnit("rover-01", { name: "Rover" })', ctx);
    listenEvent(ctx, 'ability:activated');
    const ws = vm.runInContext('new WebSocketManager()', ctx);
    ws.connect();
    createdSockets[0]._simulateOpen();
    createdSockets[0]._simulateMessage({
        type: 'amy_ability_activated',
        data: { unit_id: 'rover-01', ability_id: 'speed_boost', duration: 10 }
    });
    assertDefined(_bridge['ability:activated'], 'amy_ability_activated emits ability:activated');
    const unit = vm.runInContext('TritiumStore.units.get("rover-01")', ctx);
    assert(unit.activeAbilities && unit.activeAbilities.length === 1, 'amy_ability_activated adds to activeAbilities');
})();

(function testAmyAbilityExpiredPrefix() {
    const ctx = createFreshContext();
    vm.runInContext('TritiumStore.updateUnit("rover-01", { name: "Rover", activeAbilities: [{ ability_id: "speed_boost", remaining: 0 }] })', ctx);
    listenEvent(ctx, 'ability:expired');
    const ws = vm.runInContext('new WebSocketManager()', ctx);
    ws.connect();
    createdSockets[0]._simulateOpen();
    createdSockets[0]._simulateMessage({
        type: 'amy_ability_expired',
        data: { unit_id: 'rover-01', ability_id: 'speed_boost' }
    });
    assertDefined(_bridge['ability:expired'], 'amy_ability_expired emits ability:expired');
    const unit = vm.runInContext('TritiumStore.units.get("rover-01")', ctx);
    assertEqual(unit.activeAbilities.length, 0, 'amy_ability_expired removes from activeAbilities');
})();

// ============================================================
// Game reset should clear store units
// ============================================================

console.log('\n--- game reset clears store units ---');

(function testGameResetClearsStoreUnits() {
    const ctx = createFreshContext();
    const ws = vm.runInContext('new WebSocketManager()', ctx);
    ws.connect();
    createdSockets[createdSockets.length - 1]._simulateOpen();

    // Populate some units in the store
    vm.runInContext('TritiumStore.updateUnit("t1", { name: "Turret", alliance: "friendly", status: "active" })', ctx);
    vm.runInContext('TritiumStore.updateUnit("h1", { name: "Hostile", alliance: "hostile", status: "active" })', ctx);
    const before = vm.runInContext('TritiumStore.units.size', ctx);
    assertEqual(before, 2, 'store has 2 units before reset');

    // Send game_state_change to idle (game reset)
    createdSockets[createdSockets.length - 1]._simulateMessage({
        type: 'amy_game_state_change',
        data: { state: 'idle', wave: 0, total_waves: 10, score: 0 }
    });

    const after = vm.runInContext('TritiumStore.units.size', ctx);
    assertEqual(after, 0, 'store units cleared on game reset to idle');
})();

(function testGameStateSetupDoesNotClearUnits() {
    const ctx = createFreshContext();
    const ws = vm.runInContext('new WebSocketManager()', ctx);
    ws.connect();
    createdSockets[createdSockets.length - 1]._simulateOpen();

    // Start in idle, populate a defender
    vm.runInContext('TritiumStore.updateUnit("def1", { name: "Defender", alliance: "friendly", status: "active" })', ctx);

    // Transition to setup (new game setup should NOT clear — defenders are being placed)
    createdSockets[createdSockets.length - 1]._simulateMessage({
        type: 'amy_game_state_change',
        data: { state: 'setup', wave: 0, total_waves: 10 }
    });

    const after = vm.runInContext('TritiumStore.units.size', ctx);
    assertEqual(after, 1, 'store units preserved during setup');
})();

// Setup should still clear per-game overlays (hazards, intel, etc.)
(function testGameStateSetupClearsOverlays() {
    const ctx = createFreshContext();
    const ws = vm.runInContext('new WebSocketManager()', ctx);
    ws.connect();
    createdSockets[createdSockets.length - 1]._simulateOpen();

    // Set some overlay state that should leak without cleanup
    vm.runInContext('TritiumStore.set("game.hostileIntel", { plan: "attack" })', ctx);
    vm.runInContext('TritiumStore.set("game.coverPoints", [{ x: 1, y: 2 }])', ctx);

    // Transition to setup (game reset)
    createdSockets[createdSockets.length - 1]._simulateMessage({
        type: 'amy_game_state_change',
        data: { state: 'setup', wave: 0, total_waves: 10 }
    });

    const intel = vm.runInContext('TritiumStore.get("game.hostileIntel")', ctx);
    assertEqual(intel, null, 'setup clears hostileIntel overlay');
    const cover = vm.runInContext('JSON.stringify(TritiumStore.get("game.coverPoints"))', ctx);
    assertEqual(cover, '[]', 'setup clears coverPoints overlay');
})();

// ============================================================
// New event handlers: npc_alliance_change, weapon_jam, ammo
// ============================================================

(function testNpcAllianceChangeUpdatesStore() {
    const ctx = createFreshContext();
    vm.runInContext('var _ws = new WebSocketManager(); _ws.connect();', ctx);
    createdSockets[createdSockets.length - 1]._simulateOpen();

    // Add a neutral person unit
    vm.runInContext('TritiumStore.updateUnit("p1", { name: "Person", alliance: "neutral", status: "active" })', ctx);

    // Simulate alliance change event
    createdSockets[createdSockets.length - 1]._simulateMessage({
        type: 'amy_npc_alliance_change',
        data: {
            unit_id: 'p1',
            old_alliance: 'neutral',
            new_alliance: 'hostile',
        }
    });

    const unit = vm.runInContext('TritiumStore.units.get("p1")', ctx);
    assertEqual(unit.alliance, 'hostile', 'npc_alliance_change updates unit alliance in store');
})();

(function testWeaponJamUpdatesStore() {
    const ctx = createFreshContext();
    vm.runInContext('var _ws = new WebSocketManager(); _ws.connect();', ctx);
    createdSockets[createdSockets.length - 1]._simulateOpen();

    // Add a turret
    vm.runInContext('TritiumStore.updateUnit("t1", { name: "Turret", alliance: "friendly", status: "active" })', ctx);

    // Simulate weapon jam event
    createdSockets[createdSockets.length - 1]._simulateMessage({
        type: 'amy_weapon_jam',
        data: {
            unit_id: 't1',
            jam_duration: 2.5,
        }
    });

    const unit = vm.runInContext('TritiumStore.units.get("t1")', ctx);
    assertEqual(unit.weaponJammed, true, 'weapon_jam sets weaponJammed on unit in store');
})();

(function testAmmoLowUpdatesStore() {
    const ctx = createFreshContext();
    vm.runInContext('var _ws = new WebSocketManager(); _ws.connect();', ctx);
    createdSockets[createdSockets.length - 1]._simulateOpen();

    // Add a rover
    vm.runInContext('TritiumStore.updateUnit("r1", { name: "Rover", alliance: "friendly", status: "active" })', ctx);

    // Simulate ammo low event
    createdSockets[createdSockets.length - 1]._simulateMessage({
        type: 'amy_ammo_low',
        data: {
            unit_id: 'r1',
            ammo: 5,
            max_ammo: 30,
        }
    });

    const unit = vm.runInContext('TritiumStore.units.get("r1")', ctx);
    assertEqual(unit.ammoLow, true, 'ammo_low sets ammoLow on unit in store');
})();

(function testAmmoDepletedUpdatesStore() {
    const ctx = createFreshContext();
    vm.runInContext('var _ws = new WebSocketManager(); _ws.connect();', ctx);
    createdSockets[createdSockets.length - 1]._simulateOpen();

    // Add a turret
    vm.runInContext('TritiumStore.updateUnit("t1", { name: "Turret", alliance: "friendly", status: "active" })', ctx);

    // Simulate ammo depleted event
    createdSockets[createdSockets.length - 1]._simulateMessage({
        type: 'amy_ammo_depleted',
        data: {
            unit_id: 't1',
            weapon: 'turret_cannon',
        }
    });

    const unit = vm.runInContext('TritiumStore.units.get("t1")', ctx);
    assertEqual(unit.ammoDepleted, true, 'ammo_depleted sets ammoDepleted on unit in store');
})();

(function testTargetNeutralizedUpdatesStore() {
    const ctx = createFreshContext();
    vm.runInContext('var _ws = new WebSocketManager(); _ws.connect();', ctx);
    createdSockets[createdSockets.length - 1]._simulateOpen();

    // Add a hostile
    vm.runInContext('TritiumStore.updateUnit("h1", { name: "Hostile", alliance: "hostile", status: "active" })', ctx);

    // Simulate target neutralized event
    createdSockets[createdSockets.length - 1]._simulateMessage({
        type: 'amy_target_neutralized',
        data: {
            target_id: 'h1',
            reason: 'stalled',
        }
    });

    const unit = vm.runInContext('TritiumStore.units.get("h1")', ctx);
    assertEqual(unit.status, 'neutralized', 'target_neutralized sets status to neutralized');
})();

// ============================================================
// target_eliminated event handler (was game_elimination dead handler)
// ============================================================

// Test: target_eliminated triggers both game:elimination and combat:elimination
(function testTargetEliminatedEmitsBothEvents() {
    const ctx = createFreshContext();
    vm.runInContext('var _ws = new WebSocketManager(); _ws.connect();', ctx);
    createdSockets[createdSockets.length - 1]._simulateOpen();

    vm.runInContext(`
        EventBus.on('game:elimination', function(data) {
            globalThis._gameElim = data;
        });
        EventBus.on('combat:elimination', function(data) {
            globalThis._combatElim = data;
        });
    `, ctx);

    createdSockets[createdSockets.length - 1]._simulateMessage({
        type: 'target_eliminated',
        data: {
            target_id: 'h1',
            target_name: 'Hostile Alpha',
            interceptor_id: 't1',
            interceptor_name: 'Turret-01',
            method: 'nerf_dart',
        }
    });

    const gameData = vm.runInContext('globalThis._gameElim', ctx);
    assertDefined(gameData, 'target_eliminated triggers game:elimination');
    assertEqual(gameData.target_id, 'h1', 'target_eliminated game:elimination passes target_id');

    const combatData = vm.runInContext('globalThis._combatElim', ctx);
    assertDefined(combatData, 'target_eliminated triggers combat:elimination');
    assertEqual(combatData.interceptor_name, 'Turret-01', 'target_eliminated combat:elimination passes interceptor_name');
})();

// Test: amy_target_eliminated also triggers both events
(function testAmyTargetEliminatedEmitsBothEvents() {
    const ctx = createFreshContext();
    vm.runInContext('var _ws = new WebSocketManager(); _ws.connect();', ctx);
    createdSockets[createdSockets.length - 1]._simulateOpen();

    vm.runInContext(`
        EventBus.on('game:elimination', function(data) {
            globalThis._gameElim2 = data;
        });
        EventBus.on('combat:elimination', function(data) {
            globalThis._combatElim2 = data;
        });
    `, ctx);

    createdSockets[createdSockets.length - 1]._simulateMessage({
        type: 'amy_target_eliminated',
        data: {
            target_id: 'h2',
            target_name: 'Hostile Bravo',
            interceptor_id: 'd1',
            interceptor_name: 'Drone-01',
            method: 'turret_cannon',
        }
    });

    const gameData = vm.runInContext('globalThis._gameElim2', ctx);
    assertDefined(gameData, 'amy_target_eliminated triggers game:elimination');
    assertEqual(gameData.target_id, 'h2', 'amy_target_eliminated game:elimination passes target_id');

    const combatData = vm.runInContext('globalThis._combatElim2', ctx);
    assertDefined(combatData, 'amy_target_eliminated triggers combat:elimination');
})();

// ============================================================
// NPC thought triggers store notification
// ============================================================

console.log('\n--- NPC thought triggers store notification ---');

(function testNpcThoughtCallsScheduleNotify() {
    // The amy_npc_thought handler should call _scheduleNotify('units')
    // so the detail panel updates when thought text changes
    const code = require('fs').readFileSync(
        require('path').join(__dirname, '..', '..', 'frontend', 'js', 'command', 'websocket.js'), 'utf8'
    );
    // Find the amy_npc_thought case and verify _scheduleNotify is called
    const thoughtIdx = code.indexOf("case 'amy_npc_thought':");
    const clearIdx = code.indexOf("case 'amy_npc_thought_clear':");
    assert(thoughtIdx !== -1, 'websocket.js has amy_npc_thought handler');
    assert(clearIdx !== -1, 'websocket.js has amy_npc_thought_clear handler');

    const thoughtBlock = code.substring(thoughtIdx, clearIdx);
    assert(thoughtBlock.includes("_scheduleNotify('units')"),
        'amy_npc_thought handler calls _scheduleNotify("units") to trigger store update');
})();

(function testNpcThoughtClearCallsScheduleNotify() {
    const code = require('fs').readFileSync(
        require('path').join(__dirname, '..', '..', 'frontend', 'js', 'command', 'websocket.js'), 'utf8'
    );
    const clearIdx = code.indexOf("case 'amy_npc_thought_clear':");
    const nextCase = code.indexOf('case ', clearIdx + 30);
    const clearBlock = code.substring(clearIdx, nextCase !== -1 ? nextCase : clearIdx + 500);
    assert(clearBlock.includes("_scheduleNotify('units')"),
        'amy_npc_thought_clear handler calls _scheduleNotify("units") to trigger store update');
})();

// ============================================================
// Radio detection fields in sim_telemetry
// ============================================================

console.log('\n--- Radio Detection Fields in Telemetry ---');

(function testRadioDetectedFieldParsed() {
    const rCtx = createFreshContext();
    const mgr = vm.runInContext('new WebSocketManager()', rCtx);
    mgr.connect();
    createdSockets[createdSockets.length - 1]._simulateOpen();
    const ws = createdSockets[createdSockets.length - 1];

    ws._simulateMessage({
        type: 'sim_telemetry',
        data: {
            target_id: 'hostile-radio-1',
            name: 'Scout Alpha',
            alliance: 'hostile',
            position: { x: 50, y: 100 },
            heading: 90,
            health: 80,
            max_health: 100,
            status: 'active',
            visible: false,
            radio_detected: true,
            radio_signal_strength: 0.72,
            identity: { bluetooth_mac: 'AA:BB:CC:DD:EE:FF', wifi_mac: '11:22:33:44:55:66' },
        },
    });
    const unit = vm.runInContext('TritiumStore.units.get("hostile-radio-1")', rCtx);
    assertDefined(unit, 'radio telemetry: unit created in store');
    assertEqual(unit.radio_detected, true, 'radio telemetry: radio_detected parsed as true');
    assertClose(unit.radio_signal_strength, 0.72, 0.01, 'radio telemetry: radio_signal_strength parsed');
    assertEqual(unit.visible, false, 'radio telemetry: visible is false (not visually seen)');
    assertDefined(unit.identity, 'radio telemetry: identity object present');
    assertEqual(unit.identity.bluetooth_mac, 'AA:BB:CC:DD:EE:FF', 'radio telemetry: bluetooth_mac preserved');
})();

(function testRadioDetectedFalseNotSet() {
    const rCtx = createFreshContext();
    const mgr = vm.runInContext('new WebSocketManager()', rCtx);
    mgr.connect();
    createdSockets[createdSockets.length - 1]._simulateOpen();
    const ws = createdSockets[createdSockets.length - 1];

    ws._simulateMessage({
        type: 'sim_telemetry',
        data: {
            target_id: 'hostile-no-radio',
            name: 'Foot Soldier',
            alliance: 'hostile',
            position: { x: 10, y: 20 },
            heading: 0,
            health: 100,
            max_health: 100,
            status: 'active',
            visible: false,
            radio_detected: false,
            radio_signal_strength: 0.0,
        },
    });
    const unit = vm.runInContext('TritiumStore.units.get("hostile-no-radio")', rCtx);
    assertDefined(unit, 'no-radio: unit created in store');
    assertEqual(unit.radio_detected, false, 'no-radio: radio_detected is false');
    assertClose(unit.radio_signal_strength, 0.0, 0.01, 'no-radio: radio_signal_strength is 0');
})();

(function testRadioFieldsInBatchTelemetry() {
    const rCtx = createFreshContext();
    const mgr = vm.runInContext('new WebSocketManager()', rCtx);
    mgr.connect();
    createdSockets[createdSockets.length - 1]._simulateOpen();
    const ws = createdSockets[createdSockets.length - 1];

    ws._simulateMessage({
        type: 'amy_sim_telemetry_batch',
        data: [
            {
                target_id: 'batch-radio-1',
                alliance: 'hostile',
                position: { x: 100, y: 200 },
                heading: 45,
                health: 60,
                max_health: 100,
                status: 'active',
                visible: false,
                radio_detected: true,
                radio_signal_strength: 0.55,
            },
            {
                target_id: 'batch-radio-2',
                alliance: 'hostile',
                position: { x: 150, y: 250 },
                heading: 180,
                health: 90,
                max_health: 100,
                status: 'active',
                visible: true,
                radio_detected: false,
                radio_signal_strength: 0.0,
            },
        ],
    });
    const u1 = vm.runInContext('TritiumStore.units.get("batch-radio-1")', rCtx);
    const u2 = vm.runInContext('TritiumStore.units.get("batch-radio-2")', rCtx);
    assertDefined(u1, 'batch-radio: first unit created');
    assertEqual(u1.radio_detected, true, 'batch-radio: first unit radio_detected');
    assertClose(u1.radio_signal_strength, 0.55, 0.01, 'batch-radio: first unit signal strength');
    assertDefined(u2, 'batch-radio: second unit created');
    assertEqual(u2.radio_detected, false, 'batch-radio: second unit not radio detected');
    assertEqual(u2.visible, true, 'batch-radio: second unit visually visible');
})();

// ============================================================
// Game reset clears mission-mode-specific state
// ============================================================

console.log('\n--- game reset clears mission-mode state ---');

(function testGameResetClearsMissionState() {
    const ctx = createFreshContext();
    const ws = vm.runInContext('new WebSocketManager()', ctx);
    ws.connect();
    createdSockets[createdSockets.length - 1]._simulateOpen();

    // Set mission-mode-specific state
    vm.runInContext("TritiumStore.set('game.modeType', 'civil_unrest')", ctx);
    vm.runInContext("TritiumStore.set('game.infrastructureHealth', 80)", ctx);
    vm.runInContext("TritiumStore.set('game.infrastructureMax', 100)", ctx);
    vm.runInContext("TritiumStore.set('game.deEscalationScore', 42)", ctx);
    vm.runInContext("TritiumStore.set('game.civilianHarmCount', 3)", ctx);
    vm.runInContext("TritiumStore.set('game.civilianHarmLimit', 10)", ctx);
    vm.runInContext("TritiumStore.set('game.weightedTotalScore', 500)", ctx);
    vm.runInContext("TritiumStore.set('game.signals', [{signal_type:'distress'}])", ctx);

    // Verify pre-reset state
    const preMode = vm.runInContext("TritiumStore.get('game.modeType')", ctx);
    assertEqual(preMode, 'civil_unrest', 'mission modeType set before reset');

    // Reset game to idle
    createdSockets[createdSockets.length - 1]._simulateMessage({
        type: 'amy_game_state_change',
        data: { state: 'idle', wave: 0, total_waves: 10, score: 0 }
    });

    // Verify all mission state cleared
    const postMode = vm.runInContext("TritiumStore.get('game.modeType')", ctx);
    assertEqual(postMode, null, 'game.modeType cleared on reset');

    const postInfra = vm.runInContext("TritiumStore.get('game.infrastructureHealth')", ctx);
    assertEqual(postInfra, null, 'game.infrastructureHealth cleared on reset');

    const postInfraMax = vm.runInContext("TritiumStore.get('game.infrastructureMax')", ctx);
    assertEqual(postInfraMax, null, 'game.infrastructureMax cleared on reset');

    const postDeEsc = vm.runInContext("TritiumStore.get('game.deEscalationScore')", ctx);
    assertEqual(postDeEsc, null, 'game.deEscalationScore cleared on reset');

    const postCivHarm = vm.runInContext("TritiumStore.get('game.civilianHarmCount')", ctx);
    assertEqual(postCivHarm, null, 'game.civilianHarmCount cleared on reset');

    const postCivLimit = vm.runInContext("TritiumStore.get('game.civilianHarmLimit')", ctx);
    assertEqual(postCivLimit, null, 'game.civilianHarmLimit cleared on reset');

    const postWeighted = vm.runInContext("TritiumStore.get('game.weightedTotalScore')", ctx);
    assertEqual(postWeighted, null, 'game.weightedTotalScore cleared on reset');

    const postSignals = vm.runInContext("TritiumStore.get('game.signals')", ctx);
    assertEqual(Array.isArray(postSignals) ? postSignals.length : -1, 0, 'game.signals cleared on reset');
})();


// ============================================================
// Auto-dispatch speech event
// ============================================================

console.log('\n--- Auto-dispatch Speech Event ---');

(function testAutoDispatchSpeechAddsAlert() {
    const ctx = createFreshContext();
    const ws = vm.runInContext('new WebSocketManager()', ctx);
    ws.connect();
    const alertsBefore = vm.runInContext("TritiumStore.alerts.length", ctx);
    createdSockets[0]._simulateMessage({
        type: 'auto_dispatch_speech',
        data: { text: 'Dispatching Rover Alpha to intercept hostile-01.' },
    });
    const alertsAfter = vm.runInContext("TritiumStore.alerts.length", ctx);
    assert(alertsAfter > alertsBefore, 'auto_dispatch_speech adds alert to store');
})();

(function testAutoDispatchSpeechEmitsEvent() {
    const ctx = createFreshContext();
    const ws = vm.runInContext('new WebSocketManager()', ctx);
    ws.connect();
    vm.runInContext(`
        EventBus.on('dispatch:speech', (d) => { _testAutoDispatchData = d; });
    `, ctx);
    createdSockets[0]._simulateMessage({
        type: 'auto_dispatch_speech',
        data: { text: 'Dispatch test' },
    });
    const data = vm.runInContext("_testAutoDispatchData", ctx);
    assertEqual(data.text, 'Dispatch test', 'auto_dispatch_speech emits dispatch:speech event');
})();

// ============================================================
// Zone violation event
// ============================================================

console.log('\n--- Zone Violation Event ---');

(function testZoneViolationAddsAlert() {
    const ctx = createFreshContext();
    const ws = vm.runInContext('new WebSocketManager()', ctx);
    ws.connect();
    const alertsBefore = vm.runInContext("TritiumStore.alerts.length", ctx);
    createdSockets[0]._simulateMessage({
        type: 'zone_violation',
        data: {
            target_id: 'h-99',
            zone_name: 'Property Restricted',
            zone_type: 'restricted_area',
            position: { x: 5, y: 5 },
        },
    });
    const alertsAfter = vm.runInContext("TritiumStore.alerts.length", ctx);
    assert(alertsAfter > alertsBefore, 'zone_violation adds alert to store');
})();

(function testZoneViolationEmitsEvent() {
    const ctx = createFreshContext();
    const ws = vm.runInContext('new WebSocketManager()', ctx);
    ws.connect();
    vm.runInContext(`
        EventBus.on('zone:violation', (d) => { _testZoneData = d; });
    `, ctx);
    createdSockets[0]._simulateMessage({
        type: 'zone_violation',
        data: {
            target_id: 'h-99',
            zone_name: 'No-Go',
            zone_type: 'restricted_area',
        },
    });
    const zoneData = vm.runInContext("_testZoneData", ctx);
    assertEqual(zoneData.zone_name, 'No-Go', 'zone_violation emits zone:violation with zone_name');
})();

// ============================================================
// Formation created event
// ============================================================

console.log('\n--- Formation & Mode Change Events ---');

(function testFormationCreatedEmitsEvent() {
    const ctx = createFreshContext();
    const ws = vm.runInContext('new WebSocketManager()', ctx);
    ws.connect();
    vm.runInContext(`
        EventBus.on('formation:created', (d) => { _testFormData = d; });
    `, ctx);
    createdSockets[0]._simulateMessage({
        type: 'formation_created',
        data: { formation_type: 'wedge', unit_count: 4 },
    });
    const formData = vm.runInContext("_testFormData", ctx);
    assertEqual(formData.formation_type, 'wedge', 'formation_created emits formation:created');
})();

(function testModeChangeEmitsEvent() {
    const ctx = createFreshContext();
    const ws = vm.runInContext('new WebSocketManager()', ctx);
    ws.connect();
    vm.runInContext(`
        EventBus.on('amy:mode_change', (d) => { _testModeData = d; });
    `, ctx);
    createdSockets[0]._simulateMessage({
        type: 'mode_change',
        data: { mode: 'battle', previous: 'patrol' },
    });
    const modeData = vm.runInContext("_testModeData", ctx);
    assertEqual(modeData.mode, 'battle', 'mode_change emits amy:mode_change');
})();

// ============================================================
// Identified field in telemetry
// ============================================================

console.log('\n--- Identified Field ---');

(function testIdentifiedFieldParsed() {
    const ctx = createFreshContext();
    const ws = vm.runInContext('new WebSocketManager()', ctx);
    ws.connect();
    createdSockets[0]._simulateMessage({
        type: 'amy_sim_telemetry_batch',
        data: [{
            target_id: 'instigator-01',
            name: 'Instigator',
            asset_type: 'person_hostile',
            alliance: 'hostile',
            position: { x: 100, y: 50 },
            identified: true,
            instigator_state: 'detected',
        }],
    });
    const unit = vm.runInContext("TritiumStore.units.get('instigator-01')", ctx);
    assertEqual(unit?.identified, true, 'identified field parsed from telemetry');
    assertEqual(unit?.instigatorState, 'detected', 'instigator_state parsed from telemetry');
})();

// ============================================================
// State Refresh on Connect
// ============================================================

console.log('\n--- State Refresh on Connect ---');

(function testRefreshStateMethodExists() {
    const ctx = createFreshContext();
    const wsCode2 = fs.readFileSync(
        __dirname + '/../../frontend/js/command/websocket.js', 'utf8'
    );
    assert(
        wsCode2.includes('_refreshState()'),
        '_refreshState method exists in websocket.js'
    );
    assert(
        wsCode2.includes("fetch('/api/game/state')"),
        '_refreshState fetches /api/game/state'
    );
    assert(
        wsCode2.includes("fetch('/api/targets')"),
        '_refreshState fetches /api/targets'
    );
})();

(function testOnOpenCallsRefreshState() {
    const wsCode2 = fs.readFileSync(
        __dirname + '/../../frontend/js/command/websocket.js', 'utf8'
    );
    // onopen handler must call _refreshState
    assert(
        wsCode2.includes('this._refreshState()'),
        'onopen handler calls this._refreshState()'
    );
    // Verify it's in the onopen block (after 'ws:connected' emit)
    const lines = wsCode2.split('\n');
    let inOnOpen = false;
    let foundRefresh = false;
    for (const line of lines) {
        if (line.includes('this._ws.onopen')) inOnOpen = true;
        if (inOnOpen && line.includes('this._refreshState()')) {
            foundRefresh = true;
            break;
        }
        if (inOnOpen && line.includes('this._ws.onclose')) break;
    }
    assert(foundRefresh, '_refreshState() is called inside onopen handler');
})();

(function testRefreshStateSetsGamePhase() {
    const wsCode2 = fs.readFileSync(
        __dirname + '/../../frontend/js/command/websocket.js', 'utf8'
    );
    assert(
        wsCode2.includes("game.state") && wsCode2.includes("game.phase"),
        '_refreshState sets game.phase from response'
    );
    assert(
        wsCode2.includes("game.wave"),
        '_refreshState sets game.wave from response'
    );
})();

(function testRefreshStateUpdatesUnits() {
    const wsCode2 = fs.readFileSync(
        __dirname + '/../../frontend/js/command/websocket.js', 'utf8'
    );
    // Must call _updateUnit for each target in the response
    assert(
        wsCode2.includes('this._updateUnit(t)'),
        '_refreshState calls _updateUnit for each target'
    );
})();

(function testRefreshStateCatchesErrors() {
    const wsCode2 = fs.readFileSync(
        __dirname + '/../../frontend/js/command/websocket.js', 'utf8'
    );
    // Must have try/catch for network failures
    assert(
        wsCode2.includes("'[WS] State refresh failed:'"),
        '_refreshState has error handling for fetch failures'
    );
})();

// ============================================================
// Game state: difficulty_multiplier + wave_name + countdown wiring
// ============================================================

(function testGameStateWiresDifficultyMultiplier() {
    const src = fs.readFileSync(__dirname + '/../../frontend/js/command/websocket.js', 'utf8');
    assert(
        src.includes("game.difficultyMultiplier") && src.includes("d.difficulty_multiplier"),
        'game_state_change handler wires difficulty_multiplier to store'
    );
})();

(function testGameStateWiresWaveName() {
    const src = fs.readFileSync(__dirname + '/../../frontend/js/command/websocket.js', 'utf8');
    assert(
        src.includes("game.waveName") && src.includes("d.wave_name"),
        'game_state_change handler wires wave_name to store'
    );
})();

(function testGameStateWiresCountdown() {
    const src = fs.readFileSync(__dirname + '/../../frontend/js/command/websocket.js', 'utf8');
    assert(
        src.includes("game.countdown") && src.includes("d.countdown"),
        'game_state_change handler wires countdown to store'
    );
})();

(function testGameStateWiresWaveHostilesRemaining() {
    const src = fs.readFileSync(__dirname + '/../../frontend/js/command/websocket.js', 'utf8');
    assert(
        src.includes("game.waveHostilesRemaining") && src.includes("d.wave_hostiles_remaining"),
        'game_state_change handler wires wave_hostiles_remaining to store'
    );
})();

(function testRefreshStateWiresDifficultyMultiplier() {
    const src = fs.readFileSync(__dirname + '/../../frontend/js/command/websocket.js', 'utf8');
    // refreshState should also set difficulty_multiplier
    const refreshIdx = src.indexOf('async _refreshState');
    assert(refreshIdx >= 0, 'async _refreshState method exists');
    const refreshBlock = src.slice(refreshIdx, refreshIdx + 1500);
    assert(
        refreshBlock.includes("game.difficultyMultiplier"),
        '_refreshState also wires difficulty_multiplier from REST response'
    );
})();

// ============================================================
// Store: default game state fields
// ============================================================

(function testStoreHasDifficultyMultiplierDefault() {
    const src = fs.readFileSync(__dirname + '/../../frontend/js/command/store.js', 'utf8');
    assert(
        src.includes('difficultyMultiplier: 1.0'),
        'Store game state has difficultyMultiplier default of 1.0'
    );
})();

(function testStoreHasWaveNameDefault() {
    const src = fs.readFileSync(__dirname + '/../../frontend/js/command/store.js', 'utf8');
    assert(
        src.includes("waveName: ''"),
        "Store game state has waveName default of empty string"
    );
})();

// ============================================================
// amy_transcript handler
// ============================================================

console.log('\n--- amy_transcript handler ---');

(function testAmyTranscriptRoutesChatResponse() {
    const ctx = createFreshContext();
    const ws = vm.runInContext('new WebSocketManager()', ctx);
    ws.connect();
    createdSockets[0]._simulateOpen();
    listenEvent(ctx, 'chat:amy_response');
    createdSockets[0]._simulateMessage({
        type: 'amy_transcript',
        data: { speaker: 'amy', text: 'Moving turret to sector 4.' },
    });
    const d = _bridge['chat:amy_response'];
    assertDefined(d, 'amy_transcript with speaker=amy emits chat:amy_response');
    assertEqual(d.text, 'Moving turret to sector 4.', 'chat:amy_response text matches');
})();

(function testAmyTranscriptIgnoresOperator() {
    const ctx = createFreshContext();
    const ws = vm.runInContext('new WebSocketManager()', ctx);
    ws.connect();
    createdSockets[0]._simulateOpen();
    listenEvent(ctx, 'chat:amy_response');
    createdSockets[0]._simulateMessage({
        type: 'amy_transcript',
        data: { speaker: 'operator', text: 'Status report' },
    });
    const d = _bridge['chat:amy_response'];
    assert(d === undefined, 'amy_transcript with speaker=operator does NOT emit chat:amy_response');
})();

(function testAmyTranscriptNoDataWrapper() {
    const ctx = createFreshContext();
    const ws = vm.runInContext('new WebSocketManager()', ctx);
    ws.connect();
    createdSockets[0]._simulateOpen();
    listenEvent(ctx, 'chat:amy_response');
    createdSockets[0]._simulateMessage({
        type: 'amy_transcript',
        speaker: 'amy',
        text: 'All clear.',
    });
    const d = _bridge['chat:amy_response'];
    assertDefined(d, 'amy_transcript without data wrapper still emits event');
    assertEqual(d.text, 'All clear.', 'text from unwrapped message');
})();

// ============================================================
// hostile_intel handler
// ============================================================

console.log('\n--- hostile_intel handler ---');

(function testHostileIntelSetsStore() {
    const ctx = createFreshContext();
    const ws = vm.runInContext('new WebSocketManager()', ctx);
    ws.connect();
    createdSockets[0]._simulateOpen();
    createdSockets[0]._simulateMessage({
        type: 'hostile_intel',
        data: {
            threat_level: 'high',
            force_ratio: 0.8,
            hostile_count: 6,
            recommended_action: 'flank',
        },
    });
    const intel = vm.runInContext('TritiumStore.get("game.hostileIntel")', ctx);
    assertDefined(intel, 'hostile_intel sets game.hostileIntel in store');
    assertEqual(intel.threat_level, 'high', 'threat_level stored correctly');
    assertEqual(intel.recommended_action, 'flank', 'recommended_action stored correctly');
})();

(function testHostileIntelEmitsEvent() {
    const ctx = createFreshContext();
    const ws = vm.runInContext('new WebSocketManager()', ctx);
    ws.connect();
    createdSockets[0]._simulateOpen();
    listenEvent(ctx, 'hostile:intel');
    createdSockets[0]._simulateMessage({
        type: 'hostile_intel',
        data: { threat_level: 'moderate', hostile_count: 3 },
    });
    const d = _bridge['hostile:intel'];
    assertDefined(d, 'hostile_intel emits hostile:intel event');
    assertEqual(d.threat_level, 'moderate', 'hostile:intel event carries threat_level');
})();

(function testAmyHostileIntelAlias() {
    const ctx = createFreshContext();
    const ws = vm.runInContext('new WebSocketManager()', ctx);
    ws.connect();
    createdSockets[0]._simulateOpen();
    listenEvent(ctx, 'hostile:intel');
    createdSockets[0]._simulateMessage({
        type: 'amy_hostile_intel',
        data: { threat_level: 'low', hostile_count: 1 },
    });
    const d = _bridge['hostile:intel'];
    assertDefined(d, 'amy_hostile_intel alias routes same as hostile_intel');
    assertEqual(d.threat_level, 'low', 'aliased event carries correct data');
})();

(function testHostileIntelNoDataWrapper() {
    const ctx = createFreshContext();
    const ws = vm.runInContext('new WebSocketManager()', ctx);
    ws.connect();
    createdSockets[0]._simulateOpen();
    createdSockets[0]._simulateMessage({
        type: 'hostile_intel',
        threat_level: 'extreme',
        hostile_count: 10,
    });
    const intel = vm.runInContext('TritiumStore.get("game.hostileIntel")', ctx);
    assertDefined(intel, 'hostile_intel without data wrapper still sets store');
    assertEqual(intel.threat_level, 'extreme', 'threat_level from unwrapped message');
})();

// ============================================================
// Audio-relevant EventBus emissions
// Verify that combat events emitted by the WebSocket handler
// match the events that the audio system in main.js listens to.
// ============================================================

console.log('\n--- Audio-relevant EventBus emissions ---');

(function testWeaponJamEmitsCombatWeaponJam() {
    const ctx = createFreshContext();
    const ws = vm.runInContext('new WebSocketManager()', ctx);
    ws.connect();
    createdSockets[0]._simulateOpen();
    listenEvent(ctx, 'combat:weapon_jam');
    createdSockets[0]._simulateMessage({
        type: 'weapon_jam',
        data: { unit_id: 'turret-01', weapon: 'nerf_turret_gun' },
    });
    assertDefined(_bridge['combat:weapon_jam'], 'weapon_jam emits combat:weapon_jam event');
    assertEqual(_bridge['combat:weapon_jam'].unit_id, 'turret-01', 'weapon_jam data has unit_id');
})();

(function testAmyWeaponJamAlias() {
    const ctx = createFreshContext();
    const ws = vm.runInContext('new WebSocketManager()', ctx);
    ws.connect();
    createdSockets[0]._simulateOpen();
    listenEvent(ctx, 'combat:weapon_jam');
    createdSockets[0]._simulateMessage({
        type: 'amy_weapon_jam',
        data: { unit_id: 'rover-01' },
    });
    assertDefined(_bridge['combat:weapon_jam'], 'amy_weapon_jam also emits combat:weapon_jam');
})();

(function testAmmoLowEmitsCombatAmmoLow() {
    const ctx = createFreshContext();
    const ws = vm.runInContext('new WebSocketManager()', ctx);
    ws.connect();
    createdSockets[0]._simulateOpen();
    listenEvent(ctx, 'combat:ammo_low');
    createdSockets[0]._simulateMessage({
        type: 'ammo_low',
        data: { unit_id: 'turret-02' },
    });
    assertDefined(_bridge['combat:ammo_low'], 'ammo_low emits combat:ammo_low event');
})();

(function testAmmoDepletedEmitsCombatAmmoDepleted() {
    const ctx = createFreshContext();
    const ws = vm.runInContext('new WebSocketManager()', ctx);
    ws.connect();
    createdSockets[0]._simulateOpen();
    listenEvent(ctx, 'combat:ammo_depleted');
    createdSockets[0]._simulateMessage({
        type: 'ammo_depleted',
        data: { unit_id: 'rover-03' },
    });
    assertDefined(_bridge['combat:ammo_depleted'], 'ammo_depleted emits combat:ammo_depleted event');
})();

(function testHazardSpawnedEmitsHazardEvent() {
    const ctx = createFreshContext();
    const ws = vm.runInContext('new WebSocketManager()', ctx);
    ws.connect();
    createdSockets[0]._simulateOpen();
    listenEvent(ctx, 'hazard:spawned');
    createdSockets[0]._simulateMessage({
        type: 'hazard_spawned',
        data: {
            hazard_id: 'haz-01',
            hazard_type: 'fire',
            position: { x: 10, y: 20 },
            radius: 5,
        },
    });
    assertDefined(_bridge['hazard:spawned'], 'hazard_spawned emits hazard:spawned event');
    assertEqual(_bridge['hazard:spawned'].hazard_type, 'fire', 'hazard:spawned data has hazard_type');
})();

(function testSensorTriggeredEmitsSensorEvent() {
    const ctx = createFreshContext();
    const ws = vm.runInContext('new WebSocketManager()', ctx);
    ws.connect();
    createdSockets[0]._simulateOpen();
    listenEvent(ctx, 'sensor:triggered');
    createdSockets[0]._simulateMessage({
        type: 'sensor_triggered',
        data: { sensor_id: 'sensor-01', target_id: 'hostile-05' },
    });
    assertDefined(_bridge['sensor:triggered'], 'sensor_triggered emits sensor:triggered event');
})();

(function testProjectileFiredEmitsCombatProjectile() {
    // Verify the specific EventBus event that audio wiring listens to
    const ctx = createFreshContext();
    const ws = vm.runInContext('new WebSocketManager()', ctx);
    ws.connect();
    createdSockets[0]._simulateOpen();
    listenEvent(ctx, 'combat:projectile');
    createdSockets[0]._simulateMessage({
        type: 'projectile_fired',
        data: {
            projectile_type: 'nerf_missile_launcher',
            source_pos: { x: 5, y: 10 },
            target_pos: { x: 15, y: 20 },
        },
    });
    const d = _bridge['combat:projectile'];
    assertDefined(d, 'projectile_fired emits combat:projectile for audio system');
    assertEqual(d.projectile_type, 'nerf_missile_launcher', 'projectile_type passed through for weapon-specific audio');
    assertDefined(d.source_pos, 'source_pos passed through for positional audio');
})();

(function testEliminationEmitsBothGameAndCombatEvents() {
    // Audio listens to combat:elimination; HUD listens to game:elimination
    // Both must fire for the same WebSocket message
    const ctx = createFreshContext();
    const ws = vm.runInContext('new WebSocketManager()', ctx);
    ws.connect();
    createdSockets[0]._simulateOpen();
    listenEvent(ctx, 'combat:elimination');
    listenEvent(ctx, 'game:elimination');
    createdSockets[0]._simulateMessage({
        type: 'target_eliminated',
        data: { target_id: 'hostile-01', position: { x: 10, y: 20 } },
    });
    assertDefined(_bridge['combat:elimination'], 'target_eliminated emits combat:elimination (audio)');
    assertDefined(_bridge['game:elimination'], 'target_eliminated emits game:elimination (HUD)');
})();

(function testGameStateActiveEmitsForAmbientAudio() {
    // Audio wiring starts ambient on 'active' state
    const ctx = createFreshContext();
    const ws = vm.runInContext('new WebSocketManager()', ctx);
    ws.connect();
    createdSockets[0]._simulateOpen();
    listenEvent(ctx, 'game:state');
    createdSockets[0]._simulateMessage({
        type: 'game_state',
        data: { state: 'active', wave: 1, total_waves: 10 },
    });
    const d = _bridge['game:state'];
    assertDefined(d, 'game_state emits game:state for audio ambient management');
    assertEqual(d.state, 'active', 'game:state carries state field for audio branching');
})();

(function testGameOverVictoryEmitsGameState() {
    // Audio plays victory_fanfare when game:state has state='victory'
    const ctx = createFreshContext();
    const ws = vm.runInContext('new WebSocketManager()', ctx);
    ws.connect();
    createdSockets[0]._simulateOpen();
    listenEvent(ctx, 'game:state');
    createdSockets[0]._simulateMessage({
        type: 'amy_game_over',
        data: { result: 'victory', score: 5000 },
    });
    const d = _bridge['game:state'];
    assertDefined(d, 'amy_game_over emits game:state for audio victory/defeat');
    assertEqual(d.state, 'victory', 'game_over victory maps to game:state state=victory');
})();

(function testGameOverDefeatEmitsGameState() {
    const ctx = createFreshContext();
    const ws = vm.runInContext('new WebSocketManager()', ctx);
    ws.connect();
    createdSockets[0]._simulateOpen();
    listenEvent(ctx, 'game:state');
    createdSockets[0]._simulateMessage({
        type: 'amy_game_over',
        data: { result: 'defeat', score: 1200 },
    });
    const d = _bridge['game:state'];
    assertDefined(d, 'amy_game_over defeat emits game:state');
    assertEqual(d.state, 'defeat', 'game_over defeat maps to game:state state=defeat');
})();

(function testAlertNewEmitsForAudioWiring() {
    const ctx = createFreshContext();
    const ws = vm.runInContext('new WebSocketManager()', ctx);
    ws.connect();
    createdSockets[0]._simulateOpen();
    listenEvent(ctx, 'alert:new');
    createdSockets[0]._simulateMessage({
        type: 'escalation_change',
        data: { message: 'THREAT LEVEL ELEVATED' },
    });
    assertDefined(_bridge['alert:new'], 'escalation_change emits alert:new for audio');
})();

(function testAnnouncerEmitsForAudioWiring() {
    const ctx = createFreshContext();
    const ws = vm.runInContext('new WebSocketManager()', ctx);
    ws.connect();
    createdSockets[0]._simulateOpen();
    listenEvent(ctx, 'announcer');
    createdSockets[0]._simulateMessage({
        type: 'announcer',
        data: { text: 'DOUBLE KILL', category: 'elimination' },
    });
    assertDefined(_bridge['announcer'], 'announcer event emits announcer for audio wiring');
})();

(function testDispatchSpeechEmitsForAudioWiring() {
    const ctx = createFreshContext();
    const ws = vm.runInContext('new WebSocketManager()', ctx);
    ws.connect();
    createdSockets[0]._simulateOpen();
    listenEvent(ctx, 'dispatch:speech');
    createdSockets[0]._simulateMessage({
        type: 'auto_dispatch_speech',
        data: { text: 'Rover-01 dispatched to sector 3' },
    });
    assertDefined(_bridge['dispatch:speech'], 'auto_dispatch_speech emits dispatch:speech for audio');
})();

// ============================================================
// Summary
// ============================================================

console.log('\n' + '='.repeat(50));
console.log(`WebSocket Tests: ${passed} passed, ${failed} failed`);
console.log('='.repeat(50));
process.exit(failed > 0 ? 1 : 0);
