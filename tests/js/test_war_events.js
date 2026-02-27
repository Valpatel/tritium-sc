/**
 * TRITIUM-SC War Room -- Event Mapper tests
 * Run: node tests/js/test_war_events.js
 *
 * Tests WarEventMapper — event-to-audio routing, game state tracking,
 * elimination streak effects, event priorities, and handler wiring.
 */

const fs = require('fs');
const vm = require('vm');

let passed = 0, failed = 0;
function assert(cond, msg) {
    if (!cond) { console.error('FAIL:', msg); failed++; }
    else { console.log('PASS:', msg); passed++; }
}

const eventsCode = fs.readFileSync(__dirname + '/../../frontend/js/war-events.js', 'utf8');

// Mock warAudio that records all calls
let audioCalls = [];
const mockWarAudio = {
    play(name) { audioCalls.push({ method: 'play', name }); },
    playAt(name, x, y) { audioCalls.push({ method: 'playAt', name, x, y }); },
    startAmbient() { audioCalls.push({ method: 'startAmbient' }); },
    stopAmbient() { audioCalls.push({ method: 'stopAmbient' }); },
    init() { audioCalls.push({ method: 'init' }); },
    preload(list) { audioCalls.push({ method: 'preload', list }); return { then: (cb) => cb() }; },
    preloadAll() { audioCalls.push({ method: 'preloadAll' }); },
};

// Context with mock audio and DOM
const eventListeners = {};
const ctx = vm.createContext({
    Math, Date, console, Array, Object, Number, Boolean, parseInt, parseFloat, Infinity,
    setTimeout: (fn) => fn(), // Execute immediately
    warAudio: mockWarAudio,
    window: {},
    document: {
        readyState: 'complete',
        addEventListener(type, fn, opts) {
            eventListeners[type] = eventListeners[type] || [];
            eventListeners[type].push(fn);
        },
    },
});

vm.runInContext(eventsCode, ctx);

const { WarEventMapper, warEventMapper } = ctx.window;

function resetAudio() { audioCalls = []; }

// ============================================================
// Event priorities
// ============================================================

console.log('\n--- Event priorities ---');

const priorities = warEventMapper.getPriorities();
assert(priorities.game === 3, 'game priority is 3 (highest)');
assert(priorities.combat === 2, 'combat priority is 2');
assert(priorities.ambient === 1, 'ambient priority is 1 (lowest)');

// ============================================================
// Event mappings
// ============================================================

console.log('\n--- Event mappings ---');

const mappings = warEventMapper.getEventMappings();
assert(mappings.projectile_fired === 'nerf_shot', 'projectile_fired -> nerf_shot');
assert(mappings.projectile_hit === 'impact_hit', 'projectile_hit -> impact_hit');
assert(mappings.target_eliminated === 'explosion', 'target_eliminated -> explosion');
assert(mappings.wave_start === 'wave_start', 'wave_start -> wave_start');
assert(mappings.wave_complete === 'wave_start', 'wave_complete -> wave_start (reuse)');
assert(mappings.game_over_victory === 'victory_fanfare', 'game_over_victory -> victory_fanfare');
assert(mappings.game_over_defeat === 'defeat_sting', 'game_over_defeat -> defeat_sting');
assert(mappings.turret_rotate === 'turret_rotate', 'turret_rotate mapped');
assert(mappings.drone_move === 'drone_buzz', 'drone_move mapped');
assert(mappings.dispatch === 'dispatch_ack', 'dispatch -> dispatch_ack');
assert(mappings.alert === 'alert_tone', 'alert -> alert_tone');
assert(mappings.escalation === 'escalation_siren', 'escalation -> escalation_siren');

// Mappings return a copy
mappings.projectile_fired = 'MODIFIED';
assert(warEventMapper.getEventMappings().projectile_fired === 'nerf_shot', 'getEventMappings returns copy');

// ============================================================
// Elimination streak effects
// ============================================================

console.log('\n--- Elimination streak effects ---');

assert(warEventMapper.getEliminationStreakEffect(3) === 'elimination_streak_killing_spree', 'streak 3 effect');
assert(warEventMapper.getEliminationStreakEffect(5) === 'elimination_streak_rampage', 'streak 5 effect');
assert(warEventMapper.getEliminationStreakEffect(7) === 'elimination_streak_dominating', 'streak 7 effect');
assert(warEventMapper.getEliminationStreakEffect(10) === 'elimination_streak_godlike', 'streak 10 effect');
assert(warEventMapper.getEliminationStreakEffect(4) === null, 'non-threshold returns null');
assert(warEventMapper.getEliminationStreakEffect(0) === null, 'zero streak returns null');

