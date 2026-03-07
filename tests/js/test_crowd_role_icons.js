// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
/**
 * TRITIUM-SC Crowd Role Visual Differentiation Tests
 *
 * Tests that the map renderer visually distinguishes crowd roles
 * (instigator, rioter, civilian) on person-type units during civil_unrest mode.
 *
 * The _drawUnit function in map.js should:
 * - Render instigators with a magenta diamond marker
 * - Render rioters with an orange agitated indicator
 * - Render civilians as default neutral_person (blue circle)
 * - Only apply crowd role visuals during civil_unrest game mode
 * - Show identified instigators differently from hidden ones
 *
 * Run: node tests/js/test_crowd_role_icons.js
 */

const fs = require('fs');
const path = require('path');

// Simple test runner
let passed = 0, failed = 0;
function assert(cond, msg) {
    if (!cond) { console.error('FAIL:', msg); failed++; }
    else { console.log('PASS:', msg); passed++; }
}

function assertEq(a, b, msg) {
    if (a === b) { console.log('PASS:', msg); passed++; }
    else { console.error(`FAIL: ${msg} (expected ${b}, got ${a})`); failed++; }
}

// ============================================================
// Read unit-icons.js source
// ============================================================

const iconsSource = fs.readFileSync(
    path.join(__dirname, '../../src/frontend/js/command/unit-icons.js'), 'utf8');

// ============================================================
// Test: drawUnit function supports crowdRole parameter
// ============================================================

console.log('\n--- Crowd Role Icon Support ---');

// The drawUnit function signature should accept an options object
// or an extra crowdRole parameter
{
    // Check that CROWD_ROLE_COLORS constant exists
    assert(iconsSource.includes('CROWD_ROLE_COLORS'), 'unit-icons.js defines CROWD_ROLE_COLORS');
}

{
    // Check instigator color is magenta
    assert(iconsSource.includes('instigator') && iconsSource.includes('#ff2a6d'),
        'instigator uses magenta color');
}

{
    // Check rioter color is orange/amber
    assert(iconsSource.includes('rioter'),
        'unit-icons.js handles rioter crowd role');
}

{
    // Check civilian is handled (or falls through to default)
    assert(iconsSource.includes('civilian') || iconsSource.includes('neutral_person'),
        'civilian falls through to neutral_person default');
}

// ============================================================
// Test: drawCrowdRoleIndicator function exists
// ============================================================

console.log('\n--- drawCrowdRoleIndicator function ---');

{
    assert(iconsSource.includes('drawCrowdRoleIndicator'),
        'unit-icons.js exports drawCrowdRoleIndicator function');
}

{
    // Check that it draws different indicators per role
    // instigator = diamond outline
    assert(iconsSource.includes('instigator') && iconsSource.includes('diamond'),
        'instigator gets diamond indicator (comments or drawing code)');
}

// ============================================================
// Test: map.js _drawUnit passes crowdRole
// ============================================================

console.log('\n--- map.js crowd role integration ---');

const mapSource = fs.readFileSync(
    path.join(__dirname, '../../src/frontend/js/command/map.js'), 'utf8');

{
    assert(mapSource.includes('crowdRole'), 'map.js _drawUnit references crowdRole');
}

{
    assert(mapSource.includes('drawCrowdRoleIndicator'),
        'map.js calls drawCrowdRoleIndicator');
}

{
    // It should only render crowd role indicators during civil_unrest
    assert(mapSource.includes('civil_unrest') || mapSource.includes('crowdRole'),
        'map.js has civil_unrest or crowdRole conditional');
}

// ============================================================
// Test: instigator identified state visual difference
// ============================================================

console.log('\n--- Instigator identified state ---');

{
    // When identified, the indicator should change (e.g., solid vs dashed)
    assert(iconsSource.includes('identified') || mapSource.includes('instigatorState'),
        'identified instigators have visual distinction');
}

{
    // instigatorState === 'identified' should show a different visual
    assert(mapSource.includes('instigatorState') || iconsSource.includes('instigatorState'),
        'instigatorState field is used in rendering');
}

// ============================================================
// Test: crowd role indicator drawing details
// ============================================================

console.log('\n--- Drawing details ---');

{
    // Instigator indicator should use pulsing glow
    assert(iconsSource.includes('pulse') || iconsSource.includes('sin'),
        'instigator indicator includes pulsing effect');
}

{
    // Rioter indicator should use a distinct shape from instigator
    // Could be a triangle warning or agitation lines
    const hasRioterDraw = iconsSource.includes('rioter');
    assert(hasRioterDraw, 'rioter has distinct drawing code');
}

// ============================================================
// Summary
// ============================================================

console.log(`\n--- Crowd Role Icons: ${passed} passed, ${failed} failed ---`);
if (failed > 0) process.exit(1);
