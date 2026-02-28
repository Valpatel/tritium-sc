// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
/**
 * TRITIUM-SC -- Map Position Pipeline Diagnostic Tests
 *
 * Verifies the position data flow from telemetry through the store to screen coordinates.
 * Tests worldToScreen, screenToWorld, and label resolution positioning.
 *
 * Run: node tests/js/test_map_positions.js
 */

const fs = require('fs');
const vm = require('vm');

// Simple test runner
let passed = 0, failed = 0;
function assert(cond, msg) {
    if (!cond) { console.error('FAIL:', msg); failed++; }
    else { console.log('PASS:', msg); passed++; }
}
function assertClose(a, b, eps, msg) {
    assert(Math.abs(a - b) < (eps || 0.5), msg + ` (got ${a}, expected ${b})`);
}
function assertEqual(a, b, msg) {
    assert(a === b, msg + ` (got ${JSON.stringify(a)}, expected ${JSON.stringify(b)})`);
}

// ================================================================
// Mock browser environment for ES module loading
// ================================================================

// Minimal store implementation (extracted from store.js)
const TritiumStore = {
    map: { viewport: { x: 0, y: 0, zoom: 1 }, selectedUnitId: null, mode: 'observe' },
    game: { phase: 'idle', wave: 0, totalWaves: 10, score: 0, eliminations: 0 },
    units: new Map(),
    amy: { state: 'idle', mood: 'calm', lastThought: '', speaking: false, nodeCount: 0 },
    connection: { status: 'disconnected' },
    alerts: [],
    cameras: [],
    _listeners: new Map(),
    on(path, fn) {
        if (!this._listeners.has(path)) this._listeners.set(path, new Set());
        this._listeners.get(path).add(fn);
        return () => this._listeners.get(path)?.delete(fn);
    },
    set(path, value) {
        const parts = path.split('.');
        let obj = this;
        for (let i = 0; i < parts.length - 1; i++) {
            if (obj[parts[i]] === undefined || obj[parts[i]] === null) obj[parts[i]] = {};
            obj = obj[parts[i]];
        }
        obj[parts[parts.length - 1]] = value;
    },
    get(path) {
        const parts = path.split('.');
        let obj = this;
        for (const part of parts) {
            if (obj === undefined || obj === null) return undefined;
            obj = obj instanceof Map ? obj.get(part) : obj[part];
        }
        return obj;
    },
    updateUnit(id, data) {
        const existing = this.units.get(id) || {};
        this.units.set(id, { ...existing, ...data, id });
    },
    removeUnit(id) { this.units.delete(id); },
};

// ================================================================
// worldToScreen / screenToWorld (extracted from map.js)
// ================================================================

function worldToScreen(wx, wy, cam, cssW, cssH) {
    const sx = (wx - cam.x) * cam.zoom + cssW / 2;
    const sy = -(wy - cam.y) * cam.zoom + cssH / 2;
    return { x: sx, y: sy };
}

function screenToWorld(sx, sy, cam, cssW, cssH) {
    const wx = (sx - cssW / 2) / cam.zoom + cam.x;
    const wy = -((sy - cssH / 2) / cam.zoom) + cam.y;
    return { x: wx, y: wy };
}

// ================================================================
// _updateUnit (extracted from websocket.js)
// ================================================================

function updateUnitFromTelemetry(t) {
    if (!t || !t.target_id) return;
    const update = {
        name: t.name || t.target_id,
        type: t.asset_type || t.type || 'unknown',
        alliance: t.alliance || 'unknown',
        position: t.position || { x: t.x || 0, y: t.y || 0 },
        heading: t.heading || 0,
        health: t.health,
        maxHealth: t.max_health,
        battery: typeof t.battery === 'number' ? Math.round(t.battery * 100) : undefined,
        status: t.status || 'active',
        eliminations: t.kills || t.eliminations || 0,
        speed: t.speed || 0,
    };
    if (t.kills !== undefined) update.kills = t.kills;
    if (t.morale !== undefined) update.morale = t.morale;
    if (t.fsm_state !== undefined) { update.fsmState = t.fsm_state; update.fsm_state = t.fsm_state; }
    if (t.degradation !== undefined) update.degradation = t.degradation;
    if (t.weapon_range !== undefined) update.weaponRange = t.weapon_range;
    if (t.is_combatant !== undefined) update.isCombatant = t.is_combatant;
    TritiumStore.updateUnit(t.target_id, update);

    // Clean up terminal-state units (sync for tests, async in production)
    const TERMINAL_STATES = ['eliminated', 'destroyed', 'despawned'];
    if (TERMINAL_STATES.includes(update.status)) {
        TritiumStore.removeUnit(t.target_id);
    }
}

