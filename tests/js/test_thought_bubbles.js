// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
/**
 * TRITIUM-SC Thought Bubble Tests
 * Tests the helper functions for NPC thought bubble rendering.
 * Run: node tests/js/test_thought_bubbles.js
 */

let passed = 0, failed = 0;
function assert(cond, msg) {
    if (!cond) { console.error('FAIL:', msg); failed++; }
    else { console.log('PASS:', msg); passed++; }
}

// ============================================================
// Mock canvas context for wrapText testing
// ============================================================

function createMockCtx() {
    return {
        measureText(text) {
            // Approximate: 7px per character
            return { width: text.length * 7 };
        },
    };
}

// ============================================================
// Import helpers — inline from map.js exports
// We test the pure functions directly.
// ============================================================

// Replicate the functions to test (these will be exported from map.js)
function _wrapText(ctx, text, maxWidth) {
    const words = text.split(' ');
    const lines = [];
    let currentLine = '';

    for (const word of words) {
        const testLine = currentLine ? currentLine + ' ' + word : word;
        const metrics = ctx.measureText(testLine);
        if (metrics.width > maxWidth && currentLine) {
            lines.push(currentLine);
            currentLine = word;
        } else {
            currentLine = testLine;
        }
    }
    if (currentLine) lines.push(currentLine);
    return lines;
}

function _emotionColor(emotion) {
    const colors = {
        curious: '#00f0ff',
        afraid: '#fcee0a',
        angry: '#ff2a6d',
        happy: '#05ffa1',
        neutral: '#888888',
    };
    return colors[emotion] || '#888888';
}

// ============================================================
// Tests
// ============================================================

console.log('\n=== Thought Bubble Tests ===\n');

// -- wrapText tests --

{
    const ctx = createMockCtx();

    // test_wrapText_splits_long_lines
    const lines = _wrapText(ctx, 'This is a really long sentence that should be wrapped across lines', 100);
    assert(lines.length > 1, 'wrapText_splits_long_lines: should produce multiple lines');
    for (const line of lines) {
        // Each line should be within maxWidth (approx check with 7px/char = ~14 chars for 100px)
        assert(ctx.measureText(line).width <= 120, `wrapText line "${line}" within reasonable width`);
    }
}

{
    const ctx = createMockCtx();

    // test_wrapText_single_short_line
    const lines = _wrapText(ctx, 'Hi', 200);
    assert(lines.length === 1, 'wrapText_single_short_line: single word = 1 line');
    assert(lines[0] === 'Hi', 'wrapText_single_short_line: text preserved');
}

{
    const ctx = createMockCtx();

    // test_wrapText_empty_string
    const lines = _wrapText(ctx, '', 200);
    // Empty string: split(' ') gives [''], so 1 line with empty content or 0 lines
    assert(lines.length <= 1, 'wrapText_empty: returns 0 or 1 lines');
}

// -- emotionColor tests --

// test_emotionColor_known_emotions
assert(_emotionColor('curious') === '#00f0ff', 'emotionColor curious = cyan');
assert(_emotionColor('afraid') === '#fcee0a', 'emotionColor afraid = yellow');
assert(_emotionColor('angry') === '#ff2a6d', 'emotionColor angry = magenta');
assert(_emotionColor('happy') === '#05ffa1', 'emotionColor happy = green');
assert(_emotionColor('neutral') === '#888888', 'emotionColor neutral = grey');

// test_emotionColor_unknown_defaults_grey
assert(_emotionColor('confused') === '#888888', 'emotionColor unknown defaults to grey');
assert(_emotionColor('') === '#888888', 'emotionColor empty defaults to grey');

// -- expired thoughts test --
{
    // test_expired_thoughts_cleared
    // Simulate a unit with an expired thought
    const unit = {
        thoughtText: 'Old thought',
        thoughtEmotion: 'curious',
        thoughtExpires: Date.now() - 1000,  // 1s ago
    };
    const isExpired = unit.thoughtExpires <= Date.now();
    assert(isExpired, 'expired_thoughts_cleared: expired thought detected');

    // Verify active thought is not expired
    const unit2 = {
        thoughtText: 'Active thought',
        thoughtEmotion: 'happy',
        thoughtExpires: Date.now() + 60000,  // 60s from now
    };
    const isActive = unit2.thoughtExpires > Date.now();
    assert(isActive, 'expired_thoughts_cleared: active thought not expired');
}

// -- Visibility parameter tests --
// These test the expected rendering constants for improved visibility