// Backwards compatibility alias
assert(warEventMapper.getKillStreakEffect(3) === 'elimination_streak_killing_spree', 'getKillStreakEffect alias works');

// ============================================================
// handleEvent
// ============================================================

console.log('\n--- handleEvent ---');

resetAudio();
warEventMapper.handleEvent('projectile_fired', {});
assert(audioCalls.length === 1, 'handleEvent triggers audio');
assert(audioCalls[0].method === 'play', 'uses play() for event without position');
assert(audioCalls[0].name === 'nerf_shot', 'plays nerf_shot');

resetAudio();
warEventMapper.handleEvent('projectile_fired', { x: 10, y: 20 });
assert(audioCalls[0].method === 'playAt', 'uses playAt() for positioned event');
assert(audioCalls[0].x === 10, 'x position passed');
assert(audioCalls[0].y === 20, 'y position passed');

resetAudio();
warEventMapper.handleEvent('unknown_event', {});
assert(audioCalls.length === 0, 'unknown event plays nothing');

// ============================================================
// onGameStateChange
// ============================================================

console.log('\n--- onGameStateChange ---');

resetAudio();
warEventMapper.onGameStateChange({ state: 'active' });
assert(warEventMapper._gameActive === true, 'game active flag set');
assert(audioCalls.some(c => c.method === 'startAmbient'), 'ambient started on active');

resetAudio();
warEventMapper.onGameStateChange({ state: 'setup' });
assert(warEventMapper._gameActive === false, 'game active flag cleared on setup');
assert(audioCalls.some(c => c.method === 'stopAmbient'), 'ambient stopped on setup');

resetAudio();
warEventMapper.onGameStateChange({ state: 'idle' });
assert(warEventMapper._gameActive === false, 'game active flag cleared on idle');

resetAudio();
warEventMapper.onGameStateChange({ state: 'game_over' });
assert(warEventMapper._gameActive === false, 'game active cleared on game_over');
assert(audioCalls.some(c => c.method === 'stopAmbient'), 'ambient stopped on game_over');

resetAudio();
warEventMapper.onGameStateChange({ state: 'victory' });
assert(warEventMapper._gameActive === false, 'game active cleared on victory');

resetAudio();
warEventMapper.onGameStateChange({ state: 'defeat' });
assert(warEventMapper._gameActive === false, 'game active cleared on defeat');

// new_state field
resetAudio();
warEventMapper.onGameStateChange({ new_state: 'active' });
assert(warEventMapper._gameActive === true, 'new_state field works');

// null data
resetAudio();
warEventMapper.onGameStateChange(null);
assert(audioCalls.length === 0, 'null data is no-op');

// ============================================================
// onProjectileFired
// ============================================================

console.log('\n--- onProjectileFired ---');

resetAudio();
warEventMapper.onProjectileFired({ source_pos: { x: 5, y: 10 } });
assert(audioCalls[0].method === 'playAt', 'uses playAt');
assert(audioCalls[0].name === 'nerf_shot', 'plays nerf_shot');
assert(audioCalls[0].x === 5, 'x from source_pos');
assert(audioCalls[0].y === 10, 'y from source_pos');

resetAudio();
warEventMapper.onProjectileFired({});
assert(audioCalls[0].x === 0, 'missing pos defaults to 0');

resetAudio();
warEventMapper.onProjectileFired(null);
assert(audioCalls.length === 0, 'null is no-op');

// ============================================================
// onProjectileHit
// ============================================================

console.log('\n--- onProjectileHit ---');

resetAudio();
warEventMapper.onProjectileHit({ target_pos: { x: 15, y: 25 } });
assert(audioCalls[0].name === 'impact_hit', 'plays impact_hit');
assert(audioCalls[0].x === 15, 'x from target_pos');

resetAudio();
warEventMapper.onProjectileHit({ position: { x: 30, y: 40 } });
assert(audioCalls[0].x === 30, 'fallback to position field');

resetAudio();
warEventMapper.onProjectileHit(null);
assert(audioCalls.length === 0, 'null is no-op');

// ============================================================
// onTargetEliminated
// ============================================================

console.log('\n--- onTargetEliminated ---');

