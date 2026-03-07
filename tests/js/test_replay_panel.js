// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
/**
 * TRITIUM-SC Replay Panel tests
 * Tests ReplayPanelDef structure, DOM creation, transport controls,
 * speed selector, timeline scrubber, status bar, helper functions,
 * mount subscription wiring, and unmount.
 * Run: node tests/js/test_replay_panel.js
 */

const fs = require('fs');
const vm = require('vm');

// Simple test runner
let passed = 0, failed = 0;
function assert(cond, msg) {
    if (!cond) { console.error('FAIL:', msg); failed++; }
    else { console.log('PASS:', msg); passed++; }
}

// ============================================================
// DOM + browser mocks
// ============================================================

function createMockElement(tag) {
    const children = [];
    const classList = new Set();
    const eventListeners = {};
    const dataset = {};
    const style = {};
    let _innerHTML = '';
    let _textContent = '';

    const el = {
        tagName: (tag || 'DIV').toUpperCase(),
        className: '',
        get innerHTML() { return _innerHTML; },
        set innerHTML(val) {
            _innerHTML = val;
            el._parsedBinds = {};
            const bindMatches = val.matchAll(/data-bind="([^"]+)"/g);
            for (const m of bindMatches) el._parsedBinds[m[1]] = true;
            el._parsedActions = {};
            const actionMatches = val.matchAll(/data-action="([^"]+)"/g);
            for (const m of actionMatches) el._parsedActions[m[1]] = true;
            el._parsedSections = {};
            const sectionMatches = val.matchAll(/data-section="([^"]+)"/g);
            for (const m of sectionMatches) el._parsedSections[m[1]] = true;
            el._parsedElements = {};
            const elementMatches = val.matchAll(/data-element="([^"]+)"/g);
            for (const m of elementMatches) el._parsedElements[m[1]] = true;
        },
        get textContent() { return _textContent; },
        set textContent(val) {
            _textContent = String(val);
            _innerHTML = String(val)
                .replace(/&/g, '&amp;')
                .replace(/</g, '&lt;')
                .replace(/>/g, '&gt;');
        },
        style,
        dataset,
        children,
        childNodes: children,
        parentNode: null,
        hidden: false,
        value: '',
        disabled: false,
        get classList() {
            return {
                add(cls) { classList.add(cls); },
                remove(cls) { classList.delete(cls); },
                contains(cls) { return classList.has(cls); },
                toggle(cls, force) {
                    if (force === undefined) {
                        if (classList.has(cls)) classList.delete(cls);
                        else classList.add(cls);
                    } else if (force) classList.add(cls);
                    else classList.delete(cls);
                },
            };
        },
        appendChild(child) {
            children.push(child);
            if (child && typeof child === 'object') child.parentNode = el;
            return child;
        },
        remove() {},
        focus() {},
        getAttribute(name) {
            if (name === 'data-speed') return el._dataSpeed || null;
            if (name === 'data-wave') return el._dataWave || null;
            if (name === 'data-action') return el._dataAction || null;
            return null;
        },
        getBoundingClientRect() {
            return { left: 0, top: 0, width: 400, height: 12 };
        },
        addEventListener(evt, fn) {
            if (!eventListeners[evt]) eventListeners[evt] = [];
            eventListeners[evt].push(fn);
        },
        removeEventListener(evt, fn) {
            if (eventListeners[evt]) {
                eventListeners[evt] = eventListeners[evt].filter(f => f !== fn);
            }
        },
        querySelector(sel) {
            const bindMatch = sel.match(/\[data-bind="([^"]+)"\]/);
            if (bindMatch) {
                const mock = createMockElement('span');
                mock._bindName = bindMatch[1];
                return mock;
            }
            const actionMatch = sel.match(/\[data-action="([^"]+)"\]/);
            if (actionMatch) {
                const mock = createMockElement('button');
                mock._actionName = actionMatch[1];
                mock._dataAction = actionMatch[1];
                return mock;
            }
            const elementMatch = sel.match(/\[data-element="([^"]+)"\]/);
            if (elementMatch) {
                const mock = createMockElement('div');
                mock._elementName = elementMatch[1];
                return mock;
            }
            const sectionMatch = sel.match(/\[data-section="([^"]+)"\]/);
            if (sectionMatch) {
                const mock = createMockElement('div');
                mock._sectionName = sectionMatch[1];
                return mock;
            }
            const classMatch = sel.match(/\.([a-zA-Z0-9_-]+)/);
            if (classMatch) {
                const mock = createMockElement('div');
                mock.className = classMatch[1];
                return mock;
            }
            return null;
        },
        querySelectorAll(sel) {
            // Return mock speed buttons for .replay-speed-btn queries
            if (sel === '.replay-speed-btn') {
                return [0.25, 0.5, 1, 2, 4].map(speed => {
                    const btn = createMockElement('button');
                    btn._dataSpeed = String(speed);
                    btn.getAttribute = (name) => name === 'data-speed' ? String(speed) : null;
                    return btn;
                });
            }
            if (sel === '.replay-wave-btn') {
                return [];
            }
            return [];
        },
        closest(sel) { return null; },
        _eventListeners: eventListeners,
        _classList: classList,
    };
    return el;
}

const sandbox = {
    Math, Date, console, Map, Set, Array, Object, Number, String, Boolean,
    Infinity, NaN, undefined, parseInt, parseFloat, isNaN, isFinite, JSON,
    Promise, setTimeout, clearTimeout, setInterval, clearInterval, Error,
    document: {
        createElement: createMockElement,
        getElementById: () => null,
        querySelector: () => null,
        addEventListener() {},
        removeEventListener() {},
    },
    window: {},
    fetch: () => Promise.resolve({ ok: true, json: () => Promise.resolve({}) }),
    performance: { now: () => Date.now() },
};

const ctx = vm.createContext(sandbox);

// Load events.js (EventBus)
const eventsCode = fs.readFileSync(__dirname + '/../../src/frontend/js/command/events.js', 'utf8');
const eventsPlain = eventsCode
    .replace(/^export\s+/gm, '')
    .replace(/^import\s+.*$/gm, '');
vm.runInContext(eventsPlain, ctx);

// Load store.js (TritiumStore)
const storeCode = fs.readFileSync(__dirname + '/../../src/frontend/js/command/store.js', 'utf8');
const storePlain = storeCode
    .replace(/^export\s+/gm, '')
    .replace(/^import\s+.*$/gm, '');
vm.runInContext(storePlain, ctx);

// Load replay.js panel
const replayCode = fs.readFileSync(__dirname + '/../../src/frontend/js/command/panels/replay.js', 'utf8');
const replayPlain = replayCode
    .replace(/^export\s+const\s+/gm, 'var ')
    .replace(/^export\s+/gm, '')
    .replace(/^import\s+.*$/gm, '');
vm.runInContext(replayPlain, ctx);

const ReplayPanelDef = ctx.ReplayPanelDef;
const ReplayHelpers = ctx.window.ReplayHelpers;

// ============================================================
// 1. ReplayPanelDef has required properties
// ============================================================

console.log('\n--- ReplayPanelDef structure ---');

(function testHasId() {
    assert(ReplayPanelDef.id === 'replay', 'ReplayPanelDef.id is "replay"');
})();

(function testHasTitle() {
    assert(ReplayPanelDef.title === 'REPLAY', 'ReplayPanelDef.title is "REPLAY"');
})();

(function testHasCreate() {
    assert(typeof ReplayPanelDef.create === 'function', 'ReplayPanelDef.create is a function');
})();

(function testHasMount() {
    assert(typeof ReplayPanelDef.mount === 'function', 'ReplayPanelDef.mount is a function');
})();

(function testHasUnmount() {
    assert(typeof ReplayPanelDef.unmount === 'function', 'ReplayPanelDef.unmount is a function');
})();

(function testHasDefaultPosition() {
    assert(ReplayPanelDef.defaultPosition !== undefined, 'ReplayPanelDef has defaultPosition');
    assert(ReplayPanelDef.defaultPosition.x === 8, 'defaultPosition.x is 8');
    assert(ReplayPanelDef.defaultPosition.y === null, 'defaultPosition.y is null (calculated at mount)');
})();

(function testHasDefaultSize() {
    assert(ReplayPanelDef.defaultSize !== undefined, 'ReplayPanelDef has defaultSize');
    assert(ReplayPanelDef.defaultSize.w === 420, 'defaultSize.w is 420');
    assert(ReplayPanelDef.defaultSize.h === 260, 'defaultSize.h is 260');
})();

// ============================================================
// 2. create() returns DOM element with expected structure
// ============================================================

console.log('\n--- create() DOM structure ---');

(function testCreateReturnsDomElement() {
    const el = ReplayPanelDef.create({});
    assert(el !== null && el !== undefined, 'create() returns an element');
    assert(el.className === 'replay-panel-inner', 'create() element has correct className');
})();

(function testCreateHasStatusBar() {
    const el = ReplayPanelDef.create({});
    const html = el.innerHTML;
    assert(html.includes('data-section="status"'), 'DOM contains status section');
    assert(html.includes('replay-status-bar'), 'DOM has replay-status-bar');
})();

(function testCreateHasModeBadge() {
    const el = ReplayPanelDef.create({});
    const html = el.innerHTML;
    assert(html.includes('data-bind="mode"'), 'DOM contains mode data-bind');
    assert(html.includes('LIVE'), 'DOM contains default mode "LIVE"');
    assert(html.includes('replay-mode-badge'), 'DOM has replay-mode-badge class');
})();

(function testCreateHasTimeDisplay() {
    const el = ReplayPanelDef.create({});
    const html = el.innerHTML;
    assert(html.includes('data-bind="time"'), 'DOM contains time data-bind');
    assert(html.includes('0:00 / 0:00'), 'DOM contains default time "0:00 / 0:00"');
})();

// ============================================================
// 3. Timeline scrubber structure
// ============================================================

console.log('\n--- Timeline scrubber ---');

(function testCreateHasTimeline() {
    const el = ReplayPanelDef.create({});
    const html = el.innerHTML;
    assert(html.includes('data-section="timeline"'), 'DOM contains timeline section');
    assert(html.includes('replay-timeline'), 'DOM has replay-timeline class');
})();

(function testCreateHasTimelineBar() {
    const el = ReplayPanelDef.create({});
    const html = el.innerHTML;
    assert(html.includes('data-element="timeline-bar"'), 'DOM has timeline-bar element');
    assert(html.includes('replay-timeline-bar'), 'DOM has replay-timeline-bar class');
})();

(function testCreateHasTimelineFill() {
    const el = ReplayPanelDef.create({});
    const html = el.innerHTML;
    assert(html.includes('data-element="timeline-fill"'), 'DOM has timeline-fill element');
    assert(html.includes('replay-timeline-fill'), 'DOM has replay-timeline-fill class');
})();

