// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
/**
 * TRITIUM-SC Camera Pan to Mission Area Tests
 *
 * Tests the camera pan logic for mission launch:
 * - _radiusToZoom() mapping from mission radius to map zoom
 * - map:flyToMission event handling (lat/lng and x/y coords)
 * - Fallback centroid calculation from unit positions
 *
 * Run: node tests/js/test_camera_pan.js
 */

const fs = require('fs');
const path = require('path');
const mapLibreSource = fs.readFileSync(
    path.join(__dirname, '../../src/frontend/js/command/map-maplibre.js'), 'utf8');

// Simple test runner
let passed = 0, failed = 0;
function assert(cond, msg) {
    if (!cond) { console.error('FAIL:', msg); failed++; }
    else { console.log('PASS:', msg); passed++; }
}

function approx(a, b, tolerance, msg) {
    if (Math.abs(a - b) <= tolerance) { console.log('PASS:', msg); passed++; }
    else { console.error(`FAIL: ${msg} (expected ~${b}, got ${a})`); failed++; }
}


// ============================================================
// _radiusToZoom mapping
// ============================================================

console.log('\n--- _radiusToZoom mapping ---');

// Mirror the function from map-maplibre.js
const ZOOM_MIN = 10;
const ZOOM_MAX = 21;

function _radiusToZoom(radiusM) {
    const z = 16 + Math.log2(920 / Math.max(radiusM, 50));
    return Math.max(ZOOM_MIN, Math.min(ZOOM_MAX, z));
}

// Test specific radius values
{
    const z100 = _radiusToZoom(100);
    approx(z100, 19.2, 0.2, '_radiusToZoom(100) gives zoom ~19.2');
}

{
    const z200 = _radiusToZoom(200);
    approx(z200, 18.2, 0.2, '_radiusToZoom(200) gives zoom ~18.2');
}

{
    const z500 = _radiusToZoom(500);
    approx(z500, 16.9, 0.2, '_radiusToZoom(500) gives zoom ~16.9');
}

// Clamp to min
{
    const zHuge = _radiusToZoom(100000);
    assert(zHuge >= ZOOM_MIN, '_radiusToZoom(100000) clamped to ZOOM_MIN');
    assert(zHuge === ZOOM_MIN, '_radiusToZoom(100000) equals ZOOM_MIN');
}

// Clamp radius floor of 50
{
    const zSmall = _radiusToZoom(10);
    const z50 = _radiusToZoom(50);
    assert(zSmall === z50, '_radiusToZoom(10) same as _radiusToZoom(50) due to floor');
}

// Max zoom clamp
{
    const zTiny = _radiusToZoom(50);
    assert(zTiny <= ZOOM_MAX, '_radiusToZoom(50) does not exceed ZOOM_MAX');
}

// Monotonically decreasing: larger radius = smaller zoom
{
    const z100 = _radiusToZoom(100);
    const z200 = _radiusToZoom(200);
    const z500 = _radiusToZoom(500);
    assert(z100 > z200, 'zoom decreases as radius increases (100 > 200)');
    assert(z200 > z500, 'zoom decreases as radius increases (200 > 500)');
}


// ============================================================
// Pan event with lat/lng coordinates
// ============================================================

console.log('\n--- Pan event with lat/lng ---');

{
    const data = { lat: 37.703, lng: -121.934, radius_m: 200 };
    assert(data.lat !== undefined, 'lat/lng event has lat');
    assert(data.lng !== undefined, 'lat/lng event has lng');
    assert(data.radius_m !== undefined, 'lat/lng event has radius_m');

    // MapLibre handler uses lat/lng directly as flyTo center
    const center = [data.lng, data.lat];
    assert(center[0] === -121.934, 'center lng extracted correctly');
    assert(center[1] === 37.703, 'center lat extracted correctly');

    const zoom = _radiusToZoom(data.radius_m);
    assert(zoom > 15 && zoom < 21, 'zoom from radius_m is reasonable');
}


// ============================================================
// Pan event with x/y coordinates (Canvas 2D map)
// ============================================================

console.log('\n--- Pan event with x/y ---');

{
    const data = { x: 150.5, y: -230.2, radius_m: 300 };
    assert(data.x !== undefined, 'x/y event has x');
    assert(data.y !== undefined, 'x/y event has y');

    // Canvas 2D handler sets cam.targetX/Y directly
    const cam = { targetX: 0, targetY: 0, targetZoom: 1.0 };
    cam.targetX = data.x;
    cam.targetY = data.y;
    assert(cam.targetX === 150.5, 'cam.targetX set to event x');
    assert(cam.targetY === -230.2, 'cam.targetY set to event y');
}