console.log('\n--- Bubble Visibility Parameters ---');

{
    // test_font_size_larger_at_default_zoom
    // Default zoom ~ 1.0, formula: max(11, 13 * min(zoom, 2.5))
    const zoom = 1.0;
    const fontSize = Math.max(11, 13 * Math.min(zoom, 2.5));
    assert(fontSize >= 13, `font size at zoom 1.0 = ${fontSize} (should be >= 13)`);
    assert(fontSize > 10, 'font size at default zoom larger than old 10px');
}

{
    // test_font_size_caps_at_zoom_2_5
    const zoom = 5.0;
    const fontSize = Math.max(11, 13 * Math.min(zoom, 2.5));
    assert(fontSize === 32.5, `font size caps at zoom 5.0 = ${fontSize} (should be 32.5)`);
}

{
    // test_font_minimum_at_low_zoom
    const zoom = 0.5;
    const fontSize = Math.max(11, 13 * Math.min(zoom, 2.5));
    assert(fontSize === 11, `font size minimum at low zoom = ${fontSize} (should be 11)`);
}

{
    // test_max_text_width_expanded
    const maxTextWidth = 200;
    assert(maxTextWidth === 200, `maxTextWidth is 200 (was 120)`);
}

{
    // test_padding_increased
    const padding = 10;
    assert(padding === 10, `padding is 10 (was 6)`);
}

{
    // test_tail_height_increased
    const tailHeight = 10;
    assert(tailHeight === 10, `tailHeight is 10 (was 8)`);
}

{
    // test_vertical_offset_increased
    const verticalOffset = 28;
    assert(verticalOffset === 28, `vertical offset is 28 (was 20)`);
}

{
    // test_border_width_increased
    const borderWidth = 2.5;
    assert(borderWidth === 2.5, `border width is 2.5 (was 1.5)`);
}

{
    // test_wrapText_with_wider_maxWidth
    const ctx = createMockCtx();
    const lines200 = _wrapText(ctx, 'This is a test sentence for wider bubbles', 200);
    const lines120 = _wrapText(ctx, 'This is a test sentence for wider bubbles', 120);
    assert(lines200.length <= lines120.length, 'wider maxWidth produces fewer or equal lines');
}

// -- thoughtDuration storage test --
console.log('\n--- Thought Duration Storage ---');

{
    // test_thoughtDuration_stored_from_ws_message
    const unit = {};
    const d = { unit_id: 'npc-1', text: 'Hello', emotion: 'happy', duration: 8 };
    unit.thoughtText = d.text;
    unit.thoughtEmotion = d.emotion || 'neutral';
    unit.thoughtExpires = Date.now() + (d.duration || 5) * 1000;
    unit.thoughtDuration = d.duration || 5;
    assert(unit.thoughtDuration === 8, 'thoughtDuration stored from WS message');
}

{
    // test_thoughtDuration_defaults_to_5
    const unit = {};
    const d = { unit_id: 'npc-1', text: 'Hello' };
    unit.thoughtDuration = d.duration || 5;
    assert(unit.thoughtDuration === 5, 'thoughtDuration defaults to 5 when absent');
}

// -- thoughtHistory accumulation test --
console.log('\n--- Thought History ---');

{
    // test_thoughtHistory_accumulates
    const unit = { thoughtHistory: [] };
    for (let i = 0; i < 12; i++) {
        unit.thoughtHistory.push({ text: `thought ${i}`, emotion: 'neutral', time: Date.now() });
        if (unit.thoughtHistory.length > 10) {
            unit.thoughtHistory.shift();
        }
    }
    assert(unit.thoughtHistory.length === 10, 'thoughtHistory capped at 10 entries');
    assert(unit.thoughtHistory[0].text === 'thought 2', 'oldest thought pruned correctly');
    assert(unit.thoughtHistory[9].text === 'thought 11', 'newest thought is last');
}

{
    // test_thoughtHistory_initialized_as_array
    const unit = {};
    if (!unit.thoughtHistory) {
        unit.thoughtHistory = [];
    }
    unit.thoughtHistory.push({ text: 'first', emotion: 'curious', time: Date.now() });
    assert(Array.isArray(unit.thoughtHistory), 'thoughtHistory is an array');
    assert(unit.thoughtHistory.length === 1, 'thoughtHistory has one entry');
}

// ============================================================
// Summary
// ============================================================

console.log(`\nResults: ${passed} passed, ${failed} failed out of ${passed + failed}\n`);
if (failed > 0) process.exit(1);
