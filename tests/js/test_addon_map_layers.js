// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
/**
 * TRITIUM-SC addon-map-layers.js tests
 * Tests AddonMapLayers: addLayer, refreshLayer, toggleLayer, polling, destroy.
 * Run: node tests/js/test_addon_map_layers.js
 */

// Simple test runner
let passed = 0, failed = 0;
function assert(cond, msg) {
    if (!cond) { console.error('FAIL:', msg); failed++; }
    else { console.log('PASS:', msg); passed++; }
}

// ============================================================
// Mock EventBus (must exist before we load the module)
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
    },
};

// ============================================================
// Mock MapLibre map
// ============================================================
class MockMap {
    constructor() {
        this.sources = {};
        this.layers = {};
    }
    addSource(id, opts) {
        this.sources[id] = { ...opts, _data: opts.data };
    }
    addLayer(layerDef) {
        this.layers[layerDef.id] = layerDef;
    }
    getSource(id) {
        const s = this.sources[id];
        if (!s) return null;
        return {
            setData(data) { s._data = data; },
            _data: s._data,
        };
    }
    getLayer(id) {
        return this.layers[id] || null;
    }
    removeSource(id) {
        delete this.sources[id];
    }
    removeLayer(id) {
        delete this.layers[id];
    }
    setLayoutProperty(layerId, prop, value) {
        const l = this.layers[layerId];
        if (l) {
            if (!l.layout) l.layout = {};
            l.layout[prop] = value;
        }
    }
}

// ============================================================
// Mock fetch for testing
// ============================================================
const fetchResponses = {};
globalThis.fetch = async function(url) {
    const resp = fetchResponses[url];
    if (!resp) return { ok: false, status: 404 };
    return {
        ok: true,
        status: 200,
        json: async () => resp,
    };
};

// ============================================================
// Load AddonMapLayers via vm (CommonJS wrapper for ESM source)
// ============================================================
const fs = require('fs');
const vm = require('vm');
const path = require('path');

const srcPath = path.resolve(__dirname, '../../src/frontend/js/command/addon-map-layers.js');
let src = fs.readFileSync(srcPath, 'utf-8');

// Rewrite ESM to CommonJS for Node
src = src.replace(/import\s*\{[^}]*\}\s*from\s*'[^']*';/g, '');
src = src.replace(/export\s+class\s+/g, 'class ');
src += '\nmodule.exports = { AddonMapLayers };';

const sandbox = {
    console,
    module: { exports: {} },
    exports: {},
    require,
    globalThis,
    fetch: globalThis.fetch,
    setInterval: globalThis.setInterval,
    clearInterval: globalThis.clearInterval,
    EventBus,
};
sandbox.module.exports = {};
vm.runInNewContext(src, sandbox, { filename: srcPath });

const { AddonMapLayers } = sandbox.module.exports;

// ============================================================
// Tests
// ============================================================

// --- Test: constructor ---
{
    const map = new MockMap();
    const aml = new AddonMapLayers(map);
    assert(aml._map === map, 'constructor stores map');
    assert(aml._layers && typeof aml._layers.has === 'function', 'constructor creates _layers Map');
    assert(aml._layers.size === 0, 'constructor starts with no layers');
}

// --- Test: addLayer creates source and 3 sub-layers ---
{
    const map = new MockMap();
    const aml = new AddonMapLayers(map);
    emittedEvents.length = 0;

    // Mock the geojson endpoint
    fetchResponses['/api/addons/hackrf/geojson/adsb'] = {
        type: 'FeatureCollection',
        features: [
            { type: 'Feature', geometry: { type: 'Point', coordinates: [0, 0] }, properties: { callsign: 'TEST' } },
        ],
    };

    aml.addLayer({
        layer_id: 'hackrf-adsb',
        addon_id: 'hackrf',
        label: 'ADS-B Aircraft',
        category: 'aircraft',
        color: '#ffaa00',
        geojson_endpoint: '/api/addons/hackrf/geojson/adsb',
        refresh_interval: 5,
        visible_by_default: true,
    });

    assert(map.sources['hackrf-adsb'] !== undefined, 'addLayer creates GeoJSON source');
    assert(map.layers['hackrf-adsb-circle'] !== undefined, 'addLayer creates circle sub-layer');
    assert(map.layers['hackrf-adsb-line'] !== undefined, 'addLayer creates line sub-layer');
    assert(map.layers['hackrf-adsb-fill'] !== undefined, 'addLayer creates fill sub-layer');
    assert(aml._layers.has('hackrf-adsb'), 'addLayer registers in _layers');

    const entry = aml._layers.get('hackrf-adsb');
    assert(entry.visible === true, 'addLayer respects visible_by_default');
    assert(entry.timer !== null, 'addLayer starts polling timer');

    // Check circle paint color
    assert(map.layers['hackrf-adsb-circle'].paint['circle-color'] === '#ffaa00',
        'addLayer uses specified color');

    // Check visibility layout
    assert(map.layers['hackrf-adsb-circle'].layout.visibility === 'visible',
        'addLayer sets visible layout');

    // Check event emitted
    const addedEvent = emittedEvents.find(e => e.event === 'addon-layers:added');
    assert(addedEvent && addedEvent.data.layer_id === 'hackrf-adsb', 'addLayer emits addon-layers:added event');

    aml.destroy();
}

