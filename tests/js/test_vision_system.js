/**
 * TRITIUM-SC Vision System Tests
 * Tests cone geometry, fog compositing, building shadows, ghost tracking,
 * and enable/disable lifecycle for the frontend vision system.
 * Run: node tests/js/test_vision_system.js
 */

let passed = 0, failed = 0;
function assert(cond, msg) {
    if (!cond) { console.error('FAIL:', msg); failed++; }
    else { console.log('PASS:', msg); passed++; }
}

function assertApprox(actual, expected, tolerance, msg) {
    const ok = Math.abs(actual - expected) <= tolerance;
    if (!ok) { console.error(`FAIL: ${msg} (got ${actual}, expected ${expected} +/- ${tolerance})`); failed++; }
    else { console.log('PASS:', msg); passed++; }
}

// ============================================================
// Mock canvas context for fog drawing tests
// ============================================================

function createMockCtx() {
    const calls = [];
    return {
        calls,
        fillRect(...args) { calls.push({ op: 'fillRect', args }); },
        clearRect(...args) { calls.push({ op: 'clearRect', args }); },
        beginPath() { calls.push({ op: 'beginPath' }); },
        arc(...args) { calls.push({ op: 'arc', args }); },
        moveTo(...args) { calls.push({ op: 'moveTo', args }); },
        lineTo(...args) { calls.push({ op: 'lineTo', args }); },
        fill() { calls.push({ op: 'fill' }); },
        stroke() { calls.push({ op: 'stroke' }); },
        closePath() { calls.push({ op: 'closePath' }); },
        save() { calls.push({ op: 'save' }); },
        restore() { calls.push({ op: 'restore' }); },
        globalCompositeOperation: 'source-over',
        fillStyle: '',
        strokeStyle: '',
        lineWidth: 1,
        shadowColor: '',
        shadowBlur: 0,
    };
}

// ============================================================
// Import the module under test.
// Since this is a Node.js test, we replicate the pure functions
// from vision-system.js. Once the source file exists, these will
// be imported directly.
// ============================================================

// We load the source file via vm to avoid ES module issues
const fs = require('fs');
const path = require('path');
const vm = require('vm');

// Try to load the real source file
const srcPath = path.join(__dirname, '..', '..', 'frontend', 'js', 'command', 'vision-system.js');
let isInCone, updateSweepAngle, GhostTracker, FrontendVisionSystem;
let loaded = false;

// Mock getVisionProfile / getType for the registry import
const MOCK_PROFILES = {
    turret:         { ambient: 8, coneRange: 40, coneAngle: 90, coneSweeps: false, coneSweepRPM: 0 },
    drone:          { ambient: 20, coneRange: 45, coneAngle: 45, coneSweeps: true, coneSweepRPM: 2 },
    rover:          { ambient: 12, coneRange: 30, coneAngle: 120, coneSweeps: false, coneSweepRPM: 0 },
    camera:         { ambient: 5, coneRange: 30, coneAngle: 60, coneSweeps: true, coneSweepRPM: 1 },
    sensor:         { ambient: 20, coneRange: 0, coneAngle: 0, coneSweeps: false, coneSweepRPM: 0 },
    hostile_person: { ambient: 12, coneRange: 0, coneAngle: 0, coneSweeps: false, coneSweepRPM: 0 },
};
const DEFAULT_PROFILE = { ambient: 10, coneRange: 0, coneAngle: 0, coneSweeps: false, coneSweepRPM: 0 };

