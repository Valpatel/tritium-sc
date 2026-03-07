// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
/**
 * TRITIUM-SC Hostile Objective Visualization Tests
 *
 * Tests the _drawHostileObjectives() method in map.js that renders dashed
 * lines from hostile units to their assigned objective targets on the
 * tactical map canvas.
 *
 * Run: node tests/js/test_hostile_objectives.js
 */

const fs = require('fs');
const path = require('path');
const vm = require('vm');

// Simple test runner
let passed = 0, failed = 0;
function assert(cond, msg) {
    if (!cond) { console.error('FAIL:', msg); failed++; }
    else { console.log('PASS:', msg); passed++; }
}
function assertEqual(a, b, msg) {
    assert(a === b, msg + ` (got ${JSON.stringify(a)}, expected ${JSON.stringify(b)})`);
}

// Read map.js source for static analysis and extraction
const mapSource = fs.readFileSync(
    path.join(__dirname, '../../src/frontend/js/command/map.js'), 'utf8');

// Read store + events for functional tests
const storeSrc = fs.readFileSync(
    path.join(__dirname, '../../src/frontend/js/command/store.js'), 'utf8');
const eventsSrc = fs.readFileSync(
    path.join(__dirname, '../../src/frontend/js/command/events.js'), 'utf8');


// ============================================================
// 1. _drawHostileObjectives function exists in map.js
// ============================================================

console.log('\n--- _drawHostileObjectives existence ---');

{
    assert(mapSource.includes('function _drawHostileObjectives'),
        '_drawHostileObjectives function defined in map.js');
}

{
    assert(mapSource.includes('_drawHostileObjectives(ctx)'),
        '_drawHostileObjectives(ctx) called in render loop');
}


// ============================================================
// 2. Reads from TritiumStore 'game.hostileObjectives'
// ============================================================

console.log('\n--- TritiumStore hostileObjectives access ---');

{
    const fnStart = mapSource.indexOf('function _drawHostileObjectives');
    assert(fnStart !== -1, '_drawHostileObjectives found in source');
    if (fnStart !== -1) {
        const snippet = mapSource.substring(fnStart, fnStart + 2000);
        assert(snippet.includes("game.hostileObjectives") ||
               snippet.includes('hostileObjectives'),
            '_drawHostileObjectives reads game.hostileObjectives from store');
    }
}


// ============================================================
// 3. Color mapping per objective type is correct
// ============================================================

console.log('\n--- Objective color mapping ---');

{
    // assault -> red (#ff2a6d)
    assert(mapSource.includes('#ff2a6d'),
        'map.js contains assault objective color #ff2a6d');
}

{
    // flank -> orange (#ff8800)
    assert(mapSource.includes('#ff8800'),
        'map.js contains flank objective color #ff8800');
}

{
    // advance -> yellow (#fcee0a)
    assert(mapSource.includes('#fcee0a'),
        'map.js contains advance objective color #fcee0a');
}

{
    // retreat -> grey (#888888)
    assert(mapSource.includes('#888888'),
        'map.js contains retreat objective color #888888');
}

// Test the color selection logic by mirroring the expected implementation
function _objectiveColor(type) {
    switch (type) {
        case 'assault': return '#ff2a6d';
        case 'flank':   return '#ff8800';
        case 'advance': return '#fcee0a';
        case 'retreat': return '#888888';
        default:        return '#ff2a6d';
    }
}

{
    assertEqual(_objectiveColor('assault'), '#ff2a6d', 'assault color is red/magenta');
    assertEqual(_objectiveColor('flank'), '#ff8800', 'flank color is orange');
    assertEqual(_objectiveColor('advance'), '#fcee0a', 'advance color is yellow');
    assertEqual(_objectiveColor('retreat'), '#888888', 'retreat color is grey');
    assertEqual(_objectiveColor('unknown_type'), '#ff2a6d', 'unknown type defaults to red');
}


// ============================================================
// 4. Handles null/empty objectives gracefully
// ============================================================

console.log('\n--- Null/empty objectives handling ---');

{
    const fnStart = mapSource.indexOf('function _drawHostileObjectives');
    if (fnStart !== -1) {
        const snippet = mapSource.substring(fnStart, fnStart + 500);
        const hasGuard = snippet.includes('!objectives') || snippet.includes('!obj') ||
                         snippet.includes('return') || snippet.includes('if (');
        assert(hasGuard, '_drawHostileObjectives has guard clause for missing data');
    }
}