// --- Test: addLayer with visible_by_default=false ---
{
    const map = new MockMap();
    const aml = new AddonMapLayers(map);

    aml.addLayer({
        layer_id: 'test-hidden',
        addon_id: 'test',
        label: 'Hidden Layer',
        category: 'rf_signal',
        color: '#b060ff',
        geojson_endpoint: '/api/test/geojson',
        refresh_interval: 10,
        visible_by_default: false,
    });

    assert(map.layers['test-hidden-circle'].layout.visibility === 'none',
        'addLayer with visible_by_default=false sets none');
    assert(aml._layers.get('test-hidden').visible === false,
        'entry.visible is false when visible_by_default=false');

    aml.destroy();
}

// --- Test: addLayer rejects invalid definition ---
{
    const map = new MockMap();
    const aml = new AddonMapLayers(map);

    aml.addLayer({ addon_id: 'test' }); // no layer_id, no endpoint
    assert(aml._layers.size === 0, 'addLayer rejects definition without layer_id');

    aml.addLayer({ layer_id: 'test', addon_id: 'test' }); // no endpoint
    assert(aml._layers.size === 0, 'addLayer rejects definition without endpoint');
}

// --- Test: addLayer skips duplicates ---
{
    const map = new MockMap();
    const aml = new AddonMapLayers(map);

    const def = {
        layer_id: 'dup-test',
        addon_id: 'test',
        label: 'Dup',
        geojson_endpoint: '/api/test/dup',
        refresh_interval: 5,
    };

    aml.addLayer(def);
    aml.addLayer(def); // duplicate
    assert(aml._layers.size === 1, 'addLayer does not duplicate existing layer');
    aml.destroy();
}

// --- Test: refreshLayer updates source data ---
async function testRefreshLayer() {
    const map = new MockMap();
    const aml = new AddonMapLayers(map);

    fetchResponses['/api/test/refresh'] = {
        type: 'FeatureCollection',
        features: [
            { type: 'Feature', geometry: { type: 'Point', coordinates: [1, 2] }, properties: {} },
        ],
    };

    aml.addLayer({
        layer_id: 'refresh-test',
        addon_id: 'test',
        label: 'Refresh Test',
        geojson_endpoint: '/api/test/refresh',
        refresh_interval: 60,
    });

    // Wait for initial fetch
    await new Promise(r => setTimeout(r, 50));

    const src = map.getSource('refresh-test');
    assert(src !== null, 'refreshLayer: source exists');
    // The data should have been updated by the initial refreshLayer call
    assert(src._data && src._data.features && src._data.features.length === 1,
        'refreshLayer updates source data with fetched GeoJSON');

    aml.destroy();
}

// --- Test: toggleLayer changes visibility ---
{
    const map = new MockMap();
    const aml = new AddonMapLayers(map);

    aml.addLayer({
        layer_id: 'toggle-test',
        addon_id: 'test',
        label: 'Toggle Test',
        geojson_endpoint: '/api/test/toggle',
        refresh_interval: 60,
        visible_by_default: true,
    });

    aml.toggleLayer('toggle-test', false);
    assert(aml._layers.get('toggle-test').visible === false,
        'toggleLayer(false) updates entry.visible');
    assert(map.layers['toggle-test-circle'].layout.visibility === 'none',
        'toggleLayer(false) sets circle to none');
    assert(map.layers['toggle-test-line'].layout.visibility === 'none',
        'toggleLayer(false) sets line to none');

    aml.toggleLayer('toggle-test', true);
    assert(aml._layers.get('toggle-test').visible === true,
        'toggleLayer(true) updates entry.visible');
    assert(map.layers['toggle-test-circle'].layout.visibility === 'visible',
        'toggleLayer(true) sets circle to visible');

    aml.destroy();
}

// --- Test: removeLayer cleans up ---
{
    const map = new MockMap();
    const aml = new AddonMapLayers(map);
    emittedEvents.length = 0;

    aml.addLayer({
        layer_id: 'remove-test',
        addon_id: 'test',
        label: 'Remove Test',
        geojson_endpoint: '/api/test/remove',
        refresh_interval: 60,
    });

    assert(aml._layers.has('remove-test'), 'removeLayer precondition: layer exists');

    aml.removeLayer('remove-test');
    assert(!aml._layers.has('remove-test'), 'removeLayer removes from _layers');
    assert(map.sources['remove-test'] === undefined, 'removeLayer removes source');
    assert(map.layers['remove-test-circle'] === undefined, 'removeLayer removes circle layer');
    assert(map.layers['remove-test-line'] === undefined, 'removeLayer removes line layer');
    assert(map.layers['remove-test-fill'] === undefined, 'removeLayer removes fill layer');

    const removedEvent = emittedEvents.find(e => e.event === 'addon-layers:removed');
    assert(removedEvent && removedEvent.data.layer_id === 'remove-test',
        'removeLayer emits addon-layers:removed');
}

