// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
/**
 * TRITIUM-SC War Audio tests
 * Tests AudioManager logic, event mapping, debounce, priority
 * Run: node tests/js/test_war_audio.js
 */

const fs = require('fs');
const vm = require('vm');

// Simple test runner
let passed = 0, failed = 0;
function assert(cond, msg) {
    if (!cond) { console.error('FAIL:', msg); failed++; }
    else { console.log('PASS:', msg); passed++; }
}
function assertClose(a, b, eps, msg) {
    assert(Math.abs(a - b) < (eps || 0.001), msg + ` (got ${a}, expected ${b})`);
}

// ============================================================
// Load war-audio.js into a sandboxed context
// ============================================================

const audioCode = fs.readFileSync(__dirname + '/../../frontend/js/war-audio.js', 'utf8');
const eventsCode = fs.readFileSync(__dirname + '/../../frontend/js/war-events.js', 'utf8');

// Mock Web Audio API
class MockAudioContext {
    constructor() {
        this.sampleRate = 44100;
        this.state = 'running';
        this.destination = {};
        this._decodeCount = 0;
    }
    createBufferSource() {
        return {
            buffer: null,
            connect() {},
            start() {},
            stop() {},
            disconnect() {},
            playbackRate: { value: 1 },
            loop: false,
            onended: null,
        };
    }
    createGain() {
        return {
            gain: { value: 1, setValueAtTime() {}, linearRampToValueAtTime() {} },
            connect() {},
            disconnect() {},
        };
    }
    createStereoPanner() {
        return {
            pan: { value: 0, setValueAtTime() {} },
            connect() {},
            disconnect() {},
        };
    }
    decodeAudioData(buffer) {
        this._decodeCount++;
        return Promise.resolve({ duration: 0.5, length: 22050, numberOfChannels: 1 });
    }
    resume() { return Promise.resolve(); }
}

class MockResponse {
    constructor(ok) { this.ok = ok !== false; }
    arrayBuffer() { return Promise.resolve(new ArrayBuffer(100)); }
    json() { return Promise.resolve([]); }
}

let fetchCalls = [];
function mockFetch(url) {
    fetchCalls.push(url);
    return Promise.resolve(new MockResponse(true));
}

// Create sandbox
const sandbox = {
    Math, Date, console, Map, Set, Array, Object, Number, String, Boolean,
    Infinity, NaN, undefined, parseInt, parseFloat, isNaN, isFinite,
    Promise, setTimeout, clearTimeout, setInterval, clearInterval,
    AudioContext: MockAudioContext,
    webkitAudioContext: MockAudioContext,
    ArrayBuffer,
    fetch: mockFetch,
    window: {},
    document: {
        addEventListener() {},
        getElementById() { return null; },
    },
    performance: { now: () => Date.now() },
};
// window references itself
sandbox.window = sandbox;

const ctx = vm.createContext(sandbox);

// Load the modules
vm.runInContext(audioCode, ctx);
vm.runInContext(eventsCode, ctx);

// ============================================================
// AudioManager tests
// ============================================================

console.log('\n--- AudioManager ---');

(function testAudioManagerExists() {
    assert(typeof ctx.WarAudioManager === 'function', 'WarAudioManager class exists');
})();

(function testCanCreateInstance() {
    const mgr = new ctx.WarAudioManager();
    assert(mgr !== null && mgr !== undefined, 'Can create WarAudioManager instance');
})();

(function testDefaultVolume() {
    const mgr = new ctx.WarAudioManager();
    assertClose(mgr.getVolume(), 0.7, 0.01, 'Default volume is 0.7');
})();

(function testSetVolume() {
    const mgr = new ctx.WarAudioManager();
    mgr.setVolume(0.5);
    assertClose(mgr.getVolume(), 0.5, 0.01, 'setVolume(0.5) works');
})();

