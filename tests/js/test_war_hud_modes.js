// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
/**
 * TRITIUM-SC War Room -- Mode-specific HUD tests
 * Run: node tests/js/test_war_hud_modes.js
 *
 * Tests mode-specific HUD rendering for civil_unrest and drone_swarm
 * mission types: infrastructure health bar, civilian harm counter,
 * de-escalation score, mode indicator, and game state updates.
 */

const fs = require('fs');
const vm = require('vm');

let passed = 0, failed = 0;
function assert(cond, msg) {
    if (!cond) { console.error('FAIL:', msg); failed++; }
    else { console.log('PASS:', msg); passed++; }
}

let hudCode = fs.readFileSync(__dirname + '/../../src/frontend/js/war-hud.js', 'utf8');

// Expose internal state for testing
hudCode += `
window._hudState = _hudState;
window._formatNum = _formatNum;
`;

// Mock DOM elements
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
// _hudState mode fields initial values
// ============================================================

console.log('\n--- _hudState mode fields initial ---');

assert(st.gameModeType === 'battle' || st.gameModeType === undefined || st.gameModeType === null,
    'initial gameModeType is battle or unset');

// ============================================================
// warHudUpdateGameState with game_mode_type
// ============================================================

console.log('\n--- warHudUpdateGameState with game_mode_type ---');

// Drone swarm mode
resetElements();
w.warHudUpdateGameState({
    state: 'active',
    game_mode_type: 'drone_swarm',
    infrastructure_health: 800,
    infrastructure_max: 1000,
    wave: 1,
});
assert(st.gameModeType === 'drone_swarm', 'gameModeType set to drone_swarm');
assert(st.infrastructureHealth === 800, 'infrastructure_health stored');
assert(st.infrastructureMax === 1000, 'infrastructure_max stored');

// Civil unrest mode
resetElements();
w.warHudUpdateGameState({
    state: 'active',
    game_mode_type: 'civil_unrest',
    de_escalation_score: 500,
    civilian_harm_count: 2,
    civilian_harm_limit: 5,
    weighted_total_score: 1500,
    wave: 1,
});
assert(st.gameModeType === 'civil_unrest', 'gameModeType set to civil_unrest');
assert(st.deEscalationScore === 500, 'de_escalation_score stored');
assert(st.civilianHarmCount === 2, 'civilian_harm_count stored');
assert(st.civilianHarmLimit === 5, 'civilian_harm_limit stored');
assert(st.weightedTotalScore === 1500, 'weighted_total_score stored');

// Battle mode (default)
resetElements();
w.warHudUpdateGameState({
    state: 'active',
    game_mode_type: 'battle',
    wave: 1,
});
assert(st.gameModeType === 'battle', 'gameModeType set to battle');

// ============================================================
// warHudDrawModeHud — drone_swarm infrastructure bar
// ============================================================

console.log('\n--- warHudDrawModeHud drone_swarm ---');

const mockCtx = {
    saved: 0, restored: 0,
    fillStyle: '', strokeStyle: '', globalAlpha: 1,
    font: '', textAlign: '', textBaseline: '',
    lineWidth: 1,
    fillRects: [],
    fillTexts: [],
    strokeRects: [],
    save() { this.saved++; },
    restore() { this.restored++; },
    beginPath() {},
    arc() {},
    fill() {},
    fillRect(x, y, w, h) { this.fillRects.push({ x, y, w, h }); },
    fillText(text, x, y) { this.fillTexts.push({ text, x, y }); },
    strokeRect(x, y, w, h) { this.strokeRects.push({ x, y, w, h }); },
    stroke() {},
    moveTo() {},
    lineTo() {},
    closePath() {},
    measureText(t) { return { width: t.length * 6 }; },
};

// Setup drone_swarm state
st.gameModeType = 'drone_swarm';
st.gameState = 'active';
st.infrastructureHealth = 800;
st.infrastructureMax = 1000;

// Reset mock
mockCtx.saved = 0;
mockCtx.restored = 0;
mockCtx.fillRects = [];
mockCtx.fillTexts = [];

assert(typeof w.warHudDrawModeHud === 'function', 'warHudDrawModeHud function exists');

w.warHudDrawModeHud(mockCtx, 800, 600);
assert(mockCtx.saved > 0, 'drone_swarm HUD draws (ctx.save called)');
// Should draw infrastructure bar and text
const infraTexts = mockCtx.fillTexts.filter(t =>
    typeof t.text === 'string' && (t.text.includes('800') || t.text.includes('INFRASTRUCTURE') || t.text.includes('DRONE SWARM'))
);
assert(infraTexts.length > 0, 'infrastructure health text drawn');

