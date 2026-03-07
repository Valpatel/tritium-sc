// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
/**
 * TRITIUM-SC -- Morale marker visual indicator tests
 * Run: node tests/js/test_morale_markers.js
 *
 * Tests:
 * - _getMoraleState returns correct states at thresholds
 * - CSS class assignment for each state
 * - Badge text content for each state
 * - Null/undefined morale handling
 * - Threshold boundary tests (0.1, 0.3, 0.9 exactly)
 * - Tooltip text for morale states
 * - CSS keyframes and rules exist in command.css
 * - Injected CSS includes morale rules in map-maplibre.js
 */

const fs = require('fs');
const vm = require('vm');

let passed = 0, failed = 0;
function assert(cond, msg) {
    if (!cond) { console.error('FAIL:', msg); failed++; }
    else { console.log('PASS:', msg); passed++; }
}

// ============================================================
// Extract _getMoraleState from map-maplibre.js source
// ============================================================

const mapSrc = fs.readFileSync(__dirname + '/../../src/frontend/js/command/map-maplibre.js', 'utf8');

// Extract the function body
const fnMatch = mapSrc.match(/function _getMoraleState\(morale\)\s*\{([\s\S]*?)\n\}/);
assert(!!fnMatch, '_getMoraleState function found in map-maplibre.js');

// Build a runnable version
let _getMoraleState;
if (fnMatch) {
    // eslint-disable-next-line no-eval
    _getMoraleState = new Function('morale', fnMatch[1]);
}

// ============================================================
// Test: _getMoraleState returns correct states
// ============================================================

console.log('\n--- _getMoraleState threshold logic ---');

assert(_getMoraleState(0.0) === 'broken', 'morale 0.0 => broken');
assert(_getMoraleState(0.05) === 'broken', 'morale 0.05 => broken');
assert(_getMoraleState(0.09) === 'broken', 'morale 0.09 => broken');
assert(_getMoraleState(0.15) === 'suppressed', 'morale 0.15 => suppressed');
assert(_getMoraleState(0.2) === 'suppressed', 'morale 0.2 => suppressed');
assert(_getMoraleState(0.29) === 'suppressed', 'morale 0.29 => suppressed');
assert(_getMoraleState(0.5) === null, 'morale 0.5 => null (normal)');
assert(_getMoraleState(0.7) === null, 'morale 0.7 => null (normal)');
assert(_getMoraleState(0.85) === null, 'morale 0.85 => null (normal)');
assert(_getMoraleState(0.95) === 'emboldened', 'morale 0.95 => emboldened');
assert(_getMoraleState(1.0) === 'emboldened', 'morale 1.0 => emboldened');

// ============================================================
// Test: Boundary values (exactly at thresholds)
// ============================================================

console.log('\n--- Boundary values ---');

// Backend uses strict < for broken/suppressed, strict > for emboldened
// 0.1 is NOT broken (not < 0.1), but IS suppressed (< 0.3)
assert(_getMoraleState(0.1) === 'suppressed', 'morale 0.1 exactly => suppressed (not broken)');
// 0.3 is NOT suppressed (not < 0.3)
assert(_getMoraleState(0.3) === null, 'morale 0.3 exactly => null (not suppressed)');
// 0.9 is NOT emboldened (not > 0.9)
assert(_getMoraleState(0.9) === null, 'morale 0.9 exactly => null (not emboldened)');

// ============================================================
// Test: Null/undefined/invalid morale handling
// ============================================================

console.log('\n--- Null/undefined/invalid handling ---');

assert(_getMoraleState(undefined) === null, 'undefined morale => null');
assert(_getMoraleState(null) === null, 'null morale => null');
assert(_getMoraleState('high') === null, 'string morale => null');
assert(_getMoraleState(NaN) === null, 'NaN morale => null (NaN comparisons are false)');

// ============================================================
// Test: Badge text content for each state
// ============================================================

console.log('\n--- Badge text content ---');

// Extract _MORALE_BADGE_TEXT from source
const badgeTextMatch = mapSrc.match(/const _MORALE_BADGE_TEXT\s*=\s*\{([\s\S]*?)\};/);
assert(!!badgeTextMatch, '_MORALE_BADGE_TEXT object found in map-maplibre.js');

if (badgeTextMatch) {
    const block = badgeTextMatch[1];
    assert(block.includes('broken'), '_MORALE_BADGE_TEXT has broken entry');
    assert(block.includes('suppressed'), '_MORALE_BADGE_TEXT has suppressed entry');
    assert(block.includes('emboldened'), '_MORALE_BADGE_TEXT has emboldened entry');
}

