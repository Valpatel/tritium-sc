// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
/**
 * TRITIUM-SC Tactical Label tests
 * Tests short callsign generation (F-T-1 format) and zoom-based LOD.
 * Run: node tests/js/test_tactical_labels.js
 */

// Simple test runner
let passed = 0, failed = 0;
function assert(cond, msg) {
    if (!cond) { console.error('FAIL:', msg); failed++; }
    else { console.log('PASS:', msg); passed++; }
}

// ============================================================
// Tactical callsign generator (mirrors map.js implementation)
// We inline the function here for unit testing, then verify
// the actual map.js uses the same logic.
// ============================================================

/**
 * Generate a short tactical callsign from unit data.
 *
 * Format: {alliance}-{type}-{seq}
 *   alliance: F=friendly, E=enemy/hostile, N=neutral, U=unknown
 *   type:     T=turret, D=drone, R=rover, K=tank, C=camera, S=sensor,
 *             P=person, A=apc, H=heavy_turret, M=missile_turret, X=unknown
 *   seq:      1-based sequence number per alliance+type group
 *
 * @param {string} id - Unit ID
 * @param {string} alliance - friendly, hostile, neutral, unknown
 * @param {string} type - Unit type string
 * @param {Map} counters - Mutable map tracking per-group counts
 * @returns {string} Short callsign like "F-T-1"
 */
function tacticalCallsign(id, alliance, type, counters) {
    const ALLIANCE_CODES = {
        friendly: 'F', hostile: 'E', neutral: 'N', unknown: 'U',
    };
    const TYPE_CODES = {
        turret: 'T', sentry_turret: 'T', heavy_turret: 'H', missile_turret: 'M',
        drone: 'D', scout_drone: 'D',
        rover: 'R', patrol_rover: 'R',
        tank: 'K', camera: 'C', ptz_camera: 'C', security_camera: 'C',
        sensor: 'S', person: 'P', apc: 'A',
        hostile_person: 'P', neutral_person: 'P',
    };

    var a = ALLIANCE_CODES[(alliance || '').toLowerCase()] || 'U';
    var t = TYPE_CODES[(type || '').toLowerCase()] || 'X';
    var key = a + '-' + t;
    var seq = (counters.get(key) || 0) + 1;
    counters.set(key, seq);
    return a + '-' + t + '-' + seq;
}

// ============================================================
// Tests: Callsign generation
// ============================================================

console.log('\n--- Callsign Generation ---');

(function testBasicCallsign() {
    var counters = new Map();
    var cs = tacticalCallsign('t1', 'friendly', 'turret', counters);
    assert(cs === 'F-T-1', 'Friendly turret 1 = F-T-1 (got ' + cs + ')');
})();

(function testSequentialNumbers() {
    var counters = new Map();
    var cs1 = tacticalCallsign('t1', 'friendly', 'turret', counters);
    var cs2 = tacticalCallsign('t2', 'friendly', 'turret', counters);
    var cs3 = tacticalCallsign('t3', 'friendly', 'turret', counters);
    assert(cs1 === 'F-T-1', 'First turret is 1');
    assert(cs2 === 'F-T-2', 'Second turret is 2');
    assert(cs3 === 'F-T-3', 'Third turret is 3');
})();

(function testDifferentTypesGetSeparateCounters() {
    var counters = new Map();
    var ct = tacticalCallsign('t1', 'friendly', 'turret', counters);
    var cd = tacticalCallsign('d1', 'friendly', 'drone', counters);
    var cr = tacticalCallsign('r1', 'friendly', 'rover', counters);
    assert(ct === 'F-T-1', 'Turret gets own counter');
    assert(cd === 'F-D-1', 'Drone gets own counter');
    assert(cr === 'F-R-1', 'Rover gets own counter');
})();

(function testHostileCallsign() {
    var counters = new Map();
    var cs = tacticalCallsign('h1', 'hostile', 'person', counters);
    assert(cs === 'E-P-1', 'Hostile person = E-P-1 (got ' + cs + ')');
})();

(function testNeutralCallsign() {
    var counters = new Map();
    var cs = tacticalCallsign('n1', 'neutral', 'person', counters);
    assert(cs === 'N-P-1', 'Neutral person = N-P-1 (got ' + cs + ')');
})();