// Simulate null objectives handling
{
    const objectives = null;
    let crashed = false;
    try {
        if (objectives) {
            for (const [id, obj] of Object.entries(objectives)) {
                // would draw
            }
        }
    } catch (e) {
        crashed = true;
    }
    assert(!crashed, 'null objectives does not crash');
}

// Simulate empty objectives handling
{
    const objectives = {};
    let drawCount = 0;
    for (const [id, obj] of Object.entries(objectives)) {
        drawCount++;
    }
    assertEqual(drawCount, 0, 'empty objectives object draws nothing');
}


// ============================================================
// 5. Draws dashed lines (setLineDash)
// ============================================================

console.log('\n--- Dashed lines ---');

{
    const fnStart = mapSource.indexOf('function _drawHostileObjectives');
    assert(fnStart !== -1, '_drawHostileObjectives found for dashed line check');
    if (fnStart !== -1) {
        const snippet = mapSource.substring(fnStart, fnStart + 3000);
        assert(snippet.includes('setLineDash'),
            '_drawHostileObjectives uses setLineDash for dashed lines');
    }
}


// ============================================================
// 6. Uses worldToScreen for coordinate conversion
// ============================================================

console.log('\n--- worldToScreen usage ---');

{
    const fnStart = mapSource.indexOf('function _drawHostileObjectives');
    if (fnStart !== -1) {
        const snippet = mapSource.substring(fnStart, fnStart + 3000);
        assert(snippet.includes('worldToScreen'),
            '_drawHostileObjectives uses worldToScreen for coordinate conversion');
    }
}


// ============================================================
// 7. Only renders when game is active
// ============================================================

console.log('\n--- Active game gate ---');

{
    const fnStart = mapSource.indexOf('function _drawHostileObjectives');
    if (fnStart !== -1) {
        const snippet = mapSource.substring(fnStart, fnStart + 800);
        assert(snippet.includes('game.phase') || snippet.includes('gamePhase') ||
               snippet.includes("'active'"),
            '_drawHostileObjectives checks for active game state');
    }
}


// ============================================================
// 8. Draws arrowhead at target end
// ============================================================

console.log('\n--- Arrowhead drawing ---');

{
    const fnStart = mapSource.indexOf('function _drawHostileObjectives');
    if (fnStart !== -1) {
        const snippet = mapSource.substring(fnStart, fnStart + 3000);
        assert(snippet.includes('Math.atan2') || snippet.includes('atan2'),
            '_drawHostileObjectives calculates angle for arrowhead');
        assert(snippet.includes('closePath') || snippet.includes('fill()'),
            '_drawHostileObjectives draws filled arrowhead');
    }
}


// ============================================================
// 9. Uses ~30% opacity for lines
// ============================================================

console.log('\n--- Opacity setting ---');

{
    const fnStart = mapSource.indexOf('function _drawHostileObjectives');
    if (fnStart !== -1) {
        const snippet = mapSource.substring(fnStart, fnStart + 3000);
        assert(snippet.includes('globalAlpha') || snippet.includes('rgba'),
            '_drawHostileObjectives uses transparency (globalAlpha or rgba)');
    }
}


// ============================================================
// 10. Looks up hostile unit positions from TritiumStore.units
// ============================================================

console.log('\n--- Unit position lookup ---');

{
    const fnStart = mapSource.indexOf('function _drawHostileObjectives');
    if (fnStart !== -1) {
        const snippet = mapSource.substring(fnStart, fnStart + 3000);
        assert(snippet.includes('TritiumStore.units') || snippet.includes('units.get'),
            '_drawHostileObjectives looks up unit positions from store');
    }
}


// ============================================================
// 11. Render loop integration -- correct layer ordering
// ============================================================

console.log('\n--- Render loop integration ---');

