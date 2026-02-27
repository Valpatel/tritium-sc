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
// Summary
// ============================================================

console.log('\n' + '='.repeat(50));
console.log(`WebSocket Tests: ${passed} passed, ${failed} failed`);
console.log('='.repeat(50));
process.exit(failed > 0 ? 1 : 0);