resetAudio();
warEventMapper.onTargetEliminated({ position: { x: 20, y: 30 } });
assert(audioCalls[0].name === 'explosion', 'plays explosion');
assert(audioCalls[0].x === 20, 'x from position');

resetAudio();
warEventMapper.onTargetEliminated(null);
assert(audioCalls.length === 0, 'null is no-op');

// ============================================================
// onWaveStart
// ============================================================

console.log('\n--- onWaveStart ---');

resetAudio();
warEventMapper.onWaveStart({});
assert(audioCalls[0].method === 'play', 'uses play()');
assert(audioCalls[0].name === 'wave_start', 'plays wave_start');

// ============================================================
// onKillStreak
// ============================================================

console.log('\n--- onKillStreak ---');

resetAudio();
warEventMapper.onKillStreak({ streak: 5 });
assert(audioCalls[0].name === 'elimination_streak_rampage', 'streak 5 plays rampage');

resetAudio();
warEventMapper.onKillStreak({ streak: 2 });
assert(audioCalls.length === 0, 'non-threshold streak plays nothing');

resetAudio();
warEventMapper.onKillStreak(null);
assert(audioCalls.length === 0, 'null is no-op');

// ============================================================
// onGameOver
// ============================================================

console.log('\n--- onGameOver ---');

resetAudio();
warEventMapper._gameActive = true;
warEventMapper.onGameOver({ result: 'victory' });
assert(warEventMapper._gameActive === false, 'game active cleared');
assert(audioCalls.some(c => c.method === 'stopAmbient'), 'ambient stopped');
assert(audioCalls.some(c => c.name === 'victory_fanfare'), 'victory plays fanfare');

resetAudio();
warEventMapper.onGameOver({ result: 'defeat' });
assert(audioCalls.some(c => c.name === 'defeat_sting'), 'defeat plays sting');

resetAudio();
warEventMapper.onGameOver({ result: 'VICTORY' });
assert(audioCalls.some(c => c.name === 'victory_fanfare'), 'case insensitive victory');

resetAudio();
warEventMapper.onGameOver({ result: '' });
assert(audioCalls.some(c => c.name === 'defeat_sting'), 'empty result defaults to defeat');

resetAudio();
warEventMapper.onGameOver(null);
assert(audioCalls.length === 0, 'null is no-op');

// ============================================================
// Utility event handlers
// ============================================================

console.log('\n--- Utility event handlers ---');

resetAudio();
warEventMapper.onDispatch({});
assert(audioCalls[0].name === 'dispatch_ack', 'onDispatch plays dispatch_ack');

resetAudio();
warEventMapper.onAlert({});
assert(audioCalls[0].name === 'alert_tone', 'onAlert plays alert_tone');

resetAudio();
warEventMapper.onEscalation({});
assert(audioCalls[0].name === 'escalation_siren', 'onEscalation plays escalation_siren');

resetAudio();
warEventMapper.onWaveComplete({});
assert(audioCalls[0].name === 'wave_start', 'onWaveComplete plays wave_start');

resetAudio();
warEventMapper.onCountdown({});
assert(audioCalls[0].name === 'alert_tone', 'onCountdown plays alert_tone');

resetAudio();
warEventMapper.onAmyAnnouncement({});
assert(audioCalls[0].name === 'dispatch_ack', 'onAmyAnnouncement plays dispatch_ack');

// ============================================================
// WarEventMapper constructor
// ============================================================

console.log('\n--- WarEventMapper constructor ---');

const customAudio = { play() {}, playAt() {}, startAmbient() {}, stopAmbient() {} };
const custom = new WarEventMapper(customAudio);
assert(custom._audio === customAudio, 'custom audio manager set');
assert(custom._gameActive === false, 'starts inactive');

const defaultMapper = new WarEventMapper();
assert(defaultMapper._audio === mockWarAudio, 'default uses global warAudio');

// ============================================================
// Audio initialization on gesture
// ============================================================

console.log('\n--- Audio initialization ---');

// _initWarAudioOnGesture should exist
assert(typeof ctx.window._initWarAudioOnGesture === 'function', '_initWarAudioOnGesture exposed');

// Document listeners registered for click and keydown
assert(eventListeners.click && eventListeners.click.length > 0, 'click listener registered');
assert(eventListeners.keydown && eventListeners.keydown.length > 0, 'keydown listener registered');

// ============================================================
// Summary
// ============================================================

console.log(`\n=== test_war_events.js: ${passed} passed, ${failed} failed ===`);
if (failed > 0) process.exit(1);
