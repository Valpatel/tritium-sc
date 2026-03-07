// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
/**
 * TRITIUM-SC Battle Stats Panel Tests
 * Tests helper functions, panel structure, leaderboard sorting,
 * MVP badge, sparkline generation, hostile filtering, and polling lifecycle.
 * Run: node tests/js/test_stats_panel.js
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
    assert(typeof str === 'string' && str.includes(sub), msg + ` (expected "${sub}" in "${String(str).substring(0, 120)}")`);
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
    createElementNS: (ns, tag) => createMockElement(tag),
};

// ============================================================
// Load stats.js
// ============================================================

const statsCode = fs.readFileSync(__dirname + '/../../src/frontend/js/command/panels/stats.js', 'utf8');

let processedCode = statsCode
    .replace(/^import\s+.*?from\s+['"].*?['"];?\s*$/gm, '')
    .replace(/^export\s+const\s+/gm, 'var ')
    .replace(/^export\s+/gm, '');

const ctx = vm.createContext({
    Math, Date, console, Map, Array, Object, Number, Infinity, Boolean, String,
    parseInt, parseFloat, isNaN, isFinite, undefined, null: null,
    JSON, Error, TypeError, RangeError, Set,
    setTimeout: (fn) => fn(),
    setInterval: () => 999,
    clearInterval: () => {},
    clearTimeout: () => {},
    document: mockDocument,
    window: {},
    fetch: () => Promise.resolve({ ok: true, json: () => Promise.resolve({}) }),
    TritiumStore: {
        game: { phase: 'idle', wave: 0, totalWaves: 10, score: 0, eliminations: 0 },
        units: new Map(),
        on: () => () => {},
        set: () => {},
        get: () => undefined,
    },
    EventBus: {
        emit: () => {},
        on: () => () => {},
        off: () => {},
    },
});

try {
    vm.runInContext(processedCode, ctx);
} catch (e) {
    console.error('Failed to load stats.js:', e.message);
}

const H = ctx.window.BattleStatsHelpers || {};
const PanelDef = ctx.BattleStatsPanelDef;

// ============================================================
// 1. Panel definition structure
// ============================================================
console.log('\n--- Panel Definition ---');

assert(PanelDef !== undefined, 'BattleStatsPanelDef exists');
assert(PanelDef && PanelDef.id === 'battle-stats', 'panel id is battle-stats');
assert(PanelDef && PanelDef.title === 'BATTLE STATS', 'panel title is BATTLE STATS');
assert(PanelDef && typeof PanelDef.create === 'function', 'create is a function');
assert(PanelDef && typeof PanelDef.mount === 'function', 'mount is a function');
assert(PanelDef && typeof PanelDef.unmount === 'function', 'unmount is a function');
assert(PanelDef && PanelDef.defaultPosition && typeof PanelDef.defaultPosition.x === 'number', 'defaultPosition.x is number');
assert(PanelDef && PanelDef.defaultPosition && typeof PanelDef.defaultPosition.y === 'number', 'defaultPosition.y is number');
assert(PanelDef && PanelDef.defaultSize && PanelDef.defaultSize.w === 380, 'defaultSize.w is 380');
assert(PanelDef && PanelDef.defaultSize && PanelDef.defaultSize.h === 400, 'defaultSize.h is 400');

// ============================================================
// 2. DOM structure from create()
// ============================================================
console.log('\n--- DOM Structure ---');

if (PanelDef) {
    const el = PanelDef.create({ def: PanelDef });
    assert(el && el.className === 'bstats-panel-inner', 'create returns element with bstats-panel-inner class');
    const html = el.innerHTML || '';
    assertContains(html, 'bstats-header', 'contains bstats-header');
    assertContains(html, 'bstats-leaderboard', 'contains bstats-leaderboard section');
    assertContains(html, 'bstats-sparkline', 'contains bstats-sparkline section');
}

// ============================================================
// 3. Helper: formatAccuracy
// ============================================================
console.log('\n--- formatAccuracy ---');

assert(typeof H.formatAccuracy === 'function', 'formatAccuracy is a function');
assert(H.formatAccuracy && H.formatAccuracy(0.85) === '85%', 'formatAccuracy(0.85) = "85%"');
assert(H.formatAccuracy && H.formatAccuracy(1.0) === '100%', 'formatAccuracy(1.0) = "100%"');
assert(H.formatAccuracy && H.formatAccuracy(0) === '0%', 'formatAccuracy(0) = "0%"');
assert(H.formatAccuracy && H.formatAccuracy(0.333) === '33%', 'formatAccuracy(0.333) = "33%"');
assert(H.formatAccuracy && H.formatAccuracy(null) === '0%', 'formatAccuracy(null) = "0%"');
assert(H.formatAccuracy && H.formatAccuracy(undefined) === '0%', 'formatAccuracy(undefined) = "0%"');

// ============================================================
// 4. Helper: formatDamage
// ============================================================
console.log('\n--- formatDamage ---');

assert(typeof H.formatDamage === 'function', 'formatDamage is a function');
assert(H.formatDamage && H.formatDamage(1234) === '1,234', 'formatDamage(1234) = "1,234"');
assert(H.formatDamage && H.formatDamage(0) === '0', 'formatDamage(0) = "0"');
assert(H.formatDamage && H.formatDamage(999) === '999', 'formatDamage(999) = "999"');
assert(H.formatDamage && H.formatDamage(1000000) === '1,000,000', 'formatDamage(1000000) = "1,000,000"');
assert(H.formatDamage && H.formatDamage(12345.67) === '12,346', 'formatDamage(12345.67) rounds to integer');

// ============================================================
// 5. Helper: accuracyColor
// ============================================================
console.log('\n--- accuracyColor ---');

assert(typeof H.accuracyColor === 'function', 'accuracyColor is a function');
if (H.accuracyColor) {
    const green = H.accuracyColor(0.75);
    const amber = H.accuracyColor(0.35);
    const red = H.accuracyColor(0.10);
    assert(green === '#05ffa1', 'accuracyColor(0.75) = green (#05ffa1), got ' + green);
    assert(amber === '#fcee0a', 'accuracyColor(0.35) = amber (#fcee0a), got ' + amber);
    assert(red === '#ff2a6d', 'accuracyColor(0.10) = red (#ff2a6d), got ' + red);
    // Boundary tests
    assert(H.accuracyColor(0.50) === '#05ffa1', 'accuracyColor(0.50) = green (>= 50%)');
    assert(H.accuracyColor(0.25) === '#fcee0a', 'accuracyColor(0.25) = amber (>= 25%)');
    assert(H.accuracyColor(0.249) === '#ff2a6d', 'accuracyColor(0.249) = red (<25%)');
}

// ============================================================
// 6. Helper: buildStatCardHTML
// ============================================================
console.log('\n--- buildStatCardHTML ---');

assert(typeof H.buildStatCardHTML === 'function', 'buildStatCardHTML is a function');
if (H.buildStatCardHTML) {
    const card = H.buildStatCardHTML('ACCURACY', '85%', '#05ffa1');
    assertContains(card, 'bstats-card', 'card has bstats-card class');
    assertContains(card, 'bstats-card-value', 'card has bstats-card-value class');
    assertContains(card, 'bstats-card-label', 'card has bstats-card-label class');
    assertContains(card, 'ACCURACY', 'card contains label');
    assertContains(card, '85%', 'card contains value');
    assertContains(card, '#05ffa1', 'card contains color');
}

// ============================================================
// 7. Helper: buildLeaderboardHTML — sorting by kills
// ============================================================
console.log('\n--- buildLeaderboardHTML ---');

assert(typeof H.buildLeaderboardHTML === 'function', 'buildLeaderboardHTML is a function');
if (H.buildLeaderboardHTML) {
    const units = [
        { target_id: 'r1', name: 'Rover Alpha', alliance: 'friendly', kills: 3, accuracy: 0.5, damage_dealt: 150 },
        { target_id: 't1', name: 'Turret Beta', alliance: 'friendly', kills: 7, accuracy: 0.8, damage_dealt: 400 },
        { target_id: 'd1', name: 'Drone Gamma', alliance: 'friendly', kills: 5, accuracy: 0.6, damage_dealt: 250 },
    ];
    const html = H.buildLeaderboardHTML(units);
    assertContains(html, 'bstats-table', 'leaderboard has bstats-table class');
    assertContains(html, 'Turret Beta', 'leaderboard contains highest-kills unit');
    assertContains(html, 'Drone Gamma', 'leaderboard contains second-kills unit');
    assertContains(html, 'Rover Alpha', 'leaderboard contains lowest-kills unit');

    // Verify sorted order: Turret Beta (7) before Drone Gamma (5) before Rover Alpha (3)
    const betaIdx = html.indexOf('Turret Beta');
    const gammaIdx = html.indexOf('Drone Gamma');
    const alphaIdx = html.indexOf('Rover Alpha');
    assert(betaIdx < gammaIdx, 'Turret Beta (7 kills) appears before Drone Gamma (5 kills)');
    assert(gammaIdx < alphaIdx, 'Drone Gamma (5 kills) appears before Rover Alpha (3 kills)');
}

// ============================================================
// 8. MVP badge on rank 1
// ============================================================
console.log('\n--- MVP Badge ---');

if (H.buildLeaderboardHTML) {
    const units = [
        { target_id: 't1', name: 'Top Turret', alliance: 'friendly', kills: 10, accuracy: 0.9, damage_dealt: 500 },
        { target_id: 'r1', name: 'Second Rover', alliance: 'friendly', kills: 3, accuracy: 0.5, damage_dealt: 100 },
    ];
    const html = H.buildLeaderboardHTML(units);
    assertContains(html, 'bstats-mvp-badge', 'leaderboard contains MVP badge');
    // The MVP badge should be near the top (rank 1) entry
    const badgeIdx = html.indexOf('bstats-mvp-badge');
    const topIdx = html.indexOf('Top Turret');
    const secondIdx = html.indexOf('Second Rover');
    assert(badgeIdx < secondIdx, 'MVP badge appears before the second-ranked unit');
}

// ============================================================
// 9. Hostile filtering (only friendly units shown)
// ============================================================
console.log('\n--- Hostile Filtering ---');

if (H.buildLeaderboardHTML) {
    const units = [
        { target_id: 'f1', name: 'Friendly One', alliance: 'friendly', kills: 5, accuracy: 0.7, damage_dealt: 200 },
        { target_id: 'h1', name: 'Hostile Bad', alliance: 'hostile', kills: 15, accuracy: 0.9, damage_dealt: 900 },
        { target_id: 'f2', name: 'Friendly Two', alliance: 'friendly', kills: 2, accuracy: 0.4, damage_dealt: 80 },
    ];
    const html = H.buildLeaderboardHTML(units);
    assertContains(html, 'Friendly One', 'leaderboard contains friendly unit');
    assertContains(html, 'Friendly Two', 'leaderboard contains second friendly unit');
    assert(!html.includes('Hostile Bad'), 'leaderboard does NOT contain hostile unit');
}

// ============================================================
// 10. Empty leaderboard
// ============================================================
console.log('\n--- Empty Leaderboard ---');

if (H.buildLeaderboardHTML) {
    const html = H.buildLeaderboardHTML([]);
    assert(typeof html === 'string', 'buildLeaderboardHTML([]) returns a string');
    // Should produce a table or empty state message, not throw
    assert(html.length > 0, 'empty leaderboard produces some output');
}

// ============================================================
// 11. Sparkline points generation
// ============================================================
console.log('\n--- buildSparklinePoints ---');

assert(typeof H.buildSparklinePoints === 'function', 'buildSparklinePoints is a function');
if (H.buildSparklinePoints) {
    // Simulate elimination events with timestamps and alliance
    const events = [
        { time: 0, alliance: 'hostile' },    // hostile killed at t=0
        { time: 5, alliance: 'hostile' },    // hostile killed at t=5
        { time: 8, alliance: 'friendly' },   // friendly killed at t=8
        { time: 10, alliance: 'hostile' },   // hostile killed at t=10
    ];
    const points = H.buildSparklinePoints(events, 200, 40);
    assert(typeof points === 'string', 'buildSparklinePoints returns a string');
    assert(points.length > 0, 'buildSparklinePoints returns non-empty string');

    // Points should be space-separated x,y pairs
    const pairs = points.trim().split(/\s+/);
    assert(pairs.length >= 2, 'sparkline has at least 2 points');

    // Verify all pairs are valid x,y format
    const allValid = pairs.every(p => /^\d+(\.\d+)?,\d+(\.\d+)?$/.test(p));
    assert(allValid, 'all sparkline points are valid x,y format');
}

// ============================================================
// 12. Sparkline with empty events
// ============================================================
console.log('\n--- Sparkline empty events ---');

if (H.buildSparklinePoints) {
    const points = H.buildSparklinePoints([], 200, 40);
    assert(typeof points === 'string', 'buildSparklinePoints([]) returns a string');
    // Should return at least origin point "0,40"
    assert(points.length > 0, 'empty events still produces points');
}

// ============================================================
// 13. Sparkline single event
// ============================================================
console.log('\n--- Sparkline single event ---');

if (H.buildSparklinePoints) {
    const events = [{ time: 5, alliance: 'hostile' }];
    const points = H.buildSparklinePoints(events, 100, 30);
    assert(typeof points === 'string' && points.length > 0, 'single event produces valid points');
}

// ============================================================
// 14. Helpers exposed on window.BattleStatsHelpers
// ============================================================
console.log('\n--- Window exposure ---');

const expectedHelpers = ['formatAccuracy', 'formatDamage', 'accuracyColor', 'buildStatCardHTML', 'buildLeaderboardHTML', 'buildSparklinePoints'];
for (const name of expectedHelpers) {
    assert(typeof H[name] === 'function', `window.BattleStatsHelpers.${name} exists`);
}

// ============================================================
// 15. Polling lifecycle — mount starts/stops polling on phase
// ============================================================
console.log('\n--- Polling lifecycle ---');

(function testPollingStartsOnActivePhase() {
    // Re-create a sandbox with mutable TritiumStore and EventBus
    let setIntervalCalls = [];
    let clearIntervalCalls = [];
    let fetchCalls = [];
    let storeListeners = {};
    let ebListeners = {};

    const pollingCtx = vm.createContext({
        Math, Date, console, Map, Array, Object, Number, Infinity, Boolean, String,
        parseInt, parseFloat, isNaN, isFinite, undefined, JSON, Error, Set,
        setTimeout: (fn) => { fn(); return 888; },
        setInterval: (fn, ms) => { setIntervalCalls.push({ fn, ms }); return 777; },
        clearInterval: (id) => { clearIntervalCalls.push(id); },
        clearTimeout: () => {},
        document: mockDocument,
        window: {},
        fetch: (...args) => {
            fetchCalls.push(args);
            return Promise.resolve({
                ok: true,
                json: () => Promise.resolve({ summary: {}, units: [], waves: [] }),
            });
        },
        TritiumStore: {
            game: { phase: 'idle', wave: 0, totalWaves: 10, score: 0, eliminations: 0 },
            units: new Map(),
            on: (key, fn) => { storeListeners[key] = fn; return () => {}; },
            set: () => {},
            get: () => undefined,
        },
        EventBus: {
            emit: () => {},
            on: (key, fn) => { ebListeners[key] = fn; return () => {}; },
            off: () => {},
        },
    });

    try { vm.runInContext(processedCode, pollingCtx); } catch (e) { /* ignore */ }

    const PDef = pollingCtx.BattleStatsPanelDef;
    if (PDef) {
        const bodyEl = createMockElement('div');
        bodyEl.querySelector = (sel) => {
            if (sel.includes('header')) return createMockElement('div');
            if (sel.includes('leaderboard-body')) return createMockElement('div');
            if (sel.includes('sparkline-friendly')) return createMockElement('polyline');
            if (sel.includes('sparkline-hostile')) return createMockElement('polyline');
            return null;
        };
        const panel = { def: PDef, _unsubs: [] };

        // Phase is idle, so mount should NOT start polling
        PDef.mount(bodyEl, panel);
        assert(setIntervalCalls.length === 0, 'mount with idle phase does NOT start polling');

        // Now simulate phase change to active
        if (storeListeners['game.phase']) {
            storeListeners['game.phase']('active');
        }
        assert(setIntervalCalls.length >= 1, 'phase=active starts setInterval polling');
        assert(setIntervalCalls[0].ms === 3000, 'polling interval is 3000ms');

        // Simulate phase back to idle
        if (storeListeners['game.phase']) {
            storeListeners['game.phase']('idle');
        }
        assert(clearIntervalCalls.length >= 1, 'phase=idle clears polling interval');

        // Simulate victory phase — should do one last forced fetch
        fetchCalls = [];
        if (storeListeners['game.phase']) {
            storeListeners['game.phase']('victory');
        }
        assert(fetchCalls.length >= 1, 'phase=victory triggers one last fetch (forced)');
    }
})();