// ============================================================
// warHudDrawModeHud — infrastructure health color thresholds
// ============================================================

console.log('\n--- Infrastructure health colors ---');

// Green: >60%
st.infrastructureHealth = 700;
st.infrastructureMax = 1000;
mockCtx.fillRects = [];
mockCtx.fillStyle = '';
w.warHudDrawModeHud(mockCtx, 800, 600);
// The bar fill color should be green (#05ffa1) at 70%
const greenBarDrawn = mockCtx.fillRects.length > 0;
assert(greenBarDrawn, 'infrastructure bar drawn at 70%');

// Yellow: 30-60%
st.infrastructureHealth = 400;
mockCtx.fillRects = [];
w.warHudDrawModeHud(mockCtx, 800, 600);
assert(mockCtx.fillRects.length > 0, 'infrastructure bar drawn at 40%');

// Red: <30%
st.infrastructureHealth = 200;
mockCtx.fillRects = [];
w.warHudDrawModeHud(mockCtx, 800, 600);
assert(mockCtx.fillRects.length > 0, 'infrastructure bar drawn at 20%');

// ============================================================
// warHudDrawModeHud — civil_unrest harm counter
// ============================================================

console.log('\n--- warHudDrawModeHud civil_unrest ---');

st.gameModeType = 'civil_unrest';
st.gameState = 'active';
st.civilianHarmCount = 2;
st.civilianHarmLimit = 5;
st.deEscalationScore = 750;
st.weightedTotalScore = 2000;

mockCtx.fillTexts = [];
mockCtx.saved = 0;
w.warHudDrawModeHud(mockCtx, 800, 600);
assert(mockCtx.saved > 0, 'civil_unrest HUD draws');

// Should show civilian harm count
const harmTexts = mockCtx.fillTexts.filter(t =>
    typeof t.text === 'string' && (t.text.includes('HARM') || t.text.includes('2') || t.text.includes('CIVILIAN'))
);
assert(harmTexts.length > 0, 'civilian harm text drawn');

// Should show de-escalation score
const deescTexts = mockCtx.fillTexts.filter(t =>
    typeof t.text === 'string' && (t.text.includes('DE-ESCALATION') || t.text.includes('750'))
);
assert(deescTexts.length > 0, 'de-escalation score text drawn');

// Should show mode indicator
const modeTexts = mockCtx.fillTexts.filter(t =>
    typeof t.text === 'string' && t.text.includes('CIVIL UNREST')
);
assert(modeTexts.length > 0, 'civil_unrest mode indicator drawn');

// ============================================================
// warHudDrawModeHud — civil_unrest harm warning colors
// ============================================================

console.log('\n--- Civilian harm warning colors ---');

// At 3 harms — should use amber/warning
st.civilianHarmCount = 3;
mockCtx.fillTexts = [];
w.warHudDrawModeHud(mockCtx, 800, 600);
assert(mockCtx.fillTexts.length > 0, 'harm counter draws at 3');

// At 4+ harms — should use red/critical
st.civilianHarmCount = 4;
mockCtx.fillTexts = [];
w.warHudDrawModeHud(mockCtx, 800, 600);
assert(mockCtx.fillTexts.length > 0, 'harm counter draws at 4');

// At 5 harms (limit) — should use red
st.civilianHarmCount = 5;
mockCtx.fillTexts = [];
w.warHudDrawModeHud(mockCtx, 800, 600);
assert(mockCtx.fillTexts.length > 0, 'harm counter draws at limit');

// ============================================================
// warHudDrawModeHud — mode indicator for drone_swarm
// ============================================================

console.log('\n--- Mode indicator drone_swarm ---');

st.gameModeType = 'drone_swarm';
st.gameState = 'active';
mockCtx.fillTexts = [];
w.warHudDrawModeHud(mockCtx, 800, 600);
const droneTexts = mockCtx.fillTexts.filter(t =>
    typeof t.text === 'string' && t.text.includes('DRONE SWARM')
);
assert(droneTexts.length > 0, 'drone_swarm mode indicator drawn');

// ============================================================
// warHudDrawModeHud — no draw for battle mode
// ============================================================

console.log('\n--- No mode HUD for battle ---');

