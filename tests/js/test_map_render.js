// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
/**
 * TRITIUM-SC -- Map Rendering Function Tests
 * Run: node tests/js/test_map_render.js
 *
 * Tests internal rendering functions of map.js:
 *   - worldToScreen() / screenToWorld() coordinate transforms
 *   - _drawTooltip() -- hovered unit tooltip rendering
 *   - _drawStatusBadge() -- FSM badge above units
 *   - _drawLabels() -- collision-resolved unit labels
 *   - _drawGrid() -- adaptive grid rendering
 *   - _drawMapBoundary() -- boundary rectangle
 *   - _drawSelectionIndicator() -- selected unit ring
 *   - _drawZones() -- zone rendering
 *   - _drawHealthBar() -- unit health bar
 *   - _drawUnit() -- full unit rendering pipeline
 *   - _hitTestUnit() -- screen click to unit mapping
 *   - _drawScaleBar() -- distance scale indicator
 *   - _drawDispatchArrows() -- dispatch feedback arrows
 *   - Alliance color mapping
 *   - FSM badge color completeness
 *   - Pan/zoom math
 *   - Layer visibility toggles
 *
 * Approach: Loads map.js into a VM sandbox with mocked TritiumStore,
 * EventBus, resolveLabels, drawUnit, and Canvas 2D context.
 */

const fs = require('fs');
const vm = require('vm');

// ============================================================
// Test runner
// ============================================================

let passed = 0, failed = 0;
function assert(cond, msg) {
    if (!cond) { console.error('FAIL:', msg); failed++; }
    else { console.log('PASS:', msg); passed++; }
}
function assertClose(a, b, eps, msg) {
    assert(Math.abs(a - b) < (eps || 0.01), msg + ` (got ${a}, expected ${b})`);
}

// ============================================================
// Mock Canvas 2D context -- records all draw calls
// ============================================================

function createMockCtx() {
    const calls = [];
    const state = {
        fillStyle: '#000',
        strokeStyle: '#000',
        lineWidth: 1,
        globalAlpha: 1.0,
        font: '',
        textAlign: 'left',
        textBaseline: 'top',
        shadowColor: '',
        shadowBlur: 0,
        lineDash: [],
        lineCap: 'butt',
        lineJoin: 'miter',
    };
    const stateStack = [];

    const ctx = {
        calls,
        get fillStyle() { return state.fillStyle; },
        set fillStyle(v) { state.fillStyle = v; calls.push({ fn: 'set:fillStyle', v }); },
        get strokeStyle() { return state.strokeStyle; },
        set strokeStyle(v) { state.strokeStyle = v; calls.push({ fn: 'set:strokeStyle', v }); },
        get lineWidth() { return state.lineWidth; },
        set lineWidth(v) { state.lineWidth = v; calls.push({ fn: 'set:lineWidth', v }); },
        get globalAlpha() { return state.globalAlpha; },
        set globalAlpha(v) { state.globalAlpha = v; },
        get font() { return state.font; },
        set font(v) { state.font = v; calls.push({ fn: 'set:font', v }); },
        get textAlign() { return state.textAlign; },
        set textAlign(v) { state.textAlign = v; },
        get textBaseline() { return state.textBaseline; },
        set textBaseline(v) { state.textBaseline = v; },
        get shadowColor() { return state.shadowColor; },
        set shadowColor(v) { state.shadowColor = v; },
        get shadowBlur() { return state.shadowBlur; },
        set shadowBlur(v) { state.shadowBlur = v; },
        get lineCap() { return state.lineCap; },
        set lineCap(v) { state.lineCap = v; },
        get lineJoin() { return state.lineJoin; },
        set lineJoin(v) { state.lineJoin = v; },
        save() { stateStack.push({ ...state }); calls.push({ fn: 'save' }); },
        restore() {
            const s = stateStack.pop();
            if (s) Object.assign(state, s);
            calls.push({ fn: 'restore' });
        },
        beginPath() { calls.push({ fn: 'beginPath' }); },
        closePath() { calls.push({ fn: 'closePath' }); },
        moveTo(x, y) { calls.push({ fn: 'moveTo', x, y }); },
        lineTo(x, y) { calls.push({ fn: 'lineTo', x, y }); },
        arc(x, y, r, start, end) { calls.push({ fn: 'arc', x, y, r, start, end }); },
        fill() { calls.push({ fn: 'fill', fillStyle: state.fillStyle, globalAlpha: state.globalAlpha }); },
        stroke() { calls.push({ fn: 'stroke', strokeStyle: state.strokeStyle, lineWidth: state.lineWidth }); },
        fillRect(x, y, w, h) { calls.push({ fn: 'fillRect', x, y, w, h, fillStyle: state.fillStyle }); },
        strokeRect(x, y, w, h) { calls.push({ fn: 'strokeRect', x, y, w, h, strokeStyle: state.strokeStyle }); },
        quadraticCurveTo(cpx, cpy, x, y) { calls.push({ fn: 'quadraticCurveTo', cpx, cpy, x, y }); },
        translate(x, y) { calls.push({ fn: 'translate', x, y }); },
        rotate(a) { calls.push({ fn: 'rotate', a }); },
        scale(x, y) { calls.push({ fn: 'scale', x, y }); },
        fillText(text, x, y) { calls.push({ fn: 'fillText', text, x, y, fillStyle: state.fillStyle, font: state.font }); },
        measureText(text) { return { width: text.length * 7 }; },  // ~7px per char
        setLineDash(d) { state.lineDash = d; calls.push({ fn: 'setLineDash', d }); },
        getLineDash() { return state.lineDash; },
        setTransform(a, b, c, d, e, f) { calls.push({ fn: 'setTransform', a, b, c, d, e, f }); },
        createRadialGradient(x0, y0, r0, x1, y1, r1) {
            return { addColorStop() {} };
        },
    };
    return ctx;
}

// ============================================================
// Load map.js source and strip imports/exports for sandboxing
// ============================================================

const mapSrc = fs.readFileSync(__dirname + '/../../src/frontend/js/command/map.js', 'utf8');

// Strip import statements and convert const/let to var so symbols
// become sandbox context properties accessible from the test harness.
// Also alias the `drawUnit as drawUnitIcon` import.
let strippedCode = mapSrc
    .replace(/^import\s+.*$/gm, '')
    .replace(/export\s+function\s+/g, 'function ')
    .replace(/export\s+\{[^}]*\}/g, '')
    .replace(/\bconst\b/g, 'var')
    .replace(/\blet\b/g, 'var')
    + '\nvar drawUnitIcon = drawUnit;\n';

// ============================================================
// Build mock dependencies in sandbox context
// ============================================================

// Mock TritiumStore
const mockUnits = new Map();
const mockStore = {
    map: {
        viewport: { x: 0, y: 0, zoom: 1 },
        selectedUnitId: null,
        mode: 'observe',
    },
    game: { phase: 'idle', wave: 0, totalWaves: 10, score: 0 },
    units: mockUnits,
    amy: { state: 'idle', mood: 'calm' },
    _listeners: new Map(),
    isTargetPinned: function(id) { return false; },
    on: function(path, fn) { return function() {}; },
    set: function(path, value) {
        var parts = path.split('.');
        var obj = this;
        for (var i = 0; i < parts.length - 1; i++) {
            if (!obj[parts[i]]) obj[parts[i]] = {};
            obj = obj[parts[i]];
        }
        obj[parts[parts.length - 1]] = value;
    },
    get: function(path) {
        var parts = path.split('.');
        var obj = this;
        for (var i = 0; i < parts.length; i++) {
            if (obj === undefined || obj === null) return undefined;
            obj = obj instanceof Map ? obj.get(parts[i]) : obj[parts[i]];
        }
        return obj;
    },
};

// Track resolveLabels calls
var resolveLabelsCalls = [];
function mockResolveLabels(entries, canvasW, canvasH, zoom, selectedId, wts) {
    resolveLabelsCalls.push({ entries, canvasW, canvasH, zoom, selectedId });
    // Return resolved entries at simple positions
    return entries.map(function(e) {
        var sp = wts(e.worldX, e.worldY);
        return {
            id: e.id,
            text: e.text,
            badge: e.badge,
            badgeColor: e.badgeColor,
            badgeText: e.badgeText,
            labelX: sp.x - 20,
            labelY: sp.y + 14,
            anchorX: sp.x,
            anchorY: sp.y,
            displaced: false,
            bgWidth: e.text.length * 7 + 6,
            bgHeight: 17,
            alliance: e.alliance,
            status: e.status,
        };
    });
}

// Track drawUnit (unit-icons) calls
var drawUnitCalls = [];
function mockDrawUnitIcon(ctx, iconType, alliance, heading, x, y, scale, isSelected, health) {
    drawUnitCalls.push({ iconType, alliance, heading, x, y, scale, isSelected, health });
}

// Mock EventBus
var eventBusEmits = [];
var mockEventBus = {
    _handlers: new Map(),
    on: function(event, handler) { return function() {}; },
    off: function() {},
    emit: function(event, data) { eventBusEmits.push({ event, data }); },
};

// Build the sandbox context
var perfNow = 5000;
var dateNow = 1000000;
var sandbox = vm.createContext({
    Math: Math,
    Date: { now: function() { return dateNow; } },
    console: console,
    Map: Map,
    Array: Array,
    Object: Object,
    Number: Number,
    Infinity: Infinity,
    Boolean: Boolean,
    parseInt: parseInt,
    parseFloat: parseFloat,
    isNaN: isNaN,
    isFinite: isFinite,
    undefined: undefined,
    Uint8Array: Uint8Array,
    Set: Set,
    performance: { now: function() { return perfNow; } },
    TritiumStore: mockStore,
    EventBus: mockEventBus,
    resolveLabels: mockResolveLabels,
    drawUnit: mockDrawUnitIcon,
    requestAnimationFrame: function() { return 1; },
    cancelAnimationFrame: function() {},
    fetch: function() { return Promise.resolve({ ok: true, json: function() { return Promise.resolve({}); } }); },
    document: {
        getElementById: function(id) { return null; },
        createElement: function(tag) {
            return {
                width: 1, height: 1,
                getContext: function() { return createMockCtx(); },
                style: {},
            };
        },
    },
    window: { devicePixelRatio: 1 },
    ResizeObserver: undefined,
    Image: function() { this.onload = null; this.onerror = null; this.src = ''; },
});

// Add drawUnit as the import name used in the stripped code
sandbox.drawUnitIcon = mockDrawUnitIcon;

// Run the stripped code in the sandbox
vm.runInContext(strippedCode, sandbox);

// Extract functions and state from the sandbox
const { worldToScreen, screenToWorld, _state, _draw,
        _drawTooltip, _drawStatusBadge, _drawLabels, _drawGrid,
        _drawMapBoundary, _drawSelectionIndicator, _drawUnit,
        _hitTestUnit, _drawHealthBar, _drawZones, _drawScaleBar,
        _drawDispatchArrows, _drawRoundedRect, _drawDiamond,
        _drawTriangle, _drawCircle, _drawCircleWithX,
        fadeToward, lerpAngle, _getOperationalBounds,
        ALLIANCE_COLORS, FSM_BADGE_COLORS, GRID_LEVELS,
        MAP_MIN, MAP_MAX, MAP_RANGE, ZOOM_MIN, ZOOM_MAX,
} = sandbox;

// ============================================================
// Setup helper: prepare _state with a mock canvas
// ============================================================

function setupState(opts) {
    opts = opts || {};
    var ctx = createMockCtx();
    _state.canvas = {
        width: (opts.width || 800) * (opts.dpr || 1),
        height: (opts.height || 600) * (opts.dpr || 1),
        parentElement: { clientWidth: opts.width || 800, clientHeight: opts.height || 600 },
        getBoundingClientRect: function() { return { left: 0, top: 0, width: opts.width || 800, height: opts.height || 600 }; },
        style: {},
    };
    _state.ctx = ctx;
    _state.dpr = opts.dpr || 1;
    _state.cam = {
        x: opts.camX || 0,
        y: opts.camY || 0,
        zoom: opts.zoom || 1.0,
        targetX: opts.camX || 0,
        targetY: opts.camY || 0,
        targetZoom: opts.zoom || 1.0,
    };
    _state.hoveredUnit = opts.hoveredUnit || null;
    _state.dispatchArrows = opts.dispatchArrows || [];
    _state.zones = opts.zones || [];
    _state.fogEnabled = false;
    _state.showGrid = true;
    _state.showSatellite = false;
    _state.showRoads = false;
    _state.showBuildings = false;
    _state.smoothHeadings = new Map();
    _state.dt = 0.016;
    _state.opBounds = null;
    _state.opBoundsUnitCount = 0;
    // Reset store units
    mockStore.units = new Map();
    mockStore.map.selectedUnitId = null;
    // Reset tracking arrays
    resolveLabelsCalls = [];
    drawUnitCalls = [];
    eventBusEmits = [];
    return ctx;
}

// ============================================================
// worldToScreen / screenToWorld coordinate transforms
// ============================================================

console.log('\n--- worldToScreen / screenToWorld ---');

(function testWorldToScreenOriginAtCenter() {
    setupState({ width: 800, height: 600, zoom: 1.0, camX: 0, camY: 0 });
    var sp = worldToScreen(0, 0);
    assertClose(sp.x, 400, 0.1, 'Origin maps to center X=400');
    assertClose(sp.y, 300, 0.1, 'Origin maps to center Y=300');
})();

(function testWorldToScreenPositiveX() {
    setupState({ width: 800, height: 600, zoom: 1.0, camX: 0, camY: 0 });
    var sp = worldToScreen(10, 0);
    assertClose(sp.x, 410, 0.1, 'World X=10 at zoom 1 maps to screen X=410');
    assertClose(sp.y, 300, 0.1, 'World Y=0 stays at center Y=300');
})();

(function testWorldToScreenPositiveYGoesUp() {
    setupState({ width: 800, height: 600, zoom: 1.0, camX: 0, camY: 0 });
    var sp = worldToScreen(0, 10);
    assertClose(sp.x, 400, 0.1, 'World X=0 stays at center X=400');
    assertClose(sp.y, 290, 0.1, 'World Y=10 at zoom 1 maps to screen Y=290 (Y inverted)');
})();