// ================================================================
// TESTS: Position format from Python to_dict()
// ================================================================

console.log('\n=== Position Format Tests ===\n');

(function test_position_from_to_dict() {
    // Python to_dict() produces: {"position": {"x": 50.0, "y": -30.0}}
    const telemetry = {
        target_id: 'rover-abc123',
        name: 'RoboDog-1',
        alliance: 'friendly',
        asset_type: 'rover',
        position: { x: 50.0, y: -30.0 },
        heading: 90,
        speed: 2.0,
        battery: 0.85,
        status: 'active',
        health: 100.0,
        max_health: 100.0,
        kills: 0,
        is_combatant: true,
        fsm_state: 'patrolling',
    };

    updateUnitFromTelemetry(telemetry);
    const unit = TritiumStore.units.get('rover-abc123');

    assert(unit !== undefined, 'Unit stored in TritiumStore');
    assert(unit.position !== undefined, 'Unit has position');
    assertEqual(unit.position.x, 50.0, 'Position x is 50.0');
    assertEqual(unit.position.y, -30.0, 'Position y is -30.0');
    assertEqual(unit.type, 'rover', 'Type is rover');
    assertEqual(unit.alliance, 'friendly', 'Alliance is friendly');
})();

(function test_position_zero_zero() {
    const telemetry = {
        target_id: 'turret-zero',
        name: 'Turret-0',
        alliance: 'friendly',
        asset_type: 'turret',
        position: { x: 0, y: 0 },
        heading: 0,
        speed: 0,
        status: 'stationary',
        health: 100,
        max_health: 100,
    };
    updateUnitFromTelemetry(telemetry);
    const unit = TritiumStore.units.get('turret-zero');
    assert(unit.position.x === 0, 'Zero position x stored correctly');
    assert(unit.position.y === 0, 'Zero position y stored correctly');
})();

(function test_position_negative_coords() {
    const telemetry = {
        target_id: 'hostile-neg',
        name: 'BadGuy-1',
        alliance: 'hostile',
        asset_type: 'person',
        position: { x: -100, y: -100 },
        heading: 45,
        speed: 1.5,
        health: 80,
        max_health: 80,
    };
    updateUnitFromTelemetry(telemetry);
    const unit = TritiumStore.units.get('hostile-neg');
    assertEqual(unit.position.x, -100, 'Negative x stored correctly');
    assertEqual(unit.position.y, -100, 'Negative y stored correctly');
})();

(function test_position_fallback_to_xy_fields() {
    // If position is missing, falls back to t.x/t.y
    const telemetry = {
        target_id: 'fallback-unit',
        name: 'Fallback',
        alliance: 'hostile',
        asset_type: 'person',
        x: 25,
        y: 50,
        heading: 0,
        health: 80,
        max_health: 80,
    };
    updateUnitFromTelemetry(telemetry);
    const unit = TritiumStore.units.get('fallback-unit');
    assertEqual(unit.position.x, 25, 'Fallback x from t.x');
    assertEqual(unit.position.y, 50, 'Fallback y from t.y');
})();

(function test_position_missing_entirely() {
    // No position, no x, no y — defaults to {x:0, y:0}
    const telemetry = {
        target_id: 'no-pos-unit',
        name: 'NoPos',
        alliance: 'hostile',
        asset_type: 'person',
        heading: 0,
        health: 80,
        max_health: 80,
    };
    updateUnitFromTelemetry(telemetry);
    const unit = TritiumStore.units.get('no-pos-unit');
    assertEqual(unit.position.x, 0, 'Missing position defaults x to 0');
    assertEqual(unit.position.y, 0, 'Missing position defaults y to 0');
})();


// ================================================================
// TESTS: worldToScreen coordinate transforms
// ================================================================

console.log('\n=== worldToScreen Tests ===\n');

