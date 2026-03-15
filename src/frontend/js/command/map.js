// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
/**
 * TRITIUM Command Center -- Tactical Map (Canvas 2D)
 *
 * Standalone tactical map renderer for the Command Center layout.
 * Reads unit data from TritiumStore.units, responds to EventBus events.
 * Renders to #tactical-canvas (main map) and #minimap-canvas (overview).
 *
 * Exports: initMap(), destroyMap()
 *
 * Coordinate system:
 *   Game world: -2500 to +2500 on both axes, 1 unit = 1 meter (5km x 5km)
 *   Screen Y is inverted: +Y world = up on screen
 *   Camera: { x, y, zoom, targetX, targetY, targetZoom } with smooth lerp
 */

import { TritiumStore } from './store.js';
import { EventBus } from './events.js';
import { resolveLabels } from './label-collision.js';
import { drawUnit as drawUnitIcon, drawCrowdRoleIndicator, drawFusionIndicator } from './unit-icons.js';
import { DeviceModalManager } from './device-modal.js';

// ============================================================
// Constants
// ============================================================

const MAP_MIN = -2500;
const MAP_MAX = 2500;
const MAP_RANGE = MAP_MAX - MAP_MIN; // 5000
const BG_COLOR = '#060609';
const GRID_COLOR = 'rgba(0, 240, 255, 0.04)';
const BOUNDARY_COLOR = 'rgba(0, 240, 255, 0.15)';
const ZOOM_MIN = 0.02;
const ZOOM_MAX = 30.0;
const LERP_SPEED_CAM = 8;
const LERP_SPEED_ZOOM = 6;
const FPS_UPDATE_INTERVAL = 500;
const DISPATCH_ARROW_LIFETIME = 3000; // ms
const FONT_FAMILY = '"JetBrains Mono", monospace';

// Adaptive grid thresholds: [maxZoom, gridStep]
const GRID_LEVELS = [
    [0.1,  500],   // city-scale: 500m grid
    [0.5,  100],   // neighborhood: 100m grid
    [2.0,   20],   // tactical: 20m grid
    [Infinity, 5], // close-up: 5m grid
];

// Dynamic satellite tile zoom levels: [maxCamZoom, tileZoom, radiusMeters]
const SAT_TILE_LEVELS = [
    [0.15, 14, 8000],   // extremely zoomed out
    [0.5,  15, 3000],   // very zoomed out
    [2.0,  16, 1200],   // zoomed out
    [5.0,  17,  500],   // medium
    [12.0, 18,  250],   // zoomed in
    [Infinity, 19, 200], // close-up (default view)
];

const ALLIANCE_COLORS = {
    friendly: '#05ffa1',
    hostile:  '#ff2a6d',
    neutral:  '#00a0ff',
    unknown:  '#fcee0a',
};

const FSM_BADGE_COLORS = {
    idle: '#888888',
    scanning: '#4a9eff',
    tracking: '#00f0ff',
    engaging: '#ff2a6d',
    cooldown: '#668899',
    patrolling: '#05ffa1',
    pursuing: '#ff8800',
    retreating: '#fcee0a',
    rtb: '#4a8866',
    scouting: '#88ddaa',
    orbiting: '#66ccee',
    spawning: '#cccccc',
    advancing: '#22dd66',
    flanking: '#ff6633',
    fleeing: '#ffff00',
};

// ============================================================
// Module state (private)
// ============================================================

const _state = {
    // Canvas elements
    canvas: null,
    ctx: null,
    minimapCanvas: null,
    minimapCtx: null,

    // Device pixel ratio for HiDPI scaling
    dpr: 1,

    // Camera (with smooth target)
    // Initial zoom fits ~200m radius visible (neighborhood view)
    cam: { x: 0, y: 0, zoom: 15.0, targetX: 0, targetY: 0, targetZoom: 15.0 },

    // Render loop
    animFrame: null,
    lastFrameTime: 0,
    dt: 0.016,

    // FPS tracking
    frameTimes: [],
    lastFpsUpdate: 0,
    currentFps: 0,

    // Mouse state
    lastMouse: { x: 0, y: 0 },
    isPanning: false,
    dragStart: null,
    hoveredUnit: null,

    // Dispatch mode
    dispatchMode: false,
    dispatchUnitId: null,

    // Dispatch arrows (visual feedback, fade over time)
    dispatchArrows: [], // { fromX, fromY, toX, toY, time }

    // Auto-fit camera (first time units appear)
    hasAutoFit: false,

    // Satellite tile cache
    satTiles: [],     // { image, bounds: { minX, maxX, minY, maxY } }
    geoLoaded: false,
    showSatellite: false, // toggled with I key
    geoCenter: null,     // { lat, lng } — cached for dynamic reload
    satTileLevel: -1,    // current SAT_TILE_LEVELS index (for threshold detection)
    satReloadTimer: null, // debounce timer for tile reload

    // Road tile overlay
    roadTiles: [],      // { image, bounds: { minX, maxX, minY, maxY } }
    showRoads: false,   // toggled with G key (default off)
    roadTileLevel: -1,
    roadReloadTimer: null,
    showGrid: true,     // toggled from menu

    // Overlay data (building outlines + road polylines from OSM)
    overlayBuildings: [],  // [{ polygon: [[x,y], ...], height }]
    overlayRoads: [],      // [{ points: [[x,y], ...], class }]
    showBuildings: true,   // toggled with K key

    // Zones (from escalation)
    zones: [],

    // Operational bounds cache (for minimap dynamic scaling)
    opBounds: null,       // { minX, maxX, minY, maxY }
    opBoundsUnitCount: 0, // unit count when last computed

    // Smooth heading cache
    smoothHeadings: new Map(),

    // Fog of war
    fogEnabled: true,

    // Mesh radio overlay
    showMesh: true,
    showMeshNodes: true,
    showMeshLinks: true,
    showMeshCoverage: false,

    // NPC thought bubbles
    showThoughts: true,
    _visibleThoughtIds: new Set(),  // unit IDs with visible thought bubbles
    _maxThoughtBubbles: 5,          // max non-critical visible at once

    // Geofence polygon drawing mode
    geofenceDrawing: false,
    geofenceVertices: [],  // [{x, y}, ...] in world coords

    // Patrol waypoint drawing mode
    patrolDrawing: false,
    patrolUnitId: null,
    patrolWaypoints: [],  // [{x, y}, ...] in world coords

    // Prediction cones toggle
    showPredictionCones: false,

    // RF motion data (from rfMotion:update events)
    rfMotionPairs: [],     // active motion pairs with positions
    rfMotionZones: [],     // occupied zones
    rfMotionDetected: false,

    // Screen shake tracking
    _shakeActive: false,

    // Multi-select (Shift+click)
    selectedUnitIds: new Set(),  // Set of selected unit IDs for multi-select
    multiSelectActive: false,    // true when shift is held

    // Context menu
    contextMenu: null,
    contextMenuWorld: null,

    // Cleanup handles
    unsubs: [],
    boundHandlers: new Map(),
    resizeObserver: null,
    initialized: false,
};

// ============================================================
// Coordinate transforms
// ============================================================

/**
 * Convert world coordinates to screen (CSS pixel) coordinates.
 * The canvas ctx has a DPI scale transform applied, so drawing happens
 * in CSS pixel space — no need to multiply by dpr here.
 */
function worldToScreen(wx, wy) {
    const { cam, canvas, dpr } = _state;
    // Use CSS pixel dimensions (canvas buffer / dpr)
    const cssW = canvas.width / dpr;
    const cssH = canvas.height / dpr;
    const sx = (wx - cam.x) * cam.zoom + cssW / 2;
    const sy = -(wy - cam.y) * cam.zoom + cssH / 2;
    return { x: sx, y: sy };
}

/**
 * Convert screen (CSS pixel) coordinates to world coordinates.
 */
function screenToWorld(sx, sy) {
    const { cam, canvas, dpr } = _state;
    const cssW = canvas.width / dpr;
    const cssH = canvas.height / dpr;
    const wx = (sx - cssW / 2) / cam.zoom + cam.x;
    const wy = -((sy - cssH / 2) / cam.zoom) + cam.y;
    return { x: wx, y: wy };
}

// ============================================================
// Lerp utility
// ============================================================

/**
 * Smooth exponential approach: current toward target at a given speed.
 * Frame-rate independent via dt.
 */
function fadeToward(current, target, speed, dt) {
    const t = 1 - Math.exp(-speed * dt);
    return current + (target - current) * t;
}

/**
 * Shortest-arc angle lerp (degrees).
 */
function lerpAngle(from, to, speed, dt) {
    let diff = to - from;
    // Normalize to [-180, 180]
    while (diff > 180) diff -= 360;
    while (diff < -180) diff += 360;
    const t = 1 - Math.exp(-speed * dt);
    return from + diff * t;
}

// ============================================================
// Init / Destroy
// ============================================================

/**
 * Initialize the tactical map renderer.
 * Call once after the DOM is ready.
 */
export function initMap() {
    if (_state.initialized) return;

    _state.canvas = document.getElementById('tactical-canvas');
    _state.minimapCanvas = document.getElementById('minimap-canvas');
    if (!_state.canvas) {
        console.error('[MAP] #tactical-canvas not found');
        return;
    }

    _state.ctx = _state.canvas.getContext('2d');
    if (_state.minimapCanvas) {
        _state.minimapCtx = _state.minimapCanvas.getContext('2d');
    }

    // Sync camera to store
    const vp = TritiumStore.get('map.viewport');
    if (vp) {
        _state.cam.x = vp.x || 0;
        _state.cam.y = vp.y || 0;
        _state.cam.zoom = vp.zoom || 1.0;
        _state.cam.targetX = _state.cam.x;
        _state.cam.targetY = _state.cam.y;
        _state.cam.targetZoom = _state.cam.zoom;
    }

    // Initial resize
    _resizeCanvas();

    // ResizeObserver on parent for auto-resize
    const parent = _state.canvas.parentElement;
    if (parent && typeof ResizeObserver !== 'undefined') {
        _state.resizeObserver = new ResizeObserver(() => _resizeCanvas());
        _state.resizeObserver.observe(parent);
    }

    // Bind input events
    _bindCanvasEvents();
    _bindMinimapEvents();

    // Subscribe to EventBus
    _state.unsubs.push(
        EventBus.on('units:updated', _onUnitsUpdated),
        EventBus.on('map:mode', _onMapMode),
        EventBus.on('unit:dispatch-mode', _onDispatchMode),
        EventBus.on('unit:dispatched', _onDispatched),
        EventBus.on('mesh:center-on-node', _onMeshCenterOnNode),
        EventBus.on('minimap:pan', _onMinimapPan),
        EventBus.on('map:flyToMission', _onPanToMission),
        EventBus.on('device:open-modal', _onDeviceOpenModal),
        EventBus.on('geofence:drawZone', _onGeofenceDrawStart),
        EventBus.on('patrol:drawRoute', _onPatrolDrawStart),
        EventBus.on('rfMotion:update', _onRfMotionUpdate),
        EventBus.on('map:drawFinish', _onDrawFinish),
        EventBus.on('map:drawCancel', _onDrawCancel),
    );

    // Subscribe to store for selectedUnitId changes (highlight sync)
    _state.unsubs.push(
        TritiumStore.on('map.selectedUnitId', _onSelectedUnitChanged),
    );

    // Start/stop hostile objective polling when game state changes
    _state.unsubs.push(
        TritiumStore.on('game.phase', (phase) => {
            if (phase === 'active') _startHostileObjectivePoll();
            else _stopHostileObjectivePoll();
        }),
    );

    // Load geo reference + satellite tiles
    _loadGeoReference();

    // Fetch initial zones
    _fetchZones();

    // Start render loop
    _state.lastFrameTime = performance.now();
    _renderLoop();

    _state.initialized = true;
    console.log('%c[MAP] Tactical map initialized', 'color: #00f0ff; font-weight: bold;');
}

/**
 * Tear down the map renderer and release all resources.
 */
export function destroyMap() {
    // Stop render loop
    if (_state.animFrame) {
        cancelAnimationFrame(_state.animFrame);
        _state.animFrame = null;
    }

    // Unsubscribe events
    for (const unsub of _state.unsubs) unsub();
    _state.unsubs.length = 0;

    // Unbind DOM events
    _unbindCanvasEvents();
    _unbindMinimapEvents();

    // Stop hostile objective polling
    _stopHostileObjectivePoll();

    // Stop ResizeObserver
    if (_state.resizeObserver) {
        _state.resizeObserver.disconnect();
        _state.resizeObserver = null;
    }

    _state.initialized = false;
    console.log('%c[MAP] Tactical map destroyed', 'color: #ff2a6d;');
}

// ============================================================
// Canvas resize
// ============================================================

function _resizeCanvas() {
    const canvas = _state.canvas;
    if (!canvas) return;
    const parent = canvas.parentElement;
    if (!parent) return;
    const dpr = window.devicePixelRatio || 1;
    _state.dpr = dpr;
    const w = parent.clientWidth;
    const h = parent.clientHeight;
    const bufW = Math.round(w * dpr);
    const bufH = Math.round(h * dpr);
    if (canvas.width !== bufW || canvas.height !== bufH) {
        canvas.width = bufW;
        canvas.height = bufH;
        // CSS size matches parent (layout pixels)
        canvas.style.width = `${w}px`;
        canvas.style.height = `${h}px`;
    }
    // Apply DPI scale transform so all drawing is in CSS pixel space
    const ctx = _state.ctx;
    if (ctx) {
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    }
}

// ============================================================
// Render loop
// ============================================================

function _renderLoop() {
    _update();
    _draw();
    _drawMinimap();
    _updateFps();
    _state.animFrame = requestAnimationFrame(_renderLoop);
}

// ============================================================
// Update (camera lerp, prune arrows)
// ============================================================

function _update() {
    const now = performance.now();
    const dt = Math.min((now - _state.lastFrameTime) / 1000, 0.05);
    _state.lastFrameTime = now;
    _state.dt = dt;

    // Camera lerp
    const cam = _state.cam;
    cam.x = fadeToward(cam.x, cam.targetX, LERP_SPEED_CAM, dt);
    cam.y = fadeToward(cam.y, cam.targetY, LERP_SPEED_CAM, dt);
    cam.zoom = fadeToward(cam.zoom, cam.targetZoom, LERP_SPEED_ZOOM, dt);

    // Edge scrolling
    const cssW = _state.canvas.width / _state.dpr;
    const cssH = _state.canvas.height / _state.dpr;
    const mx = _state.lastMouse.x;
    const my = _state.lastMouse.y;
    const edgeW = 20;
    const edgeSpeed = 15 * dt / Math.max(cam.zoom, 0.3);
    if (mx < edgeW && mx > 0) cam.targetX -= edgeSpeed;
    if (mx > cssW - edgeW && mx < cssW) cam.targetX += edgeSpeed;
    if (my < edgeW && my > 0) cam.targetY += edgeSpeed;
    if (my > cssH - edgeW && my < cssH) cam.targetY -= edgeSpeed;

    // Sync to store
    TritiumStore.map.viewport.x = cam.x;
    TritiumStore.map.viewport.y = cam.y;
    TritiumStore.map.viewport.zoom = cam.zoom;

    // Prune expired dispatch arrows
    const cutoff = Date.now() - DISPATCH_ARROW_LIFETIME;
    _state.dispatchArrows = _state.dispatchArrows.filter(a => a.time > cutoff);

    // Update combat systems (feature-detected from war-combat.js)
    if (typeof warCombatUpdateProjectiles === 'function') {
        warCombatUpdateProjectiles(dt);
    }
    if (typeof warCombatUpdateEffects === 'function') {
        warCombatUpdateEffects(dt);
    }

    // Dynamic satellite tile reload on zoom threshold change
    _checkSatelliteTileReload();

    // Dynamic road tile reload
    _checkRoadTileReload();
}

// ============================================================
// Main draw
// ============================================================

function _draw() {
    const { ctx, canvas, dpr } = _state;
    if (!ctx || !canvas || canvas.width === 0 || canvas.height === 0) return;

    // Clear velocity anomaly click areas for this frame
    _state.velocityAnomalyAreas = [];

    // CSS pixel dimensions (drawing space after DPI transform)
    const cssW = canvas.width / dpr;
    const cssH = canvas.height / dpr;

    // Clear (in CSS pixel space since transform is applied)
    ctx.fillStyle = BG_COLOR;
    ctx.fillRect(0, 0, cssW, cssH);

    // Apply screen shake offset (from war-combat.js elimination effects)
    if (typeof warCombatGetScreenShake === 'function') {
        const shake = warCombatGetScreenShake();
        if (shake.x !== 0 || shake.y !== 0) {
            ctx.save();
            ctx.translate(shake.x, shake.y);
            _state._shakeActive = true;
        } else {
            _state._shakeActive = false;
        }
    }

    // Layer 1: Satellite tiles (under everything, 70% opacity)
    if (_state.showSatellite) {
        _drawSatelliteTiles(ctx);
    }

    // Layer 1.5: Road overlay (transparent tiles on top of satellite)
    if (_state.showRoads) {
        _drawRoadTiles(ctx);
    }

    // Layer 1.7: Building outlines (OSM building footprints)
    if (_state.showBuildings) {
        _drawBuildingOutlines(ctx);
    }

    // Layer 1.8: Road polylines (OSM street graph)
    if (_state.showRoads && _state.overlayRoads.length > 0) {
        _drawRoadPolylines(ctx);
    }

    // Layer 2: Grid (adaptive spacing based on zoom)
    if (_state.showGrid) _drawGrid(ctx);

    // Layer 3: Map boundary
    _drawMapBoundary(ctx);

    // Layer 4: Zones
    _drawZones(ctx);

    // Layer 4.3: Environmental hazards (fire, flood, roadblock)
    _drawHazards(ctx);

    // Layer 4.4: Crowd density heatmap (civil_unrest mode only)
    _drawCrowdDensity(ctx);

    // Layer 4.45: Cover points (translucent shield markers)
    _drawCoverPoints(ctx);

    // Layer 4.5: Fog of war (darkens areas far from friendly units)
    if (typeof fogDraw === 'function' && _state.fogEnabled) {
        const fogTargets = _buildTargetsObject();
        // fogDraw expects raw canvas dimensions, but our ctx has a DPI transform
        // Create a wrapper canvas object with CSS pixel dims for fogDraw
        const fogCanvas = { width: cssW, height: cssH };
        fogDraw(ctx, fogCanvas, worldToScreen, fogTargets, _state.cam, TritiumStore.get('map.mode'));
    }

    // Layer 4.7: Mesh radio overlay (protocol-specific icons + dotted links)
    if (typeof meshDrawNodes === 'function' && _state.showMesh) {
        const meshTargets = _buildMeshTargets();
        meshDrawNodes(ctx, worldToScreen, meshTargets, _state.showMesh);
    }

    // Layer 4.9: Sensor coverage overlays (circles/cones for placed assets)
    _drawSensorCoverage(ctx);

    // Layer 5: Targets (shapes only — labels handled separately)
    _drawTargets(ctx);

    // Layer 5.02: Correlation lines (thin lines between fused targets)
    _drawCorrelationLines(ctx);

    // Layer 5.03: Prediction confidence cones (expanding uncertainty)
    _drawPredictionCones(ctx);

    // Layer 5.05: Squad formation lines (thin lines connecting squad members)
    _drawSquadLines(ctx);

    // Layer 5.1: Unit labels (collision-resolved)
    _drawLabels(ctx);

    // Layer 5.15: NPC thought bubbles
    if (_state.showThoughts) _drawThoughtBubbles(ctx);

    // Layer 5.2: Hovered unit tooltip
    _drawTooltip(ctx);

    // Layer 5.5: FOV cones (if war-fx.js loaded)
    if (typeof warFxDrawVisionCones === 'function') {
        const targetsObj = _buildTargetsObject();
        warFxDrawVisionCones(ctx, worldToScreen, targetsObj, _state.cam.zoom);
    }

    // Layer 6: Combat projectiles (feature-detected from war-combat.js)
    if (typeof warCombatDrawProjectiles === 'function') {
        warCombatDrawProjectiles(ctx, worldToScreen);
    }

    // Layer 7: Combat effects (particles, rings, screen flash)
    if (typeof warCombatDrawEffects === 'function') {
        warCombatDrawEffects(ctx, worldToScreen, cssW, cssH);
    }

    // Layer 7.5: Trails
    const targetsObj = _buildTargetsObject();
    if (typeof warFxUpdateTrails === 'function') warFxUpdateTrails(targetsObj, _state.dt);
    if (typeof warFxDrawTrails === 'function') warFxDrawTrails(ctx, worldToScreen);

    // Layer 7.8: RF motion indicators (pulsing circles at motion locations)
    _drawRfMotion(ctx);

    // Layer 7.9: Geofence drawing overlay (vertices + lines while drawing)
    _drawGeofenceOverlay(ctx);

    // Layer 7.95: Patrol waypoint drawing overlay
    _drawPatrolOverlay(ctx);

    // Layer 8: Selection indicator
    _drawSelectionIndicator(ctx);

    // Layer 9: Dispatch arrows
    _drawDispatchArrows(ctx);

    // Undo screen shake translate before fixed HUD elements
    if (_state._shakeActive) {
        ctx.restore();
        _state._shakeActive = false;
    }

    // Layer 9.5: Canvas HUD overlays (fixed-position, above world)
    if (typeof warHudDrawCanvasCountdown === 'function') {
        warHudDrawCanvasCountdown(ctx, cssW, cssH);
    }
    if (typeof warHudDrawFriendlyHealthBars === 'function') {
        warHudDrawFriendlyHealthBars(ctx, worldToScreen, _state.cam.zoom);
    }
    if (typeof warHudDrawModeHud === 'function') {
        warHudDrawModeHud(ctx, cssW, cssH);
    }
    if (typeof warHudDrawBonusObjectives === 'function') {
        warHudDrawBonusObjectives(ctx, cssW, cssH);
    }
    if (typeof warHudDrawHostileIntel === 'function') {
        const intel = TritiumStore.get('game.hostileIntel');
        warHudDrawHostileIntel(ctx, cssW, cssH, intel);
    }

    // Layer 9.6: Hostile objective lines (dashed lines from hostiles to targets)
    _drawHostileObjectives(ctx);

    // Layer 9.7: Unit communication signals (distress/contact/regroup rings)
    _drawUnitSignals(ctx);

    // Layer 10: Scanlines
    if (typeof warFxDrawScanlines === 'function') warFxDrawScanlines(ctx, cssW, cssH);

    // Layer 10.5: Scale bar
    _drawScaleBar(ctx);

    // Layer 11: "NO LOCATION SET" fallback overlay
    if (_state.noLocationSet && !_state.geoCenter) {
        ctx.save();
        ctx.fillStyle = 'rgba(0, 240, 255, 0.15)';
        ctx.font = '24px "JetBrains Mono", monospace';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.fillText('NO LOCATION SET', cssW / 2, cssH / 2 - 16);
        ctx.font = '13px "JetBrains Mono", monospace';
        ctx.fillStyle = 'rgba(0, 240, 255, 0.10)';
        ctx.fillText('Set MAP_CENTER_LAT / MAP_CENTER_LNG or use /api/geo/reference', cssW / 2, cssH / 2 + 14);
        ctx.restore();
    }

    // Update mouse coords display
    _updateCoordsDisplay();
}

// ============================================================
// Build targets object for war-fx.js integration
// ============================================================

/**
 * Convert TritiumStore.units Map to a plain object keyed by ID,
 * in the format war-fx.js expects (t.x, t.y, t.position.x, t.position.y).
 */