(function testVolumeClampHigh() {
    const mgr = new ctx.WarAudioManager();
    mgr.setVolume(1.5);
    assertClose(mgr.getVolume(), 1.0, 0.01, 'Volume clamped to 1.0');
})();

(function testVolumeClampLow() {
    const mgr = new ctx.WarAudioManager();
    mgr.setVolume(-0.5);
    assertClose(mgr.getVolume(), 0.0, 0.01, 'Volume clamped to 0.0');
})();

(function testMute() {
    const mgr = new ctx.WarAudioManager();
    mgr.setMuted(true);
    assert(mgr.isMuted() === true, 'setMuted(true) mutes');
})();

(function testUnmute() {
    const mgr = new ctx.WarAudioManager();
    mgr.setMuted(true);
    mgr.setMuted(false);
    assert(mgr.isMuted() === false, 'setMuted(false) unmutes');
})();

(function testToggleMute() {
    const mgr = new ctx.WarAudioManager();
    mgr.toggleMute();
    assert(mgr.isMuted() === true, 'toggleMute once -> muted');
    mgr.toggleMute();
    assert(mgr.isMuted() === false, 'toggleMute twice -> unmuted');
})();

// ============================================================
// Event mapping tests
// ============================================================

console.log('\n--- WarEventMapper ---');

(function testEventMapperExists() {
    assert(typeof ctx.WarEventMapper === 'function', 'WarEventMapper class exists');
})();

(function testMapperHasEventMappings() {
    const mapper = new ctx.WarEventMapper(new ctx.WarAudioManager());
    assert(typeof mapper.handleEvent === 'function', 'handleEvent method exists');
})();

(function testEventToEffectMapping() {
    const mapper = new ctx.WarEventMapper(new ctx.WarAudioManager());
    // Check known mappings
    const mappings = mapper.getEventMappings();
    assert(mappings !== null, 'getEventMappings returns object');
    assert(mappings['projectile_fired'] === 'nerf_shot', 'projectile_fired -> nerf_shot');
    assert(mappings['projectile_hit'] === 'impact_hit', 'projectile_hit -> impact_hit');
    assert(mappings['target_eliminated'] === 'explosion', 'target_eliminated -> explosion');
    assert(mappings['wave_start'] === 'wave_start', 'wave_start -> wave_start');
    assert(mappings['game_over_victory'] === 'victory_fanfare', 'game_over_victory -> victory_fanfare');
    assert(mappings['game_over_defeat'] === 'defeat_sting', 'game_over_defeat -> defeat_sting');
})();

// ============================================================
// Debounce tests
// ============================================================

console.log('\n--- Debounce ---');

(function testDebounceTracking() {
    const mgr = new ctx.WarAudioManager();
    // Simulate rapid fire - should be debounced
    const played = [];
    mgr._playInternal = function(name) { played.push(name); };

    // First play should work
    mgr.play('nerf_shot');
    assert(played.length === 1, 'First play goes through');

    // Immediate second play of same effect should be debounced
    mgr.play('nerf_shot');
    assert(played.length === 1, 'Rapid duplicate debounced');

    // Different effect should go through
    mgr.play('explosion');
    assert(played.length === 2, 'Different effect goes through');
})();

// ============================================================
// Priority tests
// ============================================================

console.log('\n--- Priority ---');

(function testPriorityCategories() {
    const mapper = new ctx.WarEventMapper(new ctx.WarAudioManager());
    const priorities = mapper.getPriorities();
    assert(priorities !== null, 'getPriorities returns object');
    // Game state changes should be highest priority
    assert(priorities['game'] > priorities['combat'], 'game > combat priority');
    assert(priorities['combat'] > priorities['ambient'], 'combat > ambient priority');
})();

// ============================================================
// Effect name helpers
// ============================================================

console.log('\n--- Effect helpers ---');

(function testEliminationStreakEffectName() {
    const mapper = new ctx.WarEventMapper(new ctx.WarAudioManager());
    const name = mapper.getEliminationStreakEffect(3);
    assert(name === 'elimination_streak_killing_spree', 'streak 3 -> killing_spree');
})();

