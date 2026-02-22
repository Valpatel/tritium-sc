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
    [0.1,  13, 3000],
    [0.5,  15, 1000],
    [2.0,  17,  400],
    [Infinity, 19, 200],
];

const ALLIANCE_COLORS = {
    friendly: '#05ffa1',
    hostile:  '#ff2a6d',
    neutral:  '#00a0ff',
    unknown:  '#fcee0a',
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
    showSatellite: true, // toggled with I key
    geoCenter: null,     // { lat, lng } — cached for dynamic reload
    satTileLevel: -1,    // current SAT_TILE_LEVELS index (for threshold detection)
    satReloadTimer: null, // debounce timer for tile reload

    // Road tile overlay
    roadTiles: [],      // { image, bounds: { minX, maxX, minY, maxY } }
    showRoads: false,   // toggled with G key (default off)
    roadTileLevel: -1,
    roadReloadTimer: null,
    showGrid: true,     // toggled from menu

    // Zones (from escalation)
    zones: [],

    // Operational bounds cache (for minimap dynamic scaling)
    opBounds: null,       // { minX, maxX, minY, maxY }
    opBoundsUnitCount: 0, // unit count when last computed

    // Smooth heading cache
    smoothHeadings: new Map(),

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
    );

    // Subscribe to store for selectedUnitId changes (highlight sync)
    _state.unsubs.push(
        TritiumStore.on('map.selectedUnitId', _onSelectedUnitChanged),
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

    // CSS pixel dimensions (drawing space after DPI transform)
    const cssW = canvas.width / dpr;
    const cssH = canvas.height / dpr;

    // Clear (in CSS pixel space since transform is applied)
    ctx.fillStyle = BG_COLOR;
    ctx.fillRect(0, 0, cssW, cssH);

    // Layer 1: Satellite tiles (under everything, 70% opacity)
    if (_state.showSatellite) {
        _drawSatelliteTiles(ctx);
    }

    // Layer 1.5: Road overlay (transparent tiles on top of satellite)
    if (_state.showRoads) {
        _drawRoadTiles(ctx);
    }

    // Layer 2: Grid (adaptive spacing based on zoom)
    if (_state.showGrid) _drawGrid(ctx);

    // Layer 3: Map boundary
    _drawMapBoundary(ctx);

    // Layer 4: Zones
    _drawZones(ctx);

    // Layer 5: Targets (shapes only — labels handled separately)
    _drawTargets(ctx);

    // Layer 5.1: Unit labels (collision-resolved)
    _drawLabels(ctx);

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

    // Layer 8: Selection indicator
    _drawSelectionIndicator(ctx);

    // Layer 9: Dispatch arrows
    _drawDispatchArrows(ctx);

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

// ============================================================
// Layer 1: Satellite tiles
// ============================================================

function _drawSatelliteTiles(ctx) {
    const tiles = _state.satTiles;
    if (!tiles || tiles.length === 0) return;

    const cssW = _state.canvas.width / _state.dpr;
    const cssH = _state.canvas.height / _state.dpr;

    ctx.save();
    ctx.globalAlpha = 0.7;

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
// Layer 5: Targets
// ============================================================

function _drawTargets(ctx) {
    const units = TritiumStore.units;
    for (const [id, unit] of units) {
        _drawUnit(ctx, id, unit);
    }
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
    for (const [id, unit] of units) {
        const pos = unit.position;
        if (!pos || pos.x === undefined || pos.y === undefined) continue;
        entries.push({
            id,
            text: unit.name || id,
            worldX: pos.x,
            worldY: pos.y,
            alliance: (unit.alliance || 'unknown').toLowerCase(),
            status: (unit.status || 'active').toLowerCase(),
            isSelected: id === selectedId,
        });
    }

    const resolved = resolveLabels(entries, cssW, cssH, _state.cam.zoom, selectedId, worldToScreen);

    ctx.save();
    const fontSize = Math.max(9, 11 * Math.min(_state.cam.zoom, 2));
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
    }

    ctx.restore();
}

function _drawUnit(ctx, id, unit) {
    const pos = unit.position;
    if (!pos || pos.x === undefined || pos.y === undefined) return;

    const sp = worldToScreen(pos.x, pos.y);
    const alliance = (unit.alliance || 'unknown').toLowerCase();
    const color = ALLIANCE_COLORS[alliance] || ALLIANCE_COLORS.unknown;
    const type = (unit.type || '').toLowerCase();
    const status = (unit.status || 'active').toLowerCase();
    const isNeutralized = status === 'neutralized' || status === 'eliminated' || status === 'destroyed';
    const isSelected = TritiumStore.get('map.selectedUnitId') === id;
    const isHovered = _state.hoveredUnit === id;
    const baseSize = 6 * Math.min(_state.cam.zoom, 3);
    const size = isSelected ? baseSize * 1.3 : (isHovered ? baseSize * 1.15 : baseSize);

    // Fade neutralized targets
    if (isNeutralized) {
        ctx.globalAlpha = 0.4;
    }

    // Smooth heading interpolation (shared by both paths)
    const heading = unit.heading;
    let smoothedHeading = heading;
    if (heading !== undefined && heading !== null) {
        const prevHeading = _state.smoothHeadings.get(id);
        if (prevHeading !== undefined) {
            smoothedHeading = lerpAngle(prevHeading, heading, 10, _state.dt);
        }
        _state.smoothHeadings.set(id, smoothedHeading);
    }

    // Use war-combat.js rich shapes if available
    if (typeof warCombatDrawTargetShape === 'function') {
        const targetObj = {
            asset_type: unit.type || '',
            heading: smoothedHeading,
            status: unit.status || 'active',
            weapon_cooldown: unit.weapon_cooldown,
            weapon_range: unit.weapon_range,
            last_fired: unit.last_fired,
            kills: unit.kills,
            fov_angle: unit.fov_angle,
            fov_range: unit.fov_range,
        };
        warCombatDrawTargetShape(ctx, sp, size, targetObj, alliance, _state.cam.zoom);
        ctx.globalAlpha = 1.0;
    } else {
        // Fallback: basic shapes
        ctx.fillStyle = color;
        ctx.strokeStyle = color;

        switch (type) {
            case 'rover':
                _drawRoundedRect(ctx, sp.x, sp.y, size, color);
                break;
            case 'drone':
                _drawDiamond(ctx, sp.x, sp.y, size, color);
                break;
            case 'turret':
                _drawTriangle(ctx, sp.x, sp.y, size, color);
                break;
            case 'person':
                _drawCircle(ctx, sp.x, sp.y, size, color);
                break;
            case 'hostile_kid':
                _drawCircleWithX(ctx, sp.x, sp.y, size, color);
                break;
            case 'mesh_radio':
            case 'meshtastic':
                // Antenna icon in cyan
                ctx.strokeStyle = '#00f0ff';
                ctx.lineWidth = 2;
                ctx.beginPath();
                ctx.moveTo(sp.x, sp.y + size * 0.5);
                ctx.lineTo(sp.x, sp.y - size * 0.8);
                ctx.stroke();
                ctx.fillStyle = '#00f0ff';
                ctx.beginPath();
                ctx.arc(sp.x, sp.y - size * 0.8, 2, 0, Math.PI * 2);
                ctx.fill();
                break;
            default: {
                ctx.fillStyle = color;
                const half = size * 0.8;
                ctx.fillRect(sp.x - half, sp.y - half, half * 2, half * 2);
                break;
            }
        }

        // Heading arrow (fallback only — warCombatDrawTargetShape handles its own)
        if (heading !== undefined && heading !== null && !isNeutralized) {
            const rad = (90 - smoothedHeading) * Math.PI / 180;
            const lineLen = size * 2.2;
            ctx.strokeStyle = color;
            ctx.lineWidth = 2;
            ctx.beginPath();
            ctx.moveTo(sp.x, sp.y);
            ctx.lineTo(sp.x + Math.cos(rad) * lineLen, sp.y - Math.sin(rad) * lineLen);
            ctx.stroke();
        }

        // Neutralized X overlay
        if (isNeutralized) {
            const xSize = size * 1.2;
            ctx.strokeStyle = '#ff2a6d';
            ctx.lineWidth = 2;
            ctx.beginPath();
            ctx.moveTo(sp.x - xSize, sp.y - xSize);
            ctx.lineTo(sp.x + xSize, sp.y + xSize);
            ctx.moveTo(sp.x + xSize, sp.y - xSize);
            ctx.lineTo(sp.x - xSize, sp.y + xSize);
            ctx.stroke();
        }

        ctx.globalAlpha = 1.0;
    }

    // Health bar (only if health < maxHealth and unit has health data)
    if (unit.health !== undefined && unit.maxHealth && unit.health < unit.maxHealth && !isNeutralized) {
        _drawHealthBar(ctx, sp.x, sp.y, size, unit.health, unit.maxHealth);
    }

    // Labels are drawn by _drawLabels() using label-collision.js
}

// ============================================================
// Target shapes
// ============================================================

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
    const ctx = _state.minimapCtx;
    if (!ctx) {
        _drawMinimapOnMain();
        return;
    }
    const mmCanvas = _state.minimapCanvas;
    const mmRect = mmCanvas?.getBoundingClientRect();
    if (!mmRect || mmRect.width === 0 || mmRect.height === 0) {
        _drawMinimapOnMain();
        return;
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
        // Dispatch mode: click to send selected unit somewhere
        if (_state.dispatchMode && _state.dispatchUnitId) {
            const wp = screenToWorld(sx, sy);
            _doDispatch(_state.dispatchUnitId, wp.x, wp.y);
            _state.dispatchMode = false;
            _state.dispatchUnitId = null;
            _state.canvas.style.cursor = 'crosshair';
            return;
        }

        // Hit test units
        const hitId = _hitTestUnit(sx, sy);
        if (hitId) {
            TritiumStore.set('map.selectedUnitId', hitId);
            EventBus.emit('unit:selected', { id: hitId });
        } else {
            TritiumStore.set('map.selectedUnitId', null);
            EventBus.emit('unit:deselected', {});
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
        // If right-click and barely moved, treat as right-click dispatch
        if (e.button === 2 && _state.dragStart) {
            const dx = Math.abs(sx - _state.dragStart.x);
            const dy = Math.abs(sy - _state.dragStart.y);
            if (dx < 5 && dy < 5) {
                // Right-click dispatch for selected unit
                const selectedId = TritiumStore.get('map.selectedUnitId');
                if (selectedId) {
                    const wp = screenToWorld(sx, sy);
                    _doDispatch(selectedId, wp.x, wp.y);
                }
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

    const units = TritiumStore.units;
    for (const [id, unit] of units) {
        const pos = unit.position;
        if (!pos || pos.x === undefined) continue;
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

// ============================================================
// Dispatch
// ============================================================

function _doDispatch(unitId, wx, wy) {
    const unit = TritiumStore.units.get(unitId);
    if (unit && unit.position) {
        // Add visual dispatch arrow
        _state.dispatchArrows.push({
            fromX: unit.position.x,
            fromY: unit.position.y,
            toX: wx,
            toY: wy,
            time: Date.now(),
        });
    }

    EventBus.emit('unit:dispatched', { id: unitId, target: { x: wx, y: wy } });

    // Send dispatch command to backend
    fetch('/api/amy/command', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: 'dispatch', target_id: unitId, x: wx, y: wy }),
    }).catch(err => {
        console.error('[MAP] Dispatch failed:', err);
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

function _onSelectedUnitChanged(newId, _oldId) {
    // If a unit is selected, optionally center camera on it
    // (Only on explicit programmatic selection, not on every click)
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
        })
        .catch(err => {
            console.warn('[MAP] Geo reference fetch failed:', err);
            _state.noLocationSet = true;
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

    // Zoom level crossed threshold — debounce reload (300ms)
    clearTimeout(_state.satReloadTimer);
    _state.satReloadTimer = setTimeout(() => {
        const idx = _getSatTileLevelIndex();
        if (idx !== _state.satTileLevel) {
            _state.satTileLevel = idx;
            const [, tileZoom, radius] = SAT_TILE_LEVELS[idx];
            console.log(`[MAP] Reloading satellite tiles: zoom=${tileZoom}, radius=${radius}m`);
            _fetchTilesFromApi(_state.geoCenter.lat, _state.geoCenter.lng, radius, tileZoom);
        }
    }, 300);
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
 * Return current map state for menu checkmarks.
 */
export function getMapState() {
    return {
        showSatellite: _state.showSatellite,
        showRoads: _state.showRoads,
        showGrid: _state.showGrid,
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