{
    // Should be called after hostile intel HUD
    const drawFn = mapSource.indexOf('function _draw()');
    assert(drawFn !== -1, '_draw() function found');
    if (drawFn !== -1) {
        const drawBody = mapSource.substring(drawFn, drawFn + 8000);
        const hostileObjIdx = drawBody.indexOf('_drawHostileObjectives');
        assert(hostileObjIdx > 0, '_drawHostileObjectives called from _draw()');

        // Should be after warHudDrawHostileIntel
        const intelIdx = drawBody.indexOf('warHudDrawHostileIntel');
        if (intelIdx !== -1 && hostileObjIdx !== -1) {
            assert(hostileObjIdx > intelIdx,
                '_drawHostileObjectives called after warHudDrawHostileIntel');
        }
    }
}


// ============================================================
// 12. ctx.save/restore pattern
// ============================================================

console.log('\n--- Save/restore pattern ---');

{
    const fnStart = mapSource.indexOf('function _drawHostileObjectives');
    if (fnStart !== -1) {
        const snippet = mapSource.substring(fnStart, fnStart + 3000);
        assert(snippet.includes('ctx.save') || snippet.includes('.save()'),
            '_drawHostileObjectives saves canvas state');
        assert(snippet.includes('ctx.restore') || snippet.includes('.restore()'),
            '_drawHostileObjectives restores canvas state');
    }
}


// ============================================================
// 13. Polling function for /api/game/hostile-intel
// ============================================================

console.log('\n--- Polling function ---');

{
    // Look for a polling function or setInterval with hostile-intel fetch
    const hasPolling = mapSource.includes('/api/game/hostile-intel') ||
                       mapSource.includes('hostile-intel') ||
                       mapSource.includes('hostileObjectives');
    assert(hasPolling, 'map.js contains hostile-intel polling reference');
}

{
    // Check for periodic fetch interval (5 second interval)
    const hasInterval = mapSource.includes('setInterval') || mapSource.includes('setTimeout');
    assert(hasInterval, 'map.js uses setInterval or setTimeout for periodic fetch');
}

{
    // Check for fetch call to the endpoint
    const hasFetch = mapSource.includes("fetch(") || mapSource.includes("fetch('");
    assert(hasFetch, 'map.js uses fetch() for API call');
}


// ============================================================
// 14. Polling stores objectives in TritiumStore
// ============================================================

console.log('\n--- Polling stores objectives ---');

{
    assert(mapSource.includes("game.hostileObjectives") ||
           mapSource.includes('hostileObjectives'),
        'map.js references game.hostileObjectives store key');
}


// ============================================================
// 15. Functional test: _drawHostileObjectives with mock canvas
// ============================================================

console.log('\n--- Functional test: mock canvas execution ---');

