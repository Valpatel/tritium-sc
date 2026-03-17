// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
/**
 * TRITIUM-SC addon-loader.js tests
 * Tests loadAddons, panel registration, layer events, shortcut events.
 * Run: node tests/js/test_addon_loader.js
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
// Mock EventBus
// ============================================================

const emittedEvents = [];
const EventBus = {
    _handlers: new Map(),
    on(event, handler) {
        if (!this._handlers.has(event)) this._handlers.set(event, new Set());
        this._handlers.get(event).add(handler);
        return () => this._handlers.get(event).delete(handler);
    },
    emit(event, data) {
        emittedEvents.push({ event, data });
        const handlers = this._handlers.get(event);
        if (handlers) handlers.forEach(h => { try { h(data); } catch(_) {} });
    },
};

// ============================================================
// Mock PanelManager
// ============================================================

class MockPanelManager {
    constructor() {
        this._registry = new Map();
    }
    register(def) {
        if (!def.id || !def.title) return;
        this._registry.set(def.id, def);
    }
    registeredIds() { return [...this._registry.keys()]; }
}

// ============================================================
// Mock fetch + dynamic import
// ============================================================

let fetchMockResponse = null;

function createFetchMock(response) {
    return async function fetch(url) {
        return {
            ok: response !== null,
            json: async () => response,
        };
    };
}

// ============================================================
// Load source via vm to get the functions
// ============================================================

const src = fs.readFileSync('src/frontend/js/command/addon-loader.js', 'utf8');

// We can't use ES module import in Node CJS tests, so we extract the
// functions by transpiling the module syntax.
// Replace import/export with CJS equivalents:
let cjsSrc = src
    .replace(/^import\s+\{[^}]+\}\s+from\s+'[^']+';$/gm, '')
    .replace(/^export\s+async\s+function\s+/gm, 'async function ')
    .replace(/^export\s+function\s+/gm, 'function ')
    .replace(/^export\s+/gm, '');

// Wrap in an IIFE that returns the loadAddons function
const wrappedSrc = `
(function(EventBus, console) {
    ${cjsSrc}
    return { loadAddons };
})
`;

const factory = vm.runInThisContext(wrappedSrc, { filename: 'addon-loader.js' });
const { loadAddons } = factory(EventBus, console);

// ============================================================
// Tests
// ============================================================

async function runTests() {

    // Test 1: loadAddons handles fetch failure gracefully
    {
        const pm = new MockPanelManager();
        const origFetch = globalThis.fetch;
        globalThis.fetch = async () => { throw new Error('network error'); };
        await loadAddons(pm);
        assert(pm.registeredIds().length === 0, 'No panels registered on fetch error');
        globalThis.fetch = origFetch;
    }

    // Test 2: loadAddons handles non-ok response
    {
        const pm = new MockPanelManager();
        globalThis.fetch = async () => ({ ok: false, json: async () => [] });
        await loadAddons(pm);
        assert(pm.registeredIds().length === 0, 'No panels registered on non-ok response');
    }

    // Test 3: loadAddons handles empty addon list
    {
        const pm = new MockPanelManager();
        globalThis.fetch = async () => ({ ok: true, json: async () => [] });
        emittedEvents.length = 0;
        await loadAddons(pm);
        assert(pm.registeredIds().length === 0, 'No panels registered for empty addon list');
        const loadedEvt = emittedEvents.find(e => e.event === 'addons:loaded');
        assert(!loadedEvt, 'No addons:loaded event for empty list');
    }

    // Test 4: loadAddons registers layers via EventBus
    {
        emittedEvents.length = 0;
        const pm = new MockPanelManager();
        globalThis.fetch = async () => ({
            ok: true,
            json: async () => [{
                id: 'test-addon',
                panels: [],
                layers: [
                    { id: 'testLayer1', label: 'Test Layer 1', category: 'TEST', color: '#ff0000' },
                    { id: 'testLayer2', label: 'Test Layer 2', category: 'TEST', color: '#00ff00' },
                ],
                shortcuts: [],
            }],
        });
        await loadAddons(pm);
        const layerEvents = emittedEvents.filter(e => e.event === 'addon:layer-register');
        assert(layerEvents.length === 2, 'Two layer-register events emitted');
        assert(layerEvents[0].data.id === 'testLayer1', 'First layer has correct id');
        assert(layerEvents[0].data.addonId === 'test-addon', 'Layer event has addonId');
        assert(layerEvents[1].data.color === '#00ff00', 'Second layer has correct color');
    }

    // Test 5: loadAddons registers shortcuts via EventBus
    {
        emittedEvents.length = 0;
        const pm = new MockPanelManager();
        globalThis.fetch = async () => ({
            ok: true,
            json: async () => [{
                id: 'shortcut-addon',
                panels: [],
                layers: [],
                shortcuts: [
                    { key: 'Shift+M', action: 'test:action', description: 'Test shortcut' },
                ],
            }],
        });
        await loadAddons(pm);
        const shortcutEvents = emittedEvents.filter(e => e.event === 'addon:shortcut-register');
        assert(shortcutEvents.length === 1, 'One shortcut-register event emitted');
        assert(shortcutEvents[0].data.key === 'Shift+M', 'Shortcut has correct key');
        assert(shortcutEvents[0].data.addonId === 'shortcut-addon', 'Shortcut event has addonId');
    }

    // Test 6: loadAddons emits addons:loaded event
    {
        emittedEvents.length = 0;
        const pm = new MockPanelManager();
        globalThis.fetch = async () => ({
            ok: true,
            json: async () => [
                { id: 'addon-a', panels: [], layers: [], shortcuts: [] },
                { id: 'addon-b', panels: [], layers: [], shortcuts: [] },
            ],
        });
        await loadAddons(pm);
        const loadedEvt = emittedEvents.find(e => e.event === 'addons:loaded');
        assert(!!loadedEvt, 'addons:loaded event emitted');
        assert(loadedEvt.data.count === 2, 'addons:loaded event has correct count');
        assert(loadedEvt.data.ids.includes('addon-a'), 'addons:loaded includes addon-a');
        assert(loadedEvt.data.ids.includes('addon-b'), 'addons:loaded includes addon-b');
    }

    // Test 7: loadAddons skips addons without id
    {
        emittedEvents.length = 0;
        const pm = new MockPanelManager();
        globalThis.fetch = async () => ({
            ok: true,
            json: async () => [
                { panels: [], layers: [{ id: 'x', label: 'X' }], shortcuts: [] },
            ],
        });
        await loadAddons(pm);
        const layerEvents = emittedEvents.filter(e => e.event === 'addon:layer-register');
        assert(layerEvents.length === 0, 'No layer events for addon without id');
    }

    // Test 8: loadAddons handles panels with import failure gracefully
    {
        const pm = new MockPanelManager();
        // dynamic import will fail since /addons/... path doesn't resolve in Node
        globalThis.fetch = async () => ({
            ok: true,
            json: async () => [{
                id: 'broken-addon',
                panels: [{ file: 'nonexistent.js' }],
                layers: [],
                shortcuts: [],
            }],
        });
        // Should not throw
        await loadAddons(pm);
        assert(pm.registeredIds().length === 0, 'No panels registered when import fails');
    }

    // Test 9: loadAddons handles non-array response
    {
        const pm = new MockPanelManager();
        globalThis.fetch = async () => ({
            ok: true,
            json: async () => ({ addons: [] }), // object, not array
        });
        await loadAddons(pm);
        assert(pm.registeredIds().length === 0, 'No panels registered for non-array response');
    }

    // Done
    console.log(`\n=== addon-loader tests: ${passed} passed, ${failed} failed ===`);
    if (failed > 0) process.exit(1);
}

runTests();