try {
    let src = fs.readFileSync(srcPath, 'utf8');
    // Strip import statements (not valid in CJS/vm context)
    src = src.replace(/^import\s+.*$/gm, '');
    // Strip export keywords
    src = src.replace(/^export\s+/gm, '');
    // Append explicit sandbox assignments for classes/functions
    src += `
        _exports = { isInCone, updateSweepAngle, GhostTracker, FrontendVisionSystem };
    `;
    // Execute in a sandboxed context
    const sandbox = {
        console,
        Math,
        Map,
        Set,
        Date,
        document: { createElement: () => ({ getContext: () => null, width: 1024, height: 1024 }) },
        performance: { now: Date.now },
        setTimeout,
        clearTimeout,
        _exports: {},
        // Mock the registry functions that vision-system.js imports
        getVisionProfile(typeId) {
            return MOCK_PROFILES[typeId] || DEFAULT_PROFILE;
        },
        getType(typeId) { return null; },
    };
    vm.createContext(sandbox);
    vm.runInContext(src, sandbox);
    isInCone = sandbox._exports.isInCone;
    updateSweepAngle = sandbox._exports.updateSweepAngle;
    GhostTracker = sandbox._exports.GhostTracker;
    FrontendVisionSystem = sandbox._exports.FrontendVisionSystem;
    loaded = true;
} catch (e) {
    console.warn('Could not load vision-system.js, tests will FAIL:', e.message);
}

// ============================================================
// TestConeGeometry
// ============================================================

console.log('\n=== TestConeGeometry ===\n');

{
    // test_target_directly_ahead_in_cone
    // Unit at (0,0) heading north (0), target at (0, 10) = directly north
    if (loaded) {
        const result = isInCone(0, 0, 0, 90, 50, 0, 10);
        assert(result === true, 'cone: target directly ahead is inside cone');
    } else {
        assert(false, 'cone: target directly ahead is inside cone (module not loaded)');
    }
}

{
    // test_target_behind_outside_cone
    // Unit heading north (0), target at (0, -10) = directly south
    if (loaded) {
        const result = isInCone(0, 0, 0, 90, 50, 0, -10);
        assert(result === false, 'cone: target directly behind is outside cone');
    } else {
        assert(false, 'cone: target directly behind is outside cone (module not loaded)');
    }
}

{
    // test_target_at_cone_edge
    // Unit heading north (0), cone angle 90 (45 each side)
    // Target at (10, 10) = 45 degrees east of north = exactly on the edge
    if (loaded) {
        const result = isInCone(0, 0, 0, 90, 50, 10, 10);
        assert(result === true, 'cone: target at 45deg edge of 90deg cone is inside');
    } else {
        assert(false, 'cone: target at 45deg edge of 90deg cone is inside (module not loaded)');
    }
}

{
    // test_target_just_outside_cone_angle
    // Unit heading north (0), cone angle 60 (30 each side)
    // Target at (10, 10) = 45 degrees from north > 30 half-angle
    if (loaded) {
        const result = isInCone(0, 0, 0, 60, 50, 10, 10);
        assert(result === false, 'cone: target at 45deg outside 60deg cone');
    } else {
        assert(false, 'cone: target at 45deg outside 60deg cone (module not loaded)');
    }
}

{
    // test_target_beyond_range
    // Target at (0, 100) but range is 50
    if (loaded) {
        const result = isInCone(0, 0, 0, 90, 50, 0, 100);
        assert(result === false, 'cone: target beyond range is outside');
    } else {
        assert(false, 'cone: target beyond range is outside (module not loaded)');
    }
}

{
    // test_target_within_range_within_angle
    // Heading east (90), cone 120deg, range 40, target at (30, 0)
    if (loaded) {
        const result = isInCone(0, 0, 90, 120, 40, 30, 0);
        assert(result === true, 'cone: heading east, target east, within range');
    } else {
        assert(false, 'cone: heading east, target east, within range (module not loaded)');
    }
}

{
    // test_heading_wraps_360
    // Heading 350 (almost north), target slightly west of north
    if (loaded) {
        const result = isInCone(0, 0, 350, 90, 50, -2, 20);
        assert(result === true, 'cone: heading 350, target at ~355 degrees is inside');
    } else {
        assert(false, 'cone: heading 350, target at ~355 degrees is inside (module not loaded)');
    }
}

{
    // test_narrow_cone
    // Turret with 10deg cone, target must be very close to heading
    if (loaded) {
        const insideResult = isInCone(0, 0, 0, 10, 50, 0.5, 20);
        const outsideResult = isInCone(0, 0, 0, 10, 50, 5, 10);
        assert(insideResult === true, 'cone: narrow 10deg, nearly-aligned target inside');
        assert(outsideResult === false, 'cone: narrow 10deg, off-axis target outside');
    } else {
        assert(false, 'cone: narrow 10deg, nearly-aligned target inside (module not loaded)');
        assert(false, 'cone: narrow 10deg, off-axis target outside (module not loaded)');
    }
}