function _buildTargetsObject() {
    const obj = {};
    for (const [id, unit] of TritiumStore.units) {
        const pos = unit.position;
        if (!pos || pos.x === undefined) continue;
        obj[id] = {
            x: pos.x,
            y: pos.y,
            position: { x: pos.x, y: pos.y },
            asset_type: unit.type || '',
            alliance: unit.alliance || 'unknown',
            heading: unit.heading,
            status: unit.status || 'active',
            weapon_range: unit.weapon_range,
            weapon_cooldown: unit.weapon_cooldown,
            fov_angle: unit.fov_angle,
            fov_range: unit.fov_range,
        };
    }
    return obj;
}

/**
 * Build array of mesh_radio targets for the mesh draw layer.
 * Filters TritiumStore.units to only mesh_radio asset types.
 */
function _buildMeshTargets() {
    const result = [];
    for (const [id, unit] of TritiumStore.units) {
        if ((unit.type || unit.asset_type) !== 'mesh_radio') continue;
        const pos = unit.position;
        if (!pos || pos.x === undefined) continue;
        const meta = unit.metadata || {};
        result.push({
            target_id: id,
            x: pos.x,
            y: pos.y,
            asset_type: 'mesh_radio',
            metadata: meta,
            name: unit.name || meta.short_name || meta.long_name || '',
            snr: unit.snr !== undefined ? unit.snr : meta.snr,
        });
    }
    return result;
}

// ============================================================
// Layer 1: Satellite tiles
// ============================================================

function _drawSatelliteTiles(ctx) {
    const tiles = _state.satTiles;
    if (!tiles || tiles.length === 0) return;

    const cssW = _state.canvas.width / _state.dpr;
    const cssH = _state.canvas.height / _state.dpr;

    ctx.save();
    ctx.globalAlpha = 1.0;

    for (const tile of tiles) {
        const b = tile.bounds;
        const tl = worldToScreen(b.minX, b.maxY); // NW corner
        const br = worldToScreen(b.maxX, b.minY); // SE corner
        const sw = br.x - tl.x;
        const sh = br.y - tl.y;

        if (sw < 1 || sh < 1) continue;
        // Cull off-screen tiles (CSS pixel space)
        if (br.x < 0 || tl.x > cssW) continue;
        if (br.y < 0 || tl.y > cssH) continue;

        ctx.drawImage(tile.image, tl.x, tl.y, sw, sh);
    }

    ctx.restore();
}

// ============================================================
// Layer 1.7: Building outlines (OSM footprints from overlay API)
// ============================================================

function _drawBuildingOutlines(ctx) {
    const buildings = _state.overlayBuildings;
    if (!buildings || buildings.length === 0) return;

    const cssW = _state.canvas.width / _state.dpr;
    const cssH = _state.canvas.height / _state.dpr;

    ctx.save();
    ctx.strokeStyle = 'rgba(0, 240, 255, 0.35)';
    ctx.fillStyle = 'rgba(0, 240, 255, 0.06)';
    ctx.lineWidth = 1;

    for (const bldg of buildings) {
        const poly = bldg.polygon;
        if (!poly || poly.length < 3) continue;

        // Quick bounds check: skip if all points are off-screen
        const first = worldToScreen(poly[0][0], poly[0][1]);
        let minSx = first.x, maxSx = first.x, minSy = first.y, maxSy = first.y;
        for (let i = 1; i < poly.length; i++) {
            const sp = worldToScreen(poly[i][0], poly[i][1]);
            if (sp.x < minSx) minSx = sp.x;
            if (sp.x > maxSx) maxSx = sp.x;
            if (sp.y < minSy) minSy = sp.y;
            if (sp.y > maxSy) maxSy = sp.y;
        }
        if (maxSx < 0 || minSx > cssW || maxSy < 0 || minSy > cssH) continue;

        // Draw polygon
        ctx.beginPath();
        ctx.moveTo(first.x, first.y);
        for (let i = 1; i < poly.length; i++) {
            const sp = worldToScreen(poly[i][0], poly[i][1]);
            ctx.lineTo(sp.x, sp.y);
        }
        ctx.closePath();
        ctx.fill();
        ctx.stroke();
    }

    ctx.restore();
}

// ============================================================
// Layer 1.8: Road polylines (OSM street graph from overlay API)
// ============================================================

const _ROAD_STYLES = {
    motorway:    { color: 'rgba(255, 200, 50, 0.5)',  width: 3 },
    trunk:       { color: 'rgba(255, 200, 50, 0.4)',  width: 2.5 },
    primary:     { color: 'rgba(255, 180, 50, 0.35)', width: 2 },
    secondary:   { color: 'rgba(200, 200, 100, 0.3)', width: 1.5 },
    tertiary:    { color: 'rgba(180, 180, 120, 0.25)',width: 1.2 },
    residential: { color: 'rgba(150, 150, 150, 0.2)', width: 1 },
    service:     { color: 'rgba(120, 120, 120, 0.15)',width: 0.8 },
};

function _drawRoadPolylines(ctx) {
    const roads = _state.overlayRoads;
    if (!roads || roads.length === 0) return;

    const cssW = _state.canvas.width / _state.dpr;
    const cssH = _state.canvas.height / _state.dpr;

    ctx.save();
    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';

    for (const road of roads) {
        const pts = road.points;
        if (!pts || pts.length < 2) continue;

        // Quick cull
        const s0 = worldToScreen(pts[0][0], pts[0][1]);
        const s1 = worldToScreen(pts[pts.length - 1][0], pts[pts.length - 1][1]);
        if (s0.x < -50 && s1.x < -50) continue;
        if (s0.x > cssW + 50 && s1.x > cssW + 50) continue;
        if (s0.y < -50 && s1.y < -50) continue;
        if (s0.y > cssH + 50 && s1.y > cssH + 50) continue;

        const style = _ROAD_STYLES[road.class] || _ROAD_STYLES.residential;
        ctx.strokeStyle = style.color;
        ctx.lineWidth = style.width;

        ctx.beginPath();
        ctx.moveTo(s0.x, s0.y);
        for (let i = 1; i < pts.length; i++) {
            const sp = worldToScreen(pts[i][0], pts[i][1]);
            ctx.lineTo(sp.x, sp.y);
        }
        ctx.stroke();
    }

    ctx.restore();
}

// ============================================================
// Layer 2: Adaptive grid (spacing depends on zoom level)
// ============================================================

function _drawGrid(ctx) {
    const zoom = _state.cam.zoom;

    // Pick grid step based on zoom level
    let gridStep = 5;
    for (const [maxZoom, step] of GRID_LEVELS) {
        if (zoom < maxZoom) {
            gridStep = step;
            break;
        }
    }

    // Only draw lines visible on screen (avoid drawing thousands of lines)
    const cssW = _state.canvas.width / _state.dpr;
    const cssH = _state.canvas.height / _state.dpr;
    const topLeft = screenToWorld(0, 0);
    const bottomRight = screenToWorld(cssW, cssH);
    const visMinX = Math.max(MAP_MIN, Math.floor(topLeft.x / gridStep) * gridStep - gridStep);
    const visMaxX = Math.min(MAP_MAX, Math.ceil(bottomRight.x / gridStep) * gridStep + gridStep);
    const visMinY = Math.max(MAP_MIN, Math.floor(bottomRight.y / gridStep) * gridStep - gridStep);
    const visMaxY = Math.min(MAP_MAX, Math.ceil(topLeft.y / gridStep) * gridStep + gridStep);

    ctx.strokeStyle = GRID_COLOR;
    ctx.lineWidth = 1;

    // Vertical lines
    for (let wx = visMinX; wx <= visMaxX; wx += gridStep) {
        const p1 = worldToScreen(wx, visMinY);
        const p2 = worldToScreen(wx, visMaxY);
        ctx.beginPath();
        ctx.moveTo(p1.x, p1.y);
        ctx.lineTo(p2.x, p2.y);
        ctx.stroke();
    }

    // Horizontal lines
    for (let wy = visMinY; wy <= visMaxY; wy += gridStep) {
        const p1 = worldToScreen(visMinX, wy);
        const p2 = worldToScreen(visMaxX, wy);
        ctx.beginPath();
        ctx.moveTo(p1.x, p1.y);
        ctx.lineTo(p2.x, p2.y);
        ctx.stroke();
    }

    // Grid scale label (bottom-left corner)
    if (zoom > 0.04) {
        ctx.fillStyle = 'rgba(0, 240, 255, 0.2)';
        ctx.font = `10px ${FONT_FAMILY}`;
        ctx.textAlign = 'left';
        ctx.fillText(`${gridStep}m grid`, 8, cssH - 8);
    }
}

// ============================================================
// Layer 3: Map boundary
// ============================================================

function _drawMapBoundary(ctx) {
    const tl = worldToScreen(MAP_MIN, MAP_MAX);
    const br = worldToScreen(MAP_MAX, MAP_MIN);
    const w = br.x - tl.x;
    const h = br.y - tl.y;

    ctx.strokeStyle = BOUNDARY_COLOR;
    ctx.lineWidth = 2;
    ctx.strokeRect(tl.x, tl.y, w, h);
}

// ============================================================
// Layer 4: Zones
// ============================================================

function _drawZones(ctx) {
    for (const zone of _state.zones) {
        const pos = zone.position || {};
        const wx = pos.x || 0;
        const wy = pos.z !== undefined ? pos.z : (pos.y || 0);
        const radius = (zone.properties && zone.properties.radius) || 10;
        const sp = worldToScreen(wx, wy);
        const sr = radius * _state.cam.zoom;
        const isRestricted = (zone.type || '').includes('restricted');
        const fillColor = isRestricted ? 'rgba(255, 42, 109, 0.12)' : 'rgba(0, 240, 255, 0.06)';
        const borderColor = isRestricted ? 'rgba(255, 42, 109, 0.35)' : 'rgba(0, 240, 255, 0.18)';

        // Fill
        ctx.fillStyle = fillColor;
        ctx.beginPath();
        ctx.arc(sp.x, sp.y, sr, 0, Math.PI * 2);
        ctx.fill();

        // Border
        ctx.strokeStyle = borderColor;
        ctx.lineWidth = isRestricted ? 2 : 1;
        if (!isRestricted) ctx.setLineDash([6, 4]);
        ctx.beginPath();
        ctx.arc(sp.x, sp.y, sr, 0, Math.PI * 2);
        ctx.stroke();
        if (!isRestricted) ctx.setLineDash([]);

        // Label
        const name = zone.name || zone.type || '';
        if (name && _state.cam.zoom > 0.15) {
            ctx.fillStyle = isRestricted ? 'rgba(255, 42, 109, 0.5)' : 'rgba(0, 240, 255, 0.3)';
            ctx.font = `${Math.max(8, 10 * Math.min(_state.cam.zoom, 2))}px ${FONT_FAMILY}`;
            ctx.textAlign = 'center';
            ctx.fillText(name.toUpperCase(), sp.x, sp.y + sr + 14);
        }
    }
}

// ============================================================
// Layer 7.8: RF Motion Indicators
// ============================================================

function _drawRfMotion(ctx) {
    const pairs = _state.rfMotionPairs;
    if (!pairs || pairs.length === 0) return;

    const now = Date.now();

    for (const p of pairs) {
        const pos = p.midpoint || p.estimated_position;
        if (!pos) continue;
        const px = pos.x !== undefined ? pos.x : 0;
        const py = pos.y !== undefined ? pos.y : 0;
        const sp = worldToScreen(px, py);
        const confidence = p.confidence || 0.5;

        // Pulsing ring animation
        const pulse = 0.5 + 0.5 * Math.sin(now / 300);
        const baseRadius = 8 + confidence * 12;
        const radius = (baseRadius + pulse * 6) * Math.min(_state.cam.zoom, 3);

        // Outer pulse ring
        ctx.beginPath();
        ctx.arc(sp.x, sp.y, radius, 0, Math.PI * 2);
        ctx.strokeStyle = `rgba(255, 42, 109, ${0.3 + pulse * 0.3})`;
        ctx.lineWidth = 2;
        ctx.stroke();

        // Inner fill
        ctx.beginPath();
        ctx.arc(sp.x, sp.y, radius * 0.5, 0, Math.PI * 2);
        ctx.fillStyle = `rgba(255, 42, 109, ${0.15 + confidence * 0.2})`;
        ctx.fill();

        // Direction arrow
        const dir = p.direction_hint || 'unknown';
        if (dir !== 'unknown') {
            ctx.fillStyle = 'rgba(255, 42, 109, 0.8)';
            ctx.font = `bold ${Math.max(10, 12 * Math.min(_state.cam.zoom, 2))}px ${FONT_FAMILY}`;
            ctx.textAlign = 'center';
            const arrow = dir === 'approaching' ? '>' : dir === 'departing' ? '<' : 'X';
            ctx.fillText(arrow, sp.x, sp.y + 4);
        }

        // Label
        if (_state.cam.zoom > 0.3) {
            ctx.fillStyle = 'rgba(255, 42, 109, 0.7)';
            ctx.font = `${Math.max(7, 9 * Math.min(_state.cam.zoom, 2))}px ${FONT_FAMILY}`;
            ctx.textAlign = 'center';
            ctx.fillText('RF MOTION', sp.x, sp.y + radius + 10);
        }
    }
}

// ============================================================
// Layer 7.9: Geofence Drawing Overlay
// ============================================================

function _drawGeofenceOverlay(ctx) {
    if (!_state.geofenceDrawing || _state.geofenceVertices.length === 0) return;

    const verts = _state.geofenceVertices;

    // Draw lines connecting vertices
    ctx.beginPath();
    for (let i = 0; i < verts.length; i++) {
        const sp = worldToScreen(verts[i][0], verts[i][1]);
        if (i === 0) ctx.moveTo(sp.x, sp.y);
        else ctx.lineTo(sp.x, sp.y);
    }
    // Close polygon preview (dashed line back to first)
    if (verts.length >= 3) {
        const first = worldToScreen(verts[0][0], verts[0][1]);
        ctx.lineTo(first.x, first.y);
    }
    ctx.strokeStyle = '#00f0ff';
    ctx.lineWidth = 2;
    ctx.setLineDash([6, 4]);
    ctx.stroke();
    ctx.setLineDash([]);

    // Fill preview
    if (verts.length >= 3) {
        ctx.beginPath();
        for (let i = 0; i < verts.length; i++) {
            const sp = worldToScreen(verts[i][0], verts[i][1]);
            if (i === 0) ctx.moveTo(sp.x, sp.y);
            else ctx.lineTo(sp.x, sp.y);
        }
        ctx.closePath();
        ctx.fillStyle = 'rgba(0, 240, 255, 0.1)';
        ctx.fill();
    }

    // Draw vertex dots
    for (let i = 0; i < verts.length; i++) {
        const sp = worldToScreen(verts[i][0], verts[i][1]);
        ctx.beginPath();
        ctx.arc(sp.x, sp.y, 5, 0, Math.PI * 2);
        ctx.fillStyle = i === 0 ? '#05ffa1' : '#00f0ff';
        ctx.fill();
        ctx.strokeStyle = '#fff';
        ctx.lineWidth = 1;
        ctx.stroke();
    }

    // HUD instruction text
    ctx.fillStyle = 'rgba(0, 240, 255, 0.8)';
    ctx.font = `12px ${FONT_FAMILY}`;
    ctx.textAlign = 'center';
    const cssW = _state.canvas.width / _state.dpr;
    ctx.fillText(`DRAWING ZONE: ${verts.length} vertices — Enter to finish, Escape to cancel`, cssW / 2, 30);
}

// ============================================================
// Layer 7.95: Patrol Waypoint Drawing Overlay
// ============================================================

function _drawPatrolOverlay(ctx) {
    if (!_state.patrolDrawing || _state.patrolWaypoints.length === 0) return;

    const wps = _state.patrolWaypoints;

    // Draw lines connecting waypoints
    ctx.beginPath();
    for (let i = 0; i < wps.length; i++) {
        const sp = worldToScreen(wps[i].x, wps[i].y);
        if (i === 0) ctx.moveTo(sp.x, sp.y);
        else ctx.lineTo(sp.x, sp.y);
    }
    ctx.strokeStyle = '#05ffa1';
    ctx.lineWidth = 2;
    ctx.setLineDash([8, 4]);
    ctx.stroke();
    ctx.setLineDash([]);

    // Draw waypoint markers
    for (let i = 0; i < wps.length; i++) {
        const sp = worldToScreen(wps[i].x, wps[i].y);

        // Diamond marker
        ctx.beginPath();
        ctx.moveTo(sp.x, sp.y - 6);
        ctx.lineTo(sp.x + 6, sp.y);
        ctx.lineTo(sp.x, sp.y + 6);
        ctx.lineTo(sp.x - 6, sp.y);
        ctx.closePath();
        ctx.fillStyle = '#05ffa1';
        ctx.fill();
        ctx.strokeStyle = '#fff';
        ctx.lineWidth = 1;
        ctx.stroke();

        // Waypoint number
        ctx.fillStyle = '#0a0a0f';
        ctx.font = `bold 8px ${FONT_FAMILY}`;
        ctx.textAlign = 'center';
        ctx.fillText(String(i + 1), sp.x, sp.y + 3);
    }

    // HUD instruction text
    ctx.fillStyle = 'rgba(5, 255, 161, 0.8)';
    ctx.font = `12px ${FONT_FAMILY}`;
    ctx.textAlign = 'center';
    const cssW = _state.canvas.width / _state.dpr;
    ctx.fillText(`PATROL: ${wps.length} waypoints for ${_state.patrolUnitId} — Enter to finish, Escape to cancel`, cssW / 2, 30);
}

// ============================================================
// Layer 4.3: Environmental Hazards
// ============================================================

function _drawHazards(ctx) {
    const hazards = TritiumStore.get('hazards');
    if (!hazards || !(hazards instanceof Map) || hazards.size === 0) return;

    const now = Date.now();

    for (const [id, h] of hazards) {
        const pos = h.position;
        if (!pos) continue;
        // Accept both {x, y} objects and [x, y] arrays
        const px = Array.isArray(pos) ? pos[0] : (pos.x !== undefined ? pos.x : undefined);
        const py = Array.isArray(pos) ? pos[1] : (pos.y !== undefined ? pos.y : undefined);
        if (px === undefined || py === undefined) continue;

        // Calculate remaining time fraction (1.0 = just spawned, 0.0 = expired)
        const totalMs = (h.duration || 60) * 1000;
        const elapsed = now - (h.spawned_at || now);
        const remaining = Math.max(0, Math.min(1, 1 - elapsed / totalMs));
        if (remaining <= 0) continue; // fully expired, skip

        // World to screen transform
        const sp = worldToScreen(px, py);
        const sr = (h.radius || 10) * _state.cam.zoom;

        // Color per hazard type
        let color;
        switch (h.hazard_type) {
            case 'fire':      color = '#ff4400'; break;
            case 'flood':     color = '#0088ff'; break;
            case 'roadblock': color = '#ffcc00'; break;
            default:          color = '#ffffff'; break;
        }

        // Base opacity fades with remaining time
        const baseAlpha = h.hazard_type === undefined ? 0.20 : 0.30;
        const fillAlpha = baseAlpha * remaining;

        // Filled circle
        ctx.save();
        ctx.globalAlpha = fillAlpha;
        ctx.fillStyle = color;
        ctx.beginPath();
        ctx.arc(sp.x, sp.y, sr, 0, Math.PI * 2);
        ctx.fill();

        // Pulsing neon border ring
        const pulse = 0.55 + 0.15 * Math.sin(now / 400);
        ctx.globalAlpha = pulse * remaining;
        ctx.strokeStyle = color;
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.arc(sp.x, sp.y, sr, 0, Math.PI * 2);
        ctx.stroke();

        // Label centered on circle
        if (_state.cam.zoom > 0.15) {
            const label = (h.hazard_type || 'HAZARD').toUpperCase();
            ctx.globalAlpha = 0.7 * remaining;
            ctx.fillStyle = color;
            ctx.font = `${Math.max(8, 10 * Math.min(_state.cam.zoom, 2))}px ${FONT_FAMILY}`;
            ctx.textAlign = 'center';
            ctx.fillText(label, sp.x, sp.y + 4);
        }

        ctx.restore();
    }
}

// ============================================================
// Layer 9.6: Hostile Objective Lines (active game only)
// ============================================================

/**
 * Draw dashed lines from hostile units to their assigned objective targets.
 * Only renders when the game is active. Reads objective data from
 * TritiumStore 'game.hostileObjectives' (polled from /api/game/hostile-intel).
 *
 * Color per objective type:
 *   assault -> #ff2a6d (red/magenta)
 *   flank   -> #ff8800 (orange)
 *   advance -> #fcee0a (yellow)
 *   retreat -> #888888 (grey)
 */

/**
 * Draw unit communication signal rings on the map.
 * Signals fade out as they age toward their TTL.
 * Colors: distress=red, contact=orange, regroup=cyan, retreat=grey.
 */
function _drawUnitSignals(ctx) {
    let signals = TritiumStore.get('game.signals');
    if (!Array.isArray(signals) || signals.length === 0) return;

    const now = Date.now();
    // Remove expired signals and update store
    signals = signals.filter(s => now - s.received_at < (s.ttl || 10) * 1000);
    TritiumStore.set('game.signals', signals);

    if (signals.length === 0) return;

    const SIGNAL_COLORS = {
        distress: '#ff2a6d',
        contact: '#ff8800',
        regroup: '#00f0ff',
        retreat: '#888888',
        instigator_marked: '#ff2a6d',
        emp_jamming: '#fcee0a',
    };

    ctx.save();
    for (const sig of signals) {
        const pos = sig.position;
        if (!pos) continue;
        const px = Array.isArray(pos) ? pos[0] : pos.x;
        const py = Array.isArray(pos) ? pos[1] : pos.y;
        if (px === undefined || py === undefined) continue;

        const sp = worldToScreen(px, py);
        const color = SIGNAL_COLORS[sig.signal_type] || '#ffffff';
        const elapsed = (now - sig.received_at) / 1000;
        const ttl = sig.ttl || 10;
        const frac = Math.max(0, 1 - elapsed / ttl);

        // Expanding ring effect
        const expansion = 1 - frac;  // 0 -> 1 as signal ages
        const radiusWorld = (sig.signal_range || 50) * expansion;
        const radiusPx = radiusWorld * (_state.cam.zoom / 100) * (_state.canvas.width / _state.dpr / 800);

        if (radiusPx < 2) continue;

        ctx.beginPath();
        ctx.arc(sp.x, sp.y, radiusPx, 0, Math.PI * 2);
        ctx.strokeStyle = color;
        ctx.lineWidth = 2;
        ctx.globalAlpha = frac * 0.6;
        ctx.setLineDash([4, 4]);
        ctx.stroke();
        ctx.setLineDash([]);

        // Label at center
        if (frac > 0.3) {
            ctx.font = '9px monospace';
            ctx.textAlign = 'center';
            ctx.fillStyle = color;
            ctx.globalAlpha = frac * 0.8;
            ctx.fillText(sig.signal_type.toUpperCase(), sp.x, sp.y - radiusPx - 6);
        }
    }
    ctx.globalAlpha = 1;
    ctx.restore();
}
function _drawHostileObjectives(ctx) {
    const phase = TritiumStore.get('game.phase');
    if (phase !== 'active') return;

    const objectives = TritiumStore.get('game.hostileObjectives');
    if (!objectives || typeof objectives !== 'object') return;

    const units = TritiumStore.units;

    ctx.save();

    for (const [uid, obj] of Object.entries(objectives)) {
        // Look up unit position from store
        const unit = units.get(uid);
        if (!unit || !unit.position) continue;

        // Validate target_position
        const tp = obj.target_position;
        if (!tp || !Array.isArray(tp) || tp.length < 2) continue;

        // Color per objective type
        let color;
        switch (obj.type) {
            case 'assault': color = '#ff2a6d'; break;
            case 'flank':   color = '#ff8800'; break;
            case 'advance': color = '#fcee0a'; break;
            case 'retreat': color = '#888888'; break;
            default:        color = '#ff2a6d'; break;
        }

        const from = worldToScreen(unit.position.x, unit.position.y);
        const to = worldToScreen(tp[0], tp[1]);

        // Dashed line at ~30% opacity
        ctx.globalAlpha = 0.3;
        ctx.strokeStyle = color;
        ctx.lineWidth = 1.5;
        ctx.setLineDash([6, 4]);
        ctx.beginPath();
        ctx.moveTo(from.x, from.y);
        ctx.lineTo(to.x, to.y);
        ctx.stroke();
        ctx.setLineDash([]);

        // Small arrowhead at target end
        const angle = Math.atan2(to.y - from.y, to.x - from.x);
        const headLen = 8;
        ctx.globalAlpha = 0.4;
        ctx.fillStyle = color;
        ctx.beginPath();
        ctx.moveTo(to.x, to.y);
        ctx.lineTo(to.x - headLen * Math.cos(angle - 0.4), to.y - headLen * Math.sin(angle - 0.4));
        ctx.lineTo(to.x - headLen * Math.cos(angle + 0.4), to.y - headLen * Math.sin(angle + 0.4));
        ctx.closePath();
        ctx.fill();
    }

    ctx.restore();
}