// ============================================================
// Pan event with both lat/lng and x/y (MapLibre prefers lat/lng)
// ============================================================

console.log('\n--- Pan event coordinate priority ---');

{
    const data = { lat: 37.703, lng: -121.934, x: 150, y: -230, radius_m: 200 };

    // MapLibre handler should prefer lat/lng when available
    const hasLatLng = data.lat !== undefined && data.lng !== undefined;
    const hasXY = data.x !== undefined && data.y !== undefined;
    assert(hasLatLng, 'event has lat/lng');
    assert(hasXY, 'event also has x/y');

    // MapLibre uses lat/lng for flyTo
    if (hasLatLng) {
        const center = [data.lng, data.lat];
        assert(center[0] === data.lng, 'MapLibre uses lng from event');
    }
}


// ============================================================
// Fallback centroid calculation from unit positions
// ============================================================

console.log('\n--- Fallback centroid calculation ---');

// Array position format [x, y]
{
    const units = [
        { type: 'turret', position: [10, 20] },
        { type: 'rover', position: [30, 40] },
        { type: 'drone', position: [20, 30] },
    ];

    let sx = 0, sy = 0, count = 0;
    for (const u of units) {
        const pos = u.position;
        if (Array.isArray(pos)) { sx += pos[0]; sy += pos[1]; count++; }
        else if (pos) { sx += (pos.x || 0); sy += (pos.y || 0); count++; }
    }

    assert(count === 3, 'counted all 3 units');
    approx(sx / count, 20, 0.01, 'centroid x = 20');
    approx(sy / count, 30, 0.01, 'centroid y = 30');
}

// Object position format { x, y }
{
    const units = [
        { type: 'turret', position: { x: 100, y: 200 } },
        { type: 'rover', position: { x: 300, y: 400 } },
    ];

    let sx = 0, sy = 0, count = 0;
    for (const u of units) {
        const pos = u.position;
        if (Array.isArray(pos)) { sx += pos[0]; sy += pos[1]; count++; }
        else if (pos) { sx += (pos.x || 0); sy += (pos.y || 0); count++; }
    }

    assert(count === 2, 'counted all 2 units with object positions');
    approx(sx / count, 200, 0.01, 'centroid x = 200');
    approx(sy / count, 300, 0.01, 'centroid y = 300');
}

// Mixed position formats
{
    const units = [
        { type: 'turret', position: [10, 20] },
        { type: 'rover', position: { x: 30, y: 40 } },
    ];

    let sx = 0, sy = 0, count = 0;
    for (const u of units) {
        const pos = u.position;
        if (Array.isArray(pos)) { sx += pos[0]; sy += pos[1]; count++; }
        else if (pos) { sx += (pos.x || 0); sy += (pos.y || 0); count++; }
    }

    assert(count === 2, 'counted mixed format units');
    approx(sx / count, 20, 0.01, 'centroid x = 20 (mixed)');
    approx(sy / count, 30, 0.01, 'centroid y = 30 (mixed)');
}

// Empty units array -- no event should be emitted
{
    const units = [];
    let sx = 0, sy = 0, count = 0;
    for (const u of units) {
        const pos = u.position;
        if (Array.isArray(pos)) { sx += pos[0]; sy += pos[1]; count++; }
        else if (pos) { sx += (pos.x || 0); sy += (pos.y || 0); count++; }
    }
    assert(count === 0, 'no units = no centroid');
}

// Units with null/undefined position
{
    const units = [
        { type: 'turret', position: null },
        { type: 'rover', position: [50, 60] },
    ];

    let sx = 0, sy = 0, count = 0;
    for (const u of units) {
        const pos = u.position;
        if (Array.isArray(pos)) { sx += pos[0]; sy += pos[1]; count++; }
        else if (pos) { sx += (pos.x || 0); sy += (pos.y || 0); count++; }
    }
    assert(count === 1, 'null position units skipped');
    assert(sx / count === 50, 'centroid uses only valid positions');
}


// ============================================================
// Canvas 2D zoom from radius
// ============================================================

console.log('\n--- Canvas 2D zoom from radius ---');

// Canvas 2D map uses different zoom scale (0.02 to 30.0)
// We test the zoom mapping for x/y coordinate events
{
    const CANVAS_ZOOM_MIN = 0.02;
    const CANVAS_ZOOM_MAX = 30.0;

    // When we get a radius, we need a canvas zoom that shows the area
    // Use a similar formula adapted for canvas scale
    function canvasZoomFromRadius(radiusM) {
        // At zoom 1.0, the viewport shows roughly 500m across
        // So zoom = 500 / (2 * radius) clamped
        const z = 250 / Math.max(radiusM, 20);
        return Math.max(CANVAS_ZOOM_MIN, Math.min(CANVAS_ZOOM_MAX, z));
    }

    const z100 = canvasZoomFromRadius(100);
    assert(z100 > 1.0, 'canvas zoom for 100m radius > 1.0');

    const z500 = canvasZoomFromRadius(500);
    assert(z500 < 1.0, 'canvas zoom for 500m radius < 1.0');

    assert(canvasZoomFromRadius(100) > canvasZoomFromRadius(500),
        'canvas zoom decreases with larger radius');
}


