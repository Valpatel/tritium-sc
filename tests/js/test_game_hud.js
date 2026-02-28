// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
/**
 * TRITIUM-SC Game HUD Panel Tests
 * Tests all pure helper functions, CombatStatsTracker, HTML builders,
 * and backward compatibility with missing telemetry fields.
 * Run: node tests/js/test_game_hud.js
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
function assertContains(str, sub, msg) {
    assert(typeof str === 'string' && str.includes(sub), msg + ` (expected "${sub}" in "${str}")`);
}

// ============================================================
// DOM + browser mocks
// ============================================================

function createMockElement(tag) {
    const children = [];
    const classList = new Set();
    const style = {};
    const dataset = {};
    let _textContent = '';
    let _innerHTML = '';
    const el = {
        tagName: tag || 'DIV',
        className: '',
        get innerHTML() { return _innerHTML; },
        set innerHTML(v) { _innerHTML = v; },
        get textContent() { return _textContent; },
        set textContent(v) {
            _textContent = String(v);
            // Simulate browser behavior: textContent escapes HTML
            _innerHTML = String(v)
                .replace(/&/g, '&amp;')
                .replace(/</g, '&lt;')
                .replace(/>/g, '&gt;')
                .replace(/"/g, '&quot;');
        },
        style,
        dataset,
        children,
        childNodes: children,
        parentNode: null,
        classList: {
            add(cls) { classList.add(cls); el.className = [...classList].join(' '); },
            remove(cls) { classList.delete(cls); el.className = [...classList].join(' '); },
            contains(cls) { return classList.has(cls); },
            toggle(cls) {
                if (classList.has(cls)) classList.delete(cls);
                else classList.add(cls);
                el.className = [...classList].join(' ');
            },
        },
        appendChild(child) { children.push(child); return child; },
        removeChild(child) {
            const i = children.indexOf(child);
            if (i >= 0) children.splice(i, 1);
            return child;
        },
        querySelector(sel) { return null; },
        querySelectorAll(sel) { return []; },
        addEventListener() {},
        removeEventListener() {},
        getBoundingClientRect() { return { top: 0, left: 0, width: 100, height: 100 }; },
        setAttribute(k, v) { el[k] = v; },
        getAttribute(k) { return el[k]; },
        get offsetWidth() { return 100; },
        get offsetHeight() { return 100; },
    };
    return el;
}

const mockDocument = {
    createElement: (tag) => createMockElement(tag),
    getElementById: () => null,
    querySelector: () => null,
    querySelectorAll: () => [],
    body: createMockElement('BODY'),
    documentElement: createMockElement('HTML'),
};

// ============================================================
// Load game-hud.js as a module (ESM -> we load and extract helpers)
// The file uses ES module imports, so we need to handle that
// We'll create a context with the needed globals and run the helpers portion
// ============================================================

// We need to load game-hud.js. It uses ES module imports (import { TritiumStore } ...)
// which won't work in vm.runInContext. We'll load only the helpers/tracker that are
// exposed on window.GameHudHelpers and window.CombatStatsTracker.
// The approach: read the file, strip the ESM import/export, provide mocks.

const gameHudCode = fs.readFileSync(__dirname + '/../../frontend/js/command/panels/game-hud.js', 'utf8');

// Strip ES module import statements and export keyword
let processedCode = gameHudCode
    .replace(/^import\s+.*?from\s+['"].*?['"];?\s*$/gm, '')
    .replace(/^export\s+/gm, '');

// Create sandbox
const ctx = vm.createContext({
    Math, Date, console, Map, Array, Object, Number, Infinity, Boolean, String,
    parseInt, parseFloat, isNaN, isFinite, undefined, null: null,
    JSON, Error, TypeError, RangeError,
    setTimeout: (fn) => fn(),
    setInterval: () => 0,
    clearInterval: () => {},
    clearTimeout: () => {},
    document: mockDocument,
    window: {},
    fetch: () => Promise.resolve({ ok: true, json: () => Promise.resolve({}) }),
    // Mock TritiumStore and EventBus (used in original code)
    TritiumStore: {
        game: { phase: 'idle', wave: 0, totalWaves: 10, score: 0, eliminations: 0 },
        on: () => () => {},
        set: () => {},
    },
    EventBus: {
        emit: () => {},
        on: () => () => {},
    },
});

try {
    vm.runInContext(processedCode, ctx);
} catch (e) {
    console.error('Failed to load game-hud.js:', e.message);
    // If it fails because helpers haven't been added yet, tests will fail naturally
}

const H = ctx.window.GameHudHelpers || {};
const CombatStatsTracker = ctx.window.CombatStatsTracker;

// ============================================================
// 1. healthColor(ratio)
// ============================================================
console.log('\n--- healthColor ---');

(function testHealthColorGreen() {
    assert(H.healthColor && H.healthColor(1.0) === '#05ffa1', 'healthColor 100% = green');
})();

(function testHealthColorGreen61() {
    assert(H.healthColor && H.healthColor(0.61) === '#05ffa1', 'healthColor 61% = green');
})();

(function testHealthColorYellow60() {
    assert(H.healthColor && H.healthColor(0.60) === '#fcee0a', 'healthColor 60% = yellow');
})();

(function testHealthColorYellow35() {
    assert(H.healthColor && H.healthColor(0.35) === '#fcee0a', 'healthColor 35% = yellow');
})();

(function testHealthColorRed29() {
    assert(H.healthColor && H.healthColor(0.29) === '#ff2a6d', 'healthColor 29% = red');
})();

(function testHealthColorRedZero() {
    assert(H.healthColor && H.healthColor(0) === '#ff2a6d', 'healthColor 0% = red');
})();

// ============================================================
// 2. healthBar(ratio, width)
// ============================================================
console.log('\n--- healthBar ---');

(function testHealthBarFull() {
    if (!H.healthBar) { assert(false, 'healthBar not defined'); return; }
    const bar = H.healthBar(1.0, 10);
    assert(bar.length === 10, 'healthBar full width 10 = 10 chars');
})();

(function testHealthBarHalf() {
    if (!H.healthBar) { assert(false, 'healthBar not defined'); return; }
    const bar = H.healthBar(0.5, 10);
    assert(bar.length === 10, 'healthBar half width 10 = 10 chars');
    // First 5 should be filled blocks, rest should be empty blocks
    const filledCount = (bar.match(/\u2588/g) || []).length;
    assert(filledCount === 5, 'healthBar 50% has 5 filled blocks');
})();

(function testHealthBarZero() {
    if (!H.healthBar) { assert(false, 'healthBar not defined'); return; }
    const bar = H.healthBar(0, 10);
    const filledCount = (bar.match(/\u2588/g) || []).length;
    assert(filledCount === 0, 'healthBar 0% has 0 filled blocks');
})();

(function testHealthBarDefaultWidth() {
    if (!H.healthBar) { assert(false, 'healthBar not defined'); return; }
    const bar = H.healthBar(1.0);
    assert(bar.length > 0, 'healthBar defaults to some width');
})();

// ============================================================
// 3. moraleTrend(current, previous)
// ============================================================
console.log('\n--- moraleTrend ---');

(function testMoraleTrendRising() {
    if (!H.moraleTrend) { assert(false, 'moraleTrend not defined'); return; }
    assert(H.moraleTrend(0.8, 0.5) === 'rising', 'moraleTrend 0.8 vs 0.5 = rising');
})();

(function testMoraleTrendFalling() {
    if (!H.moraleTrend) { assert(false, 'moraleTrend not defined'); return; }
    assert(H.moraleTrend(0.3, 0.7) === 'falling', 'moraleTrend 0.3 vs 0.7 = falling');
})();

(function testMoraleTrendSteady() {
    if (!H.moraleTrend) { assert(false, 'moraleTrend not defined'); return; }
    assert(H.moraleTrend(0.51, 0.50) === 'steady', 'moraleTrend 0.51 vs 0.50 = steady (within 5%)');
})();

(function testMoraleTrendExactThreshold() {
    if (!H.moraleTrend) { assert(false, 'moraleTrend not defined'); return; }
    // Exactly 5% difference should be steady
    assert(H.moraleTrend(0.55, 0.50) === 'steady', 'moraleTrend 0.55 vs 0.50 = steady (exactly 5%)');
})();

(function testMoraleTrendJustOverThreshold() {
    if (!H.moraleTrend) { assert(false, 'moraleTrend not defined'); return; }
    assert(H.moraleTrend(0.56, 0.50) === 'rising', 'moraleTrend 0.56 vs 0.50 = rising (over 5%)');
})();

// ============================================================
// 4. waveProgressPct(remaining, total)
// ============================================================
console.log('\n--- waveProgressPct ---');

(function testWaveProgressAllEliminated() {
    if (!H.waveProgressPct) { assert(false, 'waveProgressPct not defined'); return; }
    assert(H.waveProgressPct(0, 10) === 100, 'waveProgressPct 0 remaining of 10 = 100%');
})();

(function testWaveProgressHalf() {
    if (!H.waveProgressPct) { assert(false, 'waveProgressPct not defined'); return; }
    assert(H.waveProgressPct(5, 10) === 50, 'waveProgressPct 5 remaining of 10 = 50%');
})();

(function testWaveProgressNoneEliminated() {
    if (!H.waveProgressPct) { assert(false, 'waveProgressPct not defined'); return; }
    assert(H.waveProgressPct(10, 10) === 0, 'waveProgressPct 10 remaining of 10 = 0%');
})();

(function testWaveProgressDivByZero() {
    if (!H.waveProgressPct) { assert(false, 'waveProgressPct not defined'); return; }
    assert(H.waveProgressPct(0, 0) === 0, 'waveProgressPct div by zero = 0');
})();

// ============================================================
// 5. computeAccuracy(hits, shots)
// ============================================================
console.log('\n--- computeAccuracy ---');

(function testAccuracyPerfect() {
    if (!H.computeAccuracy) { assert(false, 'computeAccuracy not defined'); return; }
    assert(H.computeAccuracy(10, 10) === 100, 'computeAccuracy 10/10 = 100%');
})();

(function testAccuracyHalf() {
    if (!H.computeAccuracy) { assert(false, 'computeAccuracy not defined'); return; }
    assert(H.computeAccuracy(5, 10) === 50, 'computeAccuracy 5/10 = 50%');
})();

(function testAccuracyZeroShots() {
    if (!H.computeAccuracy) { assert(false, 'computeAccuracy not defined'); return; }
    assert(H.computeAccuracy(0, 0) === 0, 'computeAccuracy 0/0 = 0');
})();

(function testAccuracyNoHits() {
    if (!H.computeAccuracy) { assert(false, 'computeAccuracy not defined'); return; }
    assert(H.computeAccuracy(0, 10) === 0, 'computeAccuracy 0/10 = 0%');
})();

// ============================================================
// 6. findMVP(units)
// ============================================================
console.log('\n--- findMVP ---');

(function testFindMVPBasic() {
    if (!H.findMVP) { assert(false, 'findMVP not defined'); return; }
    const units = [
        { target_id: 'a', name: 'Alpha', alliance: 'friendly', kills: 3 },
        { target_id: 'b', name: 'Bravo', alliance: 'friendly', kills: 7 },
        { target_id: 'c', name: 'Charlie', alliance: 'friendly', kills: 1 },
    ];
    const mvp = H.findMVP(units);
    assert(mvp && mvp.name === 'Bravo', 'findMVP picks unit with most kills');
})();

(function testFindMVPFiltersHostiles() {
    if (!H.findMVP) { assert(false, 'findMVP not defined'); return; }
    const units = [
        { target_id: 'a', name: 'Alpha', alliance: 'friendly', kills: 3 },
        { target_id: 'b', name: 'Enemy', alliance: 'hostile', kills: 99 },
    ];
    const mvp = H.findMVP(units);
    assert(mvp && mvp.name === 'Alpha', 'findMVP ignores hostile units');
})();

(function testFindMVPEmptyArray() {
    if (!H.findMVP) { assert(false, 'findMVP not defined'); return; }
    assert(H.findMVP([]) === null, 'findMVP empty array = null');
})();

(function testFindMVPNoFriendlies() {
    if (!H.findMVP) { assert(false, 'findMVP not defined'); return; }
    const units = [
        { target_id: 'a', name: 'Enemy', alliance: 'hostile', kills: 5 },
    ];
    assert(H.findMVP(units) === null, 'findMVP no friendlies = null');
})();

(function testFindMVPUsesEliminations() {
    if (!H.findMVP) { assert(false, 'findMVP not defined'); return; }
    const units = [
        { target_id: 'a', name: 'Alpha', alliance: 'friendly', eliminations: 5 },
        { target_id: 'b', name: 'Bravo', alliance: 'friendly', eliminations: 2 },
    ];
    const mvp = H.findMVP(units);
    assert(mvp && mvp.name === 'Alpha', 'findMVP uses eliminations field as fallback');
})();

// ============================================================
// 7. typeIcon(type)
// ============================================================
console.log('\n--- typeIcon ---');

(function testTypeIconTurret() {
    if (!H.typeIcon) { assert(false, 'typeIcon not defined'); return; }
    const icon = H.typeIcon('turret');
    assert(typeof icon === 'string' && icon.length > 0, 'typeIcon turret returns a symbol');
})();

(function testTypeIconDrone() {
    if (!H.typeIcon) { assert(false, 'typeIcon not defined'); return; }
    const icon = H.typeIcon('drone');
    assert(typeof icon === 'string' && icon.length > 0, 'typeIcon drone returns a symbol');
})();

(function testTypeIconRover() {
    if (!H.typeIcon) { assert(false, 'typeIcon not defined'); return; }
    const icon = H.typeIcon('rover');
    assert(typeof icon === 'string' && icon.length > 0, 'typeIcon rover returns a symbol');
})();

(function testTypeIconPerson() {
    if (!H.typeIcon) { assert(false, 'typeIcon not defined'); return; }
    const icon = H.typeIcon('person');
    assert(typeof icon === 'string' && icon.length > 0, 'typeIcon person returns a symbol');
})();

(function testTypeIconUnknown() {
    if (!H.typeIcon) { assert(false, 'typeIcon not defined'); return; }
    const icon = H.typeIcon('xyzzy_unknown_thing');
    assert(typeof icon === 'string' && icon.length > 0, 'typeIcon unknown returns fallback symbol');
})();

(function testTypeIconTank() {
    if (!H.typeIcon) { assert(false, 'typeIcon not defined'); return; }
    const icon = H.typeIcon('tank');
    assert(typeof icon === 'string' && icon.length > 0, 'typeIcon tank returns a symbol');
})();

// ============================================================
// 8. formatTime(seconds)
// ============================================================
console.log('\n--- formatTime ---');

(function testFormatTimeZero() {
    if (!H.formatTime) { assert(false, 'formatTime not defined'); return; }
    assert(H.formatTime(0) === '0:00', 'formatTime 0 = 0:00');
})();

(function testFormatTime90() {
    if (!H.formatTime) { assert(false, 'formatTime not defined'); return; }
    assert(H.formatTime(90) === '1:30', 'formatTime 90 = 1:30');
})();

(function testFormatTime5() {
    if (!H.formatTime) { assert(false, 'formatTime not defined'); return; }
    assert(H.formatTime(5) === '0:05', 'formatTime 5 = 0:05');
})();

(function testFormatTime600() {
    if (!H.formatTime) { assert(false, 'formatTime not defined'); return; }
    assert(H.formatTime(600) === '10:00', 'formatTime 600 = 10:00');
})();

(function testFormatTime61() {
    if (!H.formatTime) { assert(false, 'formatTime not defined'); return; }
    assert(H.formatTime(61) === '1:01', 'formatTime 61 = 1:01');
})();

// ============================================================
// 9. countThreats(units)
// ============================================================
console.log('\n--- countThreats ---');

(function testCountThreatsBasic() {
    if (!H.countThreats) { assert(false, 'countThreats not defined'); return; }
    const units = [
        { alliance: 'hostile', status: 'active' },
        { alliance: 'hostile', status: 'active' },
        { alliance: 'friendly', status: 'active' },
        { alliance: 'hostile', status: 'eliminated' },
    ];
    assert(H.countThreats(units) === 2, 'countThreats counts active hostiles only');
})();

(function testCountThreatsEmpty() {
    if (!H.countThreats) { assert(false, 'countThreats not defined'); return; }
    assert(H.countThreats([]) === 0, 'countThreats empty = 0');
})();

(function testCountThreatsNoHostiles() {
    if (!H.countThreats) { assert(false, 'countThreats not defined'); return; }
    const units = [
        { alliance: 'friendly', status: 'active' },
    ];
    assert(H.countThreats(units) === 0, 'countThreats no hostiles = 0');
})();

(function testCountThreatsDefaultStatus() {
    if (!H.countThreats) { assert(false, 'countThreats not defined'); return; }
    // Units with missing status default to active
    const units = [
        { alliance: 'hostile' },
        { alliance: 'hostile' },
    ];
    assert(H.countThreats(units) === 2, 'countThreats missing status defaults to active');
})();

// ============================================================
// 10. avgMorale(units)
// ============================================================
console.log('\n--- avgMorale ---');

(function testAvgMoraleBasic() {
    if (!H.avgMorale) { assert(false, 'avgMorale not defined'); return; }
    const units = [
        { alliance: 'friendly', morale: 0.8 },
        { alliance: 'friendly', morale: 0.6 },
    ];
    assertClose(H.avgMorale(units), 0.7, 0.01, 'avgMorale of 0.8 and 0.6 = 0.7');
})();

(function testAvgMoraleDefault() {
    if (!H.avgMorale) { assert(false, 'avgMorale not defined'); return; }
    const units = [
        { alliance: 'friendly' }, // missing morale
        { alliance: 'friendly', morale: 0.5 },
    ];
    assertClose(H.avgMorale(units), 0.75, 0.01, 'avgMorale missing field defaults to 1.0');
})();

(function testAvgMoraleEmpty() {
    if (!H.avgMorale) { assert(false, 'avgMorale not defined'); return; }
    assertClose(H.avgMorale([]), 1.0, 0.01, 'avgMorale empty = 1.0');
})();

(function testAvgMoraleIgnoresHostiles() {
    if (!H.avgMorale) { assert(false, 'avgMorale not defined'); return; }
    const units = [
        { alliance: 'friendly', morale: 0.4 },
        { alliance: 'hostile', morale: 0.1 },
    ];
    assertClose(H.avgMorale(units), 0.4, 0.01, 'avgMorale ignores hostile units');
})();

(function testAvgMoraleNoFriendlies() {
    if (!H.avgMorale) { assert(false, 'avgMorale not defined'); return; }
    const units = [
        { alliance: 'hostile', morale: 0.1 },
    ];
    assertClose(H.avgMorale(units), 1.0, 0.01, 'avgMorale no friendlies = 1.0');
})();

// ============================================================
// 11. CombatStatsTracker
// ============================================================
console.log('\n--- CombatStatsTracker ---');

(function testCombatStatsTrackerExists() {
    assert(typeof CombatStatsTracker === 'function', 'CombatStatsTracker class exists');
})();

(function testCombatStatsTrackerInitial() {
    if (!CombatStatsTracker) { assert(false, 'CombatStatsTracker not defined'); return; }
    const t = new CombatStatsTracker();
    assert(t.shotsFired === 0, 'initial shotsFired = 0');
    assert(t.shotsHit === 0, 'initial shotsHit = 0');
    assert(t.totalDamage === 0, 'initial totalDamage = 0');
    assert(t.totalEliminations === 0, 'initial totalEliminations = 0');
})();

(function testCombatStatsTrackerRecordShot() {
    if (!CombatStatsTracker) { assert(false, 'CombatStatsTracker not defined'); return; }
    const t = new CombatStatsTracker();
    t.recordShot();
    t.recordShot();
    assert(t.shotsFired === 2, 'recordShot increments shotsFired');
})();

(function testCombatStatsTrackerRecordHit() {
    if (!CombatStatsTracker) { assert(false, 'CombatStatsTracker not defined'); return; }
    const t = new CombatStatsTracker();
    t.recordHit();
    assert(t.shotsHit === 1, 'recordHit increments shotsHit');
})();

(function testCombatStatsTrackerRecordDamage() {
    if (!CombatStatsTracker) { assert(false, 'CombatStatsTracker not defined'); return; }
    const t = new CombatStatsTracker();
    t.recordDamage(25);
    t.recordDamage(15);
    assert(t.totalDamage === 40, 'recordDamage accumulates');
})();

(function testCombatStatsTrackerRecordElimination() {
    if (!CombatStatsTracker) { assert(false, 'CombatStatsTracker not defined'); return; }
    const t = new CombatStatsTracker();
    t.recordElimination();
    t.recordElimination();
    t.recordElimination();
    assert(t.totalEliminations === 3, 'recordElimination increments');
})();

(function testCombatStatsTrackerAccuracy() {
    if (!CombatStatsTracker) { assert(false, 'CombatStatsTracker not defined'); return; }
    const t = new CombatStatsTracker();
    t.shotsFired = 10;
    t.shotsHit = 7;
    assertClose(t.accuracy(), 70, 0.01, 'accuracy 7/10 = 70%');
})();

(function testCombatStatsTrackerAccuracyZero() {
    if (!CombatStatsTracker) { assert(false, 'CombatStatsTracker not defined'); return; }
    const t = new CombatStatsTracker();
    assert(t.accuracy() === 0, 'accuracy 0/0 = 0');
})();

(function testCombatStatsTrackerDPS() {
    if (!CombatStatsTracker) { assert(false, 'CombatStatsTracker not defined'); return; }
    const t = new CombatStatsTracker();
    t.totalDamage = 100;
    t._startTime = Date.now() - 10000; // 10 seconds ago
    const dps = t.dps();
    assertClose(dps, 10, 1, 'dps 100 damage over 10s ~= 10');
})();

(function testCombatStatsTrackerDPSZero() {
    if (!CombatStatsTracker) { assert(false, 'CombatStatsTracker not defined'); return; }
    const t = new CombatStatsTracker();
    assert(t.dps() === 0, 'dps with 0 damage = 0');
})();

(function testCombatStatsTrackerReset() {
    if (!CombatStatsTracker) { assert(false, 'CombatStatsTracker not defined'); return; }
    const t = new CombatStatsTracker();
    t.recordShot(); t.recordHit(); t.recordDamage(50); t.recordElimination();
    t.reset();
    assert(t.shotsFired === 0, 'reset clears shotsFired');
    assert(t.shotsHit === 0, 'reset clears shotsHit');
    assert(t.totalDamage === 0, 'reset clears totalDamage');
    assert(t.totalEliminations === 0, 'reset clears totalEliminations');
})();

// ============================================================
// 12. buildRosterHTML(units)
// ============================================================
console.log('\n--- buildRosterHTML ---');

(function testBuildRosterHTMLBasic() {
    if (!H.buildRosterHTML) { assert(false, 'buildRosterHTML not defined'); return; }
    const units = [
        { target_id: 'a', name: 'Alpha', alliance: 'friendly', type: 'turret', health: 80, max_health: 100 },
        { target_id: 'b', name: 'Bravo', alliance: 'friendly', type: 'drone', health: 50, max_health: 100 },
    ];
    const html = H.buildRosterHTML(units);
    assertContains(html, 'Alpha', 'buildRosterHTML contains unit name Alpha');
    assertContains(html, 'Bravo', 'buildRosterHTML contains unit name Bravo');
})();

(function testBuildRosterHTMLFiltersHostiles() {
    if (!H.buildRosterHTML) { assert(false, 'buildRosterHTML not defined'); return; }
    const units = [
        { target_id: 'a', name: 'Alpha', alliance: 'friendly', type: 'turret', health: 100, max_health: 100 },
        { target_id: 'b', name: 'Enemy', alliance: 'hostile', type: 'person', health: 100, max_health: 100 },
    ];
    const html = H.buildRosterHTML(units);
    assertContains(html, 'Alpha', 'buildRosterHTML includes friendly');
    assert(!html.includes('Enemy'), 'buildRosterHTML excludes hostile (' + html + ')');
})();

(function testBuildRosterHTMLEmpty() {
    if (!H.buildRosterHTML) { assert(false, 'buildRosterHTML not defined'); return; }
    const html = H.buildRosterHTML([]);
    assert(typeof html === 'string', 'buildRosterHTML empty array returns string');
})();

(function testBuildRosterHTMLHealthColor() {
    if (!H.buildRosterHTML) { assert(false, 'buildRosterHTML not defined'); return; }
    const units = [
        { target_id: 'a', name: 'Wounded', alliance: 'friendly', type: 'rover', health: 20, max_health: 100 },
    ];
    const html = H.buildRosterHTML(units);
    // Should contain the red health color since 20% < 30%
    assertContains(html, '#ff2a6d', 'buildRosterHTML low health uses red color');
})();

// ============================================================
// 13. buildWaveProgressHTML(wave, remaining, total, elapsed)
// ============================================================
console.log('\n--- buildWaveProgressHTML ---');

(function testBuildWaveProgressHTMLBasic() {
    if (!H.buildWaveProgressHTML) { assert(false, 'buildWaveProgressHTML not defined'); return; }
    const html = H.buildWaveProgressHTML(3, 5, 10, 45);
    assertContains(html, 'WAVE 3', 'buildWaveProgressHTML contains wave number');
    assertContains(html, '50%', 'buildWaveProgressHTML contains progress percentage');
})();

(function testBuildWaveProgressHTMLElapsed() {
    if (!H.buildWaveProgressHTML) { assert(false, 'buildWaveProgressHTML not defined'); return; }
    const html = H.buildWaveProgressHTML(1, 0, 10, 90);
    assertContains(html, '1:30', 'buildWaveProgressHTML contains formatted elapsed time');
})();

(function testBuildWaveProgressHTMLZeroTotal() {
    if (!H.buildWaveProgressHTML) { assert(false, 'buildWaveProgressHTML not defined'); return; }
    const html = H.buildWaveProgressHTML(1, 0, 0, 0);
    assert(typeof html === 'string', 'buildWaveProgressHTML handles zero total');
})();

// ============================================================
// 14. buildCombatMetricsHTML(data)
// ============================================================
console.log('\n--- buildCombatMetricsHTML ---');

(function testBuildCombatMetricsHTMLBasic() {
    if (!H.buildCombatMetricsHTML) { assert(false, 'buildCombatMetricsHTML not defined'); return; }
    const html = H.buildCombatMetricsHTML({
        accuracy: 65,
        dps: 12.5,
        threats: 3,
        morale: 0.85,
    });
    assertContains(html, '65', 'buildCombatMetricsHTML contains accuracy');
    assertContains(html, '12.5', 'buildCombatMetricsHTML contains dps');
})();

(function testBuildCombatMetricsHTMLMoraleTrend() {
    if (!H.buildCombatMetricsHTML) { assert(false, 'buildCombatMetricsHTML not defined'); return; }
    const html = H.buildCombatMetricsHTML({
        accuracy: 50,
        dps: 0,
        threats: 0,
        morale: 0.9,
        moraleTrend: 'rising',
    });
    assert(typeof html === 'string' && html.length > 0, 'buildCombatMetricsHTML with morale trend');
})();

(function testBuildCombatMetricsHTMLDefaults() {
    if (!H.buildCombatMetricsHTML) { assert(false, 'buildCombatMetricsHTML not defined'); return; }
    const html = H.buildCombatMetricsHTML({});
    assert(typeof html === 'string', 'buildCombatMetricsHTML handles empty data');
})();

// ============================================================
// 15. buildMVPHTML(mvp)
// ============================================================
console.log('\n--- buildMVPHTML ---');

(function testBuildMVPHTMLBasic() {
    if (!H.buildMVPHTML) { assert(false, 'buildMVPHTML not defined'); return; }
    const html = H.buildMVPHTML({
        name: 'Alpha Turret',
        kills: 5,
        type: 'turret',
    });
    assertContains(html, 'Alpha Turret', 'buildMVPHTML contains MVP name');
    assertContains(html, '5', 'buildMVPHTML contains kill count');
})();

(function testBuildMVPHTMLNull() {
    if (!H.buildMVPHTML) { assert(false, 'buildMVPHTML not defined'); return; }
    const html = H.buildMVPHTML(null);
    assert(typeof html === 'string', 'buildMVPHTML null returns string');
})();

(function testBuildMVPHTMLNoKills() {
    if (!H.buildMVPHTML) { assert(false, 'buildMVPHTML not defined'); return; }
    const html = H.buildMVPHTML({ name: 'Rookie', kills: 0, type: 'rover' });
    assertContains(html, 'Rookie', 'buildMVPHTML shows unit with 0 kills');
})();

// ============================================================
// 16. Backward compatibility (missing fields)
// ============================================================
console.log('\n--- Backward Compatibility ---');

(function testHealthColorUndefined() {
    if (!H.healthColor) { assert(false, 'healthColor not defined'); return; }
    // Should not throw for undefined/NaN
    const color = H.healthColor(undefined);
    assert(typeof color === 'string', 'healthColor handles undefined input');
})();

(function testHealthBarNegative() {
    if (!H.healthBar) { assert(false, 'healthBar not defined'); return; }
    const bar = H.healthBar(-0.5, 10);
    assert(typeof bar === 'string', 'healthBar handles negative ratio');
})();

(function testFindMVPMissingKills() {
    if (!H.findMVP) { assert(false, 'findMVP not defined'); return; }
    const units = [
        { target_id: 'a', name: 'Silent', alliance: 'friendly' }, // no kills field
    ];
    const mvp = H.findMVP(units);
    assert(mvp !== undefined, 'findMVP handles missing kills field');
})();

(function testCountThreatsUndefinedAlliance() {
    if (!H.countThreats) { assert(false, 'countThreats not defined'); return; }
    const units = [
        { status: 'active' }, // no alliance
    ];
    assert(H.countThreats(units) === 0, 'countThreats ignores units with undefined alliance');
})();

(function testBuildRosterHTMLMissingHealth() {
    if (!H.buildRosterHTML) { assert(false, 'buildRosterHTML not defined'); return; }
    const units = [
        { target_id: 'a', name: 'Bare', alliance: 'friendly', type: 'turret' },
    ];
    const html = H.buildRosterHTML(units);
    assert(typeof html === 'string', 'buildRosterHTML handles missing health');
})();

(function testAvgMoraleUndefinedItems() {
    if (!H.avgMorale) { assert(false, 'avgMorale not defined'); return; }
    const units = [
        { alliance: 'friendly', morale: undefined },
    ];
    // morale undefined should default to 1.0
    assertClose(H.avgMorale(units), 1.0, 0.01, 'avgMorale undefined morale defaults to 1.0');
})();

(function testFormatTimeNegative() {
    if (!H.formatTime) { assert(false, 'formatTime not defined'); return; }
    const result = H.formatTime(-5);
    assert(typeof result === 'string', 'formatTime handles negative input');
})();

(function testWaveProgressPctNegativeRemaining() {
    if (!H.waveProgressPct) { assert(false, 'waveProgressPct not defined'); return; }
    const pct = H.waveProgressPct(-1, 10);
    assert(typeof pct === 'number' && pct >= 0 && pct <= 100, 'waveProgressPct clamps negative remaining');
})();

// ============================================================
// 17. typeIcon distinct symbols
// ============================================================
console.log('\n--- typeIcon distinct symbols ---');

(function testTypeIconsDistinct() {
    if (!H.typeIcon) { assert(false, 'typeIcon not defined'); return; }
    const types = ['turret', 'drone', 'rover', 'person', 'tank', 'apc', 'scout_drone'];
    const icons = types.map(t => H.typeIcon(t));
    const unique = new Set(icons);
    // At minimum turret, drone, rover, person should be distinct
    assert(unique.size >= 4, 'typeIcon returns at least 4 distinct symbols for core types');
})();

// ============================================================
// 18. healthBar clamping
// ============================================================
console.log('\n--- healthBar clamping ---');

(function testHealthBarOverflow() {
    if (!H.healthBar) { assert(false, 'healthBar not defined'); return; }
    const bar = H.healthBar(1.5, 10);
    assert(bar.length === 10, 'healthBar clamps ratio > 1.0');
    const filledCount = (bar.match(/\u2588/g) || []).length;
    assert(filledCount === 10, 'healthBar 150% clamped to all filled');
})();

// ============================================================
// Summary
// ============================================================

console.log('\n' + '='.repeat(40));
console.log(`Results: ${passed} passed, ${failed} failed`);
console.log('='.repeat(40));
process.exit(failed > 0 ? 1 : 0);