// ============================================================
// Hostile Objective Polling (5s interval during active game)
// ============================================================

let _hostileObjPollTimer = null;

/**
 * Start polling /api/game/hostile-intel every 5 seconds.
 * Stores the objectives in TritiumStore 'game.hostileObjectives'.
 */
function _startHostileObjectivePoll() {
    if (_hostileObjPollTimer) return; // already running
    _hostileObjPollTimer = setInterval(async () => {
        const phase = TritiumStore.get('game.phase');
        if (phase !== 'active') {
            _stopHostileObjectivePoll();
            return;
        }
        try {
            const resp = await fetch('/api/game/hostile-intel');
            if (resp.ok) {
                const data = await resp.json();
                if (data && data.objectives) {
                    TritiumStore.set('game.hostileObjectives', data.objectives);
                }
            }
        } catch (e) {
            // Silently ignore fetch errors (server may be down)
        }
    }, 5000);
}

function _stopHostileObjectivePoll() {
    if (_hostileObjPollTimer) {
        clearInterval(_hostileObjPollTimer);
        _hostileObjPollTimer = null;
    }
    TritiumStore.set('game.hostileObjectives', null);
}


// ============================================================
// Layer 4.4: Crowd Density Heatmap (civil_unrest mode only)
// ============================================================

/**
 * Draw a crowd density heatmap overlay on the tactical map.
 * Only active when game_mode_type is 'civil_unrest'.
 *
 * Reads grid data from TritiumStore 'game.crowdDensity':
 *   { grid: [[str,...]], cell_size, bounds: [xMin,yMin,xMax,yMax],
 *     max_density, critical_count }
 *
 * Density levels:
 *   sparse   -> invisible (skip)
 *   moderate -> pale yellow at ~20% opacity
 *   dense    -> orange at ~40% opacity
 *   critical -> pulsing red at ~60% opacity (sin-wave pulse)
 */
function _drawCrowdDensity(ctx) {
    // Gate: only render in civil_unrest mode
    const modeType = TritiumStore.get('game.modeType');
    if (modeType !== 'civil_unrest') return;

    const data = TritiumStore.get('game.crowdDensity');
    if (!data || !data.grid) return;

    const grid = data.grid;
    if (!Array.isArray(grid) || grid.length === 0) return;

    const cellSize = data.cell_size || 10;
    const bounds = data.bounds || [0, 0, 0, 0];
    const xMin = bounds[0];
    const yMin = bounds[1];

    const now = performance.now();
    const vpW = _state.canvas.width / _state.dpr;
    const vpH = _state.canvas.height / _state.dpr;

    ctx.save();

    // Draw each grid cell
    for (let row = 0; row < grid.length; row++) {
        const cols = grid[row];
        if (!Array.isArray(cols)) continue;
        for (let col = 0; col < cols.length; col++) {
            const level = cols[col];

            // Sparse cells are invisible -- skip
            if (level === 'sparse' || !level) continue;

            // World coordinates for this cell (bottom-left corner)
            const wx = xMin + col * cellSize;
            const wy = yMin + row * cellSize;

            // Convert cell corners to screen space
            const topLeft = worldToScreen(wx, wy + cellSize);
            const bottomRight = worldToScreen(wx + cellSize, wy);
            const sw = bottomRight.x - topLeft.x;
            const sh = bottomRight.y - topLeft.y;

            // Skip cells outside viewport
            if (bottomRight.x < 0 || topLeft.x > vpW) continue;
            if (bottomRight.y < 0 || topLeft.y > vpH) continue;

            // Set color and opacity based on density level
            switch (level) {
                case 'moderate':
                    ctx.fillStyle = 'rgba(252, 238, 10, 0.20)';
                    ctx.globalAlpha = 1;
                    break;
                case 'dense':
                    ctx.fillStyle = 'rgba(255, 140, 0, 0.40)';
                    ctx.globalAlpha = 1;
                    break;
                case 'critical': {
                    // Pulsing red: sin-wave oscillates alpha between 0.4 and 0.7
                    const pulse = 0.55 + 0.15 * Math.sin(now / 300);
                    ctx.fillStyle = 'rgba(255, 42, 50, 0.60)';
                    ctx.globalAlpha = pulse;
                    break;
                }
                default:
                    continue;
            }

            ctx.fillRect(topLeft.x, topLeft.y, sw, sh);
        }
    }

    ctx.restore();

    // HUD pill: show max_density and critical_count in top-right area
    const maxDensity = data.max_density || '';
    const criticalCount = data.critical_count || 0;
    if (maxDensity) {
        ctx.save();
        const cssW = _state.canvas.width / _state.dpr;
        const label = `CROWD: ${maxDensity.toUpperCase()}`;
        const countLabel = criticalCount > 0 ? `  ${criticalCount} CRITICAL` : '';
        const fullText = label + countLabel;

        ctx.font = `11px ${FONT_FAMILY}`;
        ctx.textAlign = 'right';
        ctx.textBaseline = 'top';

        // Background pill
        const textWidth = ctx.measureText(fullText).width;
        const pillX = cssW - 12 - textWidth - 10;
        const pillY = 54;
        ctx.fillStyle = 'rgba(0, 0, 0, 0.6)';
        ctx.fillRect(pillX, pillY, textWidth + 20, 20);

        // Density-colored border accent
        let accentColor = '#05ffa1';
        if (maxDensity === 'critical') accentColor = '#ff2a6d';
        else if (maxDensity === 'dense') accentColor = '#ff8800';
        else if (maxDensity === 'moderate') accentColor = '#fcee0a';

        ctx.fillStyle = accentColor;
        ctx.fillRect(pillX, pillY, 3, 20);

        // Text
        ctx.fillStyle = '#cccccc';
        ctx.fillText(fullText, cssW - 12, pillY + 4);

        ctx.restore();
    }
}

// ============================================================
// Layer 4.9: Sensor Coverage Overlays
// ============================================================

/**
 * Color map for sensor coverage by asset class.
 * BLE=cyan, WiFi/sensor=blue, camera=green, mesh_radio/RF=yellow, gateway=magenta
 */
const COVERAGE_COLORS = {
    camera:     { fill: 'rgba(5, 255, 161, 0.08)',  stroke: 'rgba(5, 255, 161, 0.4)'  },  // green
    sensor:     { fill: 'rgba(0, 120, 255, 0.08)',   stroke: 'rgba(0, 120, 255, 0.4)'   },  // blue
    mesh_radio: { fill: 'rgba(252, 238, 10, 0.08)',  stroke: 'rgba(252, 238, 10, 0.4)'  },  // yellow
    gateway:    { fill: 'rgba(255, 42, 109, 0.08)',  stroke: 'rgba(255, 42, 109, 0.4)'  },  // magenta
    ble:        { fill: 'rgba(0, 240, 255, 0.08)',   stroke: 'rgba(0, 240, 255, 0.4)'   },  // cyan
};

const COVERAGE_DEFAULT = { fill: 'rgba(0, 240, 255, 0.06)', stroke: 'rgba(0, 240, 255, 0.3)' };

function _drawSensorCoverage(ctx) {
    const units = TritiumStore.units;
    if (!units || units.size === 0) return;

    ctx.save();

    // Default coverage radii (meters) for sensor types without explicit coverage_radius_meters
    const DEFAULT_COVERAGE = {
        camera: 30, sensor: 25, ble_device: 10, ble: 10,
        mesh_radio: 50, meshtastic: 50, turret: 40,
        edge_node: 30, // BLE default
    };

    // Edge node dual-ring config: BLE ~30m (cyan) + WiFi ~50m (blue)
    const EDGE_BLE_RADIUS = 30;
    const EDGE_WIFI_RADIUS = 50;
    const EDGE_BLE_COLORS = { fill: 'rgba(0, 240, 255, 0.06)', stroke: 'rgba(0, 240, 255, 0.35)' };
    const EDGE_WIFI_COLORS = { fill: 'rgba(0, 80, 220, 0.05)', stroke: 'rgba(0, 120, 255, 0.3)' };

    for (const [id, unit] of units) {
        const assetType = (unit.asset_type || unit.type || '').toLowerCase();

        // Check if this is an edge node (fleet device with position)
        const isEdgeNode = assetType === 'edge_node' || assetType === 'edge'
            || (unit.device_id && (assetType === 'fixed' || assetType === 'sensor'));
        const capabilities = unit.capabilities || [];
        const hasBle = capabilities.includes('ble') || capabilities.includes('ble_scan');
        const hasWifi = capabilities.includes('wifi') || capabilities.includes('wifi_scan');

        // Draw dual BLE/WiFi coverage rings for edge nodes
        if (isEdgeNode || (hasBle && hasWifi)) {
            const pos = unit.position;
            if (pos && pos.x !== undefined && pos.y !== undefined) {
                const sp = worldToScreen(pos.x, pos.y);

                // WiFi outer ring (larger, blue)
                const wifiRadius = (unit.wifi_range_meters || EDGE_WIFI_RADIUS) * _state.cam.zoom;
                const wifiGrad = ctx.createRadialGradient(sp.x, sp.y, 0, sp.x, sp.y, wifiRadius);
                wifiGrad.addColorStop(0, 'rgba(0, 80, 220, 0.12)');
                wifiGrad.addColorStop(0.6, EDGE_WIFI_COLORS.fill);
                wifiGrad.addColorStop(1, 'rgba(0,0,0,0)');
                ctx.beginPath();
                ctx.arc(sp.x, sp.y, wifiRadius, 0, Math.PI * 2);
                ctx.fillStyle = wifiGrad;
                ctx.fill();
                ctx.strokeStyle = EDGE_WIFI_COLORS.stroke;
                ctx.lineWidth = 1;
                ctx.setLineDash([6, 4]);
                ctx.stroke();
                ctx.setLineDash([]);

                // WiFi label
                ctx.font = '8px "Share Tech Mono", monospace';
                ctx.fillStyle = 'rgba(0, 120, 255, 0.5)';
                ctx.textAlign = 'center';
                ctx.fillText('WiFi', sp.x, sp.y - wifiRadius - 3);

                // BLE inner ring (smaller, cyan)
                const bleRadius = (unit.ble_range_meters || EDGE_BLE_RADIUS) * _state.cam.zoom;
                const bleGrad = ctx.createRadialGradient(sp.x, sp.y, 0, sp.x, sp.y, bleRadius);
                bleGrad.addColorStop(0, 'rgba(0, 240, 255, 0.15)');
                bleGrad.addColorStop(0.6, EDGE_BLE_COLORS.fill);
                bleGrad.addColorStop(1, 'rgba(0,0,0,0)');
                ctx.beginPath();
                ctx.arc(sp.x, sp.y, bleRadius, 0, Math.PI * 2);
                ctx.fillStyle = bleGrad;
                ctx.fill();
                ctx.strokeStyle = EDGE_BLE_COLORS.stroke;
                ctx.lineWidth = 1;
                ctx.setLineDash([3, 3]);
                ctx.stroke();
                ctx.setLineDash([]);

                // BLE label
                ctx.fillStyle = 'rgba(0, 240, 255, 0.5)';
                ctx.fillText('BLE', sp.x, sp.y - bleRadius - 3);

                continue;  // Skip normal coverage rendering for this unit
            }
        }

        // Draw coverage for sensor-type assets (explicit or default radius)
        const isSensorType = assetType === 'fixed' || assetType.includes('sensor')
            || assetType.includes('camera') || assetType === 'ble_device' || assetType === 'ble'
            || assetType === 'mesh_radio' || assetType === 'meshtastic' || assetType.includes('turret');
        if (!isSensorType) continue;

        const coverageRadius = unit.coverage_radius_meters || DEFAULT_COVERAGE[assetType] || 0;
        if (!coverageRadius || coverageRadius <= 0) continue;

        const pos = unit.position;
        if (!pos || pos.x === undefined || pos.y === undefined) continue;

        const sp = worldToScreen(pos.x, pos.y);
        // Convert radius from meters (world units) to screen pixels
        const radiusPx = coverageRadius * _state.cam.zoom;

        const assetClass = (unit.asset_class || assetType || '').toLowerCase();
        const colors = COVERAGE_COLORS[assetClass] || COVERAGE_DEFAULT;

        const coneAngle = unit.coverage_cone_angle || 360;
        const heading = unit.heading || 0;

        if (coneAngle >= 360) {
            // Omnidirectional: draw full circle with radial gradient
            const gradient = ctx.createRadialGradient(sp.x, sp.y, 0, sp.x, sp.y, radiusPx);
            gradient.addColorStop(0, colors.fill.replace(/[\d.]+\)$/, '0.18)'));
            gradient.addColorStop(0.6, colors.fill);
            gradient.addColorStop(1, 'rgba(0,0,0,0)');

            ctx.beginPath();
            ctx.arc(sp.x, sp.y, radiusPx, 0, Math.PI * 2);
            ctx.fillStyle = gradient;
            ctx.fill();

            // Outer ring
            ctx.strokeStyle = colors.stroke;
            ctx.lineWidth = 1;
            ctx.setLineDash([4, 4]);
            ctx.stroke();
            ctx.setLineDash([]);
        } else {
            // Directional cone: draw arc sector
            // heading 0=north, clockwise. Canvas 0=east, counter-clockwise.
            const halfAngle = (coneAngle / 2) * (Math.PI / 180);
            const headingRad = -(heading - 90) * (Math.PI / 180);  // convert to canvas coords
            const startAngle = headingRad - halfAngle;
            const endAngle = headingRad + halfAngle;

            // Gradient within cone
            const gradient = ctx.createRadialGradient(sp.x, sp.y, 0, sp.x, sp.y, radiusPx);
            gradient.addColorStop(0, colors.fill.replace(/[\d.]+\)$/, '0.22)'));
            gradient.addColorStop(0.5, colors.fill);
            gradient.addColorStop(1, 'rgba(0,0,0,0)');

            ctx.beginPath();
            ctx.moveTo(sp.x, sp.y);
            ctx.arc(sp.x, sp.y, radiusPx, startAngle, endAngle);
            ctx.closePath();
            ctx.fillStyle = gradient;
            ctx.fill();

            // Cone outline
            ctx.strokeStyle = colors.stroke;
            ctx.lineWidth = 1;
            ctx.setLineDash([4, 4]);
            ctx.stroke();
            ctx.setLineDash([]);
        }

        // Height indicator: small altitude label next to sensor icon
        const heightM = unit.height_meters;
        if (heightM != null && heightM > 0) {
            const labelText = `${heightM}m`;
            ctx.font = `bold 9px "Share Tech Mono", monospace`;
            ctx.textAlign = 'left';
            ctx.textBaseline = 'middle';
            const labelX = sp.x + 12;
            const labelY = sp.y - 8;

            // Background pill
            const tw = ctx.measureText(labelText).width;
            ctx.fillStyle = 'rgba(6, 6, 9, 0.85)';
            ctx.fillRect(labelX - 2, labelY - 6, tw + 4, 12);

            // Vertical bar indicator (proportional to height, capped at 20px)
            const barH = Math.min(20, Math.max(4, heightM * 1.5));
            ctx.fillStyle = colors.stroke;
            ctx.fillRect(labelX - 5, labelY + 6 - barH, 2, barH);

            // Text
            ctx.fillStyle = colors.stroke;
            ctx.fillText(labelText, labelX, labelY);
        }
    }

    ctx.restore();
}

// ============================================================
// Layer 5: Targets
// ============================================================

function _drawTargets(ctx) {
    const units = TritiumStore.units;
    const fogEnabled = _state.fogEnabled;
    for (const [id, unit] of units) {
        const alliance = (unit.alliance || 'unknown').toLowerCase();
        // Fog of war: hide hostile/unknown units not seen by any friendly
        if (fogEnabled && alliance === 'hostile') {
            if (!unit.visible) {
                // Not visually detected — check radio
                if (unit.radio_detected) {
                    _drawRadioGhost(ctx, unit);
                }
                continue; // skip full unit render
            }
        }
        _drawUnit(ctx, id, unit);
    }
}

// ============================================================
// Layer 5.02: Correlation lines between fused targets
// ============================================================

/**
 * Draw thin lines between correlated targets with confidence score labels.
 * Fetches correlation data from /api/correlations periodically.
 */
const _correlationState = {
    records: [],
    lastFetch: 0,
    fetchInterval: 5000, // ms
};

function _drawCorrelationLines(ctx) {
    const now = Date.now();

    // Periodically fetch correlation data
    if (now - _correlationState.lastFetch > _correlationState.fetchInterval) {
        _correlationState.lastFetch = now;
        fetch('/api/correlations')
            .then(r => r.ok ? r.json() : { correlations: [] })
            .then(data => {
                _correlationState.records = data.correlations || [];
            })
            .catch(() => {
                _correlationState.records = [];
            });
    }

    const records = _correlationState.records;
    if (!records || records.length === 0) return;

    const units = TritiumStore.units;
    if (!units || units.size === 0) return;

    ctx.save();

    for (const corr of records) {
        const unitA = units.get(corr.primary_id);
        const unitB = units.get(corr.secondary_id);
        if (!unitA || !unitB) continue;

        const posA = unitA.position;
        const posB = unitB.position;
        if (!posA || !posB) continue;
        if (posA.x === undefined || posB.x === undefined) continue;

        const spA = worldToScreen(posA.x, posA.y);
        const spB = worldToScreen(posB.x, posB.y);

        // Skip if both off-screen
        const cssW = _state.canvas.width / _state.dpr;
        const cssH = _state.canvas.height / _state.dpr;
        if ((spA.x < -50 || spA.x > cssW + 50) && (spB.x < -50 || spB.x > cssW + 50)) continue;

        // Line color based on confidence (cyan=high, yellow=low)
        const conf = corr.confidence || 0;
        const r = Math.round(252 * (1 - conf));
        const g = Math.round(238 * (1 - conf) + 240 * conf);
        const b = Math.round(10 * (1 - conf) + 255 * conf);
        const lineColor = `rgba(${r}, ${g}, ${b}, 0.5)`;

        // Draw dashed line
        ctx.beginPath();
        ctx.setLineDash([4, 4]);
        ctx.strokeStyle = lineColor;
        ctx.lineWidth = 1;
        ctx.moveTo(spA.x, spA.y);
        ctx.lineTo(spB.x, spB.y);
        ctx.stroke();
        ctx.setLineDash([]);

        // Draw confidence label at midpoint
        const midX = (spA.x + spB.x) / 2;
        const midY = (spA.y + spB.y) / 2;
        const label = `${Math.round(conf * 100)}%`;

        ctx.font = '9px monospace';
        const metrics = ctx.measureText(label);
        const pad = 3;

        // Background pill
        ctx.fillStyle = 'rgba(10, 10, 15, 0.8)';
        ctx.fillRect(
            midX - metrics.width / 2 - pad,
            midY - 5 - pad,
            metrics.width + pad * 2,
            12 + pad
        );

        // Label text
        ctx.fillStyle = lineColor;
        ctx.textAlign = 'center';
        ctx.fillText(label, midX, midY + 3);
        ctx.textAlign = 'left'; // reset
    }

    ctx.restore();
}

// ============================================================
// Layer 5.03: Prediction confidence cones
// ============================================================

/**
 * Draw expanding uncertainty cones for target predicted future positions.
 * Uses velocity (heading + speed) from unit data to project future positions
 * at 1s, 3s, 5s, 10s intervals. The cone widens over time to represent
 * growing positional uncertainty.
 */
const PREDICTION_STEPS = [
    { dt: 1, alpha: 0.25 },
    { dt: 3, alpha: 0.18 },
    { dt: 5, alpha: 0.12 },
    { dt: 10, alpha: 0.07 },
];
const PREDICTION_BASE_SPREAD = 0.15; // radians spread per second of prediction
const PREDICTION_CONE_LENGTH = 1.0;  // meters per unit speed per second

function _drawPredictionCones(ctx) {
    const units = TritiumStore.units;
    if (!units || units.size === 0) return;

    const selectedId = TritiumStore.get('map.selectedUnitId');
    const showAll = _state.showPredictionCones;
    if (!showAll && !selectedId) return;

    ctx.save();

    for (const [id, unit] of units) {
        // Only show for selected unit unless showAll is enabled
        if (!showAll && id !== selectedId) continue;

        const pos = unit.position;
        if (!pos || pos.x === undefined || pos.y === undefined) continue;

        // Need heading and some indication of movement (speed or velocity)
        const heading = unit.heading;
        if (heading === undefined || heading === null) continue;

        // Estimate speed from unit data or default
        const speed = unit.speed || unit.velocity || 0;
        if (speed < 0.1) continue; // skip stationary units

        const alliance = (unit.alliance || 'unknown').toLowerCase();
        const color = ALLIANCE_COLORS[alliance] || ALLIANCE_COLORS.unknown;

        // Convert heading to radians (heading is degrees, 0=north, CW)
        const headingRad = (90 - heading) * Math.PI / 180;

        for (const step of PREDICTION_STEPS) {
            const dist = speed * step.dt * PREDICTION_CONE_LENGTH;
            const spread = PREDICTION_BASE_SPREAD * step.dt;

            // Predicted center position
            const predX = pos.x + Math.cos(headingRad) * dist;
            const predY = pos.y + Math.sin(headingRad) * dist;

            // Cone edges (left and right of heading)
            const leftAngle = headingRad + spread;
            const rightAngle = headingRad - spread;
            const leftX = pos.x + Math.cos(leftAngle) * dist;
            const leftY = pos.y + Math.sin(leftAngle) * dist;
            const rightX = pos.x + Math.cos(rightAngle) * dist;
            const rightY = pos.y + Math.sin(rightAngle) * dist;

            // Convert to screen coordinates
            const spOrigin = worldToScreen(pos.x, pos.y);
            const spLeft = worldToScreen(leftX, leftY);
            const spRight = worldToScreen(rightX, rightY);
            const spCenter = worldToScreen(predX, predY);

            // Draw filled cone
            ctx.beginPath();
            ctx.moveTo(spOrigin.x, spOrigin.y);
            ctx.lineTo(spLeft.x, spLeft.y);
            // Arc at the far end
            ctx.lineTo(spCenter.x, spCenter.y);
            ctx.lineTo(spRight.x, spRight.y);
            ctx.closePath();
            ctx.fillStyle = color;
            ctx.globalAlpha = step.alpha;
            ctx.fill();

            // Draw cone outline
            ctx.beginPath();
            ctx.moveTo(spOrigin.x, spOrigin.y);
            ctx.lineTo(spLeft.x, spLeft.y);
            ctx.lineTo(spCenter.x, spCenter.y);
            ctx.lineTo(spRight.x, spRight.y);
            ctx.closePath();
            ctx.strokeStyle = color;
            ctx.lineWidth = 0.5;
            ctx.globalAlpha = step.alpha * 1.5;
            ctx.stroke();

            // Draw predicted position dot
            ctx.beginPath();
            ctx.arc(spCenter.x, spCenter.y, 2, 0, Math.PI * 2);
            ctx.fillStyle = color;
            ctx.globalAlpha = step.alpha * 2;
            ctx.fill();
        }

        // Draw time labels at furthest prediction
        const lastStep = PREDICTION_STEPS[PREDICTION_STEPS.length - 1];
        const lastDist = speed * lastStep.dt * PREDICTION_CONE_LENGTH;
        const lastPredX = pos.x + Math.cos(headingRad) * lastDist;
        const lastPredY = pos.y + Math.sin(headingRad) * lastDist;
        const spLast = worldToScreen(lastPredX, lastPredY);

        ctx.globalAlpha = 0.4;
        ctx.font = '8px monospace';
        ctx.fillStyle = color;
        ctx.textAlign = 'center';
        ctx.fillText(`+${lastStep.dt}s`, spLast.x, spLast.y - 6);
    }

    ctx.globalAlpha = 1.0;
    ctx.restore();
}

