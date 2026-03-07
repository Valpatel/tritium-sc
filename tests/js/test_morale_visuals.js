// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
/**
 * Tests for morale visualization on the tactical map.
 *
 * Morale is already sent over WebSocket as unit.morale (0.0-1.0).
 * The map should render a morale indicator on each combatant unit:
 *   - < 0.1  BROKEN (red pulsing)
 *   - < 0.3  SUPPRESSED (yellow outline)
 *   - 0.3-0.9  normal (no indicator)
 *   - > 0.9  EMBOLDENED (green glow)
 */

'use strict';

const fs = require('fs');
const vm = require('vm');

let passed = 0;
let failed = 0;

function assert(cond, msg) {
    if (!cond) { failed++; console.error(`  FAIL: ${msg}`); return false; }
    passed++;
    return true;
}

// ---- Helpers ----

function createFreshContext() {
    const ctx = vm.createContext({
        console,
        setTimeout,
        clearTimeout,
        setInterval,
        clearInterval,
        Date,
        Math,
        Array,
        Object,
        Map,
        Set,
        JSON,
        parseInt,
        parseFloat,
        Number,
        String,
        Boolean,
        RegExp,
        Error,
        TypeError,
        Symbol,
        Promise,
        requestAnimationFrame: () => 0,
        cancelAnimationFrame: () => {},
        document: {
            getElementById: () => null,
            querySelector: () => null,
            querySelectorAll: () => [],
            createElement: (tag) => ({
                tagName: tag.toUpperCase(),
                style: {},
                classList: { add() {}, remove() {}, toggle() {}, contains() { return false; } },
                appendChild() {},
                removeChild() {},
                addEventListener() {},
                removeEventListener() {},
                setAttribute() {},
                getAttribute() { return null; },
                getContext() {
                    return {
                        save() {}, restore() {},
                        beginPath() {}, closePath() {},
                        moveTo() {}, lineTo() {},
                        arc() {}, fill() {}, stroke() {},
                        fillRect() {}, clearRect() {},
                        fillText() {}, measureText() { return { width: 0 }; },
                        setLineDash() {}, createRadialGradient() {
                            return { addColorStop() {} };
                        },
                        drawImage() {},
                        translate() {}, scale() {}, rotate() {},
                        set fillStyle(v) {},
                        get fillStyle() { return ''; },
                        set strokeStyle(v) {},
                        get strokeStyle() { return ''; },
                        set lineWidth(v) {},
                        set font(v) {},
                        set textAlign(v) {},
                        set textBaseline(v) {},
                        set globalAlpha(v) {},
                        get globalAlpha() { return 1; },
                        set shadowColor(v) {},
                        set shadowBlur(v) {},
                    };
                },
            }),
            createElementNS() {
                return { setAttribute() {}, style: {}, appendChild() {} };
            },
            body: { appendChild() {}, removeChild() {} },
        },
        window: {},
        Image: function() { this.onload = null; this.src = ''; },
    });
    ctx.window = ctx;
    ctx.globalThis = ctx;
    return ctx;
}

// ---- Read map.js source ----

const mapSrc = fs.readFileSync(`${__dirname}/../../src/frontend/js/command/map.js`, 'utf-8');

// ================================================================
// Test: _drawMoraleIndicator function exists in map.js
// ================================================================
(function testMoraleIndicatorFunctionExists() {
    assert(
        mapSrc.includes('_drawMoraleIndicator'),
        '_drawMoraleIndicator function should exist in map.js'
    );
})();

// ================================================================
// Test: Morale thresholds are defined
// ================================================================
(function testMoraleThresholdConstants() {
    // The function should reference key morale thresholds
    assert(
        mapSrc.includes('0.1') || mapSrc.includes('BROKEN'),
        'Morale broken threshold (0.1) should be referenced'
    );
    assert(
        mapSrc.includes('0.3') || mapSrc.includes('SUPPRESSED'),
        'Morale suppressed threshold (0.3) should be referenced'
    );
    assert(
        mapSrc.includes('0.9') || mapSrc.includes('EMBOLDENED'),
        'Morale emboldened threshold (0.9) should be referenced'
    );
})();

// ================================================================
// Test: _drawMoraleIndicator is called from _drawUnit
// ================================================================
(function testMoraleIndicatorCalledFromDrawUnit() {
    // _drawUnit should call _drawMoraleIndicator for combatant units
    assert(
        mapSrc.includes('_drawMoraleIndicator(ctx'),
        '_drawMoraleIndicator should be called from unit rendering'
    );
})();

// ================================================================
// Test: Morale colors for different states
// ================================================================
(function testMoraleColorsByState() {
    // Broken = red-ish
    assert(
        mapSrc.includes('#ff2a6d') || mapSrc.includes('ff2a6d'),
        'Broken morale should use red/magenta color'
    );
    // Emboldened = green
    assert(
        mapSrc.includes('#05ffa1') || mapSrc.includes('05ffa1'),
        'Emboldened morale should use green color'
    );
})();

// ================================================================
// Test: Morale indicator only for combatants
// ================================================================
(function testMoraleOnlyForCombatants() {
    assert(
        mapSrc.includes('is_combatant') || mapSrc.includes('isCombatant'),
        'Morale indicator should check is_combatant before drawing'
    );
})();

// ================================================================
// Test: Morale rendering in render loop
// ================================================================
(function testMoraleInRenderPipeline() {
    // _drawMoraleIndicator should be called within _drawUnit,
    // which is called by _drawTargets (Layer 5)
    assert(
        mapSrc.includes('_drawMoraleIndicator'),
        'Morale indicator should be part of the unit draw pipeline'
    );
})();

// ================================================================
// Test: Normal morale (0.3-0.9) has no special indicator
// ================================================================
(function testNormalMoraleNoIndicator() {
    // The function definition should have an early return for normal morale
    const fnIdx = mapSrc.indexOf('function _drawMoraleIndicator');
    assert(fnIdx > -1, 'function _drawMoraleIndicator must exist');
    const moraleSection = mapSrc.substring(fnIdx, fnIdx + 800);
    assert(
        moraleSection.includes('>= 0.3') && moraleSection.includes('return'),
        'Normal morale (0.3-0.9) should skip drawing'
    );
})();

// ================================================================
// Summary
// ================================================================
console.log(`\nMorale visuals tests: ${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