// ============================================================
// Test: Badge color definitions for each state
// ============================================================

console.log('\n--- Badge color definitions ---');

const badgeColorMatch = mapSrc.match(/const _MORALE_BADGE_COLORS\s*=\s*\{([\s\S]*?)\};/);
assert(!!badgeColorMatch, '_MORALE_BADGE_COLORS object found in map-maplibre.js');

if (badgeColorMatch) {
    const block = badgeColorMatch[1];
    assert(block.includes('#ff2a6d'), 'broken badge color is magenta/red');
    assert(block.includes('#fcee0a'), 'suppressed badge color is yellow');
    assert(block.includes('#00f0ff'), 'emboldened badge color is cyan');
}

// ============================================================
// Test: Tooltip text definitions for each state
// ============================================================

console.log('\n--- Tooltip text definitions ---');

const tooltipMatch = mapSrc.match(/const _MORALE_TOOLTIP_TEXT\s*=\s*\{([\s\S]*?)\};/);
assert(!!tooltipMatch, '_MORALE_TOOLTIP_TEXT object found in map-maplibre.js');

if (tooltipMatch) {
    const block = tooltipMatch[1];
    assert(block.includes("'BROKEN'") || block.includes('"BROKEN"'), 'broken tooltip text is "BROKEN"');
    assert(block.includes("'SUPPRESSED'") || block.includes('"SUPPRESSED"'), 'suppressed tooltip text is "SUPPRESSED"');
    assert(block.includes("'EMBOLDENED'") || block.includes('"EMBOLDENED"'), 'emboldened tooltip text is "EMBOLDENED"');
}

// ============================================================
// Test: CSS class assignment in _updateMarkerElement
// ============================================================

console.log('\n--- CSS class assignment in _updateMarkerElement ---');

assert(mapSrc.includes("'unit-marker-suppressed'"), 'unit-marker-suppressed class referenced in JS');
assert(mapSrc.includes("'unit-marker-broken'"), 'unit-marker-broken class referenced in JS');
assert(mapSrc.includes("'unit-marker-emboldened'"), 'unit-marker-emboldened class referenced in JS');
assert(mapSrc.includes("el.classList.add('unit-marker-' + moraleState)"), 'moraleState class added dynamically');
assert(mapSrc.includes("el.classList.remove(cls)"), 'old morale classes removed before adding new');

// ============================================================
// Test: Morale badge DOM element in _applyMarkerStyle
// ============================================================

console.log('\n--- Morale badge DOM element ---');

assert(mapSrc.includes("morale-badge"), 'morale-badge class used in JS');
assert(mapSrc.includes("_getMoraleState(unit.morale)"), '_getMoraleState called with unit.morale');
assert(mapSrc.includes("_MORALE_BADGE_TEXT[moraleState]"), 'badge text set from _MORALE_BADGE_TEXT');
assert(mapSrc.includes("_MORALE_BADGE_COLORS[moraleState]"), 'badge color set from _MORALE_BADGE_COLORS');

// ============================================================
// Test: Tooltip includes morale state in _updateMarkerElement
// ============================================================

console.log('\n--- Tooltip morale state ---');

assert(mapSrc.includes('_MORALE_TOOLTIP_TEXT[moraleState]'), 'tooltip uses _MORALE_TOOLTIP_TEXT');
assert(mapSrc.includes('el.title = titleParts.join'), 'title attribute set on marker element');

// ============================================================
// Test: window._getMoraleState exposed for testing
// ============================================================

console.log('\n--- Exposed for testing ---');

assert(mapSrc.includes('window._getMoraleState = _getMoraleState'), '_getMoraleState exposed on window');

// ============================================================
// Test: CSS keyframes exist in command.css
// ============================================================

console.log('\n--- CSS keyframes in command.css ---');

const cssSrc = fs.readFileSync(__dirname + '/../../src/frontend/css/command.css', 'utf8');

assert(cssSrc.includes('@keyframes morale-suppressed-pulse'), 'command.css has morale-suppressed-pulse keyframes');
assert(cssSrc.includes('@keyframes morale-broken-pulse'), 'command.css has morale-broken-pulse keyframes');
assert(cssSrc.includes('@keyframes morale-emboldened-glow'), 'command.css has morale-emboldened-glow keyframes');

// ============================================================
// Test: CSS rules for morale classes in command.css
// ============================================================

console.log('\n--- CSS rules in command.css ---');

