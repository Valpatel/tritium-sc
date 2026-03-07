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
const mapSrc = fs.readFileSync(__dirname + '/../../src/frontend/js/command/map-maplibre.js', 'utf8');
const menuBarSrc = fs.readFileSync(__dirname + '/../../src/frontend/js/command/menu-bar.js', 'utf8');
const mainSrc = fs.readFileSync(__dirname + '/../../src/frontend/js/command/main.js', 'utf8');

// ============================================================
// 1. Verify all toggle functions are exported from map-maplibre.js
// ============================================================

console.log('\n--- Toggle function exports ---');

const requiredExports = [
    'toggleSatellite', 'toggleRoads', 'toggleGrid', 'toggleBuildings',
    'toggleFog', 'toggleTerrain', 'toggleLabels', 'toggleModels',
    'toggleWaterways', 'toggleParks', 'toggleMesh', 'toggleTilt',
    'togglePatrolRoutes',
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
    'showPatrolRoutes',
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
    togglePatrolRoutes: 'showPatrolRoutes',
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
    'showPatrolRoutes',
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

// NOTE: FX toggles moved to Layers panel (Layer Browser).
// MAP menu now has simplified quick toggles only.
const menuLabels = [
    'Layer Browser...', 'Toggle All Layers',
    'Satellite', 'Buildings', 'Roads', 'Grid', 'Unit Markers',
    'GIS Intelligence', 'Fog of War', 'Terrain',
    'Center on Action', 'Reset Camera', 'Zoom In', 'Zoom Out',
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
// 10. Fog of war integration wiring
// ============================================================

console.log('\n--- Fog of war integration wiring ---');

// Verify fog-hidden CSS class applied when showFog && !visible
(function testFogHiddenClassApplied() {
    // Find the _updateUnits function or the unit marker fog block
    const fogBlock = mapSrc.match(/unit\.alliance\s*===?\s*['"]hostile['"].*visible\s*===?\s*false.*showFog/s);
    assert(fogBlock !== null, 'Unit marker update checks hostile + !visible + showFog');
})();

(function testFogHiddenClassSet() {
    const fogIdx = mapSrc.indexOf("el.classList.add('fog-hidden')");
    assert(fogIdx > 0, 'fog-hidden CSS class is set on invisible hostiles');
})();

(function testRadioGhostClassSet() {
    const radioIdx = mapSrc.indexOf("el.classList.add('radio-ghost')");
    assert(radioIdx > 0, 'radio-ghost CSS class is set on radio-detected hostiles');
})();

(function testSignalStrengthStored() {
    const ssIdx = mapSrc.indexOf('dataset.signalStrength');
    assert(ssIdx > 0, 'radio signal strength stored in data attribute');
})();

(function testFogClassesRemovedWhenVisible() {
    // When showFog is false or unit becomes visible, both classes removed
    const block = mapSrc.match(/remove\('fog-hidden'\)[\s\S]{0,100}remove\('radio-ghost'\)/);
    assert(block !== null, 'fog-hidden and radio-ghost classes removed when not applicable');
})();

// Auto-enable fog on game start
(function testAutoEnableFogOnCombat() {
    const autoBlock = mainSrc.match(/phase\s*===?\s*['"]countdown['"].*toggleFog/s) ||
                      mainSrc.match(/phase\s*===?\s*['"]active['"].*toggleFog/s);
    assert(autoBlock !== null, 'Fog auto-enabled on countdown/active phase');
})();

(function testAutoDisableFogOnIdle() {
    const idleBlock = mainSrc.match(/phase\s*===?\s*['"]idle['"].*toggleFog/s) ||
                      mainSrc.match(/phase\s*===?\s*['"]setup['"].*toggleFog/s);
    assert(idleBlock !== null, 'Fog auto-disabled on idle/setup phase');
})();

// V key toggles fog
(function testVKeyTogglesFog() {
    const vBlock = mainSrc.match(/case\s+['"]v['"][\s\S]*?toggleFog/);
    assert(vBlock !== null, 'V key triggers toggleFog()');
})();

// toggleFog enables/disables vision system
(function testToggleFogWiresVisionSystem() {
    const toggleFn = mapSrc.match(/function toggleFog[\s\S]*?console\.log/);
    assert(toggleFn !== null, 'toggleFog function found');
    if (toggleFn) {
        assert(toggleFn[0].includes('visionSystem.enable'), 'toggleFog calls visionSystem.enable()');
        assert(toggleFn[0].includes('visionSystem.disable'), 'toggleFog calls visionSystem.disable()');
    }
})();

// FrontendVisionSystem initialized during map setup
(function testVisionSystemInitialized() {
    assert(mapSrc.includes('new FrontendVisionSystem()'), 'FrontendVisionSystem created in map init');
    assert(mapSrc.includes('visionSystem.init'), 'VisionSystem initialized with scene');
})();

// Vision system updated per render frame
(function testVisionSystemUpdatedPerFrame() {
    const renderBlock = mapSrc.match(/visionSystem[\s\S]{0,40}update\(/);
    assert(renderBlock !== null, 'VisionSystem updated per render frame');
})();

// CSS fog-hidden and radio-ghost styles exist
const cssSrc = fs.readFileSync(__dirname + '/../../src/frontend/css/tritium.css', 'utf8');
(function testFogHiddenCSSExists() {
    assert(cssSrc.includes('.fog-hidden'), 'fog-hidden CSS class defined in tritium.css');
    assert(cssSrc.includes('opacity: 0.2'), 'fog-hidden has reduced opacity');
})();

(function testRadioGhostCSSExists() {
    assert(cssSrc.includes('.radio-ghost'), 'radio-ghost CSS class defined in tritium.css');
    assert(cssSrc.includes('radio-pulse'), 'radio-ghost has pulse animation');
})();

(function testRadioGhostShowsSignalStrength() {
    assert(cssSrc.includes('attr(data-signal-strength)'), 'radio-ghost displays signal strength from data attribute');
})();

// ============================================================
// 11. Verify newer toggle function exports
// ============================================================

console.log('\n--- Newer toggle function exports ---');

const newerExports = [
    'toggleUnits', 'toggleWeaponRange', 'toggleHeatmap',
    'toggleSwarmHull', 'toggleSquadHulls', 'toggleHazardZones',
    'toggleHostileObjectives', 'toggleCrowdDensity', 'toggleCoverPoints',
    'toggleUnitSignals', 'toggleHostileIntel', 'toggleAutoFollow',
    'toggleThoughts',
];

for (const name of newerExports) {
    const pattern = new RegExp('export\\s+function\\s+' + name + '\\b');
    assert(pattern.test(mapSrc), `map-maplibre.js exports ${name}()`);
}

// ============================================================
// 12. Verify newer state variables exist in _state initialization
// ============================================================

console.log('\n--- Newer state variable declarations ---');

const newerState = [
    'showWeaponRange', 'showHeatmap', 'showSwarmHull', 'showSquadHulls',
    'showHazardZones', 'showHostileObjectives', 'showCrowdDensity',
    'showCoverPoints', 'showUnitSignals', 'showHostileIntel',
    'autoFollow', 'showThoughts',
];

for (const key of newerState) {
    const pattern = new RegExp(key + '\\s*:\\s*(true|false)');
    assert(pattern.test(mapSrc), `_state has ${key} (boolean)`);
}

// ============================================================
// 13. Verify newer toggle functions flip their state flag
// ============================================================

console.log('\n--- Newer toggle function state flips ---');

const newerToggleToState = {
    toggleWeaponRange: 'showWeaponRange',
    toggleHeatmap: 'showHeatmap',
    toggleSwarmHull: 'showSwarmHull',
    toggleSquadHulls: 'showSquadHulls',
    toggleHazardZones: 'showHazardZones',
    toggleHostileObjectives: 'showHostileObjectives',
    toggleCrowdDensity: 'showCrowdDensity',
    toggleCoverPoints: 'showCoverPoints',
    toggleUnitSignals: 'showUnitSignals',
    toggleHostileIntel: 'showHostileIntel',
    toggleSatellite: 'showSatellite',
    toggleRoads: 'showRoads',
    toggleBuildings: 'showBuildings',
    toggleGrid: 'showGrid',
    toggleFog: 'showFog',
    toggleUnits: 'showUnits',
    toggleLabels: 'showLabels',
    toggleModels: 'showModels3d',
    toggleWaterways: 'showWaterways',
    toggleParks: 'showParks',
    toggleMesh: 'showMesh',
    toggleThoughts: 'showThoughts',
};

for (const [fn, stateKey] of Object.entries(newerToggleToState)) {
    const pattern = new RegExp('_state\\.' + stateKey + '\\s*=\\s*!_state\\.' + stateKey);
    assert(pattern.test(mapSrc), `${fn}() toggles _state.${stateKey}`);
}

// ============================================================
// 14. Verify getMapState() returns all newer keys
// ============================================================

console.log('\n--- getMapState() returns newer keys ---');

// Use a broader pattern to capture the full function body (it spans many lines)
const fullGetMapState = mapSrc.match(/export function getMapState\(\)\s*\{[\s\S]*?^\}/m);
const fullGetMapStateBody = fullGetMapState ? fullGetMapState[0] : '';

const newerReturnKeys = [
    'showWeaponRange', 'showHeatmap', 'showSwarmHull', 'showSquadHulls',
    'showHazardZones', 'showHostileObjectives', 'showCrowdDensity',
    'showCoverPoints', 'showUnitSignals', 'showHostileIntel',
    'autoFollow', 'tiltMode', 'currentMode',
    'showSatellite', 'showRoads', 'showGrid', 'showBuildings',
    'showUnits', 'showLabels', 'showModels3d', 'showFog',
    'showTerrain', 'showWaterways', 'showParks', 'showMesh',
    'showThoughts',
];

for (const key of newerReturnKeys) {
    assert(fullGetMapStateBody.includes(key + ':'), `getMapState() returns ${key}`);
}

// ============================================================
// 15. setMapMode() sets correct layer configurations
// ============================================================

console.log('\n--- setMapMode() configurations ---');

// Extract setMapMode function body
const setMapModeMatch = mapSrc.match(/export function setMapMode\(mode\)\s*\{[\s\S]*?^}/m);
assert(setMapModeMatch !== null, 'setMapMode() function found');

if (setMapModeMatch) {
    const smBody = setMapModeMatch[0];

    // Observe mode: satellite true, grid false, models3d false
    assert(smBody.includes("case 'observe':"), 'setMapMode handles observe mode');
    assert(smBody.includes("case 'tactical':"), 'setMapMode handles tactical mode');
    assert(smBody.includes("case 'setup':"), 'setMapMode handles setup mode');

    // All modes call _updateLayerHud and log
    assert(smBody.includes('_updateLayerHud()'), 'setMapMode updates layer HUD');
    assert(smBody.includes('console.log'), 'setMapMode logs mode change');

    // Unknown mode guard
    assert(smBody.includes('Unknown mode'), 'setMapMode warns on unknown mode');
}

// ============================================================
// 16. setMapMode() stores current mode in _state
// ============================================================

console.log('\n--- setMapMode() stores currentMode ---');

(function testSetMapModeUpdatesState() {
    const smMatch = mapSrc.match(/export function setMapMode[\s\S]*?_state\.currentMode\s*=\s*mode/);
    assert(smMatch !== null, 'setMapMode sets _state.currentMode = mode');
})();

// ============================================================
// 17. setMapMode() cleans up setup ghost when leaving setup
// ============================================================

(function testSetMapModeCleansUpSetupGhost() {
    const smMatch = mapSrc.match(/setMapMode[\s\S]*?_clearSetupGhost/);
    assert(smMatch !== null, 'setMapMode clears setup ghost when leaving setup mode');
})();

// ============================================================
// 18. setLayers() individual override logic
// ============================================================

console.log('\n--- setLayers() individual override logic ---');

const setLayersMatch = mapSrc.match(/export function setLayers\(layers\)\s*\{[\s\S]*?^}/m);
assert(setLayersMatch !== null, 'setLayers() function found');

if (setLayersMatch) {
    const slBody = setLayersMatch[0];

    // allMapLayers support
    assert(slBody.includes('allMapLayers'), 'setLayers supports allMapLayers flag');

    // Individual layer overrides
    const layerOverrides = [
        'layers.satellite', 'layers.buildings', 'layers.roads', 'layers.grid',
        'layers.units', 'layers.models3d', 'layers.domMarkers', 'layers.geoLayers',
        'layers.waterways', 'layers.parks', 'layers.fog', 'layers.terrain',
        'layers.patrolRoutes', 'layers.weaponRange', 'layers.heatmap',
        'layers.swarmHull', 'layers.squadHulls', 'layers.autoFollow',
    ];

    for (const override of layerOverrides) {
        assert(slBody.includes(override), `setLayers supports ${override} override`);
    }

    // Returns getMapState()
    assert(slBody.includes('return getMapState()'), 'setLayers returns getMapState()');
}

// ============================================================
// 19. toggleAllLayers() logic
// ============================================================

console.log('\n--- toggleAllLayers() logic ---');

(function testToggleAllLayersCallsSetLayers() {
    const toggleAllMatch = mapSrc.match(/function toggleAllLayers[\s\S]*?(?=export function [a-z])/);
    assert(toggleAllMatch !== null, 'toggleAllLayers function found');
    if (toggleAllMatch) {
        const body = toggleAllMatch[0];
        assert(body.includes('setLayers'), 'toggleAllLayers calls setLayers');
        assert(body.includes('allMapLayers'), 'toggleAllLayers uses allMapLayers');
        assert(body.includes('defaultOnKeys'), 'toggleAllLayers uses defaultOnKeys list for direction');
    }
})();

// ============================================================
// 20. Terrain toggle has API guard (setTerrain)
// ============================================================

console.log('\n--- Terrain toggle guards ---');

(function testTerrainToggleHasAPIGuard() {
    const terrainMatch = mapSrc.match(/export function toggleTerrain[\s\S]*?console\.log/);
    assert(terrainMatch !== null, 'toggleTerrain function found');
    if (terrainMatch) {
        assert(terrainMatch[0].includes('setTerrain'), 'toggleTerrain calls map.setTerrain');
        assert(terrainMatch[0].includes('typeof'), 'toggleTerrain guards with typeof check');
    }
})();

(function testTerrainToggleSetsExaggeration() {
    const terrainMatch = mapSrc.match(/export function toggleTerrain[\s\S]*?console\.log/);
    if (terrainMatch) {
        assert(terrainMatch[0].includes('terrainExaggeration'),
            'toggleTerrain uses terrain exaggeration setting');
    }
})();

(function testTerrainToggleSetsNullWhenOff() {
    const terrainMatch = mapSrc.match(/export function toggleTerrain[\s\S]*?console\.log/);
    if (terrainMatch) {
        assert(terrainMatch[0].includes('setTerrain(null)'),
            'toggleTerrain sets terrain to null when disabled');
    }
})();

// ============================================================
// 21. Toggle functions with DOM side effects
// ============================================================

console.log('\n--- Toggle DOM side effects ---');

(function testToggleUnitsHidesMarkers() {
    const toggleMatch = mapSrc.match(/export function toggleUnits[\s\S]*?console\.log/);
    assert(toggleMatch !== null, 'toggleUnits function found');
    if (toggleMatch) {
        assert(toggleMatch[0].includes('display'), 'toggleUnits sets marker display style');
        assert(toggleMatch[0].includes('unitMarkers'), 'toggleUnits iterates unitMarkers');
    }
})();

(function testToggleModelsTogglesThreeRoot() {
    const toggleMatch = mapSrc.match(/export function toggleModels[\s\S]*?console\.log/);
    assert(toggleMatch !== null, 'toggleModels function found');
    if (toggleMatch) {
        assert(toggleMatch[0].includes('threeRoot'), 'toggleModels toggles threeRoot visibility');
    }
})();

(function testToggleLayerHudHidesDom() {
    const toggleMatch = mapSrc.match(/export function toggleLayerHud[\s\S]*?console\.log/);
    assert(toggleMatch !== null, 'toggleLayerHud function found');
    if (toggleMatch) {
        assert(toggleMatch[0].includes('layerHud'), 'toggleLayerHud controls layerHud element');
        assert(toggleMatch[0].includes('display'), 'toggleLayerHud sets display style');
    }
})();

(function testToggleKillFeedHidesDom() {
    const toggleMatch = mapSrc.match(/export function toggleKillFeed[\s\S]*?console\.log/);
    assert(toggleMatch !== null, 'toggleKillFeed function found');
    if (toggleMatch) {
        assert(toggleMatch[0].includes('fx-kill-feed'), 'toggleKillFeed targets .fx-kill-feed element');
    }
})();

(function testToggleHostileIntelHidesDom() {
    const toggleMatch = mapSrc.match(/export function toggleHostileIntel[\s\S]*?console\.log/);
    assert(toggleMatch !== null, 'toggleHostileIntel function found');
    if (toggleMatch) {
        assert(toggleMatch[0].includes('_hostileIntelEl'), 'toggleHostileIntel controls hostile intel element');
        assert(toggleMatch[0].includes('display'), 'toggleHostileIntel sets display style');
    }
})();

// ============================================================
// 22. Toggle functions that clear overlays on disable
// ============================================================

console.log('\n--- Overlay clearing on toggle off ---');

const overlayClears = {
    toggleWeaponRange: '_clearWeaponRange',
    toggleSwarmHull: '_clearSwarmHull',
    toggleSquadHulls: '_clearSquadHulls',
    toggleHazardZones: '_clearHazardZones',
    toggleHostileObjectives: '_clearHostileObjectives',
    toggleCrowdDensity: '_clearCrowdDensity',
    toggleCoverPoints: '_clearCoverPoints',
    toggleUnitSignals: '_clearUnitSignals',
};

for (const [fn, clearFn] of Object.entries(overlayClears)) {
    const pattern = new RegExp('function ' + fn.replace('toggle', 'toggle') + '[\\s\\S]*?' + clearFn);
    assert(pattern.test(mapSrc), `${fn}() calls ${clearFn}() when toggled off`);
}

// ============================================================
// 23. Clear functions exist for all overlays
// ============================================================

console.log('\n--- Clear functions exist ---');

const clearFunctions = [
    '_clearWeaponRange', '_clearSwarmHull', '_clearSquadHulls',
    '_clearHazardZones', '_clearHostileObjectives', '_clearCrowdDensity',
    '_clearCoverPoints', '_clearUnitSignals', '_clearCombatRadius',
];

for (const fn of clearFunctions) {
    assert(mapSrc.includes('function ' + fn), `${fn}() function exists`);
}

// ============================================================
// 24. toggleThoughts clears visible thought IDs when disabled
// ============================================================

console.log('\n--- toggleThoughts clears thought IDs ---');

(function testToggleThoughtsClearsIds() {
    const thoughtMatch = mapSrc.match(/export function toggleThoughts[\s\S]*?console\.log/);
    assert(thoughtMatch !== null, 'toggleThoughts function found');
    if (thoughtMatch) {
        assert(thoughtMatch[0].includes('_visibleThoughtIds'),
            'toggleThoughts clears _visibleThoughtIds');
        assert(thoughtMatch[0].includes('thought-bubble'),
            'toggleThoughts hides thought bubble DOM elements');
    }
})();

// ============================================================
// 25. toggleTilt checks current pitch and flips
// ============================================================

console.log('\n--- toggleTilt pitch logic ---');

(function testToggleTiltChecksCurrentPitch() {
    const tiltMatch = mapSrc.match(/export function toggleTilt[\s\S]*?console\.log/);
    assert(tiltMatch !== null, 'toggleTilt function found');
    if (tiltMatch) {
        assert(tiltMatch[0].includes('getPitch'), 'toggleTilt reads current pitch');
        assert(tiltMatch[0].includes('easeTo'), 'toggleTilt calls easeTo for smooth transition');
        assert(tiltMatch[0].includes('tiltMode'), 'toggleTilt updates tiltMode state');
    }
})();

(function testToggleTiltGuardsNoMap() {
    const tiltMatch = mapSrc.match(/export function toggleTilt[\s\S]*?console\.log/);
    if (tiltMatch) {
        assert(tiltMatch[0].includes('if (!_state.map) return'),
            'toggleTilt returns early when no map');
    }
})();

// ============================================================
// 26. toggleAutoFollow starts/stops auto-follow
// ============================================================

console.log('\n--- toggleAutoFollow logic ---');

(function testToggleAutoFollowLogic() {
    // toggleAutoFollow has nested braces, so extract a broader chunk
    const afIdx = mapSrc.indexOf('export function toggleAutoFollow');
    assert(afIdx >= 0, 'toggleAutoFollow function found');
    if (afIdx >= 0) {
        const snippet = mapSrc.substring(afIdx, afIdx + 300);
        assert(snippet.includes('_startAutoFollow'), 'toggleAutoFollow calls _startAutoFollow');
        assert(snippet.includes('_stopAutoFollow'), 'toggleAutoFollow calls _stopAutoFollow');
        assert(snippet.includes('autoFollow'), 'toggleAutoFollow checks autoFollow state');
    }
})();

// ============================================================
// 27. centerOnAction focuses on hostile units
// ============================================================

console.log('\n--- centerOnAction logic ---');

(function testCenterOnActionUsesHostiles() {
    const caMatch = mapSrc.match(/export function centerOnAction[\s\S]*?^}/m);
    assert(caMatch !== null, 'centerOnAction function found');
    if (caMatch) {
        assert(caMatch[0].includes("'hostile'"), 'centerOnAction filters for hostile units');
        assert(caMatch[0].includes('flyTo'), 'centerOnAction calls map.flyTo');
        assert(caMatch[0].includes('count'), 'centerOnAction counts hostiles for centroid');
    }
})();

// ============================================================
// 28. resetCamera restores defaults
// ============================================================

console.log('\n--- resetCamera logic ---');

(function testResetCameraUsesDefaults() {
    const rcMatch = mapSrc.match(/export function resetCamera[\s\S]*?^}/m);
    assert(rcMatch !== null, 'resetCamera function found');
    if (rcMatch) {
        assert(rcMatch[0].includes('flyTo'), 'resetCamera calls map.flyTo');
        assert(rcMatch[0].includes('geoCenter'), 'resetCamera uses geoCenter');
        assert(rcMatch[0].includes('_clearCombatRadius'), 'resetCamera clears combat radius');
    }
})();

// ============================================================
// 29. zoomIn/zoomOut use map methods
// ============================================================

console.log('\n--- zoomIn/zoomOut logic ---');

(function testZoomInGuardsNoMap() {
    const ziMatch = mapSrc.match(/export function zoomIn[\s\S]*?^}/m);
    assert(ziMatch !== null, 'zoomIn function found');
    if (ziMatch) {
        assert(ziMatch[0].includes('if (_state.map)'), 'zoomIn guards with _state.map check');
        assert(ziMatch[0].includes('zoomIn'), 'zoomIn calls map.zoomIn');
    }
})();

(function testZoomOutGuardsNoMap() {
    const zoMatch = mapSrc.match(/export function zoomOut[\s\S]*?^}/m);
    assert(zoMatch !== null, 'zoomOut function found');
    if (zoMatch) {
        assert(zoMatch[0].includes('if (_state.map)'), 'zoomOut guards with _state.map check');
        assert(zoMatch[0].includes('zoomOut'), 'zoomOut calls map.zoomOut');
    }
})();

// ============================================================
// 30. destroyMap cleanup
// ============================================================

console.log('\n--- destroyMap cleanup ---');

(function testDestroyMapCleanup() {
    const dmMatch = mapSrc.match(/export function destroyMap[\s\S]*?console\.log/);
    assert(dmMatch !== null, 'destroyMap function found');
    if (dmMatch) {
        assert(dmMatch[0].includes('map.remove()'), 'destroyMap removes MapLibre map');
        assert(dmMatch[0].includes('unitMarkers'), 'destroyMap cleans up unit markers');
        assert(dmMatch[0].includes('unitMeshes'), 'destroyMap cleans up unit meshes');
        assert(dmMatch[0].includes('visionSystem'), 'destroyMap disposes vision system');
        assert(dmMatch[0].includes('initialized = false'), 'destroyMap sets initialized to false');
        assert(dmMatch[0].includes('_hostileIntelEl'), 'destroyMap removes hostile intel element');
    }
})();

// ============================================================
// 31. GeoJSON overlay layer constants
// ============================================================

console.log('\n--- GeoJSON overlay layer constants ---');

const overlayConstants = [
    'PATROL_ROUTES_SOURCE', 'PATROL_ROUTES_LINE', 'PATROL_ROUTES_DOTS',
    'COMBAT_HEATMAP_SOURCE', 'COMBAT_HEATMAP_LAYER',
    'SWARM_HULL_SOURCE', 'SWARM_HULL_FILL',
    'SQUAD_HULL_SOURCE', 'SQUAD_HULL_FILL',
    'HAZARD_ZONES_SOURCE', 'HAZARD_ZONES_FILL',
    'HOSTILE_OBJ_SOURCE', 'HOSTILE_OBJ_LINE',
    'CROWD_DENSITY_SOURCE', 'CROWD_DENSITY_FILL',
    'COVER_POINTS_SOURCE', 'COVER_POINTS_CIRCLE',
    'UNIT_SIGNALS_SOURCE', 'UNIT_SIGNALS_CIRCLE',
];

for (const name of overlayConstants) {
    assert(mapSrc.includes(name), `Overlay constant ${name} defined`);
}

// ============================================================
// 32. Waterways/Parks toggle iterates style layers
// ============================================================

console.log('\n--- Waterways/Parks layer iteration ---');

(function testWaterwaysIteratesLayers() {
    const wwMatch = mapSrc.match(/export function toggleWaterways[\s\S]*?console\.log/);
    assert(wwMatch !== null, 'toggleWaterways function found');
    if (wwMatch) {
        assert(wwMatch[0].includes('getStyle'), 'toggleWaterways uses getStyle()');
        assert(wwMatch[0].includes("'water'"), 'toggleWaterways matches water layer IDs');
    }
})();

(function testParksIteratesLayers() {
    const pkMatch = mapSrc.match(/export function toggleParks[\s\S]*?console\.log/);
    assert(pkMatch !== null, 'toggleParks function found');
    if (pkMatch) {
        assert(pkMatch[0].includes('getStyle'), 'toggleParks uses getStyle()');
        assert(pkMatch[0].includes("'park'"), 'toggleParks matches park layer IDs');
        assert(pkMatch[0].includes("'landuse'"), 'toggleParks matches landuse layer IDs');
    }
})();

// ============================================================
// 33. setLayers allMapLayers resets all state flags
// ============================================================

console.log('\n--- setLayers allMapLayers state sync ---');

(function testSetLayersAllMapLayersSyncsFlags() {
    const slBody = setLayersMatch ? setLayersMatch[0] : '';
    if (slBody) {
        // When allMapLayers=false, these state flags should be set to false
        const falseFlags = [
            'showSatellite', 'showBuildings', 'showRoads', 'showWaterways',
            'showParks', 'showUnits', 'showLabels', 'showModels3d', 'showGeoLayers',
        ];
        for (const flag of falseFlags) {
            assert(slBody.includes(flag + ' = false'), `setLayers allMapLayers:false sets ${flag}=false`);
            assert(slBody.includes(flag + ' = true'), `setLayers allMapLayers:true sets ${flag}=true`);
        }
    }
})();

// ============================================================
// 34. initMap checks MapLibre dependency
// ============================================================

console.log('\n--- initMap dependency checks ---');

(function testInitMapChecksMaplibre() {
    const initMatch = mapSrc.match(/export function initMap[\s\S]*?_fetchGeoReference/);
    assert(initMatch !== null, 'initMap function found');
    if (initMatch) {
        assert(initMatch[0].includes('maplibregl'), 'initMap checks for maplibregl global');
        assert(initMatch[0].includes('tactical-area'), 'initMap looks for tactical-area container');
        assert(initMatch[0].includes("'undefined'"), 'initMap uses typeof check for maplibregl');
    }
})();

// ============================================================
// 35. _state exposed as window._mapState for testing
// ============================================================

console.log('\n--- _state exposed for testing ---');

(function testStateExposedOnWindow() {
    assert(mapSrc.includes('window._mapState = _state'),
        '_state exposed as window._mapState for automated testing');
})();

// ============================================================
// 36. FX constants defined
// ============================================================

console.log('\n--- FX constants ---');

(function testFXConstants() {
    const fxKeys = [
        'TRACER_DURATION', 'TRACER_HEAD_R', 'TRACER_GLOW_R',
        'FLASH_DURATION', 'FLASH_R',
        'HIT_DURATION', 'HIT_R',
        'ELIM_DURATION', 'ELIM_R_START', 'ELIM_R_END',
        'PARTICLE_COUNT', 'PARTICLE_DURATION', 'PARTICLE_SPEED', 'PARTICLE_R',
    ];
    for (const key of fxKeys) {
        assert(mapSrc.includes(key), `FX constant ${key} defined`);
    }
})();

// ============================================================
// 37. UNIT_3D model sizing constants
// ============================================================

console.log('\n--- UNIT_3D constants ---');

(function testUnit3DConstants() {
    const u3dKeys = ['SCALE', 'ALT', 'DRONE_ALT', 'RING_PULSE', 'ROTOR_SPEED', 'BEAM_PULSE'];
    for (const key of u3dKeys) {
        const pattern = new RegExp('UNIT_3D\\s*=\\s*\\{[\\s\\S]*?' + key);
        assert(pattern.test(mapSrc), `UNIT_3D.${key} defined`);
    }
})();

// ============================================================
// 38. ALLIANCE_COLORS match between MapLibre and Canvas
// ============================================================

console.log('\n--- ALLIANCE_COLORS consistency ---');

(function testAllianceColorsDefined() {
    const alliances = ['friendly', 'hostile', 'neutral', 'unknown'];
    for (const a of alliances) {
        const pattern = new RegExp("ALLIANCE_COLORS[\\s\\S]*?" + a + "\\s*:\\s*'#[0-9a-f]{6}'", 'i');
        assert(pattern.test(mapSrc), `ALLIANCE_COLORS.${a} defined in map-maplibre.js`);
    }
})();

// ============================================================
// Summary
// ============================================================

console.log('\n' + '='.repeat(40));
console.log(`Results: ${passed} passed, ${failed} failed`);
console.log('='.repeat(40));
process.exit(failed > 0 ? 1 : 0);