// ============================================================
// 16. Polling starts immediately when game is already active on mount
// ============================================================
console.log('\n--- Poll on mount when active ---');

(function testPollingStartsImmediatelyWhenActive() {
    let setIntervalCalls = [];
    let fetchCalls = [];
    let storeListeners = {};

    const activeCtx = vm.createContext({
        Math, Date, console, Map, Array, Object, Number, Infinity, Boolean, String,
        parseInt, parseFloat, isNaN, isFinite, undefined, JSON, Error, Set,
        setTimeout: (fn) => { fn(); return 888; },
        setInterval: (fn, ms) => { setIntervalCalls.push({ fn, ms }); return 777; },
        clearInterval: () => {},
        clearTimeout: () => {},
        document: mockDocument,
        window: {},
        fetch: (...args) => {
            fetchCalls.push(args);
            return Promise.resolve({
                ok: true,
                json: () => Promise.resolve({ summary: {}, units: [], waves: [] }),
            });
        },
        TritiumStore: {
            game: { phase: 'active', wave: 3, totalWaves: 10, score: 100, eliminations: 5 },
            units: new Map(),
            on: (key, fn) => { storeListeners[key] = fn; return () => {}; },
            set: () => {},
            get: () => undefined,
        },
        EventBus: {
            emit: () => {},
            on: () => () => {},
            off: () => {},
        },
    });

    try { vm.runInContext(processedCode, activeCtx); } catch (e) { /* ignore */ }

    const PDef2 = activeCtx.BattleStatsPanelDef;
    if (PDef2) {
        const bodyEl = createMockElement('div');
        bodyEl.querySelector = (sel) => {
            if (sel.includes('header')) return createMockElement('div');
            if (sel.includes('leaderboard-body')) return createMockElement('div');
            if (sel.includes('sparkline-friendly')) return createMockElement('polyline');
            if (sel.includes('sparkline-hostile')) return createMockElement('polyline');
            return null;
        };
        const panel = { def: PDef2, _unsubs: [] };
        PDef2.mount(bodyEl, panel);

        assert(fetchCalls.length >= 1, 'mount with active phase triggers immediate fetch');
        assert(setIntervalCalls.length >= 1, 'mount with active phase starts setInterval');
    }
})();