// --- Test: destroy cleans up all layers ---
{
    const map = new MockMap();
    const aml = new AddonMapLayers(map);

    aml.addLayer({
        layer_id: 'destroy-a',
        addon_id: 'test',
        label: 'A',
        geojson_endpoint: '/api/test/a',
        refresh_interval: 60,
    });
    aml.addLayer({
        layer_id: 'destroy-b',
        addon_id: 'test',
        label: 'B',
        geojson_endpoint: '/api/test/b',
        refresh_interval: 60,
    });

    assert(aml._layers.size === 2, 'destroy precondition: 2 layers');

    aml.destroy();
    assert(aml._layers.size === 0, 'destroy removes all layers');
    assert(Object.keys(map.sources).length === 0, 'destroy removes all sources');
    assert(Object.keys(map.layers).length === 0, 'destroy removes all sub-layers');
}

// --- Test: polling starts and stops ---
{
    const map = new MockMap();
    const aml = new AddonMapLayers(map);

    aml.addLayer({
        layer_id: 'poll-test',
        addon_id: 'test',
        label: 'Poll',
        geojson_endpoint: '/api/test/poll',
        refresh_interval: 1,
    });

    const entry = aml._layers.get('poll-test');
    assert(entry.timer !== null, 'polling: timer is set after addLayer');

    aml._stopPolling('poll-test');
    assert(entry.timer === null, '_stopPolling clears timer');

    aml._startPolling('poll-test', 5000);
    assert(entry.timer !== null, '_startPolling sets a new timer');

    aml.destroy();
}

// --- Test: loadFromAddons parses API response ---
async function testLoadFromAddons() {
    const map = new MockMap();
    const aml = new AddonMapLayers(map);

    fetchResponses['/api/addons/geojson-layers'] = [
        {
            layer_id: 'hackrf-adsb',
            addon_id: 'hackrf',
            label: 'ADS-B Aircraft',
            category: 'SDR',
            color: '#ffaa00',
            geojson_endpoint: '/api/addons/hackrf/geojson/adsb',
            refresh_interval: 3,
            visible_by_default: true,
        },
        {
            layer_id: 'meshtastic-nodes',
            addon_id: 'meshtastic',
            label: 'Mesh Nodes',
            category: 'MESH',
            color: '#00d4aa',
            geojson_endpoint: '/api/addons/meshtastic/geojson/nodes',
            refresh_interval: 10,
            visible_by_default: true,
        },
    ];

    await aml.loadFromAddons();
    assert(aml._layers.size === 2, 'loadFromAddons creates layers from API response');
    assert(aml._layers.has('hackrf-adsb'), 'loadFromAddons creates hackrf-adsb layer');
    assert(aml._layers.has('meshtastic-nodes'), 'loadFromAddons creates meshtastic-nodes layer');
    assert(map.sources['hackrf-adsb'] !== undefined, 'loadFromAddons creates hackrf-adsb source');
    assert(map.sources['meshtastic-nodes'] !== undefined, 'loadFromAddons creates meshtastic-nodes source');

    aml.destroy();
}

// --- Test: loadFromAddons handles empty/error gracefully ---
async function testLoadFromAddonsError() {
    const map = new MockMap();
    const aml = new AddonMapLayers(map);

    // Remove the endpoint to simulate 404
    delete fetchResponses['/api/addons/geojson-layers'];

    await aml.loadFromAddons();
    assert(aml._layers.size === 0, 'loadFromAddons handles 404 gracefully');

    aml.destroy();
}

// --- Test: default color fallback ---
{
    const map = new MockMap();
    const aml = new AddonMapLayers(map);

    aml.addLayer({
        layer_id: 'fallback-color',
        addon_id: 'test',
        label: 'Fallback',
        geojson_endpoint: '/api/test/fallback',
        refresh_interval: 60,
        // no color, no matching category
    });

    assert(map.layers['fallback-color-circle'].paint['circle-color'] === '#00f0ff',
        'addLayer uses default cyan when no color or matching category');

    aml.destroy();
}

// --- Test: category color lookup ---
{
    const map = new MockMap();
    const aml = new AddonMapLayers(map);

    aml.addLayer({
        layer_id: 'cat-color',
        addon_id: 'test',
        label: 'Aircraft',
        category: 'aircraft',
        geojson_endpoint: '/api/test/aircraft',
        refresh_interval: 60,
        // no explicit color — should use category color
    });

    assert(map.layers['cat-color-circle'].paint['circle-color'] === '#ffaa00',
        'addLayer uses category color when no explicit color');

    aml.destroy();
}

// Run async tests
(async () => {
    await testRefreshLayer();
    await testLoadFromAddons();
    await testLoadFromAddonsError();

    console.log(`\n--- RESULTS: ${passed} passed, ${failed} failed ---`);
    if (failed > 0) process.exit(1);
})();