// ============================================================
// Layer 5.1: Labels (collision-resolved via label-collision.js)
// ============================================================

function _drawLabels(ctx) {
    const units = TritiumStore.units;
    if (!units || units.size === 0) return;

    const selectedId = TritiumStore.get('map.selectedUnitId');
    const cssW = _state.canvas.width / _state.dpr;
    const cssH = _state.canvas.height / _state.dpr;

    // Collect label entries from all units
    const entries = [];
    const fogEnabled = _state.fogEnabled;
    for (const [id, unit] of units) {
        const pos = unit.position;
        if (!pos || pos.x === undefined || pos.y === undefined) continue;
        const alliance = (unit.alliance || 'unknown').toLowerCase();
        // Fog of war: skip labels for invisible hostile units
        if (fogEnabled && alliance === 'hostile' && !unit.visible) {
            continue; // radio ghost labels are drawn by _drawRadioGhost
        }
        const fsm = unit.fsm_state || '';
        const status = (unit.status || 'active').toLowerCase();
        const badgeColor = FSM_BADGE_COLORS[fsm] || FSM_BADGE_COLORS[status] || null;
        const fsmState = fsm ? ` [${fsm.toUpperCase()}]` : '';
        const elims = unit.eliminations ? ` ${unit.eliminations}K` : '';
        const badgeText = fsm || status;
        // Show a short UUID prefix for all units with real IDs
        let shortId = '';
        if (unit.identity && unit.identity.short_id) {
            shortId = unit.identity.short_id;
        } else if (typeof id === 'string') {
            // Extract short prefix from target_id UUID (e.g. "rover-a3f1b2c4" -> "A3F1B2")
            const clean = id.replace(/^[a-z_]+-/, '');  // strip type prefix
            if (clean.length >= 6) {
                shortId = clean.substring(0, 6).toUpperCase();
            }
        }
        const labelText = shortId ? `${shortId} ${unit.name || id}` : (unit.name || id);
        entries.push({
            id,
            text: labelText,
            badge: fsmState + elims,
            badgeColor,
            badgeText,
            worldX: pos.x,
            worldY: pos.y,
            alliance,
            status,
            isSelected: id === selectedId,
        });
    }

    const resolved = resolveLabels(entries, cssW, cssH, _state.cam.zoom, selectedId, worldToScreen);

    ctx.save();
    const fontSize = Math.max(7, 8 * Math.min(_state.cam.zoom, 2));
    ctx.font = `${fontSize}px ${FONT_FAMILY}`;
    ctx.textAlign = 'left';
    ctx.textBaseline = 'top';

    for (const r of resolved) {
        // Leader line (thin white line from label to unit when displaced)
        if (r.displaced) {
            ctx.strokeStyle = 'rgba(255, 255, 255, 0.15)';
            ctx.lineWidth = 1;
            ctx.beginPath();
            ctx.moveTo(r.labelX + r.bgWidth / 2, r.labelY + r.bgHeight / 2);
            ctx.lineTo(r.anchorX, r.anchorY);
            ctx.stroke();
        }

        // Background box
        ctx.fillStyle = 'rgba(6, 6, 9, 0.7)';
        ctx.fillRect(r.labelX, r.labelY, r.bgWidth, r.bgHeight);

        // Text
        const isNeutralized = r.status === 'neutralized' || r.status === 'eliminated' || r.status === 'destroyed';
        ctx.fillStyle = isNeutralized ? 'rgba(255, 255, 255, 0.3)' : 'rgba(255, 255, 255, 0.85)';
        ctx.fillText(r.text, r.labelX + 3, r.labelY + 3);

        // FSM badge
        if (r.badge) {
            const textW = ctx.measureText(r.text).width;
            ctx.fillStyle = r.badgeColor || 'rgba(255, 255, 255, 0.5)';
            ctx.font = `${Math.max(7, fontSize - 2)}px ${FONT_FAMILY}`;
            ctx.fillText(r.badge, r.labelX + 3 + textW + 4, r.labelY + 3);
            ctx.font = `${fontSize}px ${FONT_FAMILY}`;
        }
    }

    ctx.restore();
}

// ============================================================
// Thought bubble helpers (exported for testing)
// ============================================================

/**
 * Word-wrap text to fit within maxWidth pixels.
 * @param {CanvasRenderingContext2D} ctx
 * @param {string} text
 * @param {number} maxWidth
 * @returns {string[]} array of lines
 */
function _wrapText(ctx, text, maxWidth) {
    const words = text.split(' ');
    const lines = [];
    let currentLine = '';

    for (const word of words) {
        const testLine = currentLine ? currentLine + ' ' + word : word;
        const metrics = ctx.measureText(testLine);
        if (metrics.width > maxWidth && currentLine) {
            lines.push(currentLine);
            currentLine = word;
        } else {
            currentLine = testLine;
        }
    }
    if (currentLine) lines.push(currentLine);
    return lines;
}

/**
 * Map emotion name to a border color.
 * @param {string} emotion
 * @returns {string} CSS color
 */
function _emotionColor(emotion) {
    const colors = {
        curious: '#00f0ff',
        afraid: '#fcee0a',
        angry: '#ff2a6d',
        happy: '#05ffa1',
        neutral: '#888888',
    };
    return colors[emotion] || '#888888';
}

/**
 * Draw NPC thought bubbles above units that have active thoughts.
 * Only shows critical/high importance thoughts and the selected unit's thought.
 * Caps visible non-critical bubbles to _state._maxThoughtBubbles.
 */
function _drawThoughtBubbles(ctx) {
    const units = TritiumStore.units;
    if (!units || units.size === 0) return;

    const now = Date.now();
    const fontSize = Math.max(11, 13 * Math.min(_state.cam.zoom, 2.5));
    const lineHeight = fontSize + 4;
    const padding = 10;
    const maxTextWidth = 200;
    const tailHeight = 10;
    const fadeInDuration = 300;
    const fadeOutStart = 1000; // start fading 1s before expiry

    // Clean expired entries from the visible set
    for (const uid of _state._visibleThoughtIds) {
        const u = units.get(uid);
        if (!u || !u.thoughtText || !u.thoughtExpires || u.thoughtExpires <= now) {
            _state._visibleThoughtIds.delete(uid);
        }
    }

    ctx.save();
    ctx.font = `${fontSize}px ${FONT_FAMILY}`;
    ctx.textBaseline = 'top';
    ctx.textAlign = 'left';

    // Count non-critical visible bubbles (excluding selected and critical)
    const selectedUnitId = TritiumStore.get('map.selectedUnitId');
    let nonCriticalCount = 0;
    for (const uid of _state._visibleThoughtIds) {
        if (uid === selectedUnitId) continue;
        const u = units.get(uid);
        if (u && u.thoughtImportance === 'critical') continue;
        nonCriticalCount++;
    }

    for (const [id, unit] of units) {
        if (!unit.thoughtText || !unit.thoughtExpires) continue;
        if (unit.thoughtExpires <= now) continue;

        // Visibility filter: critical + selected always show, others capped
        const isCritical = unit.thoughtImportance === 'critical';
        const isSelected = selectedUnitId === id;
        if (!isCritical && !isSelected) {
            if (_state._visibleThoughtIds.has(id)) {
                // Already visible, keep it
            } else if (nonCriticalCount >= _state._maxThoughtBubbles) {
                continue; // Cap reached, skip
            } else {
                nonCriticalCount++;
            }
        }
        _state._visibleThoughtIds.add(id);

        const pos = unit.position;
        if (!pos || pos.x === undefined || pos.y === undefined) continue;

        const screen = worldToScreen(pos.x, pos.y);
        const text = unit.thoughtText;
        const emotion = unit.thoughtEmotion || 'neutral';
        const borderColor = _emotionColor(emotion);

        // Compute opacity for fade-in / fade-out
        const created = unit.thoughtExpires - ((unit.thoughtDuration || 5) * 1000);
        const age = now - created;
        const timeLeft = unit.thoughtExpires - now;
        let alpha = 1.0;
        if (age < fadeInDuration) {
            alpha = age / fadeInDuration;
        }
        if (timeLeft < fadeOutStart) {
            alpha = Math.min(alpha, timeLeft / fadeOutStart);
        }
        alpha = Math.max(0, Math.min(1, alpha));
        if (alpha <= 0) continue;

        // Word-wrap
        const lines = _wrapText(ctx, text, maxTextWidth);
        const textW = Math.min(
            maxTextWidth,
            Math.max(...lines.map(l => ctx.measureText(l).width))
        );
        const bubbleW = textW + padding * 2;
        const bubbleH = lines.length * lineHeight + padding * 2;

        // Position: centered above unit
        const bx = screen.x - bubbleW / 2;
        const by = screen.y - bubbleH - tailHeight - 28; // 28px above unit icon
        const radius = 4;

        ctx.globalAlpha = alpha;

        // Glow effect behind bubble
        ctx.shadowColor = borderColor;
        ctx.shadowBlur = 12;

        // Bubble background
        ctx.fillStyle = 'rgba(18, 22, 36, 0.92)';
        ctx.beginPath();
        ctx.moveTo(bx + radius, by);
        ctx.lineTo(bx + bubbleW - radius, by);
        ctx.arcTo(bx + bubbleW, by, bx + bubbleW, by + radius, radius);
        ctx.lineTo(bx + bubbleW, by + bubbleH - radius);
        ctx.arcTo(bx + bubbleW, by + bubbleH, bx + bubbleW - radius, by + bubbleH, radius);
        ctx.lineTo(bx + radius, by + bubbleH);
        ctx.arcTo(bx, by + bubbleH, bx, by + bubbleH - radius, radius);
        ctx.lineTo(bx, by + radius);
        ctx.arcTo(bx, by, bx + radius, by, radius);
        ctx.closePath();
        ctx.fill();

        // Tail (triangle pointing down to unit)
        ctx.beginPath();
        ctx.moveTo(screen.x - 5, by + bubbleH);
        ctx.lineTo(screen.x, by + bubbleH + tailHeight);
        ctx.lineTo(screen.x + 5, by + bubbleH);
        ctx.closePath();
        ctx.fill();

        // Reset shadow so border/text don't double-glow
        ctx.shadowColor = 'transparent';
        ctx.shadowBlur = 0;

        // Border
        ctx.strokeStyle = borderColor;
        ctx.lineWidth = 2.5;
        // Re-draw bubble path for stroke
        ctx.beginPath();
        ctx.moveTo(bx + radius, by);
        ctx.lineTo(bx + bubbleW - radius, by);
        ctx.arcTo(bx + bubbleW, by, bx + bubbleW, by + radius, radius);
        ctx.lineTo(bx + bubbleW, by + bubbleH - radius);
        ctx.arcTo(bx + bubbleW, by + bubbleH, bx + bubbleW - radius, by + bubbleH, radius);
        ctx.lineTo(bx + radius, by + bubbleH);
        ctx.arcTo(bx, by + bubbleH, bx, by + bubbleH - radius, radius);
        ctx.lineTo(bx, by + radius);
        ctx.arcTo(bx, by, bx + radius, by, radius);
        ctx.closePath();
        ctx.stroke();

        // Tail border
        ctx.beginPath();
        ctx.moveTo(screen.x - 5, by + bubbleH);
        ctx.lineTo(screen.x, by + bubbleH + tailHeight);
        ctx.lineTo(screen.x + 5, by + bubbleH);
        ctx.stroke();

        // Text
        ctx.fillStyle = 'rgba(255, 255, 255, 0.95)';
        for (let i = 0; i < lines.length; i++) {
            ctx.fillText(lines[i], bx + padding, by + padding + i * lineHeight);
        }
    }

    ctx.globalAlpha = 1.0;
    ctx.restore();
}

function _drawTooltip(ctx) {
    if (!_state.hoveredUnit) return;
    const u = TritiumStore.units.get(_state.hoveredUnit);
    if (!u || !u.position) return;

    const mouse = _state.lastMouse || worldToScreen(u.position.x, u.position.y);
    const fsm = u.fsm_state || u.fsmState || '';
    const tooltipColor = FSM_BADGE_COLORS[fsm] || '#ccc';
    const fsmLabel = fsm ? fsm.toUpperCase() : '';
    const elims = u.eliminations ? ` ${u.eliminations}K` : '';

    // Build tooltip lines
    const lines = [];
    lines.push((u.name || _state.hoveredUnit) + (fsmLabel ? ' ' + fsmLabel + elims : elims));
    if (u.type) lines.push(u.type.toUpperCase());
    if (u.health !== undefined && u.maxHealth) {
        lines.push('HP: ' + Math.round(u.health) + '/' + u.maxHealth);
    }
    if (u.altitude > 0) lines.push('ALT: ' + Math.round(u.altitude) + 'm');
    // BLE device extra info
    const uType = (u.type || u.asset_type || '').toLowerCase();
    if (uType === 'ble_device' || uType === 'ble') {
        if (u.manufacturer) lines.push('MFR: ' + u.manufacturer);
        if (u.rssi !== undefined) lines.push('RSSI: ' + u.rssi + ' dBm');
        if (u.confidence !== undefined) lines.push('CONF: ' + Math.round(u.confidence * 100) + '%');
        if (u.device_class) lines.push('CLASS: ' + u.device_class);
    }
    // Mesh radio extra info
    if (uType === 'mesh_radio' || uType === 'meshtastic') {
        if (u.snr !== undefined) lines.push('SNR: ' + u.snr + ' dB');
        if (u.channel) lines.push('CH: ' + u.channel);
    }
    // Fixed sensor 3D placement info
    if (uType === 'fixed' || uType === 'sensor' || uType === 'camera') {
        if (u.height_meters != null) lines.push('ALT: ' + u.height_meters + 'm');
        if (u.floor_level != null) lines.push('FLOOR: ' + u.floor_level);
        if (u.mounting_type) lines.push('MOUNT: ' + u.mounting_type.toUpperCase());
        if (u.coverage_radius_meters) lines.push('RANGE: ' + u.coverage_radius_meters + 'm');
        if (u.coverage_cone_angle && u.coverage_cone_angle < 360) lines.push('FOV: ' + u.coverage_cone_angle + '\u00B0');
    }

    ctx.save();
    ctx.font = `11px ${FONT_FAMILY}`;
    ctx.textAlign = 'left';
    ctx.textBaseline = 'top';

    // Measure widths
    const lineH = 15;
    const padX = 6;
    const padY = 4;
    let maxW = 0;
    for (const line of lines) {
        const w = ctx.measureText(line).width;
        if (w > maxW) maxW = w;
    }
    const boxW = maxW + padX * 2;
    const boxH = lines.length * lineH + padY * 2;

    // Position: offset from mouse, clamped to canvas bounds
    const cssW = _state.canvas.width / _state.dpr;
    const cssH = _state.canvas.height / _state.dpr;
    let tx = mouse.x + 14;
    let ty = mouse.y - boxH - 8;
    if (tx + boxW > cssW - 4) tx = mouse.x - boxW - 8;
    if (ty < 4) ty = mouse.y + 14;
    if (ty + boxH > cssH - 4) ty = cssH - boxH - 4;

    // Background
    ctx.fillStyle = 'rgba(6, 6, 9, 0.9)';
    ctx.fillRect(tx, ty, boxW, boxH);
    ctx.strokeStyle = tooltipColor;
    ctx.lineWidth = 1;
    ctx.strokeRect(tx, ty, boxW, boxH);

    // Text lines
    for (let i = 0; i < lines.length; i++) {
        ctx.fillStyle = i === 0 ? tooltipColor : '#aaa';
        ctx.fillText(lines[i], tx + padX, ty + padY + i * lineH);
    }

    ctx.restore();
}

function _drawStatusBadge(ctx, unit, sp) {
    const fsm = unit.fsm_state || '';
    const status = (unit.status || 'active').toLowerCase();
    const badgeText = fsm || status;
    if (!badgeText || badgeText === 'active') return;

    const badgeColor = FSM_BADGE_COLORS[fsm] || '#888';
    ctx.save();
    ctx.font = `8px ${FONT_FAMILY}`;
    ctx.textAlign = 'center';
    ctx.fillStyle = badgeColor;
    ctx.fillText(badgeText.toUpperCase(), sp.x, sp.y - 18);
    ctx.restore();
}

/**
 * Draw a radio-only ghost blip for a hostile detected via BLE/WiFi/cell
 * but not visually confirmed.  Renders as a pulsing hollow ring with a "?"
 * marker and optional MAC address label.
 */
function _drawRadioGhost(ctx, unit) {
    const pos = unit.position;
    if (!pos || pos.x === undefined || pos.y === undefined) return;
    const sp = worldToScreen(pos.x, pos.y);

    ctx.save();
    const strength = unit.radio_signal_strength || 0.3;
    const pulse = 0.7 + 0.3 * Math.sin(Date.now() / 400);
    const alpha = 0.3 + 0.4 * strength * pulse;
    const radius = 8 + 4 * (1 - strength); // weaker = larger uncertainty ring

    // Outer uncertainty ring
    ctx.strokeStyle = `rgba(255, 42, 109, ${alpha})`; // magenta ghost
    ctx.lineWidth = 1.5;
    ctx.setLineDash([4, 4]);
    ctx.beginPath();
    ctx.arc(sp.x, sp.y, radius, 0, Math.PI * 2);
    ctx.stroke();
    ctx.setLineDash([]);

    // Inner dot
    ctx.fillStyle = `rgba(255, 42, 109, ${alpha * 0.8})`;
    ctx.beginPath();
    ctx.arc(sp.x, sp.y, 3, 0, Math.PI * 2);
    ctx.fill();

    // "?" marker
    ctx.fillStyle = `rgba(255, 42, 109, ${Math.min(1, alpha + 0.2)})`;
    ctx.font = 'bold 10px monospace';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText('?', sp.x, sp.y);

    // MAC address label (if available from identity)
    const identity = unit.identity;
    if (identity) {
        const mac = identity.bluetooth_mac || identity.wifi_mac || identity.cell_id || '';
        if (mac) {
            const shortMac = mac.length > 8 ? mac.slice(-8) : mac;
            ctx.fillStyle = `rgba(255, 42, 109, ${alpha * 0.6})`;
            ctx.font = '8px monospace';
            ctx.fillText(shortMac, sp.x, sp.y + radius + 8);
        }
    }

    ctx.restore();
}

function _drawUnit(ctx, id, unit) {
    const pos = unit.position;
    if (!pos || pos.x === undefined || pos.y === undefined) return;

    const sp = worldToScreen(pos.x, pos.y);
    const alliance = (unit.alliance || 'unknown').toLowerCase();
    const type = (unit.asset_type || unit.type || '').toLowerCase();
    const status = (unit.status || 'active').toLowerCase();
    const isNeutralized = status === 'neutralized' || status === 'eliminated' || status === 'destroyed';
    const isSelected = TritiumStore.get('map.selectedUnitId') === id;
    const isMultiSelected = _state.selectedUnitIds.has(id);
    const isHovered = _state.hoveredUnit === id;

    // Smooth heading interpolation
    const heading = unit.heading;
    let smoothedHeading = heading;
    if (heading !== undefined && heading !== null) {
        const prevHeading = _state.smoothHeadings.get(id);
        if (prevHeading !== undefined) {
            smoothedHeading = lerpAngle(prevHeading, heading, 10, _state.dt);
        }
        _state.smoothHeadings.set(id, smoothedHeading);
    }

    // Compute scale from zoom and hover/selection
    // Compact icons: ~0.4x at zoom 1.5, matching 3D indicator scale
    let scale = Math.min(_state.cam.zoom, 3) / 4.0;
    scale = Math.max(0.2, Math.min(0.8, scale));
    if (isSelected) scale *= 1.3;
    else if (isMultiSelected) scale *= 1.2;
    else if (isHovered) scale *= 1.15;

    // Map type name to unit-icons type
    let iconType = type;
    if (type.includes('turret') || type.includes('sentry')) iconType = 'turret';
    else if (type.includes('drone')) iconType = 'drone';
    else if (type.includes('rover') || type.includes('interceptor') || type.includes('patrol')) iconType = 'rover';
    else if (type.includes('tank') || type.includes('truck') || type.includes('vehicle')) iconType = 'tank';
    else if (type.includes('camera') || type.includes('sensor')) iconType = 'sensor';
    else if (type === 'person' && alliance === 'hostile') iconType = 'hostile_person';
    else if (type === 'person' && alliance === 'neutral') iconType = 'neutral_person';
    else if (type === 'hostile_kid') iconType = 'hostile_person';
    else if (type === 'mesh_radio' || type === 'meshtastic') iconType = 'mesh_radio';
    else if (type === 'ble_device' || type === 'ble') iconType = 'ble_device';
    else if (type === 'rf_motion') iconType = 'rf_motion';
    else if (type === 'camera_detection' || type === 'detection') iconType = 'camera_detection';

    // Universal confidence-based transparency: targets with decaying confidence
    // render faded/ghostly. High confidence = solid, low = transparent.
    // Pulsing animation when confidence is actively decaying.
    const confidence = unit.confidence !== undefined ? unit.confidence : 1.0;
    const prevConfidence = unit._prevConfidence !== undefined ? unit._prevConfidence : confidence;
    const isDecaying = confidence < prevConfidence || (confidence < 0.8 && confidence > 0);
    let confidenceAlpha = 1.0;

    if (confidence < 1.0) {
        // Map confidence [0, 1] -> alpha [0.15, 1.0] for smooth fade
        confidenceAlpha = 0.15 + confidence * 0.85;

        // Pulsing effect when actively decaying
        if (isDecaying && confidence < 0.8) {
            const pulseFreq = 1.5 + (1.0 - confidence) * 2.0; // faster pulse at lower confidence
            const pulse = Math.sin(performance.now() / 1000 * pulseFreq * Math.PI * 2) * 0.15;
            confidenceAlpha = Math.max(0.1, confidenceAlpha + pulse);
        }

        ctx.globalAlpha = confidenceAlpha;
    }

    // Track previous confidence for decay detection
    unit._prevConfidence = confidence;

    // Compute health ratio (0.0 = dead, 1.0 = full)
    let health = 1.0;
    if (isNeutralized) {
        health = 0;
    } else if (unit.health !== undefined && unit.maxHealth) {
        health = Math.max(0, Math.min(1, unit.health / unit.maxHealth));
    }

    // Draw using procedural unit icons
    drawUnitIcon(ctx, iconType, alliance, smoothedHeading, sp.x, sp.y, scale, isSelected, health, isHovered);

    // Ghostly glow ring for low-confidence targets
    if (confidence < 0.5 && confidence > 0) {
        ctx.save();
        ctx.globalAlpha = (0.5 - confidence) * 0.6;
        ctx.strokeStyle = alliance === 'hostile' ? '#ff2a6d' : '#00f0ff';
        ctx.lineWidth = 1;
        ctx.setLineDash([3, 3]);
        const glowRadius = scale * 18;
        ctx.beginPath();
        ctx.arc(sp.x, sp.y, glowRadius, 0, Math.PI * 2);
        ctx.stroke();
        ctx.setLineDash([]);
        ctx.restore();
    }

    // Reset alpha after confidence fade
    if (confidence < 1.0) {
        ctx.globalAlpha = 1.0;
    }

    // Fusion indicator for correlated multi-source targets
    const sourceCount = unit.source_count || (unit.sources ? unit.sources.length : 0);
    if (sourceCount >= 2) {
        drawFusionIndicator(ctx, sp.x, sp.y, scale, sourceCount, unit.sources || []);
    }

    // Crowd role indicator (civil_unrest mode — instigator/rioter visual differentiation)
    if (unit.crowdRole && unit.crowdRole !== 'civilian') {
        drawCrowdRoleIndicator(ctx, sp.x, sp.y, scale, unit.crowdRole, unit.instigatorState);
    }

    // Pin icon for pinned targets (top-right of unit)
    if (TritiumStore.isTargetPinned(id)) {
        _drawPinIcon(ctx, sp.x + scale * 8, sp.y - scale * 10, scale);
    }

    // FSM status badge above unit
    _drawStatusBadge(ctx, unit, sp);

    // Morale indicator for combatant units
    if (unit.is_combatant) {
        _drawMoraleIndicator(ctx, unit, sp, scale);
    }

    // Velocity anomaly indicator
    _drawVelocityAnomaly(ctx, id, unit, sp, scale);

    // Labels are drawn by _drawLabels() using label-collision.js
}