// ============================================================
// 17. Elimination event handling — sparkline data accumulation
// ============================================================
console.log('\n--- Elimination events ---');

(function testEliminationEventAccumulation() {
    let ebListeners = {};

    const elimCtx = vm.createContext({
        Math, Date, console, Map, Array, Object, Number, Infinity, Boolean, String,
        parseInt, parseFloat, isNaN, isFinite, undefined, JSON, Error, Set,
        setTimeout: (fn) => { fn(); return 888; },
        setInterval: () => 999,
        clearInterval: () => {},
        clearTimeout: () => {},
        document: mockDocument,
        window: {},
        fetch: () => Promise.resolve({
            ok: true,
            json: () => Promise.resolve({ summary: {}, units: [], waves: [] }),
        }),
        TritiumStore: {
            game: { phase: 'active', wave: 1, totalWaves: 10, score: 0, eliminations: 0 },
            units: new Map(),
            on: () => () => {},
            set: () => {},
            get: () => undefined,
        },
        EventBus: {
            emit: () => {},
            on: (key, fn) => { if (!ebListeners[key]) ebListeners[key] = []; ebListeners[key].push(fn); return () => {}; },
            off: () => {},
        },
    });

    try { vm.runInContext(processedCode, elimCtx); } catch (e) { /* ignore */ }

    const PDef3 = elimCtx.BattleStatsPanelDef;
    if (PDef3) {
        const bodyEl = createMockElement('div');
        bodyEl.querySelector = (sel) => {
            if (sel.includes('header')) return createMockElement('div');
            if (sel.includes('leaderboard-body')) return createMockElement('div');
            if (sel.includes('sparkline-friendly')) return createMockElement('polyline');
            if (sel.includes('sparkline-hostile')) return createMockElement('polyline');
            return null;
        };
        const panel = { def: PDef3, _unsubs: [] };
        PDef3.mount(bodyEl, panel);

        // Trigger game:state to set start time
        if (ebListeners['game:state']) {
            ebListeners['game:state'].forEach(fn => fn({ state: 'active' }));
        }

        // Trigger elimination event — hostile killed (friendly team scores)
        if (ebListeners['combat:elimination']) {
            ebListeners['combat:elimination'].forEach(fn => fn({ target_alliance: 'hostile' }));
            ebListeners['combat:elimination'].forEach(fn => fn({ target_alliance: 'hostile' }));
            ebListeners['combat:elimination'].forEach(fn => fn({ target_alliance: 'friendly' }));
        }

        assert(ebListeners['combat:elimination'] !== undefined, 'mount subscribes to combat:elimination');
        assert(ebListeners['game:state'] !== undefined, 'mount subscribes to game:state');
    }
})();

