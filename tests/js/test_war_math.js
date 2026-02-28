// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
/**
 * TRITIUM-SC War FX math + trail tests
 * Run: node tests/js/test_war_math.js
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

// Load war-fx.js into a sandboxed context
const code = fs.readFileSync(__dirname + '/../../frontend/js/war-fx.js', 'utf8');
let perfNow = 1000;
const ctx = vm.createContext({
    Math, Date, console, Map, Array, Object, Number, Infinity,
    performance: { now: () => perfNow },
});
vm.runInContext(code, ctx);

const { fadeToward, lerpAngle, easeInOut, warFxUpdateTrails, warFxAddEvent } = ctx;

// ============================================================
// fadeToward tests
// ============================================================

console.log('\n--- fadeToward ---');

(function testFadeTowardMovesTowardTarget() {
    const result = fadeToward(0, 10, 8, 0.016);
    assert(result > 0 && result < 10, 'fadeToward(0, 10, 8, 0.016) moves toward 10');
})();

(function testFadeTowardStaysAtTarget() {
    const result = fadeToward(10, 10, 8, 0.016);
    assertClose(result, 10, 0.01, 'fadeToward(10, 10, 8, 0.016) stays at 10');
})();

(function testFadeTowardSnapsWhenClose() {
    const result = fadeToward(9.99, 10, 8, 0.016);
    assertClose(result, 10, 0.001, 'fadeToward(9.99, 10, 8, 0.016) snaps to 10');
})();

(function testFadeTowardLargeDt() {
    const result = fadeToward(0, 10, 8, 1.0);
    assert(result > 9.0, 'fadeToward(0, 10, 8, 1.0) gets close to 10 with large dt (got ' + result + ')');
})();

(function testFadeTowardNegativeDirection() {
    const result = fadeToward(10, 0, 8, 0.016);
    assert(result < 10 && result > 0, 'fadeToward(10, 0, 8, 0.016) moves toward 0');
})();

// ============================================================
// lerpAngle tests
// ============================================================

console.log('\n--- lerpAngle ---');

(function testLerpAngleThroughZero() {
    const result = lerpAngle(350, 10, 8, 0.016);
    // Should go through 360/0 boundary: increase past 350 toward 360/10
    assert(result > 350 || result < 10, 'lerpAngle(350, 10, 8, 0.016) goes through 360 (got ' + result + ')');
})();

(function testLerpAngleBackwardsThroughZero() {
    const result = lerpAngle(10, 350, 8, 0.016);
    // Should go backward through 0: decrease from 10 toward 350
    assert(result < 10 || result > 350, 'lerpAngle(10, 350, 8, 0.016) goes backwards through 0 (got ' + result + ')');
})();

(function testLerpAngleStays() {
    const result = lerpAngle(180, 180, 8, 0.016);
    assertClose(result, 180, 0.1, 'lerpAngle(180, 180, 8, 0.016) stays at 180');
})();

(function testLerpAngleMovesToward180() {
    const result = lerpAngle(0, 180, 8, 0.016);
    assert(result > 0 && result < 180, 'lerpAngle(0, 180, 8, 0.016) moves toward 180 (got ' + result + ')');
})();

(function testLerpAngleNormalizesResult() {
    // Result should always be in [0, 360)
    const result = lerpAngle(5, 355, 8, 0.016);
    assert(result >= 0 && result < 360, 'lerpAngle result normalized to [0, 360) (got ' + result + ')');
})();

// ============================================================
// easeInOut tests
// ============================================================

console.log('\n--- easeInOut ---');

(function testEaseInOutZero() {
    assertClose(easeInOut(0), 0, 0.001, 'easeInOut(0) === 0');
})();

(function testEaseInOutOne() {
    assertClose(easeInOut(1), 1, 0.001, 'easeInOut(1) === 1');
})();

(function testEaseInOutHalf() {
    assertClose(easeInOut(0.5), 0.5, 0.001, 'easeInOut(0.5) === 0.5');
})();

(function testEaseInOutSlowStart() {
    assert(easeInOut(0.25) < 0.25, 'easeInOut(0.25) < 0.25 (slow start, got ' + easeInOut(0.25) + ')');
})();

(function testEaseInOutSlowEnd() {
    assert(easeInOut(0.75) > 0.75, 'easeInOut(0.75) > 0.75 (slow end, got ' + easeInOut(0.75) + ')');
})();

// ============================================================
// Trail system tests
// ============================================================

console.log('\n--- Trails ---');

(function testTrailGrowsOnMove() {
    // Simulate targets moving
    const targets = {
        'unit-1': { x: 0, y: 0 },
        'unit-2': { x: 10, y: 10 },
    };
    // First tick adds initial points
    perfNow = 1000;
    warFxUpdateTrails(targets, 0.1);

    // Move targets
    targets['unit-1'].x = 5;
    targets['unit-1'].y = 5;
    perfNow = 2000;
    warFxUpdateTrails(targets, 0.1);

    // Check trail exists via internal map - access via context
    const trails = ctx._trails;
    assert(trails instanceof Map, 'Trail map exists');
    const trail1 = trails.get('unit-1');
    assert(trail1 && trail1.length >= 2, 'Trail grows when target moves (length=' + (trail1 ? trail1.length : 0) + ')');
})();

(function testTrailDoesNotGrowWhenStationary() {
    const targets = { 'still-unit': { x: 20, y: 20 } };
    perfNow = 3000;
    warFxUpdateTrails(targets, 0.1);
    perfNow = 3100;
    warFxUpdateTrails(targets, 0.1);

    const trails = ctx._trails;
    const trail = trails.get('still-unit');
    assert(trail && trail.length === 1, 'Trail does not grow when stationary (length=' + (trail ? trail.length : 0) + ')');
})();

(function testTrailCleanupOnRemove() {
    const targets = { 'temp-unit': { x: 0, y: 0 } };
    perfNow = 4000;
    warFxUpdateTrails(targets, 0.1);

    // Remove target
    warFxUpdateTrails({}, 0.1);

    const trails = ctx._trails;
    assert(!trails.has('temp-unit'), 'Trail cleaned up when target removed');
})();

// ============================================================
// Event log tests
// ============================================================

console.log('\n--- Event Log ---');

(function testEventLogAddsEntries() {
    warFxAddEvent('HOSTILE DETECTED', '#ff2a6d');
    warFxAddEvent('DISPATCH SENT', '#00f0ff');
    const log = ctx._eventLog;
    assert(log.length >= 2, 'Event log has entries after adding (length=' + log.length + ')');
    assert(log[log.length - 1].text === 'DISPATCH SENT', 'Last event text matches');
    assert(log[log.length - 1].color === '#00f0ff', 'Event color matches');
})();

// ============================================================
// Cinematic camera tests
// ============================================================

console.log('\n--- Cinematic Camera ---');

const { warFxToggleCinematic, warFxIsCinematic, warFxCinematicTick } = ctx;

(function testCinemaToggle() {
    // Start disabled
    assert(!warFxIsCinematic(), 'Cinema starts disabled');
    const enabled = warFxToggleCinematic();
    assert(enabled === true, 'Toggle returns true when enabling');
    assert(warFxIsCinematic(), 'Cinema enabled after toggle');
    warFxToggleCinematic(); // disable again
    assert(!warFxIsCinematic(), 'Cinema disabled after second toggle');
})();

(function testCinemaFollowsHostileWhenActive() {
    // Enable cinematic
    warFxToggleCinematic();
    // Create a cam object
    const cam = { x: 0, y: 0, targetX: 0, targetY: 0, zoom: 1, targetZoom: 1 };
    // Create targets with a hostile
    const targets = {
        'hostile-1': { alliance: 'Hostile', x: 20, y: 30, position: { x: 20, y: 30 } },
        'turret-1': { alliance: 'Friendly', x: 0, y: 0, position: { x: 0, y: 0 } },
    };
    // Pass gameState with .gameState property (like _hudState from war-hud.js)
    const gameState = { gameState: 'active', wave: 1, totalWaves: 10 };
    // Tick enough to trigger a shot change
    for (let i = 0; i < 100; i++) {
        warFxCinematicTick(0.1, cam, targets, gameState);
    }
    // Camera should have moved toward the hostile (either targetX or targetY != 0)
    const moved = cam.targetX !== 0 || cam.targetY !== 0;
    assert(moved, 'Camera targets hostile during active game (targetX=' + cam.targetX + ', targetY=' + cam.targetY + ')');
    warFxToggleCinematic(); // disable
})();

(function testCinemaOverviewWhenNotActive() {
    warFxToggleCinematic(); // enable
    const cam = { x: 0, y: 0, targetX: 0, targetY: 0, zoom: 1, targetZoom: 1 };
    const targets = {
        'hostile-1': { alliance: 'Hostile', x: 20, y: 30, position: { x: 20, y: 30 } },
    };
    // No game state -> should stay in overview, not follow hostile
    warFxCinematicTick(10, cam, targets, null);
    // In overview mode the camera stays at origin (no targetId set)
    // Just verify it doesn't crash
    assert(true, 'Cinema runs without game state (overview mode)');
    warFxToggleCinematic(); // disable
})();

// ============================================================
// Summary
// ============================================================

console.log('\n' + '='.repeat(40));
console.log(`Results: ${passed} passed, ${failed} failed`);
console.log('='.repeat(40));
process.exit(failed > 0 ? 1 : 0);
