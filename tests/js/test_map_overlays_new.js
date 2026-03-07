// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 -- see LICENSE for details.
/**
 * TRITIUM-SC Map Overlay tests -- New Overlays
 *
 * Validates 6 new map overlay features ported from map.js to map-maplibre.js:
 * 1. Hazard Zones -- environmental hazards (fire/flood/roadblock)
 * 2. Hostile Objectives -- dashed lines from hostiles to targets
 * 3. Crowd Density -- heatmap grid (civil_unrest mode)
 * 4. Cover Points -- tactical cover positions
 * 5. Unit Signals -- distress/contact/regroup/retreat rings
 * 6. Hostile Intel -- HUD overlay with enemy assessment
 *
 * Tests verify:
 * - Source/layer constants exist with correct IDs
 * - State variables declared with correct defaults
 * - Toggle functions exported and flip state
 * - getMapState() returns new keys
 * - Implementation functions exist and follow patterns
 * - Update loop integration (_updateUnits calls new overlays)
 * - Clear functions exist for cleanup
 * - Game state change handler wires overlays
 * - WebSocket routes overlay data to store
 * - Layer HUD includes new overlay indicators
 *
 * Run: node tests/js/test_map_overlays_new.js
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

// ============================================================
// 1. Hazard Zones -- Source/Layer Constants
// ============================================================

console.log('\n--- Hazard Zones: source/layer constants ---');

assert(mapSrc.includes("HAZARD_ZONES_SOURCE"), 'HAZARD_ZONES_SOURCE constant defined');
assert(mapSrc.includes("HAZARD_ZONES_FILL"), 'HAZARD_ZONES_FILL layer constant defined');
assert(mapSrc.includes("HAZARD_ZONES_STROKE"), 'HAZARD_ZONES_STROKE layer constant defined');
assert(mapSrc.includes("'hazard-zones-source'"), "Source ID is 'hazard-zones-source'");
assert(mapSrc.includes("'hazard-zones-fill'"), "Fill layer ID is 'hazard-zones-fill'");
assert(mapSrc.includes("'hazard-zones-stroke'"), "Stroke layer ID is 'hazard-zones-stroke'");

// ============================================================
// 2. Hazard Zones -- State Variable
// ============================================================

console.log('\n--- Hazard Zones: state variable ---');

assert(/showHazardZones\s*:\s*true/.test(mapSrc), '_state.showHazardZones defaults to true');

// ============================================================
// 3. Hazard Zones -- Toggle Function
// ============================================================

console.log('\n--- Hazard Zones: toggle function ---');

assert(/export\s+function\s+toggleHazardZones\b/.test(mapSrc),
    'toggleHazardZones() is exported');
assert(/_state\.showHazardZones\s*=\s*!_state\.showHazardZones/.test(mapSrc),
    'toggleHazardZones() flips _state.showHazardZones');

// ============================================================
// 4. Hazard Zones -- Implementation
// ============================================================

console.log('\n--- Hazard Zones: implementation ---');

assert(mapSrc.includes('function _updateHazardZones'), '_updateHazardZones function exists');
assert(mapSrc.includes('function _clearHazardZones'), '_clearHazardZones function exists');

(function testHazardZonesImpl() {
    const fnIdx = mapSrc.indexOf('function _updateHazardZones');
    assert(fnIdx !== -1, '_updateHazardZones found in source');
    if (fnIdx === -1) return;
    const snippet = mapSrc.substring(fnIdx, fnIdx + 1500);
    assert(snippet.includes('showHazardZones'), '_updateHazardZones checks showHazardZones flag');
    assert(snippet.includes("TritiumStore.get('hazards')"), '_updateHazardZones reads hazards from store');
    assert(snippet.includes('hazard_type'), '_updateHazardZones uses hazard_type');
    assert(snippet.includes('HAZARD_COLORS'), '_updateHazardZones uses HAZARD_COLORS');
    assert(snippet.includes('_makeCircleGeoJSON'), '_updateHazardZones creates circle polygons');
    assert(snippet.includes('remaining'), '_updateHazardZones calculates remaining time');
})();

// ============================================================
// 5. Hazard Zones -- Color Map
// ============================================================

console.log('\n--- Hazard Zones: color map ---');

assert(mapSrc.includes('HAZARD_COLORS'), 'HAZARD_COLORS constant defined');
assert(mapSrc.includes("fire:"), 'HAZARD_COLORS has fire entry');
assert(mapSrc.includes("flood:"), 'HAZARD_COLORS has flood entry');
assert(mapSrc.includes("roadblock:"), 'HAZARD_COLORS has roadblock entry');
assert(mapSrc.includes('#ff4400'), 'Fire color is #ff4400');
assert(mapSrc.includes('#0088ff'), 'Flood color is #0088ff');
assert(mapSrc.includes('#ffcc00'), 'Roadblock color is #ffcc00');

// ============================================================
// 6. Hostile Objectives -- Source/Layer Constants
// ============================================================

console.log('\n--- Hostile Objectives: source/layer constants ---');

assert(mapSrc.includes("HOSTILE_OBJ_SOURCE"), 'HOSTILE_OBJ_SOURCE constant defined');
assert(mapSrc.includes("HOSTILE_OBJ_LINE"), 'HOSTILE_OBJ_LINE layer constant defined');
assert(mapSrc.includes("'hostile-obj-source'"), "Source ID is 'hostile-obj-source'");
assert(mapSrc.includes("'hostile-obj-line'"), "Line layer ID is 'hostile-obj-line'");

// ============================================================
// 7. Hostile Objectives -- State Variable
// ============================================================

console.log('\n--- Hostile Objectives: state variable ---');

assert(/showHostileObjectives\s*:\s*true/.test(mapSrc), '_state.showHostileObjectives defaults to true');

// ============================================================
// 8. Hostile Objectives -- Toggle Function
// ============================================================

console.log('\n--- Hostile Objectives: toggle function ---');

assert(/export\s+function\s+toggleHostileObjectives\b/.test(mapSrc),
    'toggleHostileObjectives() is exported');
assert(/_state\.showHostileObjectives\s*=\s*!_state\.showHostileObjectives/.test(mapSrc),
    'toggleHostileObjectives() flips _state.showHostileObjectives');

// ============================================================
// 9. Hostile Objectives -- Implementation
// ============================================================

console.log('\n--- Hostile Objectives: implementation ---');

assert(mapSrc.includes('function _updateHostileObjectives'), '_updateHostileObjectives function exists');
assert(mapSrc.includes('function _clearHostileObjectives'), '_clearHostileObjectives function exists');

(function testHostileObjectivesImpl() {
    const fnIdx = mapSrc.indexOf('function _updateHostileObjectives');
    assert(fnIdx !== -1, '_updateHostileObjectives found in source');
    if (fnIdx === -1) return;
    const snippet = mapSrc.substring(fnIdx, fnIdx + 2500);
    assert(snippet.includes('showHostileObjectives'), '_updateHostileObjectives checks flag');
    assert(snippet.includes("game.phase"), '_updateHostileObjectives checks game phase');
    assert(snippet.includes("game.hostileObjectives"), '_updateHostileObjectives reads objectives from store');
    assert(snippet.includes('target_position'), '_updateHostileObjectives uses target_position');
    assert(snippet.includes('line-dasharray'), '_updateHostileObjectives uses dashed lines');
})();

// ============================================================
// 10. Hostile Objectives -- Polling
// ============================================================

console.log('\n--- Hostile Objectives: polling ---');

assert(mapSrc.includes('function _startHostileObjectivePoll'), '_startHostileObjectivePoll exists');
assert(mapSrc.includes('function _stopHostileObjectivePoll'), '_stopHostileObjectivePoll exists');
assert(mapSrc.includes('/api/game/hostile-intel'), 'Polls /api/game/hostile-intel endpoint');

// ============================================================
// 11. Hostile Objectives -- Objective Colors
// ============================================================

console.log('\n--- Hostile Objectives: objective type colors ---');

(function testObjectiveColors() {
    const fnIdx = mapSrc.indexOf('function _updateHostileObjectives');
    if (fnIdx === -1) return;
    const snippet = mapSrc.substring(fnIdx, fnIdx + 1500);
    assert(snippet.includes("assault"), 'Has assault objective type');
    assert(snippet.includes("flank"), 'Has flank objective type');
    assert(snippet.includes("advance"), 'Has advance objective type');
    assert(snippet.includes("retreat"), 'Has retreat objective type');
    assert(snippet.includes('#ff2a6d'), 'Assault color is magenta');
    assert(snippet.includes('#ff8800'), 'Flank color is orange');
    assert(snippet.includes('#fcee0a'), 'Advance color is yellow');
    assert(snippet.includes('#888888'), 'Retreat color is grey');
})();

// ============================================================
// 12. Crowd Density -- Source/Layer Constants
// ============================================================

console.log('\n--- Crowd Density: source/layer constants ---');

assert(mapSrc.includes("CROWD_DENSITY_SOURCE"), 'CROWD_DENSITY_SOURCE constant defined');
assert(mapSrc.includes("CROWD_DENSITY_FILL"), 'CROWD_DENSITY_FILL layer constant defined');
assert(mapSrc.includes("'crowd-density-source'"), "Source ID is 'crowd-density-source'");
assert(mapSrc.includes("'crowd-density-fill'"), "Fill layer ID is 'crowd-density-fill'");

// ============================================================
// 13. Crowd Density -- State Variable
// ============================================================

console.log('\n--- Crowd Density: state variable ---');

assert(/showCrowdDensity\s*:\s*true/.test(mapSrc), '_state.showCrowdDensity defaults to true');

// ============================================================
// 14. Crowd Density -- Toggle Function
// ============================================================

console.log('\n--- Crowd Density: toggle function ---');

assert(/export\s+function\s+toggleCrowdDensity\b/.test(mapSrc),
    'toggleCrowdDensity() is exported');
assert(/_state\.showCrowdDensity\s*=\s*!_state\.showCrowdDensity/.test(mapSrc),
    'toggleCrowdDensity() flips _state.showCrowdDensity');

// ============================================================
// 15. Crowd Density -- Implementation
// ============================================================

console.log('\n--- Crowd Density: implementation ---');

assert(mapSrc.includes('function _updateCrowdDensity'), '_updateCrowdDensity function exists');
assert(mapSrc.includes('function _clearCrowdDensity'), '_clearCrowdDensity function exists');

(function testCrowdDensityImpl() {
    const fnIdx = mapSrc.indexOf('function _updateCrowdDensity');
    assert(fnIdx !== -1, '_updateCrowdDensity found in source');
    if (fnIdx === -1) return;
    const snippet = mapSrc.substring(fnIdx, fnIdx + 1500);
    assert(snippet.includes('showCrowdDensity'), '_updateCrowdDensity checks flag');
    assert(snippet.includes("civil_unrest"), '_updateCrowdDensity gates on civil_unrest mode');
    assert(snippet.includes("game.crowdDensity"), '_updateCrowdDensity reads grid data from store');
    assert(snippet.includes("moderate"), '_updateCrowdDensity handles moderate level');
    assert(snippet.includes("dense"), '_updateCrowdDensity handles dense level');
    assert(snippet.includes("critical"), '_updateCrowdDensity handles critical level');
    assert(snippet.includes('cell_size'), '_updateCrowdDensity uses cell_size');
    assert(snippet.includes('_gameToLngLat'), '_updateCrowdDensity converts to lng/lat');
})();

// ============================================================
// 16. Cover Points -- Source/Layer Constants
// ============================================================

console.log('\n--- Cover Points: source/layer constants ---');

assert(mapSrc.includes("COVER_POINTS_SOURCE"), 'COVER_POINTS_SOURCE constant defined');
assert(mapSrc.includes("COVER_POINTS_CIRCLE"), 'COVER_POINTS_CIRCLE layer constant defined');
assert(mapSrc.includes("'cover-points-source'"), "Source ID is 'cover-points-source'");
assert(mapSrc.includes("'cover-points-circle'"), "Circle layer ID is 'cover-points-circle'");

// ============================================================
// 17. Cover Points -- State Variable
// ============================================================

console.log('\n--- Cover Points: state variable ---');

assert(/showCoverPoints\s*:\s*true/.test(mapSrc), '_state.showCoverPoints defaults to true');

// ============================================================
// 18. Cover Points -- Toggle Function
// ============================================================

console.log('\n--- Cover Points: toggle function ---');

assert(/export\s+function\s+toggleCoverPoints\b/.test(mapSrc),
    'toggleCoverPoints() is exported');
assert(/_state\.showCoverPoints\s*=\s*!_state\.showCoverPoints/.test(mapSrc),
    'toggleCoverPoints() flips _state.showCoverPoints');

// ============================================================
// 19. Cover Points -- Implementation
// ============================================================

console.log('\n--- Cover Points: implementation ---');

assert(mapSrc.includes('function _updateCoverPoints'), '_updateCoverPoints function exists');
assert(mapSrc.includes('function _clearCoverPoints'), '_clearCoverPoints function exists');

(function testCoverPointsImpl() {
    const fnIdx = mapSrc.indexOf('function _updateCoverPoints');
    assert(fnIdx !== -1, '_updateCoverPoints found in source');
    if (fnIdx === -1) return;
    const snippet = mapSrc.substring(fnIdx, fnIdx + 2500);
    assert(snippet.includes('showCoverPoints'), '_updateCoverPoints checks flag');
    assert(snippet.includes("game.coverPoints"), '_updateCoverPoints reads from store');
    assert(snippet.includes("circle-color"), '_updateCoverPoints uses circle layer type');
    assert(snippet.includes('#00f0ff'), '_updateCoverPoints uses cyan color');
})();

// ============================================================
// 20. Unit Signals -- Source/Layer Constants
// ============================================================

console.log('\n--- Unit Signals: source/layer constants ---');

assert(mapSrc.includes("UNIT_SIGNALS_SOURCE"), 'UNIT_SIGNALS_SOURCE constant defined');
assert(mapSrc.includes("UNIT_SIGNALS_CIRCLE"), 'UNIT_SIGNALS_CIRCLE layer constant defined');
assert(mapSrc.includes("'unit-signals-source'"), "Source ID is 'unit-signals-source'");
assert(mapSrc.includes("'unit-signals-circle'"), "Circle layer ID is 'unit-signals-circle'");

// ============================================================
// 21. Unit Signals -- State Variable
// ============================================================

console.log('\n--- Unit Signals: state variable ---');

assert(/showUnitSignals\s*:\s*true/.test(mapSrc), '_state.showUnitSignals defaults to true');

// ============================================================
// 22. Unit Signals -- Toggle Function
// ============================================================

console.log('\n--- Unit Signals: toggle function ---');

assert(/export\s+function\s+toggleUnitSignals\b/.test(mapSrc),
    'toggleUnitSignals() is exported');
assert(/_state\.showUnitSignals\s*=\s*!_state\.showUnitSignals/.test(mapSrc),
    'toggleUnitSignals() flips _state.showUnitSignals');

// ============================================================
// 23. Unit Signals -- Implementation
// ============================================================

console.log('\n--- Unit Signals: implementation ---');

assert(mapSrc.includes('function _updateUnitSignals'), '_updateUnitSignals function exists');
assert(mapSrc.includes('function _clearUnitSignals'), '_clearUnitSignals function exists');

(function testUnitSignalsImpl() {
    const fnIdx = mapSrc.indexOf('function _updateUnitSignals');
    assert(fnIdx !== -1, '_updateUnitSignals found in source');
    if (fnIdx === -1) return;
    const snippet = mapSrc.substring(fnIdx, fnIdx + 4000);
    assert(snippet.includes('showUnitSignals'), '_updateUnitSignals checks flag');
    assert(snippet.includes("game.signals"), '_updateUnitSignals reads signals from store');
    assert(snippet.includes('signal_type'), '_updateUnitSignals uses signal_type');
    assert(snippet.includes('ttl'), '_updateUnitSignals checks TTL for expiry');
    assert(snippet.includes('_makeCircleGeoJSON'), '_updateUnitSignals creates expanding circles');
    assert(snippet.includes('line-dasharray'), '_updateUnitSignals uses dashed lines');
})();

// ============================================================
// 24. Unit Signals -- Color Map
// ============================================================

console.log('\n--- Unit Signals: color map ---');

assert(mapSrc.includes('SIGNAL_COLORS'), 'SIGNAL_COLORS constant defined');
assert(mapSrc.includes("distress:"), 'SIGNAL_COLORS has distress entry');
assert(mapSrc.includes("contact:"), 'SIGNAL_COLORS has contact entry');
assert(mapSrc.includes("regroup:"), 'SIGNAL_COLORS has regroup entry');
assert(mapSrc.includes("retreat:"), 'SIGNAL_COLORS has retreat entry');

// ============================================================
// 25. Hostile Intel -- State Variable & Toggle
// ============================================================

console.log('\n--- Hostile Intel: state/toggle ---');

assert(/showHostileIntel\s*:\s*true/.test(mapSrc), '_state.showHostileIntel defaults to true');
assert(/export\s+function\s+toggleHostileIntel\b/.test(mapSrc),
    'toggleHostileIntel() is exported');
assert(/_state\.showHostileIntel\s*=\s*!_state\.showHostileIntel/.test(mapSrc),
    'toggleHostileIntel() flips _state.showHostileIntel');

// ============================================================
// 26. Hostile Intel -- Implementation
// ============================================================

console.log('\n--- Hostile Intel: implementation ---');

assert(mapSrc.includes('function _updateHostileIntel'), '_updateHostileIntel function exists');

(function testHostileIntelImpl() {
    const fnIdx = mapSrc.indexOf('function _updateHostileIntel');
    assert(fnIdx !== -1, '_updateHostileIntel found in source');
    if (fnIdx === -1) return;
    const snippet = mapSrc.substring(fnIdx, fnIdx + 2500);
    assert(snippet.includes('showHostileIntel'), '_updateHostileIntel checks flag');
    assert(snippet.includes("game.hostileIntel"), '_updateHostileIntel reads intel from store');
    assert(snippet.includes('threat_level'), '_updateHostileIntel shows threat level');
    assert(snippet.includes('force_ratio'), '_updateHostileIntel shows force ratio');
    assert(snippet.includes('recommended_action'), '_updateHostileIntel shows recommended action');
    assert(snippet.includes('hostile-intel-hud'), '_updateHostileIntel creates DOM element');
})();

// ============================================================
// 27. Update Loop Integration
// ============================================================

console.log('\n--- Update loop integration ---');

(function testUpdateLoopIntegration() {
    const fnMatch = mapSrc.match(/function _updateUnits\b[\s\S]*?(?=\nfunction\s)/);
    assert(fnMatch !== null, '_updateUnits function found');
    if (!fnMatch) return;
    const body = fnMatch[0];
    assert(body.includes('_updateHazardZones'), '_updateUnits calls _updateHazardZones');
    assert(body.includes('_updateUnitSignals'), '_updateUnits calls _updateUnitSignals');
    assert(body.includes('_updateHostileObjectives'), '_updateUnits calls _updateHostileObjectives');
    assert(body.includes('_updateCrowdDensity'), '_updateUnits calls _updateCrowdDensity');
    assert(body.includes('_updateCoverPoints'), '_updateUnits calls _updateCoverPoints');
    assert(body.includes('_updateHostileIntel'), '_updateUnits calls _updateHostileIntel');
})();

// ============================================================
// 28. Layer HUD Integration
// ============================================================

console.log('\n--- Layer HUD integration ---');

(function testLayerHudIntegration() {
    const fnMatch = mapSrc.match(/function _updateLayerHud\b[\s\S]*?(?=\n\/\/ ===)/);
    assert(fnMatch !== null, '_updateLayerHud function found');
    if (!fnMatch) return;
    const body = fnMatch[0];
    assert(body.includes("'HAZARD'"), 'Layer HUD shows HAZARD indicator');
    assert(body.includes("'HOBJ'"), 'Layer HUD shows HOBJ indicator');
    assert(body.includes("'CROWD'"), 'Layer HUD shows CROWD indicator');
    assert(body.includes("'COVER'"), 'Layer HUD shows COVER indicator');
    assert(body.includes("'SIG'"), 'Layer HUD shows SIG indicator');
    assert(body.includes("'INTEL'"), 'Layer HUD shows INTEL indicator');
})();

// ============================================================
// 29. getMapState() Integration
// ============================================================

console.log('\n--- getMapState() integration ---');

(function testGetMapState() {
    const fnMatch = mapSrc.match(/export function getMapState\b[\s\S]*?(?=\nexport\s)/);
    assert(fnMatch !== null, 'getMapState function found');
    if (!fnMatch) return;
    const body = fnMatch[0];
    assert(body.includes('showHazardZones'), 'getMapState returns showHazardZones');
    assert(body.includes('showHostileObjectives'), 'getMapState returns showHostileObjectives');
    assert(body.includes('showCrowdDensity'), 'getMapState returns showCrowdDensity');
    assert(body.includes('showCoverPoints'), 'getMapState returns showCoverPoints');
    assert(body.includes('showUnitSignals'), 'getMapState returns showUnitSignals');
    assert(body.includes('showHostileIntel'), 'getMapState returns showHostileIntel');
})();

// ============================================================
// 30. Game State Change Handler Integration
// ============================================================

console.log('\n--- Game state change handler ---');

(function testGameStateHandler() {
    const fnMatch = mapSrc.match(/function _onGameStateChange\b[\s\S]*?(?=\n\/\*\*|\nfunction\s)/);
    assert(fnMatch !== null, '_onGameStateChange function found');
    if (!fnMatch) return;
    const body = fnMatch[0];
    assert(body.includes('_startHostileObjectivePoll'), 'Starts hostile objective poll on active');
    assert(body.includes('_stopHostileObjectivePoll'), 'Stops hostile objective poll on end');
    assert(body.includes('_clearHazardZones'), 'Clears hazard zones on idle');
    assert(body.includes('_clearHostileObjectives'), 'Clears hostile objectives on idle');
    assert(body.includes('_clearCrowdDensity'), 'Clears crowd density on idle');
    assert(body.includes('_clearCoverPoints'), 'Clears cover points on idle');
    assert(body.includes('_clearUnitSignals'), 'Clears unit signals on idle');
})();

// ============================================================
// 31. destroyMap cleanup
// ============================================================

console.log('\n--- destroyMap cleanup ---');

(function testDestroyCleanup() {
    const fnMatch = mapSrc.match(/export function destroyMap\b[\s\S]*?(?=\nexport\s)/);
    assert(fnMatch !== null, 'destroyMap function found');
    if (!fnMatch) return;
    const body = fnMatch[0];
    assert(body.includes('_stopHostileObjectivePoll'), 'destroyMap stops objective polling');
    assert(body.includes('_hostileIntelEl'), 'destroyMap cleans up hostile intel DOM');
})();

// ============================================================
// 32. WebSocket -- hazard store keys
// ============================================================

console.log('\n--- WebSocket: store keys ---');

assert(wsSrc.includes("TritiumStore.set('hazards'"), 'WebSocket stores hazards');
assert(wsSrc.includes("TritiumStore.set('game.hostileIntel'"), 'WebSocket stores hostile intel');
assert(wsSrc.includes("TritiumStore.set('game.crowdDensity'"), 'WebSocket stores crowd density');
assert(wsSrc.includes("TritiumStore.set('game.coverPoints'"), 'WebSocket stores cover points');
assert(wsSrc.includes("TritiumStore.set('game.signals'"), 'WebSocket stores signals');
assert(wsSrc.includes("TritiumStore.set('game.hostileObjectives'"), 'WebSocket stores hostile objectives');

// ============================================================
// 33. WebSocket -- event types for all overlays
// ============================================================

console.log('\n--- WebSocket: event types ---');

assert(wsSrc.includes("case 'hazard_spawned'"), 'WebSocket handles hazard_spawned');
assert(wsSrc.includes("case 'hazard_expired'"), 'WebSocket handles hazard_expired');
assert(wsSrc.includes("case 'hostile_intel'"), 'WebSocket handles hostile_intel');
assert(wsSrc.includes("case 'crowd_density'"), 'WebSocket handles crowd_density');
assert(wsSrc.includes("case 'cover_points'"), 'WebSocket handles cover_points');
assert(wsSrc.includes("case 'unit_signal'"), 'WebSocket handles unit_signal');

// ============================================================
// 34. Hash caching for change detection
// ============================================================

console.log('\n--- Hash caching ---');

assert(mapSrc.includes('_lastHazardHash'), 'Hazard zone hash cache exists');
assert(mapSrc.includes('_lastHostileObjHash'), 'Hostile objective hash cache exists');
assert(mapSrc.includes('_lastCrowdDensityHash'), 'Crowd density hash cache exists');
assert(mapSrc.includes('_lastCoverPointsHash'), 'Cover points hash cache exists');
assert(mapSrc.includes('_lastSignalsHash'), 'Unit signals hash cache exists');

// ============================================================
// Summary
// ============================================================

console.log(`\n=== RESULTS: ${passed} passed, ${failed} failed ===`);
if (failed > 0) process.exit(1);