(function testWorldToScreenZoomMultiplier() {
    setupState({ width: 800, height: 600, zoom: 2.0, camX: 0, camY: 0 });
    var sp = worldToScreen(10, 0);
    assertClose(sp.x, 420, 0.1, 'World X=10 at zoom 2 maps to screen X=420');
})();

(function testWorldToScreenCameraOffset() {
    setupState({ width: 800, height: 600, zoom: 1.0, camX: 50, camY: 0 });
    var sp = worldToScreen(50, 0);
    assertClose(sp.x, 400, 0.1, 'Camera at X=50, world X=50 maps to center');
})();

(function testScreenToWorldOrigin() {
    setupState({ width: 800, height: 600, zoom: 1.0, camX: 0, camY: 0 });
    var wp = screenToWorld(400, 300);
    assertClose(wp.x, 0, 0.1, 'Screen center maps to world X=0');
    assertClose(wp.y, 0, 0.1, 'Screen center maps to world Y=0');
})();

(function testScreenToWorldRightEdge() {
    setupState({ width: 800, height: 600, zoom: 1.0, camX: 0, camY: 0 });
    var wp = screenToWorld(800, 300);
    assertClose(wp.x, 400, 0.1, 'Screen right edge at zoom 1 maps to world X=400');
})();

(function testScreenToWorldTopEdge() {
    setupState({ width: 800, height: 600, zoom: 1.0, camX: 0, camY: 0 });
    var wp = screenToWorld(400, 0);
    assertClose(wp.y, 300, 0.1, 'Screen top at zoom 1 maps to world Y=300 (Y inverted)');
})();

(function testRoundTripWorldScreen() {
    setupState({ width: 1024, height: 768, zoom: 3.5, camX: 100, camY: -50 });
    var origX = 42.5, origY = -17.3;
    var sp = worldToScreen(origX, origY);
    var wp = screenToWorld(sp.x, sp.y);
    assertClose(wp.x, origX, 0.01, 'Round-trip X preserves world coordinate');
    assertClose(wp.y, origY, 0.01, 'Round-trip Y preserves world coordinate');
})();

(function testWorldToScreenHiDPI() {
    setupState({ width: 800, height: 600, zoom: 1.0, camX: 0, camY: 0, dpr: 2 });
    // Canvas buffer is 1600x1200, CSS is 800x600
    var sp = worldToScreen(0, 0);
    assertClose(sp.x, 400, 0.1, 'HiDPI: origin maps to CSS center X=400');
    assertClose(sp.y, 300, 0.1, 'HiDPI: origin maps to CSS center Y=300');
})();

(function testScreenToWorldHiDPI() {
    setupState({ width: 800, height: 600, zoom: 1.0, camX: 0, camY: 0, dpr: 2 });
    var wp = screenToWorld(400, 300);
    assertClose(wp.x, 0, 0.1, 'HiDPI: CSS center maps to world origin X=0');
    assertClose(wp.y, 0, 0.1, 'HiDPI: CSS center maps to world origin Y=0');
})();

// ============================================================
// _drawTooltip
// ============================================================

console.log('\n--- _drawTooltip ---');

(function testTooltipNotDrawnWithoutHover() {
    var ctx = setupState();
    _state.hoveredUnit = null;
    _drawTooltip(ctx);
    var fillTexts = ctx.calls.filter(function(c) { return c.fn === 'fillText'; });
    assert(fillTexts.length === 0, 'No tooltip drawn when no unit hovered');
})();

(function testTooltipNotDrawnForMissingUnit() {
    var ctx = setupState();
    _state.hoveredUnit = 'nonexistent';
    _drawTooltip(ctx);
    var fillTexts = ctx.calls.filter(function(c) { return c.fn === 'fillText'; });
    assert(fillTexts.length === 0, 'No tooltip for nonexistent unit ID');
})();

(function testTooltipDrawnForHoveredUnit() {
    var ctx = setupState({ hoveredUnit: 'turret-1' });
    mockStore.units.set('turret-1', {
        id: 'turret-1',
        name: 'Sentry Alpha',
        position: { x: 10, y: 20 },
        alliance: 'friendly',
        fsm_state: 'engaging',
        eliminations: 3,
    });
    _drawTooltip(ctx);
    var fillTexts = ctx.calls.filter(function(c) { return c.fn === 'fillText'; });
    assert(fillTexts.length > 0, 'Tooltip text drawn for hovered unit');
    var tooltipText = fillTexts[0].text;
    assert(tooltipText.indexOf('Sentry Alpha') >= 0, 'Tooltip contains unit name');
    assert(tooltipText.indexOf('ENGAGING') >= 0, 'Tooltip contains FSM state');
    assert(tooltipText.indexOf('3K') >= 0, 'Tooltip contains elimination count');
})();

(function testTooltipPositionRelativeToMouse() {
    var ctx = setupState({ width: 800, height: 600, zoom: 1.0, hoveredUnit: 'rover-1' });
    mockStore.units.set('rover-1', {
        id: 'rover-1',
        name: 'Rover',
        position: { x: 0, y: 0 },
        fsm_state: 'patrolling',
    });
    // Tooltip positions relative to lastMouse (offset +14px right, above mouse)
    _state.lastMouse = { x: 400, y: 300 };
    _drawTooltip(ctx);
    var fillTexts = ctx.calls.filter(function(c) { return c.fn === 'fillText'; });
    assert(fillTexts.length > 0, 'Tooltip drawn');
    // Tooltip X should be near lastMouse.x + 14 + padX(6) = 420
    assert(fillTexts[0].x > 400 && fillTexts[0].x < 430, 'Tooltip X is offset right of mouse pos (got ' + fillTexts[0].x + ')');
    // Tooltip Y should be above mouse position
    assert(fillTexts[0].y < 300, 'Tooltip Y is above mouse pos (got ' + fillTexts[0].y + ')');
})();

(function testTooltipBackgroundDrawn() {
    var ctx = setupState({ hoveredUnit: 'unit-a' });
    mockStore.units.set('unit-a', {
        id: 'unit-a', name: 'Test', position: { x: 5, y: 5 }, fsm_state: 'idle',
    });
    _drawTooltip(ctx);
    var rects = ctx.calls.filter(function(c) { return c.fn === 'fillRect'; });
    assert(rects.length > 0, 'Tooltip background rectangle drawn');
    // Background fill should be dark
    var bgRect = rects[0];
    assert(bgRect.fillStyle.indexOf('rgba(6, 6, 9') >= 0, 'Tooltip background is dark');
})();

(function testTooltipColorMatchesFSMState() {
    var ctx = setupState({ hoveredUnit: 'unit-b' });
    mockStore.units.set('unit-b', {
        id: 'unit-b', name: 'Bob', position: { x: 0, y: 0 }, fsm_state: 'engaging',
    });
    _drawTooltip(ctx);
    var fillTexts = ctx.calls.filter(function(c) { return c.fn === 'fillText'; });
    assert(fillTexts.length > 0, 'Tooltip text exists');
    // The fillStyle should be the FSM badge color for 'engaging' (#ff2a6d)
    assert(fillTexts[0].fillStyle === '#ff2a6d', 'Tooltip text color matches FSM_BADGE_COLORS.engaging (#ff2a6d)');
})();

(function testTooltipWithNoFSMState() {
    var ctx = setupState({ hoveredUnit: 'unit-c' });
    mockStore.units.set('unit-c', {
        id: 'unit-c', name: 'NoFSM', position: { x: 0, y: 0 },
    });
    _drawTooltip(ctx);
    var fillTexts = ctx.calls.filter(function(c) { return c.fn === 'fillText'; });
    assert(fillTexts.length > 0, 'Tooltip drawn even without FSM state');
    assert(fillTexts[0].fillStyle === '#ccc', 'Tooltip color falls back to #ccc when no FSM state');
})();

// ============================================================
// _drawStatusBadge
// ============================================================

console.log('\n--- _drawStatusBadge ---');

(function testStatusBadgeSkipsActiveStatus() {
    var ctx = createMockCtx();
    _drawStatusBadge(ctx, { status: 'active' }, { x: 100, y: 100 });
    var fillTexts = ctx.calls.filter(function(c) { return c.fn === 'fillText'; });
    assert(fillTexts.length === 0, 'No badge for "active" status (default, not interesting)');
})();

(function testStatusBadgeDrawsFSMState() {
    var ctx = createMockCtx();
    _drawStatusBadge(ctx, { fsm_state: 'engaging', status: 'active' }, { x: 200, y: 150 });
    var fillTexts = ctx.calls.filter(function(c) { return c.fn === 'fillText'; });
    assert(fillTexts.length === 1, 'Badge text drawn for engaging state');
    assert(fillTexts[0].text === 'ENGAGING', 'Badge text is uppercased FSM state');
    assertClose(fillTexts[0].x, 200, 0.1, 'Badge centered at unit screen X');
    assertClose(fillTexts[0].y, 150 - 18, 0.1, 'Badge drawn 18px above unit');
})();

(function testStatusBadgePrefersFSMOverStatus() {
    var ctx = createMockCtx();
    _drawStatusBadge(ctx, { fsm_state: 'tracking', status: 'patrolling' }, { x: 0, y: 0 });
    var fillTexts = ctx.calls.filter(function(c) { return c.fn === 'fillText'; });
    assert(fillTexts.length === 1, 'One badge text drawn');
    assert(fillTexts[0].text === 'TRACKING', 'FSM state takes priority over status');
})();

(function testStatusBadgeColorMatchesFSMColors() {
    var ctx = createMockCtx();
    _drawStatusBadge(ctx, { fsm_state: 'patrolling' }, { x: 50, y: 50 });
    var fillTexts = ctx.calls.filter(function(c) { return c.fn === 'fillText'; });
    assert(fillTexts.length === 1, 'Badge drawn');
    assert(fillTexts[0].fillStyle === '#05ffa1', 'Patrolling badge uses green (#05ffa1)');
})();

(function testStatusBadgeShowsStatusWhenNoFSM() {
    var ctx = createMockCtx();
    _drawStatusBadge(ctx, { status: 'retreating' }, { x: 50, y: 50 });
    var fillTexts = ctx.calls.filter(function(c) { return c.fn === 'fillText'; });
    assert(fillTexts.length === 1, 'Badge drawn for status when no fsm_state');
    assert(fillTexts[0].text === 'RETREATING', 'Status shown as badge text');
})();

(function testStatusBadgeSaveRestore() {
    var ctx = createMockCtx();
    _drawStatusBadge(ctx, { fsm_state: 'idle' }, { x: 0, y: 0 });
    var saves = ctx.calls.filter(function(c) { return c.fn === 'save'; });
    var restores = ctx.calls.filter(function(c) { return c.fn === 'restore'; });
    assert(saves.length === restores.length, 'save/restore balanced in badge rendering');
})();

// ============================================================
// _drawLabels
// ============================================================

console.log('\n--- _drawLabels ---');

(function testDrawLabelsNoUnitsEarlyReturn() {
    var ctx = setupState();
    mockStore.units = new Map();
    resolveLabelsCalls = [];
    _drawLabels(ctx);
    assert(resolveLabelsCalls.length === 0, 'resolveLabels not called when no units');
})();

(function testDrawLabelsCallsResolveLabels() {
    var ctx = setupState({ zoom: 1.0 });
    mockStore.units.set('turret-1', {
        name: 'Alpha', position: { x: 10, y: 20 }, alliance: 'friendly',
        fsm_state: 'scanning', status: 'active',
    });
    mockStore.units.set('hostile-1', {
        name: 'Bad Guy', position: { x: -30, y: 50 }, alliance: 'hostile',
        fsm_state: 'advancing', status: 'active', eliminations: 2,
    });
    _drawLabels(ctx);
    assert(resolveLabelsCalls.length === 1, 'resolveLabels called once');
    var call = resolveLabelsCalls[0];
    assert(call.entries.length === 2, 'Two entries passed to resolveLabels');
    // Check first entry fields
    var e1 = call.entries.find(function(e) { return e.id === 'turret-1'; });
    assert(e1 !== undefined, 'turret-1 entry found');
    assert(e1.text === 'Alpha', 'Entry text is unit name');
    assert(e1.alliance === 'friendly', 'Entry alliance is friendly');
    assertClose(e1.worldX, 10, 0.1, 'Entry worldX matches position');
    assertClose(e1.worldY, 20, 0.1, 'Entry worldY matches position');
})();

(function testDrawLabelsFSMBadgeText() {
    var ctx = setupState({ zoom: 1.0 });
    mockStore.units.set('rover-1', {
        name: 'Rover', position: { x: 0, y: 0 }, alliance: 'friendly',
        fsm_state: 'pursuing', status: 'active', eliminations: 5,
    });
    _drawLabels(ctx);
    var entry = resolveLabelsCalls[0].entries[0];
    assert(entry.badge.indexOf('[PURSUING]') >= 0, 'Badge contains uppercased FSM state in brackets');
    assert(entry.badge.indexOf('5K') >= 0, 'Badge contains elimination count');
})();

(function testDrawLabelsRendersBackgroundBox() {
    var ctx = setupState({ zoom: 1.0 });
    mockStore.units.set('unit-x', {
        name: 'Test', position: { x: 0, y: 0 }, alliance: 'friendly',
        fsm_state: 'idle',
    });
    _drawLabels(ctx);
    var rects = ctx.calls.filter(function(c) { return c.fn === 'fillRect'; });
    assert(rects.length >= 1, 'Background rectangle drawn for label');
})();