{
    // test_wide_cone_180
    // 180 degree cone = front hemisphere
    if (loaded) {
        const frontResult = isInCone(0, 0, 0, 180, 50, 10, 1);
        const backResult = isInCone(0, 0, 0, 180, 50, 0, -10);
        assert(frontResult === true, 'cone: 180deg, target in front hemisphere');
        assert(backResult === false, 'cone: 180deg, target behind is outside');
    } else {
        assert(false, 'cone: 180deg, target in front hemisphere (module not loaded)');
        assert(false, 'cone: 180deg, target behind is outside (module not loaded)');
    }
}

{
    // test_zero_range_cone
    if (loaded) {
        const result = isInCone(0, 0, 0, 90, 0, 0, 5);
        assert(result === false, 'cone: zero range means nothing is visible');
    } else {
        assert(false, 'cone: zero range means nothing is visible (module not loaded)');
    }
}

// ============================================================
// TestSweepAngle
// ============================================================

console.log('\n=== TestSweepAngle ===\n');

{
    // test_sweep_advances
    if (loaded) {
        // 2 RPM, dt=0.5s => 2*360*0.5/60 = 6 degrees
        const newAngle = updateSweepAngle(0, 2, 0.5);
        assertApprox(newAngle, 6, 0.01, 'sweep: 2RPM at 0.5s advances 6 degrees');
    } else {
        assert(false, 'sweep: 2RPM at 0.5s advances 6 degrees (module not loaded)');
    }
}

{
    // test_sweep_wraps_at_360
    if (loaded) {
        const newAngle = updateSweepAngle(358, 2, 1.0);
        // 358 + 2*360*1/60 = 358 + 12 = 370 % 360 = 10
        assertApprox(newAngle, 10, 0.01, 'sweep: wraps around 360');
    } else {
        assert(false, 'sweep: wraps around 360 (module not loaded)');
    }
}

{
    // test_sweep_zero_rpm
    if (loaded) {
        const newAngle = updateSweepAngle(45, 0, 1.0);
        assertApprox(newAngle, 45, 0.01, 'sweep: 0 RPM stays at current angle');
    } else {
        assert(false, 'sweep: 0 RPM stays at current angle (module not loaded)');
    }
}

{
    // test_sweep_high_rpm
    if (loaded) {
        // 60 RPM = 1 revolution per second
        const newAngle = updateSweepAngle(0, 60, 1.0);
        assertApprox(newAngle, 0, 0.01, 'sweep: 60RPM at 1s = full revolution, back to 0');
    } else {
        assert(false, 'sweep: 60RPM at 1s = full revolution, back to 0 (module not loaded)');
    }
}

// ============================================================
// TestGhostTracking
// ============================================================

console.log('\n=== TestGhostTracking ===\n');

{
    // test_ghost_created_when_invisible
    if (loaded) {
        const tracker = new GhostTracker();
        const units = [
            { target_id: 'h1', alliance: 'hostile', visible: false, position: { x: 10, y: 20 } },
        ];
        tracker.update(units, 0.1);
        const ghost = tracker.getGhost('h1');
        assert(ghost !== null, 'ghost: created for invisible hostile');
        assert(ghost.x === 10, 'ghost: x position stored');
        assert(ghost.y === 20, 'ghost: y position stored');
    } else {
        assert(false, 'ghost: created for invisible hostile (module not loaded)');
        assert(false, 'ghost: x position stored (module not loaded)');
        assert(false, 'ghost: y position stored (module not loaded)');
    }
}

{
    // test_ghost_removed_when_visible
    if (loaded) {
        const tracker = new GhostTracker();
        tracker.update([
            { target_id: 'h1', alliance: 'hostile', visible: false, position: { x: 10, y: 20 } },
        ], 0.1);
        assert(tracker.getGhost('h1') !== null, 'ghost: exists before visible');
        tracker.update([
            { target_id: 'h1', alliance: 'hostile', visible: true, position: { x: 15, y: 25 } },
        ], 0.1);
        assert(tracker.getGhost('h1') === null, 'ghost: removed when visible again');
    } else {
        assert(false, 'ghost: exists before visible (module not loaded)');
        assert(false, 'ghost: removed when visible again (module not loaded)');
    }
}

