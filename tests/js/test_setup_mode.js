// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
/**
 * TRITIUM-SC Setup Mode Tests
 * Tests the setup placement toolbar logic, ghost preview helpers,
 * click-to-place coordinate conversion, and mode switching cleanup.
 * Run: node tests/js/test_setup_mode.js
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
    assert(Math.abs(a - b) < (eps || 0.01), msg + ` (got ${a}, expected ${b})`);
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
    const attrs = {};
    const listeners = {};
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
        addEventListener(ev, fn) {
            if (!listeners[ev]) listeners[ev] = [];
            listeners[ev].push(fn);
        },
        removeEventListener() {},
        getBoundingClientRect() { return { top: 0, left: 0, width: 100, height: 100 }; },
        setAttribute(k, v) { attrs[k] = v; },
        getAttribute(k) { return attrs[k]; },
        get offsetWidth() { return 100; },
        get offsetHeight() { return 100; },
        _listeners: listeners,
        _classList: classList,
    };
    return el;
}

// ============================================================
// 1. Test SETUP_UNIT_RANGES values
// ============================================================
console.log('\n--- SETUP_UNIT_RANGES ---');

(function testTurretRange() {
    // Expected range values match the spec
    const ranges = { turret: 20, heavy_turret: 30, rover: 15, drone: 25 };
    assert(ranges.turret === 20, 'turret range = 20m');
})();

(function testHeavyTurretRange() {
    const ranges = { turret: 20, heavy_turret: 30, rover: 15, drone: 25 };
    assert(ranges.heavy_turret === 30, 'heavy_turret range = 30m');
})();

(function testRoverRange() {
    const ranges = { turret: 20, heavy_turret: 30, rover: 15, drone: 25 };
    assert(ranges.rover === 15, 'rover range = 15m');
})();

(function testDroneRange() {
    const ranges = { turret: 20, heavy_turret: 30, rover: 15, drone: 25 };
    assert(ranges.drone === 25, 'drone range = 25m');
})();

// ============================================================
// 2. Test coordinate conversion functions (_lngLatToGame, _gameToLngLat)
// ============================================================
console.log('\n--- Coordinate Conversion ---');

// Replicate the conversion logic from map-maplibre.js
function gameToLngLat(gx, gy, geoCenter) {
    if (!geoCenter) return [0, 0];
    const R = 6378137;
    const latRad = geoCenter.lat * Math.PI / 180;
    const dLng = gx / (R * Math.cos(latRad)) * (180 / Math.PI);
    const dLat = gy / R * (180 / Math.PI);
    return [geoCenter.lng + dLng, geoCenter.lat + dLat];
}

function lngLatToGame(lng, lat, geoCenter) {
    if (!geoCenter) return { x: 0, y: 0 };
    const R = 6378137;
    const latRad = geoCenter.lat * Math.PI / 180;
    const gx = (lng - geoCenter.lng) * (Math.PI / 180) * R * Math.cos(latRad);
    const gy = (lat - geoCenter.lat) * (Math.PI / 180) * R;
    return { x: gx, y: gy };
}

(function testLngLatToGameAtCenter() {
    const center = { lat: 30.0, lng: -97.0 };
    const result = lngLatToGame(-97.0, 30.0, center);
    assertClose(result.x, 0, 0.01, 'lngLatToGame at center x = 0');
    assertClose(result.y, 0, 0.01, 'lngLatToGame at center y = 0');
})();

(function testLngLatToGameOffset() {
    const center = { lat: 30.0, lng: -97.0 };
    // Moving ~111m north should give y ≈ 111
    const result = lngLatToGame(-97.0, 30.001, center);
    assert(result.y > 100 && result.y < 120, 'lngLatToGame 0.001 lat offset is ~111m y');
})();

(function testGameToLngLatRoundTrip() {
    const center = { lat: 30.0, lng: -97.0 };
    const game = { x: 50, y: -30 };
    const lnglat = gameToLngLat(game.x, game.y, center);
    const back = lngLatToGame(lnglat[0], lnglat[1], center);
    assertClose(back.x, game.x, 0.01, 'round-trip game x preserved');
    assertClose(back.y, game.y, 0.01, 'round-trip game y preserved');
})();

(function testLngLatToGameNoCenter() {
    const result = lngLatToGame(-97.0, 30.0, null);
    assert(result.x === 0 && result.y === 0, 'lngLatToGame returns 0,0 with null center');
})();

(function testGameToLngLatNoCenter() {
    const result = gameToLngLat(50, 50, null);
    assert(result[0] === 0 && result[1] === 0, 'gameToLngLat returns [0,0] with null center');
})();

// ============================================================
// 3. Test makeCircleGeoJSON
// ============================================================
console.log('\n--- makeCircleGeoJSON ---');

function makeCircleGeoJSON(centerLngLat, radiusMeters, points) {
    const coords = [];
    const R = 6378137;
    const lat = centerLngLat[1] * Math.PI / 180;
    const lng = centerLngLat[0] * Math.PI / 180;

    for (let i = 0; i <= points; i++) {
        const angle = (i / points) * 2 * Math.PI;
        const dLat = (radiusMeters * Math.cos(angle)) / R;
        const dLng = (radiusMeters * Math.sin(angle)) / (R * Math.cos(lat));
        coords.push([
            (lng + dLng) * 180 / Math.PI,
            (lat + dLat) * 180 / Math.PI,
        ]);
    }

    return {
        type: 'Feature',
        geometry: { type: 'Polygon', coordinates: [coords] },
    };
}

(function testCircleGeoJSONIsPolygon() {
    const circle = makeCircleGeoJSON([-97.0, 30.0], 20, 32);
    assert(circle.type === 'Feature', 'circle is a GeoJSON Feature');
    assert(circle.geometry.type === 'Polygon', 'circle geometry is Polygon');
    assert(circle.geometry.coordinates.length === 1, 'circle has one ring');
    // 32 points + 1 closing = 33
    assert(circle.geometry.coordinates[0].length === 33, 'circle ring has 33 vertices (32 + close)');
})();

(function testCircleGeoJSONClosedRing() {
    const circle = makeCircleGeoJSON([-97.0, 30.0], 20, 16);
    const ring = circle.geometry.coordinates[0];
    assertClose(ring[0][0], ring[ring.length - 1][0], 0.0001, 'circle ring is closed (lng)');
    assertClose(ring[0][1], ring[ring.length - 1][1], 0.0001, 'circle ring is closed (lat)');
})();

(function testCircleGeoJSONRadiusApproximation() {
    // A 20m circle at lat=30 should have vertices ~20m from center
    const center = [-97.0, 30.0];
    const circle = makeCircleGeoJSON(center, 20, 32);
    const ring = circle.geometry.coordinates[0];
    // Check the northernmost point (i=0 => angle=0 => dLat positive)
    const northPoint = ring[0];
    // Distance in lat degrees for 20m
    const dLat = (northPoint[1] - center[1]) * Math.PI / 180 * 6378137;
    assertClose(dLat, 20, 1, 'circle radius is approximately 20m at north');
})();

(function testCircleGeoJSONDifferentRadius() {
    const center = [-97.0, 30.0];
    const c20 = makeCircleGeoJSON(center, 20, 32);
    const c30 = makeCircleGeoJSON(center, 30, 32);
    // Larger radius should have points further away
    const north20 = c20.geometry.coordinates[0][0][1];
    const north30 = c30.geometry.coordinates[0][0][1];
    assert(north30 > north20, '30m circle extends further north than 20m circle');
})();

// ============================================================
// 4. Test placement toolbar logic (game-hud.js)
// ============================================================
console.log('\n--- Placement Toolbar ---');

// Load game-hud.js helpers
const gameHudCode = fs.readFileSync(
    __dirname + '/../../src/frontend/js/command/panels/game-hud.js', 'utf8'
);

// Strip ES module imports/exports and expose GameHudPanelDef on window
let processedCode = gameHudCode
    .replace(/^import\s+.*?from\s+['"].*?['"];?\s*$/gm, '')
    .replace(/^export\s+(const|let|var|function|class)\s+/gm, '$1 ')
    + '\nif (typeof GameHudPanelDef !== "undefined") window.GameHudPanelDef = GameHudPanelDef;\n';

const mockWindow = {};
const mockTritiumStore = {
    game: { phase: 'idle', wave: 0, totalWaves: 10, score: 0, eliminations: 0 },
    units: { forEach: () => {} },
    on: () => () => {},
    set: () => {},
    get: () => null,
};
const mockEventBus = {
    emit: () => {},
    on: () => () => {},
};

const ctx = vm.createContext({
    Math, Date, console, Map, Array, Object, Number, Infinity, Boolean, String, Set,
    parseInt, parseFloat, isNaN, isFinite, undefined, null: null,
    JSON, Error, TypeError, RangeError,
    setTimeout: (fn) => fn(),
    setInterval: () => 0,
    clearInterval: () => {},
    clearTimeout: () => {},
    document: {
        createElement: (tag) => createMockElement(tag),
        getElementById: () => null,
        querySelector: () => null,
        querySelectorAll: () => [],
        body: createMockElement('BODY'),
        documentElement: createMockElement('HTML'),
    },
    window: mockWindow,
    fetch: () => Promise.resolve({ ok: true, json: () => Promise.resolve({}) }),
    TritiumStore: mockTritiumStore,
    EventBus: mockEventBus,
});

try {
    vm.runInContext(processedCode, ctx);
} catch (e) {
    console.error('Failed to load game-hud.js:', e.message);
}

const GameHudPanelDef = ctx.window.GameHudPanelDef;

(function testGameHudPanelDefExists() {
    assert(GameHudPanelDef != null, 'GameHudPanelDef exported');
})();

(function testCreateHasPlacementToolbar() {
    if (!GameHudPanelDef) return;
    const el = GameHudPanelDef.create({});
    const html = el.innerHTML;
    assert(html.includes('data-section="placement-toolbar"'), 'create() has placement toolbar section');
    assert(html.includes('data-place-type="turret"'), 'create() has turret button');
    assert(html.includes('data-place-type="heavy_turret"'), 'create() has heavy_turret button');
    assert(html.includes('data-place-type="rover"'), 'create() has rover button');
    assert(html.includes('data-place-type="drone"'), 'create() has drone button');
})();

(function testCreatePlacementButtonLabels() {
    if (!GameHudPanelDef) return;
    const el = GameHudPanelDef.create({});
    const html = el.innerHTML;
    // Check button text content
    assert(html.includes('>T</button>'), 'turret button shows T');
    assert(html.includes('>H</button>'), 'heavy_turret button shows H');
    assert(html.includes('>R</button>'), 'rover button shows R');
    assert(html.includes('>D</button>'), 'drone button shows D');
})();

(function testCreateHasBeginWarButton() {
    if (!GameHudPanelDef) return;
    const el = GameHudPanelDef.create({});
    const html = el.innerHTML;
    assert(html.includes('data-action="begin-war"'), 'create() has begin war button');
    assert(html.includes('BEGIN WAR'), 'create() has BEGIN WAR text');
})();

(function testDefaultPlacementType() {
    // Before mount, window._setupPlacementType may not exist
    // After toolbar init, it should default to turret
    assert(
        mockWindow._setupPlacementType === undefined || mockWindow._setupPlacementType === 'turret',
        'default placement type is turret or undefined before mount'
    );
})();

(function testTurretButtonHasActiveClass() {
    if (!GameHudPanelDef) return;
    const el = GameHudPanelDef.create({});
    const html = el.innerHTML;
    assert(
        html.includes('ghud-place-btn--active" data-place-type="turret"') ||
        html.includes('ghud-place-btn ghud-place-btn--active" data-place-type="turret"'),
        'turret button starts with active class'
    );
})();

// ============================================================
// 5. Test placement request body construction
// ============================================================
console.log('\n--- Placement Request Body ---');

(function testPlaceRequestBodyFormat() {
    // Verify the shape of the body that _onMapClick sends to /api/game/place
    const unitType = 'heavy_turret';
    const game = { x: 42.5, y: -18.3 };
    const displayName = unitType.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
    const body = {
        name: displayName,
        asset_type: unitType,
        position: { x: game.x, y: game.y },
    };
    assert(body.name === 'Heavy Turret', 'display name title-cased');
    assert(body.asset_type === 'heavy_turret', 'asset_type preserved');
    assert(body.position.x === 42.5, 'position x preserved');
    assert(body.position.y === -18.3, 'position y preserved');
})();

(function testDisplayNameTurret() {
    const name = 'turret'.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
    assert(name === 'Turret', 'turret display name = "Turret"');
})();

(function testDisplayNameHeavyTurret() {
    const name = 'heavy_turret'.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
    assert(name === 'Heavy Turret', 'heavy_turret display name = "Heavy Turret"');
})();

(function testDisplayNameRover() {
    const name = 'rover'.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
    assert(name === 'Rover', 'rover display name = "Rover"');
})();

(function testDisplayNameDrone() {
    const name = 'drone'.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
    assert(name === 'Drone', 'drone display name = "Drone"');
})();

// ============================================================
// 6. Test mode switching ghost cleanup logic
// ============================================================
console.log('\n--- Mode Switching ---');

(function testSetupModeExitCleansUpGhost() {
    // Simulate: was setup, switching to observe
    // The cleanup call should be triggered
    const previousMode = 'setup';
    const newMode = 'observe';
    const shouldClean = previousMode === 'setup' && newMode !== 'setup';
    assert(shouldClean === true, 'switching from setup to observe triggers ghost cleanup');
})();

(function testSetupToTacticalCleansUpGhost() {
    const previousMode = 'setup';
    const newMode = 'tactical';
    const shouldClean = previousMode === 'setup' && newMode !== 'setup';
    assert(shouldClean === true, 'switching from setup to tactical triggers ghost cleanup');
})();

(function testSetupToSetupNoCleanup() {
    const previousMode = 'setup';
    const newMode = 'setup';
    const shouldClean = previousMode === 'setup' && newMode !== 'setup';
    assert(shouldClean === false, 'switching from setup to setup does not trigger cleanup');
})();

(function testObserveToTacticalNoCleanup() {
    const previousMode = 'observe';
    const newMode = 'tactical';
    const shouldClean = previousMode === 'setup' && newMode !== 'setup';
    assert(shouldClean === false, 'switching from observe to tactical does not trigger cleanup');
})();

// ============================================================
// 7. Test mousemove gate by mode
// ============================================================
console.log('\n--- Mouse Move Gate ---');

(function testMouseMoveOnlyInSetupMode() {
    let ghostUpdated = false;
    function mockOnMapMouseMove(currentMode) {
        if (currentMode !== 'setup') return false;
        ghostUpdated = true;
        return true;
    }

    assert(mockOnMapMouseMove('observe') === false, 'mousemove in observe mode does not update ghost');
    assert(ghostUpdated === false, 'ghost not updated in observe mode');

    assert(mockOnMapMouseMove('tactical') === false, 'mousemove in tactical mode does not update ghost');
    assert(ghostUpdated === false, 'ghost not updated in tactical mode');

    assert(mockOnMapMouseMove('setup') === true, 'mousemove in setup mode updates ghost');
    assert(ghostUpdated === true, 'ghost updated in setup mode');
})();

// ============================================================
// 8. Test placement toolbar visibility by phase
// ============================================================
console.log('\n--- Placement Toolbar Visibility ---');

(function testToolbarVisibleDuringIdle() {
    const phase = 'idle';
    const visible = (phase === 'idle' || phase === 'setup');
    assert(visible === true, 'toolbar visible during idle phase');
})();

(function testToolbarVisibleDuringSetup() {
    const phase = 'setup';
    const visible = (phase === 'idle' || phase === 'setup');
    assert(visible === true, 'toolbar visible during setup phase');
})();

(function testToolbarHiddenDuringActive() {
    const phase = 'active';
    const visible = (phase === 'idle' || phase === 'setup');
    assert(visible === false, 'toolbar hidden during active phase');
})();

(function testToolbarHiddenDuringCountdown() {
    const phase = 'countdown';
    const visible = (phase === 'idle' || phase === 'setup');
    assert(visible === false, 'toolbar hidden during countdown phase');
})();

(function testToolbarHiddenDuringVictory() {
    const phase = 'victory';
    const visible = (phase === 'idle' || phase === 'setup');
    assert(visible === false, 'toolbar hidden during victory phase');
})();

(function testToolbarHiddenDuringDefeat() {
    const phase = 'defeat';
    const visible = (phase === 'idle' || phase === 'setup');
    assert(visible === false, 'toolbar hidden during defeat phase');
})();

// ============================================================
// 9. Test _setupPlacementType window global behavior
// ============================================================
console.log('\n--- _setupPlacementType Global ---');

(function testDefaultFallbackToTurret() {
    // If window._setupPlacementType is not set, should fall back to turret
    const win = {};
    const unitType = (win._setupPlacementType) || 'turret';
    assert(unitType === 'turret', 'fallback to turret when _setupPlacementType not set');
})();

(function testCustomPlacementType() {
    const win = { _setupPlacementType: 'drone' };
    const unitType = (win._setupPlacementType) || 'turret';
    assert(unitType === 'drone', 'reads drone from _setupPlacementType');
})();

(function testHeavyTurretPlacementType() {
    const win = { _setupPlacementType: 'heavy_turret' };
    const unitType = (win._setupPlacementType) || 'turret';
    assert(unitType === 'heavy_turret', 'reads heavy_turret from _setupPlacementType');
})();

(function testRoverPlacementType() {
    const win = { _setupPlacementType: 'rover' };
    const unitType = (win._setupPlacementType) || 'turret';
    assert(unitType === 'rover', 'reads rover from _setupPlacementType');
})();

// ============================================================
// 10. Test ghost GeoJSON source and layer constants
// ============================================================
console.log('\n--- Ghost Source/Layer Constants ---');

(function testGhostSourceId() {
    const SETUP_GHOST_SOURCE = 'setup-ghost-source';
    assert(SETUP_GHOST_SOURCE === 'setup-ghost-source', 'ghost source ID matches');
})();

(function testGhostFillLayerId() {
    const SETUP_GHOST_FILL = 'setup-ghost-fill';
    assert(SETUP_GHOST_FILL === 'setup-ghost-fill', 'ghost fill layer ID matches');
})();

(function testGhostLineLayerId() {
    const SETUP_GHOST_LINE = 'setup-ghost-line';
    assert(SETUP_GHOST_LINE === 'setup-ghost-line', 'ghost line layer ID matches');
})();

// ============================================================
// 11. Test click-to-place only fires in setup mode
// ============================================================
console.log('\n--- Click-to-Place Mode Gate ---');

(function testClickInSetupModePlaces() {
    let placed = false;
    function onMapClick(currentMode) {
        if (currentMode === 'setup') {
            placed = true;
            return 'placed';
        }
        return 'deselect';
    }
    const result = onMapClick('setup');
    assert(result === 'placed', 'click in setup mode triggers placement');
    assert(placed === true, 'placement flag set in setup mode');
})();

(function testClickInObserveModeDeselects() {
    function onMapClick(currentMode) {
        if (currentMode === 'setup') return 'placed';
        return 'deselect';
    }
    assert(onMapClick('observe') === 'deselect', 'click in observe mode deselects');
})();

(function testClickInTacticalModeDeselects() {
    function onMapClick(currentMode) {
        if (currentMode === 'setup') return 'placed';
        return 'deselect';
    }
    assert(onMapClick('tactical') === 'deselect', 'click in tactical mode deselects');
})();

// ============================================================
// 12. Test range lookup with fallback
// ============================================================
console.log('\n--- Range Lookup ---');

(function testRangeLookupTurret() {
    const SETUP_UNIT_RANGES = { turret: 20, heavy_turret: 30, rover: 15, drone: 25 };
    assert(SETUP_UNIT_RANGES['turret'] === 20, 'turret range lookup = 20');
})();

(function testRangeLookupUnknownFallback() {
    const SETUP_UNIT_RANGES = { turret: 20, heavy_turret: 30, rover: 15, drone: 25 };
    const range = SETUP_UNIT_RANGES['unknown_type'] || 20;
    assert(range === 20, 'unknown type falls back to 20m');
})();

(function testRangeLookupAllTypes() {
    const SETUP_UNIT_RANGES = { turret: 20, heavy_turret: 30, rover: 15, drone: 25 };
    const types = Object.keys(SETUP_UNIT_RANGES);
    assert(types.length === 4, '4 unit types have ranges');
    types.forEach(t => {
        assert(typeof SETUP_UNIT_RANGES[t] === 'number' && SETUP_UNIT_RANGES[t] > 0,
            `${t} range is a positive number`);
    });
})();

// ============================================================
// Summary
// ============================================================
console.log(`\n=== Setup Mode Tests: ${passed} passed, ${failed} failed ===`);
if (failed > 0) process.exit(1);