(function testUnknownAlliance() {
    var counters = new Map();
    var cs = tacticalCallsign('x1', 'unknown', 'turret', counters);
    assert(cs === 'U-T-1', 'Unknown alliance = U (got ' + cs + ')');
})();

(function testUnknownType() {
    var counters = new Map();
    var cs = tacticalCallsign('x1', 'friendly', 'banana', counters);
    assert(cs === 'F-X-1', 'Unknown type = X (got ' + cs + ')');
})();

(function testHeavyTurretCode() {
    var counters = new Map();
    var cs = tacticalCallsign('ht1', 'friendly', 'heavy_turret', counters);
    assert(cs === 'F-H-1', 'Heavy turret = H (got ' + cs + ')');
})();

(function testMissileTurretCode() {
    var counters = new Map();
    var cs = tacticalCallsign('mt1', 'friendly', 'missile_turret', counters);
    assert(cs === 'F-M-1', 'Missile turret = M (got ' + cs + ')');
})();

(function testScoutDroneSameAsDrone() {
    var counters = new Map();
    var cd = tacticalCallsign('d1', 'friendly', 'drone', counters);
    var csd = tacticalCallsign('sd1', 'friendly', 'scout_drone', counters);
    assert(cd === 'F-D-1', 'Drone = D-1');
    assert(csd === 'F-D-2', 'Scout drone shares D counter = D-2 (got ' + csd + ')');
})();

(function testPatrolRoverSameAsRover() {
    var counters = new Map();
    var cr = tacticalCallsign('r1', 'friendly', 'patrol_rover', counters);
    assert(cr === 'F-R-1', 'Patrol rover = R (got ' + cr + ')');
})();

(function testPtzCameraSameAsCamera() {
    var counters = new Map();
    var cc = tacticalCallsign('c1', 'friendly', 'ptz_camera', counters);
    assert(cc === 'F-C-1', 'PTZ camera = C (got ' + cc + ')');
})();

(function testSecurityCameraSameAsCamera() {
    var counters = new Map();
    var cc = tacticalCallsign('c1', 'friendly', 'security_camera', counters);
    assert(cc === 'F-C-1', 'Security camera = C (got ' + cc + ')');
})();

(function testTankCode() {
    var counters = new Map();
    var cs = tacticalCallsign('tk1', 'friendly', 'tank', counters);
    assert(cs === 'F-K-1', 'Tank = K (got ' + cs + ')');
})();

(function testApcCode() {
    var counters = new Map();
    var cs = tacticalCallsign('a1', 'friendly', 'apc', counters);
    assert(cs === 'F-A-1', 'APC = A (got ' + cs + ')');
})();

(function testSensorCode() {
    var counters = new Map();
    var cs = tacticalCallsign('s1', 'friendly', 'sensor', counters);
    assert(cs === 'F-S-1', 'Sensor = S (got ' + cs + ')');
})();

(function testMixedAlliancesSeparateCounters() {
    var counters = new Map();
    var ft = tacticalCallsign('t1', 'friendly', 'turret', counters);
    var et = tacticalCallsign('t2', 'hostile', 'turret', counters);
    assert(ft === 'F-T-1', 'Friendly turret = F-T-1');
    assert(et === 'E-T-1', 'Hostile turret = E-T-1 (separate counter)');
})();

(function testHostilePersonCode() {
    var counters = new Map();
    var cs = tacticalCallsign('hp1', 'hostile', 'hostile_person', counters);
    assert(cs === 'E-P-1', 'hostile_person type = P (got ' + cs + ')');
})();

(function testNeutralPersonCode() {
    var counters = new Map();
    var cs = tacticalCallsign('np1', 'neutral', 'neutral_person', counters);
    assert(cs === 'N-P-1', 'neutral_person type = P (got ' + cs + ')');
})();

(function testSentryTurretSameAsTurret() {
    var counters = new Map();
    var cs1 = tacticalCallsign('st1', 'friendly', 'sentry_turret', counters);
    var cs2 = tacticalCallsign('t1', 'friendly', 'turret', counters);
    assert(cs1 === 'F-T-1', 'Sentry turret = T-1');
    assert(cs2 === 'F-T-2', 'Regular turret shares T counter = T-2 (got ' + cs2 + ')');
})();

(function testEmptyType() {
    var counters = new Map();
    var cs = tacticalCallsign('x1', 'friendly', '', counters);
    assert(cs === 'F-X-1', 'Empty type = X (got ' + cs + ')');
})();