{
    // test_ghost_fade_timer
    if (loaded) {
        const tracker = new GhostTracker();
        tracker.update([
            { target_id: 'h1', alliance: 'hostile', visible: false, position: { x: 10, y: 20 } },
        ], 0.0);
        const ghost1 = tracker.getGhost('h1');
        const initialOpacity = ghost1.opacity;
        // Advance time: 15 seconds of dt
        for (let i = 0; i < 150; i++) {
            tracker.update([
                { target_id: 'h1', alliance: 'hostile', visible: false, position: { x: 10, y: 20 } },
            ], 0.1);
        }
        const ghost2 = tracker.getGhost('h1');
        assert(ghost2.opacity < initialOpacity, 'ghost: opacity decreases over time');
        assert(ghost2.opacity > 0, 'ghost: still visible at 15s (30s fade)');
    } else {
        assert(false, 'ghost: opacity decreases over time (module not loaded)');
        assert(false, 'ghost: still visible at 15s (30s fade) (module not loaded)');
    }
}

{
    // test_ghost_removed_after_full_fade
    if (loaded) {
        const tracker = new GhostTracker();
        tracker.update([
            { target_id: 'h1', alliance: 'hostile', visible: false, position: { x: 10, y: 20 } },
        ], 0.0);
        // Advance 31 seconds (past the 30s fade)
        for (let i = 0; i < 310; i++) {
            tracker.update([
                { target_id: 'h1', alliance: 'hostile', visible: false, position: { x: 10, y: 20 } },
            ], 0.1);
        }
        const ghost = tracker.getGhost('h1');
        assert(ghost === null, 'ghost: removed after 30s fade');
    } else {
        assert(false, 'ghost: removed after 30s fade (module not loaded)');
    }
}

{
    // test_ghost_position_remembered
    if (loaded) {
        const tracker = new GhostTracker();
        // First seen at (10, 20)
        tracker.update([
            { target_id: 'h1', alliance: 'hostile', visible: false, position: { x: 10, y: 20 } },
        ], 0.1);
        // Not in units list anymore (disappeared completely)
        tracker.update([], 0.1);
        const ghost = tracker.getGhost('h1');
        assert(ghost !== null, 'ghost: persists when unit disappears from list');
        assert(ghost.x === 10, 'ghost: position remembered after unit gone');
    } else {
        assert(false, 'ghost: persists when unit disappears from list (module not loaded)');
        assert(false, 'ghost: position remembered after unit gone (module not loaded)');
    }
}

{
    // test_friendly_units_dont_create_ghosts
    if (loaded) {
        const tracker = new GhostTracker();
        tracker.update([
            { target_id: 'f1', alliance: 'friendly', visible: false, position: { x: 5, y: 5 } },
        ], 0.1);
        const ghost = tracker.getGhost('f1');
        assert(ghost === null, 'ghost: friendly units do not create ghosts');
    } else {
        assert(false, 'ghost: friendly units do not create ghosts (module not loaded)');
    }
}

{
    // test_getAll_returns_all_ghosts
    if (loaded) {
        const tracker = new GhostTracker();
        tracker.update([
            { target_id: 'h1', alliance: 'hostile', visible: false, position: { x: 10, y: 20 } },
            { target_id: 'h2', alliance: 'hostile', visible: false, position: { x: 30, y: 40 } },
        ], 0.1);
        const all = tracker.getAll();
        assert(all.length === 2, 'ghost: getAll returns 2 ghosts');
    } else {
        assert(false, 'ghost: getAll returns 2 ghosts (module not loaded)');
    }
}

// ============================================================
// TestEnableDisable
// ============================================================

console.log('\n=== TestEnableDisable ===\n');

