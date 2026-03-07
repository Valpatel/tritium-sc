// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
/**
 * TRITIUM-SC Kill Feed Tests
 * Tests kill feed entry creation, formatting, max entries, fading, streak display.
 * Covers both war-hud.js (warHudAddEliminationFeedEntry) and map-maplibre helpers.
 * Run: node tests/js/test_kill_feed.js
 */

const fs = require('fs');
const vm = require('vm');

let passed = 0, failed = 0;
function assert(cond, msg) {
    if (!cond) { console.error('FAIL:', msg); failed++; }
    else { console.log('PASS:', msg); passed++; }
}
function assertEqual(a, b, msg) {
    assert(a === b, msg + ` (got ${JSON.stringify(a)}, expected ${JSON.stringify(b)})`);
}

// ============================================================
// Load war-hud.js
// ============================================================

let hudCode = fs.readFileSync(__dirname + '/../../src/frontend/js/war-hud.js', 'utf8');

// Expose internal state for testing
hudCode += `
window._hudState = _hudState;
window._formatNum = _formatNum;
window.warHudAddEliminationFeedEntry = warHudAddEliminationFeedEntry;
window.warHudAddKillFeedEntry = warHudAddKillFeedEntry;
window._renderEliminationFeed = _renderEliminationFeed;
window._hudEscapeHtml = typeof _hudEscapeHtml !== 'undefined' ? _hudEscapeHtml : _escHtml;
`;

// Mock DOM
const mockElements = {};
function resetElements() {
    Object.keys(mockElements).forEach(k => delete mockElements[k]);
}

let timeouts = [];
let intervals = [];
let dateNow = 10000;

const ctx = vm.createContext({
    Math, console, Array, Object, Number, Boolean, parseInt, parseFloat, Infinity, String,
    Date: { now: () => dateNow },
    setTimeout: (fn, ms) => { timeouts.push({ fn, ms }); return timeouts.length; },
    clearTimeout: () => {},
    setInterval: (fn, ms) => { intervals.push({ fn, ms }); return intervals.length; },
    clearInterval: () => {},
    fetch: () => Promise.resolve({ ok: true, json: () => Promise.resolve({}) }),
    window: {},
    warState: {
        audioCtx: null,
        targets: [],
        selectedTargets: [],
        effects: [],
        dispatchArrows: [],
        stats: { eliminations: 0, breaches: 0, dispatches: 0 },
    },
    warCombatReset: () => {},
    document: {
        getElementById(id) {
            if (!mockElements[id]) {
                mockElements[id] = {
                    style: { display: '', opacity: '' },
                    textContent: '',
                    innerHTML: '',
                    className: '',
                    classList: {
                        _classes: [],
                        add(cls) { this._classes.push(cls); },
                        remove(cls) { this._classes = this._classes.filter(c => c !== cls); },
                    },
                    onclick: null,
                    offsetWidth: 100,
                };
            }
            return mockElements[id];
        },
        createElement(tag) {
            const el = { _text: '' };
            Object.defineProperty(el, 'textContent', {
                get() { return el._text; },
                set(v) { el._text = String(v); },
            });
            Object.defineProperty(el, 'innerHTML', {
                get() { return el._text; },
                set(v) { el._text = String(v); },
            });
            return el;
        },
    },
});

vm.runInContext(hudCode, ctx);
const w = ctx.window;
const st = w._hudState;

// ============================================================
// Kill feed entry creation
// ============================================================

console.log('\n--- Kill feed entry creation ---');

// Start with clean state
st.eliminationFeed = [];

// Add a basic elimination
w.warHudAddEliminationFeedEntry({
    interceptor_name: 'Turret-01',
    target_name: 'Hostile-Alpha',
    interceptor_alliance: 'friendly',
    target_alliance: 'hostile',
    weapon: 'nerf_blaster',
});

assertEqual(st.eliminationFeed.length, 1, 'one entry after first add');
assertEqual(st.eliminationFeed[0].interceptor, 'Turret-01', 'interceptor name set');
assertEqual(st.eliminationFeed[0].target, 'Hostile-Alpha', 'target name set');
assert(st.eliminationFeed[0].time > 0, 'timestamp assigned');