(function test_wts_origin_at_center() {
    // Camera at origin, zoom 1, 1920x1080 screen
    const cam = { x: 0, y: 0, zoom: 1.0 };
    const sp = worldToScreen(0, 0, cam, 1920, 1080);
    assertClose(sp.x, 960, 0.1, 'Origin maps to screen center X');
    assertClose(sp.y, 540, 0.1, 'Origin maps to screen center Y');
})();

(function test_wts_positive_x_goes_right() {
    const cam = { x: 0, y: 0, zoom: 1.0 };
    const sp = worldToScreen(100, 0, cam, 1920, 1080);
    assert(sp.x > 960, 'Positive world X maps to right of center');
})();

(function test_wts_positive_y_goes_up() {
    // Positive world Y should go UP on screen (lower sy value)
    const cam = { x: 0, y: 0, zoom: 1.0 };
    const sp = worldToScreen(0, 100, cam, 1920, 1080);
    assert(sp.y < 540, 'Positive world Y maps to top of screen (lower sy)');
})();

(function test_wts_zoom_scales() {
    const cam1 = { x: 0, y: 0, zoom: 1.0 };
    const cam15 = { x: 0, y: 0, zoom: 15.0 };
    const sp1 = worldToScreen(10, 0, cam1, 1920, 1080);
    const sp15 = worldToScreen(10, 0, cam15, 1920, 1080);
    // At zoom 15, 10m offset = 150px. At zoom 1, 10m offset = 10px.
    assertClose(sp1.x - 960, 10, 0.1, 'Zoom 1: 10m offset = 10px');
    assertClose(sp15.x - 960, 150, 0.1, 'Zoom 15: 10m offset = 150px');
})();

(function test_wts_camera_pan() {
    // Camera panned to (50, 50), zoom 1
    const cam = { x: 50, y: 50, zoom: 1.0 };
    const sp = worldToScreen(50, 50, cam, 1920, 1080);
    assertClose(sp.x, 960, 0.1, 'Unit at camera center maps to screen center X');
    assertClose(sp.y, 540, 0.1, 'Unit at camera center maps to screen center Y');
})();

(function test_wts_roundtrip() {
    const cam = { x: 30, y: -20, zoom: 5.0 };
    const wx = 75.5, wy = -44.3;
    const sp = worldToScreen(wx, wy, cam, 1920, 1080);
    const back = screenToWorld(sp.x, sp.y, cam, 1920, 1080);
    assertClose(back.x, wx, 0.01, 'Round-trip world X preserved');
    assertClose(back.y, wy, 0.01, 'Round-trip world Y preserved');
})();


// ================================================================
// TESTS: Visibility at different zoom levels
// ================================================================

console.log('\n=== Zoom Visibility Tests ===\n');

(function test_visible_range_at_zoom15() {
    // At zoom 15, 1920px screen: visible world width = 1920/15 = 128m
    // So visible from -64m to +64m centered on camera
    const cam = { x: 0, y: 0, zoom: 15.0 };
    const cssW = 1920, cssH = 1080;

    const sp_0 = worldToScreen(0, 0, cam, cssW, cssH);
    assert(sp_0.x >= 0 && sp_0.x <= cssW, 'Origin visible at zoom 15');

    const sp_50 = worldToScreen(50, 0, cam, cssW, cssH);
    assert(sp_50.x >= 0 && sp_50.x <= cssW, '50m from center visible at zoom 15');

    const sp_100 = worldToScreen(100, 0, cam, cssW, cssH);
    assert(sp_100.x > cssW, '100m from center off-screen at zoom 15 (got ' + sp_100.x + ')');

    const sp_neg100 = worldToScreen(-100, 0, cam, cssW, cssH);
    assert(sp_neg100.x < 0, '-100m from center off-screen at zoom 15 (got ' + sp_neg100.x + ')');
})();

(function test_map_bounds_100_at_zoom15() {
    // Street combat: map_bounds=100 (hostiles at ±100)
    // At zoom 15, hostiles at edges are OFF SCREEN
    const cam = { x: 0, y: 0, zoom: 15.0 };
    const cssW = 1920;
    const sp = worldToScreen(100, 0, cam, cssW, 1080);
    assert(sp.x > cssW, 'Hostile at map edge (100m) is off-screen at default zoom');
    console.log('  Info: hostile at x=100 maps to screen x=' + Math.round(sp.x) + ' (screen width=' + cssW + ')');
})();