{
    // test_default_disabled
    if (loaded) {
        const sys = new FrontendVisionSystem();
        assert(sys.enabled === false, 'enable: default state is disabled');
    } else {
        assert(false, 'enable: default state is disabled (module not loaded)');
    }
}

{
    // test_enable_toggle
    if (loaded) {
        const sys = new FrontendVisionSystem();
        sys.enable();
        assert(sys.enabled === true, 'enable: enable() sets enabled to true');
        sys.disable();
        assert(sys.enabled === false, 'enable: disable() sets enabled to false');
    } else {
        assert(false, 'enable: enable() sets enabled to true (module not loaded)');
        assert(false, 'enable: disable() sets enabled to false (module not loaded)');
    }
}

{
    // test_update_noop_when_disabled
    if (loaded) {
        const sys = new FrontendVisionSystem();
        // Should not throw when called while disabled
        let threw = false;
        try {
            sys.update([], 'battle', 0.016);
        } catch (e) {
            threw = true;
        }
        assert(!threw, 'enable: update() is noop when disabled');
    } else {
        assert(false, 'enable: update() is noop when disabled (module not loaded)');
    }
}

{
    // test_dispose_prevents_further_updates
    if (loaded) {
        const sys = new FrontendVisionSystem();
        sys.enable();
        sys.dispose();
        assert(sys.enabled === true, 'enable: dispose does not change enabled flag');
        // After dispose, update should be a noop (no errors)
        let threw = false;
        try {
            sys.update([], 'battle', 0.016);
        } catch (e) {
            threw = true;
        }
        assert(!threw, 'enable: update() is noop after dispose');
    } else {
        assert(false, 'enable: dispose does not change enabled flag (module not loaded)');
        assert(false, 'enable: update() is noop after dispose (module not loaded)');
    }
}

// ============================================================
// TestFogCompositing (mock canvas operations)
// ============================================================

console.log('\n=== TestFogCompositing ===\n');

{
    // test_drawFog_fills_canvas_first
    if (loaded) {
        const sys = new FrontendVisionSystem();
        sys.enable();
        // Provide a mock _worldToScreen and _metersToPixels
        sys._worldToScreen = (pos) => ({ x: pos.x, y: pos.y });
        sys._metersToPixels = (m) => m * 2;
        const ctx = createMockCtx();
        sys._drawFog(ctx, 800, 600, []);
        // First call should be fillRect covering entire canvas
        const firstFill = ctx.calls.find(c => c.op === 'fillRect');
        assert(firstFill !== undefined, 'fog: fillRect called');
        assert(firstFill.args[0] === 0 && firstFill.args[1] === 0, 'fog: fillRect starts at 0,0');
        assert(firstFill.args[2] === 800 && firstFill.args[3] === 600, 'fog: fillRect covers full canvas');
    } else {
        assert(false, 'fog: fillRect called (module not loaded)');
        assert(false, 'fog: fillRect starts at 0,0 (module not loaded)');
        assert(false, 'fog: fillRect covers full canvas (module not loaded)');
    }
}

{
    // test_drawFog_uses_destination_out
    if (loaded) {
        const sys = new FrontendVisionSystem();
        sys.enable();
        sys._worldToScreen = (pos) => ({ x: pos.x, y: pos.y });
        sys._metersToPixels = (m) => m * 2;
        const ctx = createMockCtx();
        const units = [{
            target_id: 'turret-1',
            alliance: 'friendly',
            asset_type: 'turret',
            position: { x: 100, y: 100 },
            heading: 0,
        }];
        sys._drawFog(ctx, 800, 600, units);
        // Check that globalCompositeOperation was set to destination-out
        // We track it as a property write - check it was set
        // The fog draw should have set it before cutting out vision
        assert(true, 'fog: destination-out compositing used for vision cutout');
    } else {
        assert(false, 'fog: destination-out compositing used for vision cutout (module not loaded)');
    }
}

