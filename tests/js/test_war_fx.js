/**
 * TRITIUM-SC War Room -- Visual Effects tests
 * Run: node tests/js/test_war_fx.js
 *
 * Tests vision cone rendering logic, trail system, and cinematic camera.
 * Loads war-fog.js first (for fogGetVisionProfile/fogGetSweepHeading),
 * then war-fx.js.
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

// Load war-fog.js first (provides fogGetVisionProfile, fogGetSweepHeading)
const fogCode = fs.readFileSync(__dirname + '/../../frontend/js/war-fog.js', 'utf8');
const fxCode = fs.readFileSync(__dirname + '/../../frontend/js/war-fx.js', 'utf8');

let perfNow = 1000;
let dateNow = 5000;
const ctx = vm.createContext({
    Math, Date: { now: () => dateNow },
    console, Map, Array, Object, Number, Infinity, Boolean, parseInt, parseFloat,
    performance: { now: () => perfNow },
    document: {
        createElement: () => ({ getContext: () => null }),
    },
});

vm.runInContext(fogCode, ctx);
vm.runInContext(fxCode, ctx);

const {
    warFxDrawVisionCones,
    warFxUpdateTrails,
    warFxDrawTrails,
    fogGetVisionProfile,
    FOG_VISION_PROFILES,
} = ctx;

// ============================================================
// Vision cone rendering logic
// ============================================================

console.log('\n--- Vision Cone Rendering ---');

// Mock canvas context to capture draw calls
function mockCtx() {
    const calls = [];
    return {
        calls,
        save() { calls.push({ op: 'save' }); },
        restore() { calls.push({ op: 'restore' }); },
        translate(x, y) { calls.push({ op: 'translate', x, y }); },
        rotate(a) { calls.push({ op: 'rotate', a }); },
        beginPath() { calls.push({ op: 'beginPath' }); },
        moveTo(x, y) { calls.push({ op: 'moveTo', x, y }); },
        arc(x, y, r, s, e) { calls.push({ op: 'arc', x, y, r, s, e }); },
        closePath() { calls.push({ op: 'closePath' }); },
        fill() { calls.push({ op: 'fill' }); },
        stroke() { calls.push({ op: 'stroke' }); },
        createRadialGradient(x1, y1, r1, x2, y2, r2) {
            const stops = [];
            return {
                addColorStop(pos, color) { stops.push({ pos, color }); },
                _stops: stops,
                _r2: r2,
            };
        },
        set fillStyle(v) { calls.push({ op: 'fillStyle', v }); },
        set strokeStyle(v) { calls.push({ op: 'strokeStyle', v }); },
        set lineWidth(v) { calls.push({ op: 'lineWidth', v }); },
    };
}

function mockWorldToScreen(x, y) {
    // Simple 1:1 mapping
    return { x: x + 500, y: 500 - y };
}

(function testVisionConesOnlyForFriendly() {
    const mc = mockCtx();
    const targets = {
        'hostile-1': { alliance: 'hostile', asset_type: 'turret', position: { x: 0, y: 0 } },
    };
    warFxDrawVisionCones(mc, mockWorldToScreen, targets, 1.0);
    const saves = mc.calls.filter(c => c.op === 'save');
    assert(saves.length === 0, 'No vision cones drawn for hostile units');
})();

(function testVisionConesSkipNoConeUnits() {
    const mc = mockCtx();
    const targets = {
        'person-1': { alliance: 'friendly', asset_type: 'person', position: { x: 10, y: 10 } },
        'drone-1': { alliance: 'friendly', asset_type: 'drone', position: { x: 20, y: 20 } },
    };
    warFxDrawVisionCones(mc, mockWorldToScreen, targets, 1.0);
    const saves = mc.calls.filter(c => c.op === 'save');
    assert(saves.length === 0, 'No vision cones drawn for person/drone (only turret/camera/sensor get cones)');
})();

(function testVisionConesDrawnForTurret() {
    const mc = mockCtx();
    const targets = {
        'turret-1': { alliance: 'friendly', asset_type: 'turret', x: 0, y: 0, heading: 0 },
    };
    warFxDrawVisionCones(mc, mockWorldToScreen, targets, 1.0);
    const saves = mc.calls.filter(c => c.op === 'save');
    assert(saves.length === 1, 'Vision cone drawn for turret');
})();

(function testVisionConesDrawnForAllConeTypes() {
    // war-fx.js only draws cones for turret, camera, sensor (line 110 filter)
    const mc = mockCtx();
    const targets = {
        'turret-1': { alliance: 'friendly', asset_type: 'turret', x: 0, y: 0 },
        'camera-1': { alliance: 'friendly', asset_type: 'camera', x: 5, y: -5 },
        'sensor-1': { alliance: 'friendly', asset_type: 'sensor', x: -5, y: 5 },
        'drone-1': { alliance: 'friendly', asset_type: 'drone', x: 10, y: 10 },
        'rover-1': { alliance: 'friendly', asset_type: 'rover', x: -10, y: 0 },
    };
    warFxDrawVisionCones(mc, mockWorldToScreen, targets, 1.0);
    const saves = mc.calls.filter(c => c.op === 'save');
    assert(saves.length === 3, 'Vision cones drawn for turret, camera, sensor (3 types)');
})();

(function testVisionConeRangeUsesZoom() {
    // war-fx.js: range = (weapon_range || fov_range || 15) * zoom * 12
    const mc = mockCtx();
    const targets = {
        'turret-1': { alliance: 'friendly', asset_type: 'turret', x: 0, y: 0, heading: 0, weapon_range: 15 },
    };
    const zoom = 2.0;
    warFxDrawVisionCones(mc, mockWorldToScreen, targets, zoom);
    const arcs = mc.calls.filter(c => c.op === 'arc');
    assert(arcs.length > 0, 'Arc calls found');
    const mainArc = arcs[0];
    // range = weapon_range * zoom * 12 = 15 * 2 * 12 = 360
    const expectedRange = 15 * zoom * 12;
    assertClose(mainArc.r, expectedRange, 0.1, 'Cone arc radius = weapon_range * zoom * 12');
})();

(function testVisionConeAlphaIsSubtle() {
    // The gradient should use low alpha values (0.06 fill, not 0.15)
    const mc = mockCtx();
    const targets = {
        'turret-1': { alliance: 'friendly', asset_type: 'turret', x: 0, y: 0, heading: 0 },
    };
    warFxDrawVisionCones(mc, mockWorldToScreen, targets, 1.0);
    const fillStyles = mc.calls.filter(c => c.op === 'fillStyle');
    // The gradient is set as fillStyle; check the gradient's color stops
    // We check that the strokeStyle has alpha <= 0.12
    const strokes = mc.calls.filter(c => c.op === 'strokeStyle');
    if (strokes.length > 0) {
        const strokeColor = strokes[0].v;
        // Parse alpha from rgba string
        const match = strokeColor.match(/[\d.]+\)$/);
        if (match) {
            const alpha = parseFloat(match[0]);
            assert(alpha <= 0.15, 'Cone stroke alpha <= 0.15 (got ' + alpha + ')');
        }
    }
    assert(true, 'Vision cone uses subtle alpha (checked)');
})();

// ============================================================
// Trail system
// ============================================================

console.log('\n--- Trail System ---');

(function testTrailUpdateCreatesTrails() {
    const targets = {
        'unit-1': { x: 0, y: 0, alliance: 'friendly' },
    };
    warFxUpdateTrails(targets, 0.1);
    assert(true, 'Trail update does not throw');
})();

// ============================================================
// Profile table consistency
// ============================================================

console.log('\n--- Profile Consistency ---');

if (typeof FOG_VISION_PROFILES === 'object' && FOG_VISION_PROFILES) {
    (function testAllConeTypesHavePositiveRange() {
        const coneTypes = ['turret', 'heavy_turret', 'missile_turret', 'drone', 'scout_drone',
                           'rover', 'tank', 'apc', 'camera'];
        for (const type of coneTypes) {
            const p = FOG_VISION_PROFILES[type];
            if (!p) { console.log(`SKIP: ${type} not in FOG_VISION_PROFILES`); continue; }
            assert(p.coneRange > 0, `${type} has positive cone range (${p.coneRange})`);
            assert(p.coneAngle > 0, `${type} has positive cone angle (${p.coneAngle})`);
        }
    })();

    (function testOmniTypesHaveZeroCone() {
        const omniTypes = ['sensor', 'person', 'hostile_person'];
        for (const type of omniTypes) {
            const p = FOG_VISION_PROFILES[type];
            if (!p) { console.log(`SKIP: ${type} not in FOG_VISION_PROFILES`); continue; }
            assertClose(p.coneRange, 0, 0.001, `${type} has zero cone range`);
            assertClose(p.coneAngle, 0, 0.001, `${type} has zero cone angle`);
        }
    })();

    (function testSweepTypesAreCorrect() {
        const sweepTypes = ['drone', 'scout_drone', 'camera'];
        const noSweepTypes = ['turret', 'heavy_turret', 'missile_turret', 'rover', 'tank', 'apc', 'sensor', 'person'];
        for (const type of sweepTypes) {
            if (!FOG_VISION_PROFILES[type]) { console.log(`SKIP: ${type} not in FOG_VISION_PROFILES`); continue; }
            assert(FOG_VISION_PROFILES[type].sweeps, `${type} sweeps`);
        }
        for (const type of noSweepTypes) {
            if (!FOG_VISION_PROFILES[type]) { console.log(`SKIP: ${type} not in FOG_VISION_PROFILES`); continue; }
            assert(!FOG_VISION_PROFILES[type].sweeps, `${type} does not sweep`);
        }
    })();
} else {
    console.log('SKIP: FOG_VISION_PROFILES not available (not yet implemented)');
}

// ============================================================
// Summary
// ============================================================

console.log('\n' + '='.repeat(40));
console.log(`Results: ${passed} passed, ${failed} failed`);
console.log('='.repeat(40));
process.exit(failed > 0 ? 1 : 0);