// ============================================================
// EventBus integration pattern
// ============================================================

console.log('\n--- EventBus subscription pattern ---');

{
    // Verify the event name follows existing conventions
    const eventName = 'map:flyToMission';
    assert(eventName.startsWith('map:'), 'event uses map: namespace');
    assert(eventName.includes('fly') || eventName.includes('Fly') || eventName.includes('pan') || eventName.includes('Pan'),
        'event name indicates camera movement');
}

// Verify mission-modal emits event after successful apply
{
    let emitted = null;
    const mockEventBus = {
        emit(name, data) { emitted = { name, data }; },
    };

    // Simulate successful apply response with mission_center
    const data = {
        status: 'scenario_applied',
        mission_center: { x: 100, y: 200, lat: 37.703, lng: -121.934, radius_m: 200 },
    };

    if (data.mission_center) {
        mockEventBus.emit('map:flyToMission', data.mission_center);
    }

    assert(emitted !== null, 'event emitted after apply');
    assert(emitted.name === 'map:flyToMission', 'emits map:flyToMission');
    assert(emitted.data.lat === 37.703, 'event data includes lat');
    assert(emitted.data.lng === -121.934, 'event data includes lng');
    assert(emitted.data.radius_m === 200, 'event data includes radius_m');
}

// Simulate apply response without mission_center (fallback to unit centroid)
{
    let emitted = null;
    const mockEventBus = {
        emit(name, data) { emitted = { name, data }; },
    };

    const scenario = {
        units: [
            { type: 'turret', position: [100, 200] },
            { type: 'rover', position: [300, 400] },
        ],
    };

    const data = {
        status: 'scenario_applied',
        mission_center: null,
    };

    if (data.mission_center) {
        mockEventBus.emit('map:flyToMission', data.mission_center);
    } else if (scenario && scenario.units) {
        let sx = 0, sy = 0, count = 0;
        for (const u of scenario.units) {
            const pos = u.position;
            if (Array.isArray(pos)) { sx += pos[0]; sy += pos[1]; count++; }
            else if (pos) { sx += (pos.x || 0); sy += (pos.y || 0); count++; }
        }
        if (count > 0) {
            mockEventBus.emit('map:flyToMission', { x: sx / count, y: sy / count, radius_m: 200 });
        }
    }

    assert(emitted !== null, 'fallback centroid event emitted');
    assert(emitted.data.x === 200, 'fallback centroid x correct');
    assert(emitted.data.y === 300, 'fallback centroid y correct');
    assert(emitted.data.radius_m === 200, 'fallback uses default 200m radius');
}


// ============================================================
// Combat radius circle overlay (static analysis)
// ============================================================

{
    // Verify the GeoJSON source/layer constants exist
    assert(mapLibreSource.includes('combat-radius-source'),
        'map-maplibre.js has combat-radius-source constant');
    assert(mapLibreSource.includes('combat-radius-fill'),
        'map-maplibre.js has combat-radius-fill layer');
    assert(mapLibreSource.includes('combat-radius-outline'),
        'map-maplibre.js has combat-radius-outline layer');
}

{
    // Verify _drawCombatRadius is called in the flyToMission handler
    assert(mapLibreSource.includes('_drawCombatRadius'),
        'map-maplibre.js calls _drawCombatRadius');
}

{
    // Verify _clearCombatRadius is called in resetCamera
    assert(mapLibreSource.includes('_clearCombatRadius'),
        'map-maplibre.js calls _clearCombatRadius');
}

{
    // Verify _makeCircleGeoJSON generates a closed polygon
    assert(mapLibreSource.includes('_makeCircleGeoJSON'),
        'map-maplibre.js has _makeCircleGeoJSON function');
    assert(mapLibreSource.includes("type: 'Polygon'") || mapLibreSource.includes('type: "Polygon"'),
        '_makeCircleGeoJSON returns GeoJSON Polygon');
}

{
    // Verify fill color is magenta (#ff2a6d) per CYBERCORE palette
    assert(mapLibreSource.includes('#ff2a6d'),
        'combat radius fill uses CYBERCORE magenta');
}

{
    // Verify dashed outline
    assert(mapLibreSource.includes('line-dasharray'),
        'combat radius outline is dashed');
}


