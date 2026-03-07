// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
/**
 * TRITIUM-SC Hazard & Sensor Event Tests
 * Tests WebSocket handlers for hazard_spawned, hazard_expired,
 * sensor_triggered, sensor_cleared events and TritiumStore updates.
 * Run: node tests/js/test_hazard_events.js
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
function assertDefined(v, msg) {
    assert(v !== undefined && v !== null, msg + ` (got ${v})`);
}

// ============================================================
// Mock browser environment
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
        this.sentMessages = [];
        createdSockets.push(this);
    }

    send(data) { this.sentMessages.push(data); }
    close() { this.readyState = MockWebSocket.CLOSED; }

    _simulateOpen() {
        this.readyState = MockWebSocket.OPEN;
        if (this.onopen) this.onopen({ type: 'open' });
    }

    _simulateMessage(data) {
        if (this.onmessage) {
            this.onmessage({ data: JSON.stringify(data) });
        }
    }
}

function createFreshContext() {
    createdSockets.length = 0;
    const sandbox = {
        console,
        WebSocket: MockWebSocket,
        setTimeout: (fn, ms) => { fn(); return 1; },
        clearTimeout: () => {},
        setInterval: () => 1,
        clearInterval: () => {},
        window: { location: { host: 'localhost:8000' } },
        document: {
            addEventListener: () => {},
            querySelector: () => null,
            hidden: false,
        },
        navigator: { userAgent: 'node-test' },
        requestAnimationFrame: (fn) => fn(),
    };
    sandbox.globalThis = sandbox;
    sandbox.self = sandbox;
    const ctx = vm.createContext(sandbox);

    // Load store
    const storeCode = fs.readFileSync('src/frontend/js/command/store.js', 'utf-8');
    vm.runInContext(storeCode.replace(/^export\s+/gm, ''), ctx);

    // Load events
    const eventsCode = fs.readFileSync('src/frontend/js/command/events.js', 'utf-8');
    vm.runInContext(eventsCode.replace(/^export\s+/gm, '').replace(/^import\s.*$/gm, ''), ctx);

    // Load websocket
    const wsCode = fs.readFileSync('src/frontend/js/command/websocket.js', 'utf-8');
    vm.runInContext(
        wsCode.replace(/^export\s+/gm, '').replace(/^import\s.*$/gm, ''),
        ctx
    );

    return ctx;
}

// ============================================================
// Hazard events
// ============================================================

console.log('\n--- Hazard: hazard_spawned ---');

(function testHazardSpawnedEmitsEvent() {
    const ctx = createFreshContext();
    vm.runInContext('var _ws = new WebSocketManager(); _ws.connect();', ctx);
    createdSockets[createdSockets.length - 1]._simulateOpen();

    vm.runInContext(`
        EventBus.on('hazard:spawned', function(data) {
            globalThis._hazSpawned = data;
        });
    `, ctx);

    createdSockets[createdSockets.length - 1]._simulateMessage({
        type: 'hazard_spawned',
        data: {
            hazard_id: 'hz1',
            hazard_type: 'fire',
            position: [45.2, 120.1],
            radius: 15.0,
            duration: 30.0,
        }
    });

    const data = vm.runInContext('globalThis._hazSpawned', ctx);
    assertDefined(data, 'hazard_spawned emits hazard:spawned');
    if (data) {
        assertEqual(data.hazard_id, 'hz1', 'hazard_spawned passes hazard_id');
        assertEqual(data.hazard_type, 'fire', 'hazard_spawned passes hazard_type');
        assertEqual(data.radius, 15.0, 'hazard_spawned passes radius');
    }
})();

(function testAmyHazardSpawnedEmitsEvent() {
    const ctx = createFreshContext();
    vm.runInContext('var _ws = new WebSocketManager(); _ws.connect();', ctx);
    createdSockets[createdSockets.length - 1]._simulateOpen();

    vm.runInContext(`
        EventBus.on('hazard:spawned', function(data) {
            globalThis._hazSpawned2 = data;
        });
    `, ctx);

    createdSockets[createdSockets.length - 1]._simulateMessage({
        type: 'amy_hazard_spawned',
        data: { hazard_id: 'hz2', hazard_type: 'flood', position: [10, 20], radius: 25.0, duration: 60.0 }
    });

    const data = vm.runInContext('globalThis._hazSpawned2', ctx);
    assertDefined(data, 'amy_hazard_spawned also emits hazard:spawned');
})();

(function testHazardSpawnedUpdatesStore() {
    const ctx = createFreshContext();
    vm.runInContext('var _ws = new WebSocketManager(); _ws.connect();', ctx);
    createdSockets[createdSockets.length - 1]._simulateOpen();

    createdSockets[createdSockets.length - 1]._simulateMessage({
        type: 'hazard_spawned',
        data: {
            hazard_id: 'hz3',
            hazard_type: 'roadblock',
            position: [55.0, 80.0],
            radius: 10.0,
            duration: 45.0,
        }
    });

    const hazards = vm.runInContext('TritiumStore.get("hazards")', ctx);
    assertDefined(hazards, 'hazard_spawned creates hazards in store');
    if (hazards) {
        const hz = vm.runInContext('TritiumStore.get("hazards").get("hz3")', ctx);
        assertDefined(hz, 'hazard stored by hazard_id');
        if (hz) assertEqual(hz.hazard_type, 'roadblock', 'stored hazard has correct type');
    }
})();

console.log('\n--- Hazard: hazard_expired ---');

(function testHazardExpiredEmitsEvent() {
    const ctx = createFreshContext();
    vm.runInContext('var _ws = new WebSocketManager(); _ws.connect();', ctx);
    createdSockets[createdSockets.length - 1]._simulateOpen();

    vm.runInContext(`
        EventBus.on('hazard:expired', function(data) {
            globalThis._hazExpired = data;
        });
    `, ctx);

    createdSockets[createdSockets.length - 1]._simulateMessage({
        type: 'hazard_expired',
        data: { hazard_id: 'hz1' }
    });

    const data = vm.runInContext('globalThis._hazExpired', ctx);
    assertDefined(data, 'hazard_expired emits hazard:expired');
    if (data) assertEqual(data.hazard_id, 'hz1', 'hazard_expired passes hazard_id');
})();

(function testHazardExpiredRemovesFromStore() {
    const ctx = createFreshContext();
    vm.runInContext('var _ws = new WebSocketManager(); _ws.connect();', ctx);
    createdSockets[createdSockets.length - 1]._simulateOpen();

    // Spawn first
    createdSockets[createdSockets.length - 1]._simulateMessage({
        type: 'hazard_spawned',
        data: { hazard_id: 'hz4', hazard_type: 'fire', position: [0, 0], radius: 10, duration: 30 }
    });

    const hazMap = vm.runInContext('TritiumStore.get("hazards")', ctx);
    if (hazMap) {
        let hz = hazMap.get('hz4');
        assertDefined(hz, 'hazard exists before expiry');

        // Expire
        createdSockets[createdSockets.length - 1]._simulateMessage({
            type: 'hazard_expired',
            data: { hazard_id: 'hz4' }
        });

        hz = vm.runInContext('TritiumStore.get("hazards").get("hz4")', ctx);
        assertEqual(hz, undefined, 'hazard removed from store after expiry');
    } else {
        assert(false, 'hazard exists before expiry - store not initialized');
        assert(false, 'hazard removed from store after expiry - store not initialized');
    }
})();

// ============================================================
// Sensor events
// ============================================================

console.log('\n--- Sensor: sensor_triggered ---');

(function testSensorTriggeredEmitsEvent() {
    const ctx = createFreshContext();
    vm.runInContext('var _ws = new WebSocketManager(); _ws.connect();', ctx);
    createdSockets[createdSockets.length - 1]._simulateOpen();

    vm.runInContext(`
        EventBus.on('sensor:triggered', function(data) {
            globalThis._sensTriggered = data;
        });
    `, ctx);

    createdSockets[createdSockets.length - 1]._simulateMessage({
        type: 'sensor_triggered',
        data: {
            sensor_id: 's1',
            name: 'Front Porch',
            type: 'motion',
            triggered_by: 'Hostile-1',
            target_id: 't123',
            position: { x: 45.2, z: 120.1 },
        }
    });

    const data = vm.runInContext('globalThis._sensTriggered', ctx);
    assertDefined(data, 'sensor_triggered emits sensor:triggered');
    if (data) {
        assertEqual(data.sensor_id, 's1', 'sensor_triggered passes sensor_id');
        assertEqual(data.name, 'Front Porch', 'sensor_triggered passes name');
        assertEqual(data.type, 'motion', 'sensor_triggered passes type');
    }
})();

(function testAmySensorTriggeredEmitsEvent() {
    const ctx = createFreshContext();
    vm.runInContext('var _ws = new WebSocketManager(); _ws.connect();', ctx);
    createdSockets[createdSockets.length - 1]._simulateOpen();

    vm.runInContext(`
        EventBus.on('sensor:triggered', function(data) {
            globalThis._sensTriggered2 = data;
        });
    `, ctx);

    createdSockets[createdSockets.length - 1]._simulateMessage({
        type: 'amy_sensor_triggered',
        data: { sensor_id: 's2', name: 'Back Yard', type: 'tripwire', triggered_by: 'Person-2' }
    });

    const data = vm.runInContext('globalThis._sensTriggered2', ctx);
    assertDefined(data, 'amy_sensor_triggered also emits sensor:triggered');
})();

console.log('\n--- Sensor: sensor_cleared ---');

(function testSensorClearedEmitsEvent() {
    const ctx = createFreshContext();
    vm.runInContext('var _ws = new WebSocketManager(); _ws.connect();', ctx);
    createdSockets[createdSockets.length - 1]._simulateOpen();

    vm.runInContext(`
        EventBus.on('sensor:cleared', function(data) {
            globalThis._sensCleared = data;
        });
    `, ctx);

    createdSockets[createdSockets.length - 1]._simulateMessage({
        type: 'sensor_cleared',
        data: { sensor_id: 's1', name: 'Front Porch' }
    });

    const data = vm.runInContext('globalThis._sensCleared', ctx);
    assertDefined(data, 'sensor_cleared emits sensor:cleared');
    if (data) assertEqual(data.sensor_id, 's1', 'sensor_cleared passes sensor_id');
})();

// ============================================================
// Hazard ID fallback: backend sends "id" not "hazard_id"
// ============================================================

console.log('\n--- Hazard: backend "id" field fallback ---');

(function testHazardSpawnedWithIdField() {
    const ctx = createFreshContext();
    vm.runInContext('var _ws = new WebSocketManager(); _ws.connect();', ctx);
    createdSockets[createdSockets.length - 1]._simulateOpen();

    // Backend sends "id" not "hazard_id"
    createdSockets[createdSockets.length - 1]._simulateMessage({
        type: 'hazard_spawned',
        data: { id: 'hz-backend-1', hazard_type: 'roadblock', position: { x: 50, y: 50 }, radius: 10, duration: 30 }
    });

    const hazards = vm.runInContext('TritiumStore.get("hazards")', ctx);
    assertDefined(hazards, 'hazards store created from "id" field');
    if (hazards) {
        const hz = vm.runInContext('TritiumStore.get("hazards").get("hz-backend-1")', ctx);
        assertDefined(hz, 'hazard stored using "id" fallback key');
        if (hz) {
            assertEqual(hz.hazard_id, 'hz-backend-1', 'stored hazard_id matches original id');
            assertEqual(hz.hazard_type, 'roadblock', 'hazard_type preserved from "id" event');
        }
    }
})();

(function testHazardExpiredWithIdField() {
    const ctx = createFreshContext();
    vm.runInContext('var _ws = new WebSocketManager(); _ws.connect();', ctx);
    createdSockets[createdSockets.length - 1]._simulateOpen();

    // Spawn with "id" field
    createdSockets[createdSockets.length - 1]._simulateMessage({
        type: 'hazard_spawned',
        data: { id: 'hz-backend-2', hazard_type: 'fire', position: { x: 10, y: 10 }, radius: 5, duration: 20 }
    });

    // Expire with "id" field
    createdSockets[createdSockets.length - 1]._simulateMessage({
        type: 'hazard_expired',
        data: { id: 'hz-backend-2' }
    });

    const hazards = vm.runInContext('TritiumStore.get("hazards")', ctx);
    if (hazards) {
        const hz = vm.runInContext('TritiumStore.get("hazards").get("hz-backend-2")', ctx);
        assertEqual(hz, undefined, 'hazard removed from store via "id" field expiry');
    } else {
        assert(true, 'hazard removed from store via "id" field expiry (store empty)');
    }
})();

// ============================================================
// Game reset clears hazards and overlay state
// ============================================================

console.log('\n--- Game reset cleanup ---');

(function testGameResetClearsHazards() {
    const ctx = createFreshContext();
    vm.runInContext('var _ws = new WebSocketManager(); _ws.connect();', ctx);
    createdSockets[createdSockets.length - 1]._simulateOpen();

    // Seed a hazard
    createdSockets[createdSockets.length - 1]._simulateMessage({
        type: 'hazard_spawned',
        data: { hazard_id: 'hz-stale', hazard_type: 'fire', position: [10, 20], radius: 15, duration: 60 }
    });

    // Seed overlay state
    vm.runInContext(`
        TritiumStore.set('game.hostileIntel', { threat_level: 'high' });
        TritiumStore.set('game.hostileObjectives', [{ id: 'test' }]);
        TritiumStore.set('game.crowdDensity', { grid: [[]] });
    `, ctx);

    // Verify hazard exists
    const preSize = vm.runInContext("TritiumStore.get('hazards') ? TritiumStore.get('hazards').size : 0", ctx);
    assert(preSize >= 1, 'hazard stored before reset');

    // Simulate game_state to idle (handler uses 'game_state' not 'game_state_change')
    createdSockets[createdSockets.length - 1]._simulateMessage({
        type: 'game_state',
        data: { state: 'idle', wave: 0, score: 0 }
    });

    const postSize = vm.runInContext("TritiumStore.get('hazards') ? TritiumStore.get('hazards').size : 0", ctx);
    assertEqual(postSize, 0, 'hazards cleared on game reset to idle');

    const intel = vm.runInContext("TritiumStore.get('game.hostileIntel')", ctx);
    assertEqual(intel, null, 'hostileIntel cleared on game reset');

    const objectives = vm.runInContext("TritiumStore.get('game.hostileObjectives')", ctx);
    assertEqual(objectives, null, 'hostileObjectives cleared on game reset');

    const density = vm.runInContext("TritiumStore.get('game.crowdDensity')", ctx);
    assertEqual(density, null, 'crowdDensity cleared on game reset');
})();

// ============================================================
// Summary
// ============================================================

console.log('\n' + '='.repeat(50));
console.log(`Hazard & Sensor Tests: ${passed} passed, ${failed} failed`);
console.log('='.repeat(50));
process.exit(failed > 0 ? 1 : 0);