// ============================================================
// Velocity Anomaly Detection
// ============================================================

// Track velocity history per unit for anomaly detection
const _velocityHistory = new Map();  // id -> { speeds: number[], lastPos: {x,y}, lastTime: number, anomaly: bool, anomalyTime: number }
const VELOCITY_HISTORY_MAX = 30;
const VELOCITY_ANOMALY_THRESHOLD = 3.0;  // std deviations above mean
const VELOCITY_ANOMALY_DECAY = 8000;     // ms before anomaly fades

function _trackVelocity(id, unit) {
    const pos = unit.position;
    if (!pos || pos.x === undefined) return null;
    const now = performance.now();

    if (!_velocityHistory.has(id)) {
        _velocityHistory.set(id, { speeds: [], lastPos: { x: pos.x, y: pos.y }, lastTime: now, anomaly: false, anomalyTime: 0 });
        return null;
    }

    const hist = _velocityHistory.get(id);
    const dt = (now - hist.lastTime) / 1000;
    if (dt < 0.1) return hist; // too soon

    // Use unit.speed if available, else compute from position delta
    let speed = unit.speed;
    if (speed === undefined || speed === null) {
        const dx = pos.x - hist.lastPos.x;
        const dy = pos.y - hist.lastPos.y;
        speed = Math.sqrt(dx * dx + dy * dy) / dt;
    }

    hist.lastPos = { x: pos.x, y: pos.y };
    hist.lastTime = now;

    hist.speeds.push(speed);
    if (hist.speeds.length > VELOCITY_HISTORY_MAX) hist.speeds.shift();

    // Compute anomaly: speed > mean + THRESHOLD * stddev
    if (hist.speeds.length >= 5) {
        const mean = hist.speeds.reduce((a, b) => a + b, 0) / hist.speeds.length;
        const variance = hist.speeds.reduce((a, b) => a + (b - mean) ** 2, 0) / hist.speeds.length;
        const stddev = Math.sqrt(variance);
        const threshold = mean + VELOCITY_ANOMALY_THRESHOLD * Math.max(stddev, 0.5);

        if (speed > threshold && speed > 1.0) {
            hist.anomaly = true;
            hist.anomalyTime = now;
        } else if (hist.anomaly && (now - hist.anomalyTime) > VELOCITY_ANOMALY_DECAY) {
            hist.anomaly = false;
        }
    }

    return hist;
}

function _drawVelocityAnomaly(ctx, id, unit, sp, scale) {
    const hist = _trackVelocity(id, unit);
    if (!hist || !hist.anomaly) return;

    const age = performance.now() - hist.anomalyTime;
    const fadeAlpha = Math.max(0, 1.0 - age / VELOCITY_ANOMALY_DECAY);
    if (fadeAlpha <= 0) return;

    ctx.save();
    ctx.globalAlpha = fadeAlpha;

    // Warning triangle icon offset to top-right
    const ox = sp.x + scale * 12;
    const oy = sp.y - scale * 14;
    const sz = Math.max(6, scale * 5);

    // Yellow warning triangle background
    ctx.fillStyle = '#fcee0a';
    ctx.beginPath();
    ctx.moveTo(ox, oy - sz);
    ctx.lineTo(ox - sz * 0.85, oy + sz * 0.6);
    ctx.lineTo(ox + sz * 0.85, oy + sz * 0.6);
    ctx.closePath();
    ctx.fill();

    // Exclamation mark
    ctx.fillStyle = '#0a0a0f';
    ctx.font = `bold ${Math.max(7, sz)}px monospace`;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText('!', ox, oy);

    ctx.restore();

    // Store click area for velocity history popup
    if (!_state.velocityAnomalyAreas) _state.velocityAnomalyAreas = [];
    _state.velocityAnomalyAreas.push({ x: ox, y: oy, r: sz * 1.5, id, hist });
}

// Velocity anomaly click handler — show velocity history modal
function _showVelocityHistoryModal(id, hist) {
    // Remove existing modal
    const existing = document.getElementById('velocity-anomaly-modal');
    if (existing) existing.remove();

    const modal = document.createElement('div');
    modal.id = 'velocity-anomaly-modal';
    modal.className = 'vel-anomaly-modal';

    const speeds = hist.speeds || [];
    const maxSpeed = Math.max(...speeds, 1);
    const mean = speeds.length ? speeds.reduce((a, b) => a + b, 0) / speeds.length : 0;
    const variance = speeds.length ? speeds.reduce((a, b) => a + (b - mean) ** 2, 0) / speeds.length : 0;
    const stddev = Math.sqrt(variance);
    const threshold = mean + VELOCITY_ANOMALY_THRESHOLD * Math.max(stddev, 0.5);

    const bars = speeds.map(s => {
        const h = Math.max(2, (s / maxSpeed) * 100);
        const cls = s > threshold ? 'vel-bar-anomaly' : 'vel-bar-normal';
        return `<div class="vel-bar ${cls}" style="height:${h}%" title="${s.toFixed(2)} m/s"></div>`;
    }).join('');

    modal.innerHTML = `
        <div class="vel-anomaly-content">
            <div class="vel-anomaly-header">
                <h3>VELOCITY ANOMALY: ${id.substring(0, 16)}</h3>
                <button class="panel-action-btn" onclick="document.getElementById('velocity-anomaly-modal').remove()">CLOSE</button>
            </div>
            <div class="vel-chart">${bars}</div>
            <div class="vel-info">
                <div>Mean: <span style="color:var(--cyan)">${mean.toFixed(2)} m/s</span> | Stddev: <span style="color:var(--cyan)">${stddev.toFixed(2)}</span> | Threshold: <span style="color:var(--yellow)">${threshold.toFixed(2)} m/s</span></div>
                <div>Current: <span style="color:${speeds[speeds.length - 1] > threshold ? 'var(--yellow)' : 'var(--cyan)'}">${(speeds[speeds.length - 1] || 0).toFixed(2)} m/s</span> | Samples: ${speeds.length}</div>
            </div>
        </div>
    `;

    modal.addEventListener('click', (e) => {
        if (e.target === modal) modal.remove();
    });

    document.body.appendChild(modal);
}

// Expose for click detection in map click handler
window._showVelocityHistoryModal = _showVelocityHistoryModal;

// ============================================================
// Target shapes
// ============================================================

/**
 * Draw a small pin icon (pushpin shape) at the given position.
 * Used to indicate that a target is pinned and will not be pruned.
 */
function _drawPinIcon(ctx, x, y, scale) {
    const s = Math.max(3, scale * 4);
    ctx.save();
    ctx.fillStyle = '#fcee0a';
    ctx.strokeStyle = '#0a0a0f';
    ctx.lineWidth = 1;
    // Pin head (circle)
    ctx.beginPath();
    ctx.arc(x, y, s, 0, Math.PI * 2);
    ctx.fill();
    ctx.stroke();
    // Pin needle (line down)
    ctx.beginPath();
    ctx.moveTo(x, y + s);
    ctx.lineTo(x, y + s * 2.5);
    ctx.strokeStyle = '#fcee0a';
    ctx.lineWidth = Math.max(1, scale);
    ctx.stroke();
    ctx.restore();
}

function _drawRoundedRect(ctx, cx, cy, size, color) {
    const w = size * 1.6;
    const h = size * 1.2;
    const r = size * 0.3;
    const x = cx - w / 2;
    const y = cy - h / 2;

    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.lineTo(x + w - r, y);
    ctx.quadraticCurveTo(x + w, y, x + w, y + r);
    ctx.lineTo(x + w, y + h - r);
    ctx.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
    ctx.lineTo(x + r, y + h);
    ctx.quadraticCurveTo(x, y + h, x, y + h - r);
    ctx.lineTo(x, y + r);
    ctx.quadraticCurveTo(x, y, x + r, y);
    ctx.closePath();
    ctx.fill();
}

function _drawDiamond(ctx, cx, cy, size, color) {
    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.moveTo(cx, cy - size);
    ctx.lineTo(cx + size, cy);
    ctx.lineTo(cx, cy + size);
    ctx.lineTo(cx - size, cy);
    ctx.closePath();
    ctx.fill();
}

function _drawTriangle(ctx, cx, cy, size, color) {
    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.moveTo(cx, cy - size);
    ctx.lineTo(cx + size, cy + size * 0.7);
    ctx.lineTo(cx - size, cy + size * 0.7);
    ctx.closePath();
    ctx.fill();
}

function _drawCircle(ctx, cx, cy, size, color) {
    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.arc(cx, cy, size, 0, Math.PI * 2);
    ctx.fill();
}

function _drawCircleWithX(ctx, cx, cy, size, color) {
    // Circle
    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.arc(cx, cy, size, 0, Math.PI * 2);
    ctx.fill();

    // X mark inside
    const xOff = size * 0.5;
    ctx.strokeStyle = BG_COLOR;
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(cx - xOff, cy - xOff);
    ctx.lineTo(cx + xOff, cy + xOff);
    ctx.moveTo(cx + xOff, cy - xOff);
    ctx.lineTo(cx - xOff, cy + xOff);
    ctx.stroke();
}

// ============================================================
// Health bar
// ============================================================

function _drawHealthBar(ctx, cx, cy, unitSize, health, maxHealth) {
    const pct = Math.max(0, Math.min(1, health / maxHealth));
    const barW = unitSize * 3;
    const barH = 3;
    const bx = cx - barW / 2;
    const by = cy - unitSize - 8;

    // Background
    ctx.fillStyle = 'rgba(255, 255, 255, 0.15)';
    ctx.fillRect(bx, by, barW, barH);

    // Health fill: green -> yellow -> red
    let r, g;
    if (pct > 0.5) {
        // Green to yellow
        const t = (pct - 0.5) * 2; // 1..0
        r = Math.round(255 * (1 - t));
        g = 255;
    } else {
        // Yellow to red
        const t = pct * 2; // 0..1
        r = 255;
        g = Math.round(255 * t);
    }
    ctx.fillStyle = `rgb(${r}, ${g}, 0)`;
    ctx.fillRect(bx, by, barW * pct, barH);
}

// ============================================================
// Morale indicator (drawn per-unit in _drawUnit)
// ============================================================

function _drawMoraleIndicator(ctx, unit, sp, scale) {
    const morale = unit.morale;
    if (morale === undefined || morale === null) return;

    // Normal morale (0.3-0.9): no special indicator
    if (morale >= 0.3 && morale <= 0.9) return;

    ctx.save();
    const r = 12 * scale;

    if (morale < 0.1) {
        // BROKEN: pulsing red ring
        const pulse = 0.4 + 0.6 * Math.abs(Math.sin(Date.now() * 0.006));
        ctx.strokeStyle = `rgba(255, 42, 109, ${pulse})`;
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.arc(sp.x, sp.y, r + 4, 0, Math.PI * 2);
        ctx.stroke();
        // "BROKEN" text
        ctx.font = `bold 7px ${FONT_FAMILY}`;
        ctx.textAlign = 'center';
        ctx.fillStyle = `rgba(255, 42, 109, ${pulse})`;
        ctx.fillText('BROKEN', sp.x, sp.y + r + 14);
    } else if (morale < 0.3) {
        // SUPPRESSED: yellow dashed outline
        ctx.strokeStyle = 'rgba(252, 238, 10, 0.5)';
        ctx.lineWidth = 1.5;
        ctx.setLineDash([3, 3]);
        ctx.beginPath();
        ctx.arc(sp.x, sp.y, r + 3, 0, Math.PI * 2);
        ctx.stroke();
        ctx.setLineDash([]);
    } else if (morale > 0.9) {
        // EMBOLDENED: green glow
        ctx.shadowColor = '#05ffa1';
        ctx.shadowBlur = 8 * scale;
        ctx.strokeStyle = 'rgba(5, 255, 161, 0.6)';
        ctx.lineWidth = 1.5;
        ctx.beginPath();
        ctx.arc(sp.x, sp.y, r + 2, 0, Math.PI * 2);
        ctx.stroke();
        ctx.shadowBlur = 0;
    }

    ctx.restore();
}

// ============================================================
// Cover points overlay (Layer 4.45)
// ============================================================

function _drawCoverPoints(ctx) {
    const points = TritiumStore.get('game.coverPoints');
    if (!Array.isArray(points) || points.length === 0) return;

    ctx.save();
    for (const cp of points) {
        if (!cp.position || !Array.isArray(cp.position)) continue;
        const sp = worldToScreen(cp.position[0], cp.position[1]);
        const radiusPx = (cp.radius || 2) * _state.cam.zoom;

        // Translucent radius circle
        ctx.beginPath();
        ctx.arc(sp.x, sp.y, radiusPx, 0, Math.PI * 2);
        ctx.fillStyle = 'rgba(74, 158, 255, 0.08)';
        ctx.fill();
        ctx.strokeStyle = 'rgba(0, 240, 255, 0.25)';
        ctx.lineWidth = 1;
        ctx.stroke();

        // Shield icon at center (small chevron/V shape)
        const sz = Math.max(4, 6 * Math.min(_state.cam.zoom, 2));
        ctx.beginPath();
        ctx.moveTo(sp.x - sz, sp.y - sz * 0.6);
        ctx.lineTo(sp.x, sp.y + sz * 0.6);
        ctx.lineTo(sp.x + sz, sp.y - sz * 0.6);
        ctx.strokeStyle = 'rgba(0, 240, 255, 0.5)';
        ctx.lineWidth = 1.5;
        ctx.stroke();
    }
    ctx.restore();
}

// ============================================================
// Squad formation lines (Layer 5.05)
// ============================================================

const SQUAD_COLORS = [
    'rgba(0, 240, 255, 0.35)',   // cyan
    'rgba(255, 136, 0, 0.35)',   // orange
    'rgba(5, 255, 161, 0.35)',   // green
    'rgba(252, 238, 10, 0.35)',  // yellow
    'rgba(170, 100, 255, 0.35)', // purple
    'rgba(255, 42, 109, 0.35)',  // magenta
    'rgba(100, 200, 255, 0.35)', // light blue
    'rgba(255, 200, 100, 0.35)', // gold
];

function _drawSquadLines(ctx) {
    // Group units by squadId
    const squads = new Map();
    for (const [id, unit] of TritiumStore.units) {
        const sid = unit.squadId || unit.squad_id;
        if (!sid) continue;
        const status = (unit.status || 'active').toLowerCase();
        if (status === 'eliminated' || status === 'destroyed') continue;
        const pos = unit.position;
        if (!pos || pos.x === undefined || pos.y === undefined) continue;
        if (!squads.has(sid)) squads.set(sid, []);
        squads.get(sid).push({ x: pos.x, y: pos.y });
    }

    if (squads.size === 0) return;

    ctx.save();
    ctx.globalAlpha = 0.5;
    ctx.lineWidth = 1;
    let colorIdx = 0;

    for (const [sid, members] of squads) {
        if (members.length < 2) continue;
        ctx.strokeStyle = SQUAD_COLORS[colorIdx % SQUAD_COLORS.length];
        colorIdx++;

        // Draw lines from each member to the centroid
        let cx = 0, cy = 0;
        for (const m of members) { cx += m.x; cy += m.y; }
        cx /= members.length;
        cy /= members.length;
        const centroid = worldToScreen(cx, cy);

        for (const m of members) {
            const sp = worldToScreen(m.x, m.y);
            ctx.beginPath();
            ctx.moveTo(sp.x, sp.y);
            ctx.lineTo(centroid.x, centroid.y);
            ctx.stroke();
        }
    }

    ctx.restore();
}

// ============================================================
// Layer 6: Selection indicator
// ============================================================

function _drawSelectionIndicator(ctx) {
    const selectedId = TritiumStore.get('map.selectedUnitId');
    if (!selectedId) return;

    const unit = TritiumStore.units.get(selectedId);
    if (!unit || !unit.position) return;

    const sp = worldToScreen(unit.position.x, unit.position.y);
    const radius = 10 * Math.min(_state.cam.zoom, 3);

    // Animated selection ring
    ctx.strokeStyle = '#00f0ff';
    ctx.lineWidth = 2;
    ctx.shadowColor = '#00f0ff';
    ctx.shadowBlur = 8;
    ctx.beginPath();
    ctx.arc(sp.x, sp.y, radius + 4, 0, Math.PI * 2);
    ctx.stroke();
    ctx.shadowBlur = 0;

    // Pulsing outer ring
    const pulse = 0.5 + 0.5 * Math.sin(performance.now() / 300);
    ctx.strokeStyle = `rgba(0, 240, 255, ${0.15 + pulse * 0.2})`;
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.arc(sp.x, sp.y, radius + 8 + pulse * 3, 0, Math.PI * 2);
    ctx.stroke();

    // Draw multi-select rings for other selected units
    for (const uid of _state.selectedUnitIds) {
        if (uid === selectedId) continue;
        const u = TritiumStore.units.get(uid);
        if (!u || !u.position) continue;
        const usp = worldToScreen(u.position.x, u.position.y);
        const ur = 10 * Math.min(_state.cam.zoom, 3);
        ctx.strokeStyle = '#fcee0a';
        ctx.lineWidth = 2;
        ctx.setLineDash([4, 4]);
        ctx.beginPath();
        ctx.arc(usp.x, usp.y, ur + 4, 0, Math.PI * 2);
        ctx.stroke();
        ctx.setLineDash([]);
    }
}

// ============================================================
// Layer 7: Dispatch arrows
// ============================================================

function _drawDispatchArrows(ctx) {
    const now = Date.now();

    for (const arrow of _state.dispatchArrows) {
        const age = now - arrow.time;
        const alpha = Math.max(0, 1 - age / DISPATCH_ARROW_LIFETIME);
        const from = worldToScreen(arrow.fromX, arrow.fromY);
        const to = worldToScreen(arrow.toX, arrow.toY);

        // Dashed line
        ctx.strokeStyle = `rgba(0, 240, 255, ${alpha})`;
        ctx.lineWidth = 2;
        ctx.setLineDash([8, 4]);
        ctx.beginPath();
        ctx.moveTo(from.x, from.y);
        ctx.lineTo(to.x, to.y);
        ctx.stroke();
        ctx.setLineDash([]);

        // Arrowhead
        const angle = Math.atan2(to.y - from.y, to.x - from.x);
        const headLen = 12;
        ctx.fillStyle = `rgba(0, 240, 255, ${alpha})`;
        ctx.beginPath();
        ctx.moveTo(to.x, to.y);
        ctx.lineTo(to.x - headLen * Math.cos(angle - 0.4), to.y - headLen * Math.sin(angle - 0.4));
        ctx.lineTo(to.x - headLen * Math.cos(angle + 0.4), to.y - headLen * Math.sin(angle + 0.4));
        ctx.closePath();
        ctx.fill();

        // "DISPATCHING" label at midpoint
        if (alpha > 0.3) {
            const mx = (from.x + to.x) / 2;
            const my = (from.y + to.y) / 2;
            ctx.font = '10px "JetBrains Mono", monospace';
            ctx.textAlign = 'center';
            ctx.textBaseline = 'bottom';
            ctx.fillStyle = `rgba(0, 240, 255, ${alpha * 0.8})`;
            ctx.fillText('DISPATCHING', mx, my - 4);
        }
    }
}

// ============================================================
// Operational bounds (dynamic, based on unit positions)
// ============================================================

/**
 * Compute the operational bounding box from unit positions.
 * Adds 50% padding on each side, enforces minimum extent of +/-200m.
 * Caches result and recomputes when unit count changes.
 */
function _getOperationalBounds() {
    const units = TritiumStore.units;
    if (_state.opBounds && _state.opBoundsUnitCount === units.size) {
        return _state.opBounds;
    }

    let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
    for (const [, unit] of units) {
        const pos = unit.position;
        if (!pos || pos.x === undefined || pos.y === undefined) continue;
        if (pos.x < minX) minX = pos.x;
        if (pos.x > maxX) maxX = pos.x;
        if (pos.y < minY) minY = pos.y;
        if (pos.y > maxY) maxY = pos.y;
    }

    if (!isFinite(minX)) {
        // No units — use default 200m extent
        _state.opBounds = { minX: -200, maxX: 200, minY: -200, maxY: 200 };
        _state.opBoundsUnitCount = units.size;
        return _state.opBounds;
    }

    // Add 50% padding
    const spanX = (maxX - minX) || 10;
    const spanY = (maxY - minY) || 10;
    const padX = spanX * 0.5;
    const padY = spanY * 0.5;
    let bMinX = minX - padX;
    let bMaxX = maxX + padX;
    let bMinY = minY - padY;
    let bMaxY = maxY + padY;

    // Enforce minimum extent of +/-200m
    const MIN_EXTENT = 200;
    const cx = (bMinX + bMaxX) / 2;
    const cy = (bMinY + bMaxY) / 2;
    if (bMaxX - bMinX < MIN_EXTENT * 2) {
        bMinX = cx - MIN_EXTENT;
        bMaxX = cx + MIN_EXTENT;
    }
    if (bMaxY - bMinY < MIN_EXTENT * 2) {
        bMinY = cy - MIN_EXTENT;
        bMaxY = cy + MIN_EXTENT;
    }

    _state.opBounds = { minX: bMinX, maxX: bMaxX, minY: bMinY, maxY: bMaxY };
    _state.opBoundsUnitCount = units.size;
    return _state.opBounds;
}

// ============================================================
// Scale bar
// ============================================================

/**
 * Draw a scale bar in the bottom-left corner of the canvas.
 * Picks a "nice" distance that fits ~100-200px on screen at current zoom.
 */
function _drawScaleBar(ctx) {
    const zoom = _state.cam.zoom;
    if (zoom < 0.01) return; // Too zoomed out for a useful scale bar

    const cssW = _state.canvas.width / _state.dpr;
    const cssH = _state.canvas.height / _state.dpr;
    const targetPixels = 150; // Desired bar width in pixels

    // How many meters does targetPixels represent?
    const metersAtTarget = targetPixels / zoom;

    // Pick a "nice" distance
    const niceDistances = [1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 2000, 5000];
    let niceDist = niceDistances[niceDistances.length - 1];
    for (const d of niceDistances) {
        if (d >= metersAtTarget * 0.4 && d <= metersAtTarget * 1.5) {
            niceDist = d;
            break;
        }
    }

    const barPx = niceDist * zoom;
    const x = 20;
    const y = cssH - 30;
    const tickH = 6;

    // Label
    let label;
    if (niceDist >= 1000) {
        label = `${niceDist / 1000}km`;
    } else {
        label = `${niceDist}m`;
    }

    ctx.save();

    // Line
    ctx.strokeStyle = 'rgba(255, 255, 255, 0.5)';
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.moveTo(x, y);
    ctx.lineTo(x + barPx, y);
    ctx.stroke();

    // End ticks
    ctx.beginPath();
    ctx.moveTo(x, y - tickH);
    ctx.lineTo(x, y + tickH);
    ctx.moveTo(x + barPx, y - tickH);
    ctx.lineTo(x + barPx, y + tickH);
    ctx.stroke();

    // Label
    ctx.fillStyle = 'rgba(255, 255, 255, 0.5)';
    ctx.font = `10px ${FONT_FAMILY}`;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'top';
    ctx.fillText(label, x + barPx / 2, y + tickH + 2);

    ctx.restore();
}

