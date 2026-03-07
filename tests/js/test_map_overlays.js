// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
/**
 * TRITIUM-SC Map Overlay tests
 *
 * Validates three new map overlay features:
 * 1. Weapon Range Circle -- circle overlay on selected unit
 * 2. Combat Zone Heatmap -- heatmap layer from replay data
 * 3. Drone Swarm Convex Hull -- pulsing polygon around hostile units
 *
 * Tests verify:
 * - Source/layer constants exist with correct IDs
 * - State variables declared with correct defaults
 * - Toggle functions exported and flip state
 * - getMapState() returns new keys
 * - Implementation functions exist and follow patterns
 * - Convex hull algorithm correctness
 * - Event handler integration (wave complete, game state, selection)
 * - WebSocket parses weapon_range field
 *
 * Run: node tests/js/test_map_overlays.js
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
// 1. Weapon Range -- Source/Layer Constants
// ============================================================

console.log('\n--- Weapon Range: source/layer constants ---');

assert(mapSrc.includes("WEAPON_RANGE_SOURCE"), 'WEAPON_RANGE_SOURCE constant defined');
assert(mapSrc.includes("WEAPON_RANGE_FILL"), 'WEAPON_RANGE_FILL layer constant defined');
assert(mapSrc.includes("WEAPON_RANGE_STROKE"), 'WEAPON_RANGE_STROKE layer constant defined');
assert(mapSrc.includes("'weapon-range-source'"), "Source ID is 'weapon-range-source'");
assert(mapSrc.includes("'weapon-range-fill'"), "Fill layer ID is 'weapon-range-fill'");
assert(mapSrc.includes("'weapon-range-stroke'"), "Stroke layer ID is 'weapon-range-stroke'");

// ============================================================
// 2. Weapon Range -- State Variable
// ============================================================

console.log('\n--- Weapon Range: state variable ---');

assert(/showWeaponRange\s*:\s*true/.test(mapSrc), '_state.showWeaponRange defaults to true');

// ============================================================
// 3. Weapon Range -- Toggle Function
// ============================================================

console.log('\n--- Weapon Range: toggle function ---');

assert(/export\s+function\s+toggleWeaponRange\b/.test(mapSrc),
    'toggleWeaponRange() is exported');
assert(/_state\.showWeaponRange\s*=\s*!_state\.showWeaponRange/.test(mapSrc),
    'toggleWeaponRange() flips _state.showWeaponRange');

// ============================================================
// 4. Weapon Range -- Implementation Functions
// ============================================================

console.log('\n--- Weapon Range: implementation ---');

assert(mapSrc.includes('function _updateWeaponRange'), '_updateWeaponRange function exists');
assert(mapSrc.includes('function _clearWeaponRange'), '_clearWeaponRange function exists');

// Verify _updateWeaponRange checks mode and showWeaponRange
(function testWeaponRangeGuards() {
    const fnIdx = mapSrc.indexOf('function _updateWeaponRange');
    assert(fnIdx !== -1, '_updateWeaponRange found in source');
    if (fnIdx === -1) return;
    const snippet = mapSrc.substring(fnIdx, fnIdx + 800);
    assert(snippet.includes('showWeaponRange'), '_updateWeaponRange checks showWeaponRange flag');
    // Weapon range now shows in all modes (including observe); mode-specific
    // clearing is handled in setMapMode instead.
    assert(snippet.includes('weaponRange'), '_updateWeaponRange reads unit.weaponRange');
    assert(snippet.includes('_makeCircleGeoJSON'), '_updateWeaponRange uses _makeCircleGeoJSON');
})();

// Verify alliance-based color logic
(function testWeaponRangeColors() {
    const fnIdx = mapSrc.indexOf('function _updateWeaponRange');
    if (fnIdx === -1) return;
    const snippet = mapSrc.substring(fnIdx, fnIdx + 1200);
    assert(snippet.includes('#00f0ff'), 'Weapon range uses cyan for friendly');
    assert(snippet.includes('#ff2a6d'), 'Weapon range uses magenta for hostile');
    assert(snippet.includes('0.08'), 'Weapon range fill opacity is 0.08');
    assert(snippet.includes('0.3'), 'Weapon range stroke opacity is 0.3');
})();

// ============================================================
// 5. Weapon Range -- Selection Integration
// ============================================================

console.log('\n--- Weapon Range: selection integration ---');

(function testSelectionIntegration() {
    const fnMatch = mapSrc.match(/function _onSelectionChanged\b[\s\S]*?(?=\nfunction\s)/);
    assert(fnMatch !== null, '_onSelectionChanged function found');
    if (fnMatch) {
        assert(fnMatch[0].includes('_updateWeaponRange'),
            '_onSelectionChanged calls _updateWeaponRange');
    }
})();

// ============================================================
// 6. Weapon Range -- Mode Clear Integration
// ============================================================

console.log('\n--- Weapon Range: mode switching ---');

(function testModeClearing() {
    const fnMatch = mapSrc.match(/function setMapMode\b[\s\S]*?(?=\n\/\/ ===)/);
    assert(fnMatch !== null, 'setMapMode function found');
    if (fnMatch) {
        assert(fnMatch[0].includes('_clearWeaponRange'),
            'setMapMode clears weapon range in observe mode');
    }
})();

// ============================================================
// 7. Weapon Range -- Update Loop Integration
// ============================================================

console.log('\n--- Weapon Range: update loop ---');

(function testUpdateLoopIntegration() {
    const fnMatch = mapSrc.match(/function _updateUnits\b[\s\S]*?(?=\nfunction\s)/);
    assert(fnMatch !== null, '_updateUnits function found');
    if (fnMatch) {
        assert(fnMatch[0].includes('_updateWeaponRange'),
            '_updateUnits calls _updateWeaponRange');
    }
})();

// ============================================================
// 8. Combat Zone Heatmap -- Source/Layer Constants
// ============================================================

console.log('\n--- Heatmap: source/layer constants ---');

assert(mapSrc.includes("COMBAT_HEATMAP_SOURCE"), 'COMBAT_HEATMAP_SOURCE constant defined');
assert(mapSrc.includes("COMBAT_HEATMAP_LAYER"), 'COMBAT_HEATMAP_LAYER layer constant defined');
assert(mapSrc.includes("'combat-heatmap-source'"), "Source ID is 'combat-heatmap-source'");
assert(mapSrc.includes("'combat-heatmap'"), "Layer ID is 'combat-heatmap'");

// ============================================================
// 9. Heatmap -- State Variable
// ============================================================

console.log('\n--- Heatmap: state variable ---');

assert(/showHeatmap\s*:\s*false/.test(mapSrc), '_state.showHeatmap defaults to false');

// ============================================================
// 10. Heatmap -- Toggle Function
// ============================================================

console.log('\n--- Heatmap: toggle function ---');

assert(/export\s+function\s+toggleHeatmap\b/.test(mapSrc),
    'toggleHeatmap() is exported');
assert(/_state\.showHeatmap\s*=\s*!_state\.showHeatmap/.test(mapSrc),
    'toggleHeatmap() flips _state.showHeatmap');

// ============================================================
// 11. Heatmap -- Implementation Functions
// ============================================================

console.log('\n--- Heatmap: implementation ---');

assert(mapSrc.includes('function _fetchAndRenderHeatmap'), '_fetchAndRenderHeatmap function exists');
assert(mapSrc.includes('function _renderHeatmap'), '_renderHeatmap function exists');
assert(mapSrc.includes('function _clearHeatmap'), '_clearHeatmap function exists');

// Verify heatmap layer type
(function testHeatmapLayerType() {
    const fnIdx = mapSrc.indexOf('function _renderHeatmap');
    assert(fnIdx !== -1, '_renderHeatmap found in source');
    if (fnIdx === -1) return;
    const snippet = mapSrc.substring(fnIdx, fnIdx + 2500);
    assert(snippet.includes("type: 'heatmap'"), 'Heatmap uses MapLibre heatmap layer type');
    assert(snippet.includes('heatmap-weight'), 'Heatmap configures heatmap-weight');
    assert(snippet.includes('heatmap-color'), 'Heatmap configures heatmap-color');
    assert(snippet.includes('heatmap-radius'), 'Heatmap configures heatmap-radius');
    assert(snippet.includes('heatmap-opacity'), 'Heatmap configures heatmap-opacity');
})();

// Verify fetch path
(function testHeatmapFetch() {
    const fnIdx = mapSrc.indexOf('function _fetchAndRenderHeatmap');
    assert(fnIdx !== -1, '_fetchAndRenderHeatmap found in source');
    if (fnIdx === -1) return;
    const snippet = mapSrc.substring(fnIdx, fnIdx + 800);
    assert(snippet.includes('/api/game/replay/heatmap'),
        'Heatmap fetches from /api/game/replay/heatmap');
    assert(snippet.includes('_gameToLngLat'),
        'Heatmap converts positions via _gameToLngLat');
})();

// Verify cyberpunk color gradient
(function testHeatmapColors() {
    const fnIdx = mapSrc.indexOf('function _renderHeatmap');
    if (fnIdx === -1) return;
    const snippet = mapSrc.substring(fnIdx, fnIdx + 2500);
    // Should have cyan, magenta, yellow in the gradient
    assert(snippet.includes('0,240,255') || snippet.includes('0, 240, 255'),
        'Heatmap gradient includes cyan');
    assert(snippet.includes('255,42,109') || snippet.includes('255, 42, 109'),
        'Heatmap gradient includes magenta');
    assert(snippet.includes('252,238,10') || snippet.includes('252, 238, 10'),
        'Heatmap gradient includes yellow');
})();

// ============================================================
// 12. Heatmap -- Wave Complete Integration
// ============================================================

console.log('\n--- Heatmap: wave complete integration ---');

(function testWaveCompleteIntegration() {
    const fnMatch = mapSrc.match(/function _onWaveComplete\b[\s\S]*?(?=\nfunction\s)/);
    assert(fnMatch !== null, '_onWaveComplete function found');
    if (fnMatch) {
        assert(fnMatch[0].includes('_fetchAndRenderHeatmap'),
            '_onWaveComplete calls _fetchAndRenderHeatmap');
    }
})();

// ============================================================
// 13. Heatmap -- Game State Clear Integration
// ============================================================

console.log('\n--- Heatmap: game state clear ---');

(function testGameStateClear() {
    const fnMatch = mapSrc.match(/function _onGameStateChange\b[\s\S]*?(?=\n\/?\*?\*?\/?\n?function\s)/);
    assert(fnMatch !== null, '_onGameStateChange function found');
    if (fnMatch) {
        assert(fnMatch[0].includes('_clearHeatmap'),
            '_onGameStateChange clears heatmap on new game');
    }
})();

// ============================================================
// 14. Heatmap -- HUD Indicator
// ============================================================

console.log('\n--- Heatmap: HUD indicator ---');

(function testHeatmapHud() {
    const fnMatch = mapSrc.match(/function _updateLayerHud\b[\s\S]*?(?=\n\/\/ ===)/);
    assert(fnMatch !== null, '_updateLayerHud function found');
    if (fnMatch) {
        assert(fnMatch[0].includes("'HEAT'"),
            '_updateLayerHud shows HEAT indicator when heatmap active');
    }
})();

// ============================================================
// 15. Drone Swarm Convex Hull -- Source/Layer Constants
// ============================================================

console.log('\n--- Swarm Hull: source/layer constants ---');

assert(mapSrc.includes("SWARM_HULL_SOURCE"), 'SWARM_HULL_SOURCE constant defined');
assert(mapSrc.includes("SWARM_HULL_FILL"), 'SWARM_HULL_FILL layer constant defined');
assert(mapSrc.includes("SWARM_HULL_STROKE"), 'SWARM_HULL_STROKE layer constant defined');
assert(mapSrc.includes("'swarm-hull-source'"), "Source ID is 'swarm-hull-source'");
assert(mapSrc.includes("'swarm-hull-fill'"), "Fill layer ID is 'swarm-hull-fill'");
assert(mapSrc.includes("'swarm-hull-stroke'"), "Stroke layer ID is 'swarm-hull-stroke'");

// ============================================================
// 16. Swarm Hull -- State Variable
// ============================================================

console.log('\n--- Swarm Hull: state variable ---');

assert(/showSwarmHull\s*:\s*true/.test(mapSrc), '_state.showSwarmHull defaults to true');

// ============================================================
// 17. Swarm Hull -- Toggle Function
// ============================================================

console.log('\n--- Swarm Hull: toggle function ---');

assert(/export\s+function\s+toggleSwarmHull\b/.test(mapSrc),
    'toggleSwarmHull() is exported');
assert(/_state\.showSwarmHull\s*=\s*!_state\.showSwarmHull/.test(mapSrc),
    'toggleSwarmHull() flips _state.showSwarmHull');

// ============================================================
// 18. Swarm Hull -- Implementation Functions
// ============================================================

console.log('\n--- Swarm Hull: implementation ---');

assert(mapSrc.includes('function _convexHull'), '_convexHull function exists');
assert(mapSrc.includes('function _updateSwarmHull'), '_updateSwarmHull function exists');
assert(mapSrc.includes('function _clearSwarmHull'), '_clearSwarmHull function exists');

// Verify convex hull checks game mode
(function testSwarmHullGuards() {
    const fnIdx = mapSrc.indexOf('function _updateSwarmHull');
    assert(fnIdx !== -1, '_updateSwarmHull found in source');
    if (fnIdx === -1) return;
    const snippet = mapSrc.substring(fnIdx, fnIdx + 1000);
    assert(snippet.includes('showSwarmHull'), '_updateSwarmHull checks showSwarmHull flag');
    assert(snippet.includes('drone_swarm'), '_updateSwarmHull checks for drone_swarm mode');
    assert(snippet.includes("'active'"), '_updateSwarmHull checks for active game phase');
    assert(snippet.includes('hostile'), '_updateSwarmHull filters hostile units');
    assert(snippet.includes('_convexHull'), '_updateSwarmHull calls _convexHull');
})();

// Verify hull styling
(function testSwarmHullStyling() {
    const fnIdx = mapSrc.indexOf('function _updateSwarmHull');
    if (fnIdx === -1) return;
    const snippet = mapSrc.substring(fnIdx, fnIdx + 3000);
    assert(snippet.includes('#ff2a6d'), 'Swarm hull uses magenta color');
    assert(snippet.includes("'fill'"), 'Swarm hull has fill layer');
    assert(snippet.includes("'line'"), 'Swarm hull has stroke layer');
    assert(snippet.includes('0.4'), 'Swarm hull stroke opacity is 0.4');
})();

// ============================================================
// 19. Swarm Hull -- Update Loop Integration
// ============================================================

console.log('\n--- Swarm Hull: update loop ---');

(function testSwarmHullLoop() {
    const fnMatch = mapSrc.match(/function _updateUnits\b[\s\S]*?(?=\nfunction\s)/);
    assert(fnMatch !== null, '_updateUnits function found');
    if (fnMatch) {
        assert(fnMatch[0].includes('_updateSwarmHull'),
            '_updateUnits calls _updateSwarmHull');
    }
})();

// ============================================================
// 20. Swarm Hull -- Pulsing Animation
// ============================================================

console.log('\n--- Swarm Hull: pulsing animation ---');

(function testPulseAnimation() {
    const fnIdx = mapSrc.indexOf('function _updateSwarmHull');
    if (fnIdx === -1) return;
    const snippet = mapSrc.substring(fnIdx, fnIdx + 2000);
    assert(snippet.includes('Math.sin'), 'Swarm hull uses Math.sin for pulsing opacity');
    assert(snippet.includes('fill-opacity'), 'Swarm hull updates fill-opacity for pulse');
})();

// ============================================================
// 21. Convex Hull Algorithm Correctness
// ============================================================

console.log('\n--- Convex Hull: algorithm correctness ---');

// Extract and test the convex hull function directly
(function testConvexHullAlgorithm() {
    // Extract the function body
    const fnStart = mapSrc.indexOf('function _convexHull(points)');
    assert(fnStart !== -1, '_convexHull function found');
    if (fnStart === -1) return;

    // Find matching closing brace
    let depth = 0;
    let fnEnd = fnStart;
    let foundStart = false;
    for (let i = fnStart; i < mapSrc.length; i++) {
        if (mapSrc[i] === '{') { depth++; foundStart = true; }
        if (mapSrc[i] === '}') { depth--; }
        if (foundStart && depth === 0) { fnEnd = i + 1; break; }
    }
    const fnBody = mapSrc.substring(fnStart, fnEnd);

    // Create the function in a sandbox
    const fn = new Function('points', fnBody.replace('function _convexHull(points)', '').replace(/^\s*\{/, '').replace(/\}\s*$/, ''));

    // Test: triangle (already convex)
    const triangle = [[0,0], [1,0], [0,1]];
    const result1 = fn(triangle);
    assert(result1.length === 3, 'Triangle hull has 3 vertices');

    // Test: square with interior point
    const squareWithCenter = [[0,0], [1,0], [1,1], [0,1], [0.5,0.5]];
    const result2 = fn(squareWithCenter);
    assert(result2.length === 4, 'Square+center hull has 4 vertices (interior point excluded)');

    // Test: collinear points
    const collinear = [[0,0], [1,1], [2,2]];
    const result3 = fn(collinear);
    assert(result3.length <= 3, 'Collinear points hull has <= 3 vertices');

    // Test: fewer than 3 points returns input
    const twoPoints = [[0,0], [1,1]];
    const result4 = fn(twoPoints);
    assert(result4.length === 2, 'Two points returns 2 vertices');

    // Test: pentagon
    const pentagon = [[0,0], [2,0], [3,1], [1.5,3], [-0.5,1.5]];
    const result5 = fn(pentagon);
    assert(result5.length === 5, 'Pentagon hull has 5 vertices');

    // Test: L-shape with interior points excluded
    const lShape = [[0,0], [4,0], [4,2], [2,2], [2,4], [0,4], [1,1], [3,1]];
    const result6 = fn(lShape);
    // Convex hull of L should be 5 vertices (the outer corners)
    assert(result6.length >= 4 && result6.length <= 6,
        'L-shape hull has 4-6 vertices (interior excluded), got ' + result6.length);
})();

// ============================================================
// 22. getMapState() returns new keys
// ============================================================

console.log('\n--- getMapState() return keys ---');

const getMapStateMatch = mapSrc.match(/export function getMapState\(\)\s*\{[^}]+\}/s);
assert(getMapStateMatch !== null, 'getMapState() function found');

const getMapStateBody = getMapStateMatch ? getMapStateMatch[0] : '';

assert(getMapStateBody.includes('showWeaponRange:'), 'getMapState() returns showWeaponRange');
assert(getMapStateBody.includes('showHeatmap:'), 'getMapState() returns showHeatmap');
assert(getMapStateBody.includes('showSwarmHull:'), 'getMapState() returns showSwarmHull');

// ============================================================
// 23. setLayers() supports new layer keys
// ============================================================

console.log('\n--- setLayers() integration ---');

(function testSetLayersIntegration() {
    const fnIdx = mapSrc.indexOf('export function setLayers(');
    assert(fnIdx !== -1, 'setLayers function found');
    if (fnIdx === -1) return;
    // Extract roughly until end of function (setLayers is large: ~150 lines)
    const snippet = mapSrc.substring(fnIdx, fnIdx + 8000);
    assert(snippet.includes('layers.weaponRange'), 'setLayers handles weaponRange');
    assert(snippet.includes('layers.heatmap'), 'setLayers handles heatmap');
    assert(snippet.includes('layers.swarmHull'), 'setLayers handles swarmHull');
    assert(snippet.includes('toggleWeaponRange'), 'setLayers calls toggleWeaponRange');
    assert(snippet.includes('toggleHeatmap'), 'setLayers calls toggleHeatmap');
    assert(snippet.includes('toggleSwarmHull'), 'setLayers calls toggleSwarmHull');
})();

// ============================================================
// 24. _updateLayerHud() shows indicators
// ============================================================

console.log('\n--- Layer HUD indicators ---');

(function testLayerHudIndicators() {
    const fnMatch = mapSrc.match(/function _updateLayerHud\b[\s\S]*?(?=\n\/\/ ===)/);
    assert(fnMatch !== null, '_updateLayerHud function found');
    if (fnMatch) {
        assert(fnMatch[0].includes("'HEAT'"), 'HUD shows HEAT when heatmap active');
        assert(fnMatch[0].includes("'WPNRNG'"), 'HUD shows WPNRNG when weapon range active');
        assert(fnMatch[0].includes("'SWARM'"), 'HUD shows SWARM when swarm hull active');
    }
})();

// ============================================================
// 25. WebSocket parses weapon_range
// ============================================================

console.log('\n--- WebSocket weapon_range parsing ---');

assert(wsSrc.includes('weapon_range'), 'websocket.js parses weapon_range field');
assert(wsSrc.includes('weaponRange'), 'websocket.js maps to weaponRange in store');

// ============================================================
// 26. Clear functions follow cleanup pattern
// ============================================================

console.log('\n--- Clear functions follow pattern ---');

(function testClearPatterns() {
    // Each clear function should remove layers before source
    const clearFns = [
        { name: '_clearWeaponRange', layers: ['WEAPON_RANGE_FILL', 'WEAPON_RANGE_STROKE'], source: 'WEAPON_RANGE_SOURCE' },
        { name: '_clearHeatmap', layers: ['COMBAT_HEATMAP_LAYER'], source: 'COMBAT_HEATMAP_SOURCE' },
        { name: '_clearSwarmHull', layers: ['SWARM_HULL_FILL', 'SWARM_HULL_STROKE'], source: 'SWARM_HULL_SOURCE' },
    ];

    for (const { name, layers, source } of clearFns) {
        const fnIdx = mapSrc.indexOf('function ' + name);
        assert(fnIdx !== -1, name + ' function found');
        if (fnIdx === -1) continue;
        const snippet = mapSrc.substring(fnIdx, fnIdx + 500);

        for (const layer of layers) {
            assert(snippet.includes(layer), name + ' removes ' + layer);
        }
        assert(snippet.includes(source), name + ' removes ' + source);

        // Verify layers are removed before source
        const lastLayerIdx = Math.max(...layers.map(l => snippet.indexOf(l)));
        const sourceIdx = snippet.lastIndexOf(source);
        assert(sourceIdx > lastLayerIdx,
            name + ' removes source after layers (correct order)');
    }
})();

// ============================================================
// 27. _makeCircleGeoJSON reuse (not duplicated)
// ============================================================

console.log('\n--- GeoJSON helper reuse ---');

(function testMakeCircleGeoJSONReuse() {
    // Count occurrences of _makeCircleGeoJSON definition (should be exactly 1)
    const defs = mapSrc.match(/function _makeCircleGeoJSON\b/g);
    assert(defs !== null && defs.length === 1,
        '_makeCircleGeoJSON defined exactly once (reused, not duplicated)');

    // Verify weapon range uses it
    const wpnFnIdx = mapSrc.indexOf('function _updateWeaponRange');
    if (wpnFnIdx !== -1) {
        const wpnSnippet = mapSrc.substring(wpnFnIdx, wpnFnIdx + 1000);
        assert(wpnSnippet.includes('_makeCircleGeoJSON'),
            '_updateWeaponRange reuses _makeCircleGeoJSON');
    }
})();

// ============================================================
// 28. Heatmap visibility toggle updates MapLibre layout property
// ============================================================

console.log('\n--- Heatmap visibility toggle ---');

(function testHeatmapToggleVisibility() {
    const fnIdx = mapSrc.indexOf('function toggleHeatmap');
    assert(fnIdx !== -1, 'toggleHeatmap function found');
    if (fnIdx === -1) return;
    const snippet = mapSrc.substring(fnIdx, fnIdx + 500);
    assert(snippet.includes('setLayoutProperty'), 'toggleHeatmap uses setLayoutProperty');
    assert(snippet.includes('visibility'), 'toggleHeatmap toggles visibility');
})();

// ============================================================
// Summary
// ============================================================

console.log('\n' + '='.repeat(40));
console.log(`Results: ${passed} passed, ${failed} failed`);
console.log('='.repeat(40));
process.exit(failed > 0 ? 1 : 0);