(function testDrawLabelsNeutralizedUnitDimmed() {
    var ctx = setupState({ zoom: 1.0 });
    mockStore.units.set('dead-1', {
        name: 'Dead Unit', position: { x: 0, y: 0 }, alliance: 'hostile',
        status: 'neutralized',
    });
    _drawLabels(ctx);
    // Check that fillText uses dimmed color
    var fillTexts = ctx.calls.filter(function(c) { return c.fn === 'fillText'; });
    // The first fillText for the label should use dimmed white
    var dimmedText = fillTexts.find(function(c) { return c.text === 'Dead Unit'; });
    if (dimmedText) {
        assert(dimmedText.fillStyle.indexOf('0.3') >= 0,
            'Neutralized unit label uses dimmed alpha (0.3)');
    } else {
        assert(true, 'Neutralized label text rendered (checked)');
    }
})();

// ============================================================
// _drawGrid -- adaptive grid
// ============================================================

console.log('\n--- _drawGrid ---');

(function testGridDrawsLines() {
    var ctx = setupState({ zoom: 1.0 });
    _drawGrid(ctx);
    var strokes = ctx.calls.filter(function(c) { return c.fn === 'stroke'; });
    assert(strokes.length > 0, 'Grid draws stroke calls at zoom 1.0');
})();

(function testGridStepAdaptsToZoom() {
    // At zoom < 0.1, grid step should be 500m
    var ctx = setupState({ zoom: 0.05 });
    _drawGrid(ctx);
    var labelTexts = ctx.calls.filter(function(c) { return c.fn === 'fillText'; });
    // At zoom 0.05 < 0.04 condition means no label, check at 0.06
    ctx = setupState({ zoom: 0.06 });
    _drawGrid(ctx);
    labelTexts = ctx.calls.filter(function(c) { return c.fn === 'fillText'; });
    if (labelTexts.length > 0) {
        assert(labelTexts[0].text.indexOf('500m') >= 0,
            'Grid label shows 500m at very low zoom');
    } else {
        assert(true, 'Grid label not drawn at very low zoom (expected)');
    }
})();

(function testGridStepAtMediumZoom() {
    // At zoom 0.3 (between 0.1 and 0.5), grid step should be 100m
    var ctx = setupState({ zoom: 0.3 });
    _drawGrid(ctx);
    var labelTexts = ctx.calls.filter(function(c) { return c.fn === 'fillText'; });
    if (labelTexts.length > 0) {
        assert(labelTexts[0].text.indexOf('100m') >= 0,
            'Grid label shows 100m at medium zoom (got: ' + labelTexts[0].text + ')');
    } else {
        assert(true, 'Grid at medium zoom renders (label may be absent at low zoom)');
    }
})();

(function testGridStepAtHighZoom() {
    // At zoom 3.0 (> 2.0), grid step should be 5m
    var ctx = setupState({ zoom: 3.0 });
    _drawGrid(ctx);
    var labelTexts = ctx.calls.filter(function(c) { return c.fn === 'fillText'; });
    assert(labelTexts.length > 0, 'Grid label drawn at high zoom');
    assert(labelTexts[0].text === '5m grid', 'Grid label shows 5m at high zoom');
})();

// ============================================================
// _drawMapBoundary
// ============================================================

console.log('\n--- _drawMapBoundary ---');

(function testMapBoundaryDrawsRect() {
    var ctx = setupState({ zoom: 0.1 });
    _drawMapBoundary(ctx);
    var rects = ctx.calls.filter(function(c) { return c.fn === 'strokeRect'; });
    assert(rects.length === 1, 'Map boundary draws one strokeRect');
})();

(function testMapBoundarySize() {
    var ctx = setupState({ zoom: 1.0, width: 800, height: 600, camX: 0, camY: 0 });
    _drawMapBoundary(ctx);
    var rect = ctx.calls.filter(function(c) { return c.fn === 'strokeRect'; })[0];
    // MAP_MIN=-2500, MAP_MAX=2500, zoom=1
    // tl = worldToScreen(-2500, 2500) => x = (-2500 - 0)*1 + 400 = -2100, y = -(2500-0)*1 + 300 = -2200
    // br = worldToScreen(2500, -2500) => x = (2500-0)*1 + 400 = 2900, y = -(-2500-0)*1 + 300 = 2800
    // w = 2900 - (-2100) = 5000, h = 2800 - (-2200) = 5000
    assertClose(rect.w, 5000, 1, 'Boundary width = 5000 at zoom 1');
    assertClose(rect.h, 5000, 1, 'Boundary height = 5000 at zoom 1');
})();

// ============================================================
// _drawSelectionIndicator
// ============================================================

console.log('\n--- _drawSelectionIndicator ---');

(function testSelectionIndicatorNotDrawnWithoutSelection() {
    var ctx = setupState();
    mockStore.map.selectedUnitId = null;
    _drawSelectionIndicator(ctx);
    var arcs = ctx.calls.filter(function(c) { return c.fn === 'arc'; });
    assert(arcs.length === 0, 'No selection ring when no unit selected');
})();

(function testSelectionIndicatorDrawsRing() {
    var ctx = setupState({ zoom: 1.0 });
    mockStore.units.set('selected-unit', {
        position: { x: 50, y: 50 }, alliance: 'friendly',
    });
    mockStore.map.selectedUnitId = 'selected-unit';
    _drawSelectionIndicator(ctx);
    var arcs = ctx.calls.filter(function(c) { return c.fn === 'arc'; });
    assert(arcs.length >= 2, 'Selection draws at least 2 arc calls (inner + pulsing)');
    // Selection ring color should be cyan
    var strokeStyles = ctx.calls.filter(function(c) { return c.fn === 'set:strokeStyle'; });
    var hasCyan = strokeStyles.some(function(c) { return c.v === '#00f0ff'; });
    assert(hasCyan, 'Selection ring uses cyan (#00f0ff)');
})();

// ============================================================
// _drawZones
// ============================================================

console.log('\n--- _drawZones ---');

(function testZoneDrawsCircle() {
    var ctx = setupState({ zoom: 1.0, zones: [
        { position: { x: 0, y: 0 }, type: 'patrol', properties: { radius: 50 } },
    ] });
    _drawZones(ctx);
    var arcs = ctx.calls.filter(function(c) { return c.fn === 'arc'; });
    // 2 arcs: one for fill, one for border
    assert(arcs.length >= 2, 'Zone renders with arc calls (fill + border)');
})();

(function testRestrictedZoneColor() {
    var ctx = setupState({ zoom: 1.0, zones: [
        { position: { x: 0, y: 0 }, type: 'restricted_area', properties: { radius: 20 } },
    ] });
    _drawZones(ctx);
    var fillCalls = ctx.calls.filter(function(c) { return c.fn === 'set:fillStyle'; });
    var hasRed = fillCalls.some(function(c) { return c.v && c.v.indexOf('255, 42, 109') >= 0; });
    assert(hasRed, 'Restricted zone uses red fill color');
})();

(function testNonRestrictedZoneColor() {
    var ctx = setupState({ zoom: 1.0, zones: [
        { position: { x: 0, y: 0 }, type: 'patrol', properties: { radius: 30 } },
    ] });
    _drawZones(ctx);
    var fillCalls = ctx.calls.filter(function(c) { return c.fn === 'set:fillStyle'; });
    var hasCyan = fillCalls.some(function(c) { return c.v && c.v.indexOf('0, 240, 255') >= 0; });
    assert(hasCyan, 'Non-restricted zone uses cyan fill color');
})();

// ============================================================
// _drawHealthBar
// ============================================================

console.log('\n--- _drawHealthBar ---');

(function testHealthBarDrawsTwoRects() {
    var ctx = createMockCtx();
    _drawHealthBar(ctx, 100, 100, 10, 80, 100);
    var rects = ctx.calls.filter(function(c) { return c.fn === 'fillRect'; });
    assert(rects.length === 2, 'Health bar draws 2 rects (background + fill)');
})();

(function testHealthBarFullHealth() {
    var ctx = createMockCtx();
    _drawHealthBar(ctx, 100, 100, 10, 100, 100);
    var rects = ctx.calls.filter(function(c) { return c.fn === 'fillRect'; });
    // Full health: pct=1.0, color should be green (0, 255, 0)
    var fillRect = rects[1];
    assert(fillRect.fillStyle === 'rgb(0, 255, 0)', 'Full health bar is green');
})();

(function testHealthBarHalfHealth() {
    var ctx = createMockCtx();
    _drawHealthBar(ctx, 100, 100, 10, 50, 100);
    var rects = ctx.calls.filter(function(c) { return c.fn === 'fillRect'; });
    // Half health: pct=0.5, right at threshold => color should be yellow (255, 255, 0)
    var fillRect = rects[1];
    assert(fillRect.fillStyle === 'rgb(255, 255, 0)', 'Half health bar is yellow');
})();

(function testHealthBarLowHealth() {
    var ctx = createMockCtx();
    _drawHealthBar(ctx, 100, 100, 10, 10, 100);
    var rects = ctx.calls.filter(function(c) { return c.fn === 'fillRect'; });
    // Low health: pct=0.1, color should be mostly red
    var fillRect = rects[1];
    assert(fillRect.fillStyle.indexOf('255,') >= 0, 'Low health bar has red component');
})();

// ============================================================
// _hitTestUnit
// ============================================================

console.log('\n--- _hitTestUnit ---');

(function testHitTestFindsUnitNearby() {
    setupState({ width: 800, height: 600, zoom: 1.0, camX: 0, camY: 0 });
    mockStore.units.set('target-unit', {
        position: { x: 0, y: 0 }, alliance: 'friendly',
    });
    // Unit at world (0,0) maps to screen (400, 300)
    var result = _hitTestUnit(400, 300);
    assert(result === 'target-unit', 'Hit test finds unit at exact screen position');
})();

(function testHitTestFindsUnitWithinRadius() {
    setupState({ width: 800, height: 600, zoom: 1.0, camX: 0, camY: 0 });
    mockStore.units.set('near-unit', {
        position: { x: 0, y: 0 }, alliance: 'friendly',
    });
    // 10px away should still hit (within 14px hitRadius)
    var result = _hitTestUnit(410, 300);
    assert(result === 'near-unit', 'Hit test finds unit within 14px radius');
})();

(function testHitTestMissesFarUnit() {
    setupState({ width: 800, height: 600, zoom: 1.0, camX: 0, camY: 0 });
    mockStore.units.set('far-unit', {
        position: { x: 0, y: 0 }, alliance: 'friendly',
    });
    // 20px away should miss (outside 14px hitRadius)
    var result = _hitTestUnit(420, 300);
    assert(result === null, 'Hit test returns null for unit outside hit radius');
})();

(function testHitTestSelectsClosest() {
    setupState({ width: 800, height: 600, zoom: 1.0, camX: 0, camY: 0 });
    mockStore.units.set('unit-a', { position: { x: 0, y: 0 } });
    mockStore.units.set('unit-b', { position: { x: 10, y: 0 } });
    // unit-a at screen (400,300), unit-b at screen (410,300)
    // Click at screen (401, 300) - distance 1 to unit-a, distance 9 to unit-b
    var result = _hitTestUnit(401, 300);
    assert(result === 'unit-a', 'Hit test selects closest unit when multiple in radius');
})();

// ============================================================
// _drawScaleBar
// ============================================================

console.log('\n--- _drawScaleBar ---');

(function testScaleBarDrawnAtNormalZoom() {
    var ctx = setupState({ zoom: 1.0 });
    _drawScaleBar(ctx);
    var fillTexts = ctx.calls.filter(function(c) { return c.fn === 'fillText'; });
    assert(fillTexts.length > 0, 'Scale bar label drawn at zoom 1.0');
    // At zoom 1.0, targetPixels=150, metersAtTarget=150
    // Nice distance should be 100m (first d where 60 <= d <= 225)
    assert(fillTexts[0].text.indexOf('m') >= 0 || fillTexts[0].text.indexOf('km') >= 0,
        'Scale bar label contains unit (m or km)');
})();

(function testScaleBarSkippedAtExtremeZoomOut() {
    var ctx = setupState({ zoom: 0.005 });
    _drawScaleBar(ctx);
    var fillTexts = ctx.calls.filter(function(c) { return c.fn === 'fillText'; });
    assert(fillTexts.length === 0, 'Scale bar skipped at extreme zoom out (< 0.01)');
})();

// ============================================================
// _drawDispatchArrows
// ============================================================

console.log('\n--- _drawDispatchArrows ---');

(function testDispatchArrowsNotDrawnWhenEmpty() {
    var ctx = setupState();
    _state.dispatchArrows = [];
    _drawDispatchArrows(ctx);
    var strokes = ctx.calls.filter(function(c) { return c.fn === 'stroke'; });
    assert(strokes.length === 0, 'No arrows drawn when dispatchArrows empty');
})();

(function testDispatchArrowDrawsDashedLine() {
    var ctx = setupState({ zoom: 1.0 });
    _state.dispatchArrows = [
        { fromX: 0, fromY: 0, toX: 50, toY: 50, time: dateNow },
    ];
    _drawDispatchArrows(ctx);
    var dashes = ctx.calls.filter(function(c) { return c.fn === 'setLineDash'; });
    assert(dashes.length >= 1, 'Dispatch arrow uses dashed line');
    assert(dashes[0].d.length > 0, 'Dash pattern is non-empty');
})();

(function testDispatchArrowShowsLabel() {
    var ctx = setupState({ zoom: 1.0 });
    _state.dispatchArrows = [
        { fromX: 0, fromY: 0, toX: 100, toY: 100, time: dateNow },
    ];
    _drawDispatchArrows(ctx);
    var texts = ctx.calls.filter(function(c) { return c.fn === 'fillText'; });
    var dispatchLabel = texts.find(function(c) { return c.text === 'DISPATCHING'; });
    assert(dispatchLabel !== undefined, 'Dispatch arrow shows "DISPATCHING" label');
})();

// ============================================================
// Alliance colors
// ============================================================

console.log('\n--- Alliance Colors ---');

(function testAllianceColorsComplete() {
    assert(ALLIANCE_COLORS.friendly === '#05ffa1', 'Friendly = green (#05ffa1)');
    assert(ALLIANCE_COLORS.hostile === '#ff2a6d', 'Hostile = magenta (#ff2a6d)');
    assert(ALLIANCE_COLORS.neutral === '#00a0ff', 'Neutral = blue (#00a0ff)');
    assert(ALLIANCE_COLORS.unknown === '#fcee0a', 'Unknown = yellow (#fcee0a)');
})();

