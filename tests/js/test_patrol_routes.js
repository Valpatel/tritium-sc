// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
/**
 * TRITIUM-SC Patrol Route Overlay tests
 *
 * Validates that:
 * 1. Patrol route rendering code exists in map-maplibre.js
 * 2. WebSocket forwards waypoints and loop_waypoints to store
 * 3. GeoJSON source/layer IDs are defined
 * 4. Route filtering logic (only friendly patrol units)
 * 5. Toggle function and state integration
 * 6. Backend to_dict() includes loop_waypoints
 *
 * Run: node tests/js/test_patrol_routes.js
 */

const fs = require('fs');

// Simple test runner
let passed = 0, failed = 0;
function assert(cond, msg) {
    if (!cond) { console.error('FAIL:', msg); failed++; }
    else { console.log('PASS:', msg); passed++; }
}

// Read source files
const mapSrc = fs.readFileSync(__dirname + '/../../src/frontend/js/command/map-maplibre.js', 'utf8');
const wsSrc = fs.readFileSync(__dirname + '/../../src/frontend/js/command/websocket.js', 'utf8');
const targetPy = fs.readFileSync(__dirname + '/../../src/engine/simulation/target.py', 'utf8');

// ============================================================
// 1. GeoJSON source and layer constants
// ============================================================

console.log('\n--- Patrol route GeoJSON constants ---');

assert(mapSrc.includes("PATROL_ROUTES_SOURCE"), 'PATROL_ROUTES_SOURCE constant defined');
assert(mapSrc.includes("PATROL_ROUTES_LINE"), 'PATROL_ROUTES_LINE layer constant defined');
assert(mapSrc.includes("PATROL_ROUTES_DOTS"), 'PATROL_ROUTES_DOTS layer constant defined');

// Verify the source ID string value
assert(mapSrc.includes("'patrol-routes-source'"), "Source ID is 'patrol-routes-source'");
assert(mapSrc.includes("'patrol-routes-line'"), "Line layer ID is 'patrol-routes-line'");
assert(mapSrc.includes("'patrol-routes-dots'"), "Dots layer ID is 'patrol-routes-dots'");

// ============================================================
// 2. State flag for patrol routes
// ============================================================

console.log('\n--- Patrol routes state flag ---');

const statePattern = /showPatrolRoutes\s*:\s*true/;
assert(statePattern.test(mapSrc), '_state.showPatrolRoutes defaults to true');

// ============================================================
// 3. _isPatrolling helper function
// ============================================================

console.log('\n--- _isPatrolling filter function ---');

assert(mapSrc.includes('function _isPatrolling'), '_isPatrolling function defined');

// Verify it checks alliance
assert(mapSrc.includes("alliance !== 'friendly'"), '_isPatrolling checks for friendly alliance');

// Verify it checks waypoints length
assert(mapSrc.includes('wps.length < 2'), '_isPatrolling requires 2+ waypoints');

// Verify it checks loopWaypoints
assert(mapSrc.includes('loopWaypoints'), '_isPatrolling checks loopWaypoints flag');

// Verify it checks FSM state
assert(mapSrc.includes("'patrolling'"), '_isPatrolling recognizes patrolling FSM state');

// ============================================================
// 4. GeoJSON builder function
// ============================================================

console.log('\n--- GeoJSON builder ---');

assert(mapSrc.includes('function _buildPatrolRoutesGeoJSON'), '_buildPatrolRoutesGeoJSON function defined');
assert(mapSrc.includes("type: 'FeatureCollection'"), 'Returns FeatureCollection');
assert(mapSrc.includes("type: 'LineString'"), 'Creates LineString features for routes');
assert(mapSrc.includes("type: 'Point'"), 'Creates Point features for waypoint dots');

// Verify loop closing: if loopWaypoints, push first coord again
assert(mapSrc.includes('coords.push(coords[0])'), 'Closes loop for looping patrol routes');

// ============================================================
// 5. MapLibre layer creation
// ============================================================

console.log('\n--- MapLibre layer setup ---');

// Verify addSource call for patrol routes
assert(mapSrc.includes("addSource(PATROL_ROUTES_SOURCE"), 'addSource called for patrol routes');

// Verify line layer paint properties
assert(mapSrc.includes("'line-color': '#05ffa1'"), 'Line color is green (#05ffa1)');
assert(mapSrc.includes("'line-dasharray'"), 'Line uses dash pattern');
assert(mapSrc.includes("'line-opacity': 0.5"), 'Line opacity is 0.5');

// Verify circle layer for waypoint dots
assert(mapSrc.includes("'circle-color': '#05ffa1'"), 'Waypoint dots are green');
assert(mapSrc.includes("'circle-radius': 4"), 'Waypoint dot radius is 4');

// ============================================================
// 6. Update integration in _updateUnits
// ============================================================

console.log('\n--- Integration in update loop ---');