// ============================================================
// 18. Game state reset clears elimination events
// ============================================================
console.log('\n--- Game state reset ---');

(function testGameStateResetClearsElimEvents() {
    // Verify the source code structure for game state handler
    assertContains(processedCode, '_friendlyElimEvents = []', 'game:state handler clears _friendlyElimEvents');
    assertContains(processedCode, '_hostileElimEvents = []', 'game:state handler clears _hostileElimEvents');
    assertContains(processedCode, '_gameStartTime = Date.now()', 'game:state handler sets _gameStartTime');
})();

// ============================================================
// 19. renderStats updates header and leaderboard
// ============================================================
console.log('\n--- renderStats integration ---');

(function testRenderStatsUpdatesHeader() {
    // Verify renderStats function references in source
    assertContains(processedCode, 'function renderStats(data)', 'renderStats function exists');
    assertContains(processedCode, 'headerEl.innerHTML', 'renderStats updates header');
    assertContains(processedCode, 'leaderboardBody.innerHTML', 'renderStats updates leaderboard');
    assertContains(processedCode, 'setAttribute', 'renderStats updates sparkline points');
})();

// ============================================================
// 20. Unsub cleanup on unmount
// ============================================================
console.log('\n--- Unmount cleanup ---');

(function testUnmountCleanup() {
    // Verify mount pushes cleanup callbacks to panel._unsubs
    assertContains(processedCode, 'panel._unsubs.push', 'mount registers cleanup in _unsubs');

    // Verify clearInterval is pushed as cleanup
    assertContains(processedCode, 'clearInterval(_pollInterval)', 'unmount cleans up polling interval');

    // Verify EventBus.off is part of cleanup
    assertContains(processedCode, "EventBus.off('combat:elimination'", 'unmount unsubscribes from combat:elimination');
    assertContains(processedCode, "EventBus.off('game:state'", 'unmount unsubscribes from game:state');
})();