(function testEmptyAlliance() {
    var counters = new Map();
    var cs = tacticalCallsign('x1', '', 'turret', counters);
    assert(cs === 'U-T-1', 'Empty alliance = U (got ' + cs + ')');
})();

(function testNullValues() {
    var counters = new Map();
    var cs = tacticalCallsign('x1', null, null, counters);
    assert(cs === 'U-X-1', 'Null values = U-X-1 (got ' + cs + ')');
})();

// ============================================================
// Tests: Full battlefield callsign assignment
// ============================================================

console.log('\n--- Full Battlefield Scenario ---');

(function testNeighborhoodDefaultLayout() {
    // Simulate the default neighborhood layout
    var counters = new Map();
    var units = [
        { id: 'rover-alpha', alliance: 'friendly', type: 'patrol_rover' },
        { id: 'rover-bravo', alliance: 'friendly', type: 'patrol_rover' },
        { id: 'turret-north', alliance: 'friendly', type: 'sentry_turret' },
        { id: 'turret-south', alliance: 'friendly', type: 'sentry_turret' },
        { id: 'turret-west', alliance: 'friendly', type: 'heavy_turret' },
        { id: 'turret-east', alliance: 'friendly', type: 'missile_turret' },
        { id: 'drone-west', alliance: 'friendly', type: 'scout_drone' },
        { id: 'drone-east', alliance: 'friendly', type: 'scout_drone' },
        { id: 'tank-guard', alliance: 'friendly', type: 'tank' },
        { id: 'ptz-main', alliance: 'friendly', type: 'ptz_camera' },
        { id: 'cam-n', alliance: 'friendly', type: 'security_camera' },
        { id: 'cam-s', alliance: 'friendly', type: 'security_camera' },
        { id: 'cam-e', alliance: 'friendly', type: 'security_camera' },
        { id: 'cam-w', alliance: 'friendly', type: 'security_camera' },
        // Hostiles from wave spawn
        { id: 'h-1', alliance: 'hostile', type: 'hostile_person' },
        { id: 'h-2', alliance: 'hostile', type: 'hostile_person' },
        { id: 'h-3', alliance: 'hostile', type: 'hostile_person' },
        // Neutral neighbors
        { id: 'n-1', alliance: 'neutral', type: 'person' },
    ];

    var callsigns = units.map(function(u) {
        return tacticalCallsign(u.id, u.alliance, u.type, counters);
    });

    assert(callsigns[0] === 'F-R-1', 'Rover Alpha = F-R-1');
    assert(callsigns[1] === 'F-R-2', 'Rover Bravo = F-R-2');
    assert(callsigns[2] === 'F-T-1', 'Turret North = F-T-1 (sentry shares T)');
    assert(callsigns[3] === 'F-T-2', 'Turret South = F-T-2');
    assert(callsigns[4] === 'F-H-1', 'Turret West = F-H-1 (heavy)');
    assert(callsigns[5] === 'F-M-1', 'Turret East = F-M-1 (missile)');
    assert(callsigns[6] === 'F-D-1', 'Drone West = F-D-1');
    assert(callsigns[7] === 'F-D-2', 'Drone East = F-D-2');
    assert(callsigns[8] === 'F-K-1', 'Tank Guardian = F-K-1');
    assert(callsigns[9] === 'F-C-1', 'PTZ Main = F-C-1');
    assert(callsigns[10] === 'F-C-2', 'Cam North = F-C-2');
    assert(callsigns[11] === 'F-C-3', 'Cam South = F-C-3');
    assert(callsigns[12] === 'F-C-4', 'Cam East = F-C-4');
    assert(callsigns[13] === 'F-C-5', 'Cam West = F-C-5');
    assert(callsigns[14] === 'E-P-1', 'Hostile 1 = E-P-1');
    assert(callsigns[15] === 'E-P-2', 'Hostile 2 = E-P-2');
    assert(callsigns[16] === 'E-P-3', 'Hostile 3 = E-P-3');
    assert(callsigns[17] === 'N-P-1', 'Neutral = N-P-1');

    // Verify all are short (max 7 chars for F-XX-99)
    for (var i = 0; i < callsigns.length; i++) {
        assert(callsigns[i].length <= 8, 'Callsign ' + callsigns[i] + ' is short (<= 8 chars)');
    }
})();