st.gameModeType = 'battle';
st.gameState = 'active';
mockCtx.fillTexts = [];
mockCtx.saved = 0;
w.warHudDrawModeHud(mockCtx, 800, 600);
// Battle mode should not draw mode-specific HUD (or draw minimal)
// The test verifies the function exists and does not error
assert(true, 'battle mode draw does not error');

// ============================================================
// warHudDrawModeHud — no draw when not active
// ============================================================

console.log('\n--- No mode HUD when idle ---');

st.gameModeType = 'drone_swarm';
st.gameState = 'idle';
mockCtx.fillTexts = [];
mockCtx.saved = 0;
w.warHudDrawModeHud(mockCtx, 800, 600);
assert(mockCtx.saved === 0, 'no mode HUD when gameState is idle');

// ============================================================
// warHudDrawModeHud — null/missing ctx
// ============================================================

console.log('\n--- Null ctx handling ---');

st.gameModeType = 'drone_swarm';
st.gameState = 'active';
w.warHudDrawModeHud(null, 800, 600);
assert(true, 'null ctx is no-op');

// ============================================================
// warHudUpdateGameState — infrastructure_damage event updates
// ============================================================

console.log('\n--- Infrastructure damage updates ---');

st.gameModeType = 'drone_swarm';
st.infrastructureHealth = 1000;
st.infrastructureMax = 1000;

w.warHudUpdateGameState({
    state: 'active',
    game_mode_type: 'drone_swarm',
    infrastructure_health: 750,
    infrastructure_max: 1000,
});
assert(st.infrastructureHealth === 750, 'infrastructure_health updated to 750');

// ============================================================
// warHudUpdateGameState — civilian harm increment
// ============================================================

console.log('\n--- Civilian harm increment ---');

w.warHudUpdateGameState({
    state: 'active',
    game_mode_type: 'civil_unrest',
    civilian_harm_count: 3,
    civilian_harm_limit: 5,
});
assert(st.civilianHarmCount === 3, 'civilian_harm_count updated to 3');

// ============================================================
// warHudPlayAgain resets mode fields
// ============================================================

console.log('\n--- PlayAgain resets mode fields ---');

st.gameModeType = 'drone_swarm';
st.infrastructureHealth = 500;
st.infrastructureMax = 1000;
st.civilianHarmCount = 3;
st.civilianHarmLimit = 5;
st.deEscalationScore = 1000;
st.weightedTotalScore = 2000;

resetElements();
w.warHudPlayAgain();
assert(st.gameModeType === 'battle' || st.gameModeType === undefined || st.gameModeType === null,
    'gameModeType reset after playAgain');
assert(st.infrastructureHealth === 0 || st.infrastructureHealth === undefined,
    'infrastructureHealth reset after playAgain');
assert(st.civilianHarmCount === 0 || st.civilianHarmCount === undefined,
    'civilianHarmCount reset after playAgain');
assert(st.deEscalationScore === 0 || st.deEscalationScore === undefined,
    'deEscalationScore reset after playAgain');

// ============================================================
// warHudDrawModeHud — weighted_total_score display
// ============================================================

console.log('\n--- Weighted total score ---');

st.gameModeType = 'civil_unrest';
st.gameState = 'active';
st.weightedTotalScore = 3500;
st.deEscalationScore = 800;
st.civilianHarmCount = 1;
st.civilianHarmLimit = 5;

mockCtx.fillTexts = [];
w.warHudDrawModeHud(mockCtx, 800, 600);
const scoreTexts = mockCtx.fillTexts.filter(t =>
    typeof t.text === 'string' && (t.text.includes('3,500') || t.text.includes('3500') || t.text.includes('SCORE'))
);
assert(scoreTexts.length > 0, 'weighted_total_score drawn when available');

// ============================================================
// Score panel shows mode-specific stats during gameplay
// ============================================================

console.log('\n--- Score panel mode-specific stats ---');

// Drone swarm: score panel should show infrastructure health
st.gameModeType = 'drone_swarm';
st.gameState = 'active';
st.infrastructureHealth = 800;
st.infrastructureMax = 1000;
st.score = 5000;
st.wave = 3;
st.totalWaves = 10;
st.eliminations = 12;

resetElements();
w.warHudUpdateGameState({
    state: 'active',
    game_mode_type: 'drone_swarm',
    infrastructure_health: 800,
    infrastructure_max: 1000,
    score: 5000,
    wave: 3,
    total_waves: 10,
    total_eliminations: 12,
});