(function testCreateHasPlayhead() {
    const el = ReplayPanelDef.create({});
    const html = el.innerHTML;
    assert(html.includes('data-element="playhead"'), 'DOM has playhead element');
    assert(html.includes('replay-playhead'), 'DOM has replay-playhead class');
})();

(function testCreateHasWaveMarkers() {
    const el = ReplayPanelDef.create({});
    const html = el.innerHTML;
    assert(html.includes('data-element="wave-markers"'), 'DOM has wave-markers element');
    assert(html.includes('replay-wave-markers'), 'DOM has replay-wave-markers class');
})();

// ============================================================
// 4. Transport controls
// ============================================================

console.log('\n--- Transport controls ---');

(function testCreateHasTransportSection() {
    const el = ReplayPanelDef.create({});
    const html = el.innerHTML;
    assert(html.includes('data-section="transport"'), 'DOM contains transport section');
    assert(html.includes('replay-transport'), 'DOM has replay-transport class');
})();

(function testCreateHasRewindButton() {
    const el = ReplayPanelDef.create({});
    const html = el.innerHTML;
    assert(html.includes('data-action="rewind"'), 'DOM has rewind action button');
})();

(function testCreateHasStepBackButton() {
    const el = ReplayPanelDef.create({});
    const html = el.innerHTML;
    assert(html.includes('data-action="step-back"'), 'DOM has step-back action button');
})();

(function testCreateHasPlayPauseButton() {
    const el = ReplayPanelDef.create({});
    const html = el.innerHTML;
    assert(html.includes('data-action="play-pause"'), 'DOM has play-pause action button');
    assert(html.includes('PLAY'), 'Play button shows PLAY by default');
})();

(function testCreateHasStepForwardButton() {
    const el = ReplayPanelDef.create({});
    const html = el.innerHTML;
    assert(html.includes('data-action="step-forward"'), 'DOM has step-forward action button');
})();

(function testCreateHasJumpEndButton() {
    const el = ReplayPanelDef.create({});
    const html = el.innerHTML;
    assert(html.includes('data-action="jump-end"'), 'DOM has jump-end action button');
})();