assert(cssSrc.includes('.unit-marker-suppressed'), 'command.css has .unit-marker-suppressed rule');
assert(cssSrc.includes('.unit-marker-broken'), 'command.css has .unit-marker-broken rule');
assert(cssSrc.includes('.unit-marker-emboldened'), 'command.css has .unit-marker-emboldened rule');
assert(cssSrc.includes('.morale-badge'), 'command.css has .morale-badge rule');

// ============================================================
// Test: Suppressed animation cycle is 1.5s
// ============================================================

console.log('\n--- Animation timing ---');

assert(cssSrc.includes('morale-suppressed-pulse 1.5s'), 'suppressed animation is 1.5s cycle');
assert(cssSrc.includes('morale-broken-pulse 0.5s'), 'broken animation is 0.5s cycle (rapid)');
assert(cssSrc.includes('morale-emboldened-glow 2s'), 'emboldened animation is 2s cycle');

// ============================================================
// Test: Broken state shrinks marker (scale 0.85)
// ============================================================

console.log('\n--- Scale transforms ---');

// Check that broken has scale(0.85) and emboldened has scale(1.1)
// These appear in the CSS rules for .unit-marker-broken / .unit-marker-emboldened
const brokenRule = cssSrc.match(/\.unit-marker-broken[\s\S]*?scale\(0\.85\)/);
assert(!!brokenRule, 'broken state has transform: scale(0.85)');

const emboldenedRule = cssSrc.match(/\.unit-marker-emboldened[\s\S]*?scale\(1\.1\)/);
assert(!!emboldenedRule, 'emboldened state has transform: scale(1.1)');

// ============================================================
// Test: Injected CSS in JS also has morale rules
// ============================================================

console.log('\n--- Injected CSS in map-maplibre.js ---');

assert(mapSrc.includes("'@keyframes morale-suppressed-pulse {',"), 'JS injects morale-suppressed-pulse keyframes');
assert(mapSrc.includes("'@keyframes morale-broken-pulse {',"), 'JS injects morale-broken-pulse keyframes');
assert(mapSrc.includes("'@keyframes morale-emboldened-glow {',"), 'JS injects morale-emboldened-glow keyframes');
assert(mapSrc.includes("'.unit-marker-suppressed .tritium-unit-inner {',"), 'JS injects suppressed class rule');
assert(mapSrc.includes("'.unit-marker-broken .tritium-unit-inner {',"), 'JS injects broken class rule');
assert(mapSrc.includes("'.unit-marker-emboldened .tritium-unit-inner {',"), 'JS injects emboldened class rule');
assert(mapSrc.includes("'.morale-badge {',"), 'JS injects morale-badge rule');

// ============================================================
// Test: Morale colors match cyberpunk palette
// ============================================================

console.log('\n--- Color palette consistency ---');

// Suppressed = yellow (#fcee0a) -- warning color
assert(cssSrc.includes('#fcee0a') && cssSrc.includes('morale-suppressed'), 'suppressed uses yellow from palette');
// Broken = red/magenta (#ff2a6d) -- danger color
assert(cssSrc.includes('#ff2a6d') && cssSrc.includes('morale-broken'), 'broken uses magenta from palette');
// Emboldened = cyan (#00f0ff) -- positive/enhanced color
assert(cssSrc.includes('#00f0ff') && cssSrc.includes('morale-emboldened'), 'emboldened uses cyan from palette');

// ============================================================
// Test: NaN edge case - NaN comparisons are all false
// ============================================================

console.log('\n--- NaN edge case ---');

// NaN < 0.1 is false, NaN < 0.3 is false, NaN > 0.9 is false
// But NaN passes typeof === 'number' check, so we need the comparisons to all return false
// resulting in null (normal) -- this is actually the correct behavior since NaN means "no data"
const nanResult = _getMoraleState(NaN);
assert(nanResult === null, 'NaN returns null because all comparisons are false');

// ============================================================
// Test: Websocket passes morale to units
// ============================================================

console.log('\n--- Websocket morale passthrough ---');

const wsSrc = fs.readFileSync(__dirname + '/../../src/frontend/js/command/websocket.js', 'utf8');
assert(wsSrc.includes('morale'), 'websocket.js references morale field');
assert(wsSrc.includes('t.morale'), 'websocket.js reads t.morale from telemetry');

// ============================================================
// Results
// ============================================================

console.log(`\n=== Morale Marker Tests: ${passed} passed, ${failed} failed ===`);
process.exit(failed > 0 ? 1 : 0);
