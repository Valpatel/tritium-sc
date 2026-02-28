// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
/**
 * TRITIUM-SC MapLibre Layer Toggle tests
 * Tests that all layer toggle functions exist, are exported, flip state correctly,
 * and that getMapState() exposes all layer state keys.
 *
 * Also verifies guard logic: effect creation functions check state flags before
 * creating DOM/Three.js elements.
 *
 * Run: node tests/js/test_map_layers.js
 */

const fs = require('fs');

// Simple test runner
let passed = 0, failed = 0;
function assert(cond, msg) {
    if (!cond) { console.error('FAIL:', msg); failed++; }
    else { console.log('PASS:', msg); passed++; }
}

// Read the source files
const mapSrc = fs.readFileSync(__dirname + '/../../frontend/js/command/map-maplibre.js', 'utf8');
const menuBarSrc = fs.readFileSync(__dirname + '/../../frontend/js/command/menu-bar.js', 'utf8');
const mainSrc = fs.readFileSync(__dirname + '/../../frontend/js/command/main.js', 'utf8');

// ============================================================
// 1. Verify all toggle functions are exported from map-maplibre.js
// ============================================================

console.log('\n--- Toggle function exports ---');

const requiredExports = [
    'toggleSatellite', 'toggleRoads', 'toggleGrid', 'toggleBuildings',
    'toggleFog', 'toggleTerrain', 'toggleLabels', 'toggleModels',
    'toggleWaterways', 'toggleParks', 'toggleMesh', 'toggleTilt',
    'toggleTracers', 'toggleExplosions', 'toggleParticles',
    'toggleHitFlashes', 'toggleFloatingText', 'toggleKillFeed',
    'toggleScreenFx', 'toggleBanners', 'toggleLayerHud',
    'toggleHealthBars', 'toggleSelectionFx',
    'toggleAllLayers',
    'getMapState', 'centerOnAction', 'resetCamera', 'zoomIn', 'zoomOut',
    'initMap', 'destroyMap', 'setMapMode', 'setLayers',
];

for (const name of requiredExports) {
    const pattern = new RegExp('export\\s+function\\s+' + name + '\\b');
    assert(pattern.test(mapSrc), `map-maplibre.js exports ${name}()`);
}

// ============================================================
// 2. Verify all state variables exist in _state initialization
// ============================================================

console.log('\n--- State variable declarations ---');

const requiredState = [
    'showSatellite', 'showRoads', 'showGrid', 'showBuildings',
    'showWaterways', 'showParks', 'showTerrain', 'showGeoLayers',
    'showUnits', 'showLabels', 'showModels3d', 'showFog', 'showMesh',
    'showTracers', 'showExplosions', 'showParticles',
    'showHitFlashes', 'showFloatingText',
    'showHealthBars', 'showSelectionFx',
    'showKillFeed', 'showScreenFx', 'showBanners', 'showLayerHud',
];

for (const key of requiredState) {
    const pattern = new RegExp(key + '\\s*:\\s*(true|false)');
    assert(pattern.test(mapSrc), `_state has ${key} (boolean)`);
}

// ============================================================
// 3. Verify toggle functions flip their state flag
// ============================================================

console.log('\n--- Toggle function flips state ---');

const toggleToState = {
    toggleTracers: 'showTracers',
    toggleExplosions: 'showExplosions',
    toggleParticles: 'showParticles',
    toggleHitFlashes: 'showHitFlashes',
    toggleFloatingText: 'showFloatingText',
    toggleKillFeed: 'showKillFeed',
    toggleScreenFx: 'showScreenFx',
    toggleBanners: 'showBanners',
    toggleLayerHud: 'showLayerHud',
    toggleHealthBars: 'showHealthBars',
    toggleSelectionFx: 'showSelectionFx',
};

for (const [fn, stateKey] of Object.entries(toggleToState)) {
    // Each toggle function should contain `_state.{stateKey} = !_state.{stateKey}`
    const pattern = new RegExp('_state\\.' + stateKey + '\\s*=\\s*!_state\\.' + stateKey);
    assert(pattern.test(mapSrc), `${fn}() toggles _state.${stateKey}`);
}