// ============================================================
// 21. _isActivePhase helper
// ============================================================
console.log('\n--- _isActivePhase ---');

(function testIsActivePhaseLogic() {
    assertContains(processedCode, "phase === 'active'", '_isActivePhase checks active');
    assertContains(processedCode, "phase === 'wave_complete'", '_isActivePhase checks wave_complete');
})();

// ============================================================
// 22. pollStats silently skips on non-active phase
// ============================================================
console.log('\n--- pollStats guards ---');

(function testPollStatsGuardNonActive() {
    assertContains(processedCode, '!_isActivePhase()) return', 'pollStats returns early when not active');
    assertContains(processedCode, 'if (!resp.ok) return', 'pollStats returns early on bad response');
})();

// ============================================================
// 23. Leaderboard friendly-only filter and sort
// ============================================================
console.log('\n--- Leaderboard friendly filter & sort ---');

if (H.buildLeaderboardHTML) {
    const units = [
        { name: 'Alpha', alliance: 'friendly', kills: 3, accuracy: 0.8, damage_dealt: 500 },
        { name: 'Bravo', alliance: 'friendly', kills: 7, accuracy: 0.6, damage_dealt: 900 },
        { name: 'Enemy1', alliance: 'hostile', kills: 2, accuracy: 0.5, damage_dealt: 300 },
    ];
    const html = H.buildLeaderboardHTML(units);
    assertContains(html, 'Bravo', 'leaderboard includes top-killer Bravo');
    assertContains(html, 'Alpha', 'leaderboard includes Alpha');
    assert(!html.includes('Enemy1'), 'leaderboard excludes hostile units');
    // Bravo should be rank 1 (most kills)
    const bravoPos = html.indexOf('Bravo');
    const alphaPos = html.indexOf('Alpha');
    assert(bravoPos < alphaPos, 'Bravo (7 kills) ranked before Alpha (3 kills)');
}