// ============================================================
// Minimap
// ============================================================

function _drawMinimap() {
    // Dynamically find minimap canvas (may come from panel system)
    let mmCanvas = _state.minimapCanvas;
    let ctx = _state.minimapCtx;

    // If cached ref is gone or detached, re-lookup by id
    if (!mmCanvas || !mmCanvas.isConnected) {
        mmCanvas = document.getElementById('minimap-canvas');
        _state.minimapCanvas = mmCanvas;
        _state.minimapCtx = mmCanvas ? mmCanvas.getContext('2d') : null;
        ctx = _state.minimapCtx;
    }

    if (!ctx) {
        _drawMinimapOnMain();
        return;
    }
    const mmRect = mmCanvas?.getBoundingClientRect();
    if (!mmRect || mmRect.width === 0 || mmRect.height === 0) {
        _drawMinimapOnMain();
        return;
    }
    // Resize canvas buffer to match layout if panel was resized
    const layoutW = Math.max(1, Math.floor(mmRect.width));
    const layoutH = Math.max(1, Math.floor(mmRect.height));
    if (mmCanvas.width !== layoutW || mmCanvas.height !== layoutH) {
        mmCanvas.width = layoutW;
        mmCanvas.height = layoutH;
    }
    const mmW = mmCanvas.width;
    const mmH = mmCanvas.height;

    // Clear
    ctx.fillStyle = 'rgba(10, 10, 20, 0.92)';
    ctx.fillRect(0, 0, mmW, mmH);

    // Border
    ctx.strokeStyle = 'rgba(0, 240, 255, 0.25)';
    ctx.lineWidth = 1;
    ctx.strokeRect(0, 0, mmW, mmH);

    // Dynamic bounds from unit positions
    const ob = _getOperationalBounds();
    const obRangeX = ob.maxX - ob.minX;
    const obRangeY = ob.maxY - ob.minY;

    // World-to-minimap helper (uses operational bounds)
    function wToMM(wx, wy) {
        const mx = ((wx - ob.minX) / obRangeX) * mmW;
        const my = ((ob.maxY - wy) / obRangeY) * mmH; // Y flipped
        return { x: mx, y: my };
    }

    // Zones
    for (const zone of _state.zones) {
        const zpos = zone.position || {};
        const zx = zpos.x || 0;
        const zy = zpos.z !== undefined ? zpos.z : (zpos.y || 0);
        const zr = ((zone.properties && zone.properties.radius) || 10) / obRangeX * mmW;
        const zmp = wToMM(zx, zy);
        const isRestricted = (zone.type || '').includes('restricted');
        ctx.fillStyle = isRestricted ? 'rgba(255, 42, 109, 0.15)' : 'rgba(0, 240, 255, 0.08)';
        ctx.beginPath();
        ctx.arc(zmp.x, zmp.y, zr, 0, Math.PI * 2);
        ctx.fill();
    }

    // Units as colored dots
    const units = TritiumStore.units;
    for (const [id, unit] of units) {
        const pos = unit.position;
        if (!pos || pos.x === undefined) continue;
        const mp = wToMM(pos.x, pos.y);
        const alliance = (unit.alliance || 'unknown').toLowerCase();
        const color = ALLIANCE_COLORS[alliance] || ALLIANCE_COLORS.unknown;
        const status = (unit.status || 'active').toLowerCase();
        const isNeutralized = status === 'neutralized' || status === 'eliminated';

        ctx.fillStyle = color;
        ctx.globalAlpha = isNeutralized ? 0.3 : 1.0;
        ctx.beginPath();
        ctx.arc(mp.x, mp.y, 2.5, 0, Math.PI * 2);
        ctx.fill();
    }
    ctx.globalAlpha = 1.0;

    // Camera viewport rectangle
    const cam = _state.cam;
    const mainCanvas = _state.canvas;
    if (mainCanvas && mainCanvas.width > 0) {
        const cssW = mainCanvas.width / _state.dpr;
        const cssH = mainCanvas.height / _state.dpr;
        const halfW = (cssW / 2) / cam.zoom;
        const halfH = (cssH / 2) / cam.zoom;
        const vpTL = wToMM(cam.x - halfW, cam.y + halfH);
        const vpBR = wToMM(cam.x + halfW, cam.y - halfH);
        const vpW = vpBR.x - vpTL.x;
        const vpH = vpBR.y - vpTL.y;

        ctx.strokeStyle = 'rgba(0, 240, 255, 0.6)';
        ctx.lineWidth = 1.5;
        ctx.strokeRect(vpTL.x, vpTL.y, vpW, vpH);
    }
}

/**
 * Draw a minimap on the main canvas (bottom-right corner) when the
 * dedicated minimap canvas element is hidden or unavailable.
 */
function _drawMinimapOnMain() {
    const ctx = _state.ctx;
    if (!ctx) return;
    const mainCssW = _state.canvas.width / _state.dpr;
    const mainCssH = _state.canvas.height / _state.dpr;
    const mmW = 200;
    const mmH = 150;
    const margin = 10;
    const ox = mainCssW - mmW - margin;
    const oy = mainCssH - mmH - margin;

    // Background
    ctx.fillStyle = 'rgba(10, 10, 20, 0.92)';
    ctx.fillRect(ox, oy, mmW, mmH);

    // Border
    ctx.strokeStyle = 'rgba(0, 240, 255, 0.25)';
    ctx.lineWidth = 1;
    ctx.strokeRect(ox, oy, mmW, mmH);

    // Dynamic bounds from unit positions
    const ob = _getOperationalBounds();
    const obRangeX = ob.maxX - ob.minX;
    const obRangeY = ob.maxY - ob.minY;

    function wToMM(wx, wy) {
        const mx = ((wx - ob.minX) / obRangeX) * mmW + ox;
        const my = ((ob.maxY - wy) / obRangeY) * mmH + oy;
        return { x: mx, y: my };
    }

    // Zones
    for (const zone of _state.zones) {
        const zpos = zone.position || {};
        const zx = zpos.x || 0;
        const zy = zpos.z !== undefined ? zpos.z : (zpos.y || 0);
        const zr = ((zone.properties && zone.properties.radius) || 10) / obRangeX * mmW;
        const zmp = wToMM(zx, zy);
        const isRestricted = (zone.type || '').includes('restricted');
        ctx.fillStyle = isRestricted ? 'rgba(255, 42, 109, 0.15)' : 'rgba(0, 240, 255, 0.08)';
        ctx.beginPath();
        ctx.arc(zmp.x, zmp.y, zr, 0, Math.PI * 2);
        ctx.fill();
    }

    // Units
    for (const [, unit] of TritiumStore.units) {
        const pos = unit.position;
        if (!pos || pos.x === undefined) continue;
        const mp = wToMM(pos.x, pos.y);
        const alliance = (unit.alliance || 'unknown').toLowerCase();
        const color = ALLIANCE_COLORS[alliance] || ALLIANCE_COLORS.unknown;
        const status = (unit.status || 'active').toLowerCase();
        const isNeutralized = status === 'neutralized' || status === 'eliminated';

        ctx.fillStyle = color;
        ctx.globalAlpha = isNeutralized ? 0.3 : 1.0;
        ctx.beginPath();
        ctx.arc(mp.x, mp.y, 2.5, 0, Math.PI * 2);
        ctx.fill();
    }
    ctx.globalAlpha = 1.0;

    // Camera viewport rectangle
    const cam = _state.cam;
    const halfW = (mainCssW / 2) / cam.zoom;
    const halfH = (mainCssH / 2) / cam.zoom;
    const vpTL = wToMM(cam.x - halfW, cam.y + halfH);
    const vpBR = wToMM(cam.x + halfW, cam.y - halfH);
    ctx.strokeStyle = 'rgba(0, 240, 255, 0.6)';
    ctx.lineWidth = 1.5;
    ctx.strokeRect(vpTL.x, vpTL.y, vpBR.x - vpTL.x, vpBR.y - vpTL.y);
}

// ============================================================
// FPS counter
// ============================================================

function _updateFps() {
    const now = performance.now();
    _state.frameTimes.push(now);

    // Keep only last 60 frame times
    while (_state.frameTimes.length > 60) {
        _state.frameTimes.shift();
    }

    // Update display every FPS_UPDATE_INTERVAL ms
    if (now - _state.lastFpsUpdate < FPS_UPDATE_INTERVAL) return;
    _state.lastFpsUpdate = now;

    if (_state.frameTimes.length >= 2) {
        const elapsed = _state.frameTimes[_state.frameTimes.length - 1] - _state.frameTimes[0];
        const frames = _state.frameTimes.length - 1;
        _state.currentFps = Math.round((frames / elapsed) * 1000);
    }

    const fpsEl = document.getElementById('map-fps');
    if (fpsEl) {
        fpsEl.textContent = `${_state.currentFps} FPS`;
    }
    const statusEl = document.getElementById('status-fps');
    if (statusEl) statusEl.textContent = `${_state.currentFps} FPS`;
}

// ============================================================
// Coords display
// ============================================================

function _updateCoordsDisplay() {
    const coordsEl = document.getElementById('map-coords');
    if (!coordsEl) return;

    const wp = screenToWorld(_state.lastMouse.x, _state.lastMouse.y);
    const xSpan = coordsEl.querySelector('[data-coord="x"]');
    const ySpan = coordsEl.querySelector('[data-coord="y"]');
    if (xSpan) xSpan.textContent = `X: ${wp.x.toFixed(1)}`;
    if (ySpan) ySpan.textContent = `Y: ${wp.y.toFixed(1)}`;
}

// ============================================================
// Mouse event handlers (main canvas)
// ============================================================

function _bindCanvasEvents() {
    const canvas = _state.canvas;
    if (!canvas) return;

    const handlers = {
        mousedown: _onMouseDown,
        mousemove: _onMouseMove,
        mouseup: _onMouseUp,
        dblclick: _onDblClick,
        wheel: _onWheel,
        contextmenu: _onContextMenu,
    };

    for (const [event, handler] of Object.entries(handlers)) {
        const opts = event === 'wheel' ? { passive: false } : undefined;
        canvas.addEventListener(event, handler, opts);
        _state.boundHandlers.set(`canvas:${event}`, { element: canvas, event, handler, opts });
    }
}

function _unbindCanvasEvents() {
    for (const [key, entry] of _state.boundHandlers) {
        if (!key.startsWith('canvas:')) continue;
        entry.element.removeEventListener(entry.event, entry.handler, entry.opts);
    }
    // Clear canvas entries
    for (const key of [..._state.boundHandlers.keys()]) {
        if (key.startsWith('canvas:')) _state.boundHandlers.delete(key);
    }
}

function _onMouseDown(e) {
    _hideContextMenu();
    const rect = _state.canvas.getBoundingClientRect();
    const sx = e.clientX - rect.left;
    const sy = e.clientY - rect.top;
    _state.lastMouse = { x: sx, y: sy };

    // Middle-click or Alt+left = pan
    if (e.button === 1 || (e.button === 0 && e.altKey)) {
        _state.isPanning = true;
        _state.dragStart = {
            x: sx,
            y: sy,
            camX: _state.cam.targetX,
            camY: _state.cam.targetY,
        };
        e.preventDefault();
        return;
    }

    // Right-click = pan or dispatch (handled in mouseup)
    if (e.button === 2) {
        _state.isPanning = true;
        _state.dragStart = {
            x: sx,
            y: sy,
            camX: _state.cam.targetX,
            camY: _state.cam.targetY,
        };
        e.preventDefault();
        return;
    }

    // Left click
    if (e.button === 0) {
        // Geofence drawing mode: click to add vertex
        if (_state.geofenceDrawing) {
            const wp = screenToWorld(sx, sy);
            _geofenceAddVertex(wp);
            return;
        }

        // Patrol drawing mode: click to add waypoint
        if (_state.patrolDrawing) {
            const wp = screenToWorld(sx, sy);
            _patrolAddWaypoint(wp);
            return;
        }

        // Dispatch mode: click to send selected unit somewhere
        if (_state.dispatchMode && _state.dispatchUnitId) {
            const wp = screenToWorld(sx, sy);
            _doDispatch(_state.dispatchUnitId, wp.x, wp.y);
            _state.dispatchMode = false;
            _state.dispatchUnitId = null;
            _state.canvas.style.cursor = 'crosshair';
            return;
        }

        // Hit test velocity anomaly indicators first
        if (_state.velocityAnomalyAreas) {
            for (const area of _state.velocityAnomalyAreas) {
                const dx = sx - area.x;
                const dy = sy - area.y;
                if (dx * dx + dy * dy < area.r * area.r) {
                    _showVelocityHistoryModal(area.id, area.hist);
                    return;
                }
            }
        }

        // Hit test units
        const hitId = _hitTestUnit(sx, sy);
        if (hitId) {
            if (e.shiftKey) {
                // Multi-select: toggle unit in selection set
                if (_state.selectedUnitIds.has(hitId)) {
                    _state.selectedUnitIds.delete(hitId);
                } else {
                    _state.selectedUnitIds.add(hitId);
                }
                // Also set primary selected to the clicked unit
                TritiumStore.set('map.selectedUnitId', hitId);
                EventBus.emit('unit:selected', { id: hitId });
                EventBus.emit('multiselect:changed', {
                    ids: Array.from(_state.selectedUnitIds),
                    count: _state.selectedUnitIds.size,
                });
                if (_state.selectedUnitIds.size > 1) {
                    _showMultiSelectBar();
                } else {
                    _hideMultiSelectBar();
                }
            } else {
                // Single select: clear multi-select
                _state.selectedUnitIds.clear();
                _state.selectedUnitIds.add(hitId);
                TritiumStore.set('map.selectedUnitId', hitId);
                EventBus.emit('unit:selected', { id: hitId });
                EventBus.emit('panel:request-open', { id: 'unit-inspector' });
                _hideMultiSelectBar();
            }
        } else {
            // Click on empty space: clear all
            _state.selectedUnitIds.clear();
            TritiumStore.set('map.selectedUnitId', null);
            EventBus.emit('unit:deselected', {});
            EventBus.emit('multiselect:changed', { ids: [], count: 0 });
            _hideMultiSelectBar();
        }
    }
}

function _onMouseMove(e) {
    const rect = _state.canvas.getBoundingClientRect();
    const sx = e.clientX - rect.left;
    const sy = e.clientY - rect.top;
    _state.lastMouse = { x: sx, y: sy };

    // Panning
    if (_state.isPanning && _state.dragStart) {
        const dx = (sx - _state.dragStart.x) / _state.cam.zoom;
        const dy = (sy - _state.dragStart.y) / _state.cam.zoom;
        _state.cam.targetX = _state.dragStart.camX - dx;
        _state.cam.targetY = _state.dragStart.camY + dy; // Y inverted
        return;
    }

    // Hover detection
    const hitId = _hitTestUnit(sx, sy);
    _state.hoveredUnit = hitId;

    // Cursor
    if (_state.dispatchMode) {
        _state.canvas.style.cursor = 'crosshair';
    } else if (hitId) {
        _state.canvas.style.cursor = 'pointer';
    } else {
        _state.canvas.style.cursor = 'crosshair';
    }
}

function _onMouseUp(e) {
    const rect = _state.canvas.getBoundingClientRect();
    const sx = e.clientX - rect.left;
    const sy = e.clientY - rect.top;

    if (_state.isPanning) {
        // If right-click and barely moved, show context menu
        if (e.button === 2 && _state.dragStart) {
            const dx = Math.abs(sx - _state.dragStart.x);
            const dy = Math.abs(sy - _state.dragStart.y);
            if (dx < 5 && dy < 5) {
                const wp = screenToWorld(sx, sy);
                const selectedId = TritiumStore.get('map.selectedUnitId');
                if (selectedId) {
                    // Quick dispatch for selected unit (existing behavior)
                    _doDispatch(selectedId, wp.x, wp.y);
                }
                // Also show context menu for additional options
                _showContextMenu(e.clientX, e.clientY, wp);
            }
        }
        _state.isPanning = false;
        _state.dragStart = null;
        return;
    }
}

function _onWheel(e) {
    e.preventDefault();

    const rect = _state.canvas.getBoundingClientRect();
    const sx = e.clientX - rect.left;
    const sy = e.clientY - rect.top;

    const factor = e.deltaY > 0 ? 0.9 : 1.1;
    const newZoom = Math.max(ZOOM_MIN, Math.min(ZOOM_MAX, _state.cam.targetZoom * factor));

    // Cursor-centered zoom: keep world point under cursor stable
    const wp = screenToWorld(sx, sy);
    const cssW = _state.canvas.width / _state.dpr;
    const cssH = _state.canvas.height / _state.dpr;
    _state.cam.targetX = wp.x - (sx - cssW / 2) / newZoom;
    _state.cam.targetY = wp.y + (sy - cssH / 2) / newZoom;
    _state.cam.targetZoom = newZoom;
}

function _resolveModalType(unit) {
    const type = unit.asset_type || unit.type || 'generic';
    const alliance = unit.alliance || 'unknown';
    const npcTypes = ['person', 'animal', 'vehicle'];
    return (npcTypes.includes(type) && alliance === 'neutral') ? 'npc' : type;
}

function _onDblClick(e) {
    const rect = _state.canvas.getBoundingClientRect();
    const sx = e.clientX - rect.left;
    const sy = e.clientY - rect.top;

    const hitId = _hitTestUnit(sx, sy);
    if (hitId) {
        TritiumStore.set('map.selectedUnitId', hitId);
        EventBus.emit('unit:selected', { id: hitId });
        const unit = TritiumStore.units.get(hitId);
        if (unit) {
            if (unit.position) {
                _state.cam.targetX = unit.position.x;
                _state.cam.targetY = unit.position.y;
            }
            // Open the rich target detail modal
            _openTargetDetailModal(hitId, unit);
        }
    }
}

/**
 * Open a rich target detail modal with identifiers, signal timeline,
 * enrichments, dossier link, position trail, and RSSI/confidence.
 */
async function _openTargetDetailModal(targetId, unit) {
    // Remove any existing modal
    const existing = document.getElementById('target-detail-modal');
    if (existing) existing.remove();

    const alliance = (unit.alliance || 'unknown').toLowerCase();
    const allianceColor = ALLIANCE_COLORS[alliance] || '#fcee0a';
    const type = unit.asset_type || unit.type || 'unknown';
    const source = unit.source || 'unknown';
    const rssi = unit.rssi ?? unit.signal_strength ?? '--';
    const confidence = unit.confidence != null ? Math.round(unit.confidence * 100) + '%' : '--';
    const lat = unit.lat != null ? unit.lat.toFixed(6) : (unit.position?.x?.toFixed(1) || '--');
    const lng = unit.lng != null ? unit.lng.toFixed(6) : (unit.position?.y?.toFixed(1) || '--');
    const speed = unit.speed != null ? unit.speed.toFixed(1) + ' m/s' : '--';
    const heading = unit.heading != null ? Math.round(unit.heading) + 'deg' : '--';
    const health = unit.health != null ? Math.round(unit.health) + '%' : '--';
    const fsm = unit.fsm_state || unit.state || '--';
    const name = unit.name || unit.label || targetId;
    const manufacturer = unit.manufacturer || unit.oui || '';
    const deviceClass = unit.device_class || unit.classification || '';

    // Build identifiers section
    const identifiers = [];
    identifiers.push(`<div class="tdm-id-row"><span class="tdm-id-key">TARGET ID</span><span class="tdm-id-val mono">${_escMap(targetId)}</span></div>`);
    if (unit.mac) identifiers.push(`<div class="tdm-id-row"><span class="tdm-id-key">MAC</span><span class="tdm-id-val mono">${_escMap(unit.mac)}</span></div>`);
    if (unit.device_id) identifiers.push(`<div class="tdm-id-row"><span class="tdm-id-key">DEVICE ID</span><span class="tdm-id-val mono">${_escMap(unit.device_id)}</span></div>`);
    if (manufacturer) identifiers.push(`<div class="tdm-id-row"><span class="tdm-id-key">MFR</span><span class="tdm-id-val">${_escMap(manufacturer)}</span></div>`);
    if (deviceClass) identifiers.push(`<div class="tdm-id-row"><span class="tdm-id-key">CLASS</span><span class="tdm-id-val">${_escMap(deviceClass)}</span></div>`);
    if (unit.ssid) identifiers.push(`<div class="tdm-id-row"><span class="tdm-id-key">SSID</span><span class="tdm-id-val">${_escMap(unit.ssid)}</span></div>`);
    if (unit.bssid) identifiers.push(`<div class="tdm-id-row"><span class="tdm-id-key">BSSID</span><span class="tdm-id-val mono">${_escMap(unit.bssid)}</span></div>`);

    // Fetch trail data for mini-map
    let trailHtml = '<div class="tdm-trail-empty">No trail data</div>';
    try {
        const trailRes = await fetch(`/api/targets/${encodeURIComponent(targetId)}/trail?max_points=50`);
        if (trailRes.ok) {
            const trailData = await trailRes.json();
            if (trailData.trail && trailData.trail.length > 1) {
                trailHtml = _renderTrailMiniMap(trailData.trail, 200, 120);
            }
        }
    } catch (_) { /* skip */ }

    // Fetch dossier for enrichments
    let enrichHtml = '';
    let dossierLink = '';
    try {
        const dosRes = await fetch(`/api/dossiers/${encodeURIComponent(targetId)}`);
        if (dosRes.ok) {
            const dossier = await dosRes.json();
            dossierLink = `<a href="#" class="tdm-dossier-link" onclick="event.preventDefault(); window.EventBus && window.EventBus.emit('panel:request-open', {id: 'dossiers'})">VIEW FULL DOSSIER</a>`;
            const enrichments = dossier.enrichments || [];
            if (enrichments.length > 0) {
                enrichHtml = '<div class="tdm-section-title">ENRICHMENTS</div>';
                for (const e of enrichments.slice(0, 5)) {
                    enrichHtml += `<div class="tdm-enrich-row"><span class="tdm-enrich-src">${_escMap(e.source || '')}</span><span class="tdm-enrich-val">${_escMap(e.value || e.data || '')}</span></div>`;
                }
            }
        }
    } catch (_) { /* skip */ }

    const modal = document.createElement('div');
    modal.id = 'target-detail-modal';
    modal.className = 'tdm-overlay';
    modal.innerHTML = `
        <div class="tdm-content">
            <div class="tdm-header" style="border-left: 3px solid ${allianceColor}">
                <div class="tdm-header-info">
                    <div class="tdm-name mono">${_escMap(name)}</div>
                    <div class="tdm-subtitle">
                        <span class="tdm-badge" style="background:${allianceColor}">${alliance.toUpperCase()}</span>
                        <span class="tdm-type">${_escMap(type.toUpperCase())}</span>
                        <span class="tdm-source">${_escMap(source)}</span>
                    </div>
                </div>
                <button class="tdm-close" onclick="document.getElementById('target-detail-modal')?.remove()">&times;</button>
            </div>
            <div class="tdm-body">
                <div class="tdm-col tdm-col-left">
                    <div class="tdm-section-title">IDENTIFIERS</div>
                    ${identifiers.join('')}

                    <div class="tdm-section-title" style="margin-top:12px">SIGNAL</div>
                    <div class="tdm-stats-grid">
                        <div class="tdm-stat"><div class="tdm-stat-label">RSSI</div><div class="tdm-stat-value">${rssi}</div></div>
                        <div class="tdm-stat"><div class="tdm-stat-label">CONF</div><div class="tdm-stat-value">${confidence}</div></div>
                        <div class="tdm-stat"><div class="tdm-stat-label">SPEED</div><div class="tdm-stat-value">${speed}</div></div>
                        <div class="tdm-stat"><div class="tdm-stat-label">HDG</div><div class="tdm-stat-value">${heading}</div></div>
                    </div>

                    <div class="tdm-section-title" style="margin-top:12px">STATUS</div>
                    <div class="tdm-stats-grid">
                        <div class="tdm-stat"><div class="tdm-stat-label">HEALTH</div><div class="tdm-stat-value">${health}</div></div>
                        <div class="tdm-stat"><div class="tdm-stat-label">STATE</div><div class="tdm-stat-value">${_escMap(String(fsm))}</div></div>
                        <div class="tdm-stat"><div class="tdm-stat-label">POS</div><div class="tdm-stat-value mono" style="font-size:0.55rem">${lat}, ${lng}</div></div>
                    </div>

                    ${enrichHtml}
                    ${dossierLink}
                </div>
                <div class="tdm-col tdm-col-right">
                    <div class="tdm-section-title">POSITION TRAIL</div>
                    <div class="tdm-trail-container">${trailHtml}</div>

                    <div class="tdm-section-title" style="margin-top:12px">QUICK ACTIONS</div>
                    <div class="tdm-quick-actions">
                        <button class="tdm-qa-btn tdm-qa-investigate" data-target="${_escMap(targetId)}" title="Create investigation for this target">INVESTIGATE</button>
                        <button class="tdm-qa-btn tdm-qa-watch" data-target="${_escMap(targetId)}" title="Add to watch list">WATCH</button>
                        <button class="tdm-qa-btn tdm-qa-classify" data-target="${_escMap(targetId)}" title="Override alliance classification">CLASSIFY</button>
                        <button class="tdm-qa-btn tdm-qa-track" data-target="${_escMap(targetId)}" title="Enable prediction cones">TRACK</button>
                    </div>

                    <div class="tdm-actions" style="margin-top:8px">
                        <button class="tdm-action-btn" onclick="window.EventBus && window.EventBus.emit('panel:request-open', {id: 'graph-explorer'}); document.getElementById('target-detail-modal')?.remove()">GRAPH</button>
                        <button class="tdm-action-btn" onclick="window.EventBus && window.EventBus.emit('panel:request-open', {id: 'unit-inspector'}); document.getElementById('target-detail-modal')?.remove()">INSPECT</button>
                    </div>
                </div>
            </div>
        </div>
    `;

    // Close on overlay click
    modal.addEventListener('click', (ev) => {
        if (ev.target === modal) modal.remove();
    });

    // Close on Escape
    const escHandler = (ev) => {
        if (ev.key === 'Escape') { modal.remove(); document.removeEventListener('keydown', escHandler); }
    };
    document.addEventListener('keydown', escHandler);

    document.body.appendChild(modal);

    // Wire quick-action buttons
    _bindQuickActionButtons(modal, targetId);
}