// ============================================================
// 4. Verify getMapState() returns all new keys
// ============================================================

console.log('\n--- getMapState() return keys ---');

const getMapStateMatch = mapSrc.match(/export function getMapState\(\)\s*\{[^}]+\}/s);
assert(getMapStateMatch !== null, 'getMapState() function found');

const getMapStateBody = getMapStateMatch ? getMapStateMatch[0] : '';

const stateReturnKeys = [
    'showTracers', 'showExplosions', 'showParticles', 'showHitFlashes',
    'showFloatingText', 'showKillFeed', 'showScreenFx', 'showBanners',
    'showLayerHud', 'showHealthBars', 'showSelectionFx',
];

for (const key of stateReturnKeys) {
    assert(getMapStateBody.includes(key + ':'), `getMapState() returns ${key}`);
}

// ============================================================
// 5. Verify guard conditions in effect functions
// ============================================================

console.log('\n--- Effect function guards ---');

const guards = [
    { fn: '_onCombatProjectile', guard: 'showTracers', desc: 'Tracer guard in projectile handler' },
    { fn: '_spawnDomFlash', guard: 'showHitFlashes', desc: 'Hit flash guard in DOM flash' },
    { fn: '_spawnDomExplosion', guard: 'showExplosions', desc: 'Explosion guard in DOM explosion' },
    { fn: '_spawnFloatingText', guard: 'showFloatingText', desc: 'Floating text guard' },
    { fn: '_triggerScreenShake', guard: 'showScreenFx', desc: 'Screen FX guard in shake' },
    { fn: '_triggerScreenFlash', guard: 'showScreenFx', desc: 'Screen FX guard in flash' },
    { fn: '_addKillFeedEntry', guard: 'showKillFeed', desc: 'Kill feed guard' },
    { fn: '_showMapBanner', guard: 'showBanners', desc: 'Banner guard in map banner' },
    { fn: '_showStreakBanner', guard: 'showBanners', desc: 'Banner guard in streak banner' },
    { fn: '_startCountdownOverlay', guard: 'showBanners', desc: 'Banner guard in countdown' },
];

for (const g of guards) {
    // Find the function declaration and extract first 10 lines of its body
    const fnIdx = mapSrc.indexOf('function ' + g.fn + '(');
    if (fnIdx === -1) {
        assert(false, g.desc + ' (function not found: ' + g.fn + ')');
        continue;
    }
    // Get text from function start to 500 chars ahead (covers first ~10 lines)
    const snippet = mapSrc.substring(fnIdx, fnIdx + 500);
    const guardCheck = new RegExp('_state\\.' + g.guard);
    assert(guardCheck.test(snippet), g.desc);
}

// Verify _onCombatHit guards the Three.js section with showHitFlashes
(function testCombatHitGuard() {
    const hitMatch = mapSrc.match(/function _onCombatHit\b[\s\S]*?(?=function _onCombat[ELS])/);
    assert(hitMatch !== null, '_onCombatHit function found');
    if (hitMatch) {
        assert(hitMatch[0].includes('_state.showHitFlashes'),
            'Hit handler checks showHitFlashes before Three.js effects');
        assert(hitMatch[0].includes('_state.showParticles'),
            'Hit handler checks showParticles for particle burst');
    }
})();

// Verify _onCombatElimination guards with showExplosions
(function testCombatElimGuard() {
    const elimMatch = mapSrc.match(/function _onCombatElimination\b[\s\S]*?(?=function _onCombatStreak)/);
    assert(elimMatch !== null, '_onCombatElimination function found');
    if (elimMatch) {
        assert(elimMatch[0].includes('_state.showExplosions'),
            'Elimination handler checks showExplosions before Three.js effects');
        assert(elimMatch[0].includes('_state.showParticles'),
            'Elimination handler checks showParticles for particle burst');
    }
})();

