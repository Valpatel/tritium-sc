// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
/**
 * Tests for squad formation line visualization on the tactical map.
 *
 * Squad members (units sharing a squad_id or squadId) should have
 * thin colored lines connecting them on the map, so the operator
 * can visually identify squad groupings at a glance.
 */

'use strict';

const fs = require('fs');

let passed = 0;
let failed = 0;

function assert(cond, msg) {
    if (!cond) { failed++; console.error(`  FAIL: ${msg}`); return false; }
    passed++;
    return true;
}

const mapSrc = fs.readFileSync(`${__dirname}/../../src/frontend/js/command/map.js`, 'utf-8');

// ================================================================
// Test: _drawSquadLines function exists
// ================================================================
(function testSquadLinesFunctionExists() {
    assert(
        mapSrc.includes('_drawSquadLines'),
        '_drawSquadLines function should exist in map.js'
    );
})();

// ================================================================
// Test: _drawSquadLines called in render loop
// ================================================================
(function testSquadLinesInRenderLoop() {
    assert(
        mapSrc.includes('_drawSquadLines(ctx'),
        '_drawSquadLines should be called in the render loop'
    );
})();

// ================================================================
// Test: Squad lines use squadId to group
// ================================================================
(function testSquadLinesGroupBySquadId() {
    const fnIdx = mapSrc.indexOf('function _drawSquadLines');
    assert(fnIdx > -1, 'function _drawSquadLines must exist');
    const section = mapSrc.substring(fnIdx, fnIdx + 1500);
    assert(
        section.includes('squadId') || section.includes('squad_id'),
        'Squad lines should group by squadId'
    );
})();

// ================================================================
// Test: Squad lines use different colors per squad
// ================================================================
(function testSquadColorsVary() {
    const fnIdx = mapSrc.indexOf('function _drawSquadLines');
    const section = mapSrc.substring(fnIdx, fnIdx + 1500);
    // Should have a color palette or hash-based coloring
    assert(
        section.includes('SQUAD_COLORS') || section.includes('hsl') ||
        section.includes('color') || section.includes('strokeStyle'),
        'Squad lines should vary color per squad'
    );
})();

// ================================================================
// Test: Squad lines are thin and translucent
// ================================================================
(function testSquadLinesSubtle() {
    const fnIdx = mapSrc.indexOf('function _drawSquadLines');
    const section = mapSrc.substring(fnIdx, fnIdx + 1500);
    assert(
        section.includes('lineWidth') && section.includes('globalAlpha'),
        'Squad lines should be thin and translucent'
    );
})();

// ================================================================
// Test: Squad lines layer is between targets and labels
// ================================================================
(function testSquadLinesLayerOrder() {
    const callIdx = mapSrc.indexOf('_drawSquadLines(ctx');
    const targetsIdx = mapSrc.indexOf('_drawTargets(ctx');
    const labelsIdx = mapSrc.indexOf('_drawLabels(ctx');
    assert(
        callIdx > targetsIdx && callIdx < labelsIdx,
        'Squad lines should be drawn after targets but before labels'
    );
})();

// ================================================================
// Test: Only active/alive units get squad lines
// ================================================================
(function testSquadLinesSkipDead() {
    const fnIdx = mapSrc.indexOf('function _drawSquadLines');
    const section = mapSrc.substring(fnIdx, fnIdx + 1500);
    assert(
        section.includes('eliminated') || section.includes('destroyed') || section.includes('status'),
        'Squad lines should skip eliminated/destroyed units'
    );
})();

// ================================================================
// Summary
// ================================================================
console.log(`\nSquad lines tests: ${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