const scoreElDrone = mockElements['war-score'];
assert(scoreElDrone !== undefined, 'score panel element exists for drone_swarm');
const scoreHtmlDrone = (scoreElDrone && scoreElDrone.innerHTML) || '';
assert(
    scoreHtmlDrone.includes('INFRA') || scoreHtmlDrone.includes('800') || scoreHtmlDrone.includes('INFRASTRUCTURE'),
    'drone_swarm score panel shows infrastructure health'
);

// Civil unrest: score panel should show de-escalation and harm
st.gameModeType = 'civil_unrest';
st.deEscalationScore = 750;
st.civilianHarmCount = 2;
st.civilianHarmLimit = 5;
st.weightedTotalScore = 3500;

resetElements();
w.warHudUpdateGameState({
    state: 'active',
    game_mode_type: 'civil_unrest',
    de_escalation_score: 750,
    civilian_harm_count: 2,
    civilian_harm_limit: 5,
    weighted_total_score: 3500,
    score: 1000,
    wave: 2,
    total_waves: 8,
});

const scoreElCivil = mockElements['war-score'];
const scoreHtmlCivil = (scoreElCivil && scoreElCivil.innerHTML) || '';
assert(
    scoreHtmlCivil.includes('DE-ESC') || scoreHtmlCivil.includes('750') || scoreHtmlCivil.includes('HARM'),
    'civil_unrest score panel shows de-escalation/harm stats'
);

// Battle mode: score panel should NOT show infrastructure or de-escalation
st.gameModeType = 'battle';
resetElements();
w.warHudUpdateGameState({
    state: 'active',
    game_mode_type: 'battle',
    score: 2000,
    wave: 5,
    total_waves: 10,
    total_eliminations: 8,
});

const scoreElBattle = mockElements['war-score'];
const scoreHtmlBattle = (scoreElBattle && scoreElBattle.innerHTML) || '';
assert(
    scoreHtmlBattle.includes('SCORE') && scoreHtmlBattle.includes('WAVE'),
    'battle score panel shows standard SCORE/WAVE'
);
assert(
    !scoreHtmlBattle.includes('INFRA') && !scoreHtmlBattle.includes('DE-ESC') && !scoreHtmlBattle.includes('HARM'),
    'battle score panel does NOT show mode-specific stats'
);

// ============================================================
// Game over screen shows mode-specific data
// ============================================================

console.log('\n--- Game over mode-specific data ---');

// Civil unrest game over should show de-escalation stats and reason
st.gameModeType = 'civil_unrest';
resetElements();
w.warHudShowGameOver('victory', 3500, 8, 15, {
    game_mode_type: 'civil_unrest',
    reason: 'all_waves_cleared',
    de_escalation_score: 2000,
    civilian_harm_count: 1,
    civilian_harm_limit: 5,
    weighted_total_score: 3500,
});

const goElCivil = mockElements['war-game-over'];
const goHtmlCivil = (goElCivil && goElCivil.innerHTML) || '';
assert(
    goHtmlCivil.includes('DE-ESCALATION') || goHtmlCivil.includes('2,000') || goHtmlCivil.includes('2000'),
    'civil_unrest game over shows de-escalation score'
);
assert(
    goHtmlCivil.includes('HARM') || goHtmlCivil.includes('1/5') || goHtmlCivil.includes('CIVILIAN'),
    'civil_unrest game over shows civilian harm stats'
);

// Drone swarm game over should show infrastructure stats
st.gameModeType = 'drone_swarm';
resetElements();
w.warHudShowGameOver('victory', 8000, 10, 45, {
    game_mode_type: 'drone_swarm',
    reason: 'all_waves_cleared',
    infrastructure_health: 650,
    infrastructure_max: 1000,
});

const goElDrone = mockElements['war-game-over'];
const goHtmlDrone = (goElDrone && goElDrone.innerHTML) || '';
assert(
    goHtmlDrone.includes('INFRASTRUCTURE') || goHtmlDrone.includes('650') || goHtmlDrone.includes('INFRA'),
    'drone_swarm game over shows infrastructure health'
);

// Drone swarm defeat should show reason
st.gameModeType = 'drone_swarm';
resetElements();
w.warHudShowGameOver('defeat', 2000, 4, 10, {
    game_mode_type: 'drone_swarm',
    reason: 'infrastructure_destroyed',
    infrastructure_health: 0,
    infrastructure_max: 1000,
});

const goElDroneDefeat = mockElements['war-game-over'];
const goHtmlDroneDefeat = (goElDroneDefeat && goElDroneDefeat.innerHTML) || '';
assert(
    goHtmlDroneDefeat.includes('INFRASTRUCTURE') || goHtmlDroneDefeat.includes('DESTROYED'),
    'drone_swarm defeat shows infrastructure status'
);