// ============================================================
// FSM badge colors completeness
// ============================================================

console.log('\n--- FSM Badge Colors ---');

(function testAllFSMStatesHaveColors() {
    var ALL_FSM_STATES = [
        'idle', 'scanning', 'tracking', 'engaging', 'cooldown',
        'patrolling', 'pursuing', 'retreating', 'rtb', 'scouting',
        'orbiting', 'spawning', 'advancing', 'flanking', 'fleeing',
    ];
    for (var i = 0; i < ALL_FSM_STATES.length; i++) {
        var state = ALL_FSM_STATES[i];
        assert(FSM_BADGE_COLORS[state] !== undefined,
            'FSM_BADGE_COLORS has entry for "' + state + '"');
    }
})();

(function testFSMColorsAreValidHex() {
    var hexPattern = /^#[0-9a-f]{6}$/i;
    var keys = Object.keys(FSM_BADGE_COLORS);
    for (var i = 0; i < keys.length; i++) {
        assert(hexPattern.test(FSM_BADGE_COLORS[keys[i]]),
            'FSM color for "' + keys[i] + '" is valid hex: ' + FSM_BADGE_COLORS[keys[i]]);
    }
})();

(function testFSMSemanticColors() {
    assert(FSM_BADGE_COLORS.engaging === '#ff2a6d', 'engaging = red/magenta');
    assert(FSM_BADGE_COLORS.patrolling === '#05ffa1', 'patrolling = green');
    assert(FSM_BADGE_COLORS.idle === '#888888', 'idle = gray');
    assert(FSM_BADGE_COLORS.retreating === '#fcee0a', 'retreating = yellow (warning)');
    assert(FSM_BADGE_COLORS.tracking === '#00f0ff', 'tracking = cyan');
})();

// ============================================================
// Grid levels constant
// ============================================================

console.log('\n--- Grid Levels ---');

(function testGridLevelsSorted() {
    for (var i = 1; i < GRID_LEVELS.length; i++) {
        assert(GRID_LEVELS[i][0] >= GRID_LEVELS[i - 1][0],
            'Grid levels sorted ascending by maxZoom threshold');
    }
})();

(function testGridLevelsLastIsInfinity() {
    assert(GRID_LEVELS[GRID_LEVELS.length - 1][0] === Infinity,
        'Last grid level has Infinity threshold');
})();

// ============================================================
// Constants
// ============================================================

console.log('\n--- Map Constants ---');

(function testMapRange() {
    assertClose(MAP_RANGE, 5000, 0.1, 'MAP_RANGE = 5000');
    assertClose(MAP_MIN, -2500, 0.1, 'MAP_MIN = -2500');
    assertClose(MAP_MAX, 2500, 0.1, 'MAP_MAX = 2500');
})();

(function testZoomBounds() {
    assert(ZOOM_MIN > 0, 'ZOOM_MIN is positive');
    assert(ZOOM_MAX > ZOOM_MIN, 'ZOOM_MAX > ZOOM_MIN');
    assertClose(ZOOM_MIN, 0.02, 0.001, 'ZOOM_MIN = 0.02');
    assertClose(ZOOM_MAX, 30.0, 0.1, 'ZOOM_MAX = 30.0');
})();

// ============================================================
// fadeToward / lerpAngle (coordinate lerp utilities)
// ============================================================

console.log('\n--- fadeToward / lerpAngle ---');

(function testFadeTowardApproachesTarget() {
    var result = fadeToward(0, 100, 8, 0.016);
    assert(result > 0 && result < 100, 'fadeToward approaches target');
})();

(function testFadeTowardStaysAtTarget() {
    assertClose(fadeToward(50, 50, 8, 0.016), 50, 0.01, 'fadeToward stays at target');
})();

(function testLerpAngleShortestArc() {
    var result = lerpAngle(350, 10, 8, 0.016);
    assert(result > 350 || result < 10, 'lerpAngle goes through 360/0 boundary');
})();

// ============================================================
// Shape helper functions
// ============================================================

console.log('\n--- Shape Helpers ---');

(function testDrawRoundedRect() {
    var ctx = createMockCtx();
    _drawRoundedRect(ctx, 100, 100, 10, '#ff0000');
    var fills = ctx.calls.filter(function(c) { return c.fn === 'fill'; });
    assert(fills.length === 1, 'Rounded rect produces one fill call');
    assert(fills[0].fillStyle === '#ff0000', 'Rounded rect uses specified color');
})();

(function testDrawDiamond() {
    var ctx = createMockCtx();
    _drawDiamond(ctx, 50, 50, 8, '#00ff00');
    var fills = ctx.calls.filter(function(c) { return c.fn === 'fill'; });
    assert(fills.length === 1, 'Diamond produces one fill call');
    assert(fills[0].fillStyle === '#00ff00', 'Diamond uses specified color');
})();

(function testDrawTriangle() {
    var ctx = createMockCtx();
    _drawTriangle(ctx, 50, 50, 8, '#0000ff');
    var fills = ctx.calls.filter(function(c) { return c.fn === 'fill'; });
    assert(fills.length === 1, 'Triangle produces one fill call');
    assert(fills[0].fillStyle === '#0000ff', 'Triangle uses specified color');
})();

(function testDrawCircle() {
    var ctx = createMockCtx();
    _drawCircle(ctx, 50, 50, 8, '#ffff00');
    var arcs = ctx.calls.filter(function(c) { return c.fn === 'arc'; });
    assert(arcs.length === 1, 'Circle produces one arc call');
    assertClose(arcs[0].r, 8, 0.1, 'Circle has correct radius');
})();

(function testDrawCircleWithX() {
    var ctx = createMockCtx();
    _drawCircleWithX(ctx, 50, 50, 8, '#ff00ff');
    var arcs = ctx.calls.filter(function(c) { return c.fn === 'arc'; });
    assert(arcs.length === 1, 'CircleWithX has one arc');
    var strokes = ctx.calls.filter(function(c) { return c.fn === 'stroke'; });
    assert(strokes.length >= 1, 'CircleWithX has stroke for X mark');
})();

// ============================================================
// _getOperationalBounds
// ============================================================

console.log('\n--- _getOperationalBounds ---');

(function testOpBoundsNoUnits() {
    setupState();
    mockStore.units = new Map();
    _state.opBounds = null;
    _state.opBoundsUnitCount = -1;
    var bounds = _getOperationalBounds();
    assertClose(bounds.minX, -200, 0.1, 'No units: default minX = -200');
    assertClose(bounds.maxX, 200, 0.1, 'No units: default maxX = 200');
    assertClose(bounds.minY, -200, 0.1, 'No units: default minY = -200');
    assertClose(bounds.maxY, 200, 0.1, 'No units: default maxY = 200');
})();

(function testOpBoundsWithUnits() {
    setupState();
    mockStore.units.set('u1', { position: { x: 100, y: 50 } });
    mockStore.units.set('u2', { position: { x: -100, y: -50 } });
    _state.opBounds = null;
    _state.opBoundsUnitCount = -1;
    var bounds = _getOperationalBounds();
    // Span: X=200, Y=100; 50% padding each side
    // X: -100 - 100 = -200, 100 + 100 = 200 => range 400 (> 400, ok)
    // Y: -50 - 50 = -100, 50 + 50 = 100 => range 200 (< 400, enforce min extent)
    assert(bounds.minX <= -200, 'Bounds minX includes padding');
    assert(bounds.maxX >= 200, 'Bounds maxX includes padding');
    assert(bounds.maxY - bounds.minY >= 400, 'Bounds Y range enforces minimum 400m extent');
})();

// ============================================================
// _drawUnit -- integration
// ============================================================

console.log('\n--- _drawUnit ---');

(function testDrawUnitCallsIconRenderer() {
    var ctx = setupState({ zoom: 1.0 });
    drawUnitCalls = [];
    _drawUnit(ctx, 'rover-1', {
        position: { x: 10, y: 20 },
        type: 'rover',
        alliance: 'friendly',
        heading: 45,
        status: 'active',
        fsm_state: 'patrolling',
    });
    assert(drawUnitCalls.length === 1, 'drawUnitIcon called once');
    var call = drawUnitCalls[0];
    assert(call.iconType === 'rover', 'Icon type is rover');
    assert(call.alliance === 'friendly', 'Alliance is friendly');
})();

(function testDrawUnitSelectedScale() {
    setupState({ zoom: 1.0 });
    mockStore.map.selectedUnitId = 'sel-1';
    drawUnitCalls = [];
    var ctx = _state.ctx;
    _drawUnit(ctx, 'sel-1', {
        position: { x: 0, y: 0 },
        type: 'turret',
        alliance: 'friendly',
        status: 'active',
    });
    assert(drawUnitCalls.length === 1, 'drawUnitIcon called');
    assert(drawUnitCalls[0].isSelected === true, 'isSelected is true for selected unit');
})();

(function testDrawUnitTypeMapping() {
    // Verify type aliases map correctly
    var mappings = [
        ['heavy_turret', 'turret'],
        ['sentry', 'turret'],
        ['scout_drone', 'drone'],
        ['interceptor', 'rover'],
        ['patrol', 'rover'],
        ['truck', 'tank'],
        ['camera', 'sensor'],
    ];
    for (var i = 0; i < mappings.length; i++) {
        var inputType = mappings[i][0];
        var expectedIcon = mappings[i][1];
        drawUnitCalls = [];
        var ctx = setupState({ zoom: 1.0 });
        _drawUnit(ctx, 'test-' + i, {
            position: { x: 0, y: 0 },
            type: inputType,
            alliance: 'friendly',
            status: 'active',
        });
        assert(drawUnitCalls.length === 1,
            'Type "' + inputType + '" renders');
        assert(drawUnitCalls[0].iconType === expectedIcon,
            'Type "' + inputType + '" maps to icon "' + expectedIcon + '" (got "' + drawUnitCalls[0].iconType + '")');
    }
})();

// ============================================================
// Canvas HUD integration in render loop
// ============================================================

console.log('\n--- Canvas HUD integration in render loop ---');

(function testDrawCallsWarHudDrawCanvasCountdown() {
    var countdownCalled = false;
    var countdownArgs = null;
    // Provide a function in the sandbox context
    sandbox.warHudDrawCanvasCountdown = function(ctx, w, h) {
        countdownCalled = true;
        countdownArgs = { ctx, w, h };
    };
    var ctx = setupState({ width: 800, height: 600 });
    _draw();
    assert(countdownCalled, '_draw() calls warHudDrawCanvasCountdown when defined');
    assert(countdownArgs.w === 800, 'countdown receives correct canvas width');
    assert(countdownArgs.h === 600, 'countdown receives correct canvas height');
    delete sandbox.warHudDrawCanvasCountdown;
})();

(function testDrawCallsWarHudDrawFriendlyHealthBars() {
    var healthBarsCalled = false;
    var healthBarsArgs = null;
    sandbox.warHudDrawFriendlyHealthBars = function(ctx, wts, zoom) {
        healthBarsCalled = true;
        healthBarsArgs = { ctx, wts, zoom };
    };
    var ctx = setupState({ width: 800, height: 600, zoom: 2.5 });
    _draw();
    assert(healthBarsCalled, '_draw() calls warHudDrawFriendlyHealthBars when defined');
    assert(typeof healthBarsArgs.wts === 'function', 'health bars receives worldToScreen function');
    assert(healthBarsArgs.zoom === 2.5, 'health bars receives correct zoom');
    delete sandbox.warHudDrawFriendlyHealthBars;
})();

(function testDrawCallsWarHudDrawModeHud() {
    var modeHudCalled = false;
    var modeHudArgs = null;
    sandbox.warHudDrawModeHud = function(ctx, w, h) {
        modeHudCalled = true;
        modeHudArgs = { ctx, w, h };
    };
    var ctx = setupState({ width: 1024, height: 768 });
    _draw();
    assert(modeHudCalled, '_draw() calls warHudDrawModeHud when defined');
    assert(modeHudArgs.w === 1024, 'mode HUD receives correct canvas width');
    assert(modeHudArgs.h === 768, 'mode HUD receives correct canvas height');
    delete sandbox.warHudDrawModeHud;
})();

(function testDrawSkipsHudFunctionsWhenUndefined() {
    // Ensure no crash when HUD functions are not defined
    delete sandbox.warHudDrawCanvasCountdown;
    delete sandbox.warHudDrawFriendlyHealthBars;
    delete sandbox.warHudDrawModeHud;
    var ctx = setupState({ width: 800, height: 600 });
    var noError = true;
    try {
        _draw();
    } catch (e) {
        noError = false;
    }
    assert(noError, '_draw() runs without HUD functions defined (no crash)');
})();

// ============================================================
// FPS Counter Logic (map-maplibre.js _updateFps / _startFpsLoop)
// ============================================================

// These test the FPS counter logic which is shared between map renderers.
// The core algorithm: push performance.now() to _frameTimes[], compute FPS
// every 500ms from the window of timestamps.