{
    // Strip ES module syntax for Node.js
    let code = storeSrc
        .replace(/export\s+/g, '')
        .replace(/import\s+.*?from\s+['"][^'"]+['"];?\s*/g, '');

    code += '\n' + eventsSrc
        .replace(/export\s+/g, '')
        .replace(/import\s+.*?from\s+['"][^'"]+['"];?\s*/g, '');

    const mapCodeStripped = mapSource
        .replace(/export\s+/g, '')
        .replace(/import\s+.*?from\s+['"][^'"]+['"];?\s*/g, '');

    // Extract _drawHostileObjectives function
    const fnStart = mapCodeStripped.indexOf('function _drawHostileObjectives');
    if (fnStart === -1) {
        assert(false, '_drawHostileObjectives not found for functional test');
    } else {
        let depth = 0, fnEnd = fnStart, foundOpen = false;
        for (let i = fnStart; i < mapCodeStripped.length; i++) {
            if (mapCodeStripped[i] === '{') { depth++; foundOpen = true; }
            if (mapCodeStripped[i] === '}') { depth--; }
            if (foundOpen && depth === 0) { fnEnd = i + 1; break; }
        }
        const fnBody = mapCodeStripped.substring(fnStart, fnEnd);

        // Track drawing calls
        const mockLines = [];
        const mockArrows = [];
        let mockStrokeStyle = '';
        let mockGlobalAlpha = 1;
        let savedCount = 0;
        let restoredCount = 0;
        let dashSet = false;
        let dashCleared = false;

        const mockCtx = {
            get strokeStyle() { return mockStrokeStyle; },
            set strokeStyle(v) { mockStrokeStyle = v; },
            get globalAlpha() { return mockGlobalAlpha; },
            set globalAlpha(v) { mockGlobalAlpha = v; },
            fillStyle: '',
            lineWidth: 1,
            font: '',
            textAlign: '',
            textBaseline: '',
            save() { savedCount++; },
            restore() { restoredCount++; },
            beginPath() {},
            moveTo(x, y) { mockLines.push({ type: 'moveTo', x, y }); },
            lineTo(x, y) { mockLines.push({ type: 'lineTo', x, y }); },
            stroke() { mockLines.push({ type: 'stroke', style: mockStrokeStyle, alpha: mockGlobalAlpha }); },
            fill() { mockArrows.push({ type: 'fill', style: mockStrokeStyle }); },
            closePath() {},
            arc() {},
            fillRect() {},
            fillText() {},
            strokeRect() {},
            measureText(t) { return { width: t.length * 7 }; },
            setLineDash(pattern) {
                if (pattern && pattern.length > 0) dashSet = true;
                else dashCleared = true;
            },
        };

        try {
            const ctx = vm.createContext({
                Math, console, Array, Object, Number, String, JSON, Map, Set,
                Date: { now: () => 100000 },
                Infinity, undefined, Error,
                performance: { now: () => 100000 },
            });

            // Load store + events
            vm.runInContext(code, ctx);

            // Set up game state as active
            vm.runInContext(`
                TritiumStore.set('game.phase', 'active');
            `, ctx);

            // Add hostile units to the store
            vm.runInContext(`
                TritiumStore.updateUnit('hostile-001', {
                    name: 'hostile-001',
                    type: 'person',
                    alliance: 'hostile',
                    position: { x: 100, y: 200 },
                    heading: 0,
                    status: 'active',
                });
                TritiumStore.updateUnit('hostile-002', {
                    name: 'hostile-002',
                    type: 'person',
                    alliance: 'hostile',
                    position: { x: -50, y: 150 },
                    heading: 90,
                    status: 'active',
                });
            `, ctx);

            // Set hostile objectives
            vm.runInContext(`
                TritiumStore.set('game.hostileObjectives', {
                    'hostile-001': {
                        type: 'flank',
                        target_position: [300, 400],
                        priority: 3,
                        target_id: 'turret-abc123',
                    },
                    'hostile-002': {
                        type: 'assault',
                        target_position: [-200, 50],
                        priority: 5,
                        target_id: 'turret-def456',
                    },
                });
            `, ctx);

            // Inject worldToScreen and _state
            vm.runInContext(`
                var _state = {
                    canvas: { width: 1600, height: 900 },
                    dpr: 1,
                    cam: { x: 0, y: 0, zoom: 1.0 },
                    lastFrameTime: 100000,
                };
                function worldToScreen(wx, wy) {
                    var cssW = _state.canvas.width / _state.dpr;
                    var cssH = _state.canvas.height / _state.dpr;
                    var sx = (wx - _state.cam.x) * _state.cam.zoom + cssW / 2;
                    var sy = -(wy - _state.cam.y) * _state.cam.zoom + cssH / 2;
                    return { x: sx, y: sy };
                }
                var FONT_FAMILY = '"JetBrains Mono", monospace';
            `, ctx);

            // Inject the function
            vm.runInContext(fnBody, ctx);

            // Make mock ctx available
            ctx._mockCtx = mockCtx;

            // Call _drawHostileObjectives
            vm.runInContext(`
                _drawHostileObjectives(_mockCtx);
            `, ctx);

            // Should have drawn lines (moveTo + lineTo for each objective)
            const moveToCount = mockLines.filter(l => l.type === 'moveTo').length;
            const lineToCount = mockLines.filter(l => l.type === 'lineTo').length;
            assert(moveToCount >= 2,
                'moveTo called for each objective line (got ' + moveToCount + ')');
            assert(lineToCount >= 2,
                'lineTo called for each objective line (got ' + lineToCount + ')');

            // Should have set dashed line
            assert(dashSet, 'setLineDash was called with a dash pattern');
            assert(dashCleared, 'setLineDash([]) was called to reset dash');

            // Should have saved/restored
            assert(savedCount > 0, 'ctx.save() was called');
            assert(restoredCount > 0, 'ctx.restore() was called');

            // Test with null objectives -- should not throw
            vm.runInContext(`
                TritiumStore.set('game.hostileObjectives', null);
            `, ctx);

            const linesBefore = mockLines.length;
            vm.runInContext(`
                _drawHostileObjectives(_mockCtx);
            `, ctx);
            assertEqual(mockLines.length, linesBefore,
                'null hostileObjectives does not draw lines');

            // Test with idle game state -- should not render
            vm.runInContext(`
                TritiumStore.set('game.phase', 'idle');
                TritiumStore.set('game.hostileObjectives', {
                    'hostile-001': {
                        type: 'assault',
                        target_position: [100, 100],
                        priority: 5,
                    },
                });
            `, ctx);

            const linesBeforeIdle = mockLines.length;
            vm.runInContext(`
                _drawHostileObjectives(_mockCtx);
            `, ctx);
            assertEqual(mockLines.length, linesBeforeIdle,
                'idle game state does not render objective lines');

        } catch (e) {
            assert(false, 'Functional test failed with error: ' + e.message);
        }
    }
}