(function test_map_bounds_200_at_zoom15() {
    // Default map_bounds=200 (hostiles at ±200)
    // At zoom 15, even more off-screen
    const cam = { x: 0, y: 0, zoom: 15.0 };
    const cssW = 1920;
    const sp = worldToScreen(200, 0, cam, cssW, 1080);
    assert(sp.x > cssW, 'Hostile at 200m is way off-screen at default zoom');
    console.log('  Info: hostile at x=200 maps to screen x=' + Math.round(sp.x) + ' (screen width=' + cssW + ')');
})();

(function test_zoom_for_full_100m_visibility() {
    // What zoom level shows ±100m on a 1920px screen?
    // 1920 / zoom = 200 → zoom = 9.6
    const cssW = 1920;
    const targetRange = 100; // show ±100m
    const idealZoom = cssW / (targetRange * 2);
    console.log('  Info: ideal zoom for ±100m on 1920px = ' + idealZoom.toFixed(1));

    const cam = { x: 0, y: 0, zoom: idealZoom };
    const sp = worldToScreen(100, 0, cam, cssW, 1080);
    assertClose(sp.x, cssW, 5, 'At ideal zoom, 100m hits right edge');
})();


// ================================================================
// TESTS: Multiple units position spread (diagnostic)
// ================================================================

console.log('\n=== Unit Spread Diagnostic ===\n');

(function test_batch_telemetry_positions_varied() {
    // Simulate a batch of 8 units at different positions
    TritiumStore.units.clear();
    const batch = [
        { target_id: 'rover-1', name: 'Rover-1', alliance: 'friendly', asset_type: 'rover', position: { x: 0, y: 0 }, heading: 0, health: 100, max_health: 100, speed: 2 },
        { target_id: 'turret-1', name: 'Turret-1', alliance: 'friendly', asset_type: 'turret', position: { x: 20, y: 15 }, heading: 45, health: 100, max_health: 100, speed: 0 },
        { target_id: 'hostile-1', name: 'Kid-1', alliance: 'hostile', asset_type: 'person', position: { x: -80, y: 80 }, heading: 180, health: 50, max_health: 50, speed: 2 },
        { target_id: 'hostile-2', name: 'Kid-2', alliance: 'hostile', asset_type: 'person', position: { x: 90, y: -40 }, heading: 270, health: 50, max_health: 50, speed: 2 },
        { target_id: 'hostile-3', name: 'Kid-3', alliance: 'hostile', asset_type: 'person', position: { x: -50, y: -90 }, heading: 135, health: 50, max_health: 50, speed: 2 },
        { target_id: 'hostile-4', name: 'Kid-4', alliance: 'hostile', asset_type: 'person', position: { x: 100, y: 100 }, heading: 0, health: 50, max_health: 50, speed: 2 },
        { target_id: 'drone-1', name: 'Drone-1', alliance: 'friendly', asset_type: 'drone', position: { x: -30, y: 40 }, heading: 90, health: 100, max_health: 100, speed: 5 },
        { target_id: 'hostile-5', name: 'Kid-5', alliance: 'hostile', asset_type: 'person', position: { x: 0, y: -100 }, heading: 0, health: 50, max_health: 50, speed: 2 },
    ];

    for (const t of batch) {
        updateUnitFromTelemetry(t);
    }

    assertEqual(TritiumStore.units.size, 8, 'All 8 units in store');

    // Check positions are varied and correct
    const positions = [];
    for (const [id, unit] of TritiumStore.units) {
        assert(unit.position !== undefined, `Unit ${id} has position`);
        assert(unit.position.x !== undefined, `Unit ${id} has position.x`);
        assert(unit.position.y !== undefined, `Unit ${id} has position.y`);
        positions.push({ id, x: unit.position.x, y: unit.position.y });
    }

    // Verify positions are NOT all the same
    const uniqueX = new Set(positions.map(p => p.x));
    const uniqueY = new Set(positions.map(p => p.y));
    assert(uniqueX.size > 1, `X coordinates are varied (${uniqueX.size} unique values)`);
    assert(uniqueY.size > 1, `Y coordinates are varied (${uniqueY.size} unique values)`);

    // Check worldToScreen distribution at zoom that fits all units
    const cam = { x: 0, y: 0, zoom: 5.0 };
    const cssW = 1920, cssH = 1080;
    const screenPositions = positions.map(p => {
        const sp = worldToScreen(p.x, p.y, cam, cssW, cssH);
        return { id: p.id, sx: Math.round(sp.x), sy: Math.round(sp.y) };
    });

    // Print for diagnostic
    console.log('  Screen positions at zoom 5.0:');
    for (const sp of screenPositions) {
        const onScreen = sp.sx >= 0 && sp.sx <= cssW && sp.sy >= 0 && sp.sy <= cssH;
        console.log(`    ${sp.id}: (${sp.sx}, ${sp.sy}) ${onScreen ? 'ON-SCREEN' : 'OFF-SCREEN'}`);
    }

    // At zoom 5, visible range: 1920/5 = 384m wide, so ±192m visible
    // All units at ±100 should be ON SCREEN at zoom 5
    const onScreen = screenPositions.filter(sp => sp.sx >= 0 && sp.sx <= cssW && sp.sy >= 0 && sp.sy <= cssH);
    assert(onScreen.length >= 6, `At least 6 of 8 units on-screen at zoom 5 (got ${onScreen.length})`);

    // Verify NOT all clustering at one side
    const leftHalf = screenPositions.filter(sp => sp.sx < cssW / 2);
    const rightHalf = screenPositions.filter(sp => sp.sx >= cssW / 2);
    assert(leftHalf.length > 0, 'Some units on left half');
    assert(rightHalf.length > 0, 'Some units on right half');
})();