(function testEliminationStreakEffectNameRampage() {
    const mapper = new ctx.WarEventMapper(new ctx.WarAudioManager());
    const name = mapper.getEliminationStreakEffect(5);
    assert(name === 'elimination_streak_rampage', 'streak 5 -> rampage');
})();

(function testEliminationStreakEffectNameDominating() {
    const mapper = new ctx.WarEventMapper(new ctx.WarAudioManager());
    const name = mapper.getEliminationStreakEffect(7);
    assert(name === 'elimination_streak_dominating', 'streak 7 -> dominating');
})();

(function testEliminationStreakEffectNameGodlike() {
    const mapper = new ctx.WarEventMapper(new ctx.WarAudioManager());
    const name = mapper.getEliminationStreakEffect(10);
    assert(name === 'elimination_streak_godlike', 'streak 10 -> godlike');
})();

// ============================================================
// New handler methods (wave_complete, countdown, announcement)
// ============================================================

console.log('\n--- New handler methods ---');

(function testOnWaveCompleteExists() {
    const mapper = new ctx.WarEventMapper(new ctx.WarAudioManager());
    assert(typeof mapper.onWaveComplete === 'function', 'onWaveComplete method exists');
})();

(function testOnCountdownExists() {
    const mapper = new ctx.WarEventMapper(new ctx.WarAudioManager());
    assert(typeof mapper.onCountdown === 'function', 'onCountdown method exists');
})();

(function testOnAmyAnnouncementExists() {
    const mapper = new ctx.WarEventMapper(new ctx.WarAudioManager());
    assert(typeof mapper.onAmyAnnouncement === 'function', 'onAmyAnnouncement method exists');
})();

(function testOnWaveCompleteCallsPlay() {
    const played = [];
    const mockAudio = { play: function(n) { played.push(n); }, playAt: function() {}, startAmbient: function() {}, stopAmbient: function() {} };
    const mapper = new ctx.WarEventMapper(mockAudio);
    mapper.onWaveComplete({});
    assert(played.length === 1, 'onWaveComplete triggers audio');
    assert(played[0] === 'wave_start', 'onWaveComplete plays wave_start');
})();

(function testOnCountdownCallsPlay() {
    const played = [];
    const mockAudio = { play: function(n) { played.push(n); }, playAt: function() {}, startAmbient: function() {}, stopAmbient: function() {} };
    const mapper = new ctx.WarEventMapper(mockAudio);
    mapper.onCountdown({ seconds: 3 });
    assert(played.length === 1, 'onCountdown triggers audio');
    assert(played[0] === 'alert_tone', 'onCountdown plays alert_tone');
})();

(function testOnAmyAnnouncementCallsPlay() {
    const played = [];
    const mockAudio = { play: function(n) { played.push(n); }, playAt: function() {}, startAmbient: function() {}, stopAmbient: function() {} };
    const mapper = new ctx.WarEventMapper(mockAudio);
    mapper.onAmyAnnouncement({ text: 'HOSTILE DOWN!', category: 'combat' });
    assert(played.length === 1, 'onAmyAnnouncement triggers audio');
    assert(played[0] === 'dispatch_ack', 'onAmyAnnouncement plays dispatch_ack');
})();

// ============================================================
// Concurrent sound limit
// ============================================================

console.log('\n--- Concurrent limits ---');

(function testMaxConcurrentSounds() {
    const mgr = new ctx.WarAudioManager();
    assert(mgr.maxConcurrent > 0, 'maxConcurrent is positive');
    assert(mgr.maxConcurrent <= 16, 'maxConcurrent is reasonable (<=16)');
})();

// ============================================================
// Summary
// ============================================================

console.log(`\n${'='.repeat(40)}`);
console.log(`Results: ${passed} passed, ${failed} failed`);
console.log(`${'='.repeat(40)}`);

process.exit(failed > 0 ? 1 : 0);