// ============================================================
// Kill feed entry colors
// ============================================================

console.log('\n--- Kill feed entry colors ---');

st.eliminationFeed = [];

// Friendly kill (green-ish / cyan interceptor, red target)
w.warHudAddEliminationFeedEntry({
    interceptor_name: 'Rover-02',
    target_name: 'Hostile-B',
    interceptor_alliance: 'friendly',
    target_alliance: 'hostile',
});

assertEqual(st.eliminationFeed[0].interceptorColor, '#00f0ff', 'friendly interceptor is cyan');
assertEqual(st.eliminationFeed[0].targetColor, '#ff2a6d', 'hostile target is magenta');

// Hostile kill (magenta interceptor, cyan target)
w.warHudAddEliminationFeedEntry({
    interceptor_name: 'Hostile-Boss',
    target_name: 'Rover-01',
    interceptor_alliance: 'hostile',
    target_alliance: 'friendly',
});

assertEqual(st.eliminationFeed[1].interceptorColor, '#ff2a6d', 'hostile interceptor is magenta');
assertEqual(st.eliminationFeed[1].targetColor, '#00f0ff', 'friendly target is cyan');

// ============================================================
// Kill feed max entries
// ============================================================

console.log('\n--- Kill feed max entries ---');

st.eliminationFeed = [];

// Add 8 entries (max should cap at 6)
for (let i = 0; i < 8; i++) {
    w.warHudAddEliminationFeedEntry({
        interceptor_name: `Unit-${i}`,
        target_name: `Target-${i}`,
    });
}

assert(st.eliminationFeed.length <= 6, `feed capped at 6 or fewer (got ${st.eliminationFeed.length})`);
// Oldest entries should be removed (shifted), so last entry should be Target-7
assertEqual(st.eliminationFeed[st.eliminationFeed.length - 1].target, 'Target-7', 'newest entry is last');

// ============================================================
// Kill feed entry fading (8s expiry)
// ============================================================

console.log('\n--- Kill feed entry fading ---');

st.eliminationFeed = [];
dateNow = 10000;

w.warHudAddEliminationFeedEntry({
    interceptor_name: 'Turret-A',
    target_name: 'Hostile-1',
});

assertEqual(st.eliminationFeed.length, 1, 'one entry before aging');

// Simulate 9s passing
dateNow = 19001;
// The _renderEliminationFeed function filters out entries older than 8s
w._renderEliminationFeed();

assertEqual(st.eliminationFeed.length, 0, 'entry removed after 8s');

// ============================================================
// Kill feed default names
// ============================================================

console.log('\n--- Kill feed default names ---');

st.eliminationFeed = [];

// No names provided -- should use fallback
w.warHudAddEliminationFeedEntry({});

assertEqual(st.eliminationFeed[0].interceptor, 'Unit', 'default interceptor name is Unit');
assertEqual(st.eliminationFeed[0].target, 'Hostile', 'default target name is Hostile');

// ============================================================
// Kill feed backward compatibility alias
// ============================================================

console.log('\n--- Kill feed backward compat ---');

st.eliminationFeed = [];

// warHudAddKillFeedEntry should be an alias
assert(typeof w.warHudAddKillFeedEntry === 'function', 'warHudAddKillFeedEntry alias exists');

w.warHudAddKillFeedEntry({
    interceptor_name: 'Drone-01',
    target_name: 'Hostile-Z',
});

assertEqual(st.eliminationFeed.length, 1, 'alias adds entry');
assertEqual(st.eliminationFeed[0].interceptor, 'Drone-01', 'alias sets interceptor');

// ============================================================
// Kill feed alternate field names
// ============================================================

console.log('\n--- Kill feed alternate field names ---');

st.eliminationFeed = [];

// Uses killer_name/hostile_name fallbacks
w.warHudAddEliminationFeedEntry({
    killer_name: 'Tank-01',
    hostile_name: 'Invader-3',
    killer_alliance: 'friendly',
    victim_alliance: 'hostile',
});