(function testTransportButtonCount() {
    const el = ReplayPanelDef.create({});
    const html = el.innerHTML;
    const actionCount = (html.match(/data-action="/g) || []).length;
    assert(actionCount === 5, 'Transport section has 5 action buttons, got ' + actionCount);
})();

// ============================================================
// 5. Speed selector
// ============================================================

console.log('\n--- Speed selector ---');

(function testCreateHasSpeedSection() {
    const el = ReplayPanelDef.create({});
    const html = el.innerHTML;
    assert(html.includes('data-section="speed"'), 'DOM contains speed section');
    assert(html.includes('replay-speed'), 'DOM has replay-speed class');
})();

(function testCreateHasSpeedButtons() {
    const el = ReplayPanelDef.create({});
    const html = el.innerHTML;
    assert(html.includes('data-speed="0.25"'), 'DOM has 0.25x speed button');
    assert(html.includes('data-speed="0.5"'), 'DOM has 0.5x speed button');
    assert(html.includes('data-speed="1"'), 'DOM has 1x speed button');
    assert(html.includes('data-speed="2"'), 'DOM has 2x speed button');
    assert(html.includes('data-speed="4"'), 'DOM has 4x speed button');
})();

(function testDefaultSpeedIs1x() {
    const el = ReplayPanelDef.create({});
    const html = el.innerHTML;
    // The 1x button should have the active class
    assert(html.includes('replay-speed-btn--active'), 'One speed button has active class');
    // Check that 1x button specifically has the active class
    const match = html.match(/data-speed="1"[^>]*class="[^"]*replay-speed-btn--active/);
    const match2 = html.match(/class="[^"]*replay-speed-btn--active[^"]*"[^>]*data-speed="1"/);
    const match3 = html.match(/replay-speed-btn replay-speed-btn--active[^"]*" data-speed="1"/);
    assert(match || match2 || match3, '1x speed button has active class by default');
})();

(function testSpeedButtonCount() {
    const el = ReplayPanelDef.create({});
    const html = el.innerHTML;
    const speedCount = (html.match(/data-speed="/g) || []).length;
    assert(speedCount === 5, 'Speed section has 5 speed buttons, got ' + speedCount);
})();

// ============================================================
// 6. Wave jump section
// ============================================================

console.log('\n--- Wave jump ---');

(function testCreateHasWaveSection() {
    const el = ReplayPanelDef.create({});
    const html = el.innerHTML;
    assert(html.includes('data-section="waves"'), 'DOM contains waves section');
})();

// ============================================================
// 7. Event log
// ============================================================

console.log('\n--- Event log ---');

(function testCreateHasEventLog() {
    const el = ReplayPanelDef.create({});
    const html = el.innerHTML;
    assert(html.includes('data-section="event-log"'), 'DOM contains event-log section');
    assert(html.includes('replay-event-log'), 'DOM has replay-event-log class');
})();

(function testCreateHasEventList() {
    const el = ReplayPanelDef.create({});
    const html = el.innerHTML;
    assert(html.includes('data-element="event-list"'), 'DOM has event-list element');
    assert(html.includes('replay-event-list'), 'DOM has replay-event-list class');
})();

(function testCreateHasEventsLabel() {
    const el = ReplayPanelDef.create({});
    const html = el.innerHTML;
    assert(html.includes('EVENTS'), 'DOM contains EVENTS label');
    assert(html.includes('replay-event-log-label'), 'DOM has replay-event-log-label class');
})();

// ============================================================
// 8. Helper functions
// ============================================================

console.log('\n--- Helper functions ---');

(function testReplayHelpersExist() {
    assert(ReplayHelpers !== undefined, 'ReplayHelpers is exposed on window');
    assert(typeof ReplayHelpers.formatTime === 'function', 'formatTime is a function');
    assert(typeof ReplayHelpers.formatEventType === 'function', 'formatEventType is a function');
    assert(typeof ReplayHelpers.formatEventSummary === 'function', 'formatEventSummary is a function');
})();

(function testFormatTime() {
    assert(ReplayHelpers.formatTime(0) === '0:00', 'formatTime(0) => "0:00"');
    assert(ReplayHelpers.formatTime(65) === '1:05', 'formatTime(65) => "1:05"');
    assert(ReplayHelpers.formatTime(125) === '2:05', 'formatTime(125) => "2:05"');
    assert(ReplayHelpers.formatTime(3600) === '60:00', 'formatTime(3600) => "60:00"');
    assert(ReplayHelpers.formatTime(-5) === '0:00', 'formatTime(-5) => "0:00" (clamp)');
    assert(ReplayHelpers.formatTime(null) === '0:00', 'formatTime(null) => "0:00"');
    assert(ReplayHelpers.formatTime(undefined) === '0:00', 'formatTime(undefined) => "0:00"');
})();

(function testFormatEventType() {
    assert(ReplayHelpers.formatEventType('projectile_fired') === 'PROJECTILE FIRED', 'formatEventType replaces underscores and uppercases');
    assert(ReplayHelpers.formatEventType('wave_start') === 'WAVE START', 'formatEventType wave_start');
    assert(ReplayHelpers.formatEventType('') === '', 'formatEventType empty string');
    assert(ReplayHelpers.formatEventType(null) === '', 'formatEventType null');
})();

(function testFormatEventSummary() {
    const elimEvent = { event_type: 'target_eliminated', data: { target_name: 'Hostile-1' } };
    assert(ReplayHelpers.formatEventSummary(elimEvent) === 'Hostile-1 eliminated', 'formatEventSummary target_eliminated');

    const fireEvent = { event_type: 'projectile_fired', data: { source_name: 'Turret-1' } };
    assert(ReplayHelpers.formatEventSummary(fireEvent) === 'Turret-1 fired', 'formatEventSummary projectile_fired');

    const hitEvent = { event_type: 'projectile_hit', data: { target_name: 'Scout' } };
    assert(ReplayHelpers.formatEventSummary(hitEvent) === 'Hit on Scout', 'formatEventSummary projectile_hit');

    const waveEvent = { event_type: 'wave_start', data: { wave_number: 3 } };
    assert(ReplayHelpers.formatEventSummary(waveEvent) === 'Wave 3 started', 'formatEventSummary wave_start');

    const completeEvent = { event_type: 'wave_complete', data: { wave_number: 2 } };
    assert(ReplayHelpers.formatEventSummary(completeEvent) === 'Wave 2 complete', 'formatEventSummary wave_complete');

    const gameOverEvent = { event_type: 'game_over', data: { result: 'victory' } };
    assert(ReplayHelpers.formatEventSummary(gameOverEvent) === 'Game over: victory', 'formatEventSummary game_over');

    assert(ReplayHelpers.formatEventSummary(null) === '', 'formatEventSummary null');
})();

// ============================================================
// 9. mount() wires subscriptions
// ============================================================

console.log('\n--- mount() ---');

(function testMountSubscribes() {
    const bodyEl = createMockElement('div');
    const panel = {
        def: ReplayPanelDef,
        w: 420,
        h: 260,
        x: 0,
        y: 0,
        manager: {
            container: createMockElement('div'),
            getPanel: () => null,
        },
        _unsubs: [],
        _applyTransform() {},
    };
    panel.manager.container.clientHeight = 800;

    ReplayPanelDef.mount(bodyEl, panel);
    assert(panel._unsubs.length >= 1, 'mount() registers at least 1 subscription, got ' + panel._unsubs.length);
})();

(function testMountCalculatesYPosition() {
    const bodyEl = createMockElement('div');
    const panel = {
        def: ReplayPanelDef,
        w: 420,
        h: 260,
        x: 0,
        y: 0,
        manager: {
            container: createMockElement('div'),
            getPanel: () => null,
        },
        _unsubs: [],
        _applyTransform() {},
    };
    panel.manager.container.clientHeight = 800;

    ReplayPanelDef.mount(bodyEl, panel);
    // y = ch - h - 40 = 800 - 260 - 40 = 500
    assert(panel.y === 500, 'mount() positions panel at bottom-left (expected 500, got ' + panel.y + ')');
})();

(function testMountDoesNotCrash() {
    const bodyEl = createMockElement('div');
    const panel = {
        def: ReplayPanelDef,
        w: 420,
        h: 260,
        x: 0,
        y: 0,
        manager: {
            container: createMockElement('div'),
            getPanel: () => null,
        },
        _unsubs: [],
        _applyTransform() {},
    };
    panel.manager.container.clientHeight = 800;

    let threw = false;
    try {
        ReplayPanelDef.mount(bodyEl, panel);
    } catch (e) {
        threw = true;
    }
    assert(!threw, 'mount() does not crash');
})();

// ============================================================
// 10. unmount() exists and does not crash
// ============================================================

console.log('\n--- unmount() ---');

(function testUnmountDoesNotCrash() {
    const bodyEl = createMockElement('div');
    let threw = false;
    try {
        ReplayPanelDef.unmount(bodyEl);
    } catch (e) {
        threw = true;
    }
    assert(!threw, 'unmount() does not throw');
})();

(function testUnmountSetsReplayInactive() {
    const bodyEl = createMockElement('div');
    const TritiumStore = vm.runInContext('TritiumStore', ctx);
    TritiumStore.set('replay.active', true);
    ReplayPanelDef.unmount(bodyEl);
    assert(TritiumStore.get('replay.active') === false, 'unmount() sets replay.active to false');
})();

// ============================================================
// 11. State management (live vs replay)
// ============================================================

console.log('\n--- State management ---');

(function testDefaultModeLive() {
    const el = ReplayPanelDef.create({});
    const html = el.innerHTML;
    assert(html.includes('LIVE'), 'Default mode badge shows LIVE');
})();

(function testStorePhaseNotification() {
    const bodyEl = createMockElement('div');
    const panel = {
        def: ReplayPanelDef,
        w: 420,
        h: 260,
        x: 0,
        y: 0,
        manager: {
            container: createMockElement('div'),
            getPanel: () => null,
        },
        _unsubs: [],
        _applyTransform() {},
    };
    panel.manager.container.clientHeight = 800;

    ReplayPanelDef.mount(bodyEl, panel);

    const TritiumStore = vm.runInContext('TritiumStore', ctx);
    let threw = false;
    try {
        TritiumStore.set('game.phase', 'victory');
    } catch (e) {
        threw = true;
    }
    assert(!threw, 'Store game.phase victory notification does not crash');
})();

// ============================================================
// 12. CSS class naming conventions
// ============================================================

console.log('\n--- CSS class naming ---');

(function testAllCssClassesUseReplayPrefix() {
    const el = ReplayPanelDef.create({});
    const html = el.innerHTML;
    // Extract all class names
    const classMatches = html.matchAll(/class="([^"]+)"/g);
    let allPrefixed = true;
    for (const m of classMatches) {
        const classes = m[1].split(/\s+/);
        for (const cls of classes) {
            if (cls && !cls.startsWith('replay-') && cls !== 'mono') {
                allPrefixed = false;
                console.error('  Non-prefixed class found:', cls);
            }
        }
    }
    assert(allPrefixed, 'All panel CSS classes use "replay-" prefix (except "mono")');
})();

// ============================================================
// Replay frame includes fog-of-war fields
// ============================================================

(function testReplayFrameFogOfWarFields() {
    // Read replay.js source to check applyFrameToStore includes visibility fields
    const replaySrc = fs.readFileSync('src/frontend/js/command/panels/replay.js', 'utf8');

    const hasVisible = replaySrc.includes('visible: t.visible');
    assert(hasVisible, 'applyFrameToStore passes through visible field');

    const hasRadioDetected = replaySrc.includes('radio_detected: t.radio_detected');
    assert(hasRadioDetected, 'applyFrameToStore passes through radio_detected field');

    const hasMorale = replaySrc.includes('morale: t.morale');
    assert(hasMorale, 'applyFrameToStore passes through morale field');
})();

(function testReplayRecorderIncludesFogFields() {
    // Read replay.py to verify the backend includes fog fields in snapshots
    const replayPy = fs.readFileSync('src/engine/simulation/replay.py', 'utf8');

    const hasVisibleField = replayPy.includes('"visible": t.visible');
    assert(hasVisibleField, 'Backend replay recorder includes visible in snapshot');

    const hasRadioField = replayPy.includes('"radio_detected": t.radio_detected');
    assert(hasRadioField, 'Backend replay recorder includes radio_detected in snapshot');

    const hasMoraleField = replayPy.includes('"morale"');
    assert(hasMoraleField, 'Backend replay recorder includes morale in snapshot');
})();

// ============================================================
// Backward seek: eliminated units should not vanish
// ============================================================

console.log('\n--- Backward seek elimination handling ---');

(function testApplyFrameDoesNotRemoveEliminatedUnits() {
    // Simulated scenario:
    // Frame 10: turret-1 alive, hostile-1 alive
    // Frame 15: turret-1 alive, hostile-1 eliminated (still in frame)
    // Frame 20: turret-1 alive (hostile-1 no longer in frame — removed after 30s)
    // Seek backward to Frame 10: hostile-1 should reappear alive

    // The fix: applyFrameToStore should mark missing units as eliminated
    // instead of removing them from the store entirely.

    // Read replay.js source to check for the fix
    const src = fs.readFileSync('src/frontend/js/command/panels/replay.js', 'utf8');

    // The old bug: `TritiumStore.removeUnit(id)` for units not in frame
    // The fix: should not blindly remove, should mark eliminated instead
    const hasRemoveUnit = src.includes('removeUnit');
    // After the fix, removeUnit should still exist but be guarded by _replayMode
    // OR the logic should mark units as eliminated instead of removing

    // Check that the applyFrameToStore function handles missing units
    // by marking them eliminated rather than removing them
    const applyFnStart = src.indexOf('function applyFrameToStore');
    assert(applyFnStart > 0, 'applyFrameToStore function exists');

    const applyFnBlock = src.substring(applyFnStart, applyFnStart + 800);

    // The fix: units not in the current frame should be marked eliminated,
    // not removed from the store. Read a larger block to get the full function.
    const applyFnFull = src.substring(applyFnStart, applyFnStart + 1200);
    // Find the section after "frameIds" that handles units not in the frame
    const frameIdsIdx = applyFnFull.indexOf('frameIds.has');
    const afterFrameCheck = applyFnFull.substring(frameIdsIdx);
    const removesBlindly = afterFrameCheck.includes('removeUnit') && !afterFrameCheck.includes('eliminated');
    assert(!removesBlindly, 'applyFrameToStore does not blindly remove missing units (marks eliminated instead)');
})();

// ============================================================
// 13. Mounted panel helpers — shared setup for behavioral tests
// ============================================================

// Build a bodyEl mock that returns persistent child elements.
// mount() queries for specific data-bind/data-action/data-element/data-section
// selectors, so we keep a registry so the same element is returned each time.
function createMountedEnv(fetchImpl, opts) {
    const options = opts || {};
    // If true, the user's fetchImpl handles /api/game/replay and /timeline directly
    const overrideReplayEndpoints = options.overrideReplayEndpoints || false;
    const elementCache = {};
    // Speed buttons — persistent array with classList support
    const speedBtns = [0.25, 0.5, 1, 2, 4].map(speed => {
        const btn = createMockElement('button');
        btn._dataSpeed = String(speed);
        btn.getAttribute = (name) => name === 'data-speed' ? String(speed) : null;
        return btn;
    });
    // Wave buttons — initially empty, buildWaveButtons may repopulate container
    let waveBtns = [];

    function getOrCreate(key, tag) {
        if (!elementCache[key]) elementCache[key] = createMockElement(tag || 'div');
        return elementCache[key];
    }

    const bodyEl = createMockElement('div');
    bodyEl.querySelector = function(sel) {
        const bindMatch = sel.match(/\[data-bind="([^"]+)"\]/);
        if (bindMatch) return getOrCreate('bind:' + bindMatch[1], 'span');
        const actionMatch = sel.match(/\[data-action="([^"]+)"\]/);
        if (actionMatch) {
            const el = getOrCreate('action:' + actionMatch[1], 'button');
            el._dataAction = actionMatch[1];
            return el;
        }
        const elementMatch = sel.match(/\[data-element="([^"]+)"\]/);
        if (elementMatch) return getOrCreate('element:' + elementMatch[1], 'div');
        const sectionMatch = sel.match(/\[data-section="([^"]+)"\]/);
        if (sectionMatch) {
            const el = getOrCreate('section:' + sectionMatch[1], 'div');
            // waves section needs querySelectorAll for wave buttons
            if (sectionMatch[1] === 'waves') {
                el.querySelectorAll = (s) => {
                    if (s === '.replay-wave-btn') return waveBtns;
                    return [];
                };
            }
            return el;
        }
        const classMatch = sel.match(/\.([a-zA-Z0-9_-]+)/);
        if (classMatch) return getOrCreate('class:' + classMatch[1], 'div');
        return null;
    };
    bodyEl.querySelectorAll = function(sel) {
        if (sel === '.replay-speed-btn') return speedBtns;
        if (sel === '.replay-wave-btn') return waveBtns;
        return [];
    };

    const panel = {
        def: ReplayPanelDef,
        w: 420, h: 260, x: 0, y: 0,
        manager: {
            container: createMockElement('div'),
            getPanel: () => null,
        },
        _unsubs: [],
        _applyTransform() {},
    };
    panel.manager.container.clientHeight = 800;

    // Install fetch mock.  Wrap user's fetchImpl with a base layer that
    // always returns valid replay + timeline data for loadReplayData(),
    // preventing buildWaveButtons from crashing on non-array _timeline.
    // The wrapper intercepts the two data-load URLs; everything else is
    // delegated to the user's fetchImpl.
    const prevFetch = ctx.fetch;
    const _defaultReplayResp = {
        metadata: { start_time: 1000 },
        frames: [{ targets: [], timestamp: 1000 }],
    };
    const _defaultTimeline = [
        { event_type: 'wave_start', timestamp: 1002, data: { wave_number: 1 } },
    ];
    ctx.fetch = function(url, fetchOpts) {
        if (!overrideReplayEndpoints) {
            // Provide valid data for the two loadReplayData endpoints.
            // Call user fetchImpl to let it record the call for tracking.
            if (url === '/api/game/replay') {
                if (fetchImpl) fetchImpl(url, fetchOpts);
                return Promise.resolve({ ok: true, json: () => Promise.resolve(_defaultReplayResp) });
            }
            if (url === '/api/game/replay/timeline') {
                if (fetchImpl) fetchImpl(url, fetchOpts);
                return Promise.resolve({ ok: true, json: () => Promise.resolve(_defaultTimeline) });
            }
        }
        // Delegate everything else (or overridden endpoints) to user's fetchImpl
        if (fetchImpl) return fetchImpl(url, fetchOpts);
        return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    };

    // Track setInterval / clearInterval calls
    const intervals = [];
    const prevSetInterval = ctx.setInterval;
    const prevClearInterval = ctx.clearInterval;
    let nextIntervalId = 100;
    ctx.setInterval = function(fn, ms) {
        const id = nextIntervalId++;
        intervals.push({ id, fn, ms, cleared: false });
        return id;
    };
    ctx.clearInterval = function(id) {
        const entry = intervals.find(i => i.id === id);
        if (entry) entry.cleared = true;
    };

    // Mount the panel
    ReplayPanelDef.mount(bodyEl, panel);

    function cleanup() {
        ctx.fetch = prevFetch;
        ctx.setInterval = prevSetInterval;
        ctx.clearInterval = prevClearInterval;
    }

    function getBtn(action) {
        return elementCache['action:' + action];
    }

    function getElement(name) {
        return elementCache['element:' + name];
    }

    function getBind(name) {
        return elementCache['bind:' + name];
    }

    function getSection(name) {
        return elementCache['section:' + name];
    }

    // Fire a click event on a button element
    async function clickBtn(action) {
        const btn = getBtn(action);
        if (!btn) throw new Error('No button: ' + action);
        const listeners = btn._eventListeners['click'] || [];
        for (const fn of listeners) await fn({ clientX: 0, clientY: 0 });
    }

    // Fire click on a speed button by speed value
    async function clickSpeed(speed) {
        const btn = speedBtns.find(b => b._dataSpeed === String(speed));
        if (!btn) throw new Error('No speed button: ' + speed);
        const listeners = btn._eventListeners['click'] || [];
        for (const fn of listeners) await fn();
    }

    // Fire click on timeline bar at a given fraction (0..1)
    async function clickTimeline(fraction) {
        const bar = getElement('timeline-bar');
        if (!bar) throw new Error('No timeline bar');
        const listeners = bar._eventListeners['click'] || [];
        const rect = bar.getBoundingClientRect(); // {left:0, width:400}
        for (const fn of listeners) await fn({ clientX: fraction * rect.width });
    }

    return {
        bodyEl, panel, speedBtns, intervals, waveBtns,
        cleanup, getBtn, getElement, getBind, getSection,
        clickBtn, clickSpeed, clickTimeline,
    };
}

// ============================================================
// Async behavioral tests -- serialized via main()
// ============================================================

async function runAsyncTests() {

// ============================================================
// 14. Play/pause button state toggling
// ============================================================

console.log('\n--- Play/pause button state ---');

await (async function testPlayButtonChangesToPause() {
    const fetchCalls = [];
    const env = createMountedEnv(function(url, opts) {
        fetchCalls.push({ url, opts });
        // Simulate play response: playing=true
        return Promise.resolve({
            ok: true,
            json: () => Promise.resolve({
                playing: true, speed: 1, progress: 0, current_time: 0, duration: 60
            }),
        });
    });
    try {
        await env.clickBtn('play-pause');
        const playBtn = env.getBtn('play-pause');
        assert(playBtn.textContent === 'PAUSE', 'After play click, button says PAUSE');
    } catch (e) { assert(false, 'play-pause toggle to PAUSE: ' + e.message); }
    env.cleanup();
})();

await (async function testPauseButtonChangesToPlay() {
    let callCount = 0;
    const env = createMountedEnv(function(url, opts) {
        callCount++;
        if (url === '/api/game/replay/play' || url === '/api/game/replay/frame') {
            return Promise.resolve({
                ok: true,
                json: () => Promise.resolve({
                    playing: true, speed: 1, progress: 0.5, current_time: 30, duration: 60,
                    state: { playing: true, speed: 1, progress: 0.5, current_time: 30, duration: 60 },
                }),
            });
        }
        if (url === '/api/game/replay/pause') {
            return Promise.resolve({
                ok: true,
                json: () => Promise.resolve({
                    playing: false, speed: 1, progress: 0.5, current_time: 30, duration: 60
                }),
            });
        }
        return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    });
    try {
        // First click: enters replay mode + play
        await env.clickBtn('play-pause');
        const playBtn = env.getBtn('play-pause');
        assert(playBtn.textContent === 'PAUSE', 'First click sets PAUSE text');
        // Second click: pause
        await env.clickBtn('play-pause');
        assert(playBtn.textContent === 'PLAY', 'Second click sets PLAY text');
    } catch (e) { assert(false, 'play-pause toggle cycle: ' + e.message); }
    env.cleanup();
})();

await (async function testPlaySendsCorrectEndpoint() {
    const fetchCalls = [];
    const env = createMountedEnv(function(url, opts) {
        fetchCalls.push({ url, opts });
        if (url === '/api/game/replay/play') {
            return Promise.resolve({
                ok: true,
                json: () => Promise.resolve({
                    playing: true, speed: 1, progress: 0, current_time: 0, duration: 60
                }),
            });
        }
        return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    });
    try {
        await env.clickBtn('play-pause');
        const playCall = fetchCalls.find(c => c.url === '/api/game/replay/play');
        assert(playCall !== undefined, 'Play click sends /api/game/replay/play');
        assert(playCall.opts && playCall.opts.method === 'POST', 'Play request uses POST');
    } catch (e) { assert(false, 'play endpoint check: ' + e.message); }
    env.cleanup();
})();

await (async function testPauseSendsCorrectEndpoint() {
    const fetchCalls = [];
    const env = createMountedEnv(function(url, opts) {
        fetchCalls.push({ url, opts });
        if (url === '/api/game/replay/play') {
            return Promise.resolve({
                ok: true,
                json: () => Promise.resolve({
                    playing: true, speed: 1, progress: 0, current_time: 0, duration: 60
                }),
            });
        }
        if (url === '/api/game/replay/pause') {
            return Promise.resolve({
                ok: true,
                json: () => Promise.resolve({
                    playing: false, speed: 1, progress: 0, current_time: 0, duration: 60
                }),
            });
        }
        return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    });
    try {
        // First click plays
        await env.clickBtn('play-pause');
        // Second click pauses
        await env.clickBtn('play-pause');
        const pauseCall = fetchCalls.find(c => c.url === '/api/game/replay/pause');
        assert(pauseCall !== undefined, 'Pause click sends /api/game/replay/pause');
        assert(pauseCall.opts && pauseCall.opts.method === 'POST', 'Pause request uses POST');
    } catch (e) { assert(false, 'pause endpoint check: ' + e.message); }
    env.cleanup();
})();

// ============================================================
// 15. Polling lifecycle
// ============================================================

console.log('\n--- Polling lifecycle ---');

await (async function testEnterReplayModeCreatesInterval() {
    const env = createMountedEnv(function(url) {
        return Promise.resolve({
            ok: true,
            json: () => Promise.resolve({
                playing: true, speed: 1, progress: 0, current_time: 0, duration: 60
            }),
        });
    });
    try {
        await env.clickBtn('play-pause'); // triggers enterReplayMode
        const active = env.intervals.filter(i => !i.cleared);
        assert(active.length >= 1, 'enterReplayMode creates at least 1 interval, got ' + active.length);
        // Check interval is 250ms (4Hz)
        const pollInterval = active.find(i => i.ms === 250);
        assert(pollInterval !== undefined, 'Poll interval is 250ms (4Hz)');
    } catch (e) { assert(false, 'polling interval creation: ' + e.message); }
    env.cleanup();
})();

await (async function testUnsubCleanupClearsPollTimer() {
    const env = createMountedEnv(function(url) {
        return Promise.resolve({
            ok: true,
            json: () => Promise.resolve({
                playing: true, speed: 1, progress: 0, current_time: 0, duration: 60
            }),
        });
    });
    try {
        await env.clickBtn('play-pause'); // triggers enterReplayMode
        // Call the unsub cleanup functions registered during mount
        for (const unsub of env.panel._unsubs) {
            if (typeof unsub === 'function') unsub();
        }
        const allCleared = env.intervals.every(i => i.cleared);
        assert(allCleared, 'After cleanup, all poll intervals are cleared');
    } catch (e) { assert(false, 'polling cleanup: ' + e.message); }
    env.cleanup();
})();

await (async function testPollTimerCallsFetchWhenPlaying() {
    let fetchCallCount = 0;
    const env = createMountedEnv(function(url) {
        fetchCallCount++;
        return Promise.resolve({
            ok: true,
            json: () => Promise.resolve({
                playing: true, speed: 1, progress: 0.1, current_time: 6, duration: 60,
                state: { playing: true, speed: 1, progress: 0.1, current_time: 6, duration: 60 },
            }),
        });
    });
    try {
        await env.clickBtn('play-pause');
        const beforeCount = fetchCallCount;
        // Simulate the interval firing by calling the fn directly
        const pollInterval = env.intervals.find(i => i.ms === 250 && !i.cleared);
        assert(pollInterval !== undefined, 'Poll interval exists for trigger test');
        if (pollInterval) {
            pollInterval.fn();
            await new Promise(r => setTimeout(r, 50));
            assert(fetchCallCount > beforeCount, 'Poll timer fn triggers fetch when playing');
        }
    } catch (e) { assert(false, 'poll timer fetch: ' + e.message); }
    env.cleanup();
})();

await (async function testPollTimerSkipsFetchWhenPaused() {
    let fetchCallCount = 0;
    const env = createMountedEnv(function(url) {
        fetchCallCount++;
        if (url === '/api/game/replay/play') {
            return Promise.resolve({
                ok: true,
                json: () => Promise.resolve({
                    playing: true, speed: 1, progress: 0, current_time: 0, duration: 60
                }),
            });
        }
        if (url === '/api/game/replay/pause') {
            return Promise.resolve({
                ok: true,
                json: () => Promise.resolve({
                    playing: false, speed: 1, progress: 0.5, current_time: 30, duration: 60
                }),
            });
        }
        return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    });
    try {
        // Play then pause
        await env.clickBtn('play-pause');
        await env.clickBtn('play-pause');
        const beforeCount = fetchCallCount;
        // Poll timer fires but _playing is false, so should not fetch
        const pollInterval = env.intervals.find(i => i.ms === 250 && !i.cleared);
        if (pollInterval) {
            pollInterval.fn();
            await new Promise(r => setTimeout(r, 50));
            // The if (_playing) guard in the interval should prevent any fetch
            assert(fetchCallCount === beforeCount, 'Poll timer skips fetch when paused');
        } else {
            assert(true, 'Poll timer skips fetch when paused (no interval)');
        }
    } catch (e) { assert(false, 'poll timer paused skip: ' + e.message); }
    env.cleanup();
})();

// ============================================================
// 16. Speed control
// ============================================================

console.log('\n--- Speed control ---');

await (async function testSpeedButtonSendsCorrectSpeed() {
    const fetchCalls = [];
    const env = createMountedEnv(function(url, opts) {
        fetchCalls.push({ url, opts });
        if (url === '/api/game/replay/speed') {
            const body = JSON.parse(opts.body);
            return Promise.resolve({
                ok: true,
                json: () => Promise.resolve({
                    playing: true, speed: body.speed, progress: 0.5, current_time: 30, duration: 60
                }),
            });
        }
        return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    });
    try {
        await env.clickSpeed(2);
        const speedCall = fetchCalls.find(c => c.url === '/api/game/replay/speed');
        assert(speedCall !== undefined, 'Speed click sends /api/game/replay/speed');
        const body = JSON.parse(speedCall.opts.body);
        assert(body.speed === 2, 'Speed request body has speed: 2');
    } catch (e) { assert(false, 'speed button 2x: ' + e.message); }
    env.cleanup();
})();

await (async function testSpeed4xSendsCorrectValue() {
    const fetchCalls = [];
    const env = createMountedEnv(function(url, opts) {
        fetchCalls.push({ url, opts });
        if (url === '/api/game/replay/speed') {
            const body = JSON.parse(opts.body);
            return Promise.resolve({
                ok: true,
                json: () => Promise.resolve({
                    playing: true, speed: body.speed, progress: 0, current_time: 0, duration: 60
                }),
            });
        }
        return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    });
    try {
        await env.clickSpeed(4);
        const speedCall = fetchCalls.find(c => c.url === '/api/game/replay/speed');
        assert(speedCall !== undefined, 'Speed 4x click sends /api/game/replay/speed');
        const body = JSON.parse(speedCall.opts.body);
        assert(body.speed === 4, 'Speed 4x request body has speed: 4');
    } catch (e) { assert(false, 'speed button 4x: ' + e.message); }
    env.cleanup();
})();

await (async function testSpeedHalfSendsCorrectValue() {
    const fetchCalls = [];
    const env = createMountedEnv(function(url, opts) {
        fetchCalls.push({ url, opts });
        if (url === '/api/game/replay/speed') {
            const body = JSON.parse(opts.body);
            return Promise.resolve({
                ok: true,
                json: () => Promise.resolve({
                    playing: false, speed: body.speed, progress: 0, current_time: 0, duration: 60
                }),
            });
        }
        return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    });
    try {
        await env.clickSpeed(0.5);
        const speedCall = fetchCalls.find(c => c.url === '/api/game/replay/speed');
        assert(speedCall !== undefined, 'Speed 0.5x click sends /api/game/replay/speed');
        const body = JSON.parse(speedCall.opts.body);
        assert(body.speed === 0.5, 'Speed 0.5x request body has speed: 0.5');
    } catch (e) { assert(false, 'speed button 0.5x: ' + e.message); }
    env.cleanup();
})();

await (async function testSpeedQuarterSendsCorrectValue() {
    const fetchCalls = [];
    const env = createMountedEnv(function(url, opts) {
        fetchCalls.push({ url, opts });
        if (url === '/api/game/replay/speed') {
            const body = JSON.parse(opts.body);
            return Promise.resolve({
                ok: true,
                json: () => Promise.resolve({
                    playing: false, speed: body.speed, progress: 0, current_time: 0, duration: 60
                }),
            });
        }
        return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    });
    try {
        await env.clickSpeed(0.25);
        const speedCall = fetchCalls.find(c => c.url === '/api/game/replay/speed');
        assert(speedCall !== undefined, 'Speed 0.25x click sends /api/game/replay/speed');
        const body = JSON.parse(speedCall.opts.body);
        assert(body.speed === 0.25, 'Speed 0.25x request body has speed: 0.25');
    } catch (e) { assert(false, 'speed button 0.25x: ' + e.message); }
    env.cleanup();
})();

await (async function testSpeedButtonUpdatesActiveClass() {
    const env = createMountedEnv(function(url, opts) {
        if (url === '/api/game/replay/speed') {
            const body = JSON.parse(opts.body);
            return Promise.resolve({
                ok: true,
                json: () => Promise.resolve({
                    playing: true, speed: body.speed, progress: 0, current_time: 0, duration: 60
                }),
            });
        }
        return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    });
    try {
        await env.clickSpeed(2);
        // Check that the 2x button has active class and others don't
        const btn2 = env.speedBtns.find(b => b._dataSpeed === '2');
        const btn1 = env.speedBtns.find(b => b._dataSpeed === '1');
        assert(btn2._classList.has('replay-speed-btn--active'), '2x button has active class after click');
        assert(!btn1._classList.has('replay-speed-btn--active'), '1x button loses active class after 2x click');
    } catch (e) { assert(false, 'speed active class toggle: ' + e.message); }
    env.cleanup();
})();

// ============================================================
// 17. Step forward / backward
// ============================================================

console.log('\n--- Step forward / backward ---');

await (async function testStepForwardSendsRequest() {
    const fetchCalls = [];
    const env = createMountedEnv(function(url, opts) {
        fetchCalls.push({ url, opts });
        if (url === '/api/game/replay/step-forward') {
            return Promise.resolve({
                ok: true,
                json: () => Promise.resolve({
                    playing: false, speed: 1, progress: 0.1, current_time: 6, duration: 60
                }),
            });
        }
        return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    });
    try {
        await env.clickBtn('step-forward');
        const call = fetchCalls.find(c => c.url === '/api/game/replay/step-forward');
        assert(call !== undefined, 'Step forward sends /api/game/replay/step-forward');
        assert(call.opts && call.opts.method === 'POST', 'Step forward uses POST');
    } catch (e) { assert(false, 'step forward API: ' + e.message); }
    env.cleanup();
})();

await (async function testStepBackwardSendsRequest() {
    const fetchCalls = [];
    const env = createMountedEnv(function(url, opts) {
        fetchCalls.push({ url, opts });
        if (url === '/api/game/replay/step-backward') {
            return Promise.resolve({
                ok: true,
                json: () => Promise.resolve({
                    playing: false, speed: 1, progress: 0.0, current_time: 0, duration: 60
                }),
            });
        }
        return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    });
    try {
        await env.clickBtn('step-back');
        const call = fetchCalls.find(c => c.url === '/api/game/replay/step-backward');
        assert(call !== undefined, 'Step back sends /api/game/replay/step-backward');
        assert(call.opts && call.opts.method === 'POST', 'Step back uses POST');
    } catch (e) { assert(false, 'step backward API: ' + e.message); }
    env.cleanup();
})();

await (async function testStepForwardUpdatesTime() {
    const env = createMountedEnv(function(url) {
        if (url === '/api/game/replay/step-forward') {
            return Promise.resolve({
                ok: true,
                json: () => Promise.resolve({
                    playing: false, speed: 1, progress: 0.5, current_time: 30, duration: 60
                }),
            });
        }
        return Promise.resolve({
            ok: true,
            json: () => Promise.resolve({
                state: { playing: false, speed: 1, progress: 0.5, current_time: 30, duration: 60 },
            }),
        });
    });
    try {
        await env.clickBtn('step-forward');
        const timeBind = env.getBind('time');
        assert(timeBind.textContent === '0:30 / 1:00', 'Step forward updates time to 0:30 / 1:00, got: ' + timeBind.textContent);
    } catch (e) { assert(false, 'step forward time update: ' + e.message); }
    env.cleanup();
})();

await (async function testStepBackwardUpdatesTime() {
    const env = createMountedEnv(function(url) {
        if (url === '/api/game/replay/step-backward') {
            return Promise.resolve({
                ok: true,
                json: () => Promise.resolve({
                    playing: false, speed: 1, progress: 0.25, current_time: 15, duration: 60
                }),
            });
        }
        return Promise.resolve({
            ok: true,
            json: () => Promise.resolve({
                state: { playing: false, speed: 1, progress: 0.25, current_time: 15, duration: 60 },
            }),
        });
    });
    try {
        await env.clickBtn('step-back');
        const timeBind = env.getBind('time');
        assert(timeBind.textContent === '0:15 / 1:00', 'Step backward updates time to 0:15 / 1:00, got: ' + timeBind.textContent);
    } catch (e) { assert(false, 'step backward time update: ' + e.message); }
    env.cleanup();
})();

await (async function testStepForwardEntersReplayMode() {
    const fetchCalls = [];
    const env = createMountedEnv(function(url, opts) {
        fetchCalls.push({ url });
        return Promise.resolve({
            ok: true,
            json: () => Promise.resolve({
                playing: false, speed: 1, progress: 0, current_time: 0, duration: 60,
                state: { playing: false, speed: 1, progress: 0, current_time: 0, duration: 60 },
            }),
        });
    });
    try {
        await env.clickBtn('step-forward');
        // enterReplayMode loads /api/game/replay and /api/game/replay/timeline
        const replayLoad = fetchCalls.find(c => c.url === '/api/game/replay');
        assert(replayLoad !== undefined, 'Step forward triggers enterReplayMode -> loads replay data');
    } catch (e) { assert(false, 'step forward enters replay: ' + e.message); }
    env.cleanup();
})();

// ============================================================
// 18. Rewind and Jump to end
// ============================================================

console.log('\n--- Rewind and Jump to end ---');

await (async function testRewindSendsSeekToZero() {
    const fetchCalls = [];
    const env = createMountedEnv(function(url, opts) {
        fetchCalls.push({ url, opts });
        if (url === '/api/game/replay/state') {
            return Promise.resolve({
                ok: true,
                json: () => Promise.resolve({
                    playing: false, speed: 1, progress: 0, current_time: 0, duration: 60
                }),
            });
        }
        return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    });
    try {
        await env.clickBtn('rewind');
        const seekCall = fetchCalls.find(c => c.url === '/api/game/replay/seek');
        assert(seekCall !== undefined, 'Rewind sends /api/game/replay/seek');
        const body = JSON.parse(seekCall.opts.body);
        assert(body.time === 0, 'Rewind seeks to time: 0');
    } catch (e) { assert(false, 'rewind seek zero: ' + e.message); }
    env.cleanup();
})();

await (async function testRewindStopsPlaybackFirst() {
    const fetchCalls = [];
    const env = createMountedEnv(function(url, opts) {
        fetchCalls.push({ url, opts });
        return Promise.resolve({
            ok: true,
            json: () => Promise.resolve({
                playing: false, speed: 1, progress: 0, current_time: 0, duration: 60
            }),
        });
    });
    try {
        await env.clickBtn('rewind');
        const stopCall = fetchCalls.find(c => c.url === '/api/game/replay/stop');
        assert(stopCall !== undefined, 'Rewind sends /api/game/replay/stop before seeking');
        assert(stopCall.opts && stopCall.opts.method === 'POST', 'Stop request uses POST');
    } catch (e) { assert(false, 'rewind stops first: ' + e.message); }
    env.cleanup();
})();

await (async function testRewindFetchesStateAfterSeek() {
    const fetchCalls = [];
    const env = createMountedEnv(function(url, opts) {
        fetchCalls.push({ url, opts });
        return Promise.resolve({
            ok: true,
            json: () => Promise.resolve({
                playing: false, speed: 1, progress: 0, current_time: 0, duration: 60
            }),
        });
    });
    try {
        await env.clickBtn('rewind');
        const stateCall = fetchCalls.find(c => c.url === '/api/game/replay/state');
        assert(stateCall !== undefined, 'Rewind fetches /api/game/replay/state');
    } catch (e) { assert(false, 'rewind fetches state: ' + e.message); }
    env.cleanup();
})();

await (async function testJumpEndSendsSeekToDuration() {
    const fetchCalls = [];
    // Need to set _duration first. enterReplayMode loads replay data.
    // We'll use applyState via a play-pause to set _duration to 120.
    const env = createMountedEnv(function(url, opts) {
        fetchCalls.push({ url, opts });
        if (url === '/api/game/replay/play') {
            return Promise.resolve({
                ok: true,
                json: () => Promise.resolve({
                    playing: true, speed: 1, progress: 0, current_time: 0, duration: 120
                }),
            });
        }
        if (url === '/api/game/replay/state') {
            return Promise.resolve({
                ok: true,
                json: () => Promise.resolve({
                    playing: false, speed: 1, progress: 1.0, current_time: 120, duration: 120
                }),
            });
        }
        return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    });
    try {
        // First, play so _duration gets set
        await env.clickBtn('play-pause');
        fetchCalls.length = 0; // reset
        await env.clickBtn('jump-end');
        const seekCall = fetchCalls.find(c => c.url === '/api/game/replay/seek');
        assert(seekCall !== undefined, 'Jump-end sends /api/game/replay/seek');
        const body = JSON.parse(seekCall.opts.body);
        assert(body.time === 120, 'Jump-end seeks to duration (120), got ' + body.time);
    } catch (e) { assert(false, 'jump-end seek: ' + e.message); }
    env.cleanup();
})();

await (async function testJumpEndEntersReplayModeIfNeeded() {
    const fetchCalls = [];
    const env = createMountedEnv(function(url, opts) {
        fetchCalls.push({ url });
        return Promise.resolve({
            ok: true,
            json: () => Promise.resolve({
                playing: false, speed: 1, progress: 0, current_time: 0, duration: 60,
            }),
        });
    });
    try {
        await env.clickBtn('jump-end');
        const replayLoad = fetchCalls.find(c => c.url === '/api/game/replay');
        assert(replayLoad !== undefined, 'Jump-end enters replay mode -> loads replay data');
    } catch (e) { assert(false, 'jump-end enters replay: ' + e.message); }
    env.cleanup();
})();

// ============================================================
// 19. Timeline click-to-seek
// ============================================================

console.log('\n--- Timeline click-to-seek ---');

await (async function testTimelineClickSendsSeek() {
    const fetchCalls = [];
    const env = createMountedEnv(function(url, opts) {
        fetchCalls.push({ url, opts });
        if (url === '/api/game/replay/play') {
            return Promise.resolve({
                ok: true,
                json: () => Promise.resolve({
                    playing: true, speed: 1, progress: 0, current_time: 0, duration: 100
                }),
            });
        }
        return Promise.resolve({
            ok: true,
            json: () => Promise.resolve({
                state: { playing: true, speed: 1, progress: 0.5, current_time: 50, duration: 100 },
            }),
        });
    });
    try {
        // Set _duration by playing first
        await env.clickBtn('play-pause');
        fetchCalls.length = 0;
        // Click at 50% of timeline
        await env.clickTimeline(0.5);
        const seekCall = fetchCalls.find(c => c.url === '/api/game/replay/seek');
        assert(seekCall !== undefined, 'Timeline click sends /api/game/replay/seek');
        const body = JSON.parse(seekCall.opts.body);
        assert(body.time === 50, 'Timeline click at 50% of 100s seeks to 50, got ' + body.time);
    } catch (e) { assert(false, 'timeline click seek: ' + e.message); }
    env.cleanup();
})();

await (async function testTimelineClickClampsToRange() {
    const fetchCalls = [];
    const env = createMountedEnv(function(url, opts) {
        fetchCalls.push({ url, opts });
        if (url === '/api/game/replay/play') {
            return Promise.resolve({
                ok: true,
                json: () => Promise.resolve({
                    playing: true, speed: 1, progress: 0, current_time: 0, duration: 80
                }),
            });
        }
        return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    });
    try {
        await env.clickBtn('play-pause');
        fetchCalls.length = 0;
        // Click at 100% (far right)
        await env.clickTimeline(1.0);
        const seekCall = fetchCalls.find(c => c.url === '/api/game/replay/seek');
        assert(seekCall !== undefined, 'Timeline click at end sends seek');
        const body = JSON.parse(seekCall.opts.body);
        assert(body.time === 80, 'Timeline click at 100% of 80s seeks to 80, got ' + body.time);
    } catch (e) { assert(false, 'timeline click clamp: ' + e.message); }
    env.cleanup();
})();

await (async function testTimelineClickAtZero() {
    const fetchCalls = [];
    const env = createMountedEnv(function(url, opts) {
        fetchCalls.push({ url, opts });
        if (url === '/api/game/replay/play') {
            return Promise.resolve({
                ok: true,
                json: () => Promise.resolve({
                    playing: true, speed: 1, progress: 0, current_time: 0, duration: 60
                }),
            });
        }
        return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    });
    try {
        await env.clickBtn('play-pause');
        fetchCalls.length = 0;
        // Click at 0% (far left)
        await env.clickTimeline(0.0);
        const seekCall = fetchCalls.find(c => c.url === '/api/game/replay/seek');
        assert(seekCall !== undefined, 'Timeline click at start sends seek');
        const body = JSON.parse(seekCall.opts.body);
        assert(body.time === 0, 'Timeline click at 0% seeks to 0, got ' + body.time);
    } catch (e) { assert(false, 'timeline click zero: ' + e.message); }
    env.cleanup();
})();

await (async function testTimelineClickEntersReplayMode() {
    const fetchCalls = [];
    const env = createMountedEnv(function(url, opts) {
        fetchCalls.push({ url });
        return Promise.resolve({
            ok: true,
            json: () => Promise.resolve({
                playing: false, speed: 1, progress: 0, current_time: 0, duration: 60,
            }),
        });
    });
    try {
        await env.clickTimeline(0.5);
        const replayLoad = fetchCalls.find(c => c.url === '/api/game/replay');
        assert(replayLoad !== undefined, 'Timeline click auto-enters replay mode');
    } catch (e) { assert(false, 'timeline click enters replay: ' + e.message); }
    env.cleanup();
})();

// ============================================================
// 20. Time display and progress bar updates
// ============================================================

console.log('\n--- Time display and progress bar ---');

await (async function testTimeDisplayUpdatesAfterApplyState() {
    const env = createMountedEnv(function(url) {
        if (url === '/api/game/replay/play') {
            return Promise.resolve({
                ok: true,
                json: () => Promise.resolve({
                    playing: true, speed: 1, progress: 0.75, current_time: 45, duration: 60
                }),
            });
        }
        return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    });
    try {
        await env.clickBtn('play-pause');
        const timeBind = env.getBind('time');
        assert(timeBind.textContent === '0:45 / 1:00', 'Time display shows 0:45 / 1:00, got: ' + timeBind.textContent);
    } catch (e) { assert(false, 'time display after applyState: ' + e.message); }
    env.cleanup();
})();

await (async function testTimelineFillUpdatesWidth() {
    const env = createMountedEnv(function(url) {
        if (url === '/api/game/replay/play') {
            return Promise.resolve({
                ok: true,
                json: () => Promise.resolve({
                    playing: true, speed: 1, progress: 0.333, current_time: 20, duration: 60
                }),
            });
        }
        return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    });
    try {
        await env.clickBtn('play-pause');
        const fill = env.getElement('timeline-fill');
        assert(fill.style.width === '33.3%', 'Timeline fill width is 33.3%, got: ' + fill.style.width);
    } catch (e) { assert(false, 'timeline fill width: ' + e.message); }
    env.cleanup();
})();

await (async function testPlayheadPositionUpdates() {
    const env = createMountedEnv(function(url) {
        if (url === '/api/game/replay/play') {
            return Promise.resolve({
                ok: true,
                json: () => Promise.resolve({
                    playing: true, speed: 1, progress: 0.6, current_time: 36, duration: 60
                }),
            });
        }
        return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    });
    try {
        await env.clickBtn('play-pause');
        const playhead = env.getElement('playhead');
        assert(playhead.style.left === '60.0%', 'Playhead left is 60.0%, got: ' + playhead.style.left);
    } catch (e) { assert(false, 'playhead position: ' + e.message); }
    env.cleanup();
})();

// ============================================================
// 21. Mode badge toggling
// ============================================================

console.log('\n--- Mode badge toggling ---');

await (async function testModeBadgeChangesToReplay() {
    const env = createMountedEnv(function(url) {
        return Promise.resolve({
            ok: true,
            json: () => Promise.resolve({
                playing: true, speed: 1, progress: 0, current_time: 0, duration: 60
            }),
        });
    });
    try {
        await env.clickBtn('play-pause');
        const badge = env.getBind('mode');
        assert(badge.textContent === 'REPLAY', 'Mode badge shows REPLAY after entering replay mode, got: ' + badge.textContent);
        assert(badge._classList.has('replay-mode-badge--replay'), 'Badge has --replay class');
        assert(!badge._classList.has('replay-mode-badge--live'), 'Badge does not have --live class');
    } catch (e) { assert(false, 'mode badge replay: ' + e.message); }
    env.cleanup();
})();

await (async function testStoreReplayActiveSet() {
    const TritiumStore = vm.runInContext('TritiumStore', ctx);
    TritiumStore.set('replay.active', false); // reset
    const env = createMountedEnv(function(url) {
        return Promise.resolve({
            ok: true,
            json: () => Promise.resolve({
                playing: true, speed: 1, progress: 0, current_time: 0, duration: 60
            }),
        });
    });
    try {
        await env.clickBtn('play-pause');
        assert(TritiumStore.get('replay.active') === true, 'Store replay.active is true after entering replay mode');
    } catch (e) { assert(false, 'store replay.active: ' + e.message); }
    env.cleanup();
})();

// ============================================================
// 22. Error handling when API calls fail
// ============================================================

console.log('\n--- Error handling ---');

await (async function testPlayPauseHandlesNetworkError() {
    const env = createMountedEnv(function(url) {
        if (url === '/api/game/replay/play') {
            return Promise.reject(new Error('Network error'));
        }
        return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    });
    try {
        let threw = false;
        try {
            await env.clickBtn('play-pause');
        } catch (e) {
            threw = true;
        }
        assert(!threw, 'Play/pause does not throw on network error');
    } catch (e) { assert(false, 'play-pause network error: ' + e.message); }
    env.cleanup();
})();

await (async function testPlayPauseHandlesNonOkResponse() {
    const env = createMountedEnv(function(url) {
        if (url === '/api/game/replay/play') {
            return Promise.resolve({ ok: false, status: 500 });
        }
        return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    });
    try {
        let threw = false;
        try {
            await env.clickBtn('play-pause');
        } catch (e) {
            threw = true;
        }
        assert(!threw, 'Play/pause does not throw on 500 response');
    } catch (e) { assert(false, 'play-pause 500 error: ' + e.message); }
    env.cleanup();
})();

await (async function testStepForwardHandlesNetworkError() {
    const env = createMountedEnv(function(url) {
        if (url === '/api/game/replay/step-forward') {
            return Promise.reject(new Error('Connection refused'));
        }
        return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    });
    try {
        let threw = false;
        try { await env.clickBtn('step-forward'); } catch (e) { threw = true; }
        assert(!threw, 'Step forward does not throw on network error');
    } catch (e) { assert(false, 'step-forward error handling: ' + e.message); }
    env.cleanup();
})();

await (async function testStepBackwardHandlesNetworkError() {
    const env = createMountedEnv(function(url) {
        if (url === '/api/game/replay/step-backward') {
            return Promise.reject(new Error('Connection refused'));
        }
        return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    });
    try {
        let threw = false;
        try { await env.clickBtn('step-back'); } catch (e) { threw = true; }
        assert(!threw, 'Step backward does not throw on network error');
    } catch (e) { assert(false, 'step-backward error handling: ' + e.message); }
    env.cleanup();
})();

await (async function testRewindHandlesNetworkError() {
    const env = createMountedEnv(function(url) {
        if (url === '/api/game/replay/stop') {
            return Promise.reject(new Error('Network error'));
        }
        return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    });
    try {
        let threw = false;
        try { await env.clickBtn('rewind'); } catch (e) { threw = true; }
        assert(!threw, 'Rewind does not throw on network error');
    } catch (e) { assert(false, 'rewind error handling: ' + e.message); }
    env.cleanup();
})();

await (async function testJumpEndHandlesNetworkError() {
    const env = createMountedEnv(function(url) {
        if (url === '/api/game/replay/seek') {
            return Promise.reject(new Error('Network error'));
        }
        return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    });
    try {
        let threw = false;
        try { await env.clickBtn('jump-end'); } catch (e) { threw = true; }
        assert(!threw, 'Jump-end does not throw on network error');
    } catch (e) { assert(false, 'jump-end error handling: ' + e.message); }
    env.cleanup();
})();

await (async function testSpeedChangeHandlesNetworkError() {
    const env = createMountedEnv(function(url) {
        if (url === '/api/game/replay/speed') {
            return Promise.reject(new Error('Network error'));
        }
        return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    });
    try {
        let threw = false;
        try { await env.clickSpeed(2); } catch (e) { threw = true; }
        assert(!threw, 'Speed change does not throw on network error');
    } catch (e) { assert(false, 'speed error handling: ' + e.message); }
    env.cleanup();
})();

await (async function testTimelineSeekHandlesNetworkError() {
    const env = createMountedEnv(function(url) {
        if (url === '/api/game/replay/seek') {
            return Promise.reject(new Error('Network error'));
        }
        return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    });
    try {
        let threw = false;
        try { await env.clickTimeline(0.5); } catch (e) { threw = true; }
        assert(!threw, 'Timeline seek does not throw on network error');
    } catch (e) { assert(false, 'timeline seek error handling: ' + e.message); }
    env.cleanup();
})();

await (async function testPollStateHandlesNetworkError() {
    let pollFetchCount = 0;
    const env = createMountedEnv(function(url) {
        if (url === '/api/game/replay/frame') {
            pollFetchCount++;
            return Promise.reject(new Error('Timeout'));
        }
        return Promise.resolve({
            ok: true,
            json: () => Promise.resolve({
                playing: true, speed: 1, progress: 0, current_time: 0, duration: 60
            }),
        });
    });
    try {
        await env.clickBtn('play-pause');
        // Simulate poll firing
        const pollInterval = env.intervals.find(i => i.ms === 250 && !i.cleared);
        let threw = false;
        try {
            if (pollInterval) {
                pollInterval.fn();
                await new Promise(r => setTimeout(r, 50));
            }
        } catch (e) { threw = true; }
        assert(!threw, 'pollState does not throw on network error');
        assert(pollFetchCount > 0, 'pollState attempted fetch despite error');
    } catch (e) { assert(false, 'poll state error handling: ' + e.message); }
    env.cleanup();
})();

await (async function testPollStateHandlesNonOkResponse() {
    const env = createMountedEnv(function(url) {
        if (url === '/api/game/replay/frame') {
            return Promise.resolve({ ok: false, status: 404 });
        }
        return Promise.resolve({
            ok: true,
            json: () => Promise.resolve({
                playing: true, speed: 1, progress: 0, current_time: 0, duration: 60
            }),
        });
    });
    try {
        await env.clickBtn('play-pause');
        const pollInterval = env.intervals.find(i => i.ms === 250 && !i.cleared);
        let threw = false;
        try {
            if (pollInterval) {
                pollInterval.fn();
                await new Promise(r => setTimeout(r, 50));
            }
        } catch (e) { threw = true; }
        assert(!threw, 'pollState handles non-ok response gracefully');
    } catch (e) { assert(false, 'poll state 404 handling: ' + e.message); }
    env.cleanup();
})();

// ============================================================
// 23. applyFrameToStore behavior
// ============================================================

console.log('\n--- applyFrameToStore behavior ---');

await (async function testApplyFrameUpdatesUnits() {
    // We need to invoke applyFrameToStore through the poll path.
    // When pollState gets a response with frame data and _replayMode is true,
    // it calls applyFrameToStore.
    const TritiumStore = vm.runInContext('TritiumStore', ctx);
    TritiumStore.units.clear();

    const env = createMountedEnv(function(url) {
        if (url === '/api/game/replay/frame') {
            return Promise.resolve({
                ok: true,
                json: () => Promise.resolve({
                    state: { playing: true, speed: 1, progress: 0.5, current_time: 30, duration: 60 },
                    frame: {
                        targets: [
                            { target_id: 'turret-1', name: 'Turret 1', asset_type: 'turret', alliance: 'friendly', position: { x: 10, y: 20 }, heading: 90, health: 100, max_health: 100, status: 'active' },
                            { target_id: 'hostile-1', name: 'Hostile 1', asset_type: 'person', alliance: 'hostile', position: { x: 50, y: 60 }, heading: 180, health: 80, max_health: 100, status: 'active' },
                        ],
                        timestamp: 1000030,
                    },
                }),
            });
        }
        return Promise.resolve({
            ok: true,
            json: () => Promise.resolve({
                playing: true, speed: 1, progress: 0, current_time: 0, duration: 60
            }),
        });
    });
    try {
        await env.clickBtn('play-pause'); // enter replay mode
        const pollInterval = env.intervals.find(i => i.ms === 250 && !i.cleared);
        if (pollInterval) {
            pollInterval.fn(); // fire-and-forget like the real setInterval
            // Wait for the inner pollState() async work to settle
            await new Promise(r => setTimeout(r, 50));
        }

        const turret = TritiumStore.units.get('turret-1');
        assert(turret !== undefined, 'applyFrameToStore adds turret-1 to store');
        assert(turret.name === 'Turret 1', 'turret-1 has correct name');
        assert(turret.health === 100, 'turret-1 has health 100');

        const hostile = TritiumStore.units.get('hostile-1');
        assert(hostile !== undefined, 'applyFrameToStore adds hostile-1 to store');
        assert(hostile.alliance === 'hostile', 'hostile-1 has correct alliance');
    } catch (e) { assert(false, 'applyFrameToStore units: ' + e.message); }
    env.cleanup();
})();

await (async function testApplyFrameMarksAbsentUnitsEliminated() {
    const TritiumStore = vm.runInContext('TritiumStore', ctx);
    TritiumStore.units.clear();
    // Pre-populate a unit that will not be in the frame
    TritiumStore.updateUnit('old-unit', { name: 'Old Unit', status: 'active', health: 50 });

    const env = createMountedEnv(function(url) {
        if (url === '/api/game/replay/frame') {
            return Promise.resolve({
                ok: true,
                json: () => Promise.resolve({
                    state: { playing: true, speed: 1, progress: 0.5, current_time: 30, duration: 60 },
                    frame: {
                        targets: [
                            { target_id: 'turret-1', name: 'Turret 1', asset_type: 'turret', alliance: 'friendly', position: { x: 10, y: 20 }, heading: 90, health: 100, max_health: 100, status: 'active' },
                        ],
                        timestamp: 1000030,
                    },
                }),
            });
        }
        return Promise.resolve({
            ok: true,
            json: () => Promise.resolve({
                playing: true, speed: 1, progress: 0, current_time: 0, duration: 60
            }),
        });
    });
    try {
        await env.clickBtn('play-pause');
        const pollInterval = env.intervals.find(i => i.ms === 250 && !i.cleared);
        if (pollInterval) {
            pollInterval.fn();
            await new Promise(r => setTimeout(r, 50));
        }

        const oldUnit = TritiumStore.units.get('old-unit');
        assert(oldUnit !== undefined, 'old-unit still in store (not removed)');
        assert(oldUnit.status === 'eliminated', 'old-unit marked eliminated, got: ' + oldUnit.status);
        assert(oldUnit.health === 0, 'old-unit health set to 0');
    } catch (e) { assert(false, 'applyFrame marks absent eliminated: ' + e.message); }
    env.cleanup();
})();

// ============================================================
// 24. Game phase subscription (victory/defeat triggers reload)
// ============================================================

console.log('\n--- Game phase subscription ---');

await (async function testVictoryPhaseTriggersFetch() {
    const fetchCalls = [];
    const env = createMountedEnv(function(url, opts) {
        fetchCalls.push({ url });
        return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    });
    try {
        const TritiumStore = vm.runInContext('TritiumStore', ctx);
        // Reset phase first (set() no-ops if value unchanged)
        TritiumStore.set('game.phase', 'idle');
        fetchCalls.length = 0;
        // Trigger victory phase -- should fire loadReplayData
        TritiumStore.set('game.phase', 'victory');
        // Give it a tick
        await new Promise(r => setTimeout(r, 10));
        const replayLoad = fetchCalls.find(c => c.url === '/api/game/replay');
        assert(replayLoad !== undefined, 'Victory phase triggers loadReplayData fetch');
    } catch (e) { assert(false, 'victory phase fetch: ' + e.message); }
    env.cleanup();
})();

await (async function testDefeatPhaseTriggersFetch() {
    const fetchCalls = [];
    const env = createMountedEnv(function(url, opts) {
        fetchCalls.push({ url });
        return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    });
    try {
        const TritiumStore = vm.runInContext('TritiumStore', ctx);
        // Reset so we can trigger again (set() no-ops if value unchanged)
        TritiumStore.set('game.phase', 'idle');
        fetchCalls.length = 0;
        TritiumStore.set('game.phase', 'defeat');
        await new Promise(r => setTimeout(r, 10));
        const replayLoad = fetchCalls.find(c => c.url === '/api/game/replay');
        assert(replayLoad !== undefined, 'Defeat phase triggers loadReplayData fetch');
    } catch (e) { assert(false, 'defeat phase fetch: ' + e.message); }
    env.cleanup();
})();

await (async function testNonEndPhaseDoesNotTriggerFetch() {
    const fetchCalls = [];
    const env = createMountedEnv(function(url, opts) {
        fetchCalls.push({ url });
        return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    });
    try {
        const TritiumStore = vm.runInContext('TritiumStore', ctx);
        TritiumStore.set('game.phase', 'idle'); // reset
        fetchCalls.length = 0;
        TritiumStore.set('game.phase', 'active');
        await new Promise(r => setTimeout(r, 10));
        const replayLoad = fetchCalls.find(c => c.url === '/api/game/replay');
        assert(replayLoad === undefined, 'Active phase does not trigger loadReplayData');
    } catch (e) { assert(false, 'active phase no fetch: ' + e.message); }
    env.cleanup();
})();

// ============================================================
// 25. Multiple rapid operations
// ============================================================

console.log('\n--- Rapid operations ---');

await (async function testMultipleSpeedClicksApplyLastSpeed() {
    let lastSpeed = null;
    const env = createMountedEnv(function(url, opts) {
        if (url === '/api/game/replay/speed') {
            const body = JSON.parse(opts.body);
            lastSpeed = body.speed;
            return Promise.resolve({
                ok: true,
                json: () => Promise.resolve({
                    playing: true, speed: body.speed, progress: 0, current_time: 0, duration: 60
                }),
            });
        }
        return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    });
    try {
        await env.clickSpeed(0.5);
        await env.clickSpeed(2);
        await env.clickSpeed(4);
        assert(lastSpeed === 4, 'After rapid speed clicks, last speed is 4, got ' + lastSpeed);
        const btn4 = env.speedBtns.find(b => b._dataSpeed === '4');
        assert(btn4._classList.has('replay-speed-btn--active'), '4x button has active class after rapid clicks');
    } catch (e) { assert(false, 'rapid speed clicks: ' + e.message); }
    env.cleanup();
})();

await (async function testPlayPausePlayCycle() {
    let stateFlips = 0;
    const env = createMountedEnv(function(url) {
        if (url === '/api/game/replay/play') {
            stateFlips++;
            return Promise.resolve({
                ok: true,
                json: () => Promise.resolve({
                    playing: true, speed: 1, progress: 0, current_time: 0, duration: 60
                }),
            });
        }
        if (url === '/api/game/replay/pause') {
            stateFlips++;
            return Promise.resolve({
                ok: true,
                json: () => Promise.resolve({
                    playing: false, speed: 1, progress: 0.5, current_time: 30, duration: 60
                }),
            });
        }
        return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    });
    try {
        const playBtn = env.getBtn('play-pause');
        await env.clickBtn('play-pause'); // play
        assert(playBtn.textContent === 'PAUSE', 'Cycle 1: PAUSE after play');
        await env.clickBtn('play-pause'); // pause
        assert(playBtn.textContent === 'PLAY', 'Cycle 2: PLAY after pause');
        await env.clickBtn('play-pause'); // play again
        assert(playBtn.textContent === 'PAUSE', 'Cycle 3: PAUSE after play again');
        assert(stateFlips === 3, 'Three play/pause API calls made, got ' + stateFlips);
    } catch (e) { assert(false, 'play-pause-play cycle: ' + e.message); }
    env.cleanup();
})();

// ============================================================
// 26. formatTime edge cases
// ============================================================

console.log('\n--- formatTime edge cases ---');

(function testFormatTimeFractionalSeconds() {
    assert(ReplayHelpers.formatTime(65.7) === '1:05', 'formatTime(65.7) => "1:05" (truncates fractional)');
})();

(function testFormatTimeLargeValue() {
    assert(ReplayHelpers.formatTime(7200) === '120:00', 'formatTime(7200) => "120:00"');
})();

(function testFormatTimeOneSecond() {
    assert(ReplayHelpers.formatTime(1) === '0:01', 'formatTime(1) => "0:01"');
})();

(function testFormatTimeNineSeconds() {
    assert(ReplayHelpers.formatTime(9) === '0:09', 'formatTime(9) => "0:09" (zero-padded)');
})();

(function testFormatTimeTenSeconds() {
    assert(ReplayHelpers.formatTime(10) === '0:10', 'formatTime(10) => "0:10"');
})();

(function testFormatTimeNaN() {
    assert(ReplayHelpers.formatTime(NaN) === '0:00', 'formatTime(NaN) => "0:00"');
})();

// ============================================================
// 27. formatEventSummary edge cases
// ============================================================

console.log('\n--- formatEventSummary edge cases ---');

(function testFormatEventSummaryMissingData() {
    const evt = { event_type: 'target_eliminated', data: {} };
    assert(ReplayHelpers.formatEventSummary(evt) === '? eliminated', 'target_eliminated with empty data uses "?"');
})();

(function testFormatEventSummaryFallbackToId() {
    const evt = { event_type: 'projectile_fired', data: { source_id: 'turret-42' } };
    assert(ReplayHelpers.formatEventSummary(evt) === 'turret-42 fired', 'projectile_fired falls back to source_id');
})();

(function testFormatEventSummaryHitFallbackToId() {
    const evt = { event_type: 'projectile_hit', data: { target_id: 'hostile-7' } };
    assert(ReplayHelpers.formatEventSummary(evt) === 'Hit on hostile-7', 'projectile_hit falls back to target_id');
})();

(function testFormatEventSummaryUnknownEventType() {
    const evt = { event_type: 'custom_event', data: {} };
    assert(ReplayHelpers.formatEventSummary(evt) === 'CUSTOM EVENT', 'Unknown event type gets formatted with formatEventType');
})();

(function testFormatEventSummaryMissingEventType() {
    const evt = { data: {} };
    assert(ReplayHelpers.formatEventSummary(evt) === '', 'Missing event_type returns empty string');
})();

(function testFormatEventSummaryNoData() {
    const evt = { event_type: 'target_eliminated' };
    assert(ReplayHelpers.formatEventSummary(evt) === '? eliminated', 'target_eliminated with no data uses "?"');
})();

(function testFormatEventSummaryGameOverMissingResult() {
    const evt = { event_type: 'game_over', data: {} };
    assert(ReplayHelpers.formatEventSummary(evt) === 'Game over: ?', 'game_over with no result shows "?"');
})();

(function testFormatEventSummaryWaveStartMissingNumber() {
    const evt = { event_type: 'wave_start', data: {} };
    assert(ReplayHelpers.formatEventSummary(evt) === 'Wave ? started', 'wave_start with no wave_number shows "?"');
})();

// ============================================================
// 28. Replay data loading
// ============================================================

console.log('\n--- Replay data loading ---');

await (async function testLoadReplayDataFetchesBothEndpoints() {
    const fetchCalls = [];
    const env = createMountedEnv(function(url, opts) {
        fetchCalls.push({ url });
        if (url === '/api/game/replay') {
            return Promise.resolve({
                ok: true,
                json: () => Promise.resolve({
                    metadata: { start_time: 1000 },
                    frames: [{ targets: [], timestamp: 1000 }],
                }),
            });
        }
        if (url === '/api/game/replay/timeline') {
            return Promise.resolve({
                ok: true,
                json: () => Promise.resolve([
                    { event_type: 'wave_start', timestamp: 1000, data: { wave_number: 1 } },
                ]),
            });
        }
        return Promise.resolve({
            ok: true,
            json: () => Promise.resolve({
                playing: true, speed: 1, progress: 0, current_time: 0, duration: 60
            }),
        });
    });
    try {
        await env.clickBtn('play-pause'); // triggers enterReplayMode -> loadReplayData
        const replayCall = fetchCalls.find(c => c.url === '/api/game/replay');
        const timelineCall = fetchCalls.find(c => c.url === '/api/game/replay/timeline');
        assert(replayCall !== undefined, 'loadReplayData fetches /api/game/replay');
        assert(timelineCall !== undefined, 'loadReplayData fetches /api/game/replay/timeline');
    } catch (e) { assert(false, 'loadReplayData endpoints: ' + e.message); }
    env.cleanup();
})();

await (async function testLoadReplayDataHandlesReplayFailure() {
    const env = createMountedEnv(function(url) {
        if (url === '/api/game/replay') {
            return Promise.reject(new Error('Server down'));
        }
        if (url === '/api/game/replay/timeline') {
            return Promise.resolve({ ok: true, json: () => Promise.resolve([]) });
        }
        return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    }, { overrideReplayEndpoints: true });
    try {
        let threw = false;
        try { await env.clickBtn('play-pause'); } catch (e) { threw = true; }
        assert(!threw, 'loadReplayData does not throw when /api/game/replay fails');
    } catch (e) { assert(false, 'loadReplayData error handling: ' + e.message); }
    env.cleanup();
})();

// ============================================================
// 29. Cleanup and unsub behavior
// ============================================================

console.log('\n--- Cleanup and unsub ---');

(function testMountRegistersCleanupUnsub() {
    const bodyEl = createMockElement('div');
    const panel = {
        def: ReplayPanelDef,
        w: 420, h: 260, x: 0, y: 0,
        manager: {
            container: createMockElement('div'),
            getPanel: () => null,
        },
        _unsubs: [],
        _applyTransform() {},
    };
    panel.manager.container.clientHeight = 800;
    ReplayPanelDef.mount(bodyEl, panel);
    // Should have: 1 store.on subscription + 1 cleanup function (poll timer)
    assert(panel._unsubs.length === 2, 'mount registers 2 unsubs (store + cleanup), got ' + panel._unsubs.length);
    const hasFn = panel._unsubs.some(u => typeof u === 'function');
    assert(hasFn, 'At least one unsub is a cleanup function');
})();

} // end runAsyncTests

// ============================================================
// Summary
// ============================================================

runAsyncTests().then(() => {
    console.log('\n' + '='.repeat(40));
    console.log(`Results: ${passed} passed, ${failed} failed`);
    console.log('='.repeat(40));
    process.exit(failed > 0 ? 1 : 0);
}).catch(e => {
    console.error('Test runner error:', e);
    process.exit(1);
});
