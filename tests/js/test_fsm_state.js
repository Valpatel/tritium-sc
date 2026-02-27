/**
 * TRITIUM-SC -- FSM state display tests
 * Run: node tests/js/test_fsm_state.js
 *
 * Tests:
 * - FSM state color map completeness
 * - Units panel: fsm_state badge renders in list items
 * - Units panel: fsm_state row renders in detail view
 * - Map: FSM badge colors are defined for all states
 * - Tooltip: fsm_state line renders
 * - Websocket: _updateUnit passes fsm_state through
 */

const fs = require('fs');
const vm = require('vm');

let passed = 0, failed = 0;
function assert(cond, msg) {
    if (!cond) { console.error('FAIL:', msg); failed++; }
    else { console.log('PASS:', msg); passed++; }
}

// All possible FSM states from the backend
const ALL_FSM_STATES = [
    'idle', 'scanning', 'tracking', 'engaging', 'cooldown',
    'patrolling', 'pursuing', 'retreating', 'rtb', 'scouting',
    'orbiting', 'spawning', 'advancing', 'flanking', 'fleeing',
];

// ============================================================
// Load units.js to extract FSM_STATE_COLORS
// ============================================================

const unitsSrc = fs.readFileSync(__dirname + '/../../frontend/js/command/panels/units.js', 'utf8');

// Extract FSM_STATE_COLORS object from the source
const fsmColorsMatch = unitsSrc.match(/const FSM_STATE_COLORS\s*=\s*\{([^}]+)\}/);
assert(!!fsmColorsMatch, 'FSM_STATE_COLORS object found in units.js');

// Parse the color entries
const unitsFsmColors = {};
if (fsmColorsMatch) {
    const entries = fsmColorsMatch[1].matchAll(/(\w+)\s*:\s*'([^']+)'/g);
    for (const m of entries) {
        unitsFsmColors[m[1]] = m[2];
    }
}

// ============================================================
// Load map.js to extract FSM_BADGE_COLORS
// ============================================================

const mapSrc = fs.readFileSync(__dirname + '/../../frontend/js/command/map.js', 'utf8');
const fsmBadgeMatch = mapSrc.match(/const FSM_BADGE_COLORS\s*=\s*\{([^}]+)\}/);
assert(!!fsmBadgeMatch, 'FSM_BADGE_COLORS object found in map.js');

const mapFsmColors = {};
if (fsmBadgeMatch) {
    const entries = fsmBadgeMatch[1].matchAll(/(\w+)\s*:\s*'([^']+)'/g);
    for (const m of entries) {
        mapFsmColors[m[1]] = m[2];
    }
}

// ============================================================
// Test: All FSM states have colors in units.js
// ============================================================

console.log('\n--- FSM_STATE_COLORS completeness (units.js) ---');

for (const state of ALL_FSM_STATES) {
    assert(state in unitsFsmColors, `FSM_STATE_COLORS has color for "${state}"`);
}

// ============================================================
// Test: All FSM states have colors in map.js
// ============================================================

console.log('\n--- FSM_BADGE_COLORS completeness (map.js) ---');

for (const state of ALL_FSM_STATES) {
    assert(state in mapFsmColors, `FSM_BADGE_COLORS has color for "${state}"`);
}

// ============================================================
// Test: Colors match between units.js and map.js
// ============================================================

console.log('\n--- Color consistency ---');

for (const state of ALL_FSM_STATES) {
    if (unitsFsmColors[state] && mapFsmColors[state]) {
        assert(unitsFsmColors[state] === mapFsmColors[state],
            `Color for "${state}" matches: ${unitsFsmColors[state]}`);
    }
}

// ============================================================
// Test: units.js renders FSM badge in list HTML
// ============================================================

console.log('\n--- Units panel list badge ---');

// The render function builds HTML with unit-fsm-badge class
assert(unitsSrc.includes('unit-fsm-badge'), 'units.js contains unit-fsm-badge class');
assert(unitsSrc.includes('FSM_STATE_COLORS[fsm]'), 'units.js uses FSM_STATE_COLORS for badge color');
assert(unitsSrc.includes('fsm.toUpperCase()'), 'units.js uppercases FSM state text in badge');

// ============================================================
// Test: units.js renders FSM row in detail view
// ============================================================

console.log('\n--- Units panel detail FSM row ---');

assert(unitsSrc.includes("panel-stat-label\">FSM</span>"), 'units.js detail view has FSM label');
assert(unitsSrc.includes('fsmState.toUpperCase()'), 'units.js detail uppercases FSM state');
assert(unitsSrc.includes('fsmColor'), 'units.js detail uses fsmColor variable');

// ============================================================
// Test: map.js tooltip includes fsm_state
// ============================================================

console.log('\n--- Map tooltip FSM ---');

assert(mapSrc.includes('fsmState'), 'map.js tooltip builds fsmState variable');
assert(mapSrc.includes("FSM_BADGE_COLORS[u.fsm_state]"), 'map.js tooltip uses FSM_BADGE_COLORS');
assert(mapSrc.includes('fsmState + elims'), 'map.js tooltip includes fsmState in output');

// ============================================================
// Test: map.js status badges prefer fsm_state
// ============================================================

console.log('\n--- Map status badges ---');

assert(mapSrc.includes('unit.fsm_state'), 'map.js badge reads unit.fsm_state');
assert(mapSrc.includes('FSM_BADGE_COLORS[fsm]'), 'map.js badge uses FSM_BADGE_COLORS');
assert(mapSrc.includes("const badgeText = fsm || status"), 'map.js badge prefers fsm over status');

// ============================================================
// Test: websocket.js passes fsm_state
// ============================================================

console.log('\n--- Websocket fsm_state passthrough ---');

const wsSrc = fs.readFileSync(__dirname + '/../../frontend/js/command/websocket.js', 'utf8');
assert(wsSrc.includes('fsm_state = t.fsm_state'), 'websocket.js passes fsm_state from telemetry');

// ============================================================
// Test: CSS has unit-fsm-badge style
// ============================================================

console.log('\n--- CSS badge styling ---');

const cssSrc = fs.readFileSync(__dirname + '/../../frontend/css/panels.css', 'utf8');
assert(cssSrc.includes('.unit-fsm-badge'), 'panels.css has .unit-fsm-badge rule');
assert(cssSrc.includes('font-size: 0.5rem'), 'FSM badge uses small font');

// ============================================================
// Test: FSM color values are valid hex colors
// ============================================================

console.log('\n--- Color validity ---');

const hexPattern = /^#[0-9a-f]{6}$/i;
for (const [state, color] of Object.entries(unitsFsmColors)) {
    assert(hexPattern.test(color), `FSM color for "${state}" is valid hex: ${color}`);
}

// ============================================================
// Test: Engaging/combat states use warm colors (red/magenta)
// ============================================================

console.log('\n--- Semantic color checks ---');

assert(unitsFsmColors.engaging === '#ff2a6d', 'engaging uses magenta/red');
assert(unitsFsmColors.patrolling === '#05ffa1', 'patrolling uses green');
assert(unitsFsmColors.idle === '#888888', 'idle uses dim gray');
assert(unitsFsmColors.retreating === '#fcee0a', 'retreating uses yellow (warning)');
assert(unitsFsmColors.tracking === '#00f0ff', 'tracking uses cyan');

// ============================================================
// Results
// ============================================================

console.log(`\n=== FSM State Display Tests: ${passed} passed, ${failed} failed ===`);
process.exit(failed > 0 ? 1 : 0);