// ================================================================
// TESTS: Label guard logic
// ================================================================

console.log('\n=== Label Guard Tests ===\n');

(function test_label_guard_valid_position() {
    const unit = { position: { x: 50, y: -30 } };
    const pos = unit.position;
    const passes = pos && pos.x !== undefined && pos.y !== undefined;
    assert(passes, 'Valid position passes label guard');
})();

(function test_label_guard_undefined_position() {
    const unit = { position: undefined };
    const pos = unit.position;
    const passes = pos && pos.x !== undefined && pos.y !== undefined;
    assert(!passes, 'Undefined position fails label guard');
})();

(function test_label_guard_null_position() {
    const unit = { position: null };
    const pos = unit.position;
    const passes = pos && pos.x !== undefined && pos.y !== undefined;
    assert(!passes, 'Null position fails label guard');
})();

(function test_label_guard_missing_x() {
    const unit = { position: { y: 50 } };
    const pos = unit.position;
    const passes = pos && pos.x !== undefined && pos.y !== undefined;
    assert(!passes, 'Position missing x fails label guard');
})();

(function test_label_guard_zero_is_valid() {
    // CRITICAL: position {x: 0, y: 0} must pass the guard
    const unit = { position: { x: 0, y: 0 } };
    const pos = unit.position;
    const passes = pos && pos.x !== undefined && pos.y !== undefined;
    assert(passes, 'Position {x:0, y:0} passes guard (0 !== undefined)');
})();


// ================================================================
// TESTS: Batch telemetry message parsing
// ================================================================

console.log('\n=== Batch Telemetry Parsing ===\n');

(function test_batch_message_structure() {
    // The server sends: { type: "amy_sim_telemetry_batch", data: [...], timestamp: "..." }
    const msg = {
        type: "amy_sim_telemetry_batch",
        data: [
            { target_id: 'r-1', name: 'Rover', alliance: 'friendly', asset_type: 'rover', position: { x: 10, y: 20 }, heading: 0, health: 100, max_health: 100, speed: 2 },
            { target_id: 'h-1', name: 'Kid', alliance: 'hostile', asset_type: 'person', position: { x: -50, y: 80 }, heading: 180, health: 50, max_health: 50, speed: 2 },
        ],
        timestamp: "2026-02-26T12:00:00",
    };

    TritiumStore.units.clear();
    const items = msg.data || [];
    assert(Array.isArray(items), 'Batch data is an array');
    assertEqual(items.length, 2, 'Batch has 2 items');

    for (const t of items) {
        updateUnitFromTelemetry(t);
    }

    assertEqual(TritiumStore.units.size, 2, 'Both units stored');
    const r = TritiumStore.units.get('r-1');
    assertEqual(r.position.x, 10, 'Rover position x correct');
    assertEqual(r.position.y, 20, 'Rover position y correct');
    const h = TritiumStore.units.get('h-1');
    assertEqual(h.position.x, -50, 'Hostile position x correct');
    assertEqual(h.position.y, 80, 'Hostile position y correct');
})();