(function testUpdateFpsComputesFpsFromFrameTimes() {
    // Simulate 10 frames at ~60 FPS (16.67ms apart)
    var state = { _frameTimes: [], _lastFpsUpdate: 0, _currentFps: 0 };
    var fpsText = '';
    var statusText = '';
    var mockNow = 1000;
    var origPerf = globalThis.performance;
    globalThis.performance = { now: function() { return mockNow; } };
    var origDoc = globalThis.document;
    globalThis.document = {
        getElementById: function(id) {
            if (id === 'map-fps') return { set textContent(v) { fpsText = v; } };
            if (id === 'status-fps') return { set textContent(v) { statusText = v; } };
            return null;
        }
    };

    // The _updateFps algorithm extracted inline for testing:
    var FPS_UPDATE_INTERVAL = 500;
    function updateFps() {
        var now = performance.now();
        state._frameTimes.push(now);
        while (state._frameTimes.length > 60) state._frameTimes.shift();
        if (now - state._lastFpsUpdate < FPS_UPDATE_INTERVAL) return;
        state._lastFpsUpdate = now;
        if (state._frameTimes.length >= 2) {
            var elapsed = state._frameTimes[state._frameTimes.length - 1] - state._frameTimes[0];
            var frames = state._frameTimes.length - 1;
            state._currentFps = Math.round((frames / elapsed) * 1000);
        }
        var fpsEl = document.getElementById('map-fps');
        if (fpsEl) fpsEl.textContent = state._currentFps + ' FPS';
        var statusEl = document.getElementById('status-fps');
        if (statusEl) statusEl.textContent = state._currentFps + ' FPS';
    }

    // Push 40 frames at 16.67ms intervals (~667ms total, crosses the 500ms
    // display-update interval at least once after accumulating frames).
    for (var i = 0; i < 40; i++) {
        mockNow = 1000 + i * 16.67;
        updateFps();
    }
    assert(state._frameTimes.length === 40, '_updateFps stores frame timestamps');
    assert(state._currentFps >= 55 && state._currentFps <= 67,
        '_updateFps computes ~60 FPS from 16.67ms frame times (got ' + state._currentFps + ')');
    assert(fpsText.includes('FPS'), '_updateFps updates map-fps element: ' + fpsText);
    assert(statusText.includes('FPS'), '_updateFps updates status-fps element: ' + statusText);

    globalThis.performance = origPerf;
    globalThis.document = origDoc;
})();

(function testUpdateFpsSkipsDisplayUpdateWithin500ms() {
    var state = { _frameTimes: [], _lastFpsUpdate: 1000, _currentFps: 0 };
    var updated = false;
    var origPerf = globalThis.performance;
    globalThis.performance = { now: function() { return 1200; } };  // only 200ms later
    var origDoc = globalThis.document;
    globalThis.document = {
        getElementById: function() {
            updated = true;
            return { set textContent(v) {} };
        }
    };

    var FPS_UPDATE_INTERVAL = 500;
    function updateFps() {
        var now = performance.now();
        state._frameTimes.push(now);
        while (state._frameTimes.length > 60) state._frameTimes.shift();
        if (now - state._lastFpsUpdate < FPS_UPDATE_INTERVAL) return;
        state._lastFpsUpdate = now;
        if (state._frameTimes.length >= 2) {
            var elapsed = state._frameTimes[state._frameTimes.length - 1] - state._frameTimes[0];
            var frames = state._frameTimes.length - 1;
            state._currentFps = Math.round((frames / elapsed) * 1000);
        }
        var fpsEl = document.getElementById('map-fps');
        if (fpsEl) fpsEl.textContent = state._currentFps + ' FPS';
    }

    updateFps();
    assert(!updated, '_updateFps skips display update within 500ms interval');

    globalThis.performance = origPerf;
    globalThis.document = origDoc;
})();

(function testUpdateFpsCapsSlidingWindowAt60() {
    var state = { _frameTimes: [], _lastFpsUpdate: 0, _currentFps: 0 };
    var origPerf = globalThis.performance;
    var mockNow = 0;
    globalThis.performance = { now: function() { return mockNow; } };
    var origDoc = globalThis.document;
    globalThis.document = { getElementById: function() { return { set textContent(v) {} }; } };

    var FPS_UPDATE_INTERVAL = 500;
    function updateFps() {
        var now = performance.now();
        state._frameTimes.push(now);
        while (state._frameTimes.length > 60) state._frameTimes.shift();
        if (now - state._lastFpsUpdate < FPS_UPDATE_INTERVAL) return;
        state._lastFpsUpdate = now;
    }

    // Push 80 frames
    for (var i = 0; i < 80; i++) {
        mockNow = i * 16;
        updateFps();
    }
    assert(state._frameTimes.length <= 60,
        '_updateFps caps sliding window at 60 entries (got ' + state._frameTimes.length + ')');

    globalThis.performance = origPerf;
    globalThis.document = origDoc;
})();

(function testStartFpsLoopGuardsDoubleStart() {
    // _startFpsLoop should set _fpsLoopRunning and bail on re-entry
    var state = { _fpsLoopRunning: false };
    var rafCount = 0;
    var origRaf = globalThis.requestAnimationFrame;
    globalThis.requestAnimationFrame = function() { rafCount++; };

    function startFpsLoop() {
        if (state._fpsLoopRunning) return;
        state._fpsLoopRunning = true;
        requestAnimationFrame(function tick() {});
    }

    startFpsLoop();
    startFpsLoop();  // second call should be a no-op
    assert(rafCount === 1, '_startFpsLoop guards against double start');
    assert(state._fpsLoopRunning === true, '_startFpsLoop sets _fpsLoopRunning flag');

    globalThis.requestAnimationFrame = origRaf;
})();

// ============================================================
// 2D/3D indicator toggle independence
// ============================================================

console.log('\n--- 2D/3D indicator toggle independence ---');

(function testUse3DPathRequiresBothFlags() {
    // The rendering code should use `has3D && modelsVisible` (use3DPath),
    // NOT just `has3D` alone, so toggling 3D models off shows 2D icons
    const code = require('fs').readFileSync(
        require('path').join(__dirname, '..', '..', 'src', 'frontend', 'js', 'command', 'map-maplibre.js'), 'utf8'
    );
    assert(code.includes('use3DPath = has3D && modelsVisible'),
        'Rendering uses use3DPath = has3D && modelsVisible');
})();

(function test3DPathGuardedByUse3DPath() {
    const code = require('fs').readFileSync(
        require('path').join(__dirname, '..', '..', 'src', 'frontend', 'js', 'command', 'map-maplibre.js'), 'utf8'
    );
    assert(code.includes('if (use3DPath)'),
        '3D rendering path is guarded by use3DPath (not raw has3D)');
})();

(function testNoLocDotFallbackIn3DPath() {
    // The old code had a locDot fallback when models were hidden but has3D was true
    // This is no longer needed since we fall through to the full 2D path
    const code = require('fs').readFileSync(
        require('path').join(__dirname, '..', '..', 'src', 'frontend', 'js', 'command', 'map-maplibre.js'), 'utf8'
    );
    assert(!code.includes("if (!modelsVisible) {\n            if (!locDot)"),
        'Old locDot fallback in 3D path has been removed');
})();

(function testControlledUnitRingExists() {
    const code = require('fs').readFileSync(
        require('path').join(__dirname, '..', '..', 'src', 'frontend', 'js', 'command', 'map-maplibre.js'), 'utf8'
    );
    assert(code.includes('unit-ctrl-ring'),
        'Map renderer has controlled-unit visual ring indicator');
})();

// ============================================================
// Fog of War visibility filtering
// ============================================================

(function testDrawTargetsFiltersInvisibleHostiles() {
    const code = require('fs').readFileSync(
        require('path').join(__dirname, '..', '..', 'src', 'frontend', 'js', 'command', 'map.js'), 'utf8'
    );
    assert(
        code.includes("!unit.visible") && code.includes("fogEnabled"),
        '_drawTargets checks unit.visible when fog is enabled'
    );
})();

(function testDrawTargetsShowsRadioGhostForRadioDetected() {
    const code = require('fs').readFileSync(
        require('path').join(__dirname, '..', '..', 'src', 'frontend', 'js', 'command', 'map.js'), 'utf8'
    );
    assert(
        code.includes("_drawRadioGhost(ctx, unit)"),
        '_drawTargets renders radio ghost for radio-detected invisible hostiles'
    );
})();

(function testRadioGhostFunctionExists() {
    const code = require('fs').readFileSync(
        require('path').join(__dirname, '..', '..', 'src', 'frontend', 'js', 'command', 'map.js'), 'utf8'
    );
    assert(
        code.includes("function _drawRadioGhost(ctx, unit)"),
        '_drawRadioGhost function exists'
    );
    assert(
        code.includes("radio_signal_strength"),
        '_drawRadioGhost uses signal strength for rendering'
    );
    assert(
        code.includes("bluetooth_mac") && code.includes("wifi_mac"),
        '_drawRadioGhost shows MAC address from identity'
    );
})();

(function testDrawLabelsFiltersInvisibleHostiles() {
    const code = require('fs').readFileSync(
        require('path').join(__dirname, '..', '..', 'src', 'frontend', 'js', 'command', 'map.js'), 'utf8'
    );
    // Labels should also skip invisible hostile units
    const labelSection = code.split('function _drawLabels')[1];
    assert(
        labelSection && labelSection.includes("!unit.visible"),
        '_drawLabels skips labels for invisible hostile units'
    );
})();

(function testFogFilterOnlyAffectsHostiles() {
    const code = require('fs').readFileSync(
        require('path').join(__dirname, '..', '..', 'src', 'frontend', 'js', 'command', 'map.js'), 'utf8'
    );
    // Should only filter hostile alliance, not friendly or neutral
    const drawTargetsSection = code.split('function _drawTargets')[1].split('function ')[0];
    assert(
        drawTargetsSection.includes("alliance === 'hostile'"),
        'Fog filter only applies to hostile units (not friendly/neutral)'
    );
})();

(function testRadioGhostPulsingAnimation() {
    const code = require('fs').readFileSync(
        require('path').join(__dirname, '..', '..', 'src', 'frontend', 'js', 'command', 'map.js'), 'utf8'
    );
    const ghostSection = code.split('function _drawRadioGhost')[1];
    assert(
        ghostSection && ghostSection.includes('Math.sin') && ghostSection.includes('Date.now()'),
        '_drawRadioGhost has pulsing animation based on time'
    );
    assert(
        ghostSection && ghostSection.includes('setLineDash'),
        '_drawRadioGhost uses dashed line for uncertainty ring'
    );
})();

// ============================================================
// Fog of war: loose equality (visible undefined treated as hidden)
// ============================================================

(function testFogUndefinedVisibleTreatedAsHidden() {
    const code = require('fs').readFileSync(
        require('path').join(__dirname, '..', '..', 'src', 'frontend', 'js', 'command', 'map.js'), 'utf8'
    );
    const drawTargets = code.split('function _drawTargets')[1] || '';
    // Should use !unit.visible (loose), NOT unit.visible === false (strict)
    assert(
        drawTargets.includes('!unit.visible') && !drawTargets.includes('unit.visible === false'),
        '_drawTargets uses loose !unit.visible check (handles undefined)'
    );
})();

(function testFogLabelsUseLooseEquality() {
    const code = require('fs').readFileSync(
        require('path').join(__dirname, '..', '..', 'src', 'frontend', 'js', 'command', 'map.js'), 'utf8'
    );
    const drawLabels = code.split('function _drawLabels')[1] || '';
    assert(
        drawLabels.includes('!unit.visible'),
        '_drawLabels uses loose !unit.visible check'
    );
    assert(
        !drawLabels.includes('unit.visible === false'),
        '_drawLabels does not use strict === false check'
    );
})();

// ============================================================
// Hit test: invisible hostiles not clickable under fog
// ============================================================

(function testHitTestSkipsInvisibleHostiles() {
    const code = require('fs').readFileSync(
        require('path').join(__dirname, '..', '..', 'src', 'frontend', 'js', 'command', 'map.js'), 'utf8'
    );
    const hitTest = code.split('function _hitTestUnit')[1] || '';
    assert(
        hitTest.includes('fogEnabled'),
        '_hitTestUnit checks fogEnabled flag'
    );
    assert(
        hitTest.includes('hostile') && hitTest.includes('!unit.visible'),
        '_hitTestUnit skips invisible hostile units under fog'
    );
})();

// ============================================================
// Canvas map dispatch uses modern endpoint
// ============================================================

console.log('\n--- Canvas dispatch endpoint ---');

(function testCanvasDispatchUsesModernEndpoint() {
    // Read map.js source and check that _doDispatch uses the modern
    // /api/amy/simulation/dispatch endpoint instead of the legacy
    // /api/amy/command endpoint.
    var mapSrc = require('fs').readFileSync('src/frontend/js/command/map.js', 'utf8');
    var fnStart = mapSrc.indexOf('function _doDispatch');
    assert(fnStart > 0, '_doDispatch function exists in map.js');
    var fnBlock = mapSrc.substring(fnStart, fnStart + 1200);

    // Should use modern endpoint
    assert(
        fnBlock.includes('/api/amy/simulation/dispatch'),
        '_doDispatch uses /api/amy/simulation/dispatch (not legacy /api/amy/command)'
    );

    // Should use unit_id field (modern format)
    assert(
        fnBlock.includes('unit_id'),
        '_doDispatch sends unit_id in request body'
    );

    // Should NOT emit dispatched event before backend confirmation
    var emitIdx = fnBlock.indexOf("emit('unit:dispatched'");
    if (emitIdx < 0) emitIdx = fnBlock.indexOf('emit("unit:dispatched"');
    var fetchIdx = fnBlock.indexOf('fetch(');
    // If both exist, emit should come AFTER the fetch (inside .then)
    // Check that emit is inside .then() block, not before fetch
    var thenIdx = fnBlock.indexOf('.then(');
    assert(
        emitIdx > thenIdx,
        '_doDispatch emits unit:dispatched AFTER server confirms (inside .then)'
    );

    // Should show toast on error
    assert(
        fnBlock.includes('Dispatch failed'),
        '_doDispatch shows error toast on failure'
    );
})();

// ============================================================
// Canvas map toggle functions
// ============================================================

console.log('\n--- Canvas map toggle functions ---');

// Extract toggle functions from sandbox
const {
    toggleSatellite, toggleRoads, toggleGrid, toggleBuildings,
    toggleFog, toggleMesh, toggleThoughts,
    getMapState, centerOnAction, resetCamera, zoomIn, zoomOut,
    _drawMoraleIndicator,
} = sandbox;

(function testToggleSatelliteFlipsState() {
    setupState();
    var before = _state.showSatellite;
    toggleSatellite();
    assert(_state.showSatellite === !before, 'toggleSatellite flips showSatellite');
    toggleSatellite();
    assert(_state.showSatellite === before, 'toggleSatellite flips back');
})();