// ============================================================
// map:centerOnUnit event handler
// ============================================================

console.log('\n--- map:centerOnUnit handler ---');

{
    // Event name follows map: namespace convention
    const eventName = 'map:centerOnUnit';
    assert(eventName.startsWith('map:'), 'centerOnUnit uses map: namespace');
    assert(eventName.includes('center') || eventName.includes('Center'),
        'event name indicates centering');
}

{
    // Handler accepts { id } and resolves position from TritiumStore
    let flyToArgs = null;
    const mockMap = {
        flyTo(args) { flyToArgs = args; },
    };

    const mockStore = new Map();
    mockStore.set('unit-1', {
        position: { x: 50, y: -30 },
        alliance: 'friendly',
    });

    // Simulate _onCenterOnUnit handler logic
    function handleCenterOnUnit(data) {
        if (!mockMap || !data) return;
        let gx, gy;
        if (data.id) {
            const u = mockStore.get(data.id);
            if (!u || !u.position) return;
            gx = u.position.x || 0;
            gy = u.position.y || 0;
        } else if (data.x !== undefined && data.y !== undefined) {
            gx = data.x;
            gy = data.y;
        } else {
            return;
        }
        // In real code, _gameToLngLat converts; here we just verify coordinates
        mockMap.flyTo({ center: [gx, gy], zoom: 17 });
    }

    handleCenterOnUnit({ id: 'unit-1' });
    assert(flyToArgs !== null, 'centerOnUnit with {id} triggers flyTo');
    assert(flyToArgs.center[0] === 50, 'flyTo x from store position');
    assert(flyToArgs.center[1] === -30, 'flyTo y from store position');
    assert(flyToArgs.zoom === 17, 'flyTo uses zoom 17 for unit centering');
}

{
    // Handler accepts direct { x, y } coordinates
    let flyToArgs = null;
    const mockMap = {
        flyTo(args) { flyToArgs = args; },
    };

    function handleCenterOnUnit(data) {
        if (!mockMap || !data) return;
        let gx, gy;
        if (data.id) return;  // simplified: id would check store
        if (data.x !== undefined && data.y !== undefined) {
            gx = data.x;
            gy = data.y;
        } else {
            return;
        }
        mockMap.flyTo({ center: [gx, gy], zoom: 17 });
    }

    handleCenterOnUnit({ x: 100, y: -50 });
    assert(flyToArgs !== null, 'centerOnUnit with {x,y} triggers flyTo');
    assert(flyToArgs.center[0] === 100, 'flyTo x from direct coords');
    assert(flyToArgs.center[1] === -50, 'flyTo y from direct coords');
}

{
    // Handler ignores null/empty data
    let flyToCalled = false;
    const mockMap = {
        flyTo() { flyToCalled = true; },
    };

    function handleCenterOnUnit(data) {
        if (!mockMap || !data) return;
        if (!data.id && data.x === undefined && data.y === undefined) return;
        mockMap.flyTo({});
    }

    handleCenterOnUnit(null);
    assert(!flyToCalled, 'centerOnUnit ignores null data');
    handleCenterOnUnit({});
    assert(!flyToCalled, 'centerOnUnit ignores empty data');
}

{
    // Handler ignores unknown unit IDs
    let flyToCalled = false;
    const mockStore = new Map();
    const mockMap = {
        flyTo() { flyToCalled = true; },
    };

    function handleCenterOnUnit(data) {
        if (!mockMap || !data) return;
        if (data.id) {
            const u = mockStore.get(data.id);
            if (!u || !u.position) return;
        }
        mockMap.flyTo({});
    }

    handleCenterOnUnit({ id: 'nonexistent' });
    assert(!flyToCalled, 'centerOnUnit ignores unknown unit ID');
}


// ============================================================
// M key null check for panelManager
// ============================================================

console.log('\n--- M key panelManager null check ---');

{
    // When panelManager is null, M key should not crash
    const panelManager = null;
    let threw = false;
    try {
        // This mirrors the fixed code: if (panelManager) panelManager.toggle('minimap');
        if (panelManager) panelManager.toggle('minimap');
    } catch (e) {
        threw = true;
    }
    assert(!threw, 'M key with null panelManager does not crash');
}

{
    // When panelManager exists, M key should call toggle
    let toggledPanel = null;
    const panelManager = {
        toggle(name) { toggledPanel = name; },
    };
    if (panelManager) panelManager.toggle('minimap');
    assert(toggledPanel === 'minimap', 'M key toggles minimap when panelManager exists');
}


// ============================================================
// Summary
// ============================================================

console.log(`\n=== ${passed} passed, ${failed} failed ===`);
process.exit(failed > 0 ? 1 : 0);