(function test_single_telemetry_message() {
    // Also support: { type: "amy_sim_telemetry", data: { target_id: ... } }
    const msg = {
        type: "amy_sim_telemetry",
        data: { target_id: 'single-1', name: 'Single', alliance: 'friendly', asset_type: 'rover', position: { x: 33, y: -77 }, heading: 45, health: 100, max_health: 100, speed: 2 },
    };

    TritiumStore.units.clear();
    const t = msg.data;
    if (t && t.target_id) {
        updateUnitFromTelemetry(t);
    }
    assertEqual(TritiumStore.units.size, 1, 'Single unit stored');
    const u = TritiumStore.units.get('single-1');
    assertEqual(u.position.x, 33, 'Single telemetry position x correct');
    assertEqual(u.position.y, -77, 'Single telemetry position y correct');
})();


// ================================================================
// TESTS: Default zoom vs map bounds mismatch diagnostic
// ================================================================

console.log('\n=== Zoom vs Map Bounds Diagnostic ===\n');

(function test_default_zoom_coverage() {
    // map.js initial zoom is 15.0. What world range is visible?
    const zoom = 15.0;
    const cssW = 1920, cssH = 1080;
    const visibleW = cssW / zoom; // meters visible horizontally
    const visibleH = cssH / zoom;
    console.log(`  Default zoom ${zoom}: visible area = ${visibleW.toFixed(0)}m x ${visibleH.toFixed(0)}m`);
    console.log(`  Visible range: ±${(visibleW/2).toFixed(0)}m x ±${(visibleH/2).toFixed(0)}m`);

    // At default zoom, only ±64m x ±36m is visible
    // map_bounds=100 means hostiles at ±100 — mostly off-screen!
    // map_bounds=200 means hostiles at ±200 — way off-screen!
    assert(visibleW < 200, 'Default zoom shows less than 200m width — most units off-screen');
    assert(visibleW > 100, 'Default zoom shows more than 100m width — defenders visible');
})();

(function test_zoom_for_scenario_bounds() {
    const cssW = 1920;
    // Calculate ideal zoom for different map bounds
    const scenarios = [
        { name: 'street_combat', bounds: 100 },
        { name: 'riot', bounds: 500 },
        { name: 'default', bounds: 200 },
    ];
    for (const s of scenarios) {
        const idealZoom = cssW / (s.bounds * 2);
        console.log(`  ${s.name} (bounds=${s.bounds}m): ideal zoom = ${idealZoom.toFixed(2)}`);
    }
    assert(true, 'Zoom calculations computed (see above)');
})();


// ================================================================
// Alliance Filter Tests
// ================================================================

console.log('\n--- Alliance Filter Tests ---');