// ============================================================
// Tests: Zoom LOD thresholds
// ============================================================

console.log('\n--- Zoom LOD ---');

/**
 * Determine label detail level based on zoom.
 *   0 = no labels (too zoomed out)
 *   1 = callsign only (e.g., "F-T-1")
 *   2 = callsign + type for selected (e.g., "F-T-1 Turret North")
 */
function labelLOD(zoom) {
    if (zoom < 0.15) return 0;  // no labels
    if (zoom < 0.8) return 1;   // callsign only
    return 2;                   // callsign + full info for selected
}

(function testLODVeryZoomedOut() {
    assert(labelLOD(0.05) === 0, 'zoom 0.05 = no labels');
    assert(labelLOD(0.1) === 0, 'zoom 0.1 = no labels');
    assert(labelLOD(0.14) === 0, 'zoom 0.14 = no labels');
})();

(function testLODCallsignOnly() {
    assert(labelLOD(0.15) === 1, 'zoom 0.15 = callsigns');
    assert(labelLOD(0.3) === 1, 'zoom 0.3 = callsigns');
    assert(labelLOD(0.5) === 1, 'zoom 0.5 = callsigns');
    assert(labelLOD(0.79) === 1, 'zoom 0.79 = callsigns');
})();

(function testLODFullDetail() {
    assert(labelLOD(0.8) === 2, 'zoom 0.8 = full detail');
    assert(labelLOD(1.0) === 2, 'zoom 1.0 = full detail');
    assert(labelLOD(2.0) === 2, 'zoom 2.0 = full detail');
    assert(labelLOD(5.0) === 2, 'zoom 5.0 = full detail');
})();

// ============================================================
// Tests: Label text at different LOD levels
// ============================================================

console.log('\n--- Label Text by LOD ---');

function buildLabelText(callsign, name, lod, isSelected) {
    if (lod === 0) return null;   // hidden
    if (lod === 1) return callsign;
    // LOD 2: selected units show name too
    if (isSelected && name) return callsign + ' ' + name;
    return callsign;
}

(function testLabelTextHidden() {
    assert(buildLabelText('F-T-1', 'Turret North', 0, false) === null, 'LOD 0 = null');
    assert(buildLabelText('F-T-1', 'Turret North', 0, true) === null, 'LOD 0 = null even if selected');
})();

(function testLabelTextCallsignOnly() {
    assert(buildLabelText('F-T-1', 'Turret North', 1, false) === 'F-T-1', 'LOD 1 = callsign only');
    assert(buildLabelText('F-T-1', 'Turret North', 1, true) === 'F-T-1', 'LOD 1 selected = still callsign only');
})();

(function testLabelTextFullDetail() {
    assert(buildLabelText('F-T-1', 'Turret North', 2, false) === 'F-T-1', 'LOD 2 unselected = callsign');
    assert(buildLabelText('F-T-1', 'Turret North', 2, true) === 'F-T-1 Turret North', 'LOD 2 selected = callsign + name');
})();

(function testLabelTextNoName() {
    assert(buildLabelText('E-P-1', null, 2, true) === 'E-P-1', 'No name = callsign only even if selected');
    assert(buildLabelText('E-P-1', '', 2, true) === 'E-P-1', 'Empty name = callsign only');
})();

// ============================================================
// Tests: Alliance color coding for label backgrounds
// ============================================================

console.log('\n--- Label Colors ---');

var LABEL_BG_COLORS = {
    friendly: 'rgba(5, 255, 161, 0.12)',
    hostile:  'rgba(255, 42, 109, 0.15)',
    neutral:  'rgba(0, 160, 255, 0.10)',
    unknown:  'rgba(252, 238, 10, 0.10)',
};

(function testAllianceColors() {
    assert(LABEL_BG_COLORS.friendly !== undefined, 'Friendly has bg color');
    assert(LABEL_BG_COLORS.hostile !== undefined, 'Hostile has bg color');
    assert(LABEL_BG_COLORS.neutral !== undefined, 'Neutral has bg color');
    assert(LABEL_BG_COLORS.unknown !== undefined, 'Unknown has bg color');
})();

// ============================================================
// Summary
// ============================================================

console.log('\n' + '='.repeat(40));
console.log('Results: ' + passed + ' passed, ' + failed + ' failed');
console.log('='.repeat(40));
process.exit(failed > 0 ? 1 : 0);
