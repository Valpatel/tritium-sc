// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
// Tests for graphlings observer panel definition
// Run: node tests/js/test_graphlings_panel.js

const assert = require('assert');
const fs = require('fs');
const path = require('path');

let passed = 0;
let failed = 0;

function test(name, fn) {
    try {
        fn();
        passed++;
        console.log(`  PASS  ${name}`);
    } catch (e) {
        failed++;
        console.log(`  FAIL  ${name}: ${e.message}`);
    }
}

console.log('\n=== Graphlings Observer Panel Tests ===\n');

// Test 1: Panel definition file exists
test('graphlings panel file exists', () => {
    const p = path.join(__dirname, '../../frontend/js/command/panels/graphlings.js');
    assert.ok(fs.existsSync(p), 'panels/graphlings.js should exist');
});

// Test 2: Panel definition exports correctly
test('panel definition has required fields', () => {
    const content = fs.readFileSync(
        path.join(__dirname, '../../frontend/js/command/panels/graphlings.js'), 'utf8'
    );
    assert.ok(content.includes("id: 'graphlings'"), 'panel id should be graphlings');
    assert.ok(content.includes('title:'), 'panel should have a title');
    assert.ok(content.includes('create('), 'panel should have create method');
    assert.ok(content.includes('mount('), 'panel should have mount method');
    assert.ok(content.includes('defaultSize'), 'panel should have defaultSize');
});

// Test 3: Panel connects to SSE endpoint
test('panel connects to graphlings thoughts SSE', () => {
    const content = fs.readFileSync(
        path.join(__dirname, '../../frontend/js/command/panels/graphlings.js'), 'utf8'
    );
    assert.ok(
        content.includes('/api/graphlings/thoughts'),
        'panel should connect to /api/graphlings/thoughts SSE'
    );
});

// Test 4: Panel fetches agent status
test('panel fetches graphlings status', () => {
    const content = fs.readFileSync(
        path.join(__dirname, '../../frontend/js/command/panels/graphlings.js'), 'utf8'
    );
    assert.ok(
        content.includes('/api/graphlings/status') || content.includes('/api/graphlings/agents'),
        'panel should fetch graphlings status or agents'
    );
});

// Test 5: Panel shows thought stream
test('panel renders thought entries', () => {
    const content = fs.readFileSync(
        path.join(__dirname, '../../frontend/js/command/panels/graphlings.js'), 'utf8'
    );
    assert.ok(
        content.includes('thought') && content.includes('soul_id'),
        'panel should render thought data with soul_id'
    );
});

// Test 6: Panel is registered in main.js
test('panel is registered in main.js', () => {
    const content = fs.readFileSync(
        path.join(__dirname, '../../frontend/js/command/main.js'), 'utf8'
    );
    assert.ok(
        content.includes('GraphlingsPanelDef'),
        'main.js should import and register GraphlingsPanelDef'
    );
});

// Test 7: Panel cleans up SSE on unmount
test('panel cleans up SSE on unmount', () => {
    const content = fs.readFileSync(
        path.join(__dirname, '../../frontend/js/command/panels/graphlings.js'), 'utf8'
    );
    assert.ok(
        content.includes('unmount') && content.includes('close()'),
        'panel should close EventSource on unmount'
    );
});

// Test 7b: Cleanup uses standard _unsubs pattern
test('cleanup uses panel._unsubs pattern', () => {
    const content = fs.readFileSync(
        path.join(__dirname, '../../frontend/js/command/panels/graphlings.js'), 'utf8'
    );
    assert.ok(
        content.includes('panel._unsubs.push'),
        'cleanup should use panel._unsubs.push() (standard pattern)'
    );
    assert.ok(
        !content.includes('bodyEl._glCleanup'),
        'should not store cleanup on bodyEl (non-standard)'
    );
});

// Test 7c: _unsubs cleanup closes EventSource and clears interval
test('_unsubs cleanup closes EventSource and interval', () => {
    const content = fs.readFileSync(
        path.join(__dirname, '../../frontend/js/command/panels/graphlings.js'), 'utf8'
    );
    // The cleanup function inside _unsubs.push should close eventSource and clearInterval
    const pushIdx = content.indexOf('panel._unsubs.push');
    const closingParen = content.indexOf('});', pushIdx);
    const pushBlock = content.substring(pushIdx, closingParen + 3);
    assert.ok(pushBlock.includes('eventSource.close()'), '_unsubs should close EventSource');
    assert.ok(pushBlock.includes('clearInterval'), '_unsubs should clearInterval');
});

// Test 7d: cleanup includes clearInterval
test('cleanup clears polling interval', () => {
    const content = fs.readFileSync(
        path.join(__dirname, '../../frontend/js/command/panels/graphlings.js'), 'utf8'
    );
    assert.ok(
        content.includes('clearInterval(statusInterval)'),
        'cleanup should clearInterval for polling'
    );
});

// Test 8: Panel has emotion/mood indicators
test('panel shows emotion indicators', () => {
    const content = fs.readFileSync(
        path.join(__dirname, '../../frontend/js/command/panels/graphlings.js'), 'utf8'
    );
    assert.ok(
        content.includes('emotion'),
        'panel should display emotion data'
    );
});

console.log(`\n${passed} passed, ${failed} failed\n`);
process.exit(failed > 0 ? 1 : 0);