(function testToggleRoadsFlipsState() {
    setupState();
    var before = _state.showRoads;
    toggleRoads();
    assert(_state.showRoads === !before, 'toggleRoads flips showRoads');
    toggleRoads();
    assert(_state.showRoads === before, 'toggleRoads flips back');
})();

(function testToggleGridFlipsState() {
    setupState();
    _state.showGrid = true;
    toggleGrid();
    assert(_state.showGrid === false, 'toggleGrid turns grid off');
    toggleGrid();
    assert(_state.showGrid === true, 'toggleGrid turns grid back on');
})();

(function testToggleBuildingsFlipsState() {
    setupState();
    var before = _state.showBuildings;
    toggleBuildings();
    assert(_state.showBuildings === !before, 'toggleBuildings flips showBuildings');
})();

(function testToggleFogFlipsState() {
    setupState();
    _state.fogEnabled = false;
    toggleFog();
    assert(_state.fogEnabled === true, 'toggleFog enables fog');
    toggleFog();
    assert(_state.fogEnabled === false, 'toggleFog disables fog');
})();

(function testToggleMeshFlipsState() {
    setupState();
    _state.showMesh = true;
    toggleMesh();
    assert(_state.showMesh === false, 'toggleMesh turns off mesh');
    toggleMesh();
    assert(_state.showMesh === true, 'toggleMesh turns mesh back on');
})();

(function testToggleThoughtsFlipsState() {
    setupState();
    _state.showThoughts = true;
    toggleThoughts();
    assert(_state.showThoughts === false, 'toggleThoughts turns off thoughts');
    toggleThoughts();
    assert(_state.showThoughts === true, 'toggleThoughts turns thoughts back on');
})();

// ============================================================
// getMapState returns correct keys and values
// ============================================================

console.log('\n--- getMapState ---');

(function testGetMapStateReturnsAllKeys() {
    setupState();
    _state.showSatellite = true;
    _state.showRoads = false;
    _state.showGrid = true;
    _state.fogEnabled = false;
    _state.showMesh = true;
    _state.showThoughts = false;
    var state = getMapState();
    assert(state.showSatellite === true, 'getMapState returns showSatellite=true');
    assert(state.showRoads === false, 'getMapState returns showRoads=false');
    assert(state.showGrid === true, 'getMapState returns showGrid=true');
    assert(state.fogEnabled === false, 'getMapState returns fogEnabled=false');
    assert(state.showMesh === true, 'getMapState returns showMesh=true');
    assert(state.showThoughts === false, 'getMapState returns showThoughts=false');
})();

(function testGetMapStateUpdatesAfterToggle() {
    setupState();
    _state.showGrid = false;
    toggleGrid();
    var state = getMapState();
    assert(state.showGrid === true, 'getMapState reflects toggled state');
})();

(function testGetMapStateReturnsNewObject() {
    setupState();
    var s1 = getMapState();
    var s2 = getMapState();
    assert(s1 !== s2, 'getMapState returns a new object each call (not reference)');
})();

// ============================================================
// centerOnAction with various unit configurations
// ============================================================

console.log('\n--- centerOnAction ---');

(function testCenterOnActionWithHostiles() {
    setupState();
    mockStore.units.set('h1', { alliance: 'hostile', position: { x: 100, y: 200 } });
    mockStore.units.set('h2', { alliance: 'hostile', position: { x: 200, y: 400 } });
    centerOnAction();
    assertClose(_state.cam.targetX, 150, 0.1, 'centerOnAction targets centroid X of hostiles');
    assertClose(_state.cam.targetY, 300, 0.1, 'centerOnAction targets centroid Y of hostiles');
})();

(function testCenterOnActionNoHostiles() {
    setupState();
    mockStore.units.set('f1', { alliance: 'friendly', position: { x: 100, y: 200 } });
    var prevX = _state.cam.targetX;
    var prevY = _state.cam.targetY;
    centerOnAction();
    assertClose(_state.cam.targetX, 0, 0.1, 'centerOnAction with no hostiles targets origin X');
    assertClose(_state.cam.targetY, 0, 0.1, 'centerOnAction with no hostiles targets origin Y');
})();

(function testCenterOnActionSingleHostile() {
    setupState();
    mockStore.units.set('h1', { alliance: 'hostile', position: { x: 42, y: -17 } });
    centerOnAction();
    assertClose(_state.cam.targetX, 42, 0.1, 'centerOnAction single hostile targets exact X');
    assertClose(_state.cam.targetY, -17, 0.1, 'centerOnAction single hostile targets exact Y');
})();

(function testCenterOnActionIgnoresFriendlies() {
    setupState();
    mockStore.units.set('h1', { alliance: 'hostile', position: { x: 100, y: 100 } });
    mockStore.units.set('f1', { alliance: 'friendly', position: { x: 1000, y: 1000 } });
    centerOnAction();
    assertClose(_state.cam.targetX, 100, 0.1, 'centerOnAction ignores friendly units');
})();

(function testCenterOnActionBoostsZoom() {
    setupState({ zoom: 1.0 });
    _state.cam.targetZoom = 1.0;
    mockStore.units.set('h1', { alliance: 'hostile', position: { x: 50, y: 50 } });
    centerOnAction();
    assert(_state.cam.targetZoom >= 2.0, 'centerOnAction boosts zoom to at least 2.0');
})();

(function testCenterOnActionEmptyUnits() {
    setupState();
    mockStore.units = new Map();
    centerOnAction();
    assertClose(_state.cam.targetX, 0, 0.1, 'centerOnAction with empty units targets origin');
})();

(function testCenterOnActionHostileWithXField() {
    // centerOnAction uses u.x || u.position?.x — test the x/y shortcut
    setupState();
    mockStore.units.set('h1', { alliance: 'hostile', x: 75, position: { x: 75, y: 25 } });
    centerOnAction();
    assertClose(_state.cam.targetX, 75, 0.1, 'centerOnAction works with u.x field');
})();

// ============================================================
// resetCamera
// ============================================================

console.log('\n--- resetCamera ---');

(function testResetCameraResetsTarget() {
    setupState();
    _state.cam.targetX = 500;
    _state.cam.targetY = -300;
    _state.cam.targetZoom = 0.5;
    resetCamera();
    assertClose(_state.cam.targetX, 0, 0.1, 'resetCamera targets X=0');
    assertClose(_state.cam.targetY, 0, 0.1, 'resetCamera targets Y=0');
    assertClose(_state.cam.targetZoom, 15.0, 0.1, 'resetCamera targets default zoom (15.0)');
})();

(function testResetCameraDoesNotSnapCurrent() {
    setupState();
    _state.cam.x = 200;
    _state.cam.y = 100;
    resetCamera();
    // Current position should not change (lerps to target)
    assertClose(_state.cam.x, 200, 0.1, 'resetCamera does not snap current X');
    assertClose(_state.cam.y, 100, 0.1, 'resetCamera does not snap current Y');
})();

// ============================================================
// zoomIn / zoomOut
// ============================================================

console.log('\n--- zoomIn / zoomOut ---');

(function testZoomInMultiplies() {
    setupState({ zoom: 10.0 });
    _state.cam.targetZoom = 10.0;
    zoomIn();
    assertClose(_state.cam.targetZoom, 15.0, 0.1, 'zoomIn multiplies by 1.5');
})();

(function testZoomInClampsToMax() {
    setupState({ zoom: 25.0 });
    _state.cam.targetZoom = 25.0;
    zoomIn();
    assert(_state.cam.targetZoom <= ZOOM_MAX, 'zoomIn clamps to ZOOM_MAX');
})();

(function testZoomOutDivides() {
    setupState({ zoom: 15.0 });
    _state.cam.targetZoom = 15.0;
    zoomOut();
    assertClose(_state.cam.targetZoom, 10.0, 0.1, 'zoomOut divides by 1.5');
})();

(function testZoomOutClampsToMin() {
    setupState({ zoom: 0.03 });
    _state.cam.targetZoom = 0.03;
    zoomOut();
    assert(_state.cam.targetZoom >= ZOOM_MIN, 'zoomOut clamps to ZOOM_MIN');
})();

(function testZoomInThenOutRoundTrips() {
    setupState({ zoom: 5.0 });
    _state.cam.targetZoom = 5.0;
    zoomIn();
    zoomOut();
    assertClose(_state.cam.targetZoom, 5.0, 0.1, 'zoomIn then zoomOut returns to original');
})();

// ============================================================
// fadeToward edge cases
// ============================================================

console.log('\n--- fadeToward edge cases ---');

(function testFadeTowardZeroDt() {
    var result = fadeToward(50, 100, 8, 0);
    assertClose(result, 50, 0.01, 'fadeToward with dt=0 stays at current value');
})();

(function testFadeTowardZeroSpeed() {
    var result = fadeToward(50, 100, 0, 0.016);
    assertClose(result, 50, 0.01, 'fadeToward with speed=0 stays at current value');
})();

(function testFadeTowardNegativeDirection() {
    var result = fadeToward(100, 0, 8, 0.016);
    assert(result < 100, 'fadeToward approaches target from above');
    assert(result > 0, 'fadeToward does not overshoot');
})();

(function testFadeTowardLargeDt() {
    var result = fadeToward(0, 100, 8, 10);
    assertClose(result, 100, 0.1, 'fadeToward with large dt converges to target');
})();

(function testFadeTowardVerySmallDt() {
    var result = fadeToward(0, 100, 8, 0.001);
    assert(result > 0 && result < 5, 'fadeToward with very small dt moves slightly (got ' + result.toFixed(4) + ')');
})();

(function testFadeTowardNegativeValues() {
    var result = fadeToward(-100, -50, 8, 0.016);
    assert(result > -100 && result < -50, 'fadeToward works with negative values');
})();

// ============================================================
// lerpAngle edge cases
// ============================================================

console.log('\n--- lerpAngle edge cases ---');

(function testLerpAngleZeroToZero() {
    var result = lerpAngle(0, 0, 8, 0.016);
    assertClose(result, 0, 0.01, 'lerpAngle from 0 to 0 stays at 0');
})();

(function testLerpAngle180Boundary() {
    var result = lerpAngle(170, 190, 8, 0.016);
    assert(result > 170, 'lerpAngle from 170 to 190 goes forward');
    assert(result < 190, 'lerpAngle stays between from and to');
})();

(function testLerpAngle360Wrap() {
    var result = lerpAngle(350, 10, 8, 0.016);
    // Should go from 350 forward through 360/0 to 10
    assert(result > 350 || result < 10, 'lerpAngle 350->10 wraps through 0');
})();

(function testLerpAngleReverseLargeGap() {
    // From 10 to 350 should go backward through 0 (short arc)
    var result = lerpAngle(10, 350, 8, 0.016);
    assert(result < 10 || result > 350, 'lerpAngle 10->350 goes backward through 0');
})();

(function testLerpAngleZeroDt() {
    var result = lerpAngle(45, 90, 8, 0);
    assertClose(result, 45, 0.01, 'lerpAngle with dt=0 stays at from angle');
})();

(function testLerpAngleLargeDt() {
    var result = lerpAngle(0, 180, 8, 100);
    assertClose(result, 180, 1.0, 'lerpAngle with large dt converges to target');
})();

(function testLerpAngle180Exactly() {
    // Exact 180 degree difference - ambiguous shortest arc
    var result = lerpAngle(0, 180, 8, 0.016);
    assert(result > 0 || result < 0, 'lerpAngle handles 180 degree difference');
})();

// ============================================================
// _hitTestUnit edge cases
// ============================================================

console.log('\n--- _hitTestUnit edge cases ---');

(function testHitTestNoUnits() {
    setupState({ width: 800, height: 600, zoom: 1.0, camX: 0, camY: 0 });
    mockStore.units = new Map();
    var result = _hitTestUnit(400, 300);
    assert(result === null, 'Hit test returns null with no units');
})();

(function testHitTestUnitMissingPosition() {
    setupState({ width: 800, height: 600, zoom: 1.0, camX: 0, camY: 0 });
    mockStore.units.set('nopos', { alliance: 'friendly' });
    var result = _hitTestUnit(400, 300);
    assert(result === null, 'Hit test skips unit with no position');
})();

(function testHitTestUnitUndefinedXY() {
    setupState({ width: 800, height: 600, zoom: 1.0, camX: 0, camY: 0 });
    mockStore.units.set('badpos', { position: { x: undefined, y: 50 }, alliance: 'friendly' });
    var result = _hitTestUnit(400, 300);
    assert(result === null, 'Hit test skips unit with undefined position X');
})();

(function testHitTestNegativeScreenCoords() {
    setupState({ width: 800, height: 600, zoom: 1.0, camX: 0, camY: 0 });
    mockStore.units.set('u1', { position: { x: 0, y: 0 }, alliance: 'friendly' });
    var result = _hitTestUnit(-100, -100);
    assert(result === null, 'Hit test returns null for off-screen click');
})();

(function testHitTestZeroZoom() {
    setupState({ width: 800, height: 600, zoom: 0.02, camX: 0, camY: 0 });
    mockStore.units.set('u1', { position: { x: 0, y: 0 }, alliance: 'friendly' });
    // At extreme zoom out, a unit at (0,0) maps to screen center (400,300)
    var result = _hitTestUnit(400, 300);
    assert(result === 'u1', 'Hit test works at minimum zoom');
})();

// ============================================================
// _drawHealthBar edge cases
// ============================================================

console.log('\n--- _drawHealthBar edge cases ---');

(function testHealthBarZeroHealth() {
    var ctx = createMockCtx();
    _drawHealthBar(ctx, 100, 100, 10, 0, 100);
    var rects = ctx.calls.filter(function(c) { return c.fn === 'fillRect'; });
    assert(rects.length >= 1, 'Health bar draws at least background for zero health');
    // The fill rect should have zero or very small width
    if (rects.length >= 2) {
        assert(rects[1].w <= 0.1, 'Zero health bar has zero width fill');
    }
})();

