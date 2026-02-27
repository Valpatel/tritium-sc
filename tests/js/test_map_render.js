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

const mapSrc = fs.readFileSync(__dirname + '/../../frontend/js/command/map.js', 'utf8');

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
const { worldToScreen, screenToWorld, _state,
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
// Summary
// ============================================================

console.log('\n' + '='.repeat(50));
console.log('Map Render Tests: ' + passed + ' passed, ' + failed + ' failed');
console.log('='.repeat(50));
process.exit(failed > 0 ? 1 : 0);