// ============================================================
// 24. Leaderboard MVP badge on rank 1
// ============================================================
console.log('\n--- MVP badge ---');

if (H.buildLeaderboardHTML) {
    const units = [
        { name: 'MVP', alliance: 'friendly', kills: 10, accuracy: 0.9, damage_dealt: 1200 },
        { name: 'Sidekick', alliance: 'friendly', kills: 2, accuracy: 0.5, damage_dealt: 200 },
    ];
    const html = H.buildLeaderboardHTML(units);
    assertContains(html, 'bstats-mvp-badge', 'rank 1 has MVP badge');
    // MVP badge should appear before Sidekick
    const badgePos = html.indexOf('bstats-mvp-badge');
    const sidekickPos = html.indexOf('Sidekick');
    assert(badgePos < sidekickPos, 'MVP badge is on rank 1 row (before rank 2)');
}

// ============================================================
// 25. buildStatCardHTML escapes dangerous input
// ============================================================
console.log('\n--- Stat card XSS prevention ---');

if (H.buildStatCardHTML) {
    const html = H.buildStatCardHTML('<script>evil</script>', '42', '#ff0000');
    assert(!html.includes('<script>'), 'buildStatCardHTML escapes script tag in label');
}

// ============================================================
// 26. Sparkline multi-event ordering
// ============================================================
console.log('\n--- Sparkline multi-event ---');