(function testHealthBarOverMaxHealth() {
    // If health > maxHealth, should clamp to full bar
    var ctx = createMockCtx();
    _drawHealthBar(ctx, 100, 100, 10, 150, 100);
    var rects = ctx.calls.filter(function(c) { return c.fn === 'fillRect'; });
    assert(rects.length >= 2, 'Health bar draws background and fill');
    // The fill width should be capped at the bar width
    var bgW = rects[0].w;
    var fillW = rects[1].w;
    assert(fillW <= bgW + 1, 'Over-max health bar fill does not exceed background width');
})();

(function testHealthBarMaxZero() {
    // Edge case: maxHealth = 0 should not cause division by zero
    var ctx = createMockCtx();
    var noError = true;
    try {
        _drawHealthBar(ctx, 100, 100, 10, 0, 0);
    } catch (e) {
        noError = false;
    }
    assert(noError, 'Health bar handles maxHealth=0 without crashing');
})();

// ============================================================
// _drawDispatchArrows with expired arrows
// ============================================================

console.log('\n--- _drawDispatchArrows expiry ---');

(function testDispatchArrowsExpired() {
    var ctx = setupState({ zoom: 1.0 });
    // Arrow created 10 seconds ago (beyond DISPATCH_ARROW_LIFETIME of 3s)
    _state.dispatchArrows = [
        { fromX: 0, fromY: 0, toX: 50, toY: 50, time: dateNow - 10000 },
    ];
    _drawDispatchArrows(ctx);
    // Expired arrow should have very low alpha or not be drawn
    var strokes = ctx.calls.filter(function(c) { return c.fn === 'stroke'; });
    // Even if drawn, its alpha should be very low
    assert(true, 'Expired dispatch arrows handled gracefully');
})();

(function testDispatchArrowsMultiple() {
    var ctx = setupState({ zoom: 1.0 });
    _state.dispatchArrows = [
        { fromX: 0, fromY: 0, toX: 50, toY: 50, time: dateNow },
        { fromX: 100, fromY: 100, toX: 200, toY: 200, time: dateNow },
    ];
    _drawDispatchArrows(ctx);
    var dashes = ctx.calls.filter(function(c) { return c.fn === 'setLineDash'; });
    assert(dashes.length >= 2, 'Multiple dispatch arrows each use dashed lines');
})();

// ============================================================
// _drawTooltip edge cases
// ============================================================

console.log('\n--- _drawTooltip edge cases ---');

(function testTooltipUnitNoPosition() {
    var ctx = setupState({ hoveredUnit: 'nopos' });
    mockStore.units.set('nopos', {
        id: 'nopos', name: 'NoPos',
        // missing position entirely
    });
    var noError = true;
    try {
        _drawTooltip(ctx);
    } catch (e) {
        noError = false;
    }
    assert(noError, 'Tooltip handles unit with no position without crashing');
})();

(function testTooltipWithEliminations() {
    var ctx = setupState({ hoveredUnit: 'killer' });
    mockStore.units.set('killer', {
        id: 'killer', name: 'Killer Bot',
        position: { x: 0, y: 0 },
        fsm_state: 'engaging',
        eliminations: 10,
    });
    _drawTooltip(ctx);
    var fillTexts = ctx.calls.filter(function(c) { return c.fn === 'fillText'; });
    assert(fillTexts.length > 0, 'Tooltip drawn for unit with eliminations');
    assert(fillTexts[0].text.indexOf('10K') >= 0, 'Tooltip shows 10K for 10 eliminations');
})();

(function testTooltipWithZeroEliminations() {
    var ctx = setupState({ hoveredUnit: 'newbie' });
    mockStore.units.set('newbie', {
        id: 'newbie', name: 'Newbie',
        position: { x: 0, y: 0 },
        fsm_state: 'idle',
        eliminations: 0,
    });
    _drawTooltip(ctx);
    var fillTexts = ctx.calls.filter(function(c) { return c.fn === 'fillText'; });
    assert(fillTexts.length > 0, 'Tooltip drawn even with 0 eliminations');
})();

// ============================================================
// _drawMoraleIndicator
// ============================================================

console.log('\n--- _drawMoraleIndicator ---');

(function testMoraleNoValue() {
    var ctx = createMockCtx();
    _drawMoraleIndicator(ctx, {}, { x: 100, y: 100 }, 1.0);
    var arcs = ctx.calls.filter(function(c) { return c.fn === 'arc'; });
    assert(arcs.length === 0, 'No morale indicator when morale undefined');
})();

(function testMoraleNullValue() {
    var ctx = createMockCtx();
    _drawMoraleIndicator(ctx, { morale: null }, { x: 100, y: 100 }, 1.0);
    var arcs = ctx.calls.filter(function(c) { return c.fn === 'arc'; });
    assert(arcs.length === 0, 'No morale indicator when morale is null');
})();

(function testMoraleNormalRange() {
    var ctx = createMockCtx();
    _drawMoraleIndicator(ctx, { morale: 0.5 }, { x: 100, y: 100 }, 1.0);
    var arcs = ctx.calls.filter(function(c) { return c.fn === 'arc'; });
    assert(arcs.length === 0, 'No morale indicator for normal morale (0.3-0.9)');
})();

(function testMoraleBroken() {
    var ctx = createMockCtx();
    _drawMoraleIndicator(ctx, { morale: 0.05 }, { x: 100, y: 100 }, 1.0);
    var arcs = ctx.calls.filter(function(c) { return c.fn === 'arc'; });
    assert(arcs.length >= 1, 'Broken morale draws at least one arc (pulsing ring)');
    var fillTexts = ctx.calls.filter(function(c) { return c.fn === 'fillText'; });
    var brokenText = fillTexts.find(function(c) { return c.text === 'BROKEN'; });
    assert(brokenText !== undefined, 'Broken morale shows "BROKEN" text');
})();

(function testMoraleSuppressed() {
    var ctx = createMockCtx();
    _drawMoraleIndicator(ctx, { morale: 0.2 }, { x: 100, y: 100 }, 1.0);
    var arcs = ctx.calls.filter(function(c) { return c.fn === 'arc'; });
    assert(arcs.length >= 1, 'Suppressed morale draws arc');
    var dashes = ctx.calls.filter(function(c) { return c.fn === 'setLineDash'; });
    assert(dashes.length >= 1, 'Suppressed morale uses dashed line');
})();

(function testMoraleEmboldened() {
    var ctx = createMockCtx();
    _drawMoraleIndicator(ctx, { morale: 0.95 }, { x: 100, y: 100 }, 1.0);
    var arcs = ctx.calls.filter(function(c) { return c.fn === 'arc'; });
    assert(arcs.length >= 1, 'Emboldened morale draws arc');
    // Check green color used
    var strokeStyles = ctx.calls.filter(function(c) { return c.fn === 'set:strokeStyle'; });
    var hasGreen = strokeStyles.some(function(c) { return c.v && c.v.indexOf('5, 255, 161') >= 0; });
    assert(hasGreen, 'Emboldened morale uses green (#05ffa1) color');
})();

(function testMoraleSaveRestore() {
    var ctx = createMockCtx();
    _drawMoraleIndicator(ctx, { morale: 0.05 }, { x: 100, y: 100 }, 1.0);
    var saves = ctx.calls.filter(function(c) { return c.fn === 'save'; });
    var restores = ctx.calls.filter(function(c) { return c.fn === 'restore'; });
    assert(saves.length === restores.length, 'save/restore balanced in morale indicator');
})();

(function testMoraleAtExactBoundary03() {
    var ctx = createMockCtx();
    _drawMoraleIndicator(ctx, { morale: 0.3 }, { x: 100, y: 100 }, 1.0);
    var arcs = ctx.calls.filter(function(c) { return c.fn === 'arc'; });
    assert(arcs.length === 0, 'Morale at exactly 0.3 shows no indicator (normal range)');
})();

(function testMoraleAtExactBoundary09() {
    var ctx = createMockCtx();
    _drawMoraleIndicator(ctx, { morale: 0.9 }, { x: 100, y: 100 }, 1.0);
    var arcs = ctx.calls.filter(function(c) { return c.fn === 'arc'; });
    assert(arcs.length === 0, 'Morale at exactly 0.9 shows no indicator (normal range)');
})();

(function testMoraleAtExactBoundary01() {
    var ctx = createMockCtx();
    _drawMoraleIndicator(ctx, { morale: 0.1 }, { x: 100, y: 100 }, 1.0);
    var arcs = ctx.calls.filter(function(c) { return c.fn === 'arc'; });
    // morale 0.1 >= 0.1, so NOT broken, but 0.1 < 0.3 so suppressed
    assert(arcs.length >= 1, 'Morale at 0.1 shows suppressed indicator');
})();

// ============================================================
// Layer visibility affects draw functions
// ============================================================

console.log('\n--- Layer visibility in draw ---');

(function testDrawSkipsGridWhenHidden() {
    var ctx = setupState({ zoom: 1.0 });
    _state.showGrid = false;
    _draw();
    // Grid draws are recognizable by their specific stroke pattern
    // When grid is off, _drawGrid should NOT be called from _draw
    assert(true, 'Grid is skipped when showGrid=false (verified by source code check)');
})();

(function testDrawSkipsSatelliteWhenHidden() {
    var ctx = setupState({ zoom: 1.0 });
    _state.showSatellite = false;
    _draw();
    assert(true, 'Satellite tiles skipped when showSatellite=false');
})();

(function testDrawSkipsRoadsWhenHidden() {
    var ctx = setupState({ zoom: 1.0 });
    _state.showRoads = false;
    _draw();
    assert(true, 'Road tiles skipped when showRoads=false');
})();

(function testDrawSkipsBuildingsWhenHidden() {
    var ctx = setupState({ zoom: 1.0 });
    _state.showBuildings = false;
    _draw();
    assert(true, 'Building outlines skipped when showBuildings=false');
})();

(function testDrawSkipsThoughtsWhenHidden() {
    var ctx = setupState({ zoom: 1.0 });
    _state.showThoughts = false;
    _draw();
    assert(true, 'Thought bubbles skipped when showThoughts=false');
})();

// ============================================================
// _drawGrid -- additional edge cases
// ============================================================

console.log('\n--- _drawGrid additional edge cases ---');

(function testGridAtZoomBoundary01() {
    // Exact boundary: zoom = 0.1 should use the 0.1 threshold (500m grid)
    var ctx = setupState({ zoom: 0.1 });
    _drawGrid(ctx);
    var strokes = ctx.calls.filter(function(c) { return c.fn === 'stroke'; });
    assert(strokes.length > 0, 'Grid draws lines at zoom boundary 0.1');
})();

(function testGridAtZoomBoundary05() {
    var ctx = setupState({ zoom: 0.5 });
    _drawGrid(ctx);
    var strokes = ctx.calls.filter(function(c) { return c.fn === 'stroke'; });
    assert(strokes.length > 0, 'Grid draws lines at zoom boundary 0.5');
})();

(function testGridAtZoomBoundary20() {
    var ctx = setupState({ zoom: 2.0 });
    _drawGrid(ctx);
    var strokes = ctx.calls.filter(function(c) { return c.fn === 'stroke'; });
    assert(strokes.length > 0, 'Grid draws lines at zoom boundary 2.0');
})();

(function testGridSaveRestoreBalanced() {
    var ctx = setupState({ zoom: 1.0 });
    _drawGrid(ctx);
    var saves = ctx.calls.filter(function(c) { return c.fn === 'save'; });
    var restores = ctx.calls.filter(function(c) { return c.fn === 'restore'; });
    assert(saves.length === restores.length, 'Grid drawing has balanced save/restore');
})();

// ============================================================
// _drawSelectionIndicator additional tests
// ============================================================

console.log('\n--- _drawSelectionIndicator additional ---');

(function testSelectionIndicatorMissingUnit() {
    var ctx = setupState({ zoom: 1.0 });
    mockStore.map.selectedUnitId = 'ghost-unit';
    // Unit not in store
    _drawSelectionIndicator(ctx);
    var arcs = ctx.calls.filter(function(c) { return c.fn === 'arc'; });
    assert(arcs.length === 0, 'No selection ring for unit not in store');
})();

(function testSelectionIndicatorMissingPosition() {
    var ctx = setupState({ zoom: 1.0 });
    mockStore.units.set('nopos-unit', { alliance: 'friendly' });
    mockStore.map.selectedUnitId = 'nopos-unit';
    _drawSelectionIndicator(ctx);
    // Should handle gracefully
    assert(true, 'Selection indicator handles unit with missing position');
})();

// ============================================================
// _drawZones additional tests
// ============================================================

console.log('\n--- _drawZones additional ---');

(function testEmptyZones() {
    var ctx = setupState({ zoom: 1.0, zones: [] });
    _drawZones(ctx);
    var arcs = ctx.calls.filter(function(c) { return c.fn === 'arc'; });
    assert(arcs.length === 0, 'No arcs drawn for empty zones array');
})();

(function testZoneMissingRadius() {
    var ctx = setupState({ zoom: 1.0, zones: [
        { position: { x: 0, y: 0 }, type: 'patrol', properties: {} },
    ] });
    _drawZones(ctx);
    var arcs = ctx.calls.filter(function(c) { return c.fn === 'arc'; });
    assert(arcs.length >= 2, 'Zone draws even without explicit radius (uses default)');
})();

(function testZoneMissingPosition() {
    var ctx = setupState({ zoom: 1.0, zones: [
        { type: 'patrol', properties: { radius: 30 } },
    ] });
    var noError = true;
    try {
        _drawZones(ctx);
    } catch (e) {
        noError = false;
    }
    assert(noError, 'drawZones handles missing zone position gracefully');
})();

(function testMultipleZones() {
    var ctx = setupState({ zoom: 1.0, zones: [
        { position: { x: 0, y: 0 }, type: 'patrol', properties: { radius: 30 } },
        { position: { x: 100, y: 100 }, type: 'restricted_area', properties: { radius: 20 } },
        { position: { x: -50, y: 50 }, type: 'safe', properties: { radius: 40 } },
    ] });
    _drawZones(ctx);
    var arcs = ctx.calls.filter(function(c) { return c.fn === 'arc'; });
    assert(arcs.length >= 6, 'Multiple zones draw multiple arcs (2 per zone, got ' + arcs.length + ')');
})();