/**
 * Execute a quick action via the /api/quick-actions endpoint.
 */
async function _executeQuickAction(actionType, targetId, params = {}, notes = '') {
    try {
        const res = await fetch('/api/quick-actions', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                action_type: actionType,
                target_id: targetId,
                params,
                notes,
            }),
        });
        if (res.ok) {
            const data = await res.json();
            return data;
        }
    } catch (e) {
        console.warn('Quick action failed:', e);
    }
    return null;
}

/**
 * Bind click handlers to quick-action buttons in the target detail modal.
 */
function _bindQuickActionButtons(modal, targetId) {
    const investigateBtn = modal.querySelector('.tdm-qa-investigate');
    if (investigateBtn) {
        investigateBtn.addEventListener('click', async () => {
            investigateBtn.textContent = '...';
            investigateBtn.disabled = true;
            const result = await _executeQuickAction('investigate', targetId);
            if (result && result.details && result.details.created) {
                investigateBtn.textContent = 'CREATED';
                investigateBtn.style.background = '#05ffa1';
                investigateBtn.style.color = '#0a0a0f';
            } else {
                investigateBtn.textContent = 'FAILED';
                investigateBtn.style.background = '#ff2a6d';
            }
        });
    }

    const watchBtn = modal.querySelector('.tdm-qa-watch');
    if (watchBtn) {
        watchBtn.addEventListener('click', async () => {
            watchBtn.textContent = '...';
            watchBtn.disabled = true;
            const result = await _executeQuickAction('watch', targetId);
            if (result && result.details && result.details.added) {
                watchBtn.textContent = 'WATCHING';
                watchBtn.style.background = '#fcee0a';
                watchBtn.style.color = '#0a0a0f';
            } else {
                watchBtn.textContent = 'FAILED';
                watchBtn.style.background = '#ff2a6d';
            }
        });
    }

    const classifyBtn = modal.querySelector('.tdm-qa-classify');
    if (classifyBtn) {
        classifyBtn.addEventListener('click', async () => {
            // Cycle through alliances on click
            const alliances = ['hostile', 'friendly', 'neutral', 'unknown'];
            const currentIdx = alliances.indexOf(classifyBtn.dataset.currentAlliance || 'hostile');
            const nextAlliance = alliances[(currentIdx + 1) % alliances.length];
            classifyBtn.dataset.currentAlliance = nextAlliance;
            classifyBtn.textContent = '...';
            classifyBtn.disabled = true;
            const result = await _executeQuickAction('classify', targetId, { alliance: nextAlliance });
            if (result && result.details && result.details.classified) {
                const colors = { hostile: '#ff2a6d', friendly: '#05ffa1', neutral: '#fcee0a', unknown: '#888' };
                classifyBtn.textContent = nextAlliance.toUpperCase();
                classifyBtn.style.background = colors[nextAlliance] || '#888';
                classifyBtn.style.color = '#0a0a0f';
                classifyBtn.disabled = false;
            } else {
                classifyBtn.textContent = 'FAILED';
                classifyBtn.style.background = '#ff2a6d';
            }
        });
    }

    const trackBtn = modal.querySelector('.tdm-qa-track');
    if (trackBtn) {
        trackBtn.addEventListener('click', async () => {
            trackBtn.textContent = '...';
            trackBtn.disabled = true;
            const result = await _executeQuickAction('track', targetId, { prediction_cone: true, minutes_ahead: 5 });
            if (result && result.details && result.details.tracking) {
                trackBtn.textContent = 'TRACKING';
                trackBtn.style.background = '#00f0ff';
                trackBtn.style.color = '#0a0a0f';
            } else {
                trackBtn.textContent = 'FAILED';
                trackBtn.style.background = '#ff2a6d';
            }
        });
    }
}

/**
 * Render a trail as an inline SVG mini-map.
 */
function _renderTrailMiniMap(trail, width, height) {
    if (!trail || trail.length < 2) return '<div class="tdm-trail-empty">Insufficient trail data</div>';

    // Get bounds
    let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
    for (const pt of trail) {
        const x = pt.x ?? pt.lng ?? 0;
        const y = pt.y ?? pt.lat ?? 0;
        if (x < minX) minX = x;
        if (x > maxX) maxX = x;
        if (y < minY) minY = y;
        if (y > maxY) maxY = y;
    }

    const rangeX = maxX - minX || 1;
    const rangeY = maxY - minY || 1;
    const pad = 10;
    const iw = width - pad * 2;
    const ih = height - pad * 2;

    // Build polyline points
    const points = trail.map(pt => {
        const x = pt.x ?? pt.lng ?? 0;
        const y = pt.y ?? pt.lat ?? 0;
        const sx = pad + ((x - minX) / rangeX) * iw;
        const sy = pad + ih - ((y - minY) / rangeY) * ih;
        return `${sx.toFixed(1)},${sy.toFixed(1)}`;
    }).join(' ');

    // Last point marker
    const lastPt = trail[trail.length - 1];
    const lx = pad + (((lastPt.x ?? lastPt.lng ?? 0) - minX) / rangeX) * iw;
    const ly = pad + ih - (((lastPt.y ?? lastPt.lat ?? 0) - minY) / rangeY) * ih;

    return `<svg width="${width}" height="${height}" viewBox="0 0 ${width} ${height}" style="background:#060609;border:1px solid rgba(0,240,255,0.2);border-radius:4px">
        <polyline points="${points}" fill="none" stroke="#00f0ff" stroke-width="1.5" stroke-opacity="0.7"/>
        <circle cx="${lx.toFixed(1)}" cy="${ly.toFixed(1)}" r="4" fill="#00f0ff" stroke="#fff" stroke-width="1"/>
        <text x="${width-4}" y="${height-4}" text-anchor="end" fill="#666" font-size="8" font-family="monospace">${trail.length} pts</text>
    </svg>`;
}

function _escMap(text) {
    if (!text) return '';
    return String(text).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function _onContextMenu(e) {
    e.preventDefault();
}

// ============================================================
// Minimap mouse events
// ============================================================

function _bindMinimapEvents() {
    const mm = _state.minimapCanvas;
    if (!mm) return;

    const handler = _onMinimapClick;
    mm.addEventListener('mousedown', handler);
    mm.addEventListener('mousemove', (e) => {
        if (e.buttons & 1) handler(e); // Drag on minimap
    });
    _state.boundHandlers.set('minimap:mousedown', { element: mm, event: 'mousedown', handler });
}

function _unbindMinimapEvents() {
    for (const [key, entry] of _state.boundHandlers) {
        if (!key.startsWith('minimap:')) continue;
        entry.element.removeEventListener(entry.event, entry.handler);
    }
    for (const key of [..._state.boundHandlers.keys()]) {
        if (key.startsWith('minimap:')) _state.boundHandlers.delete(key);
    }
}

function _onMinimapClick(e) {
    const mm = _state.minimapCanvas;
    const rect = mm.getBoundingClientRect();
    const mx = e.clientX - rect.left;
    const my = e.clientY - rect.top;

    // Convert minimap coords to world coords (using operational bounds)
    const ob = _getOperationalBounds();
    const obRangeX = ob.maxX - ob.minX;
    const obRangeY = ob.maxY - ob.minY;
    const wx = ob.minX + (mx / mm.width) * obRangeX;
    const wy = ob.maxY - (my / mm.height) * obRangeY; // Y flipped

    _state.cam.targetX = wx;
    _state.cam.targetY = wy;
}

// ============================================================
// Hit testing
// ============================================================

function _hitTestUnit(sx, sy) {
    const hitRadius = 14;
    let closest = null;
    let closestDist = Infinity;
    const fogEnabled = _state.fogEnabled;

    const units = TritiumStore.units;
    for (const [id, unit] of units) {
        const pos = unit.position;
        if (!pos || pos.x === undefined) continue;
        // Fog of war: cannot select invisible hostile units
        if (fogEnabled) {
            const alliance = (unit.alliance || '').toLowerCase();
            if (alliance === 'hostile' && !unit.visible) continue;
        }
        const sp = worldToScreen(pos.x, pos.y);
        const dx = sp.x - sx;
        const dy = sp.y - sy;
        const dist = Math.sqrt(dx * dx + dy * dy);
        if (dist < hitRadius && dist < closestDist) {
            closestDist = dist;
            closest = id;
        }
    }
    return closest;
}

/**
 * Hit-test a building polygon. Uses ray-casting point-in-polygon.
 * Works in world coordinates (overlay buildings use world coords).
 * @param {number} wx - world X
 * @param {number} wy - world Y
 * @returns {object|null} - building object with polygon + tags, or null
 */
function _hitTestBuilding(wx, wy) {
    const buildings = _state.overlayBuildings;
    if (!buildings || !buildings.length) return null;

    for (const b of buildings) {
        const poly = b.polygon;
        if (!poly || poly.length < 3) continue;
        // Ray-casting algorithm
        let inside = false;
        for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
            const xi = poly[i][0], yi = poly[i][1];
            const xj = poly[j][0], yj = poly[j][1];
            if (((yi > wy) !== (yj > wy)) &&
                (wx < (xj - xi) * (wy - yi) / (yj - yi) + xi)) {
                inside = !inside;
            }
        }
        if (inside) return b;
    }
    return null;
}

/**
 * Show a context menu at the given screen position.
 * @param {number} sx - screen X
 * @param {number} sy - screen Y
 * @param {object} worldPos - {x, y} world coordinates
 */
function _showContextMenu(sx, sy, worldPos) {
    _hideContextMenu();
    const selectedId = TritiumStore.get('map.selectedUnitId');
    const building = _hitTestBuilding(worldPos.x, worldPos.y);

    const menu = document.createElement('div');
    menu.className = 'map-context-menu';
    menu.style.position = 'fixed';
    menu.style.left = sx + 'px';
    menu.style.top = sy + 'px';
    menu.style.zIndex = '9999';

    const items = [];
    if (selectedId) {
        items.push({ label: 'DISPATCH HERE', action: 'dispatch', icon: '>' });
        items.push({ label: 'SET WAYPOINT', action: 'waypoint', icon: '+' });
    }
    items.push({ label: 'DROP MARKER', action: 'marker', icon: 'x' });
    items.push({ label: 'MEASURE DISTANCE', action: 'measure', icon: '~' });
    if (building) {
        const addr = building.tags && building.tags['addr:street']
            ? building.tags['addr:street']
            : 'Building';
        items.push({ label: 'INFO: ' + addr, action: 'building_info', icon: '?' });
    }

    for (const item of items) {
        const el = document.createElement('div');
        el.className = 'map-ctx-item';
        el.textContent = item.icon + ' ' + item.label;
        el.dataset.action = item.action;
        menu.appendChild(el);
    }

    _state.contextMenu = menu;
    _state.contextMenuWorld = worldPos;

    // Attach click handler
    menu.addEventListener('click', (e) => {
        const target = e.target.closest('.map-ctx-item');
        if (!target) return;
        const action = target.dataset.action;
        _handleContextAction(action, worldPos, selectedId, building);
        _hideContextMenu();
    });

    // Attach to canvas parent or document body
    const parent = _state.canvas.parentNode || document.body;
    if (parent && parent.appendChild) parent.appendChild(menu);
}

function _hideContextMenu() {
    if (_state.contextMenu) {
        _state.contextMenu.remove();
        _state.contextMenu = null;
    }
}

function _handleContextAction(action, worldPos, selectedId, building) {
    switch (action) {
        case 'dispatch':
            if (selectedId) _doDispatch(selectedId, worldPos.x, worldPos.y);
            break;
        case 'waypoint':
            EventBus.emit('map:waypoint', { x: worldPos.x, y: worldPos.y, unitId: selectedId });
            break;
        case 'marker':
            EventBus.emit('map:marker', { x: worldPos.x, y: worldPos.y });
            break;
        case 'measure':
            EventBus.emit('map:measure_start', { x: worldPos.x, y: worldPos.y });
            break;
        case 'building_info':
            if (building) {
                EventBus.emit('building:info', {
                    tags: building.tags || {},
                    polygon: building.polygon,
                });
            }
            break;
    }
}

// ============================================================
// Dispatch
// ============================================================

function _doDispatch(unitId, wx, wy) {
    const unit = TritiumStore.units.get(unitId);

    // Send dispatch command to backend FIRST, then show feedback on success
    fetch('/api/amy/simulation/dispatch', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ unit_id: unitId, target: { x: wx, y: wy } }),
    }).then(resp => {
        if (resp.ok) {
            // Show visual dispatch arrow only on confirmed success
            if (unit && unit.position) {
                _state.dispatchArrows.push({
                    fromX: unit.position.x,
                    fromY: unit.position.y,
                    toX: wx,
                    toY: wy,
                    time: Date.now(),
                });
            }
            EventBus.emit('unit:dispatched', { id: unitId, target: { x: wx, y: wy } });
            EventBus.emit('toast:show', { message: 'Dispatch command sent', type: 'info' });
        } else {
            resp.json().then(data => {
                const reason = (data && data.detail) || 'Dispatch failed';
                EventBus.emit('toast:show', { message: reason, type: 'alert' });
            }).catch(() => {
                EventBus.emit('toast:show', { message: 'Dispatch failed', type: 'alert' });
            });
        }
    }).catch(() => {
        EventBus.emit('toast:show', { message: 'Dispatch failed: network error', type: 'alert' });
    });
}

// ============================================================
// EventBus / Store handlers
// ============================================================

/**
 * Auto-fit the camera to encompass all unit positions.
 * Called once on the first units:updated event that has data.
 */
function _autoFitCamera() {
    const units = TritiumStore.units;
    const cam = _state.cam;
    const cssW = _state.canvas.width / _state.dpr;
    const cssH = _state.canvas.height / _state.dpr;

    // Use operational bounds (considers units + minimum 200m extent)
    const ob = _getOperationalBounds();

    if (units.size === 0) {
        // No units: zoom to show simulation bounds centered at origin
        const fitW = ob.maxX - ob.minX;
        const fitH = ob.maxY - ob.minY;
        const zoomX = cssW / fitW;
        const zoomY = cssH / fitH;
        cam.targetZoom = Math.max(ZOOM_MIN, Math.min(ZOOM_MAX, Math.min(zoomX, zoomY)));
        cam.targetX = 0;
        cam.targetY = 0;
        _state.hasAutoFit = true;
        return;
    }

    // Compute bounding box of all unit positions
    let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
    for (const [, unit] of units) {
        const pos = unit.position;
        if (!pos || pos.x === undefined || pos.y === undefined) continue;
        if (pos.x < minX) minX = pos.x;
        if (pos.x > maxX) maxX = pos.x;
        if (pos.y < minY) minY = pos.y;
        if (pos.y > maxY) maxY = pos.y;
    }

    if (!isFinite(minX)) {
        // All units lack position data — use operational bounds
        const fitW = ob.maxX - ob.minX;
        const fitH = ob.maxY - ob.minY;
        const zoomX = cssW / fitW;
        const zoomY = cssH / fitH;
        cam.targetZoom = Math.max(ZOOM_MIN, Math.min(ZOOM_MAX, Math.min(zoomX, zoomY)));
        cam.targetX = 0;
        cam.targetY = 0;
        _state.hasAutoFit = true;
        return;
    }

    // Add 20% padding
    const spanX = (maxX - minX) || 10; // avoid zero span
    const spanY = (maxY - minY) || 10;
    const padX = spanX * 0.2;
    const padY = spanY * 0.2;

    // Ensure the fit area is at least as large as operational bounds
    const fitMinX = Math.min(minX - padX, ob.minX);
    const fitMaxX = Math.max(maxX + padX, ob.maxX);
    const fitMinY = Math.min(minY - padY, ob.minY);
    const fitMaxY = Math.max(maxY + padY, ob.maxY);
    const fitW = fitMaxX - fitMinX;
    const fitH = fitMaxY - fitMinY;

    // Compute zoom to fit both axes
    const zoomX = cssW / fitW;
    const zoomY = cssH / fitH;
    const fitZoom = Math.max(ZOOM_MIN, Math.min(ZOOM_MAX, Math.min(zoomX, zoomY)));

    cam.targetX = (fitMinX + fitMaxX) / 2;
    cam.targetY = (fitMinY + fitMaxY) / 2;
    cam.targetZoom = fitZoom;
    _state.hasAutoFit = true;
    console.log(`[MAP] Auto-fit camera: center=(${cam.targetX.toFixed(1)}, ${cam.targetY.toFixed(1)}), zoom=${fitZoom.toFixed(2)}`);
}

function _onUnitsUpdated(_targets) {
    // Auto-fit camera on first unit data
    if (!_state.hasAutoFit && TritiumStore.units.size > 0) {
        _autoFitCamera();
    }

    // Clean up smoothHeadings for units that no longer exist
    for (const id of _state.smoothHeadings.keys()) {
        if (!TritiumStore.units.has(id)) {
            _state.smoothHeadings.delete(id);
        }
    }
}

function _onMapMode(data) {
    // Mode changes are handled by main.js (buttons, etc.)
    // We could adjust render behavior based on mode here.
}

function _onDispatchMode(data) {
    if (data && data.id) {
        _state.dispatchMode = true;
        _state.dispatchUnitId = data.id;
        _state.canvas.style.cursor = 'crosshair';
    }
}

function _onDispatched(data) {
    // External dispatch events (from sidebar button, etc.)
    // Arrow already added if we originated the dispatch
}

function _onMeshCenterOnNode(data) {
    // Center camera on a mesh radio node
    if (!data || data.x === undefined || data.y === undefined) return;
    _state.cam.targetX = data.x;
    _state.cam.targetY = data.y;
    _state.cam.targetZoom = Math.max(5.0, _state.cam.zoom);
    console.log(`[MAP] Center on mesh node: (${data.x.toFixed(1)}, ${data.y.toFixed(1)})`);
}

function _onDeviceOpenModal(data) {
    if (!data || !data.id) return;
    const unit = TritiumStore.units.get(data.id);
    if (unit) {
        DeviceModalManager.open(data.id, _resolveModalType(unit), unit);
    }
}

// -- Geofence polygon drawing -----------------------------------------

function _onGeofenceDrawStart() {
    _state.geofenceDrawing = true;
    _state.geofenceVertices = [];
    _state.canvas.style.cursor = 'crosshair';
    console.log('[MAP] Geofence draw mode started — click to add vertices, Enter to finish, Escape to cancel');
}

function _geofenceAddVertex(worldPos) {
    _state.geofenceVertices.push([worldPos.x, worldPos.y]);
}

function _geofenceFinish() {
    const verts = _state.geofenceVertices;
    _state.geofenceDrawing = false;
    _state.geofenceVertices = [];
    _state.canvas.style.cursor = 'crosshair';
    if (verts.length >= 3) {
        EventBus.emit('geofence:zoneDrawn', { polygon: verts });
    } else {
        EventBus.emit('toast:show', { message: 'Need at least 3 vertices for a zone', type: 'alert' });
    }
}

function _geofenceCancel() {
    _state.geofenceDrawing = false;
    _state.geofenceVertices = [];
    _state.canvas.style.cursor = 'crosshair';
    EventBus.emit('toast:show', { message: 'Geofence drawing cancelled', type: 'info' });
}

// -- Patrol waypoint drawing ------------------------------------------

function _onPatrolDrawStart(data) {
    const unitId = data?.unitId;
    if (!unitId) return;
    _state.patrolDrawing = true;
    _state.patrolUnitId = unitId;
    _state.patrolWaypoints = [];
    _state.canvas.style.cursor = 'crosshair';
    EventBus.emit('toast:show', { message: `Click map to add patrol waypoints for ${unitId}, Enter to finish`, type: 'info' });
}

function _patrolAddWaypoint(worldPos) {
    _state.patrolWaypoints.push({ x: worldPos.x, y: worldPos.y });
}

function _patrolFinish() {
    const wps = _state.patrolWaypoints;
    const unitId = _state.patrolUnitId;
    _state.patrolDrawing = false;
    _state.patrolUnitId = null;
    _state.patrolWaypoints = [];
    _state.canvas.style.cursor = 'crosshair';
    if (wps.length >= 2 && unitId) {
        fetch('/api/amy/command', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ action: 'patrol', params: [unitId, ...wps.flatMap(w => [w.x, w.y])] }),
        }).then(() => {
            EventBus.emit('toast:show', { message: `Patrol route set: ${wps.length} waypoints`, type: 'info' });
        }).catch(() => {
            EventBus.emit('toast:show', { message: 'Failed to set patrol route', type: 'alert' });
        });
    } else {
        EventBus.emit('toast:show', { message: 'Need at least 2 waypoints for a patrol route', type: 'alert' });
    }
}

function _patrolCancel() {
    _state.patrolDrawing = false;
    _state.patrolUnitId = null;
    _state.patrolWaypoints = [];
    _state.canvas.style.cursor = 'crosshair';
    EventBus.emit('toast:show', { message: 'Patrol drawing cancelled', type: 'info' });
}