assertEqual(st.eliminationFeed[0].interceptor, 'Tank-01', 'killer_name fallback');
assertEqual(st.eliminationFeed[0].target, 'Invader-3', 'hostile_name fallback');

// Uses interceptor_id/hostile_id fallbacks
st.eliminationFeed = [];
w.warHudAddEliminationFeedEntry({
    interceptor_id: 'turret_001',
    hostile_id: 'hostile_099',
});

assertEqual(st.eliminationFeed[0].interceptor, 'turret_001', 'interceptor_id fallback');
assertEqual(st.eliminationFeed[0].target, 'hostile_099', 'hostile_id fallback');

// ============================================================
// Kill feed null data handling
// ============================================================

console.log('\n--- Kill feed null data ---');

st.eliminationFeed = [];
w.warHudAddEliminationFeedEntry(null);
assertEqual(st.eliminationFeed.length, 0, 'null data is no-op');

w.warHudAddEliminationFeedEntry(undefined);
assertEqual(st.eliminationFeed.length, 0, 'undefined data is no-op');

// ============================================================
// Kill feed weapon field
// ============================================================

console.log('\n--- Kill feed weapon field ---');

st.eliminationFeed = [];

w.warHudAddEliminationFeedEntry({
    interceptor_name: 'Turret-X',
    target_name: 'Hostile-Y',
    weapon: 'nerf_missile_launcher',
});

assertEqual(st.eliminationFeed[0].weapon, 'nerf_missile_launcher', 'weapon field preserved');

// Method field fallback
st.eliminationFeed = [];
w.warHudAddEliminationFeedEntry({
    interceptor_name: 'Turret-Z',
    target_name: 'Hostile-W',
    method: 'nerf_cannon',
});

assertEqual(st.eliminationFeed[0].weapon, 'nerf_cannon', 'method field fallback for weapon');

// ============================================================
// Kill feed render produces HTML
// ============================================================

console.log('\n--- Kill feed render output ---');

st.eliminationFeed = [];
dateNow = 50000;

w.warHudAddEliminationFeedEntry({
    interceptor_name: 'Rover-05',
    target_name: 'Hostile-K',
    interceptor_alliance: 'friendly',
    target_alliance: 'hostile',
});

w._renderEliminationFeed();

const feedEl = mockElements['war-elimination-feed'];
assert(feedEl, 'feed element exists');
assert(feedEl.innerHTML.includes('Rover-05'), 'render includes interceptor name');
assert(feedEl.innerHTML.includes('Hostile-K'), 'render includes target name');
assert(feedEl.innerHTML.includes('#00f0ff'), 'render includes friendly color');
assert(feedEl.innerHTML.includes('#ff2a6d'), 'render includes hostile color');
assert(feedEl.innerHTML.includes('war-elimination-entry'), 'render uses entry class');
assert(feedEl.innerHTML.includes('war-elimination-arrow'), 'render uses arrow class');

// ============================================================
// Kill feed opacity fading (entry within 6-8s window)
// ============================================================

console.log('\n--- Kill feed opacity fading ---');

st.eliminationFeed = [];
dateNow = 100000;

w.warHudAddEliminationFeedEntry({
    interceptor_name: 'Unit-A',
    target_name: 'Unit-B',
});

// At 7s: should be fading (opacity between 0 and 1)
dateNow = 107000;
w._renderEliminationFeed();

const fadeHtml = feedEl.innerHTML;
assert(fadeHtml.includes('opacity'), 'opacity is set in fading entry');
// Extract opacity value -- should be between 0 and 1 (exclusive)
const opMatch = fadeHtml.match(/opacity:\s*([\d.]+)/);
if (opMatch) {
    const op = parseFloat(opMatch[1]);
    assert(op > 0 && op < 1, `fading opacity ${op} is between 0 and 1`);
} else {
    assert(false, 'could not extract opacity value');
}

// ============================================================
// Summary
// ============================================================

console.log(`\n--- Kill Feed Tests: ${passed} passed, ${failed} failed ---`);
process.exit(failed > 0 ? 1 : 0);
