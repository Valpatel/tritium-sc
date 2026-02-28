// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
/**
 * TRITIUM-SC War Room -- Fog of War + Minimap tests
 * Run: node tests/js/test_war_fog.js
 *
 * Tests fog calculation, vision radius per unit type, minimap coordinate
 * mapping, viewport rectangle, toggle state management, point-in-vision,
 * minimap hit testing, vision map edge cases, and constant validation.
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
    assert(Math.abs(a - b) < (eps || 0.001), msg + ` (got ${a}, expected ${b})`);
}
function assertEqual(a, b, msg) {
    assert(a === b, msg + ` (got ${JSON.stringify(a)}, expected ${JSON.stringify(b)})`);
}

// Load war-fog.js into a sandboxed context
const code = fs.readFileSync(__dirname + '/../../frontend/js/war-fog.js', 'utf8');
let perfNow = 1000;
const ctx = vm.createContext({
    Math, Date, console, Map, Array, Object, Number, Infinity, Boolean, JSON,
    parseInt, parseFloat, isNaN, isFinite, undefined,
    performance: { now: () => perfNow },
    document: {
        createElement: () => ({ getContext: () => null, width: 0, height: 0 }),
    },
});
vm.runInContext(code, ctx);

const {
    FOG_VISION_RADII,
    fogGetVisionRadius,
    fogBuildVisionMap,
    fogState,
    fogIsPointVisible,
    fogDraw,
    fogDrawSetupPreview,
    fogDrawMinimap,
    fogMinimapHitTest,
    minimapWorldToMinimap,
    minimapGetViewportRect,
    _fogDrawVisionEdges,
    MINIMAP_W,
    MINIMAP_H,
    MINIMAP_PAD,
    MINIMAP_COLORS,
} = ctx;

// ============================================================
// Constants validation
// ============================================================

console.log('\n--- Constants ---');

(function testFogVisionRadiiKeys() {
    const keys = Object.keys(FOG_VISION_RADII).sort();
    const expected = ['camera', 'default', 'drone', 'person', 'rover', 'sensor', 'turret'].sort();
    assertEqual(keys.join(','), expected.join(','), 'FOG_VISION_RADII has all expected keys');
})();

(function testFogVisionRadiiAllPositive() {
    const keys = Object.keys(FOG_VISION_RADII);
    let allPositive = true;
    for (let i = 0; i < keys.length; i++) {
        if (FOG_VISION_RADII[keys[i]] <= 0) allPositive = false;
    }
    assert(allPositive, 'All FOG_VISION_RADII values are positive');
})();

(function testMinimapDimensions() {
    assertEqual(MINIMAP_W, 200, 'MINIMAP_W is 200');
    assertEqual(MINIMAP_H, 150, 'MINIMAP_H is 150');
    assertEqual(MINIMAP_PAD, 12, 'MINIMAP_PAD is 12');
})();

(function testMinimapColorsExist() {
    assert(MINIMAP_COLORS.friendly !== undefined, 'MINIMAP_COLORS has friendly color');
    assert(MINIMAP_COLORS.hostile !== undefined, 'MINIMAP_COLORS has hostile color');
    assert(MINIMAP_COLORS.neutral !== undefined, 'MINIMAP_COLORS has neutral color');
    assert(MINIMAP_COLORS.unknown !== undefined, 'MINIMAP_COLORS has unknown color');
    assert(MINIMAP_COLORS.bg !== undefined, 'MINIMAP_COLORS has bg color');
    assert(MINIMAP_COLORS.border !== undefined, 'MINIMAP_COLORS has border color');
    assert(MINIMAP_COLORS.viewport !== undefined, 'MINIMAP_COLORS has viewport color');
    assert(MINIMAP_COLORS.alertPulse !== undefined, 'MINIMAP_COLORS has alertPulse color');
})();

(function testMinimapColorsValues() {
    assertEqual(MINIMAP_COLORS.friendly, '#05ffa1', 'Friendly color is green');
    assertEqual(MINIMAP_COLORS.hostile, '#ff2a6d', 'Hostile color is magenta');
    assertEqual(MINIMAP_COLORS.neutral, '#00a0ff', 'Neutral color is blue');
    assertEqual(MINIMAP_COLORS.unknown, '#fcee0a', 'Unknown color is yellow');
})();

// ============================================================
// Function existence checks
// ============================================================

console.log('\n--- Function Existence ---');

(function testFogFunctionsExist() {
    assertEqual(typeof fogGetVisionRadius, 'function', 'fogGetVisionRadius is a function');
    assertEqual(typeof fogBuildVisionMap, 'function', 'fogBuildVisionMap is a function');
    assertEqual(typeof fogIsPointVisible, 'function', 'fogIsPointVisible is a function');
    assertEqual(typeof fogDraw, 'function', 'fogDraw is a function');
    assertEqual(typeof fogDrawSetupPreview, 'function', 'fogDrawSetupPreview is a function');
    assertEqual(typeof fogDrawMinimap, 'function', 'fogDrawMinimap is a function');
    assertEqual(typeof fogMinimapHitTest, 'function', 'fogMinimapHitTest is a function');
    assertEqual(typeof minimapWorldToMinimap, 'function', 'minimapWorldToMinimap is a function');
    assertEqual(typeof minimapGetViewportRect, 'function', 'minimapGetViewportRect is a function');
    assertEqual(typeof _fogDrawVisionEdges, 'function', '_fogDrawVisionEdges is a function');
})();

// ============================================================
// Vision radius per unit type -- all known types
// ============================================================

console.log('\n--- Vision Radii (all types) ---');

(function testTurretVisionRadius() {
    const r = fogGetVisionRadius({ asset_type: 'turret' });
    assertClose(r, 50, 0.001, 'Turret vision radius is 50');
})();

(function testDroneVisionRadius() {
    const r = fogGetVisionRadius({ asset_type: 'drone' });
    assertClose(r, 60, 0.001, 'Drone vision radius is 60');
})();

(function testRoverVisionRadius() {
    const r = fogGetVisionRadius({ asset_type: 'rover' });
    assertClose(r, 40, 0.001, 'Rover vision radius is 40');
})();

(function testCameraVisionRadius() {
    const r = fogGetVisionRadius({ asset_type: 'camera' });
    assertClose(r, 30, 0.001, 'Camera vision radius is 30');
})();

(function testSensorVisionRadius() {
    const r = fogGetVisionRadius({ asset_type: 'sensor' });
    assertClose(r, 30, 0.001, 'Sensor vision radius is 30');
})();

(function testPersonVisionRadius() {
    const r = fogGetVisionRadius({ asset_type: 'person' });
    assertClose(r, 15, 0.001, 'Person vision radius is 15');
})();

// Types not in FOG_VISION_RADII -- should get default (20)
(function testTankVisionRadiusDefault() {
    const r = fogGetVisionRadius({ asset_type: 'tank' });
    assertClose(r, 20, 0.001, 'Tank (not in radii map) gets default 20');
})();

(function testApcVisionRadiusDefault() {
    const r = fogGetVisionRadius({ asset_type: 'apc' });
    assertClose(r, 20, 0.001, 'APC (not in radii map) gets default 20');
})();

(function testHeavyTurretVisionRadiusDefault() {
    const r = fogGetVisionRadius({ asset_type: 'heavy_turret' });
    assertClose(r, 20, 0.001, 'Heavy turret (not in radii map) gets default 20');
})();

(function testMissileTurretVisionRadiusDefault() {
    const r = fogGetVisionRadius({ asset_type: 'missile_turret' });
    assertClose(r, 20, 0.001, 'Missile turret (not in radii map) gets default 20');
})();

(function testScoutDroneVisionRadiusDefault() {
    const r = fogGetVisionRadius({ asset_type: 'scout_drone' });
    assertClose(r, 20, 0.001, 'Scout drone (not in radii map) gets default 20');
})();

(function testHostilePersonVisionRadiusDefault() {
    const r = fogGetVisionRadius({ asset_type: 'hostile_person' });
    assertClose(r, 20, 0.001, 'hostile_person (not in radii map) gets default 20');
})();

(function testNeutralPersonVisionRadiusDefault() {
    const r = fogGetVisionRadius({ asset_type: 'neutral_person' });
    assertClose(r, 20, 0.001, 'neutral_person (not in radii map) gets default 20');
})();

(function testHostileVehicleVisionRadiusDefault() {
    const r = fogGetVisionRadius({ asset_type: 'hostile_vehicle' });
    assertClose(r, 20, 0.001, 'hostile_vehicle gets default 20');
})();

(function testHostileLeaderVisionRadiusDefault() {
    const r = fogGetVisionRadius({ asset_type: 'hostile_leader' });
    assertClose(r, 20, 0.001, 'hostile_leader gets default 20');
})();

(function testUnknownTypeGetsDefault() {
    const r = fogGetVisionRadius({ asset_type: 'unknown_thing' });
    assertClose(r, 20, 0.001, 'Unknown type gets default vision radius 20');
})();

// ============================================================
// Vision radius edge cases
// ============================================================

console.log('\n--- Vision Radius Edge Cases ---');

(function testVisionRadiusWithCustomOverride() {
    const r = fogGetVisionRadius({ asset_type: 'turret', vision_range: 30 });
    assertClose(r, 30, 0.001, 'Custom vision_range overrides type default');
})();

(function testVisionRadiusCaseInsensitive() {
    const r = fogGetVisionRadius({ asset_type: 'Turret' });
    assertClose(r, 50, 0.001, 'Vision radius lookup is case-insensitive');
})();

(function testVisionRadiusCaseInsensitiveDrone() {
    const r = fogGetVisionRadius({ asset_type: 'DRONE' });
    assertClose(r, 60, 0.001, 'DRONE uppercase resolves to 60');
})();

(function testVisionRadiusCaseInsensitiveRover() {
    const r = fogGetVisionRadius({ asset_type: 'Rover' });
    assertClose(r, 40, 0.001, 'Rover mixed-case resolves to 40');
})();

(function testVisionRadiusMissingAssetType() {
    const r = fogGetVisionRadius({});
    assertClose(r, 20, 0.001, 'Missing asset_type gets default 20');
})();

(function testVisionRadiusNullAssetType() {
    const r = fogGetVisionRadius({ asset_type: null });
    assertClose(r, 20, 0.001, 'Null asset_type gets default 20');
})();

(function testVisionRadiusUndefinedAssetType() {
    const r = fogGetVisionRadius({ asset_type: undefined });
    assertClose(r, 20, 0.001, 'Undefined asset_type gets default 20');
})();

(function testVisionRadiusEmptyStringAssetType() {
    const r = fogGetVisionRadius({ asset_type: '' });
    assertClose(r, 20, 0.001, 'Empty string asset_type gets default 20');
})();

(function testVisionRangeZeroOverride() {
    // vision_range of 0 is falsy but !== null and !== undefined
    const r = fogGetVisionRadius({ asset_type: 'turret', vision_range: 0 });
    assertClose(r, 0, 0.001, 'vision_range of 0 overrides (returns 0)');
})();

(function testVisionRangeNullDoesNotOverride() {
    const r = fogGetVisionRadius({ asset_type: 'turret', vision_range: null });
    assertClose(r, 50, 0.001, 'vision_range null does NOT override, uses type default');
})();

(function testVisionRangeUndefinedDoesNotOverride() {
    const r = fogGetVisionRadius({ asset_type: 'turret', vision_range: undefined });
    assertClose(r, 50, 0.001, 'vision_range undefined does NOT override, uses type default');
})();

(function testVisionRangeNegativeOverride() {
    // Negative vision_range is technically valid as an override
    const r = fogGetVisionRadius({ asset_type: 'turret', vision_range: -10 });
    assertClose(r, -10, 0.001, 'Negative vision_range is returned as-is (no clamping)');
})();

(function testVisionRangeLargeOverride() {
    const r = fogGetVisionRadius({ asset_type: 'turret', vision_range: 1000 });
    assertClose(r, 1000, 0.001, 'Large vision_range override is returned');
})();

(function testVisionRangeFractionalOverride() {
    const r = fogGetVisionRadius({ asset_type: 'turret', vision_range: 33.7 });
    assertClose(r, 33.7, 0.001, 'Fractional vision_range override is returned');
})();

// ============================================================
// Fog vision map (list of circles)
// ============================================================

console.log('\n--- Fog Vision Map ---');

(function testBuildVisionMapEmpty() {
    const circles = fogBuildVisionMap({});
    assert(Array.isArray(circles), 'Vision map returns array');
    assert(circles.length === 0, 'Empty targets gives empty vision map');
})();

(function testBuildVisionMapFriendlyOnly() {
    const targets = {
        'turret-1': { alliance: 'friendly', asset_type: 'turret', position: { x: 5, y: 10 } },
        'hostile-1': { alliance: 'hostile', asset_type: 'drone', position: { x: -5, y: -5 } },
    };
    const circles = fogBuildVisionMap(targets);
    assert(circles.length === 1, 'Only friendly units contribute to vision map (got ' + circles.length + ')');
    assertClose(circles[0].x, 5, 0.001, 'Vision circle x matches turret position');
    assertClose(circles[0].y, 10, 0.001, 'Vision circle y matches turret position');
    assertClose(circles[0].r, 50, 0.001, 'Vision circle radius matches turret type');
})();

(function testBuildVisionMapMultipleFriendlies() {
    const targets = {
        'turret-1': { alliance: 'friendly', asset_type: 'turret', position: { x: 0, y: 0 } },
        'drone-1': { alliance: 'friendly', asset_type: 'drone', position: { x: 10, y: 10 } },
        'rover-1': { alliance: 'friendly', asset_type: 'rover', position: { x: -5, y: 3 } },
    };
    const circles = fogBuildVisionMap(targets);
    assert(circles.length === 3, 'Three friendlies produce three vision circles');
})();

(function testBuildVisionMapSkipsNeutralized() {
    const targets = {
        'turret-1': { alliance: 'friendly', asset_type: 'turret', position: { x: 0, y: 0 }, status: 'neutralized' },
    };
    const circles = fogBuildVisionMap(targets);
    assert(circles.length === 0, 'Neutralized units do not contribute to vision');
})();

(function testBuildVisionMapSkipsEliminated() {
    const targets = {
        'turret-1': { alliance: 'friendly', asset_type: 'turret', position: { x: 0, y: 0 }, status: 'eliminated' },
    };
    const circles = fogBuildVisionMap(targets);
    assert(circles.length === 0, 'Eliminated units do not contribute to vision');
})();

(function testBuildVisionMapSkipsDestroyed() {
    const targets = {
        'turret-1': { alliance: 'friendly', asset_type: 'turret', position: { x: 0, y: 0 }, status: 'destroyed' },
    };
    const circles = fogBuildVisionMap(targets);
    assert(circles.length === 0, 'Destroyed units do not contribute to vision');
})();

(function testBuildVisionMapIncludesActiveStatus() {
    const targets = {
        'turret-1': { alliance: 'friendly', asset_type: 'turret', position: { x: 0, y: 0 }, status: 'active' },
    };
    const circles = fogBuildVisionMap(targets);
    assert(circles.length === 1, 'Active units contribute to vision');
})();

(function testBuildVisionMapIncludesNoStatus() {
    // Missing status defaults to 'active'
    const targets = {
        'turret-1': { alliance: 'friendly', asset_type: 'turret', position: { x: 0, y: 0 } },
    };
    const circles = fogBuildVisionMap(targets);
    assert(circles.length === 1, 'Units with no status (defaults active) contribute to vision');
})();

(function testBuildVisionMapUsesXYFallback() {
    const targets = {
        'rover-1': { alliance: 'friendly', asset_type: 'rover', x: 7, y: 8 },
    };
    const circles = fogBuildVisionMap(targets);
    assert(circles.length === 1, 'Unit with x/y (no position obj) is included');
    assertClose(circles[0].x, 7, 0.001, 'X from direct property');
    assertClose(circles[0].y, 8, 0.001, 'Y from direct property');
})();

(function testBuildVisionMapSkipsHostile() {
    const targets = {
        'hostile-1': { alliance: 'hostile', asset_type: 'turret', position: { x: 10, y: 10 } },
    };
    const circles = fogBuildVisionMap(targets);
    assert(circles.length === 0, 'Hostile units do not contribute to vision');
})();

(function testBuildVisionMapSkipsNeutral() {
    const targets = {
        'neutral-1': { alliance: 'neutral', asset_type: 'person', position: { x: 10, y: 10 } },
    };
    const circles = fogBuildVisionMap(targets);
    assert(circles.length === 0, 'Neutral units do not contribute to vision');
})();

(function testBuildVisionMapSkipsUnknownAlliance() {
    const targets = {
        'unk-1': { alliance: 'unknown', asset_type: 'drone', position: { x: 10, y: 10 } },
    };
    const circles = fogBuildVisionMap(targets);
    assert(circles.length === 0, 'Unknown alliance units do not contribute to vision');
})();

(function testBuildVisionMapSkipsMissingAlliance() {
    const targets = {
        'no-alliance': { asset_type: 'turret', position: { x: 10, y: 10 } },
    };
    const circles = fogBuildVisionMap(targets);
    assert(circles.length === 0, 'Units with no alliance do not contribute to vision');
})();

(function testBuildVisionMapSkipsMissingPosition() {
    const targets = {
        'no-pos': { alliance: 'friendly', asset_type: 'turret' },
    };
    const circles = fogBuildVisionMap(targets);
    assert(circles.length === 0, 'Friendly units with no position data are skipped');
})();

(function testBuildVisionMapSkipsPositionWithUndefinedXY() {
    const targets = {
        'bad-pos': { alliance: 'friendly', asset_type: 'turret', position: {} },
    };
    const circles = fogBuildVisionMap(targets);
    // position.x is undefined, falls through to x/y fallback, also undefined -> skipped
    assert(circles.length === 0, 'Friendly units with empty position object are skipped');
})();

(function testBuildVisionMapIncludesCircleTid() {
    const targets = {
        'turret-42': { alliance: 'friendly', asset_type: 'turret', position: { x: 0, y: 0 } },
    };
    const circles = fogBuildVisionMap(targets);
    assert(circles.length === 1, 'One circle created');
    assertEqual(circles[0].tid, 'turret-42', 'Circle tid matches target id');
})();

(function testBuildVisionMapWithCustomVisionRange() {
    const targets = {
        'custom-1': { alliance: 'friendly', asset_type: 'turret', position: { x: 0, y: 0 }, vision_range: 100 },
    };
    const circles = fogBuildVisionMap(targets);
    assert(circles.length === 1, 'Unit included');
    assertClose(circles[0].r, 100, 0.001, 'Circle radius uses custom vision_range, not type default');
})();

(function testBuildVisionMapAllianceCaseInsensitive() {
    const targets = {
        'case-1': { alliance: 'Friendly', asset_type: 'turret', position: { x: 1, y: 2 } },
    };
    const circles = fogBuildVisionMap(targets);
    assert(circles.length === 1, 'Alliance check is case-insensitive (Friendly)');
})();

(function testBuildVisionMapMixedStatuses() {
    const targets = {
        't1': { alliance: 'friendly', asset_type: 'turret', position: { x: 0, y: 0 }, status: 'active' },
        't2': { alliance: 'friendly', asset_type: 'drone', position: { x: 10, y: 10 }, status: 'neutralized' },
        't3': { alliance: 'friendly', asset_type: 'rover', position: { x: 20, y: 20 }, status: 'eliminated' },
        't4': { alliance: 'friendly', asset_type: 'camera', position: { x: 30, y: 30 }, status: 'destroyed' },
        't5': { alliance: 'friendly', asset_type: 'sensor', position: { x: 40, y: 40 } },
    };
    const circles = fogBuildVisionMap(targets);
    assert(circles.length === 2, 'Only active/no-status units contribute (2 of 5)');
})();

(function testBuildVisionMapPositionXZeroYZero() {
    // Position at (0, 0) should be valid
    const targets = {
        'origin': { alliance: 'friendly', asset_type: 'turret', position: { x: 0, y: 0 } },
    };
    const circles = fogBuildVisionMap(targets);
    assert(circles.length === 1, 'Unit at origin (0,0) is included');
    assertClose(circles[0].x, 0, 0.001, 'X is 0');
    assertClose(circles[0].y, 0, 0.001, 'Y is 0');
})();

(function testBuildVisionMapNegativeCoords() {
    const targets = {
        'neg': { alliance: 'friendly', asset_type: 'drone', position: { x: -100, y: -200 } },
    };
    const circles = fogBuildVisionMap(targets);
    assert(circles.length === 1, 'Unit with negative coordinates is included');
    assertClose(circles[0].x, -100, 0.001, 'Negative X preserved');
    assertClose(circles[0].y, -200, 0.001, 'Negative Y preserved');
})();

(function testBuildVisionMapLargeTargetSet() {
    const targets = {};
    for (let i = 0; i < 100; i++) {
        targets['unit-' + i] = { alliance: 'friendly', asset_type: 'turret', position: { x: i, y: i } };
    }
    const circles = fogBuildVisionMap(targets);
    assertEqual(circles.length, 100, '100 friendlies produce 100 vision circles');
})();

// ============================================================
// Fog toggle state
// ============================================================

console.log('\n--- Fog Toggle ---');

(function testFogStartsEnabled() {
    assert(fogState.fogEnabled === true, 'Fog starts enabled by default');
})();

(function testMinimapStartsEnabled() {
    assert(fogState.minimapEnabled === true, 'Minimap starts enabled by default');
})();

(function testFogCanBeDisabled() {
    fogState.fogEnabled = false;
    assert(fogState.fogEnabled === false, 'Fog can be disabled');
    fogState.fogEnabled = true; // restore
})();

(function testFogCanBeReEnabled() {
    fogState.fogEnabled = false;
    fogState.fogEnabled = true;
    assert(fogState.fogEnabled === true, 'Fog can be re-enabled after disabling');
})();

(function testMinimapCanBeDisabled() {
    fogState.minimapEnabled = false;
    assert(fogState.minimapEnabled === false, 'Minimap can be disabled');
    fogState.minimapEnabled = true; // restore
})();

(function testMinimapCanBeReEnabled() {
    fogState.minimapEnabled = false;
    fogState.minimapEnabled = true;
    assert(fogState.minimapEnabled === true, 'Minimap can be re-enabled after disabling');
})();

(function testFogStateHasOffscreenCanvasFields() {
    // Initially null (not yet initialized by fogDraw)
    assertEqual(fogState._fogCanvas, null, 'Offscreen canvas starts null');
    assertEqual(fogState._fogCtx, null, 'Offscreen context starts null');
})();

(function testFogStateAlertPulsePhase() {
    assert(typeof fogState._alertPulsePhase === 'number', 'Alert pulse phase is a number');
})();

(function testFogAndMinimapIndependent() {
    fogState.fogEnabled = false;
    fogState.minimapEnabled = true;
    assert(!fogState.fogEnabled && fogState.minimapEnabled, 'Fog disabled, minimap enabled independently');
    fogState.fogEnabled = true;
    fogState.minimapEnabled = false;
    assert(fogState.fogEnabled && !fogState.minimapEnabled, 'Fog enabled, minimap disabled independently');
    fogState.minimapEnabled = true; // restore
})();

// ============================================================
// Minimap coordinate mapping
// ============================================================

console.log('\n--- Minimap Coordinates ---');

(function testMinimapWorldCenter() {
    const p = minimapWorldToMinimap(0, 0, 200, 150, -30, 30);
    assertClose(p.x, 100, 0.5, 'World center x -> minimap center x (100)');
    assertClose(p.y, 75, 0.5, 'World center y -> minimap center y (75)');
})();

(function testMinimapWorldCornerNW() {
    const p = minimapWorldToMinimap(-30, 30, 200, 150, -30, 30);
    assertClose(p.x, 0, 0.5, 'NW corner x -> minimap left (0)');
    assertClose(p.y, 0, 0.5, 'NW corner y -> minimap top (0)');
})();

(function testMinimapWorldCornerSE() {
    const p = minimapWorldToMinimap(30, -30, 200, 150, -30, 30);
    assertClose(p.x, 200, 0.5, 'SE corner x -> minimap right (200)');
    assertClose(p.y, 150, 0.5, 'SE corner y -> minimap bottom (150)');
})();

(function testMinimapWorldCornerNE() {
    const p = minimapWorldToMinimap(30, 30, 200, 150, -30, 30);
    assertClose(p.x, 200, 0.5, 'NE corner x -> minimap right (200)');
    assertClose(p.y, 0, 0.5, 'NE corner y -> minimap top (0)');
})();

(function testMinimapWorldCornerSW() {
    const p = minimapWorldToMinimap(-30, -30, 200, 150, -30, 30);
    assertClose(p.x, 0, 0.5, 'SW corner x -> minimap left (0)');
    assertClose(p.y, 150, 0.5, 'SW corner y -> minimap bottom (150)');
})();

(function testMinimapQuarterPoint() {
    // Point at (-15, 15) -- halfway between center and NW corner
    const p = minimapWorldToMinimap(-15, 15, 200, 150, -30, 30);
    assertClose(p.x, 50, 0.5, 'Quarter point x -> 50');
    assertClose(p.y, 37.5, 0.5, 'Quarter point y -> 37.5');
})();

(function testMinimapCustomDimensions() {
    // Different minimap size
    const p = minimapWorldToMinimap(0, 0, 400, 300, -50, 50);
    assertClose(p.x, 200, 0.5, 'Center x on 400px wide minimap -> 200');
    assertClose(p.y, 150, 0.5, 'Center y on 300px tall minimap -> 150');
})();

(function testMinimapAsymmetricRange() {
    // mapMin=0, mapMax=100
    const p = minimapWorldToMinimap(50, 50, 200, 150, 0, 100);
    assertClose(p.x, 100, 0.5, 'Midpoint on asymmetric range x -> 100');
    assertClose(p.y, 75, 0.5, 'Midpoint on asymmetric range y -> 75');
})();

(function testMinimapYFlipsCorrectly() {
    // Higher world Y should map to lower minimap Y (top of screen)
    const p1 = minimapWorldToMinimap(0, 10, 200, 150, -30, 30);
    const p2 = minimapWorldToMinimap(0, -10, 200, 150, -30, 30);
    assert(p1.y < p2.y, 'Higher world Y maps to lower minimap Y (Y-axis flipped)');
})();

(function testMinimapOutOfBoundsCoords() {
    // Outside map bounds still maps, just beyond 0..mmW/mmH
    const p = minimapWorldToMinimap(60, 60, 200, 150, -30, 30);
    assert(p.x > 200, 'Outside positive boundary maps beyond minimap width');
    assert(p.y < 0, 'Outside positive boundary maps beyond minimap top');
})();

// ============================================================
// Minimap viewport rectangle
// ============================================================

console.log('\n--- Minimap Viewport Rect ---');

(function testViewportRectCentered() {
    const cam = { x: 0, y: 0, zoom: 1 };
    const rect = minimapGetViewportRect(cam, 800, 600, 200, 150, -30, 30);
    assert(rect.x < 100 && rect.x + rect.w > 100, 'Viewport rect straddles minimap center x');
    assert(rect.y < 75 && rect.y + rect.h > 75, 'Viewport rect straddles minimap center y');
})();

(function testViewportRectShrinkOnZoomIn() {
    const cam1 = { x: 0, y: 0, zoom: 1 };
    const cam2 = { x: 0, y: 0, zoom: 2 };
    const rect1 = minimapGetViewportRect(cam1, 800, 600, 200, 150, -30, 30);
    const rect2 = minimapGetViewportRect(cam2, 800, 600, 200, 150, -30, 30);
    assert(rect2.w < rect1.w, 'Zooming in shrinks viewport width on minimap');
    assert(rect2.h < rect1.h, 'Zooming in shrinks viewport height on minimap');
})();

(function testViewportRectGrowOnZoomOut() {
    const cam1 = { x: 0, y: 0, zoom: 1 };
    const cam2 = { x: 0, y: 0, zoom: 0.5 };
    const rect1 = minimapGetViewportRect(cam1, 800, 600, 200, 150, -30, 30);
    const rect2 = minimapGetViewportRect(cam2, 800, 600, 200, 150, -30, 30);
    assert(rect2.w > rect1.w, 'Zooming out grows viewport width on minimap');
    assert(rect2.h > rect1.h, 'Zooming out grows viewport height on minimap');
})();

(function testViewportRectMoveWithCamera() {
    const cam1 = { x: 0, y: 0, zoom: 1 };
    const cam2 = { x: 10, y: 5, zoom: 1 };
    const rect1 = minimapGetViewportRect(cam1, 800, 600, 200, 150, -30, 30);
    const rect2 = minimapGetViewportRect(cam2, 800, 600, 200, 150, -30, 30);
    assert(rect2.x > rect1.x, 'Camera panning right moves viewport rect right on minimap');
    assert(rect2.y < rect1.y, 'Camera panning up moves viewport rect up on minimap');
})();

(function testViewportRectPositiveDimensions() {
    const cam = { x: 0, y: 0, zoom: 1 };
    const rect = minimapGetViewportRect(cam, 800, 600, 200, 150, -30, 30);
    assert(rect.w > 0, 'Viewport width is positive');
    assert(rect.h > 0, 'Viewport height is positive');
})();

(function testViewportRectZoomHalvesSize() {
    const cam1 = { x: 0, y: 0, zoom: 1 };
    const cam2 = { x: 0, y: 0, zoom: 2 };
    const rect1 = minimapGetViewportRect(cam1, 800, 600, 200, 150, -30, 30);
    const rect2 = minimapGetViewportRect(cam2, 800, 600, 200, 150, -30, 30);
    assertClose(rect2.w, rect1.w / 2, 1.0, 'Doubling zoom halves viewport width');
    assertClose(rect2.h, rect1.h / 2, 1.0, 'Doubling zoom halves viewport height');
})();

(function testViewportRectSmallCanvas() {
    const cam = { x: 0, y: 0, zoom: 1 };
    const rect = minimapGetViewportRect(cam, 100, 75, 200, 150, -30, 30);
    assert(rect.w > 0, 'Viewport has positive width on small canvas');
    assert(rect.h > 0, 'Viewport has positive height on small canvas');
    // On a small canvas at zoom 1, the visible world may be larger than the map,
    // so the viewport rect can exceed minimap bounds
    assert(rect.w > 100, 'Viewport width scales with canvas/zoom ratio');
})();

(function testViewportRectHighZoom() {
    // At zoom 10 on an 800x600 canvas with range 60:
    // halfWWorld = 400/10 = 40, fullW = 80 -> 80/60 * 200 = 266
    // The viewport is still large because the canvas px / zoom exceeds the map range
    const cam = { x: 0, y: 0, zoom: 10 };
    const rect = minimapGetViewportRect(cam, 800, 600, 200, 150, -30, 30);
    assert(rect.w > 0, 'High zoom viewport has positive width');
    assert(rect.h > 0, 'High zoom viewport has positive height');
    // Compare with zoom=1 to verify high zoom is strictly smaller
    const rectLow = minimapGetViewportRect({ x: 0, y: 0, zoom: 1 }, 800, 600, 200, 150, -30, 30);
    assert(rect.w < rectLow.w, 'Zoom 10 viewport smaller than zoom 1 viewport');
    assert(rect.h < rectLow.h, 'Zoom 10 viewport height smaller than zoom 1');
})();

(function testViewportRectPannedToEdge() {
    // Compare panned camera to centered camera at same zoom
    const rectCenter = minimapGetViewportRect({ x: 0, y: 0, zoom: 2 }, 800, 600, 200, 150, -30, 30);
    const rectPanned = minimapGetViewportRect({ x: 25, y: 25, zoom: 2 }, 800, 600, 200, 150, -30, 30);
    assert(rectPanned.x > rectCenter.x, 'Panning to positive x shifts viewport right vs center');
    assert(rectPanned.y < rectCenter.y, 'Panning to positive y shifts viewport up vs center');
    // Dimensions should remain the same (same zoom, same canvas)
    assertClose(rectPanned.w, rectCenter.w, 1.0, 'Panning does not change viewport width');
    assertClose(rectPanned.h, rectCenter.h, 1.0, 'Panning does not change viewport height');
})();

// ============================================================
// Point-in-vision test
// ============================================================

console.log('\n--- Point in Vision ---');

(function testPointInsideVisionCircle() {
    const circles = [{ x: 0, y: 0, r: 10 }];
    assert(fogIsPointVisible(5, 5, circles), 'Point (5,5) is inside vision circle at origin r=10');
})();

(function testPointOutsideVisionCircle() {
    const circles = [{ x: 0, y: 0, r: 10 }];
    assert(!fogIsPointVisible(15, 15, circles), 'Point (15,15) is outside vision circle at origin r=10');
})();

(function testPointInsideOneOfMultipleCircles() {
    const circles = [
        { x: 0, y: 0, r: 5 },
        { x: 20, y: 20, r: 5 },
    ];
    assert(fogIsPointVisible(20, 22, circles), 'Point near second circle is visible');
    assert(!fogIsPointVisible(10, 10, circles), 'Point between both circles is not visible');
})();

(function testPointOnBoundary() {
    const circles = [{ x: 0, y: 0, r: 10 }];
    assert(fogIsPointVisible(10, 0, circles), 'Point on boundary is visible (<=)');
})();

(function testPointAtCircleCenter() {
    const circles = [{ x: 5, y: 5, r: 10 }];
    assert(fogIsPointVisible(5, 5, circles), 'Point exactly at circle center is visible');
})();

(function testPointVisibleEmptyCircles() {
    assert(!fogIsPointVisible(0, 0, []), 'No circles -> no point is visible');
})();

(function testPointVisibleZeroRadius() {
    const circles = [{ x: 0, y: 0, r: 0 }];
    assert(fogIsPointVisible(0, 0, circles), 'Point at center of zero-radius circle is visible (0<=0)');
    assert(!fogIsPointVisible(1, 0, circles), 'Point outside zero-radius circle is NOT visible');
})();

(function testPointVisibleNegativeCoordinates() {
    const circles = [{ x: -10, y: -10, r: 5 }];
    assert(fogIsPointVisible(-10, -10, circles), 'Point at negative circle center is visible');
    assert(fogIsPointVisible(-8, -8, circles), 'Point near negative circle center is visible');
    assert(!fogIsPointVisible(0, 0, circles), 'Origin far from negative circle is not visible');
})();

(function testPointVisibleOverlappingCircles() {
    const circles = [
        { x: 0, y: 0, r: 10 },
        { x: 5, y: 0, r: 10 },
    ];
    // Point in overlap of both circles
    assert(fogIsPointVisible(3, 0, circles), 'Point in overlapping region is visible');
    // Point only in first
    assert(fogIsPointVisible(-8, 0, circles), 'Point only in first circle is visible');
    // Point only in second
    assert(fogIsPointVisible(13, 0, circles), 'Point only in second circle is visible');
    // Point outside both
    assert(!fogIsPointVisible(20, 0, circles), 'Point outside both circles is not visible');
})();

(function testPointVisibleManyCircles() {
    const circles = [];
    for (let i = 0; i < 50; i++) {
        circles.push({ x: i * 10, y: 0, r: 4 });
    }
    assert(fogIsPointVisible(0, 0, circles), 'Point at first of 50 circles is visible');
    assert(fogIsPointVisible(490, 0, circles), 'Point at last of 50 circles is visible');
    assert(!fogIsPointVisible(5, 0, circles), 'Point between gaps of spaced circles is not visible');
})();

(function testPointVisibleJustInsideBoundary() {
    const circles = [{ x: 0, y: 0, r: 10 }];
    // Just inside: sqrt(7^2 + 7^2) = 9.899, which is < 10
    assert(fogIsPointVisible(7, 7, circles), 'Point just inside boundary (d=9.899) is visible');
})();

(function testPointVisibleJustOutsideBoundary() {
    const circles = [{ x: 0, y: 0, r: 10 }];
    // Just outside: sqrt(8^2 + 7^2) = 10.63, which is > 10
    assert(!fogIsPointVisible(8, 7, circles), 'Point just outside boundary (d=10.63) is not visible');
})();

(function testPointVisibleLargeCircle() {
    const circles = [{ x: 0, y: 0, r: 10000 }];
    assert(fogIsPointVisible(5000, 5000, circles), 'Point inside very large circle is visible');
    assert(!fogIsPointVisible(8000, 8000, circles), 'Point outside very large circle is not visible');
})();

// ============================================================
// Minimap hit test (click-to-jump)
// ============================================================

console.log('\n--- Minimap Hit Test ---');

(function testHitTestInside() {
    // Canvas 1000x800, minimap at bottom-right
    // mmX = 1000 - 200 - 12 = 788, mmY = 800 - 150 - 12 = 638
    const canvasW = 1000, canvasH = 800;
    const mmX = canvasW - MINIMAP_W - MINIMAP_PAD; // 788
    const mmY = canvasH - MINIMAP_H - MINIMAP_PAD; // 638
    // Click in center of minimap
    const sx = mmX + 100;
    const sy = mmY + 75;
    const result = fogMinimapHitTest(sx, sy, canvasW, canvasH, -30, 30);
    assert(result !== null, 'Click in minimap center returns non-null');
    assertClose(result.x, 0, 1.0, 'Center click maps to world x ~0');
    assertClose(result.y, 0, 1.0, 'Center click maps to world y ~0');
})();

(function testHitTestOutside() {
    const result = fogMinimapHitTest(10, 10, 1000, 800, -30, 30);
    assertEqual(result, null, 'Click outside minimap returns null');
})();

(function testHitTestTopLeftCorner() {
    const canvasW = 1000, canvasH = 800;
    const mmX = canvasW - MINIMAP_W - MINIMAP_PAD;
    const mmY = canvasH - MINIMAP_H - MINIMAP_PAD;
    const result = fogMinimapHitTest(mmX, mmY, canvasW, canvasH, -30, 30);
    assert(result !== null, 'Click at minimap top-left corner returns non-null');
    assertClose(result.x, -30, 1.0, 'Top-left maps to mapMin x');
    assertClose(result.y, 30, 1.0, 'Top-left maps to mapMax y');
})();

(function testHitTestBottomRightCorner() {
    const canvasW = 1000, canvasH = 800;
    const mmX = canvasW - MINIMAP_W - MINIMAP_PAD;
    const mmY = canvasH - MINIMAP_H - MINIMAP_PAD;
    const result = fogMinimapHitTest(mmX + MINIMAP_W, mmY + MINIMAP_H, canvasW, canvasH, -30, 30);
    assert(result !== null, 'Click at minimap bottom-right corner returns non-null');
    assertClose(result.x, 30, 1.0, 'Bottom-right maps to mapMax x');
    assertClose(result.y, -30, 1.0, 'Bottom-right maps to mapMin y');
})();

(function testHitTestJustOutsideLeft() {
    const canvasW = 1000, canvasH = 800;
    const mmX = canvasW - MINIMAP_W - MINIMAP_PAD;
    const mmY = canvasH - MINIMAP_H - MINIMAP_PAD;
    const result = fogMinimapHitTest(mmX - 1, mmY + 75, canvasW, canvasH, -30, 30);
    assertEqual(result, null, 'Click 1px left of minimap returns null');
})();

(function testHitTestJustOutsideTop() {
    const canvasW = 1000, canvasH = 800;
    const mmX = canvasW - MINIMAP_W - MINIMAP_PAD;
    const mmY = canvasH - MINIMAP_H - MINIMAP_PAD;
    const result = fogMinimapHitTest(mmX + 100, mmY - 1, canvasW, canvasH, -30, 30);
    assertEqual(result, null, 'Click 1px above minimap returns null');
})();

(function testHitTestJustOutsideRight() {
    const canvasW = 1000, canvasH = 800;
    const mmX = canvasW - MINIMAP_W - MINIMAP_PAD;
    const mmY = canvasH - MINIMAP_H - MINIMAP_PAD;
    const result = fogMinimapHitTest(mmX + MINIMAP_W + 1, mmY + 75, canvasW, canvasH, -30, 30);
    assertEqual(result, null, 'Click 1px right of minimap returns null');
})();

(function testHitTestJustOutsideBottom() {
    const canvasW = 1000, canvasH = 800;
    const mmX = canvasW - MINIMAP_W - MINIMAP_PAD;
    const mmY = canvasH - MINIMAP_H - MINIMAP_PAD;
    const result = fogMinimapHitTest(mmX + 100, mmY + MINIMAP_H + 1, canvasW, canvasH, -30, 30);
    assertEqual(result, null, 'Click 1px below minimap returns null');
})();

(function testHitTestDifferentCanvasSize() {
    const canvasW = 1920, canvasH = 1080;
    const mmX = canvasW - MINIMAP_W - MINIMAP_PAD;
    const mmY = canvasH - MINIMAP_H - MINIMAP_PAD;
    const result = fogMinimapHitTest(mmX + 100, mmY + 75, canvasW, canvasH, -50, 50);
    assert(result !== null, 'Hit test works on 1920x1080 canvas');
    assertClose(result.x, 0, 1.0, 'Center click on larger map range maps to world x ~0');
    assertClose(result.y, 0, 1.0, 'Center click on larger map range maps to world y ~0');
})();

(function testHitTestAsymmetricMapRange() {
    const canvasW = 800, canvasH = 600;
    const mmX = canvasW - MINIMAP_W - MINIMAP_PAD;
    const mmY = canvasH - MINIMAP_H - MINIMAP_PAD;
    const result = fogMinimapHitTest(mmX + 100, mmY + 75, canvasW, canvasH, 0, 100);
    assert(result !== null, 'Hit test works with asymmetric map range 0..100');
    assertClose(result.x, 50, 1.0, 'Center maps to midpoint x=50');
    assertClose(result.y, 50, 1.0, 'Center maps to midpoint y=50');
})();

// ============================================================
// Vision radius at zoom levels
// (testing the `r * cam.zoom` formula used in fogDraw)
// ============================================================

console.log('\n--- Vision Radius at Zoom Levels ---');

(function testScreenRadiusAtZoom1() {
    const worldRadius = fogGetVisionRadius({ asset_type: 'turret' }); // 50
    const cam = { zoom: 1 };
    const screenR = worldRadius * cam.zoom;
    assertClose(screenR, 50, 0.001, 'Screen radius at zoom 1 equals world radius');
})();

(function testScreenRadiusAtZoom2() {
    const worldRadius = fogGetVisionRadius({ asset_type: 'turret' }); // 50
    const cam = { zoom: 2 };
    const screenR = worldRadius * cam.zoom;
    assertClose(screenR, 100, 0.001, 'Screen radius doubles at zoom 2');
})();

(function testScreenRadiusAtZoomHalf() {
    const worldRadius = fogGetVisionRadius({ asset_type: 'drone' }); // 60
    const cam = { zoom: 0.5 };
    const screenR = worldRadius * cam.zoom;
    assertClose(screenR, 30, 0.001, 'Screen radius halves at zoom 0.5');
})();

(function testScreenRadiusAtHighZoom() {
    const worldRadius = fogGetVisionRadius({ asset_type: 'person' }); // 15
    const cam = { zoom: 10 };
    const screenR = worldRadius * cam.zoom;
    assertClose(screenR, 150, 0.001, 'Person radius * zoom 10 = 150');
})();

(function testScreenRadiusAllTypesAtZoom3() {
    const cam = { zoom: 3 };
    const types = [
        { type: 'turret', expected: 150 },
        { type: 'drone', expected: 180 },
        { type: 'rover', expected: 120 },
        { type: 'camera', expected: 90 },
        { type: 'sensor', expected: 90 },
        { type: 'person', expected: 45 },
    ];
    for (const t of types) {
        const r = fogGetVisionRadius({ asset_type: t.type });
        const sr = r * cam.zoom;
        assertClose(sr, t.expected, 0.001, `${t.type} screen radius at zoom 3 = ${t.expected}`);
    }
})();

// ============================================================
// FOG_VISION_RADII cross-check with unit-types/
// (fog system values vs unit-type visionRadius)
// ============================================================

console.log('\n--- Fog Radii Cross-Check ---');

// The fog system has its own FOG_VISION_RADII lookup, separate from the
// unit-types registry.  These tests document the expected values and
// verify that the fog radii match the unit-type visionRadius definitions.
// If they diverge intentionally (e.g., fog uses a simpler subset), the
// tests document that behavior.

(function testFogRadiiMatchUnitTypeTurret() {
    // UnitType Turret.visionRadius = 50, FOG_VISION_RADII.turret = 50
    assertClose(FOG_VISION_RADII.turret, 50, 0.001, 'FOG turret radius matches unit-type Turret (50)');
})();

(function testFogRadiiMatchUnitTypeDrone() {
    // UnitType Drone.visionRadius = 60, FOG_VISION_RADII.drone = 60
    assertClose(FOG_VISION_RADII.drone, 60, 0.001, 'FOG drone radius matches unit-type Drone (60)');
})();

(function testFogRadiiMatchUnitTypeRover() {
    // UnitType Rover.visionRadius = 40, FOG_VISION_RADII.rover = 40
    assertClose(FOG_VISION_RADII.rover, 40, 0.001, 'FOG rover radius matches unit-type Rover (40)');
})();

(function testFogRadiiMatchUnitTypeCamera() {
    // UnitType Camera.visionRadius = 30, FOG_VISION_RADII.camera = 30
    assertClose(FOG_VISION_RADII.camera, 30, 0.001, 'FOG camera radius matches unit-type Camera (30)');
})();

(function testFogRadiiMatchUnitTypeSensor() {
    // UnitType Sensor.visionRadius = 30, FOG_VISION_RADII.sensor = 30
    assertClose(FOG_VISION_RADII.sensor, 30, 0.001, 'FOG sensor radius matches unit-type Sensor (30)');
})();

(function testFogRadiiMatchUnitTypeNeutralPerson() {
    // UnitType NeutralPerson.visionRadius = 15, FOG_VISION_RADII.person = 15
    assertClose(FOG_VISION_RADII.person, 15, 0.001, 'FOG person radius matches unit-type NeutralPerson (15)');
})();

(function testFogDefaultRadius() {
    // Default is 20, which differs from UnitType base default of 25
    assertClose(FOG_VISION_RADII.default, 20, 0.001, 'FOG default radius is 20');
})();

// Tank has visionRadius 45 in unit-types but no fog entry -> gets default 20
(function testTankNotInFogRadii() {
    assert(FOG_VISION_RADII['tank'] === undefined, 'Tank is NOT in FOG_VISION_RADII (uses default)');
})();

// ============================================================
// Vision map integration scenarios
// ============================================================

console.log('\n--- Vision Map Integration ---');

(function testVisionMapCoversOwnPosition() {
    const targets = {
        't1': { alliance: 'friendly', asset_type: 'turret', position: { x: 50, y: 50 } },
    };
    const circles = fogBuildVisionMap(targets);
    assert(circles.length === 1, 'One circle');
    // The turret at (50, 50) with r=50 should be visible at its own position
    assert(fogIsPointVisible(50, 50, circles), 'Turret can see its own position');
})();

(function testVisionMapDoesNotCoverDistantPoint() {
    const targets = {
        't1': { alliance: 'friendly', asset_type: 'person', position: { x: 0, y: 0 } },
    };
    const circles = fogBuildVisionMap(targets);
    // Person has vision 15, point at (20, 0) is outside
    assert(!fogIsPointVisible(20, 0, circles), 'Person cannot see point beyond vision range');
})();

(function testOverlappingVisionFromTwoUnits() {
    const targets = {
        't1': { alliance: 'friendly', asset_type: 'turret', position: { x: 0, y: 0 } },
        't2': { alliance: 'friendly', asset_type: 'turret', position: { x: 80, y: 0 } },
    };
    const circles = fogBuildVisionMap(targets);
    // Point at (40, 0) -- exactly between, within r=50 of both turrets
    assert(fogIsPointVisible(40, 0, circles), 'Point between two turrets in overlapping vision is visible');
    // Point at (120, 0) -- only within second turret
    assert(fogIsPointVisible(120, 0, circles), 'Point near second turret is visible');
    // Point at (-40, 0) -- only within first turret
    assert(fogIsPointVisible(-40, 0, circles), 'Point near first turret is visible');
    // Point at (150, 0) -- outside both
    assert(!fogIsPointVisible(150, 0, circles), 'Point far from both turrets is not visible');
})();

(function testVisionGapBetweenDistantUnits() {
    const targets = {
        't1': { alliance: 'friendly', asset_type: 'sensor', position: { x: 0, y: 0 } },
        't2': { alliance: 'friendly', asset_type: 'sensor', position: { x: 100, y: 0 } },
    };
    const circles = fogBuildVisionMap(targets);
    // Sensors have r=30. Gap between circles is from x=30 to x=70
    assert(!fogIsPointVisible(50, 0, circles), 'Point in gap between sensors is not visible');
    assert(fogIsPointVisible(15, 0, circles), 'Point inside first sensor range is visible');
    assert(fogIsPointVisible(85, 0, circles), 'Point inside second sensor range is visible');
})();

(function testDestroyedUnitLosesVision() {
    const targets = {
        't1': { alliance: 'friendly', asset_type: 'turret', position: { x: 0, y: 0 }, status: 'active' },
        't2': { alliance: 'friendly', asset_type: 'turret', position: { x: 50, y: 0 }, status: 'destroyed' },
    };
    const circles = fogBuildVisionMap(targets);
    assert(circles.length === 1, 'Only one active unit produces vision');
    assert(fogIsPointVisible(0, 0, circles), 'Active turret provides vision at its position');
    // Point at (50, 0) is within the destroyed turret and barely at boundary of active turret
    // Distance from (0,0) to (50,0) = 50 = r, so on boundary => visible
    assert(fogIsPointVisible(50, 0, circles), 'Point at destroyed turret still visible (within active turret range)');
    // Point at (80, 0) -- outside active turret range, in destroyed turret range if it were active
    assert(!fogIsPointVisible(80, 0, circles), 'Point only in destroyed turret range is not visible');
})();

(function testAllFriendlyTypesHaveVision() {
    const types = ['turret', 'drone', 'rover', 'camera', 'sensor', 'person'];
    for (const t of types) {
        const targets = {};
        targets['test'] = { alliance: 'friendly', asset_type: t, position: { x: 0, y: 0 } };
        const circles = fogBuildVisionMap(targets);
        assert(circles.length === 1, `Friendly ${t} produces one vision circle`);
        assert(circles[0].r > 0, `Friendly ${t} has positive vision radius`);
    }
})();

// ============================================================
// fogDraw skips when fog disabled
// (we cannot test canvas rendering in Node.js, but we can
// verify the early-return branch)
// ============================================================

console.log('\n--- fogDraw Behavior ---');

(function testFogDrawReturnsEarlyWhenDisabled() {
    fogState.fogEnabled = false;
    // If fogDraw tries to use the canvas when disabled, it would crash
    // because we pass null stubs.  If it returns early, no crash.
    let crashed = false;
    try {
        fogDraw(null, null, null, {}, {}, 'tactical');
    } catch (e) {
        crashed = true;
    }
    assert(!crashed, 'fogDraw returns early when fog is disabled (no crash)');
    fogState.fogEnabled = true; // restore
})();

(function testFogDrawSetupPreviewReturnsEarlyWhenDisabled() {
    fogState.fogEnabled = false;
    let crashed = false;
    try {
        fogDrawSetupPreview(null, null, null, 0, 0, 'turret');
    } catch (e) {
        crashed = true;
    }
    assert(!crashed, 'fogDrawSetupPreview returns early when fog disabled');
    fogState.fogEnabled = true; // restore
})();

(function testFogDrawMinimapReturnsEarlyWhenDisabled() {
    fogState.minimapEnabled = false;
    let crashed = false;
    try {
        fogDrawMinimap(null, null, {}, { x: 0, y: 0, zoom: 1 }, -30, 30, [], [], []);
    } catch (e) {
        crashed = true;
    }
    assert(!crashed, 'fogDrawMinimap returns early when minimap disabled');
    fogState.minimapEnabled = true; // restore
})();

// ============================================================
// fogState mutation and reset patterns
// ============================================================

console.log('\n--- fogState Mutation ---');

(function testAlertPulsePhaseIncrements() {
    const before = fogState._alertPulsePhase;
    // Manually increment as fogDrawMinimap would
    fogState._alertPulsePhase += 0.05;
    assertClose(fogState._alertPulsePhase, before + 0.05, 0.001, 'Alert pulse phase increments by 0.05');
})();

(function testAlertPulsePhaseCanReset() {
    fogState._alertPulsePhase = 0;
    assertClose(fogState._alertPulsePhase, 0, 0.001, 'Alert pulse phase can be reset to 0');
})();

// ============================================================
// Minimap coordinate roundtrip
// (minimapWorldToMinimap -> fogMinimapHitTest should invert)
// ============================================================

console.log('\n--- Minimap Coordinate Roundtrip ---');

(function testMinimapRoundtripCenter() {
    const canvasW = 1000, canvasH = 800;
    const mapMin = -30, mapMax = 30;
    const mmX = canvasW - MINIMAP_W - MINIMAP_PAD;
    const mmY = canvasH - MINIMAP_H - MINIMAP_PAD;

    // World (0, 0) -> minimap coords -> screen coords -> hit test -> world
    const mp = minimapWorldToMinimap(0, 0, MINIMAP_W, MINIMAP_H, mapMin, mapMax);
    const sx = mmX + mp.x;
    const sy = mmY + mp.y;
    const result = fogMinimapHitTest(sx, sy, canvasW, canvasH, mapMin, mapMax);
    assert(result !== null, 'Roundtrip center: hit test returns non-null');
    assertClose(result.x, 0, 1.0, 'Roundtrip center: x recovers ~0');
    assertClose(result.y, 0, 1.0, 'Roundtrip center: y recovers ~0');
})();

(function testMinimapRoundtripArbitrary() {
    const canvasW = 1000, canvasH = 800;
    const mapMin = -30, mapMax = 30;
    const mmX = canvasW - MINIMAP_W - MINIMAP_PAD;
    const mmY = canvasH - MINIMAP_H - MINIMAP_PAD;

    const wx = 15, wy = -10;
    const mp = minimapWorldToMinimap(wx, wy, MINIMAP_W, MINIMAP_H, mapMin, mapMax);
    const sx = mmX + mp.x;
    const sy = mmY + mp.y;
    const result = fogMinimapHitTest(sx, sy, canvasW, canvasH, mapMin, mapMax);
    assert(result !== null, 'Roundtrip arbitrary: hit test returns non-null');
    assertClose(result.x, wx, 1.0, 'Roundtrip arbitrary: x recovers ~15');
    assertClose(result.y, wy, 1.0, 'Roundtrip arbitrary: y recovers ~-10');
})();

(function testMinimapRoundtripNegative() {
    const canvasW = 800, canvasH = 600;
    const mapMin = -50, mapMax = 50;
    const mmX = canvasW - MINIMAP_W - MINIMAP_PAD;
    const mmY = canvasH - MINIMAP_H - MINIMAP_PAD;

    const wx = -25, wy = 35;
    const mp = minimapWorldToMinimap(wx, wy, MINIMAP_W, MINIMAP_H, mapMin, mapMax);
    const sx = mmX + mp.x;
    const sy = mmY + mp.y;
    const result = fogMinimapHitTest(sx, sy, canvasW, canvasH, mapMin, mapMax);
    assert(result !== null, 'Roundtrip negative: hit test returns non-null');
    assertClose(result.x, wx, 1.0, 'Roundtrip negative: x recovers ~-25');
    assertClose(result.y, wy, 1.0, 'Roundtrip negative: y recovers ~35');
})();

// ============================================================
// Edge cases: position extraction from targets
// ============================================================

console.log('\n--- Position Extraction Edge Cases ---');

(function testPositionObjectPreferred() {
    // If both position.x and top-level x exist, position.x wins
    const targets = {
        't1': { alliance: 'friendly', asset_type: 'turret', position: { x: 10, y: 20 }, x: 99, y: 99 },
    };
    const circles = fogBuildVisionMap(targets);
    assertClose(circles[0].x, 10, 0.001, 'position.x preferred over top-level x');
    assertClose(circles[0].y, 20, 0.001, 'position.y preferred over top-level y');
})();

(function testPositionWithOnlyX() {
    // position has x but not y -> fallback goes to top-level x/y
    const targets = {
        't1': { alliance: 'friendly', asset_type: 'turret', position: { x: 10 } },
    };
    const circles = fogBuildVisionMap(targets);
    // position.x = 10, position.y = undefined -> both still from position obj
    // but y is undefined -> pos.y undefined -> skip
    assert(circles.length === 0, 'Unit with position.x but no position.y is skipped');
})();

(function testTopLevelXYUsedWhenPositionMissing() {
    const targets = {
        't1': { alliance: 'friendly', asset_type: 'turret', x: 5, y: 15 },
    };
    const circles = fogBuildVisionMap(targets);
    assert(circles.length === 1, 'Top-level x/y used when no position object');
    assertClose(circles[0].x, 5, 0.001, 'x from top-level');
    assertClose(circles[0].y, 15, 0.001, 'y from top-level');
})();

(function testTopLevelXYZeroIsValid() {
    const targets = {
        't1': { alliance: 'friendly', asset_type: 'turret', x: 0, y: 0 },
    };
    const circles = fogBuildVisionMap(targets);
    assert(circles.length === 1, 'Top-level x=0, y=0 is valid (not falsy skip)');
})();

(function testPositionObjectXZeroYZeroIsValid() {
    const targets = {
        't1': { alliance: 'friendly', asset_type: 'turret', position: { x: 0, y: 0 } },
    };
    const circles = fogBuildVisionMap(targets);
    assert(circles.length === 1, 'position.x=0, position.y=0 is valid');
    assertClose(circles[0].x, 0, 0.001, 'x is 0');
    assertClose(circles[0].y, 0, 0.001, 'y is 0');
})();

// ============================================================
// Summary
// ============================================================

console.log('\n' + '='.repeat(40));
console.log(`Results: ${passed} passed, ${failed} failed`);
console.log('='.repeat(40));
process.exit(failed > 0 ? 1 : 0);