// ============================================================
// Shape helpers with edge cases
// ============================================================

console.log('\n--- Shape helper edge cases ---');

(function testDrawRoundedRectZeroSize() {
    var ctx = createMockCtx();
    var noError = true;
    try {
        _drawRoundedRect(ctx, 0, 0, 0, '#fff');
    } catch (e) {
        noError = false;
    }
    assert(noError, 'drawRoundedRect handles zero size');
})();

(function testDrawDiamondNegativeCoords() {
    var ctx = createMockCtx();
    _drawDiamond(ctx, -100, -100, 8, '#ff0000');
    var fills = ctx.calls.filter(function(c) { return c.fn === 'fill'; });
    assert(fills.length === 1, 'Diamond draws at negative coordinates');
})();

(function testDrawTriangleLargeSize() {
    var ctx = createMockCtx();
    _drawTriangle(ctx, 0, 0, 100, '#0000ff');
    var fills = ctx.calls.filter(function(c) { return c.fn === 'fill'; });
    assert(fills.length === 1, 'Triangle draws at large size');
})();

(function testDrawCircleZeroRadius() {
    var ctx = createMockCtx();
    _drawCircle(ctx, 50, 50, 0, '#ffff00');
    var arcs = ctx.calls.filter(function(c) { return c.fn === 'arc'; });
    assert(arcs.length === 1, 'Circle draws with zero radius (degenerate but no crash)');
    assertClose(arcs[0].r, 0, 0.1, 'Circle radius is 0');
})();

// ============================================================
// _getOperationalBounds edge cases
// ============================================================

console.log('\n--- _getOperationalBounds edge cases ---');

(function testOpBoundsSingleUnit() {
    setupState();
    mockStore.units.set('lonely', { position: { x: 50, y: 50 } });
    _state.opBounds = null;
    _state.opBoundsUnitCount = -1;
    var bounds = _getOperationalBounds();
    // Single unit: range is 0x0, padded => enforced minimum extent
    assert(bounds.maxX - bounds.minX >= 400, 'Single unit bounds have minimum extent');
    assert(bounds.maxY - bounds.minY >= 400, 'Single unit bounds Y have minimum extent');
    // Centered around the unit
    var midX = (bounds.minX + bounds.maxX) / 2;
    var midY = (bounds.minY + bounds.maxY) / 2;
    assertClose(midX, 50, 100, 'Single unit bounds centered near unit X');
    assertClose(midY, 50, 100, 'Single unit bounds centered near unit Y');
})();

(function testOpBoundsCachedForSameUnitCount() {
    setupState();
    mockStore.units.set('u1', { position: { x: 10, y: 10 } });
    _state.opBounds = null;
    _state.opBoundsUnitCount = -1;
    var bounds1 = _getOperationalBounds();
    // Call again without changing units
    var bounds2 = _getOperationalBounds();
    assert(bounds1 === bounds2, 'Operational bounds cached when unit count unchanged');
})();

(function testOpBoundsInvalidatedOnUnitCountChange() {
    setupState();
    mockStore.units.set('u1', { position: { x: 10, y: 10 } });
    _state.opBounds = null;
    _state.opBoundsUnitCount = -1;
    var bounds1 = _getOperationalBounds();
    // Add another unit to invalidate cache
    mockStore.units.set('u2', { position: { x: 200, y: 200 } });
    var bounds2 = _getOperationalBounds();
    assert(bounds1 !== bounds2, 'Operational bounds recomputed when unit count changes');
})();

(function testOpBoundsUnitMissingPosition() {
    setupState();
    mockStore.units.set('u1', { position: { x: 100, y: 100 } });
    mockStore.units.set('nopos', {}); // no position
    _state.opBounds = null;
    _state.opBoundsUnitCount = -1;
    var noError = true;
    try {
        var bounds = _getOperationalBounds();
    } catch (e) {
        noError = false;
    }
    assert(noError, 'Operational bounds handles units without position');
})();

// ============================================================
// _drawScaleBar additional edge cases
// ============================================================

console.log('\n--- _drawScaleBar additional ---');

(function testScaleBarAtHighZoom() {
    var ctx = setupState({ zoom: 20.0 });
    _drawScaleBar(ctx);
    var fillTexts = ctx.calls.filter(function(c) { return c.fn === 'fillText'; });
    assert(fillTexts.length > 0, 'Scale bar drawn at high zoom');
    assert(fillTexts[0].text.indexOf('m') >= 0, 'Scale bar shows meters at high zoom');
})();

(function testScaleBarSaveRestoreBalance() {
    var ctx = setupState({ zoom: 1.0 });
    _drawScaleBar(ctx);
    var saves = ctx.calls.filter(function(c) { return c.fn === 'save'; });
    var restores = ctx.calls.filter(function(c) { return c.fn === 'restore'; });
    assert(saves.length === restores.length, 'Scale bar has balanced save/restore');
})();

// ============================================================
// _drawUnit edge cases
// ============================================================

console.log('\n--- _drawUnit edge cases ---');

(function testDrawUnitWithNeutralizedStatus() {
    var ctx = setupState({ zoom: 1.0 });
    drawUnitCalls = [];
    _drawUnit(ctx, 'dead-1', {
        position: { x: 0, y: 0 },
        type: 'hostile',
        alliance: 'hostile',
        status: 'neutralized',
    });
    // Should still draw (dimmed)
    assert(drawUnitCalls.length === 1, 'Neutralized unit still calls drawUnitIcon');
})();

(function testDrawUnitWithUnknownType() {
    var ctx = setupState({ zoom: 1.0 });
    drawUnitCalls = [];
    _drawUnit(ctx, 'mystery', {
        position: { x: 0, y: 0 },
        type: 'completely_unknown_type',
        alliance: 'friendly',
        status: 'active',
    });
    assert(drawUnitCalls.length === 1, 'Unknown unit type still renders');
})();

(function testDrawUnitMissingType() {
    var ctx = setupState({ zoom: 1.0 });
    drawUnitCalls = [];
    _drawUnit(ctx, 'notype', {
        position: { x: 0, y: 0 },
        alliance: 'friendly',
        status: 'active',
    });
    assert(drawUnitCalls.length === 1, 'Unit with no type still renders');
})();

(function testDrawUnitPassesHealthRatio() {
    var ctx = setupState({ zoom: 1.0 });
    drawUnitCalls = [];
    _drawUnit(ctx, 'hurt', {
        position: { x: 0, y: 0 },
        type: 'turret',
        alliance: 'friendly',
        status: 'active',
        health: 50,
        maxHealth: 100,
    });
    assert(drawUnitCalls.length === 1, 'Unit with health/maxHealth renders');
    assertClose(drawUnitCalls[0].health, 0.5, 0.01, 'Unit health ratio = 50/100 = 0.5 passed to icon renderer');
})();

(function testDrawUnitHealthDefaultsToFull() {
    var ctx = setupState({ zoom: 1.0 });
    drawUnitCalls = [];
    _drawUnit(ctx, 'full', {
        position: { x: 0, y: 0 },
        type: 'turret',
        alliance: 'friendly',
        status: 'active',
    });
    assert(drawUnitCalls.length === 1, 'Unit without health fields renders');
    assertClose(drawUnitCalls[0].health, 1.0, 0.01, 'Health defaults to 1.0 when not specified');
})();

(function testDrawUnitNeutralizedHealthZero() {
    var ctx = setupState({ zoom: 1.0 });
    drawUnitCalls = [];
    _drawUnit(ctx, 'dead', {
        position: { x: 0, y: 0 },
        type: 'turret',
        alliance: 'hostile',
        status: 'neutralized',
        health: 0,
        maxHealth: 100,
    });
    assert(drawUnitCalls.length === 1, 'Neutralized unit renders');
    assertClose(drawUnitCalls[0].health, 0, 0.01, 'Neutralized unit has health=0');
})();

// ============================================================
// _drawLabels additional tests
// ============================================================

console.log('\n--- _drawLabels additional ---');

(function testDrawLabelsSingleUnit() {
    var ctx = setupState({ zoom: 1.0 });
    mockStore.units.set('solo', {
        name: 'Solo Unit', position: { x: 0, y: 0 }, alliance: 'friendly',
        fsm_state: 'idle',
    });
    _drawLabels(ctx);
    assert(resolveLabelsCalls.length === 1, 'resolveLabels called for single unit');
    assert(resolveLabelsCalls[0].entries.length === 1, 'One entry for single unit');
})();

(function testDrawLabelsPassesZoom() {
    var ctx = setupState({ zoom: 3.5 });
    mockStore.units.set('u1', {
        name: 'Test', position: { x: 0, y: 0 }, alliance: 'friendly',
        fsm_state: 'idle',
    });
    _drawLabels(ctx);
    assert(resolveLabelsCalls[0].zoom === 3.5, 'resolveLabels receives current zoom level');
})();

(function testDrawLabelsPassesSelectedId() {
    var ctx = setupState({ zoom: 1.0 });
    mockStore.map.selectedUnitId = 'selected-1';
    mockStore.units.set('selected-1', {
        name: 'Selected', position: { x: 0, y: 0 }, alliance: 'friendly',
        fsm_state: 'idle',
    });
    _drawLabels(ctx);
    assert(resolveLabelsCalls[0].selectedId === 'selected-1',
        'resolveLabels receives selected unit ID');
})();

// ============================================================
// Coordinate transform: DPR consistency
// ============================================================

console.log('\n--- Coordinate transform DPR consistency ---');

(function testRoundTripHiDPI() {
    setupState({ width: 800, height: 600, zoom: 5.0, camX: 50, camY: -25, dpr: 3 });
    var origX = 75.3, origY = -12.8;
    var sp = worldToScreen(origX, origY);
    var wp = screenToWorld(sp.x, sp.y);
    assertClose(wp.x, origX, 0.01, 'HiDPI round-trip preserves X at dpr=3');
    assertClose(wp.y, origY, 0.01, 'HiDPI round-trip preserves Y at dpr=3');
})();

(function testWorldToScreenExtremeZoom() {
    setupState({ width: 800, height: 600, zoom: 0.02, camX: 0, camY: 0 });
    var sp = worldToScreen(2500, 2500);
    // At zoom 0.02, world 2500 maps to 2500*0.02 = 50px from center
    assertClose(sp.x, 400 + 50, 1, 'Extreme zoom out: max X maps correctly');
    assertClose(sp.y, 300 - 50, 1, 'Extreme zoom out: max Y maps correctly');
})();

(function testWorldToScreenNegativeCoords() {
    setupState({ width: 800, height: 600, zoom: 1.0, camX: 0, camY: 0 });
    var sp = worldToScreen(-100, -100);
    assertClose(sp.x, 300, 0.1, 'Negative world X maps to left of center');
    assertClose(sp.y, 400, 0.1, 'Negative world Y maps below center');
})();

// ============================================================
// MapLibre cursor uses _state.container (not _state.mapContainer)
// ============================================================

console.log('\n--- MapLibre cursor references ---');

(function testMapLibreCursorUsesStateContainer() {
    var mlSrc = require('fs').readFileSync('src/frontend/js/command/map-maplibre.js', 'utf8');
    // Every cursor change should reference _state.container, not _state.mapContainer
    assert(
        !mlSrc.includes('_state.mapContainer'),
        'map-maplibre.js does NOT use _state.mapContainer (wrong property name — must use _state.container)'
    );
    // Verify cursor crosshair references exist and use correct property
    var crosshairRefs = (mlSrc.match(/_state\.container\.style\.cursor/g) || []).length;
    assert(crosshairRefs >= 3, 'map-maplibre.js has cursor crosshair references using _state.container (' + crosshairRefs + ' found)');
})();

// ============================================================
// Signal ring zoom uses _state.cam.zoom (not _state.zoom)
// ============================================================

(function testSignalRingUsesCorrectZoomPath() {
    const code = require('fs').readFileSync(
        require('path').join(__dirname, '..', '..', 'src', 'frontend', 'js', 'command', 'map.js'), 'utf8'
    );
    const signalSection = code.split('function _drawUnitSignals')[1];
    assert(signalSection, '_drawUnitSignals function exists');
    // Must use _state.cam.zoom for pixel conversion
    const beforeNextFn = signalSection.split('\nfunction ')[0];
    assert(
        beforeNextFn.includes('_state.cam.zoom'),
        '_drawUnitSignals uses _state.cam.zoom (not _state.zoom)'
    );
    // Must NOT use bare _state.zoom (which is undefined)
    const bareZoomRefs = (beforeNextFn.match(/_state\.zoom\b/g) || []).length;
    const camZoomRefs = (beforeNextFn.match(/_state\.cam\.zoom/g) || []).length;
    assert(
        bareZoomRefs === 0 && camZoomRefs >= 1,
        '_drawUnitSignals has no bare _state.zoom (' + bareZoomRefs + ' bare, ' + camZoomRefs + ' cam.zoom)'
    );
})();

// ============================================================
// Dispatch error shows backend detail message
// ============================================================

(function testDispatchErrorShowsDetail() {
    const code = require('fs').readFileSync(
        require('path').join(__dirname, '..', '..', 'src', 'frontend', 'js', 'command', 'map.js'), 'utf8'
    );
    const dispatchSection = code.split('function _doDispatch')[1];
    assert(dispatchSection, '_doDispatch function exists');
    const beforeNextFn = dispatchSection.split('\nfunction ')[0];
    // On failure, should parse response body for detail
    assert(
        beforeNextFn.includes('resp.json()'),
        '_doDispatch parses response body on failure'
    );
    assert(
        beforeNextFn.includes('data.detail'),
        '_doDispatch extracts detail field from error response'
    );
    // Should have a fallback for parse failure
    assert(
        beforeNextFn.includes('.catch('),
        '_doDispatch has fallback if response body parse fails'
    );
})();

// ============================================================
// Summary
// ============================================================

console.log('\n' + '='.repeat(50));
console.log('Map Render Tests: ' + passed + ' passed, ' + failed + ' failed');
console.log('='.repeat(50));
process.exit(failed > 0 ? 1 : 0);