if (H.buildSparklinePoints) {
    const events = [
        { time: 10, alliance: 'hostile' },
        { time: 5, alliance: 'hostile' },
        { time: 20, alliance: 'hostile' },
    ];
    const points = H.buildSparklinePoints(events, 200, 40);
    const pairs = points.split(' ');
    // Should have origin + 3 event points = 4 pairs
    assert(pairs.length === 4, 'sparkline has origin + 3 event points (got ' + pairs.length + ')');
    // Y should decrease as cumulative increases (SVG y-axis inverted)
    const yValues = pairs.slice(1).map(p => parseInt(p.split(',')[1]));
    for (let i = 1; i < yValues.length; i++) {
        assert(yValues[i] <= yValues[i - 1], 'sparkline Y decreases as kills accumulate');
    }
}

// ============================================================
// 27. Accuracy computed from shots when accuracy field missing
// ============================================================
console.log('\n--- Accuracy fallback ---');

if (H.buildLeaderboardHTML) {
    const units = [
        { name: 'NoAccField', alliance: 'friendly', kills: 1, shots_fired: 10, shots_hit: 7, damage_dealt: 100 },
    ];
    const html = H.buildLeaderboardHTML(units);
    assertContains(html, '70%', 'accuracy computed from shots_hit/shots_fired when accuracy field missing');
}

// ============================================================
// 28. Leaderboard with no friendly units
// ============================================================
console.log('\n--- No friendlies in leaderboard ---');

if (H.buildLeaderboardHTML) {
    const units = [
        { name: 'HostileOnly', alliance: 'hostile', kills: 5 },
    ];
    const html = H.buildLeaderboardHTML(units);
    assertContains(html, 'No friendly units', 'leaderboard shows "No friendly units" when all hostile');
}

// ============================================================
// 29. Phase defeat triggers last fetch
// ============================================================
console.log('\n--- Defeat last fetch ---');

(function testDefeatTriggersLastFetch() {
    assertContains(processedCode, "'defeat'", 'source checks for defeat phase');
    assertContains(processedCode, "pollStats()", 'victory/defeat calls pollStats one last time');
})();

// ============================================================
// Summary
// ============================================================
console.log(`\n${'='.repeat(40)}`);
console.log(`Stats Panel Tests: ${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