// ============================================================
// Edge cases: backward compat (no modeData argument)
// ============================================================

console.log('\n--- Backward compat: warHudShowGameOver without modeData ---');

st.gameModeType = 'battle';
resetElements();
// Call with 4 args (old signature)
w.warHudShowGameOver('victory', 5000, 10, 20);

const goElCompat = mockElements['war-game-over'];
const goHtmlCompat = (goElCompat && goElCompat.innerHTML) || '';
assert(
    goHtmlCompat.includes('VICTORY') || goHtmlCompat.includes('SECURED'),
    'game over works without modeData (backward compat)'
);
assert(
    goHtmlCompat.includes('5,000') || goHtmlCompat.includes('5000'),
    'score displayed without modeData'
);

// ============================================================
// Edge case: game over with undefined/null modeData
// ============================================================

console.log('\n--- Game over with null modeData ---');

st.gameModeType = 'drone_swarm';
resetElements();
w.warHudShowGameOver('defeat', 1000, 3, 5, null);

const goElNull = mockElements['war-game-over'];
const goHtmlNull = (goElNull && goElNull.innerHTML) || '';
assert(
    goHtmlNull.includes('DEFEAT'),
    'game over handles null modeData'
);

// ============================================================
// Edge case: score panel with zero values
// ============================================================

console.log('\n--- Score panel with zero values ---');

st.gameModeType = 'drone_swarm';
st.gameState = 'active';
st.infrastructureHealth = 0;
st.infrastructureMax = 1000;
resetElements();
w.warHudUpdateGameState({
    state: 'active',
    game_mode_type: 'drone_swarm',
    infrastructure_health: 0,
    infrastructure_max: 1000,
    score: 0,
    wave: 1,
});

const scoreElZero = mockElements['war-score'];
const scoreHtmlZero = (scoreElZero && scoreElZero.innerHTML) || '';
assert(
    scoreHtmlZero.includes('INFRA') || scoreHtmlZero.includes('0/1000'),
    'score panel shows zero infrastructure'
);

// ============================================================
// Edge case: mode change mid-game
// ============================================================

console.log('\n--- Mode change mid-game ---');

st.gameModeType = 'battle';
resetElements();
w.warHudUpdateGameState({
    state: 'active',
    game_mode_type: 'battle',
    score: 100,
    wave: 1,
});

const scoreMid1 = (mockElements['war-score'] && mockElements['war-score'].innerHTML) || '';
assert(
    !scoreMid1.includes('INFRA') && !scoreMid1.includes('DE-ESC'),
    'battle mode has no mode-specific rows initially'
);

// Now switch to drone_swarm mid-game
resetElements();
w.warHudUpdateGameState({
    state: 'active',
    game_mode_type: 'drone_swarm',
    infrastructure_health: 900,
    infrastructure_max: 1000,
    score: 200,
    wave: 2,
});

const scoreMid2 = (mockElements['war-score'] && mockElements['war-score'].innerHTML) || '';
assert(
    scoreMid2.includes('INFRA') || scoreMid2.includes('900'),
    'score panel updates when mode changes mid-game'
);
assert(
    st.gameModeType === 'drone_swarm',
    'gameModeType updated mid-game'
);

// ============================================================
// Edge case: civil_unrest game over with zero casualties
// ============================================================

console.log('\n--- Civil unrest zero casualties ---');

st.gameModeType = 'civil_unrest';
resetElements();
w.warHudShowGameOver('victory', 5000, 8, 0, {
    game_mode_type: 'civil_unrest',
    reason: 'all_waves_cleared',
    de_escalation_score: 3000,
    civilian_harm_count: 0,
    civilian_harm_limit: 5,
    weighted_total_score: 5000,
});

const goElZeroCas = mockElements['war-game-over'];
const goHtmlZeroCas = (goElZeroCas && goElZeroCas.innerHTML) || '';
assert(
    goHtmlZeroCas.includes('0/5') || goHtmlZeroCas.includes('HARM'),
    'civil_unrest game over shows 0 casualties'
);
assert(
    goHtmlZeroCas.includes('DE-ESCALATION'),
    'zero casualty game over still shows de-escalation'
);

// ============================================================
// Summary
// ============================================================

console.log(`\n=== test_war_hud_modes.js: ${passed} passed, ${failed} failed ===`);
if (failed > 0) process.exit(1);
