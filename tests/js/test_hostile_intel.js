// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
/**
 * TRITIUM-SC Hostile Commander Intel Tests
 * Tests WebSocket handler for hostile_intel events and HUD canvas rendering.
 * Run: node tests/js/test_hostile_intel.js
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
// Mock timer system
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

function clearAllTimers() {
    pendingTimers.clear();
    timerIdCounter = 0;
}

// ============================================================
// Mock WebSocket
// ============================================================

class MockWebSocket {
    static CONNECTING = 0;
    static OPEN = 1;
    static CLOSING = 2;
    static CLOSED = 3;

    constructor(url) {
        this.url = url;
        this.readyState = MockWebSocket.OPEN;
        this.onopen = null;
        this.onclose = null;
        this.onerror = null;
        this.onmessage = null;
        this._sent = [];
    }
    send(data) { this._sent.push(data); }
    close() { this.readyState = MockWebSocket.CLOSED; }
    _simulateMessage(data) {
        if (this.onmessage) {
            this.onmessage({ data: typeof data === 'string' ? data : JSON.stringify(data) });
        }
    }
}

// ============================================================
// Load source files
// ============================================================

const storeCode = fs.readFileSync(__dirname + '/../../src/frontend/js/command/store.js', 'utf8');
const eventsCode = fs.readFileSync(__dirname + '/../../src/frontend/js/command/events.js', 'utf8');
const wsCode = fs.readFileSync(__dirname + '/../../src/frontend/js/command/websocket.js', 'utf8');
const hudCode = fs.readFileSync(__dirname + '/../../src/frontend/js/war-hud.js', 'utf8');

let _bridge = {};

function createWsContext() {
    clearAllTimers();
    _bridge = {};

    const ctx = vm.createContext({
        Math, Date, console, Map, Set, Array, Object, Number, String, JSON,
        Infinity, undefined, Error, TypeError, Boolean, parseInt, parseFloat,
        setTimeout: mockSetTimeout,
        clearTimeout: mockClearTimeout,
        setInterval: () => 0,
        clearInterval: () => {},
        WebSocket: MockWebSocket,
        _bridge,
        window: {
            location: { protocol: 'http:', host: 'localhost:8000' },
        },
    });

    const storeStripped = storeCode.replace(/^export\s+/gm, '');
    vm.runInContext(storeStripped, ctx);

    const eventsStripped = eventsCode.replace(/^export\s+/gm, '');
    vm.runInContext(eventsStripped, ctx);

    const wsStripped = wsCode
        .replace(/^import\s+.*$/gm, '')
        .replace(/^export\s+/gm, '');
    vm.runInContext(wsStripped, ctx);

    return ctx;
}

function listenEvent(ctx, eventName) {
    vm.runInContext(
        `EventBus.on("${eventName}", function(d) { _bridge["${eventName}"] = d; })`,
        ctx
    );
}

// ============================================================
// Create HUD context for canvas rendering tests
// ============================================================

const mockElements = {};
function resetElements() {
    Object.keys(mockElements).forEach(k => delete mockElements[k]);
}

function createHudContext() {
    resetElements();
    let code = hudCode;
    code += `\nwindow._hudState = _hudState;\nwindow._formatNum = _formatNum;\n`;

    const ctx = vm.createContext({
        Math, console, Array, Object, Number, Boolean, parseInt, parseFloat,
        Infinity, String,
        Date: { now: () => 10000 },
        setTimeout: (fn, ms) => 0,
        clearTimeout: () => {},
        setInterval: (fn, ms) => 0,
        clearInterval: () => {},
        fetch: () => ({ then: () => ({ then: () => ({ catch: () => {} }), catch: () => {} }) }),
        window: {},
        warState: {
            audioCtx: null,
            targets: [],
            selectedTargets: [],
            effects: [],
            dispatchArrows: [],
            stats: { eliminations: 0, breaches: 0, dispatches: 0 },
        },
        warCombatReset: () => {},
        document: {
            getElementById(id) {
                if (!mockElements[id]) {
                    mockElements[id] = {
                        style: { display: '', opacity: '' },
                        textContent: '',
                        innerHTML: '',
                        className: '',
                        classList: {
                            _classes: [],
                            add(cls) { this._classes.push(cls); },
                            remove(cls) { this._classes = this._classes.filter(c => c !== cls); },
                        },
                        onclick: null,
                        offsetWidth: 100,
                    };
                }
                return mockElements[id];
            },
            createElement(tag) {
                const el = { _text: '' };
                Object.defineProperty(el, 'textContent', {
                    get() { return el._text; },
                    set(v) { el._text = String(v); },
                });
                Object.defineProperty(el, 'innerHTML', {
                    get() { return el._text; },
                    set(v) { el._text = String(v); },
                });
                return el;
            },
        },
    });

    vm.runInContext(code, ctx);
    return ctx;
}

function createMockCanvasCtx() {
    return {
        saved: 0, restored: 0,
        fillStyle: '', strokeStyle: '', globalAlpha: 1,
        font: '', textAlign: '', textBaseline: '',
        lineWidth: 1,
        shadowColor: '', shadowBlur: 0,
        fillRects: [],
        fillTexts: [],
        strokeRects: [],
        save() { this.saved++; },
        restore() { this.restored++; },
        beginPath() {},
        arc() {},
        fill() {},
        fillRect(x, y, w, h) { this.fillRects.push({ x, y, w, h }); },
        fillText(text, x, y) { this.fillTexts.push({ text, x, y, fillStyle: this.fillStyle }); },
        strokeRect(x, y, w, h) { this.strokeRects.push({ x, y, w, h }); },
        stroke() {},
        moveTo() {},
        lineTo() {},
        closePath() {},
        measureText(t) { return { width: t.length * 6 }; },
    };
}

// ============================================================
// TESTS: WebSocket handler stores data in TritiumStore
// ============================================================

console.log('\n--- WebSocket handler: hostile_intel stores data ---');

(function testHostileIntelStoresInStore() {
    const ctx = createWsContext();
    const ws = vm.runInContext('new WebSocketManager()', ctx);
    ws.connect();

    const sock = ws._ws;
    sock._simulateMessage({
        type: 'amy_hostile_intel',
        data: {
            threat_level: 'moderate',
            force_ratio: 1.3,
            hostile_count: 8,
            friendly_count: 6,
            recommended_action: 'assault',
            priority_targets: [],
            objectives: {},
        },
    });

    const intel = vm.runInContext('TritiumStore.get("game.hostileIntel")', ctx);
    assert(intel !== undefined && intel !== null, 'hostile_intel data stored in game.hostileIntel');
    assertEqual(intel.threat_level, 'moderate', 'threat_level stored correctly');
    assertEqual(intel.force_ratio, 1.3, 'force_ratio stored correctly');
    assertEqual(intel.recommended_action, 'assault', 'recommended_action stored correctly');
})();

// ============================================================
// TESTS: WebSocket handler emits hostile:intel event
// ============================================================

console.log('\n--- WebSocket handler: hostile_intel emits event ---');

(function testHostileIntelEmitsEvent() {
    const ctx = createWsContext();
    listenEvent(ctx, 'hostile:intel');
    const ws = vm.runInContext('new WebSocketManager()', ctx);
    ws.connect();

    ws._ws._simulateMessage({
        type: 'amy_hostile_intel',
        data: {
            threat_level: 'high',
            force_ratio: 0.7,
            hostile_count: 3,
            friendly_count: 5,
            recommended_action: 'flank',
            priority_targets: [],
        },
    });

    assert('hostile:intel' in _bridge, 'hostile:intel event emitted');
    assertEqual(_bridge['hostile:intel'].threat_level, 'high', 'emitted data has correct threat_level');
})();

// ============================================================
// TESTS: Amy-prefixed variant works the same
// ============================================================

console.log('\n--- Amy-prefixed variant works ---');

(function testAmyPrefixedVariant() {
    const ctx = createWsContext();
    listenEvent(ctx, 'hostile:intel');
    const ws = vm.runInContext('new WebSocketManager()', ctx);
    ws.connect();

    ws._ws._simulateMessage({
        type: 'amy_hostile_intel',
        data: {
            threat_level: 'critical',
            force_ratio: 0.3,
            hostile_count: 2,
            friendly_count: 7,
            recommended_action: 'retreat',
            priority_targets: [],
        },
    });

    const intel = vm.runInContext('TritiumStore.get("game.hostileIntel")', ctx);
    assertEqual(intel.threat_level, 'critical', 'amy_ prefix: threat_level stored');
    assert('hostile:intel' in _bridge, 'amy_ prefix: hostile:intel event emitted');
})();

(function testUnprefixedVariant() {
    const ctx = createWsContext();
    listenEvent(ctx, 'hostile:intel');
    const ws = vm.runInContext('new WebSocketManager()', ctx);
    ws.connect();

    ws._ws._simulateMessage({
        type: 'hostile_intel',
        data: {
            threat_level: 'low',
            force_ratio: 3.0,
            hostile_count: 9,
            friendly_count: 3,
            recommended_action: 'advance',
            priority_targets: [],
        },
    });

    const intel = vm.runInContext('TritiumStore.get("game.hostileIntel")', ctx);
    assertEqual(intel.threat_level, 'low', 'unprefixed: threat_level stored');
    assert('hostile:intel' in _bridge, 'unprefixed: hostile:intel event emitted');
})();

// ============================================================
// TESTS: Handles missing/null data gracefully
// ============================================================

console.log('\n--- Handles missing/null data gracefully ---');

(function testHandlesNullData() {
    const ctx = createWsContext();
    const ws = vm.runInContext('new WebSocketManager()', ctx);
    ws.connect();

    // Should not throw
    ws._ws._simulateMessage({
        type: 'amy_hostile_intel',
        data: null,
    });

    assert(true, 'null data does not throw');
})();

(function testHandlesMissingFields() {
    const ctx = createWsContext();
    const ws = vm.runInContext('new WebSocketManager()', ctx);
    ws.connect();

    ws._ws._simulateMessage({
        type: 'amy_hostile_intel',
        data: { threat_level: 'low' },
    });

    const intel = vm.runInContext('TritiumStore.get("game.hostileIntel")', ctx);
    assertEqual(intel.threat_level, 'low', 'partial data stored without crash');
    assert(intel.force_ratio === undefined, 'missing force_ratio is undefined');
})();

(function testHandlesEmptyMessage() {
    const ctx = createWsContext();
    const ws = vm.runInContext('new WebSocketManager()', ctx);
    ws.connect();

    // No data field at all — use msg itself as data
    ws._ws._simulateMessage({
        type: 'amy_hostile_intel',
    });

    assert(true, 'message with no data field does not throw');
})();

// ============================================================
// TESTS: HUD renders force_ratio text
// ============================================================

console.log('\n--- HUD renders force_ratio ---');

(function testHudRendersForceRatioHostileAdvantage() {
    const hudCtx = createHudContext();
    const w = hudCtx.window;
    const st = w._hudState;

    // Set game state to active and add hostile intel
    st.gameState = 'active';

    // Create mock canvas context
    const mockCtx = createMockCanvasCtx();

    // Call the HUD draw function with hostile intel data
    if (typeof w.warHudDrawHostileIntel === 'function') {
        w.warHudDrawHostileIntel(mockCtx, 800, 600, {
            threat_level: 'moderate',
            force_ratio: 1.3,
            recommended_action: 'assault',
        });

        const ratioTexts = mockCtx.fillTexts.filter(t =>
            typeof t.text === 'string' && t.text.includes('1.3')
        );
        assert(ratioTexts.length > 0, 'force_ratio 1.3 text rendered on canvas');
    } else {
        assert(false, 'warHudDrawHostileIntel function not found');
    }
})();

(function testHudRendersForceRatioFriendlyAdvantage() {
    const hudCtx = createHudContext();
    const w = hudCtx.window;
    const st = w._hudState;
    st.gameState = 'active';

    const mockCtx = createMockCanvasCtx();

    if (typeof w.warHudDrawHostileIntel === 'function') {
        w.warHudDrawHostileIntel(mockCtx, 800, 600, {
            threat_level: 'high',
            force_ratio: 0.5,
            recommended_action: 'flank',
        });

        const ratioTexts = mockCtx.fillTexts.filter(t =>
            typeof t.text === 'string' && t.text.includes('0.5')
        );
        assert(ratioTexts.length > 0, 'force_ratio 0.5 text rendered on canvas');
    } else {
        assert(false, 'warHudDrawHostileIntel function not found');
    }
})();

// ============================================================
// TESTS: HUD renders threat_level with correct color
// ============================================================

console.log('\n--- HUD renders threat_level with color ---');

(function testThreatLevelLowGreen() {
    const hudCtx = createHudContext();
    const w = hudCtx.window;
    w._hudState.gameState = 'active';
    const mockCtx = createMockCanvasCtx();

    if (typeof w.warHudDrawHostileIntel === 'function') {
        w.warHudDrawHostileIntel(mockCtx, 800, 600, {
            threat_level: 'low',
            force_ratio: 3.0,
            recommended_action: 'advance',
        });

        const threatTexts = mockCtx.fillTexts.filter(t =>
            typeof t.text === 'string' && t.text.toUpperCase().includes('LOW')
        );
        assert(threatTexts.length > 0, 'LOW threat level text rendered');
        // Check that green color was used
        const greenUsed = mockCtx.fillTexts.some(t =>
            t.text.toUpperCase().includes('LOW') && t.fillStyle && t.fillStyle.includes('05ffa1')
        );
        assert(greenUsed, 'LOW threat uses green color (#05ffa1)');
    } else {
        assert(false, 'warHudDrawHostileIntel function not found');
        assert(false, 'warHudDrawHostileIntel function not found (color check)');
    }
})();

(function testThreatLevelModerateYellow() {
    const hudCtx = createHudContext();
    const w = hudCtx.window;
    w._hudState.gameState = 'active';
    const mockCtx = createMockCanvasCtx();

    if (typeof w.warHudDrawHostileIntel === 'function') {
        w.warHudDrawHostileIntel(mockCtx, 800, 600, {
            threat_level: 'moderate',
            force_ratio: 1.3,
            recommended_action: 'assault',
        });

        const threatTexts = mockCtx.fillTexts.filter(t =>
            typeof t.text === 'string' && t.text.toUpperCase().includes('MODERATE')
        );
        assert(threatTexts.length > 0, 'MODERATE threat level text rendered');
        const yellowUsed = mockCtx.fillTexts.some(t =>
            t.text.toUpperCase().includes('MODERATE') && t.fillStyle && t.fillStyle.includes('fcee0a')
        );
        assert(yellowUsed, 'MODERATE threat uses yellow color (#fcee0a)');
    } else {
        assert(false, 'warHudDrawHostileIntel function not found');
        assert(false, 'warHudDrawHostileIntel function not found (color check)');
    }
})();

(function testThreatLevelHighOrange() {
    const hudCtx = createHudContext();
    const w = hudCtx.window;
    w._hudState.gameState = 'active';
    const mockCtx = createMockCanvasCtx();

    if (typeof w.warHudDrawHostileIntel === 'function') {
        w.warHudDrawHostileIntel(mockCtx, 800, 600, {
            threat_level: 'high',
            force_ratio: 0.7,
            recommended_action: 'flank',
        });

        const threatTexts = mockCtx.fillTexts.filter(t =>
            typeof t.text === 'string' && t.text.toUpperCase().includes('HIGH')
        );
        assert(threatTexts.length > 0, 'HIGH threat level text rendered');
        const orangeUsed = mockCtx.fillTexts.some(t =>
            t.text.toUpperCase().includes('HIGH') && t.fillStyle && t.fillStyle.includes('ffa500')
        );
        assert(orangeUsed, 'HIGH threat uses orange color (#ffa500)');
    } else {
        assert(false, 'warHudDrawHostileIntel function not found');
        assert(false, 'warHudDrawHostileIntel function not found (color check)');
    }
})();

(function testThreatLevelCriticalRed() {
    const hudCtx = createHudContext();
    const w = hudCtx.window;
    w._hudState.gameState = 'active';
    const mockCtx = createMockCanvasCtx();

    if (typeof w.warHudDrawHostileIntel === 'function') {
        w.warHudDrawHostileIntel(mockCtx, 800, 600, {
            threat_level: 'critical',
            force_ratio: 0.2,
            recommended_action: 'retreat',
        });

        const threatTexts = mockCtx.fillTexts.filter(t =>
            typeof t.text === 'string' && t.text.toUpperCase().includes('CRITICAL')
        );
        assert(threatTexts.length > 0, 'CRITICAL threat level text rendered');
        const redUsed = mockCtx.fillTexts.some(t =>
            t.text.toUpperCase().includes('CRITICAL') && t.fillStyle && t.fillStyle.includes('ff2a6d')
        );
        assert(redUsed, 'CRITICAL threat uses red color (#ff2a6d)');
    } else {
        assert(false, 'warHudDrawHostileIntel function not found');
        assert(false, 'warHudDrawHostileIntel function not found (color check)');
    }
})();

// ============================================================
// TESTS: HUD renders recommended_action text
// ============================================================

console.log('\n--- HUD renders recommended_action ---');

(function testHudRendersRecommendedAction() {
    const hudCtx = createHudContext();
    const w = hudCtx.window;
    w._hudState.gameState = 'active';
    const mockCtx = createMockCanvasCtx();

    if (typeof w.warHudDrawHostileIntel === 'function') {
        w.warHudDrawHostileIntel(mockCtx, 800, 600, {
            threat_level: 'moderate',
            force_ratio: 1.0,
            recommended_action: 'assault',
        });

        const actionTexts = mockCtx.fillTexts.filter(t =>
            typeof t.text === 'string' && t.text.toUpperCase().includes('ASSAULT')
        );
        assert(actionTexts.length > 0, 'recommended_action ASSAULT text rendered');
    } else {
        assert(false, 'warHudDrawHostileIntel function not found');
    }
})();

// ============================================================
// TESTS: HUD handles missing/null intel gracefully
// ============================================================

console.log('\n--- HUD handles null intel ---');

(function testHudHandlesNullIntel() {
    const hudCtx = createHudContext();
    const w = hudCtx.window;
    w._hudState.gameState = 'active';
    const mockCtx = createMockCanvasCtx();

    if (typeof w.warHudDrawHostileIntel === 'function') {
        // Should not throw with null
        w.warHudDrawHostileIntel(mockCtx, 800, 600, null);
        assert(true, 'null intel does not throw');

        // Should not throw with undefined
        w.warHudDrawHostileIntel(mockCtx, 800, 600, undefined);
        assert(true, 'undefined intel does not throw');

        // Should not throw with empty object
        w.warHudDrawHostileIntel(mockCtx, 800, 600, {});
        assert(true, 'empty object intel does not throw');
    } else {
        assert(false, 'warHudDrawHostileIntel function not found');
        assert(false, 'warHudDrawHostileIntel function not found');
        assert(false, 'warHudDrawHostileIntel function not found');
    }
})();

(function testHudSkipsWhenNotActive() {
    const hudCtx = createHudContext();
    const w = hudCtx.window;
    w._hudState.gameState = 'idle';
    const mockCtx = createMockCanvasCtx();

    if (typeof w.warHudDrawHostileIntel === 'function') {
        w.warHudDrawHostileIntel(mockCtx, 800, 600, {
            threat_level: 'moderate',
            force_ratio: 1.0,
            recommended_action: 'assault',
        });
        assertEqual(mockCtx.fillTexts.length, 0, 'no drawing when game is idle');
    } else {
        assert(false, 'warHudDrawHostileIntel function not found');
    }
})();

// ============================================================
// Summary
// ============================================================

console.log(`\n${'='.repeat(40)}`);
console.log(`Hostile Intel Tests: ${passed} passed, ${failed} failed`);
console.log(`${'='.repeat(40)}`);
process.exit(failed > 0 ? 1 : 0);