// -- Drawing finish/cancel handlers -----------------------------------

function _onDrawFinish() {
    if (_state.geofenceDrawing) _geofenceFinish();
    else if (_state.patrolDrawing) _patrolFinish();
}

function _onDrawCancel() {
    if (_state.geofenceDrawing) _geofenceCancel();
    else if (_state.patrolDrawing) _patrolCancel();
}

// -- RF motion data handler -------------------------------------------

function _onRfMotionUpdate(data) {
    if (!data) return;
    _state.rfMotionPairs = data.pairs || [];
    _state.rfMotionZones = data.zones || [];
    _state.rfMotionDetected = data.motionDetected || false;
}

function _onMinimapPan(data) {
    if (!data || data.x === undefined || data.y === undefined) return;
    _state.cam.targetX = data.x;
    _state.cam.targetY = data.y;
}

/**
 * Handle map:flyToMission event — move camera to mission area.
 * Accepts x/y game coordinates. Calculates zoom from radius.
 */
function _onPanToMission(data) {
    if (!data) return;
    if (data.x !== undefined && data.y !== undefined) {
        _state.cam.targetX = data.x;
        _state.cam.targetY = data.y;
    }
    if (data.radius_m) {
        // At zoom 1.0, viewport shows ~500m. Scale proportionally.
        const z = 250 / Math.max(data.radius_m, 20);
        _state.cam.targetZoom = Math.max(ZOOM_MIN, Math.min(ZOOM_MAX, z));
    }
    console.log(`[MAP] Pan to mission: (${_state.cam.targetX.toFixed(1)}, ${_state.cam.targetY.toFixed(1)}), zoom=${_state.cam.targetZoom.toFixed(2)}`);
}

function _onSelectedUnitChanged(newId, _oldId) {
    // When a unit is clicked, show its latest thought (click-to-view).
    // Surfaces stored thoughts even if they were below broadcast threshold.
    if (newId) {
        const unit = TritiumStore.units.get(newId);
        if (unit && unit.latestThought && !unit.thoughtText) {
            const lt = unit.latestThought;
            unit.thoughtText = lt.text;
            unit.thoughtEmotion = lt.emotion || 'neutral';
            unit.thoughtImportance = lt.importance || 'normal';
            unit.thoughtDuration = lt.duration || 5;
            unit.thoughtExpires = Date.now() + (lt.duration || 5) * 1000;
        }
    }
}

// ============================================================
// Geo / Satellite tiles
// ============================================================

function _loadGeoReference() {
    fetch('/api/geo/reference')
        .then(r => {
            if (!r.ok) return null;
            return r.json();
        })
        .then(data => {
            if (!data) return;
            if (!data.initialized) {
                _state.noLocationSet = true;
                console.warn('[MAP] Geo reference not initialized — showing fallback');
                return;
            }
            _state.noLocationSet = false;
            _state.geoCenter = { lat: data.lat, lng: data.lng };
            _loadSatelliteTiles(data.lat, data.lng);
            _loadOverlayData();
        })
        .catch(err => {
            console.warn('[MAP] Geo reference fetch failed:', err);
            _state.noLocationSet = true;
        });
}

/**
 * Fetch overlay data (building outlines + road polylines) from the server.
 * Called once after geo reference is loaded.
 */
function _loadOverlayData() {
    fetch('/api/geo/overlay')
        .then(r => {
            if (!r.ok) return null;
            return r.json();
        })
        .then(data => {
            if (!data) return;
            _state.overlayBuildings = data.buildings || [];
            _state.overlayRoads = data.roads || [];
            console.log(`[MAP] Overlay loaded: ${_state.overlayBuildings.length} buildings, ${_state.overlayRoads.length} road segments`);
        })
        .catch(err => {
            console.warn('[MAP] Overlay fetch failed:', err);
        });
}

/**
 * Get the appropriate tile level index for the current camera zoom.
 */
function _getSatTileLevelIndex() {
    const zoom = _state.cam.zoom;
    for (let i = 0; i < SAT_TILE_LEVELS.length; i++) {
        if (zoom < SAT_TILE_LEVELS[i][0]) return i;
    }
    return SAT_TILE_LEVELS.length - 1;
}

/**
 * Check if the camera zoom has crossed a tile level threshold.
 * If so, debounce-reload tiles at the new resolution.
 */
function _checkSatelliteTileReload() {
    if (!_state.geoCenter || !_state.showSatellite) return;

    const newLevel = _getSatTileLevelIndex();
    if (newLevel === _state.satTileLevel) return;

    // Update level immediately to stop retriggering on every frame
    // (smooth zoom lerp would otherwise reset the debounce timer forever)
    _state.satTileLevel = newLevel;

    // Debounce the actual tile fetch (zoom may still be lerping)
    clearTimeout(_state.satReloadTimer);
    _state.satReloadTimer = setTimeout(() => {
        const idx = _getSatTileLevelIndex();
        _state.satTileLevel = idx;
        const [, tileZoom, radius] = SAT_TILE_LEVELS[idx];
        console.log(`[MAP] Reloading satellite tiles: zoom=${tileZoom}, radius=${radius}m`);
        _fetchTilesFromApi(_state.geoCenter.lat, _state.geoCenter.lng, radius, tileZoom);
    }, 500);
}

function _loadSatelliteTiles(lat, lng) {
    // Determine initial tile parameters from current zoom
    const levelIdx = _getSatTileLevelIndex();
    _state.satTileLevel = levelIdx;
    const [, tileZoom, radius] = SAT_TILE_LEVELS[levelIdx];

    // Use the geo.js tile loader if available on window
    if (typeof window.geo !== 'undefined' && window.geo.loadSatelliteTiles) {
        window.geo.loadSatelliteTiles(lat, lng, radius, tileZoom)
            .then(tiles => {
                if (tiles.length === 0) return;
                _state.satTiles = tiles;
                _state.geoLoaded = true;
                console.log(`[MAP] Loaded ${tiles.length} satellite tiles (zoom ${tileZoom})`);
            })
            .catch(err => {
                console.warn('[MAP] Satellite tiles failed:', err);
            });
        return;
    }

    // Fallback: fetch tile metadata from API and load images directly
    _fetchTilesFromApi(lat, lng, radius, tileZoom);
}

function _fetchTilesFromApi(lat, lng, radiusMeters, zoom) {
    // Calculate tile coordinates covering the area
    // Each tile at zoom 19 is ~0.3m/px * 256px = ~76m
    const n = Math.pow(2, zoom);
    const latRad = lat * Math.PI / 180;
    const centerTileX = Math.floor(n * (lng + 180) / 360);
    const centerTileY = Math.floor(n * (1 - Math.log(Math.tan(latRad) + 1 / Math.cos(latRad)) / Math.PI) / 2);

    // How many tiles to cover the radius
    const metersPerTile = 156543.03392 * Math.cos(latRad) / n * 256;
    const tilesNeeded = Math.ceil(radiusMeters / metersPerTile) + 1;

    const promises = [];
    for (let dx = -tilesNeeded; dx <= tilesNeeded; dx++) {
        for (let dy = -tilesNeeded; dy <= tilesNeeded; dy++) {
            const tx = centerTileX + dx;
            const ty = centerTileY + dy;
            promises.push(_loadTileImage(zoom, tx, ty, lat, lng, n, latRad, metersPerTile));
        }
    }

    Promise.allSettled(promises).then(results => {
        const tiles = results
            .filter(r => r.status === 'fulfilled' && r.value)
            .map(r => r.value);
        if (tiles.length > 0) {
            _state.satTiles = tiles;
            _state.geoLoaded = true;
            console.log(`[MAP] Loaded ${tiles.length} satellite tiles from API`);
        }
    });
}

function _loadTileImage(zoom, tx, ty, centerLat, centerLng, n, latRad, metersPerTile) {
    return new Promise((resolve, reject) => {
        const img = new Image();
        img.crossOrigin = 'anonymous';
        img.onload = () => {
            // Calculate game-coord bounds for this tile
            const tileLng = tx / n * 360 - 180;
            const tileLngEnd = (tx + 1) / n * 360 - 180;
            const tileLatRad = Math.atan(Math.sinh(Math.PI * (1 - 2 * ty / n)));
            const tileLatEndRad = Math.atan(Math.sinh(Math.PI * (1 - 2 * (ty + 1) / n)));
            const tileLat = tileLatRad * 180 / Math.PI;
            const tileLatEnd = tileLatEndRad * 180 / Math.PI;

            // Convert lat/lng to game coords (meters from center)
            const R = 6378137; // Earth radius meters
            const minX = (tileLng - centerLng) * Math.PI / 180 * R * Math.cos(latRad);
            const maxX = (tileLngEnd - centerLng) * Math.PI / 180 * R * Math.cos(latRad);
            const minY = (tileLatEnd - centerLat) * Math.PI / 180 * R; // South
            const maxY = (tileLat - centerLat) * Math.PI / 180 * R;   // North

            resolve({ image: img, bounds: { minX, maxX, minY, maxY } });
        };
        img.onerror = () => reject(new Error(`Tile ${zoom}/${tx}/${ty} failed`));
        img.src = `/api/geo/tile/${zoom}/${tx}/${ty}`;
    });
}

// ============================================================
// Road tile overlay
// ============================================================

function _drawRoadTiles(ctx) {
    const tiles = _state.roadTiles;
    if (!tiles || tiles.length === 0) return;

    const cssW = _state.canvas.width / _state.dpr;
    const cssH = _state.canvas.height / _state.dpr;

    ctx.save();
    ctx.globalAlpha = 0.85;

    for (const tile of tiles) {
        const b = tile.bounds;
        const tl = worldToScreen(b.minX, b.maxY);
        const br = worldToScreen(b.maxX, b.minY);
        const sw = br.x - tl.x;
        const sh = br.y - tl.y;

        if (sw < 1 || sh < 1) continue;
        if (br.x < 0 || tl.x > cssW) continue;
        if (br.y < 0 || tl.y > cssH) continue;

        ctx.drawImage(tile.image, tl.x, tl.y, sw, sh);
    }

    ctx.restore();
}

function _checkRoadTileReload() {
    if (!_state.geoCenter || !_state.showRoads) return;

    const newLevel = _getSatTileLevelIndex();
    if (newLevel === _state.roadTileLevel) return;

    clearTimeout(_state.roadReloadTimer);
    _state.roadReloadTimer = setTimeout(() => {
        const idx = _getSatTileLevelIndex();
        if (idx !== _state.roadTileLevel) {
            _state.roadTileLevel = idx;
            const [, tileZoom, radius] = SAT_TILE_LEVELS[idx];
            console.log(`[MAP] Reloading road tiles: zoom=${tileZoom}, radius=${radius}m`);
            _fetchRoadTiles(_state.geoCenter.lat, _state.geoCenter.lng, radius, tileZoom);
        }
    }, 300);
}

function _loadRoadTiles(lat, lng) {
    const levelIdx = _getSatTileLevelIndex();
    _state.roadTileLevel = levelIdx;
    const [, tileZoom, radius] = SAT_TILE_LEVELS[levelIdx];
    _fetchRoadTiles(lat, lng, radius, tileZoom);
}

function _fetchRoadTiles(lat, lng, radiusMeters, zoom) {
    const n = Math.pow(2, zoom);
    const latRad = lat * Math.PI / 180;
    const centerTileX = Math.floor(n * (lng + 180) / 360);
    const centerTileY = Math.floor(n * (1 - Math.log(Math.tan(latRad) + 1 / Math.cos(latRad)) / Math.PI) / 2);

    const metersPerTile = 156543.03392 * Math.cos(latRad) / n * 256;
    const tilesNeeded = Math.ceil(radiusMeters / metersPerTile) + 1;

    const promises = [];
    for (let dx = -tilesNeeded; dx <= tilesNeeded; dx++) {
        for (let dy = -tilesNeeded; dy <= tilesNeeded; dy++) {
            const tx = centerTileX + dx;
            const ty = centerTileY + dy;
            promises.push(_loadRoadTileImage(zoom, tx, ty, lat, lng, n, latRad));
        }
    }

    Promise.allSettled(promises).then(results => {
        const tiles = results
            .filter(r => r.status === 'fulfilled' && r.value)
            .map(r => r.value);
        if (tiles.length > 0) {
            _state.roadTiles = tiles;
            console.log(`[MAP] Loaded ${tiles.length} road tiles`);
        }
    });
}

function _loadRoadTileImage(zoom, tx, ty, centerLat, centerLng, n, latRad) {
    return new Promise((resolve, reject) => {
        const img = new Image();
        img.crossOrigin = 'anonymous';
        img.onload = () => {
            const tileLng = tx / n * 360 - 180;
            const tileLngEnd = (tx + 1) / n * 360 - 180;
            const tileLatRad = Math.atan(Math.sinh(Math.PI * (1 - 2 * ty / n)));
            const tileLatEndRad = Math.atan(Math.sinh(Math.PI * (1 - 2 * (ty + 1) / n)));
            const tileLat = tileLatRad * 180 / Math.PI;
            const tileLatEnd = tileLatEndRad * 180 / Math.PI;

            const R = 6378137;
            const minX = (tileLng - centerLng) * Math.PI / 180 * R * Math.cos(latRad);
            const maxX = (tileLngEnd - centerLng) * Math.PI / 180 * R * Math.cos(latRad);
            const minY = (tileLatEnd - centerLat) * Math.PI / 180 * R;
            const maxY = (tileLat - centerLat) * Math.PI / 180 * R;

            resolve({ image: img, bounds: { minX, maxX, minY, maxY } });
        };
        img.onerror = () => reject(new Error(`Road tile ${zoom}/${tx}/${ty} failed`));
        img.src = `/api/geo/road-tile/${zoom}/${tx}/${ty}`;
    });
}

// ============================================================
// Zones / Exports
// ============================================================

/**
 * Toggle satellite imagery overlay on/off.
 * Callable externally via keyboard shortcut.
 */
export function toggleSatellite() {
    _state.showSatellite = !_state.showSatellite;
    console.log(`[MAP] Satellite imagery ${_state.showSatellite ? 'ON' : 'OFF'}`);
    if (_state.showSatellite && _state.geoCenter && _state.satTiles.length === 0) {
        _loadSatelliteTiles(_state.geoCenter.lat, _state.geoCenter.lng);
    }
}

/**
 * Toggle road overlay on/off.
 */
export function toggleRoads() {
    _state.showRoads = !_state.showRoads;
    console.log(`[MAP] Road overlay ${_state.showRoads ? 'ON' : 'OFF'}`);
    if (_state.showRoads && _state.geoCenter && _state.roadTiles.length === 0) {
        _loadRoadTiles(_state.geoCenter.lat, _state.geoCenter.lng);
    }
}

/**
 * Toggle grid overlay on/off.
 */
export function toggleGrid() {
    _state.showGrid = !_state.showGrid;
    console.log(`[MAP] Grid ${_state.showGrid ? 'ON' : 'OFF'}`);
}

/**
 * Toggle building outlines on/off.
 */
export function toggleBuildings() {
    _state.showBuildings = !_state.showBuildings;
    console.log(`[MAP] Buildings ${_state.showBuildings ? 'ON' : 'OFF'}`);
}

/**
 * Return current map state for menu checkmarks.
 */
/**
 * Toggle fog of war on/off.
 */
export function toggleFog() {
    _state.fogEnabled = !_state.fogEnabled;
    console.log(`[MAP] Fog of war ${_state.fogEnabled ? 'ON' : 'OFF'}`);
}

/**
 * Toggle mesh radio overlay on/off.
 */
export function toggleMesh() {
    _state.showMesh = !_state.showMesh;
    if (typeof meshState !== 'undefined') meshState.visible = _state.showMesh;
    console.log(`[MAP] Mesh network ${_state.showMesh ? 'ON' : 'OFF'}`);
}

export function toggleMeshNodes() {
    _state.showMeshNodes = !_state.showMeshNodes;
    if (typeof meshState !== 'undefined') meshState.showNodes = _state.showMeshNodes;
    console.log(`[MAP] Mesh nodes ${_state.showMeshNodes ? 'ON' : 'OFF'}`);
}

export function toggleMeshLinks() {
    _state.showMeshLinks = !_state.showMeshLinks;
    if (typeof meshState !== 'undefined') meshState.showLinks = _state.showMeshLinks;
    console.log(`[MAP] Mesh links ${_state.showMeshLinks ? 'ON' : 'OFF'}`);
}

export function toggleMeshCoverage() {
    _state.showMeshCoverage = !_state.showMeshCoverage;
    if (typeof meshState !== 'undefined') meshState.showCoverage = _state.showMeshCoverage;
    console.log(`[MAP] Mesh coverage ${_state.showMeshCoverage ? 'ON' : 'OFF'}`);
}

/**
 * Toggle NPC thought bubbles on/off.
 */
export function toggleThoughts() {
    _state.showThoughts = !_state.showThoughts;
    console.log(`[MAP] Thought bubbles ${_state.showThoughts ? 'ON' : 'OFF'}`);
}

/**
 * Toggle prediction confidence cones on/off.
 */
export function togglePredictionCones() {
    _state.showPredictionCones = !_state.showPredictionCones;
    console.log(`[MAP] Prediction cones ${_state.showPredictionCones ? 'ON' : 'OFF'}`);
}

export function getMapState() {
    return {
        showSatellite: _state.showSatellite,
        showRoads: _state.showRoads,
        showBuildings: _state.showBuildings,
        showGrid: _state.showGrid,
        showFog: _state.fogEnabled,
        fogEnabled: _state.fogEnabled,
        showMesh: _state.showMesh,
        showMeshNodes: _state.showMeshNodes,
        showMeshLinks: _state.showMeshLinks,
        showMeshCoverage: _state.showMeshCoverage,
        showThoughts: _state.showThoughts,
        showPredictionCones: _state.showPredictionCones,
    };
}

/**
 * Center camera on the centroid of all hostile units.
 * If no hostiles, center on (0,0).
 */
export function centerOnAction() {
    const units = TritiumStore.units;
    let sumX = 0, sumY = 0, count = 0;
    units.forEach(u => {
        if (u.alliance === 'hostile') {
            sumX += (u.x || u.position?.x || 0);
            sumY += (u.y || u.position?.y || 0);
            count++;
        }
    });
    if (count > 0) {
        _state.cam.targetX = sumX / count;
        _state.cam.targetY = sumY / count;
        _state.cam.targetZoom = Math.max(2.0, _state.cam.zoom);
    } else {
        _state.cam.targetX = 0;
        _state.cam.targetY = 0;
    }
    console.log(`[MAP] Center on action: (${_state.cam.targetX.toFixed(1)}, ${_state.cam.targetY.toFixed(1)})`);
}

/**
 * Reset camera to origin with default zoom.
 */
export function resetCamera() {
    _state.cam.targetX = 0;
    _state.cam.targetY = 0;
    _state.cam.targetZoom = 15.0;
    console.log('[MAP] Camera reset');
}

/**
 * Zoom in by factor 1.5, clamped to ZOOM_MAX.
 */
export function zoomIn() {
    _state.cam.targetZoom = Math.min(_state.cam.targetZoom * 1.5, ZOOM_MAX);
}

/**
 * Zoom out by factor 1.5, clamped to ZOOM_MIN.
 */
export function zoomOut() {
    _state.cam.targetZoom = Math.max(_state.cam.targetZoom / 1.5, ZOOM_MIN);
}

// ============================================================
// Zones
// ============================================================

function _fetchZones() {
    fetch('/api/zones')
        .then(r => {
            if (!r.ok) return [];
            return r.json();
        })
        .then(data => {
            if (Array.isArray(data)) {
                _state.zones = data;
            } else if (data && Array.isArray(data.zones)) {
                _state.zones = data.zones;
            }
        })
        .catch(() => {
            // Zones not available -- non-fatal
        });
}

// ============================================================
// Multi-select action bar
// ============================================================

function _showMultiSelectBar() {
    let bar = document.getElementById('multi-select-bar');
    if (!bar) {
        bar = document.createElement('div');
        bar.id = 'multi-select-bar';
        bar.style.cssText = `
            position: fixed;
            bottom: 60px;
            left: 50%;
            transform: translateX(-50%);
            background: rgba(10, 10, 15, 0.95);
            border: 1px solid #fcee0a;
            border-radius: 8px;
            padding: 8px 16px;
            display: flex;
            align-items: center;
            gap: 12px;
            z-index: 500;
            font-family: "JetBrains Mono", monospace;
            font-size: 0.75rem;
            box-shadow: 0 0 20px rgba(252, 238, 10, 0.3);
        `;
        document.body.appendChild(bar);
    }

    const count = _state.selectedUnitIds.size;
    bar.innerHTML = `
        <span style="color: #fcee0a; font-weight: bold;">${count} SELECTED</span>
        <button onclick="window._multiSelectAction('dossier')" style="background: #00f0ff; color: #0a0a0f; border: none; padding: 4px 10px; border-radius: 4px; cursor: pointer; font-family: inherit; font-size: 0.7rem; font-weight: bold;">GROUP DOSSIER</button>
        <button onclick="window._multiSelectAction('export')" style="background: #05ffa1; color: #0a0a0f; border: none; padding: 4px 10px; border-radius: 4px; cursor: pointer; font-family: inherit; font-size: 0.7rem; font-weight: bold;">EXPORT</button>
        <button onclick="window._multiSelectAction('compare')" style="background: #ff8800; color: #0a0a0f; border: none; padding: 4px 10px; border-radius: 4px; cursor: pointer; font-family: inherit; font-size: 0.7rem; font-weight: bold;">COMPARE</button>
        <button onclick="window._multiSelectAction('alliance')" style="background: #ff2a6d; color: #fff; border: none; padding: 4px 10px; border-radius: 4px; cursor: pointer; font-family: inherit; font-size: 0.7rem; font-weight: bold;">SET ALLIANCE</button>
        <button onclick="window._multiSelectAction('clear')" style="background: transparent; color: #888; border: 1px solid #444; padding: 4px 10px; border-radius: 4px; cursor: pointer; font-family: inherit; font-size: 0.7rem;">CLEAR</button>
    `;
    bar.style.display = 'flex';
}

function _hideMultiSelectBar() {
    const bar = document.getElementById('multi-select-bar');
    if (bar) bar.style.display = 'none';
}

// Global handler for multi-select actions
window._multiSelectAction = function(action) {
    const ids = Array.from(_state.selectedUnitIds);
    if (ids.length === 0) return;

    switch (action) {
        case 'dossier':
            EventBus.emit('multiselect:group-dossier', { ids });
            EventBus.emit('panel:request-open', { id: 'dossiers' });
            break;
        case 'export':
            // Download selected targets as JSON
            fetch('/api/targets')
                .then(r => r.json())
                .then(data => {
                    const targets = (data.targets || []).filter(t => ids.includes(t.target_id));
                    const blob = new Blob([JSON.stringify(targets, null, 2)], { type: 'application/json' });
                    const url = URL.createObjectURL(blob);
                    const a = document.createElement('a');
                    a.href = url;
                    a.download = `selected_targets_${ids.length}.json`;
                    a.click();
                    URL.revokeObjectURL(url);
                });
            break;
        case 'compare':
            EventBus.emit('multiselect:compare', { ids });
            EventBus.emit('panel:request-open', { id: 'target-compare' });
            break;
        case 'alliance': {
            const alliance = prompt('Set alliance for selected targets:\nfriendly / hostile / neutral / unknown');
            if (alliance && ['friendly', 'hostile', 'neutral', 'unknown'].includes(alliance.toLowerCase())) {
                EventBus.emit('multiselect:set-alliance', { ids, alliance: alliance.toLowerCase() });
            }
            break;
        }
        case 'clear':
            _state.selectedUnitIds.clear();
            TritiumStore.set('map.selectedUnitId', null);
            EventBus.emit('unit:deselected', {});
            EventBus.emit('multiselect:changed', { ids: [], count: 0 });
            _hideMultiSelectBar();
            break;
    }
};