// Extract _updateUnits function body
const updateUnitsMatch = mapSrc.match(/function _updateUnits\(\)\s*\{[\s\S]*?\n\}/);
assert(updateUnitsMatch !== null, '_updateUnits function found');
if (updateUnitsMatch) {
    assert(updateUnitsMatch[0].includes('_updatePatrolRoutes'),
        '_updateUnits calls _updatePatrolRoutes()');
}

// ============================================================
// 7. Toggle function
// ============================================================

console.log('\n--- Toggle function ---');

const toggleExport = /export\s+function\s+togglePatrolRoutes\b/;
assert(toggleExport.test(mapSrc), 'togglePatrolRoutes is exported');

// Verify it flips the state
const toggleFlip = /_state\.showPatrolRoutes\s*=\s*!_state\.showPatrolRoutes/;
assert(toggleFlip.test(mapSrc), 'togglePatrolRoutes flips _state.showPatrolRoutes');

// Verify it sets layer visibility
assert(mapSrc.includes("setLayoutProperty(PATROL_ROUTES_LINE, 'visibility'"),
    'togglePatrolRoutes sets line layer visibility');
assert(mapSrc.includes("setLayoutProperty(PATROL_ROUTES_DOTS, 'visibility'"),
    'togglePatrolRoutes sets dots layer visibility');

// ============================================================
// 8. getMapState includes showPatrolRoutes
// ============================================================

console.log('\n--- getMapState integration ---');

const mapStateMatch = mapSrc.match(/export function getMapState\(\)\s*\{[^}]+\}/s);
assert(mapStateMatch !== null, 'getMapState found');
if (mapStateMatch) {
    assert(mapStateMatch[0].includes('showPatrolRoutes'),
        'getMapState returns showPatrolRoutes');
}

// ============================================================
// 9. setLayers supports patrolRoutes
// ============================================================

console.log('\n--- setLayers integration ---');

assert(mapSrc.includes('layers.patrolRoutes'), 'setLayers handles patrolRoutes key');

// ============================================================
// 10. Layer HUD shows PATROL
// ============================================================

console.log('\n--- Layer HUD ---');

assert(mapSrc.includes("'PATROL'"), 'Layer HUD shows PATROL indicator');
assert(mapSrc.includes('showPatrolRoutes'), '_updateLayerHud checks showPatrolRoutes');

// ============================================================
// 11. toggleAllLayers includes patrol routes
// ============================================================

console.log('\n--- toggleAllLayers integration ---');

const allLayersMatch = mapSrc.match(/export function toggleAllLayers\(\)\s*\{[\s\S]*?(?=export\s+function)/);
assert(allLayersMatch !== null, 'toggleAllLayers found');
if (allLayersMatch) {
    assert(allLayersMatch[0].includes('showPatrolRoutes'),
        'toggleAllLayers includes showPatrolRoutes in managed keys');
    assert(allLayersMatch[0].includes('PATROL_ROUTES_LINE'),
        'toggleAllLayers sets patrol line layer visibility');
    assert(allLayersMatch[0].includes('PATROL_ROUTES_DOTS'),
        'toggleAllLayers sets patrol dots layer visibility');
}

// ============================================================
// 12. WebSocket forwards waypoints to store
// ============================================================

console.log('\n--- WebSocket patrol data forwarding ---');

assert(wsSrc.includes('t.waypoints'), 'WebSocket _updateUnit checks t.waypoints');
assert(wsSrc.includes('update.waypoints = t.waypoints'),
    'WebSocket forwards waypoints to store update');
assert(wsSrc.includes('t.loop_waypoints'),
    'WebSocket _updateUnit checks t.loop_waypoints');
assert(wsSrc.includes('update.loopWaypoints = t.loop_waypoints'),
    'WebSocket forwards loop_waypoints as loopWaypoints');

// ============================================================
// 13. Backend to_dict includes loop_waypoints
// ============================================================

console.log('\n--- Backend target.py serialization ---');

assert(targetPy.includes('"loop_waypoints": self.loop_waypoints'),
    'to_dict() includes loop_waypoints field');

// ============================================================
// 14. Cleanup function exists
// ============================================================

console.log('\n--- Cleanup ---');

assert(mapSrc.includes('function _clearPatrolRoutes'), '_clearPatrolRoutes function defined');
assert(mapSrc.includes('removeLayer(PATROL_ROUTES_DOTS)'), '_clearPatrolRoutes removes dots layer');
assert(mapSrc.includes('removeLayer(PATROL_ROUTES_LINE)'), '_clearPatrolRoutes removes line layer');
assert(mapSrc.includes('removeSource(PATROL_ROUTES_SOURCE)'), '_clearPatrolRoutes removes source');

// ============================================================
// Summary
// ============================================================

console.log(`\n${'='.repeat(60)}`);
console.log(`Patrol Routes: ${passed} passed, ${failed} failed`);
console.log(`${'='.repeat(60)}`);
process.exit(failed > 0 ? 1 : 0);