// Verify _onCombatStreak guards with showHitFlashes
(function testCombatStreakGuard() {
    const streakMatch = mapSrc.match(/function _onCombatStreak\b[\s\S]*?(?=function _showStreakBanner)/);
    assert(streakMatch !== null, '_onCombatStreak function found');
    if (streakMatch) {
        assert(streakMatch[0].includes('_state.showHitFlashes'),
            'Streak handler checks showHitFlashes before Three.js flash');
    }
})();

// ============================================================
// 6. Verify _updateUnits respects showLabels
// ============================================================

console.log('\n--- Labels toggle integration ---');

(function testUpdateUnitsRespectsShowUnits() {
    const updateMatch = mapSrc.match(/function _updateUnits\b[\s\S]*?(?=function\s+\w)/);
    assert(updateMatch !== null, '_updateUnits function found');
    if (updateMatch) {
        // showUnits controls marker visibility (display none/block)
        const displayLine = updateMatch[0].match(/el\.style\.display\s*=.*showUnits/);
        assert(displayLine !== null,
            '_updateUnits display line uses showUnits');
    }
})();

(function testApplyMarkerStyleRespectsLabels() {
    // showLabels controls name label DOM elements inside _applyMarkerStyle
    const markerMatch = mapSrc.match(/function _applyMarkerStyle\b[\s\S]*?(?=function _updateMarkerElement)/);
    assert(markerMatch !== null, '_applyMarkerStyle function found');
    if (markerMatch) {
        assert(markerMatch[0].includes('_state.showLabels'),
            '_applyMarkerStyle checks showLabels for name label visibility');
    }
})();

// ============================================================
// 7. Verify main.js imports and wires all toggle functions
// ============================================================

console.log('\n--- main.js import and wiring ---');

const newToggles = [
    'toggleTracers', 'toggleExplosions', 'toggleParticles',
    'toggleHitFlashes', 'toggleFloatingText', 'toggleKillFeed',
    'toggleScreenFx', 'toggleBanners', 'toggleLayerHud',
    'toggleHealthBars', 'toggleSelectionFx',
    'toggleAllLayers',
];

for (const name of newToggles) {
    assert(mainSrc.includes(name),
        `main.js imports/uses ${name}`);
}

// Verify each is in the mapActions object
const mapActionsMatch = mainSrc.match(/const mapActions\s*=\s*\{[\s\S]*?\};/);
assert(mapActionsMatch !== null, 'mapActions object found in main.js');
if (mapActionsMatch) {
    for (const name of newToggles) {
        assert(mapActionsMatch[0].includes(name + ':'),
            `mapActions has ${name} wired`);
    }
}

// ============================================================
// 8. Verify menu-bar.js has all new menu items
// ============================================================

console.log('\n--- menu-bar.js menu items ---');

const menuLabels = [
    'Toggle All',
    'Tracers', 'Explosions', 'Particles', 'Hit Flashes', 'Floating Text',
    'Kill Feed', 'Screen FX', 'Banners', 'Layer HUD',
    'Health Bars', 'Selection FX',
];

for (const label of menuLabels) {
    const pattern = new RegExp("label:\\s*'" + label + "'");
    assert(pattern.test(menuBarSrc), `menu-bar.js has "${label}" menu item`);
}

// ============================================================
// 9. Verify effect disposal uses mesh.parent (not threeRoot)
// ============================================================

console.log('\n--- Effect disposal ---');

(function testDisposeUsesParent() {
    const disposeMatch = mapSrc.match(/function _disposeEffect\b[\s\S]*?(?=function\s+\w)/);
    assert(disposeMatch !== null, '_disposeEffect function found');
    if (disposeMatch) {
        assert(disposeMatch[0].includes('mesh.parent'),
            '_disposeEffect uses mesh.parent for removal (not hardcoded threeRoot)');
        assert(!disposeMatch[0].includes('threeRoot'),
            '_disposeEffect does NOT reference threeRoot');
    }
})();

// ============================================================
// Summary
// ============================================================

console.log('\n' + '='.repeat(40));
console.log(`Results: ${passed} passed, ${failed} failed`);
console.log('='.repeat(40));
process.exit(failed > 0 ? 1 : 0);