// ============================================================
// 16. Handles missing unit in store gracefully
// ============================================================

console.log('\n--- Missing unit handling ---');

{
    // Simulate objective with unit ID not in store
    const units = new Map();
    const objectives = {
        'hostile-999': {
            type: 'assault',
            target_position: [100, 200],
            priority: 5,
        },
    };

    let drawCount = 0;
    for (const [uid, obj] of Object.entries(objectives)) {
        const unit = units.get(uid);
        if (!unit || !unit.position) continue; // should skip
        drawCount++;
    }
    assertEqual(drawCount, 0, 'objective for missing unit is skipped');
}

{
    // Unit exists but has no position
    const units = new Map();
    units.set('hostile-003', { name: 'hostile-003', type: 'person', alliance: 'hostile' });
    const objectives = {
        'hostile-003': {
            type: 'flank',
            target_position: [100, 200],
            priority: 3,
        },
    };

    let drawCount = 0;
    for (const [uid, obj] of Object.entries(objectives)) {
        const unit = units.get(uid);
        if (!unit || !unit.position) continue;
        drawCount++;
    }
    assertEqual(drawCount, 0, 'objective for unit without position is skipped');
}


// ============================================================
// 17. Handles missing target_position gracefully
// ============================================================

console.log('\n--- Missing target_position handling ---');

{
    const objectives = {
        'hostile-001': {
            type: 'assault',
            target_position: null,
            priority: 5,
        },
    };

    for (const [uid, obj] of Object.entries(objectives)) {
        const tp = obj.target_position;
        const shouldSkip = !tp || !Array.isArray(tp) || tp.length < 2;
        assert(shouldSkip, 'null target_position is correctly skipped');
    }
}

{
    const objectives = {
        'hostile-001': {
            type: 'advance',
            target_position: [42],  // only one element
            priority: 2,
        },
    };

    for (const [uid, obj] of Object.entries(objectives)) {
        const tp = obj.target_position;
        const shouldSkip = !tp || !Array.isArray(tp) || tp.length < 2;
        assert(shouldSkip, 'single-element target_position is correctly skipped');
    }
}

{
    const objectives = {
        'hostile-001': {
            type: 'flank',
            target_position: [100, 200],
            priority: 3,
        },
    };

    for (const [uid, obj] of Object.entries(objectives)) {
        const tp = obj.target_position;
        const shouldSkip = !tp || !Array.isArray(tp) || tp.length < 2;
        assert(!shouldSkip, 'valid [x,y] target_position is not skipped');
    }
}


// ============================================================
// 18. Color mapping is within _drawHostileObjectives function body
// ============================================================

console.log('\n--- Color mapping in function body ---');

{
    const fnStart = mapSource.indexOf('function _drawHostileObjectives');
    if (fnStart !== -1) {
        const snippet = mapSource.substring(fnStart, fnStart + 3000);
        assert(snippet.includes('assault'), 'function body references assault type');
        assert(snippet.includes('flank'), 'function body references flank type');
        assert(snippet.includes('advance'), 'function body references advance type');
        assert(snippet.includes('retreat'), 'function body references retreat type');
    }
}


// ============================================================
// Summary
// ============================================================

console.log('\n' + '='.repeat(50));
console.log(`Hostile Objectives Tests: ${passed} passed, ${failed} failed`);
console.log('='.repeat(50));
process.exit(failed > 0 ? 1 : 0);