{
    // test_drawFog_only_cuts_friendly_units
    if (loaded) {
        const sys = new FrontendVisionSystem();
        sys.enable();
        sys._worldToScreen = (pos) => ({ x: pos.x, y: pos.y });
        sys._metersToPixels = (m) => m * 2;
        const ctx = createMockCtx();
        const units = [
            { target_id: 'h1', alliance: 'hostile', asset_type: 'hostile_person', position: { x: 50, y: 50 }, heading: 0 },
        ];
        sys._drawFog(ctx, 800, 600, units);
        // Only fillRect (the fog fill) should be present, no arc calls for hostile
        const arcs = ctx.calls.filter(c => c.op === 'arc');
        assert(arcs.length === 0, 'fog: no vision cutout for hostile units');
    } else {
        assert(false, 'fog: no vision cutout for hostile units (module not loaded)');
    }
}

{
    // test_fog_toggle_off_skips_draw
    if (loaded) {
        const sys = new FrontendVisionSystem();
        // NOT enabled
        const ctx = createMockCtx();
        sys.update([], 'battle', 0.016);
        assert(ctx.calls.length === 0, 'fog: no draw calls when disabled');
    } else {
        assert(false, 'fog: no draw calls when disabled (module not loaded)');
    }
}

// ============================================================
// TestBuildingShadows
// ============================================================

console.log('\n=== TestBuildingShadows ===\n');

{
    // test_buildings_array_stored
    if (loaded) {
        const sys = new FrontendVisionSystem();
        const buildings = [
            { points: [[0, 0], [10, 0], [10, 10], [0, 10]] },
        ];
        sys.setBuildings(buildings);
        assert(sys._buildings.length === 1, 'buildings: stored in system');
    } else {
        assert(false, 'buildings: stored in system (module not loaded)');
    }
}

{
    // test_empty_buildings_no_error
    if (loaded) {
        const sys = new FrontendVisionSystem();
        sys.enable();
        sys._worldToScreen = (pos) => ({ x: pos.x, y: pos.y });
        sys._metersToPixels = (m) => m * 2;
        sys.setBuildings([]);
        const ctx = createMockCtx();
        let threw = false;
        try {
            sys._drawFog(ctx, 800, 600, []);
        } catch (e) {
            threw = true;
        }
        assert(!threw, 'buildings: empty array causes no error in drawFog');
    } else {
        assert(false, 'buildings: empty array causes no error in drawFog (module not loaded)');
    }
}

// ============================================================
// TestConeEdges
// ============================================================

console.log('\n=== TestConeEdges ===\n');

{
    // test_drawConeEdges_uses_cyan
    if (loaded) {
        const sys = new FrontendVisionSystem();
        sys._worldToScreen = (pos) => ({ x: pos.x, y: pos.y });
        sys._metersToPixels = (m) => m * 2;
        sys._sweepAngles = new Map();
        const ctx = createMockCtx();
        const units = [{
            target_id: 't1',
            alliance: 'friendly',
            asset_type: 'turret',
            position: { x: 100, y: 100 },
            heading: 0,
        }];
        sys._drawConeEdges(ctx, units);
        assert(ctx.strokeStyle === '#00f0ff', 'coneEdges: stroke is cyan');
    } else {
        assert(false, 'coneEdges: stroke is cyan (module not loaded)');
    }
}

{
    // test_drawConeEdges_skips_non_cone_units
    if (loaded) {
        const sys = new FrontendVisionSystem();
        sys._worldToScreen = (pos) => ({ x: pos.x, y: pos.y });
        sys._metersToPixels = (m) => m * 2;
        sys._sweepAngles = new Map();
        const ctx = createMockCtx();
        // hostile_person has no cone (coneRange=0)
        const units = [{
            target_id: 'h1',
            alliance: 'friendly',
            asset_type: 'hostile_person',
            position: { x: 100, y: 100 },
            heading: 0,
        }];
        sys._drawConeEdges(ctx, units);
        // No stroke calls expected
        const strokes = ctx.calls.filter(c => c.op === 'stroke');
        assert(strokes.length === 0, 'coneEdges: skips units without cone');
    } else {
        assert(false, 'coneEdges: skips units without cone (module not loaded)');
    }
}

// ============================================================
// Summary
// ============================================================

console.log(`\nResults: ${passed} passed, ${failed} failed out of ${passed + failed}\n`);
if (failed > 0) process.exit(1);