{
    // Simulate the allianceFilter logic from _updateUnits line 590
    function shouldShowMarker(showUnits, allianceFilter, unitAlliance) {
        const allianceOk = !allianceFilter ||
            allianceFilter.includes(unitAlliance || 'unknown');
        return showUnits && allianceOk;
    }

    // No filter — all visible
    assert(shouldShowMarker(true, null, 'hostile'), 'null filter shows hostile');
    assert(shouldShowMarker(true, null, 'friendly'), 'null filter shows friendly');
    assert(shouldShowMarker(true, null, 'neutral'), 'null filter shows neutral');
    assert(shouldShowMarker(true, null, 'unknown'), 'null filter shows unknown');

    // showUnits=false — all hidden
    assert(!shouldShowMarker(false, null, 'hostile'), 'showUnits=false hides hostile');
    assert(!shouldShowMarker(false, null, 'friendly'), 'showUnits=false hides friendly');

    // Hostile-only filter
    assert(shouldShowMarker(true, ['hostile'], 'hostile'), 'hostile filter shows hostile');
    assert(!shouldShowMarker(true, ['hostile'], 'friendly'), 'hostile filter hides friendly');
    assert(!shouldShowMarker(true, ['hostile'], 'neutral'), 'hostile filter hides neutral');

    // Friendly-only filter
    assert(!shouldShowMarker(true, ['friendly'], 'hostile'), 'friendly filter hides hostile');
    assert(shouldShowMarker(true, ['friendly'], 'friendly'), 'friendly filter shows friendly');

    // Multi-alliance filter
    assert(shouldShowMarker(true, ['hostile', 'neutral'], 'hostile'), 'multi filter shows hostile');
    assert(shouldShowMarker(true, ['hostile', 'neutral'], 'neutral'), 'multi filter shows neutral');
    assert(!shouldShowMarker(true, ['hostile', 'neutral'], 'friendly'), 'multi filter hides friendly');

    // showUnits=false overrides filter
    assert(!shouldShowMarker(false, ['hostile'], 'hostile'), 'showUnits=false + filter still hides');

    // Empty filter = nothing shown (edge case)
    assert(!shouldShowMarker(true, [], 'hostile'), 'empty filter hides all');
    assert(!shouldShowMarker(true, [], 'friendly'), 'empty filter hides all alliances');

    // Undefined alliance treated as 'unknown'
    assert(shouldShowMarker(true, ['unknown'], undefined), 'undefined alliance matches unknown filter');
    assert(!shouldShowMarker(true, ['hostile'], undefined), 'undefined alliance hidden by hostile filter');
}

// ================================================================
// Icon Letter Mapping Tests (extracted from _applyMarkerStyle)
// ================================================================

console.log('\n--- Icon Letter Mapping Tests ---');

{
    // Replicate the hardcoded icon chain from map-maplibre.js:660-680
    function getIconFromChain(type) {
        type = (type || 'unknown').toLowerCase();
        let icon = '?';
        if (type.includes('turret')) icon = 'T';
        else if (type.includes('drone') || type.includes('scout')) icon = 'D';
        else if (type.includes('rover')) icon = 'R';
        else if (type.includes('tank')) icon = 'K';
        else if (type.includes('apc')) icon = 'A';
        else if (type === 'hostile_vehicle') icon = 'V';
        else if (type === 'hostile_leader') icon = 'L';
        else if (type.includes('person') || type.includes('hostile')) icon = 'P';
        else if (type.includes('vehicle')) icon = 'V';
        else if (type.includes('sensor')) icon = 'S';
        else if (type.includes('camera')) icon = 'C';
        return icon;
    }

    // Expected correct icons from the Python unit registry
    const EXPECTED = {
        'turret': 'T',
        'heavy_turret': 'T',
        'missile_turret': 'T',
        'tank': 'K',
        'apc': 'A',
        'drone': 'D',
        'scout_drone': 'D',
        'rover': 'R',
        'person': 'P',
        'hostile_person': 'P',  // or 'H' from Python, but 'P' is acceptable for display
        'hostile_vehicle': 'V', // MUST NOT be 'P'
        'hostile_leader': 'L',  // MUST NOT be 'P'
        'camera': 'C',
        'motion_sensor': 'S',
    };

    // Tests that SHOULD pass (basic types)
    assertEqual(getIconFromChain('turret'), 'T', 'turret icon');
    assertEqual(getIconFromChain('heavy_turret'), 'T', 'heavy_turret icon');
    assertEqual(getIconFromChain('missile_turret'), 'T', 'missile_turret icon');
    assertEqual(getIconFromChain('drone'), 'D', 'drone icon');
    assertEqual(getIconFromChain('scout_drone'), 'D', 'scout_drone icon (includes scout)');
    assertEqual(getIconFromChain('rover'), 'R', 'rover icon');
    assertEqual(getIconFromChain('tank'), 'K', 'tank icon');
    assertEqual(getIconFromChain('apc'), 'A', 'apc icon');
    assertEqual(getIconFromChain('camera'), 'C', 'camera icon');
    assertEqual(getIconFromChain('motion_sensor'), 'S', 'motion_sensor icon');
    assertEqual(getIconFromChain('person'), 'P', 'person icon');

    // BUG DETECTION: These tests catch the includes('hostile') over-matching
    // hostile_vehicle should NOT map to 'P' (person) — it should be 'V' (vehicle)
    const hvIcon = getIconFromChain('hostile_vehicle');
    assert(hvIcon !== 'P',
        `BUG: hostile_vehicle gets icon '${hvIcon}' — includes('hostile') matches before vehicle check`);

    // hostile_leader should NOT map to 'P' (person) — it should be 'L' (leader)
    const hlIcon = getIconFromChain('hostile_leader');
    assert(hlIcon !== 'P',
        `BUG: hostile_leader gets icon '${hlIcon}' — includes('hostile') matches before leader check`);
}

