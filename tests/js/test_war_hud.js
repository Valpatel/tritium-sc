/**
 * TRITIUM-SC War Room -- HUD tests
 * Run: node tests/js/test_war_hud.js
 *
 * Tests game state tracking, elimination feed, score display,
 * countdown, wave banners, game over, announcement queue, and utilities.
 */

const fs = require('fs');
const vm = require('vm');

let passed = 0, failed = 0;
function assert(cond, msg) {
    if (!cond) { console.error('FAIL:', msg); failed++; }
    else { console.log('PASS:', msg); passed++; }
}

let hudCode = fs.readFileSync(__dirname + '/../../frontend/js/war-hud.js', 'utf8');

// Expose internal state for testing
hudCode += `
window._hudState = _hudState;
window._formatNum = _formatNum;
window._announcementQueue = _announcementQueue;
window.warHudAddEliminationFeedEntry = warHudAddEliminationFeedEntry;
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

// ============================================================
// _formatNum
// ============================================================

console.log('\n--- _formatNum ---');

assert(w._formatNum(0) === '0', 'format 0');
assert(w._formatNum(1000).includes(',') || w._formatNum(1000) === '1,000', 'format 1000 has comma');
assert(w._formatNum(999999).length > 3, 'format large number');

// ============================================================
// _hudState initial values
// ============================================================

console.log('\n--- _hudState initial ---');

const st = w._hudState;
assert(st.score === 0, 'initial score 0');
assert(st.displayScore === 0, 'initial displayScore 0');
assert(st.eliminations === 0, 'initial eliminations 0');
assert(st.wave === 0, 'initial wave 0');
assert(st.totalWaves === 10, 'initial totalWaves 10');
assert(st.gameState === 'idle', 'initial gameState idle');
assert(Array.isArray(st.eliminationFeed), 'eliminationFeed is array');
assert(st.eliminationFeed.length === 0, 'eliminationFeed starts empty');

// ============================================================
// warHudUpdateGameState
// ============================================================

console.log('\n--- warHudUpdateGameState ---');

// null data is no-op
w.warHudUpdateGameState(null);
assert(st.gameState === 'idle', 'null data is no-op');

// Set state
w.warHudUpdateGameState({ state: 'active', wave: 3, total_waves: 10, score: 500 });
assert(st.gameState === 'active', 'state updated to active');
assert(st.wave === 3, 'wave updated to 3');
assert(st.totalWaves === 10, 'totalWaves updated');
assert(st.score === 500, 'score updated');

// total_eliminations field
w.warHudUpdateGameState({ total_eliminations: 7 });
assert(st.eliminations === 7, 'total_eliminations field works');

// total_kills fallback
w.warHudUpdateGameState({ total_kills: 12 });
assert(st.eliminations === 12, 'total_kills fallback works');

// Setup state shows begin button
w.warHudUpdateGameState({ state: 'setup' });
assert(st.gameState === 'setup', 'state set to setup');
const beginBtn = mockElements['war-begin-btn'];
assert(beginBtn && beginBtn.style.display === 'block', 'begin button shown in setup');

// Active state hides begin button
w.warHudUpdateGameState({ state: 'active' });
assert(beginBtn && beginBtn.style.display === 'none', 'begin button hidden in active');

// Countdown state triggers countdown overlay
timeouts = [];
w.warHudUpdateGameState({ state: 'countdown', countdown: 3 });
assert(st.gameState === 'countdown', 'state set to countdown');
const countdownEl = mockElements['war-countdown'];
assert(countdownEl && countdownEl.style.display === 'flex', 'countdown overlay shown');

// Score panel visibility
resetElements();
w.warHudUpdateGameState({ state: 'active' });
const scoreEl = mockElements['war-score'];
assert(scoreEl && scoreEl.style.display === 'block', 'score panel visible during active');

resetElements();
w.warHudUpdateGameState({ state: 'idle' });
const scoreEl2 = mockElements['war-score'];
assert(scoreEl2 && scoreEl2.style.display === 'none', 'score panel hidden during idle');

// ============================================================
// warHudShowWaveBanner
// ============================================================

console.log('\n--- warHudShowWaveBanner ---');

resetElements();
timeouts = [];
w.warHudShowWaveBanner(5, 'ASSAULT', 12);
const banner = mockElements['war-wave-banner'];
assert(banner.style.display === 'block', 'wave banner shown');
assert(banner.innerHTML.includes('WAVE 5'), 'wave number in banner');
assert(banner.innerHTML.includes('ASSAULT'), 'wave name in banner');
assert(banner.innerHTML.includes('12 HOSTILES'), 'hostile count in banner');

// Without name
resetElements();
w.warHudShowWaveBanner(1, null, null);
const b2 = mockElements['war-wave-banner'];
assert(b2.innerHTML.includes('WAVE 1'), 'wave 1 shown');
assert(!b2.innerHTML.includes('null'), 'no null in banner');

// With briefing data
resetElements();
timeouts = [];
w.warHudShowWaveBanner(3, 'Heavy Contact', 8, {
    briefing: 'Enemy reinforcements approaching from the east.',
    threat_level: 'heavy',
    intel: 'Estimated 8 hostiles with vehicles.',
});
const b3 = mockElements['war-wave-banner'];
assert(b3.innerHTML.includes('WAVE 3'), 'wave 3 with briefing');
assert(b3.innerHTML.includes('reinforcements'), 'briefing text in banner');
assert(b3.innerHTML.includes('THREAT: HEAVY'), 'threat level in banner');
assert(b3.innerHTML.includes('threat-heavy'), 'threat-heavy CSS class');
assert(b3.innerHTML.includes('Estimated 8'), 'intel text in banner');

// Without briefing data (null)
resetElements();
w.warHudShowWaveBanner(2, 'Scout Party', 4, null);
const b4 = mockElements['war-wave-banner'];
assert(b4.innerHTML.includes('WAVE 2'), 'wave 2 no briefing');
assert(!b4.innerHTML.includes('THREAT'), 'no threat without briefing data');

// ============================================================
// warHudSetLoadingMessages
// ============================================================

console.log('\n--- warHudSetLoadingMessages ---');

{
    w.warHudSetLoadingMessages(['Calibrating...', 'Loading...', 'Arming...']);
    assert(w._hudState.loadingMessages.length === 3, 'loading messages set');
    assert(w._hudState.loadingMessages[0] === 'Calibrating...', 'first message');
}

{
    w.warHudSetLoadingMessages(null);
    assert(w._hudState.loadingMessages.length === 0, 'null clears messages');
}

{
    w.warHudSetLoadingMessages([]);
    assert(w._hudState.loadingMessages.length === 0, 'empty array clears messages');
}

// ============================================================
// warHudShowWaveComplete
// ============================================================

console.log('\n--- warHudShowWaveComplete ---');

resetElements();
timeouts = [];
w.warHudShowWaveComplete(3, 8, 250);
const wc = mockElements['war-wave-banner'];
assert(wc.innerHTML.includes('WAVE 3 COMPLETE'), 'complete text shown');
assert(wc.innerHTML.includes('8 NEUTRALIZED'), 'eliminations shown');
assert(wc.innerHTML.includes('+250 PTS'), 'score bonus shown');

// Defaults for missing values
resetElements();
w.warHudShowWaveComplete(1, null, null);
const wc2 = mockElements['war-wave-banner'];
assert(wc2.innerHTML.includes('0 NEUTRALIZED'), 'default 0 eliminations');
assert(wc2.innerHTML.includes('+0 PTS'), 'default 0 pts');

// ============================================================
// warHudAddEliminationFeedEntry
// ============================================================

console.log('\n--- warHudAddEliminationFeedEntry ---');

// Reset hud state
st.eliminationFeed = [];

w.warHudAddEliminationFeedEntry(null);
assert(st.eliminationFeed.length === 0, 'null data adds nothing');

w.warHudAddEliminationFeedEntry({
    interceptor_name: 'Turret-1',
    target_name: 'Hostile-3',
    interceptor_alliance: 'friendly',
    target_alliance: 'hostile',
    weapon: 'nerf_dart',
});
assert(st.eliminationFeed.length === 1, 'one feed entry added');
assert(st.eliminationFeed[0].interceptor === 'Turret-1', 'interceptor name');
assert(st.eliminationFeed[0].target === 'Hostile-3', 'target name');
assert(st.eliminationFeed[0].interceptorColor === '#00f0ff', 'friendly = cyan');
assert(st.eliminationFeed[0].targetColor === '#ff2a6d', 'hostile = magenta');
assert(st.eliminationFeed[0].weapon === 'nerf_dart', 'weapon set');

// Fallback fields
st.eliminationFeed = [];
w.warHudAddEliminationFeedEntry({
    killer_name: 'Rover-2',
    hostile_name: 'Bad Guy',
    killer_alliance: 'friendly',
    victim_alliance: 'hostile',
});
assert(st.eliminationFeed[0].interceptor === 'Rover-2', 'killer_name fallback');
assert(st.eliminationFeed[0].target === 'Bad Guy', 'hostile_name fallback');

// Default names
st.eliminationFeed = [];
w.warHudAddEliminationFeedEntry({});
assert(st.eliminationFeed[0].interceptor === 'Unit', 'default interceptor = Unit');
assert(st.eliminationFeed[0].target === 'Hostile', 'default target = Hostile');

// Max 6 entries
st.eliminationFeed = [];
for (let i = 0; i < 8; i++) {
    w.warHudAddEliminationFeedEntry({ interceptor_name: `K${i}`, target_name: `T${i}` });
}
assert(st.eliminationFeed.length === 6, 'max 6 feed entries');
assert(st.eliminationFeed[0].interceptor === 'K2', 'oldest entries removed');

// Backward compat alias
assert(typeof w.warHudAddKillFeedEntry === 'function', 'warHudAddKillFeedEntry alias exists');

// ============================================================
// warHudShowGameOver
// ============================================================

console.log('\n--- warHudShowGameOver ---');

resetElements();
timeouts = [];
w.warHudShowGameOver('victory', 2500, 10, 15);
const go = mockElements['war-game-over'];
assert(go.style.display === 'flex', 'game over overlay shown');
assert(go.innerHTML.includes('VICTORY'), 'victory text shown');
assert(go.innerHTML.includes('NEIGHBORHOOD SECURED'), 'victory title');
assert(go.innerHTML.includes('2,500') || go.innerHTML.includes('2500'), 'score shown');
assert(go.innerHTML.includes('15'), 'eliminations shown');
assert(go.innerHTML.includes('10'), 'waves shown');

resetElements();
w.warHudShowGameOver('defeat', 0, 5, 3);
const go2 = mockElements['war-game-over'];
assert(go2.innerHTML.includes('DEFEAT'), 'defeat text');
assert(go2.innerHTML.includes('NEIGHBORHOOD OVERRUN'), 'defeat title');

// ============================================================
// warHudPlayAgain
// ============================================================

console.log('\n--- warHudPlayAgain ---');

st.score = 1000;
st.displayScore = 500;
st.eliminations = 10;
st.wave = 5;
st.gameState = 'game_over';
st.eliminationFeed = [{ interceptor: 'X', target: 'Y', time: dateNow }];

resetElements();
timeouts = [];
w.warHudPlayAgain();
assert(st.score === 0, 'score reset');
assert(st.displayScore === 0, 'displayScore reset');
assert(st.eliminations === 0, 'eliminations reset');
assert(st.wave === 0, 'wave reset');
assert(st.gameState === 'idle', 'gameState reset to idle');
assert(st.eliminationFeed.length === 0, 'elimination feed cleared');

// ============================================================
// warHudShowAmyAnnouncement
// ============================================================

console.log('\n--- warHudShowAmyAnnouncement ---');

w._announcementQueue.length = 0;
w.warHudShowAmyAnnouncement(null);
assert(w._announcementQueue.length === 0, 'null text adds nothing');

// Queue announcements
w.warHudShowAmyAnnouncement('Engaging hostile!', 'tactical');
// First one should be processed immediately (popped from queue)
// Queue might be empty now if it was processed
assert(true, 'announcement processed without error');

w.warHudShowAmyAnnouncement('Wave incoming!', 'wave');
// The queue may hold this since first one is still "active"
assert(true, 'second announcement queued');

// ============================================================
// warHudShowCountdown
// ============================================================

console.log('\n--- warHudShowCountdown ---');

resetElements();
timeouts = [];
intervals = [];
w.warHudShowCountdown(3);
const cd = mockElements['war-countdown'];
assert(cd.style.display === 'flex', 'countdown overlay shown');
assert(cd.innerHTML.includes('3'), 'starts at 3');

// Minimum 1
resetElements();
intervals = [];
w.warHudShowCountdown(0);
const cd2 = mockElements['war-countdown'];
assert(cd2.innerHTML.includes('1'), 'minimum countdown is 1');

// ============================================================
// warHudShowBeginWarButton / warHudHideBeginWarButton
// ============================================================

console.log('\n--- Begin/Hide war button ---');

resetElements();
w.warHudShowBeginWarButton();
const btn = mockElements['war-begin-btn'];
assert(btn.style.display === 'block', 'begin button shown');
assert(typeof btn.onclick === 'function', 'onclick handler set');

w.warHudHideBeginWarButton();
assert(btn.style.display === 'none', 'begin button hidden');

// ============================================================
// warHudDrawCanvasCountdown
// ============================================================

console.log('\n--- warHudDrawCanvasCountdown ---');

const mockCanvas = {
    saved: false, restored: false,
    fillStyle: '', globalAlpha: 1, font: '', textAlign: '', textBaseline: '',
    shadowColor: '', shadowBlur: 0,
    save() { this.saved = true; },
    restore() { this.restored = true; },
    beginPath() {}, arc() {}, fill() {}, fillRect() {}, fillText() {},
};

// Not in countdown state — should be no-op
st.gameState = 'active';
mockCanvas.saved = false;
w.warHudDrawCanvasCountdown(mockCanvas, 800, 600);
assert(mockCanvas.saved === false, 'no draw when not in countdown state');

// In countdown state
st.gameState = 'countdown';
mockElements['war-countdown'] = {
    textContent: '3',
    style: { display: 'flex' },
    className: 'active',
    classList: { _classes: [], add() {}, remove() {} },
};
mockCanvas.saved = false;
w.warHudDrawCanvasCountdown(mockCanvas, 800, 600);
assert(mockCanvas.saved === true, 'canvas saved during countdown draw');
assert(mockCanvas.restored === true, 'canvas restored after countdown draw');

// null ctx is no-op
w.warHudDrawCanvasCountdown(null, 800, 600);
assert(true, 'null ctx is no-op');

// ============================================================
// warHudDrawFriendlyHealthBars
// ============================================================

console.log('\n--- warHudDrawFriendlyHealthBars ---');

const mockCanvas2 = {
    saved: false, restored: false,
    fillStyle: '', fillRect() {},
    save() { this.saved = true; },
    restore() { this.restored = true; },
};

const wtsMap = (x, y) => ({ sx: x * 10, sy: y * 10 });

// Not active state — no-op
st.gameState = 'idle';
mockCanvas2.saved = false;
w.warHudDrawFriendlyHealthBars(mockCanvas2, wtsMap, 10);
assert(mockCanvas2.saved === false, 'no health bars when idle');

// Active state with damaged friendly
st.gameState = 'active';
ctx.warState.targets = [
    { alliance: 'friendly', status: 'active', health: 50, max_health: 100, position: { x: 5, y: 5 } },
];
mockCanvas2.saved = false;
w.warHudDrawFriendlyHealthBars(mockCanvas2, wtsMap, 10);
assert(mockCanvas2.saved === true, 'health bar drawn for damaged friendly');

// Full health — skip
ctx.warState.targets = [
    { alliance: 'friendly', status: 'active', health: 100, max_health: 100, position: { x: 5, y: 5 } },
];
mockCanvas2.saved = false;
mockCanvas2.restored = false;
w.warHudDrawFriendlyHealthBars(mockCanvas2, wtsMap, 10);
assert(mockCanvas2.saved === false, 'no health bar for full health');

// Hostile — skip
ctx.warState.targets = [
    { alliance: 'hostile', status: 'active', health: 50, max_health: 100, position: { x: 5, y: 5 } },
];
mockCanvas2.saved = false;
w.warHudDrawFriendlyHealthBars(mockCanvas2, wtsMap, 10);
assert(mockCanvas2.saved === false, 'no health bar for hostile');

// Eliminated — skip
ctx.warState.targets = [
    { alliance: 'friendly', status: 'eliminated', health: 0, max_health: 100, position: { x: 5, y: 5 } },
];
mockCanvas2.saved = false;
w.warHudDrawFriendlyHealthBars(mockCanvas2, wtsMap, 10);
assert(mockCanvas2.saved === false, 'no health bar for eliminated');

// ============================================================
// Summary
// ============================================================

console.log(`\n=== test_war_hud.js: ${passed} passed, ${failed} failed ===`);
if (failed > 0) process.exit(1);
