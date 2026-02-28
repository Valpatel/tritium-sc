// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
/**
 * TRITIUM-SC Scenarios — Safety & Edge Case tests
 * Run: node tests/js/test_scenarios_safety.js
 *
 * Tests that scenarios timeline rendering handles null/undefined/missing
 * timestamps without crashing (TypeError: null.toFixed is not a function).
 */

let passed = 0, failed = 0;
function assert(cond, msg) {
    if (!cond) { console.error('FAIL:', msg); failed++; }
    else { console.log('PASS:', msg); passed++; }
}

// ============================================================
// Test the timestamp formatting pattern used in scenarios.js
// ============================================================

// This is the EXACT pattern from scenarios.js line 627 and line 657:
//   const time = a.timestamp !== undefined ? a.timestamp.toFixed(1) + 's' : '--';
//
// Bug: null !== undefined is TRUE, so null.toFixed(1) crashes.

function formatTimestamp_buggy(timestamp) {
    return timestamp !== undefined ? timestamp.toFixed(1) + 's' : '--';
}

function formatTimestamp_safe(timestamp) {
    return (timestamp != null && typeof timestamp === 'number')
        ? timestamp.toFixed(1) + 's'
        : '--';
}

console.log('\n--- Timestamp formatting safety ---');

(function testNullTimestamp() {
    let crashed = false;
    try {
        formatTimestamp_buggy(null);
    } catch (e) {
        crashed = true;
    }
    assert(crashed, 'Buggy formatter crashes on null timestamp (proves bug exists)');
})();

(function testUndefinedTimestamp() {
    const result = formatTimestamp_buggy(undefined);
    assert(result === '--', 'Buggy formatter handles undefined correctly');
})();

(function testNormalTimestamp() {
    const result = formatTimestamp_buggy(5.3);
    assert(result === '5.3s', 'Buggy formatter handles normal number');
})();

(function testZeroTimestamp() {
    const result = formatTimestamp_buggy(0);
    assert(result === '0.0s', 'Buggy formatter handles zero');
})();

// Safe formatter tests (these prove the fix works)

(function testSafeNull() {
    const result = formatTimestamp_safe(null);
    assert(result === '--', 'Safe formatter handles null without crash');
})();

(function testSafeUndefined() {
    const result = formatTimestamp_safe(undefined);
    assert(result === '--', 'Safe formatter handles undefined');
})();

(function testSafeNumber() {
    const result = formatTimestamp_safe(12.5);
    assert(result === '12.5s', 'Safe formatter handles normal number');
})();

(function testSafeZero() {
    const result = formatTimestamp_safe(0);
    assert(result === '0.0s', 'Safe formatter handles zero');
})();

(function testSafeString() {
    const result = formatTimestamp_safe("5.0");
    assert(result === '--', 'Safe formatter rejects string timestamps');
})();

(function testSafeNaN() {
    const result = formatTimestamp_safe(NaN);
    assert(result === 'NaNs' || result === '--', 'Safe formatter handles NaN (NaN is typeof number)');
})();

// ============================================================
// Summary
// ============================================================

console.log('\n' + '='.repeat(40));
console.log(`Results: ${passed} passed, ${failed} failed`);
console.log('='.repeat(40));
process.exit(failed > 0 ? 1 : 0);