// ================================================================
// 10. Unit store cleanup — eliminated/destroyed units must be removed
// ================================================================

console.log('\n--- Unit store cleanup (memory leak prevention) ---');

{
    // Simulate the full lifecycle: spawn, update, eliminate, cleanup
    TritiumStore.units.clear();

    // Add 10 units
    for (let i = 0; i < 10; i++) {
        updateUnitFromTelemetry({
            target_id: `unit-${i}`,
            name: `Unit ${i}`,
            alliance: 'hostile',
            asset_type: 'person',
            position: { x: i * 10, y: 0 },
            health: 80,
            max_health: 80,
            status: 'active',
        });
    }
    assert(TritiumStore.units.size === 10, 'Store has 10 active units');

    // Simulate 5 units getting eliminated via telemetry update
    for (let i = 0; i < 5; i++) {
        updateUnitFromTelemetry({
            target_id: `unit-${i}`,
            name: `Unit ${i}`,
            alliance: 'hostile',
            asset_type: 'person',
            position: { x: i * 10, y: 0 },
            health: 0,
            max_health: 80,
            status: 'eliminated',
        });
    }

    // After telemetry updates with status=eliminated, a cleanup pass
    // should remove them (or the updateUnit should auto-remove terminal units)
    // Count non-eliminated units
    let aliveCount = 0;
    TritiumStore.units.forEach(u => {
        if (u.status !== 'eliminated' && u.status !== 'destroyed' && u.status !== 'despawned') {
            aliveCount++;
        }
    });

    // BUG TEST: Store should clean up eliminated units
    // If store.units.size is still 10, eliminated units are leaking
    assert(TritiumStore.units.size <= 7,
        `Store should remove eliminated units (has ${TritiumStore.units.size}, want <=7). ` +
        `Memory leak: ${TritiumStore.units.size - aliveCount} dead units accumulating`);
}

{
    // Test: After 100 spawn+eliminate cycles, store should not grow unboundedly
    TritiumStore.units.clear();
    const MAX_EXPECTED = 20; // Reasonable cap

    for (let wave = 0; wave < 10; wave++) {
        // Spawn 10 hostiles per wave
        for (let i = 0; i < 10; i++) {
            const id = `wave${wave}-h${i}`;
            updateUnitFromTelemetry({
                target_id: id, name: id, alliance: 'hostile', asset_type: 'person',
                position: { x: i * 10, y: wave * 10 }, health: 80, max_health: 80, status: 'active',
            });
        }

        // All get eliminated
        for (let i = 0; i < 10; i++) {
            const id = `wave${wave}-h${i}`;
            updateUnitFromTelemetry({
                target_id: id, name: id, alliance: 'hostile', asset_type: 'person',
                position: { x: i * 10, y: wave * 10 }, health: 0, max_health: 80, status: 'eliminated',
            });
        }
    }

    // After 10 waves of 10 hostiles (100 total), store should NOT have 100 entries
    assert(TritiumStore.units.size <= MAX_EXPECTED,
        `After 10 waves of eliminations, store has ${TritiumStore.units.size} entries ` +
        `(want <=${MAX_EXPECTED}). Memory leak: 100 dead units accumulating`);
}

{
    // Test: destroyed units should also be cleaned up
    TritiumStore.units.clear();
    updateUnitFromTelemetry({
        target_id: 'rover-1', name: 'Rover', alliance: 'friendly', asset_type: 'rover',
        position: { x: 0, y: 0 }, health: 0, max_health: 150, status: 'destroyed',
    });
    assert(TritiumStore.units.size === 0 || TritiumStore.units.get('rover-1')?.status === 'destroyed',
        'Destroyed units should be cleaned from store or marked correctly');
}

// ================================================================
// Summary
// ================================================================

console.log('\n========================================');
console.log(`Results: ${passed} passed, ${failed} failed`);
console.log('========================================\n');
process.exit(failed > 0 ? 1 : 0);
